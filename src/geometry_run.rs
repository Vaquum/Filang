//! Complete qualitative bar-pattern domains compiled into the shared dense
//! predicate-bank executor. Sample aliases retain their full logical counts;
//! frozen candidates always identify one explicit canonical pattern.
use crate::{
    backtest::Costs,
    data::{self, Data},
    dense_bank::{self, Builder, Coordinate},
    dense_io::{self, Reader, Writer},
    dense_run::{self, bank_context, bank_rows, record_path, BankSource, Best, ExecutionConfig},
    dense_tree::Table,
    geometry::{self, GeometryEncoder, GeometryMode, GeometryPattern},
    hash::sha256,
    kernels::Backend,
    report::{num, quote},
    rules::{Mask, Program, Qualifier},
    Result,
};
use std::{
    collections::{BTreeMap, HashMap},
    fmt::Write as _,
    fs,
    io::Write,
    path::Path,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    },
    time::Instant,
};

#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub interval_seconds: i64,
    pub start: i64,
    pub end: i64,
    pub mode: GeometryMode,
    pub windows: Vec<Vec<usize>>,
    pub qualifiers: Vec<Qualifier>,
    pub qualifier_text: String,
    pub rules: Vec<String>,
    pub allow_same_bank: bool,
    pub memory: usize,
    pub bank_budget: usize,
    pub tree_budget: usize,
    pub prepare_budget: usize,
    pub block: usize,
    pub max_nodes: u64,
    pub costs: Costs,
}
impl Config {
    pub fn parse(raw: &str) -> Result<Self> {
        if raw.len() > 1 << 20 {
            return Err("geometry configuration exceeds 1 MiB".into());
        }
        let mut fields = BTreeMap::new();
        for line in raw.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let (key, value) = line
                .split_once('=')
                .ok_or("geometry config requires key=value")?;
            if fields
                .insert(key.trim().to_owned(), value.trim().to_owned())
                .is_some()
            {
                return Err("duplicate geometry config key".into());
            }
        }
        fn take(fields: &mut BTreeMap<String, String>, key: &str) -> Result<String> {
            fields
                .remove(key)
                .ok_or_else(|| format!("missing geometry key {key}"))
        }
        fn number<T: std::str::FromStr>(
            fields: &mut BTreeMap<String, String>,
            key: &str,
        ) -> Result<T> {
            take(fields, key)?
                .parse()
                .map_err(|_| format!("invalid geometry key {key}"))
        }
        fn mib(fields: &mut BTreeMap<String, String>, key: &str) -> Result<usize> {
            number::<usize>(fields, key)?
                .checked_mul(1 << 20)
                .ok_or_else(|| "geometry budget overflow".into())
        }
        if take(&mut fields, "version")? != "1" {
            return Err("geometry config version".into());
        }
        let windows = take(&mut fields, "windows")?
            .split(';')
            .map(|window| {
                window
                    .split(',')
                    .map(|lag| {
                        lag.trim()
                            .parse::<usize>()
                            .map_err(|_| "invalid geometry lag".into())
                    })
                    .collect::<Result<Vec<_>>>()
            })
            .collect::<Result<Vec<_>>>()?;
        let qualifier_text = take(&mut fields, "qualifiers")?
            .split(',')
            .map(str::trim)
            .collect::<Vec<_>>()
            .join(",");
        let out = Self {
            data: take(&mut fields, "data")?,
            interval_seconds: number(&mut fields, "interval_seconds")?,
            start: data::date(&take(&mut fields, "start")?)?,
            end: data::date(&take(&mut fields, "end")?)?,
            mode: GeometryMode::parse(&take(&mut fields, "mode")?)?,
            windows,
            qualifiers: qualifier_text
                .split(',')
                .map(Qualifier::parse)
                .collect::<Result<_>>()?,
            qualifier_text,
            rules: take(&mut fields, "rules")?
                .split(';')
                .map(|s| s.trim().to_owned())
                .collect(),
            allow_same_bank: number(&mut fields, "allow_same_bank")?,
            memory: mib(&mut fields, "numeric_mib")?,
            bank_budget: mib(&mut fields, "bank_mib")?,
            tree_budget: mib(&mut fields, "tree_mib")?,
            prepare_budget: mib(&mut fields, "prepare_mib")?,
            block: number(&mut fields, "task_states")?,
            max_nodes: number(&mut fields, "max_task_nodes")?,
            costs: Costs {
                fee_bps: number(&mut fields, "fee_bps")?,
                slip_bps: number(&mut fields, "slip_bps")?,
            }
            .validate()?,
        };
        if !fields.is_empty() {
            return Err(format!("unknown geometry config keys {:?}", fields.keys()));
        }
        out.validate()?;
        Ok(out)
    }
    fn validate(&self) -> Result<()> {
        self.costs.validate()?;
        if self.data.is_empty()
            || self.interval_seconds <= 0
            || self.start >= self.end
            || self.windows.is_empty()
            || self.windows.len() > 128
            || !self.allow_same_bank && self.windows.len() < 2
            || self.qualifiers.is_empty()
            || self.qualifiers.len() > 16
            || self.rules.is_empty()
            || self.rules.len() > 128
            || self.memory < 16 << 20
            || self.bank_budget < 1 << 20
            || self.tree_budget < 1 << 20
            || self.prepare_budget < 1 << 20
            || self.block == 0
            || self.block > 4096
            || self.max_nodes == 0
        {
            return Err("geometry domain/resource limits".into());
        }
        for (i, window) in self.windows.iter().enumerate() {
            if window.is_empty()
                || window[0] != 0
                || window.len() > 9
                || window.last().copied().unwrap_or(0) > 100000
                || window.windows(2).any(|pair| pair[0] >= pair[1])
                || self.windows[..i].contains(window)
            {
                return Err("geometry windows require distinct increasing lags from 0, at most nine bars and maximum lag 100000".into());
            }
            geometry::count_domain(window.len(), self.mode)?;
        }
        let names = self.qualifier_text.split(',').collect::<Vec<_>>();
        if names.len() != self.qualifiers.len() {
            return Err("geometry qualifier names/count".into());
        }
        for (i, &q) in self.qualifiers.iter().enumerate() {
            if self.qualifiers[..i].contains(&q) || Qualifier::parse(names[i])? != q {
                return Err("duplicate or inconsistent geometry qualifiers".into());
            }
        }
        for (i, rule) in self.rules.iter().enumerate() {
            Table::from_program(&Program::parse(rule, 2)?)?;
            if self.rules[..i].contains(rule) {
                return Err("duplicate geometry rule template".into());
            }
        }
        self.logical()?;
        Ok(())
    }
    pub fn pattern_count(&self, bank: usize) -> Result<u128> {
        geometry::count_domain(
            self.windows.get(bank).ok_or("geometry bank address")?.len(),
            self.mode,
        )
    }
    pub fn per_bank(&self, bank: usize) -> Result<u128> {
        self.pattern_count(bank)?
            .checked_mul(self.qualifiers.len() as u128)
            .ok_or_else(|| "geometry condition-domain overflow".into())
    }
    pub fn logical(&self) -> Result<u128> {
        let counts = (0..self.windows.len())
            .map(|i| self.per_bank(i))
            .collect::<Result<Vec<_>>>()?;
        let mut total = 0u128;
        for (a, &left) in counts.iter().enumerate() {
            for (b, &right) in counts.iter().enumerate() {
                if a != b || self.allow_same_bank {
                    total = left
                        .checked_mul(right)
                        .and_then(|n| total.checked_add(n))
                        .ok_or("geometry strategy-domain overflow")?;
                }
            }
        }
        total
            .checked_mul(self.rules.len() as u128)
            .ok_or_else(|| "geometry strategy-domain overflow".into())
    }
    pub fn execution(&self) -> ExecutionConfig {
        ExecutionConfig {
            rules: self.rules.clone(),
            memory: self.memory,
            bank_budget: self.bank_budget,
            tree_budget: self.tree_budget,
            block: self.block,
            max_nodes: self.max_nodes,
            costs: self.costs,
            allow_same_bank: self.allow_same_bank,
        }
    }
    pub fn labels(&self) -> Vec<String> {
        self.windows
            .iter()
            .map(|lags| format!("lags:{}", lag_text(lags)))
            .collect()
    }
    pub fn qualifier_name(&self, index: usize) -> Result<&str> {
        self.qualifier_text
            .split(',')
            .nth(index)
            .ok_or_else(|| "geometry qualifier coordinate".into())
    }
    pub fn validate_data(&self, data: &Data) -> Result<std::ops::Range<usize>> {
        if data.is_empty()
            || data.interval != self.interval_seconds
            || data.timestamps[0] > self.start
            || data
                .timestamps
                .last()
                .and_then(|t| t.checked_add(data.interval))
                != Some(self.end)
        {
            return Err("geometry input must retain warmup and end exactly at end-exclusive boundary; future rows are forbidden".into());
        }
        let start = data.index(self.start);
        if data.timestamps.get(start) != Some(&self.start) || data.len() - start < 4 {
            return Err(
                "geometry scored start must be an exact bar boundary with at least four rows"
                    .into(),
            );
        }
        Ok(start..data.len())
    }
}

