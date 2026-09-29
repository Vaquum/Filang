//! One bounded page executor for known-indicator macros and anonymous programs.
//! No authoring labels, seeds, asset names or recorded answers select the backend.
use crate::{
    backtest::{Costs, Metrics, ReusableExecution, TransitionMode},
    data::Data,
    family,
    hash::Sha256,
    kernels::{self, Backend},
    lang::{Graph, Id},
    Result,
};
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

#[derive(Clone, Debug)]
pub struct Request {
    pub address: u64,
    pub root: Id,
    pub rules: Vec<crate::backtest::Rule>,
}
pub struct Page {
    pub graph: Graph,
    pub requests: Vec<Request>,
}
pub trait PageSource {
    fn next_page(&mut self) -> Result<Option<Page>>;
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Scorer {
    Replay,
    Legacy,
    Events,
    Delta,
    Rebuild,
    Auto,
}
impl Scorer {
    pub fn parse(v: &str) -> Result<Self> {
        match v {
            "replay" => Ok(Self::Replay),
            "legacy" => Ok(Self::Legacy),
            "events" => Ok(Self::Events),
            "delta" => Ok(Self::Delta),
            "rebuild" => Ok(Self::Rebuild),
            "auto" => Ok(Self::Auto),
            _ => Err("scorer replay/legacy/events/delta/rebuild/auto".into()),
        }
    }
}
pub trait Sink {
    fn emit(
        &mut self,
        address: u64,
        rule: usize,
        scenario: usize,
        metrics: &Metrics,
        interval: i64,
    ) -> Result<()>;
}
pub fn metric_values(m: &Metrics, interval: i64) -> [f64; 10] {
    [
        m.lite.return_pct(),
        m.gross_return_pct,
        m.cagr_pct,
        m.max_drawdown_pct,
        m.lite.sharpe(interval),
        m.lite.entries as f64,
        100.0 * m.lite.exposure(),
        10000.0 * m.lite.sum / m.lite.periods as f64,
        m.mean_trade_bps,
        m.lite.periods as f64,
    ]
}
/// Same logical records are computed and hashed in both modes. Summary mode
/// discards the record after hashing; it never substitutes partial metrics.
pub struct BinarySink {
    writer: Option<BufWriter<File>>,
    hash: Sha256,
    pub records: u64,
    pub bytes: u64,
}
impl BinarySink {
    pub fn new(path: Option<&Path>) -> Result<Self> {
        Ok(Self {
            writer: path
                .map(File::create)
                .transpose()
                .map_err(|e| e.to_string())?
                .map(BufWriter::new),
            hash: Sha256::default(),
            records: 0,
            bytes: 0,
        })
    }
    pub fn finish(mut self) -> Result<(String, u64, u64)> {
        if let Some(w) = self.writer.as_mut() {
            w.flush().map_err(|e| e.to_string())?;
        }
        Ok((self.hash.finish(), self.records, self.bytes))
    }
}
impl Sink for BinarySink {
    fn emit(&mut self, _: u64, _: usize, _: usize, m: &Metrics, interval: i64) -> Result<()> {
        let mut bytes = [0u8; 80];
        for (i, v) in metric_values(m, interval).iter().enumerate() {
            bytes[i * 8..i * 8 + 8].copy_from_slice(&v.to_le_bytes());
        }
        self.hash.update(&bytes);
        if let Some(w) = self.writer.as_mut() {
            w.write_all(&bytes).map_err(|e| e.to_string())?;
        }
        self.records = self.records.checked_add(1).ok_or("record count overflow")?;
        self.bytes = self
            .bytes
            .checked_add(80)
            .ok_or("output byte count overflow")?;
        Ok(())
    }
}
#[derive(Default, Debug)]
pub struct Work {
    pub pages: u64,
    pub programs: u64,
    pub rules: u64,
    pub nodes: u64,
    pub fused_nodes: u64,
    pub event_sorts: u64,
    pub emitted: u64,
    pub materialized_peak: usize,
    pub numeric_seconds: f64,
    pub scoring_seconds: f64,
    pub detection_seconds: f64,
    pub emission_seconds: f64,
    pub replay_calls: u64,
    pub per_series_plans: u64,
    pub cross_program_plans: u64,
}
impl Work {
    pub fn json(&self) -> String {
        format!("{{\"pages\":{},\"program_requests\":{},\"readouts\":{},\"materialized_nodes\":{},\"fused_nodes\":{},\"event_sorts\":{},\"full_metric_sets\":{},\"numeric_payload_peak\":{},\"numeric_seconds\":{},\"scoring_seconds\":{},\"detection_seconds\":{},\"output_seconds\":{},\"replay_calls\":{},\"series_plans\":{},\"cross_program_plans\":{}}}",self.pages,self.programs,self.rules,self.nodes,self.fused_nodes,self.event_sorts,self.emitted,self.materialized_peak,self.numeric_seconds,self.scoring_seconds,self.detection_seconds,self.emission_seconds,self.replay_calls,self.per_series_plans,self.cross_program_plans)
    }
}
/// Fixed context; numerical pages do not own execution state. The state survives
/// page boundaries. A new dataset/window/scenario set constructs a new Executor.
pub struct Executor<'a> {
    d: &'a Data,
    start: usize,
    end: usize,
    gaps: Vec<usize>,
    state: ReusableExecution,
    backend: Backend,
    scorer: Scorer,
    budget: usize,
    pub work: Work,
}
impl<'a> Executor<'a> {
    pub fn new(
        d: &'a Data,
        range: std::ops::Range<usize>,
        gaps: Vec<usize>,
        costs: &[Costs],
        backend: Backend,
        scorer: Scorer,
        budget: usize,
    ) -> Result<Self> {
        let (start, end) = (range.start, range.end);
        Backend::resolve(backend.name())?;
        if gaps
            .iter()
            .any(|&t| t < start || t >= end.saturating_sub(2))
        {
            return Err("gap outside scored interval".into());
        }
        let state = ReusableExecution::new(d, start, end, costs, budget)?;
        Ok(Self {
            d,
            start,
            end,
            gaps,
            state,
            backend,
            scorer,
            budget,
            work: Work::default(),
        })
    }
    pub fn state_work(&self) -> &crate::backtest::ChangeWork {
        &self.state.work
    }
    pub fn state_bytes(&self) -> usize {
        self.state.payload_bytes
    }
    pub fn run(&mut self, source: &mut dyn PageSource, sink: &mut dyn Sink) -> Result<()> {
        while let Some(page) = source.next_page()? {
            self.page(&page, sink, None)?;
        }
        Ok(())
    }
    pub fn page(
        &mut self,
        page: &Page,
        sink: &mut dyn Sink,
        mut capture: Option<&mut dyn Write>,
    ) -> Result<()> {
        let req = &page.requests;
        if req.is_empty() {
            return Ok(());
        }
        if req.len() > 4096
            || req.iter().any(|r| {
                r.root >= page.graph.nodes.len()
                    || r.rules.is_empty()
                    || r.rules.len() > 8194
                    || r.rules.iter().any(|r| !r.threshold.is_finite())
            })
        {
            return Err("invalid bounded page request".into());
        }
        let roots = req.iter().map(|r| r.root).collect::<Vec<_>>();
        let deps = page.graph.dependencies(&roots).len();
        let series_bytes = self
            .d
            .len()
            .checked_mul(8)
            .and_then(|b| b.checked_mul(deps + roots.len() + 8))
            .ok_or("page payload overflow")?;
        let rule_count = req.iter().map(|r| r.rules.len()).sum::<usize>();
        let result_bytes = rule_count
            .checked_mul(self.state.scenarios())
            .and_then(|v| v.checked_mul(std::mem::size_of::<Metrics>()))
            .ok_or("result block overflow")?;
        if series_bytes
            .checked_add(result_bytes)
            .ok_or("page size overflow")?
            > self.budget
        {
            if req.len() == 1 {
                return Err(
                    "one request exceeds page numerical/result budget; reduce rule block".into(),
                );
            }
            let mid = req.len() / 2;
            for part in [&req[..mid], &req[mid..]] {
                let p = Page {
                    graph: page.graph.clone(),
                    requests: part.to_vec(),
                };
                match capture.as_mut() {
                    Some(w) => self.page(&p, sink, Some(&mut **w))?,
                    None => self.page(&p, sink, None)?,
                }
            }
            return Ok(());
        }
        self.work.pages += 1;
        self.work.programs += req.len() as u64;
        self.work.rules += rule_count as u64;
        let timer = Instant::now();
        let store = family::prepare(
            &page.graph,
            self.d,
            &family::boundaries(&page.graph, &roots),
            self.budget,
            self.backend,
            None,
        )?;
        self.work.nodes += store.work.nodes as u64;
        self.work.materialized_peak = self
            .work
            .materialized_peak
            .max(store.work.payload + roots.len() * self.d.len() * 8 + result_bytes);
        let mut xs = Vec::with_capacity(req.len());
        for r in req {
            let p = family::Program::compile(&page.graph, r.root, &store, None)?;
            self.work.fused_nodes += p.point_nodes as u64;
            let mut x = p
                .execute(&store, None, &[], self.backend, true)?
                .1
                .ok_or("missing numeric output")?;
            if let Some(w) = capture.as_mut() {
                for v in &x {
                    w.write_all(&v.to_le_bytes()).map_err(|e| e.to_string())?;
                }
            }
            for &j in &self.gaps {
                x[j] = f64::NAN;
            }
            xs.push(x);
        }
        self.work.numeric_seconds += timer.elapsed().as_secs_f64();
        let timer = Instant::now();
        let mut results = req
            .iter()
            .map(|r| vec![None; r.rules.len()])
            .collect::<Vec<Vec<Option<Vec<Metrics>>>>>();
        let cross = matches!(self.scorer, Scorer::Delta | Scorer::Rebuild)
            || self.scorer == Scorer::Auto && rule_count <= req.len() * 16;
        if cross {
            self.work.cross_program_plans += 1;
            // Coordinate-major within a bounded page, serpentine program traversal.
            // Results are restored to original request/rule/scenario order below.
            let width = req.iter().map(|r| r.rules.len()).max().unwrap();
            for q in 0..width {
                for k in 0..req.len() {
                    let i = if q % 2 == 0 { k } else { req.len() - 1 - k };
                    if q >= req[i].rules.len() {
                        continue;
                    }
                    let detect = Instant::now();
                    let mask = kernels::threshold(
                        &xs[i][self.start..self.end - 2],
                        req[i].rules[q],
                        self.backend,
                    )?;
                    self.work.detection_seconds += detect.elapsed().as_secs_f64();
                    let mode = match self.scorer {
                        Scorer::Rebuild => TransitionMode::Rebuild,
                        Scorer::Delta => TransitionMode::Delta,
                        _ => TransitionMode::Auto,
                    };
                    results[i][q] = Some(self.state.score(&mask, mode)?);
                }
            }
        } else {
            for (i, r) in req.iter().enumerate() {
                match self.scorer {
                    Scorer::Replay => {
                        for (q, &rule) in r.rules.iter().enumerate() {
                            results[i][q] = Some(
                                self.state
                                    .reference_markets()
                                    .iter()
                                    .map(|m| m.score(&xs[i], rule))
                                    .collect::<Result<_>>()?,
                            );
                            self.work.replay_calls += self.state.scenarios() as u64;
                        }
                    }
                    Scorer::Legacy => {
                        let mm = self
                            .state
                            .reference_markets()
                            .iter()
                            .map(|m| m.full_thresholds(&xs[i], &r.rules))
                            .collect::<Result<Vec<_>>>()?;
                        for q in 0..r.rules.len() {
                            results[i][q] = Some(mm.iter().map(|v| v[q].clone()).collect());
                        }
                        self.work.event_sorts += self.state.scenarios() as u64;
                    }
                    _ => {
                        self.work.per_series_plans += 1;
                        let got = self.events(&xs[i], &r.rules)?;
                        for (q, v) in got.into_iter().enumerate() {
                            results[i][q] = Some(v);
                        }
                    }
                }
            }
        }
        self.work.scoring_seconds += timer.elapsed().as_secs_f64();
        let timer = Instant::now();
        for (i, r) in req.iter().enumerate() {
            for (q, ms) in results[i].iter().enumerate() {
                for (s, m) in ms
                    .as_ref()
                    .ok_or("unresolved page result")?
                    .iter()
                    .enumerate()
                {
                    sink.emit(r.address, q, s, m, self.d.interval)?;
                    self.work.emitted += 1;
                }
            }
        }
        self.work.emission_seconds += timer.elapsed().as_secs_f64();
        Ok(())
    }
    fn events(&mut self, x: &[f64], rules: &[crate::backtest::Rule]) -> Result<Vec<Vec<Metrics>>> {
        let detect = Instant::now();
        let mut values = x[self.start..self.end - 2]
            .iter()
            .copied()
            .enumerate()
            .filter_map(|(t, v)| if v.is_finite() { Some((v, t)) } else { None })
            .collect::<Vec<_>>();
        values.sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
        self.work.event_sorts += 1;
        let mut queries = (0..rules.len()).collect::<Vec<_>>();
        queries.sort_unstable_by(|&i, &j| {
            rules[i]
                .greater
                .cmp(&rules[j].greater)
                .then_with(|| {
                    let o = rules[i].threshold.partial_cmp(&rules[j].threshold).unwrap();
                    if rules[i].greater {
                        o.reverse()
                    } else {
                        o
                    }
                })
                .then(i.cmp(&j))
        });
        let mut words = vec![0; (self.state.len() + 63) / 64];
        let (mut next, mut last_dir) = (0, false);
        let mut out = vec![None; rules.len()];
        self.work.detection_seconds += detect.elapsed().as_secs_f64();
        for q in queries {
            let detect = Instant::now();
            let r = rules[q];
            if r.greater != last_dir {
                words.fill(0);
                next = 0;
                last_dir = r.greater;
            }
            while next < values.len() {
                let i = if r.greater {
                    values.len() - next - 1
                } else {
                    next
                };
                let (v, t) = values[i];
                if !r.active(v) {
                    break;
                }
                words[t / 64] |= 1 << (t % 64);
                next += 1;
            }
            self.work.detection_seconds += detect.elapsed().as_secs_f64();
            out[q] = Some(self.state.score(&words, TransitionMode::Auto)?);
        }
        out.into_iter()
            .map(|v| v.ok_or_else(|| "missing event result".into()))
            .collect()
    }
}
