//! Fine atom neighborhoods: authoring policy only; all numerics and full-risk
//! regions are evaluated by the same generic paged::Executor used by open programs.
use crate::{
    backtest::{Costs, Market, Metrics, Rule},
    data::{self, Data},
    hash::{sha256, Sha256},
    kernels::Backend,
    lang::{Graph, Id, Op},
    paged::{metric_values, Executor, Scorer},
    regions::Grid,
    report::{self, num, quote},
    Result,
};
use std::{
    collections::{BTreeMap, HashMap},
    fmt::Write as _,
    fs,
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};
#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub out: String,
    pub interval: i64,
    pub start: i64,
    pub end: i64,
    pub evaluation_start: i64,
    pub evaluation_end: i64,
    pub anchor: usize,
    pub windows: Vec<usize>,
    pub alpha: Grid,
    pub beta: Grid,
    pub offset: Grid,
    pub memory: usize,
    pub costs: [Costs; 2],
    pub min_trades: usize,
    pub max_drawdown: f64,
    pub min_exposure: f64,
    pub max_exposure: f64,
}
impl Config {
    pub fn parse(raw: &str) -> Result<Self> {
        let mut m = BTreeMap::new();
        for l in raw.lines() {
            let l = l.trim();
            if l.is_empty() || l.starts_with('#') {
                continue;
            }
            let (k, v) = l.split_once('=').ok_or("config needs key=value")?;
            if m.insert(k.trim().to_owned(), v.trim().to_owned()).is_some() {
                return Err("duplicate micro config key".into());
            }
        }
        fn take(m: &mut BTreeMap<String, String>, k: &str) -> Result<String> {
            m.remove(k).ok_or_else(|| format!("missing {k}"))
        }
        fn n<T: std::str::FromStr>(m: &mut BTreeMap<String, String>, k: &str) -> Result<T> {
            take(m, k)?.parse().map_err(|_| format!("bad {k}"))
        }
        if take(&mut m, "version")? != "1" {
            return Err("micro config version".into());
        }
        let c = Self {
            data: take(&mut m, "data")?,
            out: take(&mut m, "out")?,
            interval: n(&mut m, "interval_seconds")?,
            start: data::date(&take(&mut m, "discovery_start")?)?,
            end: data::date(&take(&mut m, "discovery_end")?)?,
            evaluation_start: data::date(&take(&mut m, "evaluation_start")?)?,
            evaluation_end: data::date(&take(&mut m, "evaluation_end")?)?,
            anchor: n(&mut m, "anchor_window")?,
            windows: take(&mut m, "windows")?
                .split(',')
                .map(|w| w.parse().map_err(|_| "bad window".into()))
                .collect::<Result<_>>()?,
            alpha: Grid::parse(&take(&mut m, "source_grid")?)?,
            beta: Grid::parse(&take(&mut m, "mean_grid")?)?,
            offset: Grid::parse(&take(&mut m, "offset_grid")?)?,
            memory: n::<usize>(&mut m, "memory_mib")?
                .checked_mul(1 << 20)
                .ok_or("memory overflow")?,
            costs: [
                Costs {
                    fee_bps: n(&mut m, "fee_bps")?,
                    slip_bps: n(&mut m, "slip_bps")?,
                }
                .validate()?,
                Costs {
                    fee_bps: n(&mut m, "stress_fee_bps")?,
                    slip_bps: n(&mut m, "stress_slip_bps")?,
                }
                .validate()?,
            ],
            min_trades: n(&mut m, "min_trades")?,
            max_drawdown: n(&mut m, "max_drawdown_pct")?,
            min_exposure: n(&mut m, "min_exposure")?,
            max_exposure: n(&mut m, "max_exposure")?,
        };
        if !m.is_empty() {
            return Err(format!("unknown micro keys {:?}", m.keys()));
        }
        if c.interval <= 0
            || !(c.start < c.end
                && c.end <= c.evaluation_start
                && c.evaluation_start < c.evaluation_end)
            || c.memory < 16 << 20
        {
            return Err("invalid timeline/budget".into());
        }
        if c.windows.is_empty()
            || c.windows.len() > 1024
            || !c.windows.contains(&c.anchor)
            || c.windows.iter().any(|w| *w < 2 || *w >= 100000)
        {
            return Err("invalid micro window range".into());
        }
        let mut w = c.windows.clone();
        w.sort_unstable();
        w.dedup();
        if w.len() != c.windows.len() {
            return Err("duplicate windows".into());
        }
        c.alpha.member(0.)?;
        c.beta.member(0.)?;
        c.offset.member(1.)?;
        if c.alpha.value(0) < -0.25
            || c.alpha.value(c.alpha.count - 1) > 0.25
            || c.beta.value(0) < 0.
            || c.beta.value(c.beta.count - 1) > 1.
            || c.offset.value(0) <= 0.
        {
            return Err("micro domains: alpha [-.25,.25], beta [0,1], positive offset".into());
        }
        if !c.max_drawdown.is_finite()
            || c.max_drawdown < 0.
            || c.max_drawdown > 100.
            || !c.min_exposure.is_finite()
            || !c.max_exposure.is_finite()
            || c.min_exposure < 0.
            || c.max_exposure > 1.
            || c.min_exposure >= c.max_exposure
        {
            return Err("invalid selection gates".into());
        }
        c.count()?;
        Ok(c)
    }
    pub fn bases(&self) -> Result<u64> {
        (self.windows.len() as u64)
            .checked_mul(self.alpha.count)
            .and_then(|v| v.checked_mul(self.beta.count))
            .ok_or_else(|| "base count overflow".into())
    }
    pub fn count(&self) -> Result<u64> {
        self.bases()?
            .checked_mul(self.offset.count)
            .ok_or_else(|| "domain count overflow".into())
    }
    pub fn params(&self, base: u64) -> Result<(usize, f64, f64)> {
        if base >= self.bases()? {
            return Err("bad base address".into());
        }
        let b = base % self.beta.count;
        let k = base / self.beta.count;
        let a = k % self.alpha.count;
        Ok((
            self.windows[(k / self.alpha.count) as usize],
            self.alpha.value(a),
            self.beta.value(b),
        ))
    }
    pub fn distance(&self, n: usize, a: f64, b: f64, c: f64) -> f64 {
        let aw = self
            .alpha
            .value(0)
            .abs()
            .max(self.alpha.value(self.alpha.count - 1).abs());
        let bw = self.beta.value(self.beta.count - 1).abs();
        let cw = (self.offset.value(0) - 1.)
            .abs()
            .max((self.offset.value(self.offset.count - 1) - 1.).abs());
        (n as f64 - self.anchor as f64).abs()
            + if aw > 0. { a.abs() / aw } else { 0. }
            + if bw > 0. { b.abs() / bw } else { 0. }
            + if cw > 0. { (c - 1.).abs() / cw } else { 0. }
    }
}
/// Prefix shared by all beta/offset descendants for this source/window stripe.
/// Zero coefficients select the unchanged graph, not 0*invalid or a changed warmup.
pub fn stripe(n: usize, a: f64) -> Result<(Graph, [Id; 3])> {
    if !(2..100000).contains(&n) || !a.is_finite() {
        return Err("invalid stripe parameters".into());
    }
    let mut g = Graph::new();
    let close = g.source(3);
    let price = if a == 0. {
        close
    } else {
        let open = g.source(0);
        let delta = g.binary(Op::Sub, open, close);
        let k = g.constant(a);
        let adj = g.binary(Op::Mul, k, delta);
        g.binary(Op::Add, close, adj)
    };
    let m = g.unary(Op::MeanSum(n), price);
    let next = g.unary(Op::MeanSum(n + 1), price);
    Ok((g, [price, m, next]))
}
pub fn output(g: &mut Graph, ids: [Id; 3], b: f64, c: f64) -> Result<Id> {
    if !b.is_finite() || !c.is_finite() {
        return Err("nonfinite parameters".into());
    }
    let d = if b == 0. {
        ids[1]
    } else {
        let delta = g.binary(Op::Sub, ids[2], ids[1]);
        let k = g.constant(b);
        let adj = g.binary(Op::Mul, k, delta);
        g.binary(Op::Add, ids[1], adj)
    };
    let r = g.binary(Op::Div, ids[0], d);
    let c = g.constant(c);
    Ok(g.binary(Op::Sub, r, c))
}
#[derive(Clone)]
struct Pick {
    base: u64,
    q: u64,
    n: usize,
    a: f64,
    b: f64,
    c: f64,
    ms: Vec<Metrics>,
    distance: f64,
}
impl Pick {
    fn json(&self, interval: i64) -> String {
        format!("{{\"base\":{},\"offset_index\":{},\"window\":{},\"source_weight\":{},\"mean_weight\":{},\"offset\":{},\"distance\":{},\"primary\":{},\"stress\":{}}}",self.base,self.q,self.n,num(self.a),num(self.b),num(self.c),num(self.distance),report::metrics(&self.ms[0],interval),report::metrics(&self.ms[1],interval))
    }
}
fn better(a: &Pick, b: &Pick) -> bool {
    let aa = (a.ms[1].lite.log_return * 1e9).round();
    let bb = (b.ms[1].lite.log_return * 1e9).round();
    aa > bb
        || (aa == bb
            && (a.distance < b.distance
                || (a.distance == b.distance && (a.base, a.q) < (b.base, b.q))))
}
fn eligible(c: &Config, ms: &[Metrics]) -> bool {
    ms[0].lite.entries >= c.min_trades
        && ms[0].lite.exposure() >= c.min_exposure
        && ms[0].lite.exposure() <= c.max_exposure
        && ms[1].max_drawdown_pct <= c.max_drawdown
        && ms[1].lite.log_return.is_finite()
}
fn pair_metrics(
    c: &Config,
    d: &Data,
    n: usize,
    a: f64,
    b: f64,
    offset: f64,
) -> Result<Vec<Metrics>> {
    let (mut g, ids) = stripe(n, a)?;
    let r = output(&mut g, ids, b, offset)?;
    let batch = crate::engine::evaluate(&g, d, &[r], c.memory)?;
    c.costs
        .iter()
        .map(|&cost| {
            Market::new(d, d.index(c.start), d.len(), cost)?.score(
                &batch.values[&r],
                Rule {
                    threshold: 0.,
                    greater: true,
                },
            )
        })
        .collect()
}
fn gate(path: &str, digest: &str) -> Result<()> {
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let fields: HashMap<_, _> = text.lines().filter_map(|l| l.split_once('=')).collect();
    let source = fields.get("data_sha256").ok_or("gate dataset missing")?;
    crate::anchor_run::validate_gate(path, source)?;
    if *source != digest && fields.get("authorized_prefix_sha256").copied() != Some(digest) {
        return Err("micro data are not a parity-authorized prefix".into());
    }
    Ok(())
}
fn freeze(c: &Config, d: &Data, picks: &[(&str, Pick)], dir: &Path) -> Result<()> {
    let mut text=format!("# filang-selection-v1\n# execution=spot_open_v1\n# interval={}\n# fee_bps={}\n# slip_bps={}\n# evaluation_start={}\n# evaluation_end={}\n# discovery_sha256={}\n# discovery_rows={}\n# research_role=retrospective_micro_neighborhood\nid\tgroup\tname\tgreater\tthreshold_bits\texpression\n",c.interval,c.costs[0].fee_bps,c.costs[0].slip_bps,c.evaluation_start,c.evaluation_end,d.digest,d.len());
    for (label, p) in picks {
        let (mut g, ids) = stripe(p.n, p.a)?;
        let root = output(&mut g, ids, p.b, p.c)?;
        let fid = g.identity(root);
        let id = sha256(format!("filang-readout-v1|{fid}|true|0000000000000000").as_bytes());
        writeln!(
            text,
            "{id}\t{label}\t{label}_{}\ttrue\t0000000000000000\t{}",
            &fid[..16],
            g.expression(root)
        )
        .unwrap();
    }
    report::write(
        dir.join("frozen.tsv.sha256"),
        &(sha256(text.as_bytes()) + "\n"),
    )?;
    report::write(dir.join("frozen.tsv"), &text)
}
/// Full discovery pass. The range ends exactly at discovery_end; later data are
/// rejected before any numerical evaluation. Returns compressed, replayable coverage.
pub fn run(
    c: &Config,
    raw: &str,
    gate_path: &str,
    plan: &str,
    backend: Backend,
    keep_regions: bool,
    shared: bool,
) -> Result<String> {
    if !["regions", "expanded"].contains(&plan) {
        return Err("plan regions/expanded".into());
    }
    if plan == "expanded" && c.count()? > 100000 {
        return Err(
            "expanded oracle is capped at 100000 addresses; choose a small matched grid".into(),
        );
    }
    let clock = Instant::now();
    let d = Data::read(&c.data, c.interval)?;
    if d.timestamps[0] > c.start || d.timestamps.last().unwrap() + d.interval != c.end {
        return Err(
            "micro discovery input must end exactly at discovery_end; future rows forbidden".into(),
        );
    }
    gate(gate_path, &d.digest)?;
    report::create_out(&c.out)?;
    let dir = Path::new(&c.out);
    report::write(dir.join("experiment.cfg"), raw)?;
    let anchor = Pick {
        base: (c
            .windows
            .iter()
            .position(|n| *n == c.anchor)
            .ok_or("anchor window missing")? as u64
            * c.alpha.count
            + c.alpha.member(0.)?)
            * c.beta.count
            + c.beta.member(0.)?,
        q: c.offset.member(1.)?,
        n: c.anchor,
        a: 0.,
        b: 0.,
        c: 1.,
        ms: pair_metrics(c, &d, c.anchor, 0., 0., 1.)?,
        distance: 0.,
    };
    let mut executor = Executor::new(
        &d,
        d.index(c.start)..d.len(),
        vec![],
        &c.costs,
        backend,
        Scorer::Auto,
        c.memory,
    )?;
    let mut writer = if keep_regions {
        Some(BufWriter::new(
            fs::File::create(dir.join("regions.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let mut transitions = if keep_regions && plan == "regions" {
        Some(BufWriter::new(
            fs::File::create(dir.join("transitions.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let mut surface =
        BufWriter::new(fs::File::create(dir.join("surface.csv")).map_err(|e| e.to_string())?);
    writeln!(surface,"base,window,source_weight,mean_weight,regions,eligible_addresses,at_one_net_pct,at_one_stress_pct,at_one_stress_drawdown,at_one_trades,best_stress_pct,best_offset,worst_stress_pct").map_err(|e|e.to_string())?;
    let (mut hasher, mut covered, mut regions, mut events) = (Sha256::default(), 0u64, 0u64, 0u64);
    let (mut positive, mut outperform, mut eligible_total) = (0u64, 0u64, 0u64);
    let (mut winner, mut descriptive): (Option<Pick>, Option<Pick>) = (None, None);
    let mut base = 0;
    let c_one = c.offset.member(1.)?;
    let mut output_seconds = 0.;
    for &n in &c.windows {
        for ia in 0..c.alpha.count {
            let a = c.alpha.value(ia);
            let (base_graph, ids) = stripe(n, a)?;
            if shared {
                executor.prepare_shared(&base_graph, &ids)?;
            } else {
                executor.clear_shared();
            }
            for ib in 0..c.beta.count {
                let b = c.beta.value(ib);
                let mut g = base_graph.clone();
                let root = output(&mut g, ids, b, 1.)?;
                let (mut local_regions, mut local_eligible, mut local_next) = (0u64, 0u64, 0u64);
                let mut at_one = None;
                let mut best: Option<Pick> = None;
                let mut worst = f64::INFINITY;
                let w = executor.constant_regions(
                    &g,
                    root,
                    c.offset,
                    plan == "expanded",
                    |lo, hi, ms| {
                        if lo != local_next || hi <= lo || hi > c.offset.count || ms.len() != 2 {
                            return Err("region coverage invariant failed".into());
                        }
                        local_next = hi;
                        let start = Instant::now();
                        let width = hi - lo;
                        covered = covered.checked_add(width).ok_or("coverage overflow")?;
                        local_regions += 1;
                        let q = c_one.clamp(lo, hi - 1);
                        let offset = c.offset.value(q);
                        let p = Pick {
                            base,
                            q,
                            n,
                            a,
                            b,
                            c: offset,
                            ms: ms.to_vec(),
                            distance: c.distance(n, a, b, offset),
                        };
                        if ms[1].lite.log_return > 0. {
                            positive += width;
                        }
                        if ms[1].lite.log_return > anchor.ms[1].lite.log_return {
                            outperform += width;
                        }
                        if lo <= c_one && c_one < hi {
                            at_one = Some(ms.to_vec());
                        }
                        let ok = eligible(c, ms);
                        if ok {
                            local_eligible += width;
                            if winner.as_ref().map_or(true, |v| better(&p, v)) {
                                winner = Some(p.clone());
                            }
                        }
                        if descriptive.as_ref().map_or(true, |v| better(&p, v)) {
                            descriptive = Some(p.clone());
                        }
                        if best.as_ref().map_or(true, |v| better(&p, v)) {
                            best = Some(p);
                        }
                        worst = worst.min(ms[1].lite.return_pct());
                        let mut bytes = [0u8; 184];
                        for (i, v) in [base, lo, hi].iter().enumerate() {
                            bytes[i * 8..i * 8 + 8].copy_from_slice(&v.to_le_bytes());
                        }
                        for (s, m) in ms.iter().enumerate() {
                            for (i, v) in metric_values(m, c.interval).iter().enumerate() {
                                let j = 24 + s * 80 + i * 8;
                                bytes[j..j + 8].copy_from_slice(&v.to_le_bytes());
                            }
                        }
                        hasher.update(&bytes);
                        if let Some(out) = writer.as_mut() {
                            out.write_all(&bytes).map_err(|e| e.to_string())?;
                        }
                        output_seconds += start.elapsed().as_secs_f64();
                        Ok(())
                    },
                )?;
                if local_next != c.offset.count || w.addresses != c.offset.count {
                    return Err("unresolved offset domain".into());
                }
                if let Some(out) = transitions.as_mut() {
                    out.write_all(&base.to_le_bytes())
                        .and_then(|_| out.write_all(&w.proof))
                        .map_err(|e| e.to_string())?;
                }
                regions += w.regions;
                events += w.crossing_events;
                eligible_total += local_eligible;
                let at = at_one.ok_or("anchor offset absent")?;
                let best = best.ok_or("empty grid")?;
                writeln!(surface,"{base},{n},{a:.17},{b:.17},{local_regions},{local_eligible},{:.17},{:.17},{:.17},{},{:.17},{:.17},{worst:.17}",at[0].lite.return_pct(),at[1].lite.return_pct(),at[1].max_drawdown_pct,at[0].lite.entries,best.ms[1].lite.return_pct(),best.c).map_err(|e|e.to_string())?;
                base += 1;
            }
        }
    }
    if covered != c.count()? || base != c.bases()? {
        return Err("incomplete micro coverage".into());
    }
    if let Some(out) = writer.as_mut() {
        out.flush().map_err(|e| e.to_string())?;
    }
    surface.flush().map_err(|e| e.to_string())?;
    if let Some(out) = transitions.as_mut() {
        out.flush().map_err(|e| e.to_string())?;
    }
    let mut picks = vec![("anchor", anchor.clone())];
    if let Some(p) = &winner {
        if !(p.n == anchor.n && p.a == 0. && p.b == 0. && p.c == 1.) {
            picks.push(("selected", p.clone()));
        }
    }
    freeze(c, &d, &picks, dir)?;
    let summary=format!("{{\"version\":1,\"role\":\"retrospective_discovery_frozen_before_later_replay\",\"data_sha256\":{},\"engine_sha256\":{},\"plan\":{},\"backend\":{},\"upstream_parameter_constructions\":{},\"full_parameter_addresses_resolved\":{},\"logical_scenario_metric_sets\":{},\"physical_result_regions\":{},\"crossing_events\":{},\"coverage_complete\":true,\"distinct_full_programs_not_asserted\":true,\"offset_is_readout_equivalent\":true,\"positive_stress_addresses\":{},\"beats_anchor_stress_addresses\":{},\"eligible_addresses\":{},\"region_bytes_computed\":{},\"region_bytes_written\":{},\"region_sha256\":{},\"anchor\":{},\"selected\":{},\"descriptive_best_not_additionally_selected\":{},\"prepared_banks\":{},\"prepared_nodes\":{},\"prepared_hits\":{},\"bank_peak_bytes\":{},\"state_bytes\":{},\"page_work\":{},\"transition_work\":{},\"output_seconds_included_in_scoring\":{},\"total_internal_seconds\":{}}}\n",
        quote(&d.digest),quote(&crate::anchor_run::engine_id()?),quote(plan),quote(backend.name()),base,covered,(covered as u128)*2,regions,events,positive,outperform,eligible_total,(regions as u128)*184,if keep_regions{(regions as u128)*184}else{0},quote(&hasher.finish()),anchor.json(c.interval),winner.as_ref().map_or_else(||"null".into(),|p|p.json(c.interval)),descriptive.as_ref().map_or_else(||"null".into(),|p|p.json(c.interval)),executor.bank_builds,executor.bank_nodes,executor.bank_hits,executor.bank_peak_bytes,executor.state_bytes(),executor.work.json(),executor.state_work().json(),num(output_seconds),num(clock.elapsed().as_secs_f64()));
    report::write(dir.join("summary.json"), &summary)?;
    Ok(summary)
}