fn lag_text(lags: &[usize]) -> String {
    lags.iter()
        .map(usize::to_string)
        .collect::<Vec<_>>()
        .join(",")
}

// A positive shift maps original bit t-k onto result bit t. Traversing words
// backwards keeps all lower source words unchanged during an in-place fold.
fn shifted(words: &[u64], index: usize, shift: usize) -> u64 {
    let whole = shift / 64;
    let partial = shift % 64;
    if index < whole {
        return 0;
    }
    let from = index - whole;
    let mut value = words[from] << partial;
    if partial != 0 && from > 0 {
        value |= words[from - 1] >> (64 - partial);
    }
    value
}
fn fold(words: &mut [u64], shift: usize, and: bool) {
    for i in (0..words.len()).rev() {
        let previous = shifted(words, i, shift);
        if and {
            words[i] &= previous;
        } else {
            words[i] |= previous;
        }
    }
}
/// Bitwise implementation of the scalar `Mask::qualify` contract. Validity is
/// always the intersection of the complete window, including for recency.
pub fn qualify(mask: &Mask, qualifier: Qualifier) -> Result<Mask> {
    dense_bank::validate_mask(mask, mask.len)?;
    let mut out = match qualifier {
        Qualifier::Plain => return Ok(mask.clone()),
        Qualifier::Persist(n) | Qualifier::Recent(n) => {
            if n == 0 || n > 100000 {
                return Err("qualifier window outside 1..100000".into());
            }
            if n > mask.len {
                return Ok(Mask::empty(mask.len));
            }
            mask.clone()
        }
        Qualifier::Onset => mask.clone(),
    };
    match qualifier {
        Qualifier::Persist(n) | Qualifier::Recent(n) => {
            let and = matches!(qualifier, Qualifier::Persist(_));
            let mut covered = 1usize;
            while covered <= n / 2 {
                fold(&mut out.bits, covered, and);
                fold(&mut out.valid, covered, true);
                covered *= 2;
            }
            if covered < n {
                fold(&mut out.bits, n - covered, and);
                fold(&mut out.valid, n - covered, true);
            }
        }
        Qualifier::Onset => {
            for i in (0..out.bits.len()).rev() {
                let previous = shifted(&out.bits, i, 1);
                out.bits[i] &= !previous;
            }
            fold(&mut out.valid, 1, true);
        }
        Qualifier::Plain => unreachable!(),
    }
    for (bits, valid) in out.bits.iter_mut().zip(&out.valid) {
        *bits &= *valid;
    }
    if mask.len % 64 != 0 {
        let tail = (1u64 << (mask.len % 64)) - 1;
        if let Some(last) = out.bits.last_mut() {
            *last &= tail;
        }
        if let Some(last) = out.valid.last_mut() {
            *last &= tail;
        }
    }
    Ok(out)
}

