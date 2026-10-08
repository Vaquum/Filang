//! Exact grouped next-bar direction experiments over complete candle geometry.
//!
//! Each eligible historical window belongs to one canonical geometry identity.
//! Updating its sufficient statistics is the exact sparse execution of the full
//! pattern universe; every unobserved identity has a zero count. No pattern by
//! timeline masks or enumeration of the astronomical complement are needed.
//! The fixed key and canonical language are shared with the geometry sweep.
use crate::{
    data::date,
    geometry::{
        count_domain_decimal, count_domain_unobserved_decimal, GeometryEncoder, GeometryKey,
        GeometryMode,
    },
    hash::{file_sha256, sha256, Sha256},
    report::quote,
    Result,
};
use std::{
    collections::{hash_map::Entry, HashMap},
    fmt::Write as _,
    fs::{self, File, OpenOptions},
    hash::{BuildHasherDefault, Hasher},
    io::{BufRead, BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Instant,
};

const FORMAT: &str = "geometry-direction-v1";
const BUFFER_BYTES: usize = 262_144;
const MIB: usize = 1024 * 1024;
pub const EVENT_HEADER: &str = "decision_timestamp\ttarget_timestamp\tsplit\tpattern_id\ttarget_cc\ttarget_body\tcurrent_cc\tcurrent_body\n";
pub const PATTERN_HEADER: &str = "pattern_id\tpattern\ttrain_cc_down\ttrain_cc_flat\ttrain_cc_up\ttrain_body_down\ttrain_body_flat\ttrain_body_up\tvalidation_cc_down\tvalidation_cc_flat\tvalidation_cc_up\tvalidation_body_down\tvalidation_body_flat\tvalidation_body_up\ttest_cc_down\ttest_cc_flat\ttest_cc_up\ttest_body_down\ttest_body_flat\ttest_body_up\n";
const SPLITS: [&str; 3] = ["train", "validation", "test"];

#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub out: String,
    pub interval_seconds: i64,
    pub history_start: String,
    pub validation_start: String,
    pub test_start: String,
    pub end: String,
    pub bars: Vec<usize>,
    pub modes: Vec<GeometryMode>,
    pub workers: usize,
    pub memory_mib: usize,
    pub max_rows: usize,
    pub resume: bool,
    pub max_tasks: usize,
}

impl Config {
    fn validate(&mut self) -> Result<[i64; 4]> {
        if self.interval_seconds <= 0 {
            return Err("direction interval_seconds must be positive".into());
        }
        if !(1..=1024).contains(&self.workers) {
            return Err("direction workers must be in 1..=1024".into());
        }
        if self.memory_mib < 16 || self.memory_mib.checked_mul(MIB).is_none() {
            return Err("direction memory_mib must be at least 16 and fit usize".into());
        }
        if self.max_rows < 4 || self.max_rows > u32::MAX as usize {
            return Err("direction max_rows must be in 4..=4294967295".into());
        }
        if self.bars.is_empty() || self.bars.iter().any(|n| !(2..=10).contains(n)) {
            return Err("direction bars must be a nonempty list in 2..=10".into());
        }
        self.bars.sort_unstable();
        if self.bars.windows(2).any(|v| v[0] == v[1]) {
            return Err("direction bars contain a duplicate".into());
        }
        if self.modes.is_empty() {
            return Err("direction modes cannot be empty".into());
        }
        self.modes.sort_unstable();
        if self.modes.windows(2).any(|v| v[0] == v[1]) {
            return Err("direction modes contain a duplicate".into());
        }
        let bounds = [
            date(&self.history_start)?,
            date(&self.validation_start)?,
            date(&self.test_start)?,
            date(&self.end)?,
        ];
        if bounds.windows(2).any(|v| v[0] >= v[1]) {
            return Err(
                "direction dates must satisfy history_start < validation_start < test_start < end"
                    .into(),
            );
        }
        if bounds
            .iter()
            .any(|t| t.rem_euclid(self.interval_seconds) != 0)
        {
            return Err("direction date boundaries must align with the UTC interval grid".into());
        }
        Ok(bounds)
    }
}

