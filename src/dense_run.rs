//! Bounded dense-family authoring and resumable exact execution. Generic state
//! dictionaries and Boolean certificates never dispatch on indicator labels.
use crate::{
    backtest::Costs,
    cohort,
    data::{self, Data},
    dense_bank::{self, Builder, Coordinate},
    dense_cells,
    dense_io::{self, Reader, Writer},
    dense_tree::{self, Table, Tree},
    hash::{sha256, Sha256},
    kernels::Backend,
    paged::{metric_values, Executor, Scorer},
    regions::Grid,
    report::{self, num, quote},
    rules::{Cmp, Program, Qualifier},
    Result,
};
use std::{
    collections::BTreeMap,
    fmt::Write as _,
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::Instant,
};
#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub start: i64,
    pub end: i64,
    pub families: Vec<String>,
    pub coefficients: usize,
    pub cutoffs: u64,
    pub qualifiers: Vec<Qualifier>,
    pub qualifier_text: String,
    pub rules: Vec<String>,
    pub memory: usize,
    pub bank_budget: usize,
    pub tree_budget: usize,
    pub block: usize,
    pub max_nodes: u64,
    pub costs: Costs,
}
impl Config {
    pub fn parse(text: &str) -> Result<Self> {
        let mut m = BTreeMap::new();
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let (k, v) = line.split_once('=').ok_or("config requires key=value")?;
            if m.insert(k.trim().to_owned(), v.trim().to_owned()).is_some() {
                return Err("duplicate dense key".into());
            }
        }
        fn take(m: &mut BTreeMap<String, String>, k: &str) -> Result<String> {
            m.remove(k).ok_or_else(|| format!("missing {k}"))
        }
        fn n<T: std::str::FromStr>(m: &mut BTreeMap<String, String>, k: &str) -> Result<T> {
            take(m, k)?.parse().map_err(|_| format!("bad {k}"))
        }
        if take(&mut m, "version")? != "1" {
            return Err("dense config version".into());
        }
        let qualifier_text = take(&mut m, "qualifiers")?;
        let c = Self {
            data: take(&mut m, "data")?,
            start: data::date(&take(&mut m, "start")?)?,
            end: data::date(&take(&mut m, "end")?)?,
            families: take(&mut m, "families")?
                .split(',')
                .map(str::to_owned)
                .collect(),
            coefficients: n(&mut m, "coefficients")?,
            cutoffs: n(&mut m, "cutoffs")?,
            qualifiers: qualifier_text
                .split(',')
                .map(Qualifier::parse)
                .collect::<Result<_>>()?,
            qualifier_text,
            rules: take(&mut m, "rules")?
                .split(';')
                .map(str::to_owned)
                .collect(),
            memory: n::<usize>(&mut m, "numeric_mib")?
                .checked_mul(1 << 20)
                .ok_or("budget overflow")?,
            bank_budget: n::<usize>(&mut m, "bank_mib")?
                .checked_mul(1 << 20)
                .ok_or("budget overflow")?,
            tree_budget: n::<usize>(&mut m, "tree_mib")?
                .checked_mul(1 << 20)
                .ok_or("budget overflow")?,
            block: n(&mut m, "task_states")?,
            max_nodes: n(&mut m, "max_task_nodes")?,
            costs: Costs {
                fee_bps: n(&mut m, "fee_bps")?,
                slip_bps: n(&mut m, "slip_bps")?,
            }
            .validate()?,
        };
        if !m.is_empty() {
            return Err(format!("unknown dense keys {:?}", m.keys()));
        }
        if ![3, 11, 41].contains(&c.coefficients)
            || c.cutoffs < 3
            || c.cutoffs > 100000
            || c.cutoffs % 2 == 0
            || c.start >= c.end
            || c.block == 0
            || c.block > 4096
            || c.max_nodes == 0
            || c.memory < 16 << 20
            || c.bank_budget < 1 << 20
            || c.tree_budget < 1 << 20
        {
            return Err("dense domain/resource limits".into());
        }
        if c.families.len() < 2
            || c.families.len() > 10
            || c.qualifiers.is_empty()
            || c.qualifiers.len() > 16
            || c.rules.is_empty()
            || c.rules.len() > 128
        {
            return Err("dense family/qualifier/template count".into());
        }
        let mut f = c.families.clone();
        f.sort();
        f.dedup();
        if f.len() != c.families.len() {
            return Err("duplicate families".into());
        }
        for f in &c.families {
            cohort::defaults(f)?;
        }
        for q in &c.qualifiers {
            if matches!(q, Qualifier::Onset) {
                return Err(
                    "dense v1 preparation accepts monotone plain/persist/recent qualifiers".into(),
                );
            }
        }
        for rule in &c.rules {
            Table::from_program(&Program::parse(rule, 2)?)?;
        }
        c.logical()?;
        Ok(c)
    }
    pub fn atoms(&self) -> u64 {
        3 * (self.coefficients as u64) * (self.coefficients as u64)
    }
    pub fn per_family(&self) -> u128 {
        self.atoms() as u128 * self.qualifiers.len() as u128 * self.cutoffs as u128
    }
    pub fn logical(&self) -> Result<u128> {
        let n = self.families.len() as u128;
        self.per_family()
            .checked_mul(self.per_family())
            .and_then(|v| v.checked_mul(n * (n - 1)))
            .and_then(|v| v.checked_mul(self.rules.len() as u128))
            .ok_or_else(|| "dense address overflow".into())
    }
    pub fn grid(&self, kind: &str) -> Result<Grid> {
        let (_, _, g) = cohort::defaults(kind)?;
        let scale = self.cutoffs - 1;
        let out = Grid {
            start: g.start.checked_mul(scale as i64).ok_or("grid overflow")?,
            step: g.step.checked_mul(g.count - 1).ok_or("grid overflow")?,
            count: self.cutoffs,
            denominator: g.denominator.checked_mul(scale).ok_or("grid overflow")?,
        };
        out.validate()?;
        Ok(out)
    }
    pub fn parameters(&self, kind: &str, atom: u64) -> Result<(usize, f64, f64)> {
        if atom >= self.atoms() {
            return Err("atom address".into());
        }
        let width = self.coefficients as u64;
        let b = atom % width;
        let a = atom / width % width;
        let p = atom / (width * width);
        let stride = 40 / (self.coefficients - 1);
        let n = cohort::defaults(kind)?.0 - 1 + p as usize;
        Ok((
            n,
            (a as i64 * stride as i64 - 20) as f64 / 2000.,
            (b as usize * stride) as f64 / 400.,
        ))
    }
}
pub fn example(path: &str, count: usize) -> Result<()> {
    let text=format!("version=1\ndata=data/btc4h/discovery.csv\nstart=2024-01-01\nend=2025-01-01\nfamilies={}\ncoefficients={count}\ncutoffs=20001\nqualifiers=plain,persist:2,recent:3\nrules=(and s0 s1);(or s0 s1);(and s0 (not s1))\nnumeric_mib=128\nbank_mib=64\ntree_mib=128\ntask_states=256\nmax_task_nodes=100000000\nfee_bps=10\nslip_bps=10\n",cohort::KINDS.join(","));
    Config::parse(&text)?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    file.write_all(text.as_bytes()).map_err(|e| e.to_string())
}
fn bank_context(context: &str, family: usize) -> String {
    sha256(format!("{context}|family|{family}").as_bytes())
}
fn record_path(dir: &Path, prefix: &str, id: usize, ext: &str) -> PathBuf {
    dir.join(format!("{prefix}-{id:02}.{ext}"))
}
fn prepared(
    c: &Config,
    d: &Data,
    range: std::ops::Range<usize>,
    context: &str,
    f: usize,
    dir: &Path,
    backend: Backend,
) -> Result<()> {
    let now = Instant::now();
    let ctxt = bank_context(context, f);
    let bank_path = record_path(dir, "bank", f, "bin");
    let alias_path = record_path(dir, "members", f, "bin");
    let marker = record_path(dir, "prepared", f, "chk");
    if marker.exists() {
        let b = dense_io::read(&marker, 4096)?;
        let mut r = Reader::new(&b);
        if r.bytes(64)? != ctxt.as_bytes() {
            return Err("prepared context mismatch".into());
        }
        let bankhash = r.bytes(64)?;
        let aliashash = r.bytes(64)?;
        if dense_io::verify(&bank_path)?.0.as_bytes() != bankhash
            || dense_io::verify(&alias_path)?.0.as_bytes() != aliashash
        {
            return Err("prepared payload changed".into());
        }
        return Ok(());
    }
    // Files with no commit marker belong to an interrupted preparation in this
    // locked, context-bound run. Never discard a committed artifact on mismatch.
    for p in [&bank_path, &alias_path] {
        if p.exists() {
            fs::remove_file(p).map_err(|e| e.to_string())?;
        }
    }
    let kind = &c.families[f];
    let grid = c.grid(kind)?;
    let mut ex = Executor::new(
        d,
        range.clone(),
        vec![],
        &[c.costs],
        backend,
        Scorer::Auto,
        c.memory,
    )?;
    let mut bank = Builder::new(range.end - range.start - 2, c.bank_budget)?;
    let mut writer = Writer::new(&alias_path)?;
    writer.write(b"FDALIAS1")?;
    writer.write(ctxt.as_bytes())?;
    for v in [
        c.atoms(),
        c.qualifiers.len() as u64,
        c.cutoffs,
        bank_rows(&range) as u64,
    ] {
        writer.write(&v.to_le_bytes())?;
    }
    let mut prior = None;
    let mut gbase = crate::lang::Graph::new();
    let mut ids = [0; 4];
    let mut events = 0;
    let center = cohort::defaults(kind)?.1;
    for atom in 0..c.atoms() {
        let (n, a, b) = c.parameters(kind, atom)?;
        let key = (n, a.to_bits());
        if prior != Some(key) {
            let (g, i) = cohort::stripe(kind, n, a)?;
            gbase = g;
            ids = i;
            ex.prepare_shared(&gbase, &ids)?;
            prior = Some(key);
        }
        let mut g = gbase.clone();
        let root = cohort::output(&mut g, kind, ids, b, center)?;
        let xroot = g.nodes[root].args[0];
        let x = ex
            .numerical_roots(&g, &[xroot], None)?
            .pop()
            .ok_or("numerical output")?;
        for (qi, &q) in c.qualifiers.iter().enumerate() {
            let work = dense_cells::visit(
                &x,
                Cmp::Gt,
                grid,
                &[q],
                range.start..range.end - 2,
                |lo, hi, mask| {
                    let id = bank.intern(
                        mask,
                        (hi - lo) as u128,
                        Coordinate {
                            atom,
                            qualifier: qi as u64,
                            cutoff: lo,
                        },
                    )?;
                    for v in [atom, qi as u64, lo, hi, id as u64] {
                        writer.write(&v.to_le_bytes())?;
                    }
                    Ok(())
                },
            )?;
            if work.addresses != grid.count {
                return Err("incomplete dense predicate grid".into());
            }
            events += work.events;
        }
    }
    if bank.addresses != c.per_family() {
        return Err("dense bank coverage mismatch".into());
    }
    let aliasbytes = writer.bytes;
    let aliashash = writer.finish()?;
    let bankhash = dense_bank::save(&bank.entries, bank_rows(&range), &ctxt, &bank_path)?;
    let mut record = ctxt.as_bytes().to_vec();
    record.extend_from_slice(bankhash.as_bytes());
    record.extend_from_slice(aliashash.as_bytes());
    for v in [
        c.atoms(),
        bank.cells,
        bank.entries.len() as u64,
        events,
        bank.payload as u64,
        aliasbytes,
    ] {
        record.extend_from_slice(&v.to_le_bytes());
    }
    record.extend_from_slice(&bank.addresses.to_le_bytes());
    dense_io::put(&marker, &record)?;
    let text=format!("{{\"family\":{},\"atoms_calculated\":{},\"predicate_regions\":{},\"distinct_predicate_states\":{},\"logical_condition_addresses\":{},\"payload_bytes\":{},\"member_bytes\":{},\"numeric_seconds\":{},\"seconds\":{}}}\n",quote(kind),c.atoms(),bank.cells,bank.entries.len(),quote(&bank.addresses.to_string()),bank.payload,aliasbytes,num(ex.work.numeric_seconds),num(now.elapsed().as_secs_f64()));
    fs::write(record_path(dir, "preparation", f, "json"), &text).map_err(|e| e.to_string())?;
    eprintln!(
        "Prepared {}: {} atom constructions, {} states from {} cells",
        kind,
        c.atoms(),
        bank.entries.len(),
        bank.cells
    );
    Ok(())
}
fn bank_rows(r: &std::ops::Range<usize>) -> usize {
    r.end - r.start - 2
}