pub struct Source<'a> {
    config: &'a Config,
    labels: Vec<String>,
    catalogue_records: Vec<AtomicUsize>,
    preparations: Vec<Mutex<Option<Preparation>>>,
}
impl<'a> Source<'a> {
    pub fn new(config: &'a Config) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            config,
            labels: config.labels(),
            catalogue_records: (0..config.windows.len())
                .map(|_| AtomicUsize::new(0))
                .collect(),
            preparations: (0..config.windows.len())
                .map(|_| Mutex::new(None))
                .collect(),
        })
    }
}

#[allow(clippy::too_many_arguments)]
pub fn run(
    raw: &str,
    out: &str,
    resume: bool,
    prepare_only: bool,
    max_tasks: u64,
    workers: usize,
    backend: Backend,
    proof: bool,
    capture: bool,
) -> Result<String> {
    let config = Config::parse(raw)?;
    let data = Data::read(&config.data, config.interval_seconds)?;
    let range = config.validate_data(&data)?;
    let source = Source::new(&config)?;
    dense_run::run_banks(
        raw,
        out,
        &data,
        range,
        "filang-geometry-v1",
        &config.execution(),
        &source,
        resume,
        prepare_only,
        max_tasks,
        workers,
        backend,
        proof,
        capture,
    )
}