/// Private input type: unlike the backtest Data contract, this reader retains
/// explicit missing bars. A consecutive-run counter makes gap validation O(1).
struct DirectionData {
    timestamps: Vec<i64>,
    columns: [Vec<f64>; 4],
    consecutive: Vec<u32>,
    digest: String,
    source_bytes: u64,
    gap_count: u64,
    missing_grid_bars: u64,
}

impl DirectionData {
    fn len(&self) -> usize {
        self.timestamps.len()
    }

    fn index(&self, timestamp: i64) -> usize {
        self.timestamps.partition_point(|v| *v < timestamp)
    }

    fn reserve_row(&mut self, max_rows: usize, memory_bytes: usize) -> Result<()> {
        if self.len() >= max_rows {
            return Err(format!("direction input exceeds max_rows={max_rows}"));
        }
        if self.len() == self.timestamps.capacity() {
            let additional = 4096.min(max_rows - self.len());
            let capacity = self.len() + additional;
            // Includes all input vectors, allocator slack, parsing buffers and
            // a reserve for at least one worker; checked before allocation.
            let estimate = capacity
                .checked_mul(64)
                .and_then(|v| v.checked_add(8 * MIB))
                .ok_or("direction input memory estimate overflow")?;
            if estimate > memory_bytes {
                return Err("direction input exceeds memory_mib before allocation".into());
            }
            self.timestamps
                .try_reserve_exact(additional)
                .map_err(|_| "direction timestamp allocation failed")?;
            self.consecutive
                .try_reserve_exact(additional)
                .map_err(|_| "direction gap index allocation failed")?;
            for column in &mut self.columns {
                column
                    .try_reserve_exact(additional)
                    .map_err(|_| "direction OHLC allocation failed")?;
            }
        }
        Ok(())
    }

