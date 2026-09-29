//! Known-indicator authoring for the generic page engine. Only this adapter
//! knows catalog labels and parity-campaign dates. It never chooses an indicator kernel.
use crate::{
    anchor_run::{self, Options},
    anchors::{self, Anchor},
    backtest::{Costs, Market},
    data::{self, Data},
    hash::Sha256,
    lang::Graph,
    paged::{BinarySink, Executor, Page, PageSource, Request, Scorer},
    report, Result,
};
use std::{
    fs::File,
    io::{BufReader, BufWriter, Read, Write},
    path::Path,
    time::Instant,
};
/// Bounded sequential authoring state. Clamped duplicate periods are skipped
/// arithmetically; no set growing with the number of generated programs is held.
pub struct AnchorPages {
    base: Vec<Anchor>,
    parents: Vec<Anchor>,
    fixed: usize,
    parent: usize,
    d: isize,
    e: isize,
    radius: usize,
    thresholds: usize,
    page_size: usize,
    neighbors: bool,
    next_address: u64,
}
impl AnchorPages {
    pub fn new(radius: Option<usize>, thresholds: usize, page_size: usize) -> Result<Self> {
        if radius.map_or(false, |r| r > 32)
            || !(3..=4097).contains(&thresholds)
            || thresholds % 2 == 0
            || page_size == 0
            || page_size > 256
        {
            return Err("radius<=32, odd thresholds 3..4097, page_size 1..256".into());
        }
        let (_, base) = anchors::catalog()?;
        let parents = base
            .iter()
            .filter(|a| a.profile == "talib")
            .cloned()
            .collect();
        let r = radius.unwrap_or(0);
        Ok(Self {
            base,
            parents,
            fixed: 0,
            parent: 0,
            d: -(r as isize),
            e: -(r as isize),
            radius: r,
            thresholds,
            page_size,
            neighbors: radius.is_some(),
            next_address: 0,
        })
    }
    fn next(&mut self, g: &mut Graph) -> Result<Option<Anchor>> {
        if self.fixed < self.base.len() {
            let mut a = self.base[self.fixed].clone();
            self.fixed += 1;
            a.root = anchors::expand(g, &a.kind, a.periods, &a.profile)?;
            return Ok(Some(a));
        }
        if !self.neighbors {
            return Ok(None);
        }
        let r = self.radius as isize;
        while self.parent < self.parents.len() {
            let a = &self.parents[self.parent];
            let paired = a.kind == "macd" || a.kind == "ema_cross";
            let (d, e) = (self.d, if paired { self.e } else { 0 });
            if paired && self.e < r {
                self.e += 1;
            } else {
                self.e = -r;
                self.d += 1;
            }
            if d > r {
                self.parent += 1;
                self.d = -r;
                self.e = -r;
                continue;
            }
            let mut p = a.periods;
            p[0] = (p[0] as isize + d).max(2) as usize;
            if paired {
                p[1] = (p[1] as isize + e).max(2) as usize;
            }
            if d > -r && p[0] == (a.periods[0] as isize + d - 1).max(2) as usize {
                continue;
            }
            if paired
                && (p[0] >= p[1]
                    || e > -r && p[1] == (a.periods[1] as isize + e - 1).max(2) as usize)
            {
                continue;
            }
            let root = anchors::expand(g, &a.kind, p, "talib")?;
            let (center, span) = match a.kind.as_str() {
                "rsi" => (0.0, 0.8),
                "bollinger" => (0.0, 3.0),
                "channel" => (0.5, 0.49),
                "atr" => (0.02, 0.019),
                _ => (0.0, 0.03),
            };
            let rules = (0..self.thresholds)
                .flat_map(|i| {
                    let threshold =
                        center + span * (2.0 * i as f64 / (self.thresholds - 1) as f64 - 1.0);
                    [false, true].map(move |greater| crate::backtest::Rule { threshold, greater })
                })
                .collect();
            return Ok(Some(Anchor {
                key: format!("{}_d{d}_e{e}", a.key),
                profile: a.profile.clone(),
                kind: a.kind.clone(),
                periods: p,
                root,
                rules,
                reference_key: a.key.clone(),
            }));
        }
        Ok(None)
    }
    pub fn next_authored(&mut self) -> Result<Option<(Page, Vec<Anchor>)>> {
        let mut g = Graph::new();
        let mut meta = Vec::new();
        let mut requests = Vec::new();
        for _ in 0..self.page_size {
            if let Some(a) = self.next(&mut g)? {
                requests.push(Request {
                    address: self.next_address,
                    root: a.root,
                    rules: a.rules.clone(),
                });
                self.next_address = self.next_address.checked_add(1).ok_or("address overflow")?;
                meta.push(a);
            } else {
                break;
            }
        }
        if requests.is_empty() {
            Ok(None)
        } else {
            Ok(Some((Page { graph: g, requests }, meta)))
        }
    }
}
impl PageSource for AnchorPages {
    fn next_page(&mut self) -> Result<Option<Page>> {
        Ok(self.next_authored()?.map(|p| p.0))
    }
}
fn scorer(mode: &str) -> Result<Scorer> {
    Scorer::parse(mode.strip_prefix("state-").unwrap_or(if mode == "state" {
        "auto"
    } else {
        mode
    }))
}
pub fn run(
    o: &Options,
    gate: Option<&str>,
    radius: Option<usize>,
    thresholds: usize,
    output_all: bool,
) -> Result<String> {
    if o.capture && !output_all {
        return Err("parity capture requires exhaustive output".into());
    }
    let clock = Instant::now();
    let d = Data::read(&o.data, 14400)?;
    if let Some(g) = gate {
        anchor_run::validate_gate(g, &d.digest)?;
    }
    let edges = anchor_run::EDGES
        .iter()
        .map(|s| data::date(s))
        .collect::<Result<Vec<_>>>()?;
    if d.timestamps[0] > edges[0]
        || d.timestamps.last().unwrap() + d.interval < *edges.last().unwrap()
    {
        return Err("data do not cover parity contract".into());
    }
    let lo = d.index(edges[0]);
    let hi = d.index(*edges.last().unwrap());
    let gaps = edges[1..edges.len() - 1]
        .iter()
        .flat_map(|e| {
            let i = d.index(*e);
            [i - 2, i - 1]
        })
        .collect::<Vec<_>>();
    let costs = [
        Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        },
        Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
    ];
    let mut executor = Executor::new(
        &d,
        lo..hi,
        gaps.clone(),
        &costs,
        o.backend,
        scorer(&o.mode)?,
        o.memory,
    )?;
    let mut source = AnchorPages::new(radius, thresholds, o.batch)?;
    report::create_out(&o.out)?;
    let out = Path::new(&o.out);
    let metric_path = out.join("metrics.bin");
    let mut sink = BinarySink::new(if output_all {
        Some(metric_path.as_path())
    } else {
        None
    })?;
    let mut manifest =
        BufWriter::new(File::create(out.join("manifest.json")).map_err(|e| e.to_string())?);
    write!(manifest,"{{\"format\":1,\"role\":{},\"execution\":\"spot_open_v1\",\"data_sha256\":{},\"engine_sha256\":{},\"catalog_sha256\":{},\"rows\":{},\"interval\":{},\"start_index\":{},\"end_index\":{},\"gap_signal_indices\":[{}],\"metric_columns\":{},\"capture\":{},\"scenarios\":[[5,5],[10,10]],\"requests\":[",report::quote(if gate.is_some(){"anchored_parameter_neighborhood_not_new_holdout"}else{"known_indicator_parity"}),report::quote(&d.digest),report::quote(&anchor_run::engine_id()?),report::quote(&anchor_run::catalog_id()?),d.len(),d.interval,lo,hi,gaps.iter().map(usize::to_string).collect::<Vec<_>>().join(","),report::quote(anchor_run::METRICS),o.capture).map_err(|e|e.to_string())?;
    let mut capture = if o.capture {
        Some(BufWriter::new(
            File::create(out.join("features.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let mut traces = if o.capture && gate.is_none() {
        Some(BufWriter::new(
            File::create(out.join("traces.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let trace_markets = costs
        .iter()
        .map(|&c| Market::new(&d, lo, hi, c))
        .collect::<Result<Vec<_>>>()?;
    let mut first = true;
    let mut specs_hash = Sha256::default();
    let mut program_count = 0u64;
    // In summary mode the request manifest is still a provenance stream for this
    // finite anchor cohort. Generic/open sources may instead retain domain/ranges.
    while let Some((page, meta)) = source.next_authored()? {
        for a in &meta {
            let spec = anchor_run::anchor_json(&page.graph, a);
            specs_hash.update(spec.as_bytes());
            if output_all {
                if !first {
                    write!(manifest, ",").map_err(|e| e.to_string())?;
                }
                first = false;
                write!(manifest, "{spec}").map_err(|e| e.to_string())?;
            }
            program_count += 1;
        }
        match capture.as_mut() {
            Some(w) => executor.page(&page, &mut sink, Some(w))?,
            None => executor.page(&page, &mut sink, None)?,
        }
        if let Some(tw) = traces.as_mut() {
            capture
                .as_mut()
                .unwrap()
                .flush()
                .map_err(|e| e.to_string())?;
            // Bounded page capture read; no extra reference history in timed no-capture runs.
            use std::io::{Seek, SeekFrom};
            let mut r =
                BufReader::new(File::open(out.join("features.bin")).map_err(|e| e.to_string())?);
            r.seek(SeekFrom::Start(
                (program_count - meta.len() as u64) * d.len() as u64 * 8,
            ))
            .map_err(|e| e.to_string())?;
            for a in &meta {
                let mut x = vec![0.0; d.len()];
                for v in &mut x {
                    let mut b = [0; 8];
                    r.read_exact(&mut b).map_err(|e| e.to_string())?;
                    *v = f64::from_le_bytes(b);
                }
                for &t in &gaps {
                    x[t] = f64::NAN;
                }
                for rule in &a.rules {
                    let pos = x[lo..hi - 2]
                        .iter()
                        .map(|v| rule.active(*v))
                        .collect::<Vec<_>>();
                    for m in &trace_markets {
                        let (mut eq, mut gain) = (0.0f64, 0.0f64);
                        for p in m.position_ledger(&pos)? {
                            eq += p.net.ln_1p();
                            if p.active {
                                gain += p.net.ln_1p();
                            }
                            for v in [
                                p.active as u8 as f64,
                                p.entry as u8 as f64,
                                p.exit as u8 as f64,
                                p.gross,
                                p.net,
                                eq.exp(),
                                if p.exit { gain.exp_m1() } else { f64::NAN },
                            ] {
                                tw.write_all(&v.to_le_bytes()).map_err(|e| e.to_string())?;
                            }
                            if p.exit {
                                gain = 0.;
                            }
                        }
                    }
                }
            }
        }
    }
    writeln!(manifest, "],\"request_domain\":{{\"source\":\"anchor-neighborhood-v1\",\"radius\":{},\"thresholds\":{},\"page_size\":{},\"expanded_manifest\":{}}}}}",radius.map_or("null".into(),|r|r.to_string()),thresholds,o.batch,output_all).map_err(|e|e.to_string())?;
    manifest.flush().map_err(|e| e.to_string())?;
    if let Some(w) = capture.as_mut() {
        w.flush().map_err(|e| e.to_string())?;
    }
    if let Some(w) = traces.as_mut() {
        w.flush().map_err(|e| e.to_string())?;
    }
    let (hash, records, bytes) = sink.finish()?;
    let summary=format!("{{\"version\":4,\"mode\":{},\"backend\":{},\"threads\":1,\"program_requests\":{},\"full_metric_queries\":{},\"metrics_sha256\":{},\"semantic_request_sha256\":{},\"all_metrics_computed\":true,\"metrics_bytes_written\":{},\"equivalent_unwritten_metric_bytes\":{},\"execution_state_payload_bytes\":{},\"total_internal_seconds\":{},\"page_work\":{},\"transition_work\":{}}}\n",report::quote(&o.mode),report::quote(o.backend.name()),program_count,records,report::quote(&hash),report::quote(&specs_hash.finish()),if output_all{bytes}else{0},if output_all{0}else{bytes},executor.state_bytes(),clock.elapsed().as_secs_f64(),executor.work.json(),executor.state_work().json());
    report::write(out.join("summary.json"), &summary)?;
    Ok(summary)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn paged_anchors_equal_finite_catalog_without_global_seen_set() {
        for radius in [0, 2, 10] {
            let (g, a) = anchors::neighborhood(radius, 3).unwrap();
            let mut source = AnchorPages::new(Some(radius), 3, 17).unwrap();
            let mut i = 0;
            while let Some((page, meta)) = source.next_authored().unwrap() {
                assert!(meta.len() <= 17);
                for r in meta {
                    assert_eq!(r.key, a[i].key);
                    assert_eq!(g.expression(a[i].root), page.graph.expression(r.root));
                    assert_eq!(r.rules.len(), a[i].rules.len());
                    for (x, y) in r.rules.iter().zip(&a[i].rules) {
                        assert_eq!(
                            (x.greater, x.threshold.to_bits()),
                            (y.greater, y.threshold.to_bits())
                        );
                    }
                    i += 1;
                }
            }
            assert_eq!(i, a.len());
        }
    }
}