#[derive(Clone, Debug)]
struct Preparation {
    window_size: u64,
    max_lag: u64,
    decision_rows: u64,
    scored_start: u64,
    scored_rows: u64,
    windows_encoded: u64,
    observed_patterns: u64,
    catalogue_records: u64,
    qualifier_count: u64,
    physical_memberships: u64,
    states: u64,
    prepare_charge: u64,
    total_patterns: u128,
    unobserved_patterns: u128,
    logical_conditions: u128,
}
impl Preparation {
    fn integers(&self) -> [u64; 12] {
        [
            self.window_size,
            self.max_lag,
            self.decision_rows,
            self.scored_start,
            self.scored_rows,
            self.windows_encoded,
            self.observed_patterns,
            self.catalogue_records,
            self.qualifier_count,
            self.physical_memberships,
            self.states,
            self.prepare_charge,
        ]
    }
    fn decode(reader: &mut Reader<'_>) -> Result<Self> {
        Ok(Self {
            window_size: reader.u64()?,
            max_lag: reader.u64()?,
            decision_rows: reader.u64()?,
            scored_start: reader.u64()?,
            scored_rows: reader.u64()?,
            windows_encoded: reader.u64()?,
            observed_patterns: reader.u64()?,
            catalogue_records: reader.u64()?,
            qualifier_count: reader.u64()?,
            physical_memberships: reader.u64()?,
            states: reader.u64()?,
            prepare_charge: reader.u64()?,
            total_patterns: reader.u128()?,
            unobserved_patterns: reader.u128()?,
            logical_conditions: reader.u128()?,
        })
    }
    fn validate(&self, c: &Config, bank: usize, range: &std::ops::Range<usize>) -> Result<()> {
        let lags = c.windows.get(bank).ok_or("geometry preparation bank")?;
        let max_lag = *lags.last().ok_or("empty geometry window")?;
        let cut = range.end - 2;
        let expected_catalogue = self
            .observed_patterns
            .checked_add((self.unobserved_patterns > 0) as u64)
            .ok_or("geometry catalogue count overflow")?;
        if self.window_size != lags.len() as u64
            || self.max_lag != max_lag as u64
            || self.decision_rows != cut as u64
            || self.scored_start != range.start as u64
            || self.scored_rows != bank_rows(range) as u64
            || self.windows_encoded != cut.saturating_sub(max_lag) as u64
            || self.observed_patterns > self.windows_encoded
            || self.total_patterns != c.pattern_count(bank)?
            || self
                .total_patterns
                .checked_sub(self.observed_patterns as u128)
                != Some(self.unobserved_patterns)
            || self.catalogue_records != expected_catalogue
            || self.catalogue_records == 0
            || self.qualifier_count != c.qualifiers.len() as u64
            || self.catalogue_records.checked_mul(self.qualifier_count)
                != Some(self.physical_memberships)
            || self.states == 0
            || self.states > self.physical_memberships
            || self.prepare_charge > c.prepare_budget as u64
            || self.logical_conditions != c.per_bank(bank)?
        {
            return Err("geometry preparation metadata/domain mismatch".into());
        }
        Ok(())
    }
}

// Plain JSON and selected-candidate files remain conventional text. Source
// preparation binds their exact SHA-256 in its sealed commit marker.
fn plain_write(path: &Path, bytes: &[u8], replace: bool) -> Result<String> {
    if !replace && path.exists() {
        return Err(format!(
            "immutable artifact already exists: {}",
            path.display()
        ));
    }
    let pending = path.with_extension("pending");
    let mut file = fs::File::create(&pending).map_err(|e| e.to_string())?;
    file.write_all(bytes).map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    fs::rename(&pending, path).map_err(|e| e.to_string())?;
    fs::File::open(path.parent().ok_or("artifact parent")?)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(sha256(bytes))
}

fn read_marker(
    c: &Config,
    range: &std::ops::Range<usize>,
    context: &str,
    bank: usize,
    banks: &Path,
    verify_payloads: bool,
) -> Result<Preparation> {
    let bytes = dense_io::read(&record_path(banks, "prepared", bank, "chk"), 4096)?;
    let mut reader = Reader::new(&bytes);
    if reader.bytes(8)? != b"FGPREP01"
        || reader.bytes(64)? != bank_context(context, bank).as_bytes()
    {
        return Err("geometry preparation context/version mismatch".into());
    }
    let mut hashes = Vec::new();
    for _ in 0..4 {
        hashes.push(reader.bytes(64)?);
    }
    let metadata = Preparation::decode(&mut reader)?;
    reader.end()?;
    metadata.validate(c, bank, range)?;
    if verify_payloads {
        for (i, (prefix, ext)) in [("bank", "bin"), ("patterns", "tsv"), ("members", "tsv")]
            .iter()
            .enumerate()
        {
            if dense_io::verify(&record_path(banks, prefix, bank, ext))?
                .0
                .as_bytes()
                != hashes[i]
            {
                return Err("committed geometry preparation payload changed".into());
            }
        }
        let stats_path = record_path(banks, "preparation", bank, "json");
        if fs::metadata(&stats_path).map_err(|e| e.to_string())?.len() > 65536 {
            return Err("geometry preparation statistics length".into());
        }
        if sha256(&fs::read(&stats_path).map_err(|e| e.to_string())?).as_bytes() != hashes[3] {
            return Err("committed geometry statistics changed".into());
        }
    }
    Ok(metadata)
}