    fn read(path: &Path, config: &Config) -> Result<Self> {
        let file = File::open(path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let mut reader = BufReader::with_capacity(BUFFER_BYTES, file);
        let mut line = String::with_capacity(256);
        let mut digest = Sha256::default();
        let mut bytes = 0u64;
        let mut out = Self {
            timestamps: Vec::new(),
            columns: std::array::from_fn(|_| Vec::new()),
            consecutive: Vec::new(),
            digest: String::new(),
            source_bytes: 0,
            gap_count: 0,
            missing_grid_bars: 0,
        };
        let mut line_number = 0usize;
        loop {
            line.clear();
            // Limit one row too: malformed input must not grow an unbounded
            // String before the row/memory guards can run.
            let n = reader
                .by_ref()
                .take(4097)
                .read_line(&mut line)
                .map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            if n > 4096 {
                return Err("direction CSV row exceeds 4096 bytes".into());
            }
            digest.update(line.as_bytes());
            bytes = bytes.checked_add(n as u64).ok_or("input byte overflow")?;
            line_number += 1;
            let row = line.trim_end_matches(&['\r', '\n'][..]);
            if line_number == 1 {
                if row != "timestamp,open,high,low,close,volume" {
                    return Err("CSV header must be timestamp,open,high,low,close,volume".into());
                }
                continue;
            }
            let mut fields = row.split(',');
            let timestamp = fields
                .next()
                .ok_or("direction missing timestamp")?
                .parse::<i64>()
                .map_err(|_| format!("invalid timestamp line {line_number}"))?;
            if timestamp.rem_euclid(config.interval_seconds) != 0 {
                return Err(format!("off-grid timestamp line {line_number}"));
            }
            let mut values = [0.0f64; 5];
            for value in &mut values {
                *value = fields
                    .next()
                    .ok_or_else(|| format!("expected six CSV fields line {line_number}"))?
                    .parse()
                    .map_err(|_| format!("invalid numeric field line {line_number}"))?;
            }
            if fields.next().is_some() {
                return Err(format!("expected six CSV fields line {line_number}"));
            }
            if values.iter().any(|v| !v.is_finite())
                || values[..4].iter().any(|v| *v <= 0.0)
                || values[4] < 0.0
                || values[1] < values[0].max(values[3])
                || values[2] > values[0].min(values[3])
                || values[1] < values[2]
            {
                return Err(format!("invalid OHLCV line {line_number}"));
            }
            let run = if let Some(last) = out.timestamps.last() {
                let delta = timestamp
                    .checked_sub(*last)
                    .ok_or("direction timestamp delta overflow")?;
                if delta <= 0 {
                    return Err(format!(
                        "duplicate/out-of-order timestamp line {line_number}"
                    ));
                }
                if delta == config.interval_seconds {
                    out.consecutive
                        .last()
                        .copied()
                        .unwrap_or(0)
                        .checked_add(1)
                        .ok_or("direction consecutive run exceeds u32")?
                } else {
                    out.gap_count += 1;
                    out.missing_grid_bars = out
                        .missing_grid_bars
                        .checked_add((delta / config.interval_seconds - 1) as u64)
                        .ok_or("direction missing grid count overflow")?;
                    1
                }
            } else {
                1
            };
            out.reserve_row(config.max_rows, config.memory_mib * MIB)?;
            out.timestamps.push(timestamp);
            out.consecutive.push(run);
            for (column, value) in out.columns.iter_mut().zip(values) {
                column.push(value);
            }
        }
        if out.len() < 4 {
            return Err("direction experiment requires at least four bars".into());
        }
        out.digest = digest.finish();
        out.source_bytes = bytes;
        Ok(out)
    }
}

/// Fixed, noncryptographic hashing reduces lookup overhead. Full 256-bit keys
/// are still compared by HashMap; hash collisions never merge identities.
struct KeyHasher(u64);
impl Default for KeyHasher {
    fn default() -> Self {
        Self(0x243f6a8885a308d3)
    }
}
impl Hasher for KeyHasher {
    fn finish(&self) -> u64 {
        let mut value = self.0;
        value ^= value >> 30;
        value = value.wrapping_mul(0xbf58476d1ce4e5b9);
        value ^= value >> 27;
        value = value.wrapping_mul(0x94d049bb133111eb);
        value ^ (value >> 31)
    }
    fn write_u64(&mut self, value: u64) {
        self.0 = (self.0 ^ value.wrapping_mul(0x9e3779b97f4a7c15))
            .rotate_left(27)
            .wrapping_mul(0xc2b2ae3d27d4eb4f);
    }
    fn write(&mut self, bytes: &[u8]) {
        for chunk in bytes.chunks(8) {
            let mut word = [0u8; 8];
            word[..chunk.len()].copy_from_slice(chunk);
            self.write_u64(u64::from_le_bytes(word));
        }
    }
}

struct PatternCounts {
    key: GeometryKey,
    // max_rows is limited to u32::MAX; no pattern can exceed that count.
    counts: [u32; 18],
}

#[derive(Clone, Copy)]
struct Task {
    bars: usize,
    mode: GeometryMode,
}
impl Task {
    fn id(self) -> String {
        format!("n{:02}-{}", self.bars, self.mode)
    }
}

struct Source {
    config: Config,
    bounds: [i64; 4],
    data: DirectionData,
    data_path: String,
    engine_sha256: String,
    identity: String,
    first: usize,
    end: usize,
}

impl Source {
    fn metadata(&self) -> String {
        format!(
            "\"format\":{},\"source_csv\":{},\"source_sha256\":{},\"source_bytes\":{},\"engine_sha256\":{},\"interval_seconds\":{},\"history_start\":{},\"validation_start\":{},\"test_start\":{},\"end\":{},\"input_rows\":{},\"selected_rows\":{},\"first_timestamp\":{},\"last_timestamp\":{},\"gap_count\":{},\"missing_grid_bars\":{},\"context_sha256\":{}",
            quote(FORMAT), quote(&self.data_path), quote(&self.data.digest),
            self.data.source_bytes, quote(&self.engine_sha256), self.config.interval_seconds,
            quote(&self.config.history_start), quote(&self.config.validation_start),
            quote(&self.config.test_start), quote(&self.config.end), self.data.len(),
            self.end - self.first, self.data.timestamps[0],
            self.data.timestamps[self.data.len() - 1], self.data.gap_count,
            self.data.missing_grid_bars, quote(&self.identity),
        )
    }
}

struct DigestWriter {
    file: File,
    hash: Sha256,
    bytes: u64,
}
impl Write for DigestWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let n = self.file.write(bytes)?;
        self.hash.update(&bytes[..n]);
        self.bytes += n as u64;
        Ok(n)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.file.flush()
    }
}

