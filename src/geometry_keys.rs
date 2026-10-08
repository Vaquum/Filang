//! Immutable causal geometry features, with no outcomes or split assignments.
//!
//! `keys.bin` is little endian: magic `FGKEYS01` (8 bytes), context SHA256
//! (64 ASCII hex bytes), source CSV SHA256 (64 ASCII hex bytes), then four u64s:
//! source rows, interval seconds, bars, record count. The 168-byte header is
//! followed by 40-byte records: original zero-based CSV data-row index and four
//! GeometryKey words. A final 64-byte ASCII SHA256 seals every preceding byte.
//! Keys use current-first candles. All window candles must lie in the requested
//! history and be consecutive. The final source rows are eligible without any
//! future target. `manifest.sha256` commits the complete artifact bundle.
use crate::{
    data::date,
    dense_io::{self, Lock, Writer},
    direction::DirectionData,
    geometry::{GeometryEncoder, GeometryMode},
    hash::{file_sha256, sha256},
    report::quote,
    Result,
};
use std::{
    fs::{self, File},
    io::{Read, Write},
    path::Path,
    time::Instant,
};

pub const HEADER_BYTES: usize = 168;
pub const RECORD_BYTES: usize = 40;
pub const MAGIC: &[u8; 8] = b"FGKEYS01";
const FORMAT: &str = "geometry-keys-v1";
const MIB: usize = 1024 * 1024;

#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub out: String,
    pub interval_seconds: i64,
    pub history_start: String,
    pub end: String,
    pub bars: usize,
    pub memory_mib: usize,
    pub max_rows: usize,
    pub resume: bool,
}

impl Config {
    fn validate(&self) -> Result<[i64; 2]> {
        if self.interval_seconds <= 0 || !(2..=10).contains(&self.bars) {
            return Err("geometry keys require a positive interval and bars in 2..=10".into());
        }
        if self.memory_mib < 16 || self.memory_mib.checked_mul(MIB).is_none() {
            return Err("geometry key memory_mib must be at least 16 and fit usize".into());
        }
        if self.max_rows < self.bars || self.max_rows > u32::MAX as usize {
            return Err(
                "geometry key max_rows must be at least bars and at most 4294967295".into(),
            );
        }
        let bounds = [date(&self.history_start)?, date(&self.end)?];
        if bounds[0] >= bounds[1]
            || bounds
                .iter()
                .any(|t| t.rem_euclid(self.interval_seconds) != 0)
        {
            return Err(
                "geometry key dates must increase and align with the UTC interval grid".into(),
            );
        }
        Ok(bounds)
    }
}

fn plain(path: &Path) -> Result<Vec<u8>> {
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > 65_536 {
        return Err("geometry key metadata exceeds 65536 bytes".into());
    }
    fs::read(path).map_err(|e| e.to_string())
}

fn atomic_text(path: &Path, text: &str) -> Result<()> {
    let temp = path.with_extension("pending");
    let mut file = File::create(&temp).map_err(|e| e.to_string())?;
    file.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    fs::rename(&temp, path).map_err(|e| e.to_string())?;
    File::open(path.parent().ok_or("geometry artifact parent")?)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())
}

struct Identity<'a> {
    config: &'a Config,
    data: &'a DirectionData,
    context: &'a str,
    first: usize,
    end: usize,
    records: usize,
    warmup: usize,
}