/// Conservative preparation payload charge. Per-key slack covers hash-table
/// capacity, vector headers, encoder keys and temporary ordering; occurrence
/// slack covers vector growth. Scored state banks have their separate budget.
struct PreparationBudget {
    used: usize,
    limit: usize,
}
impl PreparationBudget {
    fn charge(&mut self, bytes: usize) -> Result<()> {
        self.used = self
            .used
            .checked_add(bytes)
            .ok_or("geometry preparation charge overflow")?;
        if self.used > self.limit {
            return Err("geometry preparation budget exceeded; shorten the data/domain or increase prepare_mib".into());
        }
        Ok(())
    }
}

fn valid_from(mask: &mut Mask, start: usize) {
    if start >= mask.len {
        return;
    }
    let first = start / 64;
    for word in &mut mask.valid[first..] {
        *word = u64::MAX;
    }
    mask.valid[first] &= u64::MAX << (start % 64);
    if mask.len % 64 != 0 {
        if let Some(last) = mask.valid.last_mut() {
            *last &= (1u64 << (mask.len % 64)) - 1;
        }
    }
}

fn prepare_bank(
    c: &Config,
    data: &Data,
    range: std::ops::Range<usize>,
    context: &str,
    bank: usize,
    banks: &Path,
) -> Result<Preparation> {
    let now = Instant::now();
    let marker = record_path(banks, "prepared", bank, "chk");
    if marker.exists() {
        return read_marker(c, &range, context, bank, banks, true);
    }
    // The shared runner holds its context-bound run lock. Only these uncommitted
    // source artifacts can be discarded after a killed preparation process.
    for (prefix, extension) in [
        ("bank", "bin"),
        ("patterns", "tsv"),
        ("members", "tsv"),
        ("preparation", "json"),
    ] {
        let path = record_path(banks, prefix, bank, extension);
        if path.exists() {
            fs::remove_file(path).map_err(|e| e.to_string())?;
        }
    }
    let lags = &c.windows[bank];
    let max_lag = *lags.last().ok_or("empty geometry window")?;
    let total = c.pattern_count(bank)?;
    let cut = range.end - 2;
    let words = cut.checked_add(63).ok_or("geometry row count overflow")? / 64;
    let mut budget = PreparationBudget {
        used: 0,
        limit: c.prepare_budget,
    };
    budget.charge(
        words
            .checked_mul(64)
            .and_then(|n| n.checked_add(65536 + lags.len() * 1024))
            .ok_or("geometry mask budget overflow")?,
    )?;
    let key_charge = lags
        .len()
        .checked_mul(80)
        .and_then(|n| n.checked_add(768))
        .ok_or("geometry key charge overflow")?;
    let mut encoder = GeometryEncoder::new(lags.len(), c.mode)?;
    let mut rows = vec![[0.; 4]; lags.len()];
    let mut seen = HashMap::<GeometryPattern, usize>::new();
    let mut occurrences = Vec::<Vec<usize>>::new();
    for t in max_lag..cut {
        for (row, &lag) in rows.iter_mut().zip(lags) {
            let index = t - lag;
            *row = [
                data.columns[0][index],
                data.columns[1][index],
                data.columns[2][index],
                data.columns[3][index],
            ];
        }
        let pattern = encoder.encode_ohlc(&rows)?;
        let id = if let Some(&id) = seen.get(pattern) {
            id
        } else {
            budget.charge(key_charge)?;
            seen.try_reserve(1).map_err(|_| "geometry key allocation")?;
            occurrences
                .try_reserve(1)
                .map_err(|_| "geometry occurrence-table allocation")?;
            let id = occurrences.len();
            occurrences.push(Vec::new());
            seen.insert(pattern.clone(), id);
            id
        };
        budget.charge(4 * std::mem::size_of::<usize>())?;
        occurrences[id]
            .try_reserve(1)
            .map_err(|_| "geometry occurrence allocation")?;
        occurrences[id].push(t);
    }
    let observed = seen.len();
    let absent = total
        .checked_sub(observed as u128)
        .ok_or("observed geometry count exceeds legal domain")?;
    let complement = if absent > 0 {
        budget.charge(key_charge)?;
        Some(
            geometry::first_unobserved_by(lags.len(), c.mode, observed, |p| seen.contains_key(p))?
                .ok_or("missing unobserved geometry representative")?,
        )
    } else {
        None
    };
    let mut ordered = seen
        .iter()
        .map(|(pattern, &id)| (id, pattern))
        .collect::<Vec<_>>();
    ordered.sort_unstable_by_key(|(id, _)| *id);
    let mut catalogue = Writer::new(&record_path(banks, "patterns", bank, "tsv"))?;
    catalogue.write(b"id\tkind\tmultiplicity\tpattern\n")?;
    let mut members = Writer::new(&record_path(banks, "members", bank, "tsv"))?;
    members.write(b"pattern_id\tqualifier\tstate_id\tmultiplicity\n")?;
    let mut builder = Builder::new(bank_rows(&range), c.bank_budget)?;
    let mut base = Mask::empty(cut);
    valid_from(&mut base, max_lag);
    let representatives = observed
        .checked_add(complement.is_some() as usize)
        .ok_or("geometry catalogue overflow")?;
    for id in 0..representatives {
        let (pattern, kind, multiplicity) = if id < observed {
            if ordered[id].0 != id {
                return Err("noncontiguous geometry catalogue".into());
            }
            (ordered[id].1, "observed", 1u128)
        } else {
            (
                complement
                    .as_ref()
                    .ok_or("geometry complement representative")?,
                "unobserved",
                absent,
            )
        };
        catalogue.write(format!("{id}\t{kind}\t{multiplicity}\t{pattern}\n").as_bytes())?;
        let mut mask = base.clone();
        if id < observed {
            for &t in &occurrences[id] {
                mask.bits[t / 64] |= 1u64 << (t % 64);
            }
        }
        for (qindex, &qualifier) in c.qualifiers.iter().enumerate() {
            let qualified = qualify(&mask, qualifier)?;
            let scored = qualified.slice(range.start, cut)?;
            let state = builder.intern(
                &scored,
                multiplicity,
                Coordinate {
                    atom: id as u64,
                    qualifier: qindex as u64,
                    cutoff: 0,
                },
            )?;
            members.write(format!("{id}\t{qindex}\t{state}\t{multiplicity}\n").as_bytes())?;
        }
    }
    if builder.addresses != c.per_bank(bank)? {
        return Err("geometry bank logical coverage mismatch".into());
    }
    let catalogue_bytes = catalogue.bytes;
    let members_bytes = members.bytes;
    let catalogue_hash = catalogue.finish()?;
    let members_hash = members.finish()?;
    let bank_hash = dense_bank::save(
        &builder.entries,
        bank_rows(&range),
        &bank_context(context, bank),
        &record_path(banks, "bank", bank, "bin"),
    )?;
    let metadata = Preparation {
        window_size: lags.len() as u64,
        max_lag: max_lag as u64,
        decision_rows: cut as u64,
        scored_start: range.start as u64,
        scored_rows: bank_rows(&range) as u64,
        windows_encoded: cut.saturating_sub(max_lag) as u64,
        observed_patterns: observed as u64,
        catalogue_records: representatives as u64,
        qualifier_count: c.qualifiers.len() as u64,
        physical_memberships: builder.cells,
        states: builder.entries.len() as u64,
        prepare_charge: budget.used as u64,
        total_patterns: total,
        unobserved_patterns: absent,
        logical_conditions: builder.addresses,
    };
    metadata.validate(c, bank, &range)?;
    let statistics = format!(concat!(
        "{{\"version\":1,\"source\":\"geometry\",\"bank\":{},\"window_lags\":[{}],\"mode\":{},",
        "\"scored_rows\":{},\"scored_start_index\":{},\"decision_rows\":{},\"windows_encoded\":{},",
        "\"observed_patterns\":{},\"total_patterns\":{},\"unobserved_patterns\":{},\"qualifiers\":[{}],",
        "\"logical_conditions\":{},\"catalogue_records\":{},\"physical_memberships\":{},\"states\":{},",
        "\"bank_payload_bytes\":{},\"prepare_payload_charge_bytes\":{},\"catalogue_bytes\":{},\"member_bytes\":{},",
        "\"seconds\":{},\"alias_scope\":\"fixed_causal_input_and_scored_timeline_only\"}}\n"),
        bank, lag_text(lags), quote(&c.mode.to_string()), metadata.scored_rows, metadata.scored_start,
        metadata.decision_rows, metadata.windows_encoded, observed, quote(&total.to_string()), quote(&absent.to_string()),
        c.qualifier_text.split(',').map(quote).collect::<Vec<_>>().join(","), quote(&builder.addresses.to_string()),
        representatives, builder.cells, builder.entries.len(), builder.payload, budget.used, catalogue_bytes, members_bytes,
        num(now.elapsed().as_secs_f64()));
    let stats_hash = plain_write(
        &record_path(banks, "preparation", bank, "json"),
        statistics.as_bytes(),
        false,
    )?;
    let mut record = b"FGPREP01".to_vec();
    record.extend_from_slice(bank_context(context, bank).as_bytes());
    for hash in [bank_hash, catalogue_hash, members_hash, stats_hash] {
        record.extend_from_slice(hash.as_bytes());
    }
    for integer in metadata.integers() {
        record.extend_from_slice(&integer.to_le_bytes());
    }
    for count in [total, absent, builder.addresses] {
        record.extend_from_slice(&count.to_le_bytes());
    }
    dense_io::put(&marker, &record)?;
    eprintln!("Prepared geometry {}: {} causal windows, {} observed patterns, {} states; {} logical conditions",
        lag_text(lags), metadata.windows_encoded, observed, builder.entries.len(), builder.addresses);
    Ok(metadata)
}