struct Artifact {
    name: &'static str,
    bytes: u64,
    digest: String,
}

fn writer(path: &Path) -> Result<BufWriter<DigestWriter>> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| format!("create {}: {e}", path.display()))?;
    Ok(BufWriter::with_capacity(
        BUFFER_BYTES,
        DigestWriter {
            file,
            hash: Sha256::default(),
            bytes: 0,
        },
    ))
}

fn finish_writer(mut writer: BufWriter<DigestWriter>, name: &'static str) -> Result<Artifact> {
    writer.flush().map_err(|e| e.to_string())?;
    let writer = writer.into_inner().map_err(|e| e.to_string())?;
    writer.file.sync_all().map_err(|e| e.to_string())?;
    Ok(Artifact {
        name,
        bytes: writer.bytes,
        digest: writer.hash.finish(),
    })
}

fn text_artifact(dir: &Path, name: &'static str, text: &str) -> Result<Artifact> {
    let mut output = writer(&dir.join(name))?;
    output
        .write_all(text.as_bytes())
        .map_err(|e| e.to_string())?;
    finish_writer(output, name)
}

fn atomic_text(path: &Path, text: &str) -> Result<()> {
    let temporary = path.with_extension("pending");
    let mut output = File::create(&temporary).map_err(|e| e.to_string())?;
    output
        .write_all(text.as_bytes())
        .map_err(|e| e.to_string())?;
    output.sync_all().map_err(|e| e.to_string())?;
    fs::rename(&temporary, path).map_err(|e| e.to_string())
}

fn sign(a: f64, b: f64) -> i8 {
    if a < b {
        -1
    } else if a > b {
        1
    } else {
        0
    }
}

fn count_json(counts: &[u64; 18]) -> String {
    let mut splits = Vec::with_capacity(3);
    for (split, name) in SPLITS.iter().enumerate() {
        let i = split * 6;
        splits.push(format!(
            "{}:{{\"cc\":{{\"down\":{},\"flat\":{},\"up\":{}}},\"body\":{{\"down\":{},\"flat\":{},\"up\":{}}}}}",
            quote(name), counts[i], counts[i+1], counts[i+2], counts[i+3], counts[i+4], counts[i+5]
        ));
    }
    format!("{{{}}}", splits.join(","))
}

fn task_identity(source: &Source, task: Task) -> String {
    format!("{}\n{}\n{}\n", source.identity, task.bars, task.mode)
}