impl Identity<'_> {
    fn header(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(HEADER_BYTES);
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(self.context.as_bytes());
        bytes.extend_from_slice(self.data.digest.as_bytes());
        for n in [
            self.data.len() as u64,
            self.config.interval_seconds as u64,
            self.config.bars as u64,
            self.records as u64,
        ] {
            bytes.extend_from_slice(&n.to_le_bytes());
        }
        bytes
    }

    fn payload_bytes(&self) -> u64 {
        HEADER_BYTES as u64 + self.records as u64 * RECORD_BYTES as u64
    }

    fn manifest(&self, payload_sha: &str, file_sha: &str, timing_sha: &str) -> String {
        format!(
            "{{\"format\":{},\"status\":\"COMPLETE\",\"context_sha256\":{},\"source_sha256\":{},\"source_bytes\":{},\"source_rows\":{},\"selected_first_index\":{},\"selected_end_index_exclusive\":{},\"selected_rows\":{},\"initial_warmup_rows\":{},\"gap_window_skips\":{},\"source_gap_count\":{},\"source_missing_grid_bars\":{},\"bars\":{},\"mode\":\"oriented\",\"records\":{},\"header_bytes\":{},\"record_bytes\":{},\"keys_file\":\"keys.bin\",\"keys_payload_bytes\":{},\"keys_payload_sha256\":{},\"keys_file_bytes\":{},\"keys_file_sha256\":{},\"timings_sha256\":{}}}\n",
            quote(FORMAT), quote(self.context), quote(&self.data.digest),
            self.data.source_bytes, self.data.len(), self.first, self.end, self.end-self.first,
            self.warmup, self.end-self.first-self.warmup-self.records,
            self.data.gap_count, self.data.missing_grid_bars, self.config.bars, self.records,
            HEADER_BYTES, RECORD_BYTES, self.payload_bytes(), quote(payload_sha),
            self.payload_bytes()+64, quote(file_sha), quote(timing_sha),
        )
    }

    fn verify_keys(&self, path: &Path) -> Result<(String, String)> {
        let (payload_sha, bytes) = dense_io::verify(path)?;
        if bytes != self.payload_bytes() {
            return Err("geometry key payload length does not match eligible records".into());
        }
        let mut header = [0u8; HEADER_BYTES];
        File::open(path)
            .and_then(|mut f| f.read_exact(&mut header))
            .map_err(|e| e.to_string())?;
        if header.as_slice() != self.header().as_slice() {
            return Err("geometry key header/context mismatch".into());
        }
        Ok((payload_sha, file_sha256(path)?))
    }
}