impl Source<'_> {
    fn pattern(
        &self,
        bank: usize,
        id: u64,
        banks: &Path,
    ) -> Result<(GeometryPattern, String, u128)> {
        let bytes = dense_io::read(
            &record_path(banks, "patterns", bank, "tsv"),
            self.config.prepare_budget,
        )?;
        let text = std::str::from_utf8(&bytes).map_err(|_| "non-UTF8 geometry catalogue")?;
        let mut lines = text.lines();
        if lines.next() != Some("id\tkind\tmultiplicity\tpattern") {
            return Err("geometry catalogue header".into());
        }
        for line in lines {
            let fields = line.split('\t').collect::<Vec<_>>();
            if fields.len() != 4 {
                return Err("geometry catalogue record".into());
            }
            if fields[0]
                .parse::<u64>()
                .map_err(|_| "geometry catalogue id")?
                != id
            {
                continue;
            }
            let multiplicity = fields[2]
                .parse::<u128>()
                .map_err(|_| "geometry catalogue multiplicity")?;
            if multiplicity == 0
                || !matches!(fields[1], "observed" | "unobserved")
                || fields[1] == "observed" && multiplicity != 1
            {
                return Err("geometry catalogue kind/multiplicity".into());
            }
            let pattern = fields[3].parse::<GeometryPattern>()?;
            if pattern.mode() != self.config.mode
                || pattern.len() != self.config.windows[bank].len()
            {
                return Err("geometry catalogue mode/window".into());
            }
            return Ok((pattern, fields[1].to_owned(), multiplicity));
        }
        Err("selected geometry pattern is missing".into())
    }
    fn selected(&self, best: &Best, rules: &[String], banks: &Path) -> Result<(String, String)> {
        let mut tsv = String::from("slot\tlags\tqualifier\tpattern\n");
        let mut predicates = Vec::new();
        for slot in 0..2 {
            let bank = best.families[slot];
            let co = best.coordinates[slot];
            self.validate_coordinate(bank, co, banks)?;
            let (pattern, kind, multiplicity) = self.pattern(bank, co.atom, banks)?;
            let lags = lag_text(&self.config.windows[bank]);
            let qualifier = self.config.qualifier_name(co.qualifier as usize)?;
            writeln!(tsv, "{slot}\t{lags}\t{qualifier}\t{pattern}").map_err(|e| e.to_string())?;
            predicates.push(format!(
                "{{\"lags\":[{}],\"qualifier\":{},\"pattern\":{},\"catalogue_kind\":{},\"sample_alias_multiplicity\":{}}}",
                lags, quote(qualifier), quote(&pattern.to_string()), quote(&kind), quote(&multiplicity.to_string())
            ));
        }
        let rule = rules
            .get(best.template)
            .ok_or("geometry best rule coordinate")?;
        let json = format!(concat!(
            "{{\"source\":\"geometry\",\"mode\":{},\"families\":[{},{}],\"template\":{},",
            "\"coordinates\":[[{},{},{}],[{},{},{}]],\"predicates\":[{}],\"log_return\":{},\"metrics\":[{}],",
            "\"frozen_semantics\":\"one_explicit_pattern_per_slot\"}}"),
            quote(&self.config.mode.to_string()), quote(&self.labels[best.families[0]]),
            quote(&self.labels[best.families[1]]), quote(rule), best.coordinates[0].atom,
            best.coordinates[0].qualifier, best.coordinates[0].cutoff, best.coordinates[1].atom,
            best.coordinates[1].qualifier, best.coordinates[1].cutoff, predicates.join(","),
            num(best.score), best.metrics.iter().map(|v| num(*v)).collect::<Vec<_>>().join(","));
        Ok((tsv, json))
    }
}