fn execute_task(source: &Source, task: Task, task_root: &Path) -> Result<()> {
    let began = Instant::now();
    let id = task.id();
    let staging = task_root.join(format!(".{id}.partial"));
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| e.to_string())?;
    }
    fs::create_dir(&staging).map_err(|e| e.to_string())?;
    let start = source.first + task.bars - 1;
    let stop = source.end.saturating_sub(1);
    let candidates = stop.saturating_sub(start);
    let universe = count_domain_decimal(task.bars, task.mode)?;
    let capacity = universe
        .parse::<usize>()
        .unwrap_or(candidates)
        .min(candidates);
    let mut lookup: HashMap<GeometryKey, u32, BuildHasherDefault<KeyHasher>> =
        HashMap::with_hasher(BuildHasherDefault::default());
    lookup
        .try_reserve(capacity)
        .map_err(|_| "direction key table allocation failed")?;
    let mut patterns = Vec::<PatternCounts>::new();
    patterns
        .try_reserve_exact(capacity)
        .map_err(|_| "direction count allocation failed")?;
    let mut encoder = GeometryEncoder::new(task.bars, task.mode)?;
    let mut rows = [[0.0f64; 4]; 10];
    let mut counts = [0u64; 18];
    let mut gap_purged = 0u64;
    let mut boundary_purged = 0u64;
    let mut events = 0u64;
    let mut output = writer(&staging.join("events.tsv"))?;
    output
        .write_all(EVENT_HEADER.as_bytes())
        .map_err(|e| e.to_string())?;
    let data = &source.data;
    for t in start..stop {
        if data.consecutive[t + 1] < (task.bars + 1) as u32 {
            gap_purged += 1;
            continue;
        }
        let timestamp = data.timestamps[t];
        let target_timestamp = data.timestamps[t + 1];
        let split = if timestamp < source.bounds[1] {
            0
        } else if timestamp < source.bounds[2] {
            1
        } else {
            2
        };
        let split_end = source.bounds[split + 1];
        if target_timestamp >= split_end
            || target_timestamp + source.config.interval_seconds > split_end
        {
            boundary_purged += 1;
            continue;
        }
        for (lag, row) in rows[..task.bars].iter_mut().enumerate() {
            let index = t - lag;
            for (value, column) in row.iter_mut().zip(&data.columns) {
                *value = column[index];
            }
        }
        let key = encoder.encode_key_ohlc(&rows[..task.bars])?;
        let pattern_id = match lookup.entry(key) {
            Entry::Occupied(entry) => *entry.get(),
            Entry::Vacant(entry) => {
                let index = patterns.len() as u32;
                patterns.push(PatternCounts {
                    key,
                    counts: [0; 18],
                });
                entry.insert(index);
                index
            }
        };
        let target_cc = sign(data.columns[3][t + 1], data.columns[3][t]);
        let target_body = sign(data.columns[3][t + 1], data.columns[0][t + 1]);
        let current_cc = sign(data.columns[3][t], data.columns[3][t - 1]);
        let current_body = sign(data.columns[3][t], data.columns[0][t]);
        let offset = split * 6;
        for (target, direction) in [target_cc, target_body].iter().enumerate() {
            let position = offset + target * 3 + (*direction + 1) as usize;
            patterns[pattern_id as usize].counts[position] += 1;
            counts[position] += 1;
        }
        writeln!(
            output,
            "{timestamp}\t{target_timestamp}\t{}\t{pattern_id}\t{target_cc}\t{target_body}\t{current_cc}\t{current_body}",
            SPLITS[split]
        )
        .map_err(|e| e.to_string())?;
        events += 1;
    }
    let event_artifact = finish_writer(output, "events.tsv")?;
    // The key table is no longer needed while potentially large catalogues
    // are serialized. Keep only fixed keys and their sufficient statistics.
    drop(lookup);
    let encode_seconds = began.elapsed().as_secs_f64();
    let mut output = writer(&staging.join("patterns.tsv"))?;
    output
        .write_all(PATTERN_HEADER.as_bytes())
        .map_err(|e| e.to_string())?;
    let mut training_observed = 0usize;
    for (id, pattern) in patterns.iter().enumerate() {
        if pattern.counts[..6].iter().any(|count| *count > 0) {
            training_observed += 1;
        }
        write!(output, "{id}\t{}", pattern.key).map_err(|e| e.to_string())?;
        for count in pattern.counts {
            write!(output, "\t{count}").map_err(|e| e.to_string())?;
        }
        writeln!(output).map_err(|e| e.to_string())?;
    }
    let pattern_artifact = finish_writer(output, "patterns.tsv")?;
    let summary = format!(
        "{{\"version\":1,\"status\":\"COMPLETE\",{},\"task\":{},\"bars\":{},\"mode\":{},\"window_order\":\"current_first_contiguous\",\"label_lag\":1,\"decision_timestamp_semantics\":\"candle_open_known_at_open_plus_interval\",\"target_cc\":\"sign(close[t+1]-close[t])\",\"target_body\":\"sign(close[t+1]-open[t+1])\",\"universe_patterns\":{},\"observed_patterns\":{},\"unobserved_patterns\":{},\"training_observed_patterns\":{},\"training_unobserved_patterns\":{},\"candidate_decisions\":{},\"gap_purged\":{},\"boundary_purged\":{},\"events\":{},\"split_counts\":{}}}\n",
        source.metadata(), quote(&id), task.bars, quote(&task.mode.to_string()), quote(&universe),
        patterns.len(), quote(&count_domain_unobserved_decimal(task.bars, task.mode, patterns.len())?),
        training_observed, quote(&count_domain_unobserved_decimal(task.bars, task.mode, training_observed)?),
        candidates, gap_purged, boundary_purged, events, count_json(&counts)
    );
    let summary_artifact = text_artifact(&staging, "summary.json", &summary)?;
    let identity_artifact = text_artifact(&staging, "task.identity", &task_identity(source, task))?;
    let elapsed = began.elapsed().as_secs_f64();
    let timing_artifact = text_artifact(
        &staging,
        "timing.json",
        &format!(
            "{{\"encode_events_seconds\":{encode_seconds:.9},\"task_seconds\":{elapsed:.9}}}\n"
        ),
    )?;
    let mut artifacts = String::from("file\tbytes\tsha256\n");
    for artifact in [
        event_artifact,
        pattern_artifact,
        summary_artifact,
        identity_artifact,
        timing_artifact,
    ] {
        writeln!(
            artifacts,
            "{}\t{}\t{}",
            artifact.name, artifact.bytes, artifact.digest
        )
        .expect("String writes are infallible");
    }
    text_artifact(&staging, "artifacts.tsv", &artifacts)?;
    text_artifact(
        &staging,
        "artifacts.tsv.sha256",
        &format!("{}\n", sha256(artifacts.as_bytes())),
    )?;
    fs::rename(staging, task_root.join(&id)).map_err(|e| e.to_string())?;
    Ok(())
}