/// Export historical features once. Completed resumes verify all evidence and
/// preserve original operational timings. Interrupted exports restart under the
/// directory lock; there is no partially committed record prefix to consume.
pub fn run(config: Config) -> Result<String> {
    let began = Instant::now();
    let bounds = config.validate()?;
    let data_path = fs::canonicalize(&config.data).map_err(|e| e.to_string())?;
    let data = DirectionData::read(
        &data_path,
        config.interval_seconds,
        config.max_rows,
        config.memory_mib * MIB,
    )?;
    let read_seconds = began.elapsed().as_secs_f64();
    let first = data.index(bounds[0]);
    let end = data.index(bounds[1]);
    if data.timestamps[0] > bounds[0]
        || data.timestamps[data.len() - 1]
            .checked_add(config.interval_seconds)
            .ok_or("geometry key final timestamp overflow")?
            < bounds[1]
    {
        return Err("geometry key source must span history_start through end (exclusive)".into());
    }
    if end - first < config.bars {
        return Err("geometry key selected history is shorter than bars".into());
    }
    let warmup = config.bars - 1;
    let eligible = |t: &usize| data.consecutive[*t] as usize >= config.bars;
    let records = (first + warmup..end).filter(eligible).count();
    if records == 0 {
        return Err("geometry key history has no complete consecutive windows".into());
    }
    let engine_sha = file_sha256(std::env::current_exe().map_err(|e| e.to_string())?)?;
    let canonical = format!(
        "{{\"format\":{},\"source_sha256\":{},\"engine_sha256\":{},\"interval_seconds\":{},\"history_start\":{},\"end\":{},\"bars\":{},\"mode\":\"oriented\",\"key_layout\":\"geometry-key-256-v1\",\"eligibility\":\"all_window_rows_in_history_consecutive_past_only\"}}\n",
        quote(FORMAT), quote(&data.digest), quote(&engine_sha), config.interval_seconds,
        quote(&config.history_start), quote(&config.end), config.bars,
    );
    let context = sha256(canonical.as_bytes());
    let identity = Identity {
        config: &config,
        data: &data,
        context: &context,
        first,
        end,
        records,
        warmup,
    };
    let out = Path::new(&config.out);
    fs::create_dir_all(out).map_err(|e| e.to_string())?;
    let _lock = Lock::acquire(out)?;
    let allowed = [
        ".writer.lock",
        "context.json",
        "context.pending",
        "keys.bin",
        "keys.pending",
        "timings.json",
        "timings.pending",
        "manifest.json",
        "manifest.sha256",
        "manifest.pending",
    ];
    for entry in fs::read_dir(out).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        if !allowed.iter().any(|n| name == *n)
            || !entry.file_type().map_err(|e| e.to_string())?.is_file()
        {
            return Err(format!(
                "unexpected geometry key output entry: {}",
                entry.path().display()
            ));
        }
    }
    let context_path = out.join("context.json");
    if context_path.exists() {
        if !config.resume {
            return Err("geometry key output exists; use --resume true to verify it".into());
        }
        if plain(&context_path)? != canonical.as_bytes() {
            return Err("geometry key resume context/source/executable mismatch".into());
        }
    } else {
        // A context is the ownership marker. Never remove orphaned artifacts.
        for name in [
            "keys.bin",
            "keys.pending",
            "timings.json",
            "timings.pending",
            "manifest.json",
            "manifest.sha256",
            "manifest.pending",
        ] {
            if out.join(name).exists() {
                return Err(
                    "geometry key output has artifacts without an ownership context".into(),
                );
            }
        }
        atomic_text(&context_path, &canonical)?;
    }
    let manifest_path = out.join("manifest.json");
    let seal_path = out.join("manifest.sha256");
    let keys_path = out.join("keys.bin");
    let timing_path = out.join("timings.json");
    if seal_path.exists() {
        let manifest = plain(&manifest_path)?;
        if plain(&seal_path)? != format!("{}\n", sha256(&manifest)).as_bytes() {
            return Err("geometry key manifest checksum mismatch".into());
        }
        let (payload_sha, file_sha) = identity.verify_keys(&keys_path)?;
        let timing_sha = sha256(&plain(&timing_path)?);
        let expected = identity.manifest(&payload_sha, &file_sha, &timing_sha);
        if manifest != expected.as_bytes() {
            return Err("geometry key manifest/artifact mismatch".into());
        }
        return Ok(expected);
    }
    // A matching ownership context permits replacing only this export's
    // incomplete artifacts. Complete bundles above are immutable.
    for name in [
        "keys.bin",
        "keys.pending",
        "timings.json",
        "timings.pending",
        "manifest.json",
        "manifest.pending",
        "context.pending",
    ] {
        let path = out.join(name);
        if path.exists() {
            fs::remove_file(path).map_err(|e| e.to_string())?;
        }
    }
    let encoding_began = Instant::now();
    let mut writer = Writer::new(&keys_path)?;
    writer.write(&identity.header())?;
    let mut encoder = GeometryEncoder::new(config.bars, GeometryMode::Oriented)?;
    let mut rows = [[0.0; 4]; 10];
    let mut written = 0usize;
    for t in (first + warmup..end).filter(eligible) {
        for (lag, row) in rows[..config.bars].iter_mut().enumerate() {
            for (column, value) in row.iter_mut().enumerate() {
                *value = data.columns[column][t - lag];
            }
        }
        let key = encoder.encode_key_ohlc(&rows[..config.bars])?;
        let mut record = [0u8; RECORD_BYTES];
        record[..8].copy_from_slice(&(t as u64).to_le_bytes());
        for (i, word) in key.words().iter().enumerate() {
            record[8 + i * 8..16 + i * 8].copy_from_slice(&word.to_le_bytes());
        }
        writer.write(&record)?;
        written += 1;
    }
    if written != records || writer.bytes != identity.payload_bytes() {
        return Err("geometry key export count/byte mismatch".into());
    }
    let payload_sha = writer.finish()?;
    let encode_write_seconds = encoding_began.elapsed().as_secs_f64();
    let file_sha = file_sha256(&keys_path)?;
    let timings = format!(
        "{{\"format\":{},\"source_read_validate_hash_seconds\":{:.9},\"encode_write_seal_seconds\":{:.9},\"elapsed_before_metadata_seconds\":{:.9},\"records\":{},\"memory_mib_limit\":{},\"max_rows_limit\":{},\"measurement\":\"operational_wall_clock_not_a_benchmark\"}}\n",
        quote(FORMAT), read_seconds, encode_write_seconds, began.elapsed().as_secs_f64(),
        records, config.memory_mib, config.max_rows,
    );
    atomic_text(&timing_path, &timings)?;
    let manifest = identity.manifest(&payload_sha, &file_sha, &sha256(timings.as_bytes()));
    atomic_text(&manifest_path, &manifest)?;
    atomic_text(&seal_path, &format!("{}\n", sha256(manifest.as_bytes())))?;
    Ok(manifest)
}