impl BankSource for Source<'_> {
    fn labels(&self) -> &[String] {
        &self.labels
    }
    fn addresses(&self, bank: usize) -> Result<u128> {
        self.config.per_bank(bank)
    }
    fn validate(&self, data: &Data, range: std::ops::Range<usize>) -> Result<()> {
        self.config.validate()?;
        if self.config.validate_data(data)? != range {
            return Err("geometry scored range mismatch".into());
        }
        Ok(())
    }
    fn prepare(
        &self,
        data: &Data,
        range: std::ops::Range<usize>,
        context: &str,
        bank: usize,
        banks: &Path,
        _backend: Backend,
    ) -> Result<()> {
        let metadata = prepare_bank(self.config, data, range, context, bank, banks)?;
        let records = usize::try_from(metadata.catalogue_records)
            .map_err(|_| "geometry catalogue size overflow")?;
        *self.preparations[bank]
            .lock()
            .map_err(|_| "geometry preparation cache poisoned")? = Some(metadata);
        self.catalogue_records[bank].store(records, Ordering::Release);
        Ok(())
    }
    fn validate_coordinate(&self, bank: usize, co: Coordinate, _banks: &Path) -> Result<()> {
        let records = self
            .catalogue_records
            .get(bank)
            .ok_or("geometry bank coordinate")?
            .load(Ordering::Acquire);
        if records == 0
            || co.atom >= records as u64
            || co.qualifier >= self.config.qualifiers.len() as u64
            || co.cutoff != 0
        {
            return Err("geometry catalogue/qualifier coordinate".into());
        }
        Ok(())
    }
    fn best_json(&self, best: &Best, rules: &[String], banks: &Path) -> Result<String> {
        Ok(self.selected(best, rules, banks)?.1)
    }
    fn export_best(&self, best: &Best, rules: &[String], banks: &Path, out: &Path) -> Result<()> {
        let (tsv, json) = self.selected(best, rules, banks)?;
        let rule = format!(
            "{}\n",
            rules
                .get(best.template)
                .ok_or("geometry best rule coordinate")?
        );
        for (name, text) in [("best-geometry.tsv", tsv), ("best-rule.txt", rule)] {
            let hash = plain_write(&out.join(name), text.as_bytes(), true)?;
            plain_write(
                &out.join(format!("{name}.sha256")),
                format!("{hash}\n").as_bytes(),
                true,
            )?;
        }
        plain_write(&out.join("best.json"), json.as_bytes(), true)?;
        Ok(())
    }
    fn summary_fields(&self, _banks: &Path) -> Result<String> {
        let (mut total, mut encoded, mut observed, mut physical) = (0u128, 0u128, 0u128, 0u128);
        let mut windows = Vec::new();
        for (bank, cache) in self.preparations.iter().enumerate() {
            let held = cache
                .lock()
                .map_err(|_| "geometry preparation cache poisoned")?;
            let m = held
                .as_ref()
                .ok_or("missing geometry preparation metadata")?;
            total = total
                .checked_add(m.total_patterns)
                .ok_or("geometry universe total overflow")?;
            encoded = encoded
                .checked_add(m.windows_encoded as u128)
                .ok_or("geometry encoded count overflow")?;
            observed = observed
                .checked_add(m.observed_patterns as u128)
                .ok_or("geometry observed count overflow")?;
            physical = physical
                .checked_add(m.catalogue_records as u128)
                .ok_or("geometry representative count overflow")?;
            windows.push(format!(concat!(
                "{{\"bank\":{},\"lags\":[{}],\"total_patterns\":{},\"observed_patterns\":{},",
                "\"unobserved_patterns\":{},\"physical_pattern_representatives\":{},\"states\":{},\"logical_conditions\":{}}}"),
                bank, lag_text(&self.config.windows[bank]), quote(&m.total_patterns.to_string()),
                m.observed_patterns, quote(&m.unobserved_patterns.to_string()), m.catalogue_records,
                m.states, quote(&m.logical_conditions.to_string())));
        }
        Ok(format!(concat!(
            "\"source\":\"geometry\",\"geometry_version\":1,\"mode\":{},\"window_banks\":[{}],",
            "\"total_raw_pattern_universe\":{},\"observed_encoded_rows\":{},\"observed_pattern_instances\":{},",
            "\"physical_pattern_representatives\":{},\"qualifiers\":[{}],\"allow_same_bank\":{},",
            "\"candidate_domain\":\"complete_legal_patterns_and_declared_qualifiers\",",
            "\"alias_scope\":\"fixed_causal_input_and_scored_timeline_only\""),
            quote(&self.config.mode.to_string()), windows.join(","), quote(&total.to_string()),
            quote(&encoded.to_string()), quote(&observed.to_string()), quote(&physical.to_string()),
            self.config.qualifier_text.split(',').map(quote).collect::<Vec<_>>().join(","), self.config.allow_same_bank))
    }
}

#[cfg(test)]
#[path = "geometry_run_tests.rs"]
mod tests;