fn verify_task(source: &Source, task: Task, task_root: &Path) -> Result<bool> {
    let directory = task_root.join(task.id());
    if !directory.exists() {
        return Ok(false);
    }
    let identity = fs::read_to_string(directory.join("task.identity"))
        .map_err(|e| format!("direction checkpoint identity: {e}"))?;
    if identity != task_identity(source, task) {
        return Err(format!(
            "direction checkpoint context mismatch: {}",
            task.id()
        ));
    }
    let text = fs::read_to_string(directory.join("artifacts.tsv"))
        .map_err(|e| format!("direction checkpoint manifest: {e}"))?;
    let seal = fs::read_to_string(directory.join("artifacts.tsv.sha256"))
        .map_err(|e| format!("direction checkpoint seal: {e}"))?;
    if sha256(text.as_bytes()) != seal.trim() {
        return Err(format!(
            "direction checkpoint manifest checksum: {}",
            task.id()
        ));
    }
    let mut rows = text.lines();
    if rows.next() != Some("file\tbytes\tsha256") {
        return Err("direction checkpoint manifest header".into());
    }
    for expected in [
        "events.tsv",
        "patterns.tsv",
        "summary.json",
        "task.identity",
        "timing.json",
    ] {
        let fields: Vec<_> = rows
            .next()
            .ok_or("direction truncated artifact manifest")?
            .split('\t')
            .collect();
        if fields.len() != 3 || fields[0] != expected {
            return Err("direction checkpoint manifest fields/order".into());
        }
        let bytes: u64 = fields[1].parse().map_err(|_| "direction artifact size")?;
        let path = directory.join(expected);
        if fs::metadata(&path).map_err(|e| e.to_string())?.len() != bytes
            || file_sha256(&path)? != fields[2]
        {
            return Err(format!(
                "direction artifact checksum mismatch: {}",
                path.display()
            ));
        }
    }
    if rows.next().is_some() {
        return Err("direction checkpoint manifest extra fields".into());
    }
    Ok(true)
}