#[derive(Clone, Debug)]
pub struct Best {
    pub families: [usize; 2],
    pub template: usize,
    pub coordinates: [Coordinate; 2],
    pub score: f64,
    pub metrics: [f64; 10],
}
impl Best {
    fn better(&self, other: &Self) -> bool {
        let (a, b) = ((self.score * 1e9).round(), (other.score * 1e9).round());
        a > b
            || a == b
                && (self.template, self.families, self.coordinates)
                    < (other.template, other.families, other.coordinates)
    }
    fn json(&self, c: &Config) -> String {
        format!("{{\"families\":[{},{}],\"template\":{},\"coordinates\":[[{},{},{}],[{},{},{}]],\"log_return\":{},\"metrics\":[{}]}}",quote(&c.families[self.families[0]]),quote(&c.families[self.families[1]]),quote(&c.rules[self.template]),self.coordinates[0].atom,self.coordinates[0].qualifier,self.coordinates[0].cutoff,self.coordinates[1].atom,self.coordinates[1].qualifier,self.coordinates[1].cutoff,num(self.score),self.metrics.iter().map(|v|num(*v)).collect::<Vec<_>>().join(","))
    }
}
#[derive(Clone, Debug)]
struct Task {
    pub id: u64,
    pub work: dense_tree::Work,
    pub regions: u64,
    pub digest: String,
    pub best: Best,
}
impl Task {
    fn encode(&self, context: &str) -> Vec<u8> {
        let mut b = b"FDTASK01".to_vec();
        b.extend_from_slice(context.as_bytes());
        for v in [
            self.id,
            self.work.node_pairs,
            self.work.proved_regions,
            self.work.leaf_pairs,
            self.work.bound_words,
            self.regions,
        ] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        for v in [self.work.signature_pairs, self.work.logical] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        b.extend_from_slice(self.digest.as_bytes());
        for v in [
            self.best.families[0] as u64,
            self.best.families[1] as u64,
            self.best.template as u64,
        ] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        for co in &self.best.coordinates {
            for v in [co.atom, co.qualifier, co.cutoff] {
                b.extend_from_slice(&v.to_le_bytes());
            }
        }
        b.extend_from_slice(&self.best.score.to_le_bytes());
        for v in self.best.metrics {
            b.extend_from_slice(&v.to_le_bytes());
        }
        b
    }
    fn decode(b: &[u8], context: &str, id: u64, c: &Config) -> Result<Self> {
        let mut r = Reader::new(b);
        if r.bytes(8)? != b"FDTASK01" || r.bytes(64)? != context.as_bytes() || r.u64()? != id {
            return Err("checkpoint context/version/order mismatch".into());
        }
        let node_pairs = r.u64()?;
        let proved_regions = r.u64()?;
        let leaf_pairs = r.u64()?;
        let bound_words = r.u64()?;
        let regions = r.u64()?;
        let signature_pairs = r.u128()?;
        let logical = r.u128()?;
        let digest = String::from_utf8(r.bytes(64)?.to_vec()).map_err(|_| "bad result hash")?;
        let families = [r.u64()? as usize, r.u64()? as usize];
        let template = r.u64()? as usize;
        if families.iter().any(|i| *i >= c.families.len())
            || families[0] == families[1]
            || template >= c.rules.len()
        {
            return Err("checkpoint family/template".into());
        }
        let mut coordinates = [Coordinate::default(); 2];
        for co in &mut coordinates {
            co.atom = r.u64()?;
            co.qualifier = r.u64()?;
            co.cutoff = r.u64()?;
            if co.atom >= c.atoms()
                || co.qualifier >= c.qualifiers.len() as u64
                || co.cutoff >= c.cutoffs
            {
                return Err("checkpoint parameter coordinate".into());
            }
        }
        let score = r.f64()?;
        if !score.is_finite() {
            return Err("checkpoint nonfinite rank".into());
        }
        let mut metrics = [0.; 10];
        for v in &mut metrics {
            *v = r.f64()?;
        }
        r.end()?;
        if regions == 0 || regions != proved_regions + leaf_pairs || logical == 0 {
            return Err("checkpoint coverage counters".into());
        }
        Ok(Self {
            id,
            work: dense_tree::Work {
                node_pairs,
                proved_regions,
                leaf_pairs,
                signature_pairs,
                logical,
                bound_words,
            },
            regions,
            digest,
            best: Best {
                families,
                template,
                coordinates,
                score,
                metrics,
            },
        })
    }
}
#[allow(clippy::too_many_arguments)]
fn task(
    c: &Config,
    d: &Data,
    range: std::ops::Range<usize>,
    context: &str,
    dir: &Path,
    id: u64,
    families: [usize; 2],
    template: usize,
    left: &Tree<'_>,
    right: &Tree<'_>,
    left_node: usize,
    backend: Backend,
    proof: bool,
    capture: bool,
) -> Result<Task> {
    let path = dir.join(format!("task-{id:08}.chk"));
    let output = dir.join(format!("task-{id:08}.boxes"));
    let expected = left.nodes[left_node]
        .count
        .checked_mul(right.nodes[right.root].count)
        .ok_or("task count overflow")?;
    if path.exists() {
        let out = Task::decode(&dense_io::read(&path, 4096)?, context, id, c)?;
        if out.work.logical != expected
            || out.best.families != families
            || out.best.template != template
        {
            return Err("checkpoint task coverage/domain mismatch".into());
        }
        if capture && dense_io::verify(&output)?.0 != out.digest {
            return Err("checkpoint result payload changed".into());
        }
        return Ok(out);
    }
    if output.exists() {
        fs::remove_file(&output).map_err(|e| e.to_string())?;
    }
    let mut writer = if capture {
        Some(Writer::new(&output)?)
    } else {
        None
    };
    let mut hash = Sha256::default();
    let mut best: Option<Best> = None;
    let mut regions = 0u64;
    let mut ex = Executor::new(
        d,
        range,
        vec![],
        &[c.costs],
        backend,
        Scorer::Auto,
        c.memory,
    )?;
    let table = Table::from_program(&Program::parse(&c.rules[template], 2)?)?;
    let work = dense_tree::visit(
        left,
        right,
        left_node,
        right.root,
        table,
        proof,
        c.max_nodes,
        |r, words| {
            let ms = ex.score_positions(words)?;
            let metrics = metric_values(&ms[0], d.interval);
            let b = Best {
                families,
                template,
                coordinates: [r.left_first, r.right_first],
                score: ms[0].lite.log_return,
                metrics,
            };
            if best.as_ref().map_or(true, |prior| b.better(prior)) {
                best = Some(b);
            }
            let mut bytes = [0; 128];
            let a = &left.nodes[r.left];
            let b = &right.nodes[r.right];
            for (i, v) in [a.lo as u64, a.hi as u64, b.lo as u64, b.hi as u64]
                .iter()
                .enumerate()
            {
                bytes[i * 8..i * 8 + 8].copy_from_slice(&v.to_le_bytes());
            }
            bytes[32..48].copy_from_slice(&r.count.to_le_bytes());
            for (i, v) in metrics.iter().enumerate() {
                bytes[48 + i * 8..56 + i * 8].copy_from_slice(&v.to_le_bytes());
            }
            hash.update(&bytes);
            if let Some(w) = writer.as_mut() {
                w.write(&bytes)?;
            }
            regions += 1;
            Ok(())
        },
    )?;
    let digest = hash.finish();
    if let Some(w) = writer {
        if w.finish() != Ok(digest.clone()) {
            return Err("result digest disagreement".into());
        }
    }
    let out = Task {
        id,
        work,
        regions,
        digest,
        best: best.ok_or("empty task")?,
    };
    if std::env::var("FILANG_DENSE_TEST_INTERRUPT").ok() == Some(id.to_string()) {
        return Err("injected interruption before checkpoint commit".into());
    }
    dense_io::put(&path, &out.encode(context))?;
    Ok(out)
}
fn export_best(c: &Config, best: &Best, dir: &Path) -> Result<()> {
    let mut text = String::new();
    for slot in 0..2 {
        let co = best.coordinates[slot];
        let kind = &c.families[best.families[slot]];
        let (n, a, b) = c.parameters(kind, co.atom)?;
        let (grid_center, grid) = (cohort::defaults(kind)?.1, c.grid(kind)?);
        let (mut g, ids) = cohort::stripe(kind, n, a)?;
        let root = cohort::output(&mut g, kind, ids, b, grid_center)?;
        let xroot = g.nodes[root].args[0];
        // Exact singleton rational grid retains the chosen binary64 threshold.
        let numerator = grid.start as i128 + co.cutoff as i128 * grid.step as i128;
        let singleton = format!("{numerator}:1:1:{}", grid.denominator);
        let q = c
            .qualifier_text
            .split(',')
            .nth(co.qualifier as usize)
            .ok_or("qualifier coordinate")?;
        writeln!(
            text,
            "{slot}\t{kind}-dense\t{kind}\tthreshold:gt\t{q}\t{singleton}\t{}\t-",
            g.expression(xroot)
        )
        .map_err(|e| e.to_string())?;
    }
    fs::write(dir.join("best-parameters.tsv"), text).map_err(|e| e.to_string())?;
    fs::write(
        dir.join("best-rule.txt"),
        format!("{}\n", c.rules[best.template]),
    )
    .map_err(|e| e.to_string())?;
    fs::write(dir.join("best.json"), best.json(c)).map_err(|e| e.to_string())
}
#[allow(clippy::too_many_arguments)]
pub fn run(
    raw: &str,
    out: &str,
    gate: &str,
    resume: bool,
    prepare_only: bool,
    max_tasks: u64,
    backend: Backend,
    proof: bool,
    capture: bool,
) -> Result<String> {
    let parsed = Config::parse(raw)?;
    let c = &parsed;
    let clock = Instant::now();
    let d = Data::read(&c.data, 14400)?;
    if d.timestamps[0] > c.start || d.timestamps.last().unwrap() + d.interval != c.end {
        return Err(
            "dense input must retain warmup and end exactly at end-exclusive boundary".into(),
        );
    }
    let range = d.index(c.start)..d.len();
    if range.end - range.start < 4 {
        return Err("dense scored range too short".into());
    }
    cohort::validate_gate(gate, &d.digest)?;
    Backend::resolve(backend.name())?;
    let context = sha256(
        format!(
            "filang-dense-v1|{raw}|{}|{}|{}|{proof}|{capture}",
            d.digest,
            crate::anchor_run::engine_id()?,
            backend.name()
        )
        .as_bytes(),
    );
    let dir = Path::new(out);
    if !resume {
        report::create_out(out)?;
    } else if !dir.is_dir() {
        return Err("resume directory missing".into());
    }
    let _lock = dense_io::Lock::acquire(dir)?;
    let header = dir.join("context.chk");
    if header.exists() {
        if dense_io::read(&header, 1024)?.as_slice() != context.as_bytes() {
            return Err("resume code/data/domain/backend/output context mismatch".into());
        }
    } else {
        if resume {
            return Err("missing committed run context".into());
        }
        dense_io::put(&header, context.as_bytes())?;
        fs::write(dir.join("experiment.cfg"), raw).map_err(|e| e.to_string())?;
    }
    let banks = dir.join("banks");
    let tasks = dir.join("tasks");
    fs::create_dir_all(&banks).map_err(|e| e.to_string())?;
    fs::create_dir_all(&tasks).map_err(|e| e.to_string())?;
    for f in 0..c.families.len() {
        prepared(c, &d, range.clone(), &context, f, &banks, backend)?;
    }
    let preparation_seconds = clock.elapsed().as_secs_f64();
    let (
        mut done,
        mut new_tasks,
        mut reused,
        mut covered,
        mut regions,
        mut pairs,
        mut visits,
        mut certified,
    ) = (0u64, 0u64, 0u64, 0u128, 0u64, 0u128, 0u128, 0u128);
    let mut result_hash = Sha256::default();
    let mut best: Option<Best> = None;
    let mut complete = !prepare_only;
    if !prepare_only {
        'outer: for a in 0..c.families.len() {
            let entries_a = dense_bank::load(
                &record_path(&banks, "bank", a, "bin"),
                &bank_context(&context, a),
                c.bank_budget,
            )?;
            let left = Tree::new(&entries_a, c.tree_budget)?;
            let frontier = left.frontier(c.block)?;
            for b in 0..c.families.len() {
                if a == b {
                    continue;
                }
                let entries_b = dense_bank::load(
                    &record_path(&banks, "bank", b, "bin"),
                    &bank_context(&context, b),
                    c.bank_budget,
                )?;
                let right = Tree::new(&entries_b, c.tree_budget)?;
                for template in 0..c.rules.len() {
                    for &node in &frontier {
                        let committed = tasks.join(format!("task-{done:08}.chk")).exists();
                        if !committed && max_tasks > 0 && new_tasks >= max_tasks {
                            complete = false;
                            break 'outer;
                        }
                        let t = task(
                            c,
                            &d,
                            range.clone(),
                            &context,
                            &tasks,
                            done,
                            [a, b],
                            template,
                            &left,
                            &right,
                            node,
                            backend,
                            proof,
                            capture,
                        )?;
                        if committed {
                            reused += 1;
                        } else {
                            new_tasks += 1;
                        }
                        covered = covered
                            .checked_add(t.work.logical)
                            .ok_or("whole coverage overflow")?;
                        regions = regions
                            .checked_add(t.regions)
                            .ok_or("region count overflow")?;
                        pairs += t.work.signature_pairs;
                        visits += t.work.node_pairs as u128;
                        certified += t.work.proved_regions as u128;
                        result_hash.update(&t.encode(&context));
                        if best.as_ref().map_or(true, |v| t.best.better(v)) {
                            best = Some(t.best);
                        }
                        done += 1;
                    }
                }
                eprintln!(
                    "Dense pair {} / {} committed; {} total tasks",
                    c.families[a], c.families[b], done
                );
            }
        }
    }
    if complete && covered != c.logical()? {
        return Err("completed dense domain coverage does not reconcile".into());
    }
    if let Some(b) = &best {
        export_best(c, b, dir)?;
    }
    let summary=format!("{{\"version\":1,\"status\":{},\"coverage_complete\":{},\"context_sha256\":{},\"data_sha256\":{},\"engine_sha256\":{},\"coefficient_count\":{},\"cutoff_count\":{},\"upstream_constructions\":{},\"requested_strategy_addresses\":{},\"resolved_strategy_addresses\":{},\"signature_pair_products_resolved\":{},\"tree_node_pairs_visited\":{},\"certified_nonleaf_products\":{},\"metric_regions_evaluated\":{},\"completed_tasks\":{},\"new_tasks\":{},\"reused_tasks\":{},\"result_digest\":{},\"best\":{},\"prepare_seconds_this_invocation\":{},\"whole_seconds_this_invocation\":{},\"backend\":{},\"proof\":{},\"capture\":{},\"role\":\"retrospective_systems_discovery_not_validation\"}}\n",quote(if complete{"PASS"}else if prepare_only{"PREPARED"}else{"PAUSED"}),complete,quote(&context),quote(&d.digest),quote(&crate::anchor_run::engine_id()?),c.coefficients,c.cutoffs,c.atoms()*c.families.len()as u64,quote(&c.logical()?.to_string()),quote(&covered.to_string()),quote(&pairs.to_string()),quote(&visits.to_string()),quote(&certified.to_string()),regions,done,new_tasks,reused,quote(&result_hash.finish()),best.as_ref().map_or_else(||"null".into(),|b|b.json(c)),num(preparation_seconds),num(clock.elapsed().as_secs_f64()),quote(backend.name()),proof,capture);
    fs::write(dir.join("summary.json"), &summary).map_err(|e| e.to_string())?;
    Ok(summary)
}

#[cfg(test)]
#[path = "dense_tests.rs"]
mod tests;
