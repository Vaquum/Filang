//! Anchor authoring feeds the same generic compiled-program evaluator that
//! accepts caller-supplied atom programs. No evaluator branches on anchor names.
use crate::{
    anchors::{self, Anchor},
    backtest::{metrics_from_ledger, Costs, Market, Metrics},
    data::{self, Data},
    engine, family,
    hash::sha256,
    kernels::Backend,
    lang::{Graph, Op},
    report::{self, num, quote},
    Result,
};
use std::{
    collections::HashMap,
    fmt::Write as _,
    fs,
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};
pub const METRICS:&str="net_return_pct,gross_return_pct,cagr_pct,max_drawdown_pct,sharpe_annualized_naive,trades,exposure_pct,mean_bps_per_bar,mean_trade_bps,periods";
pub const EDGES: [&str; 9] = [
    "2023-01-01",
    "2023-07-01",
    "2024-01-01",
    "2024-07-01",
    "2025-01-01",
    "2025-07-01",
    "2026-01-01",
    "2026-07-01",
    "2026-09-28",
];
fn values(m: &Metrics, interval: i64) -> [f64; 10] {
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
pub fn engine_id() -> Result<String> {
    Ok(sha256(
        &fs::read(std::env::current_exe().map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?,
    ))
}
pub fn catalog_id() -> Result<String> {
    let (g, a) = anchors::catalog()?;
    let mut s = String::from(
        "filang-anchor-v1|spot_open_v1|all-complete-fold-intervals|numeric-profile-v1",
    );
    for v in a {
        s += &g.identity(v.root);
        s += &v.key;
        s += &v.profile;
        for r in v.rules {
            write!(&mut s, "|{}|{:016x}", r.greater, r.threshold.to_bits()).unwrap();
        }
    }
    Ok(sha256(s.as_bytes()))
}
pub fn validate_gate(path: &str, digest: &str) -> Result<()> {
    let text = fs::read_to_string(path).map_err(|e| format!("parity gate required: {e}"))?;
    let seal =
        fs::read_to_string(format!("{path}.sha256")).map_err(|_| "parity gate seal missing")?;
    if sha256(text.as_bytes()) != seal.trim() {
        return Err("parity gate seal mismatch".into());
    }
    let mut m = HashMap::new();
    for l in text.lines() {
        let (k, v) = l.split_once('=').ok_or("bad gate format")?;
        if m.insert(k, v).is_some() {
            return Err("duplicate gate field".into());
        }
    }
    for (k, v) in [
        ("version", "1".to_string()),
        ("status", "PASS".to_string()),
        ("data_sha256", digest.into()),
        ("engine_sha256", engine_id()?),
        ("catalog_sha256", catalog_id()?),
    ] {
        if m.get(k).copied() != Some(v.as_str()) {
            return Err(format!("parity gate {k} mismatch"));
        }
    }
    let base = Path::new(path).parent().ok_or("gate parent")?;
    for (file, key) in [
        ("manifest.json", "manifest_sha256"),
        ("metrics.bin", "metrics_sha256"),
        ("verification.json", "verification_sha256"),
    ] {
        let bytes = fs::read(base.join(file)).map_err(|e| format!("gate evidence {file}: {e}"))?;
        if m.get(key).copied() != Some(sha256(&bytes).as_str()) {
            return Err(format!("gate evidence mismatch: {file}"));
        }
    }
    Ok(())
}
#[derive(Clone, Debug)]
pub struct Options {
    pub data: String,
    pub out: String,
    pub mode: String,
    pub backend: Backend,
    pub capture: bool,
    pub batch: usize,
    pub memory: usize,
}
pub(crate) fn anchor_json(g: &Graph, a: &Anchor) -> String {
    format!("{{\"key\":{},\"profile\":{},\"kind\":{},\"periods\":[{},{},{}],\"parent\":{},\"feature_id\":{},\"expression\":{},\"rules\":[{}]}}",quote(&a.key),quote(&a.profile),quote(&a.kind),a.periods[0],a.periods[1],a.periods[2],quote(&a.reference_key),quote(&g.identity(a.root)),quote(&g.expression(a.root)),a.rules.iter().map(|r|format!("{{\"greater\":{},\"threshold\":{}}}",r.greater,num(r.threshold))).collect::<Vec<_>>().join(","))
}
/// Generic graph runner. Metadata are emitted, never used to choose a kernel.
pub fn run(g: &Graph, requests: &[Anchor], o: &Options, gate: Option<&str>) -> Result<String> {
    if !["direct", "shared", "family"].contains(&o.mode.as_str()) || o.batch == 0 || o.batch > 256 {
        return Err("mode direct/shared/family; batch 1..256".into());
    }
    Backend::resolve(o.backend.name())?;
    let clock = Instant::now();
    let d = Data::read(&o.data, 14400)?;
    if let Some(p) = gate {
        validate_gate(p, &d.digest)?;
    }
    let edges = EDGES
        .iter()
        .map(|s| data::date(s))
        .collect::<Result<Vec<_>>>()?;
    if d.timestamps[0] > edges[0]
        || d.timestamps.last().unwrap() + d.interval < *edges.last().unwrap()
    {
        return Err("data must cover declared anchor regression period".into());
    }
    let lo = d.index(edges[0]);
    let hi = d.index(*edges.last().unwrap());
    let costs = [
        Costs {
            fee_bps: 5.0,
            slip_bps: 5.0,
        },
        Costs {
            fee_bps: 10.0,
            slip_bps: 10.0,
        },
    ];
    let markets = costs
        .iter()
        .map(|&c| Market::new(&d, lo, hi, c))
        .collect::<Result<Vec<_>>>()?;
    let gaps = edges[1..edges.len() - 1]
        .iter()
        .flat_map(|e| {
            let i = d.index(*e);
            [i - 2, i - 1]
        })
        .collect::<Vec<_>>();
    report::create_out(&o.out)?;
    let output = Path::new(&o.out);
    let manifest=format!("{{\"format\":1,\"role\":{},\"execution\":\"spot_open_v1\",\"data_sha256\":{},\"engine_sha256\":{},\"catalog_sha256\":{},\"rows\":{},\"interval\":{},\"start_index\":{},\"end_index\":{},\"gap_signal_indices\":[{}],\"metric_columns\":{},\"capture\":{},\"scenarios\":[[5,5],[10,10]],\"requests\":[{}]}}\n",quote(if gate.is_some(){"anchored_parameter_neighborhood_not_new_holdout"}else{"known_indicator_parity"}),quote(&d.digest),quote(&engine_id()?),quote(&catalog_id()?),d.len(),d.interval,lo,hi,gaps.iter().map(|i|i.to_string()).collect::<Vec<_>>().join(","),quote(METRICS),o.capture,requests.iter().map(|a|anchor_json(g,a)).collect::<Vec<_>>().join(","));
    report::write(output.join("manifest.json"), &manifest)?;
    let mut metrics =
        BufWriter::new(fs::File::create(output.join("metrics.bin")).map_err(|e| e.to_string())?);
    let mut features = if o.capture {
        Some(BufWriter::new(
            fs::File::create(output.join("features.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let mut traces = if o.capture && gate.is_none() {
        Some(BufWriter::new(
            fs::File::create(output.join("traces.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    // Data-scoped reuse is keyed by graph structure. A bounded optional bank
    // keeps only temporal dependency closures reused by at least two programs.
    let mut counts = vec![0usize; g.nodes.len()];
    for a in requests {
        for j in g.dependencies(&[a.root]) {
            counts[j] += 1;
        }
    }
    let mut bank_roots = vec![];
    if o.mode == "family" {
        for (id, &n) in counts.iter().enumerate() {
            if n > 1
                && matches!(
                    g.nodes[id].op,
                    Op::Mean(_) | Op::Std(_) | Op::Ema(_) | Op::Wilder(_) | Op::Min(_) | Op::Max(_)
                )
            {
                let mut trial = bank_roots.clone();
                trial.push(id);
                if (g.dependencies(&trial).len() + 8) * d.len() * 8 <= o.memory / 2 {
                    bank_roots.push(id);
                }
            }
        }
    }
    let timer = Instant::now();
    let bank = if bank_roots.is_empty() {
        None
    } else {
        Some(family::prepare(
            g,
            &d,
            &bank_roots,
            o.memory / 2,
            o.backend,
            None,
        )?)
    };
    let mut nodes = bank.as_ref().map_or(0, |b| b.work.nodes);
    let mut passes = bank.as_ref().map_or(0, |b| b.work.temporal_passes);
    let mut recurrence_lanes = bank.as_ref().map_or(0, |b| b.work.recurrence_lanes);
    let mut moment_nodes = bank.as_ref().map_or(0, |b| b.work.grouped_moment_nodes);
    let mut numerical = timer.elapsed().as_secs_f64();
    let mut scoring = 0.0;
    let mut hits = 0;
    let mut peak = 0;
    let mut fused = 0;
    let mut queries = 0usize;
    let mut cursor = 0;
    let mut behavior_hits = 0usize;
    let mut metrics_replays = 0usize;
    while cursor < requests.len() {
        let mut count = if o.mode == "direct" {
            1
        } else {
            o.batch.min(requests.len() - cursor)
        };
        while count > 1
            && (g
                .dependencies(
                    &requests[cursor..cursor + count]
                        .iter()
                        .map(|a| a.root)
                        .collect::<Vec<_>>(),
                )
                .len()
                + 8)
                * d.len()
                * 8
                > o.memory
        {
            count /= 2;
        }
        let batch = &requests[cursor..cursor + count];
        let roots = batch.iter().map(|a| a.root).collect::<Vec<_>>();
        let timer = Instant::now();
        let compiled = if o.mode == "family" {
            Some(family::prepare(
                g,
                &d,
                &family::boundaries(g, &roots),
                o.memory,
                o.backend,
                bank.as_ref(),
            )?)
        } else {
            None
        };
        let plain = if compiled.is_none() {
            Some(engine::evaluate_with(
                g, &d, &roots, o.memory, o.backend, None,
            )?)
        } else {
            None
        };
        if let Some(c) = &compiled {
            nodes += c.work.nodes;
            passes += c.work.temporal_passes;
            recurrence_lanes += c.work.recurrence_lanes;
            moment_nodes += c.work.grouped_moment_nodes;
            hits += c.work.cached;
            peak = peak.max(c.work.payload);
        }
        if let Some(c) = &plain {
            nodes += c.nodes_computed;
            peak = peak.max(c.payload_bytes);
            passes += g
                .dependencies(&roots)
                .iter()
                .filter(|i| {
                    matches!(
                        g.nodes[**i].op,
                        Op::Mean(_)
                            | Op::MeanSum(_)
                            | Op::StdSum(_)
                            | Op::Std(_)
                            | Op::Ema(_)
                            | Op::Wilder(_)
                            | Op::Min(_)
                            | Op::Max(_)
                    )
                })
                .count();
        }
        numerical += timer.elapsed().as_secs_f64();
        // Bounded exact behavior cache, never a hash-only match. Whole full-risk
        // vectors may be shared across unrelated programs under the same context.
        let mut behaviors: Vec<(Vec<u64>, [Metrics; 2])> = vec![];
        for a in batch {
            let timer = Instant::now();
            let mut x = if let Some(c) = &compiled {
                let p = family::Program::compile(g, a.root, c, bank.as_ref())?;
                fused += p.point_nodes;
                p.execute(c, bank.as_ref(), &[], o.backend, true)?
                    .1
                    .unwrap()
            } else {
                plain.as_ref().unwrap().values[&a.root].clone()
            };
            if let Some(f) = features.as_mut() {
                for v in &x {
                    f.write_all(&v.to_le_bytes()).map_err(|e| e.to_string())?;
                }
            }
            for &i in &gaps {
                x[i] = f64::NAN;
            }
            numerical += timer.elapsed().as_secs_f64();
            let timer = Instant::now();
            let results = if o.mode == "family" && a.rules.len() > 8 {
                let per = markets
                    .iter()
                    .map(|m| m.full_thresholds(&x, &a.rules))
                    .collect::<Result<Vec<_>>>()?;
                metrics_replays += 2;
                per
            } else {
                let mut per = [vec![], vec![]];
                for &rule in &a.rules {
                    let mask = crate::kernels::threshold(&x[lo..hi - 2], rule, o.backend)?;
                    let got = if o.mode == "family" {
                        behaviors
                            .iter()
                            .find(|(m, _)| *m == mask)
                            .map(|(_, v)| v.clone())
                    } else {
                        None
                    };
                    let mm = if let Some(v) = got {
                        behavior_hits += 1;
                        v
                    } else {
                        let p = (0..hi - lo - 2)
                            .map(|i| mask[i / 64] >> (i % 64) & 1 != 0)
                            .collect::<Vec<_>>();
                        let mut v = vec![];
                        for m in &markets {
                            v.push(metrics_from_ledger(&m.position_ledger(&p)?, d.interval)?);
                        }
                        metrics_replays += 2;
                        let result = [v[0].clone(), v[1].clone()];
                        if o.mode == "family" && behaviors.len() < 128 {
                            behaviors.push((mask, result.clone()));
                        }
                        result
                    };
                    for (i, v) in mm.into_iter().enumerate() {
                        per[i].push(v);
                    }
                }
                per.into_iter().collect()
            };
            scoring += timer.elapsed().as_secs_f64();
            for i in 0..a.rules.len() {
                if let Some(trace) = traces.as_mut() {
                    let p = x[lo..hi - 2]
                        .iter()
                        .map(|v| a.rules[i].active(*v))
                        .collect::<Vec<_>>();
                    for market in &markets {
                        let rows = market.position_ledger(&p)?;
                        let (mut log_equity, mut trade) = (0.0, 0.0);
                        for r in rows {
                            log_equity += r.net.ln_1p();
                            if r.active {
                                trade += r.net.ln_1p();
                            }
                            let gain = if r.exit { trade.exp_m1() } else { f64::NAN };
                            for v in [
                                r.active as u8 as f64,
                                r.entry as u8 as f64,
                                r.exit as u8 as f64,
                                r.gross,
                                r.net,
                                log_equity.exp(),
                                gain,
                            ] {
                                trace
                                    .write_all(&v.to_le_bytes())
                                    .map_err(|e| e.to_string())?;
                            }
                            if r.exit {
                                trade = 0.0;
                            }
                        }
                    }
                }
                for result in &results {
                    for v in values(&result[i], d.interval) {
                        metrics
                            .write_all(&v.to_le_bytes())
                            .map_err(|e| e.to_string())?;
                    }
                    queries += 1;
                }
            }
        }
        cursor += count;
    }
    metrics.flush().map_err(|e| e.to_string())?;
    if let Some(t) = traces.as_mut() {
        t.flush().map_err(|e| e.to_string())?;
    }
    if let Some(f) = features.as_mut() {
        f.flush().map_err(|e| e.to_string())?;
    }
    let summary=format!("{{\"version\":3,\"mode\":{},\"backend\":{},\"threads\":1,\"program_requests\":{},\"structurally_distinct_roots\":{},\"full_metric_queries\":{},\"physical_numeric_nodes\":{},\"temporal_history_passes\":{},\"grouped_moment_outputs\":{},\"recurrence_lanes\":{},\"prepared_hits\":{},\"fused_point_nodes\":{},\"behavior_reuses\":{},\"metric_evaluator_invocations\":{},\"bank_payload_bytes\":{},\"batch_payload_peak_bytes\":{},\"numerical_seconds\":{},\"scoring_seconds\":{},\"total_internal_seconds\":{},\"metrics_sha256\":{}}}\n",quote(&o.mode),quote(o.backend.name()),requests.len(),family::distinct_roots(&requests.iter().map(|a|a.root).collect::<Vec<_>>()),queries,nodes,passes,moment_nodes,recurrence_lanes,hits,fused,behavior_hits,metrics_replays,bank.as_ref().map_or(0,|b|b.work.payload),peak,num(numerical),num(scoring),num(clock.elapsed().as_secs_f64()),quote(&sha256(&fs::read(output.join("metrics.bin")).map_err(|e|e.to_string())?)));
    report::write(output.join("summary.json"), &summary)?;
    Ok(summary)
}