/// Run a fixed collection of full-domain pattern mappings. Worker changes are
/// allowed on resume; semantic context, the input bytes, executable, and every
/// completed task's artifacts must match first.
pub fn run(mut config: Config) -> Result<String> {
    let began = Instant::now();
    let bounds = config.validate()?;
    let data_path = fs::canonicalize(&config.data).map_err(|e| e.to_string())?;
    let data_path = data_path
        .to_str()
        .ok_or("direction input path must be UTF-8")?
        .to_owned();
    let data = DirectionData::read(Path::new(&data_path), &config)?;
    let first = data.index(bounds[0]);
    let end = data.index(bounds[3]);
    if first == end || end - first <= *config.bars.last().unwrap() {
        return Err(
            "direction selected history is shorter than the largest window and target".into(),
        );
    }
    // Missing bars at a boundary are legal gaps. The supplied source still
    // needs to span all requested phases; no silent shorter test period.
    if data.timestamps[0] > bounds[0]
        || data.timestamps[data.len() - 1]
            .checked_add(config.interval_seconds)
            .ok_or("direction final timestamp overflow")?
            < bounds[3]
    {
        return Err("direction source must span history_start through end (exclusive)".into());
    }
    for split in 0..3 {
        if data.index(bounds[split + 1]) == data.index(bounds[split]) {
            return Err(format!(
                "direction {} split contains no real bars",
                SPLITS[split]
            ));
        }
    }
    let engine_sha256 = file_sha256(std::env::current_exe().map_err(|e| e.to_string())?)?;
    let canonical = format!(
        "{{\"format\":{},\"source_sha256\":{},\"engine_sha256\":{},\"interval_seconds\":{},\"history_start\":{},\"validation_start\":{},\"test_start\":{},\"end\":{},\"bars\":[{}],\"modes\":[{}]}}\n",
        quote(FORMAT), quote(&data.digest), quote(&engine_sha256), config.interval_seconds,
        quote(&config.history_start), quote(&config.validation_start), quote(&config.test_start),
        quote(&config.end), config.bars.iter().map(usize::to_string).collect::<Vec<_>>().join(","),
        config.modes.iter().map(|mode| quote(&mode.to_string())).collect::<Vec<_>>().join(",")
    );
    let identity = sha256(canonical.as_bytes());
    let mut tasks = Vec::new();
    for &bars in &config.bars {
        for &mode in &config.modes {
            tasks.push(Task { bars, mode });
        }
    }
    // A conservative upper bound uses one distinct key for every candidate.
    // Entries reserve once; hash-table load factor, transient allocation slack,
    // buffers and thread stacks are included in the per-worker allowance.
    let input_bytes = data
        .timestamps
        .capacity()
        .checked_mul(64)
        .and_then(|v| v.checked_add(4 * MIB))
        .ok_or("direction memory estimate overflow")?;
    let task_bytes = (end - first)
        .checked_mul(224)
        .and_then(|v| v.checked_add(8 * MIB))
        .ok_or("direction worker memory estimate overflow")?;
    let available = (config.memory_mib * MIB)
        .checked_sub(input_bytes)
        .ok_or("direction input exceeds memory_mib")?;
    let memory_workers = available / task_bytes;
    if memory_workers == 0 {
        return Err(format!(
            "direction memory_mib cannot hold one worker: estimated input={input_bytes} worker={task_bytes} bytes"
        ));
    }
    let effective_workers = config.workers.min(tasks.len()).min(memory_workers);
    let out = PathBuf::from(&config.out);
    if config.resume {
        let prior = fs::read_to_string(out.join("run.config.json"))
            .map_err(|e| format!("direction resume configuration: {e}"))?;
        if prior != canonical {
            return Err("direction resume context/input/executable mismatch".into());
        }
    } else {
        if let Some(parent) = out.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::create_dir(&out).map_err(|e| format!("create direction output: {e}"))?;
        atomic_text(&out.join("run.config.json"), &canonical)?;
        fs::create_dir(out.join("tasks")).map_err(|e| e.to_string())?;
    }
    let source = Arc::new(Source {
        config,
        bounds,
        data,
        data_path,
        engine_sha256,
        identity,
        first,
        end,
    });
    let task_root = out.join("tasks");
    let mut completed = vec![false; tasks.len()];
    let mut pending = Vec::new();
    for (index, task) in tasks.iter().enumerate() {
        completed[index] = verify_task(&source, *task, &task_root)?;
        if !completed[index] {
            pending.push(index);
        }
    }
    let resumed_tasks = completed.iter().filter(|done| **done).count();
    if source.config.max_tasks > 0 {
        pending.truncate(source.config.max_tasks);
    }
    let preparation_seconds = began.elapsed().as_secs_f64();
    let queue = Arc::new(AtomicUsize::new(0));
    let tasks = Arc::new(tasks);
    let pending = Arc::new(pending);
    let results = Arc::new(Mutex::new(Vec::<(usize, Result<()>)>::new()));
    let used_workers = effective_workers.min(pending.len());
    let mut workers = Vec::with_capacity(used_workers);
    for _ in 0..used_workers {
        let source = Arc::clone(&source);
        let queue = Arc::clone(&queue);
        let tasks = Arc::clone(&tasks);
        let pending = Arc::clone(&pending);
        let results = Arc::clone(&results);
        let task_root = task_root.clone();
        workers.push(std::thread::spawn(move || loop {
            let position = queue.fetch_add(1, Ordering::Relaxed);
            if position >= pending.len() {
                break;
            }
            let index = pending[position];
            let result = execute_task(&source, tasks[index], &task_root);
            let failed = result.is_err();
            results.lock().unwrap().push((index, result));
            if failed {
                // Stop admitting new work. In-flight workers may complete
                // independently and leave valid resumable checkpoints.
                queue.store(pending.len(), Ordering::Relaxed);
                break;
            }
        }));
    }
    for worker in workers {
        worker.join().map_err(|_| "direction worker panicked")?;
    }
    let mut results = results
        .lock()
        .map_err(|_| "direction result mutex poisoned")?;
    results.sort_unstable_by_key(|(index, _)| *index);
    for (index, result) in results.iter() {
        if let Err(error) = result {
            return Err(format!("direction task {}: {error}", tasks[*index].id()));
        }
        completed[*index] = true;
    }
    let completed_count = completed.iter().filter(|done| **done).count();
    let status = if completed_count == tasks.len() {
        "COMPLETE"
    } else {
        "PAUSED"
    };
    let task_json = tasks
        .iter()
        .zip(&completed)
        .map(|(task, done)| {
            format!(
                "{{\"id\":{},\"bars\":{},\"mode\":{},\"status\":{},\"summary\":{}}}",
                quote(&task.id()),
                task.bars,
                quote(&task.mode.to_string()),
                quote(if *done { "COMPLETE" } else { "PENDING" }),
                quote(&format!("tasks/{}/summary.json", task.id()))
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let elapsed = began.elapsed().as_secs_f64();
    let manifest = format!(
        "{{\"version\":1,\"status\":{}, {},\"requested_workers\":{},\"effective_workers\":{},\"workers_used_this_invocation\":{},\"memory_mib\":{},\"estimated_input_bytes\":{},\"estimated_worker_bytes\":{},\"resumed_tasks\":{},\"completed_tasks\":{},\"total_tasks\":{},\"preparation_seconds\":{preparation_seconds:.9},\"elapsed_seconds\":{elapsed:.9},\"tasks\":[{}]}}\n",
        quote(status), source.metadata(), source.config.workers, effective_workers, used_workers,
        source.config.memory_mib, input_bytes, task_bytes, resumed_tasks, completed_count,
        tasks.len(), task_json
    );
    atomic_text(&out.join("manifest.json"), &manifest)?;
    atomic_text(
        &out.join("manifest.json.sha256"),
        &format!("{}\n", sha256(manifest.as_bytes())),
    )?;
    Ok(manifest.trim_end().to_owned())
}
