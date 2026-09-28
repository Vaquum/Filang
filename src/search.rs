use crate::{
    backtest::{Costs, Lite, Market, Rule},
    config::Config,
    data::Data,
    engine,
    hash::sha256,
    lang::{Graph, Id, Op, SCALAR},
    report::{self, num, quote},
    Result,
};
use std::fmt::Write as _;
use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

#[derive(Clone, Debug)]
pub struct Candidate {
    pub root: Id,
    pub group: String,
    pub name: String,
    pub fixed: Option<Rule>,
}
#[derive(Clone, Debug)]
pub struct Selected {
    pub root: Id,
    pub group: String,
    pub name: String,
    pub id: String,
    pub rule: Rule,
    pub score: f64,
    pub train: Lite,
    pub validation: Lite,
    pub complexity: usize,
}
#[derive(Clone)]
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }
    fn index(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}
fn ratio_minus_one(g: &mut Graph, a: Id, b: Id) -> Id {
    let r = g.binary(Op::Div, a, b);
    let one = g.constant(1.0);
    g.binary(Op::Sub, r, one)
}
fn zscore(g: &mut Graph, a: Id, w: usize) -> Id {
    let m = g.unary(Op::Mean(w), a);
    let sd = g.unary(Op::Std(w), a);
    let d = g.binary(Op::Sub, a, m);
    g.binary(Op::Div, d, sd)
}
fn rsi(g: &mut Graph, c: Id, w: usize) -> Id {
    let d = g.unary(Op::Diff(1), c);
    let a = g.unary(Op::Abs, d);
    let up = g.binary(Op::Add, a, d);
    let u = g.unary(Op::Wilder(w), up);
    let den = g.unary(Op::Wilder(w), a);
    ratio_minus_one(g, u, den)
}
fn ema_cross(g: &mut Graph, c: Id, f: usize, s: usize) -> Id {
    let a = g.unary(Op::Ema(f), c);
    let b = g.unary(Op::Ema(s), c);
    ratio_minus_one(g, a, b)
}
fn macd(g: &mut Graph, c: Id, f: usize, s: usize, w: usize) -> Id {
    let a = g.unary(Op::Ema(f), c);
    let b = g.unary(Op::Ema(s), c);
    let d = g.binary(Op::Sub, a, b);
    let signal = g.unary(Op::Ema(w), d);
    let h = g.binary(Op::Sub, d, signal);
    g.binary(Op::Div, h, c)
}
fn add_candidate(
    out: &mut Vec<Candidate>,
    root: Id,
    group: &str,
    name: String,
    fixed: Option<Rule>,
) {
    out.push(Candidate {
        root,
        group: group.into(),
        name,
        fixed,
    });
}
/// Known formulas seed the language; generated outputs use independently varied topology.
pub fn generate(cfg: &Config) -> Result<(Graph, Vec<Candidate>, usize)> {
    let mut g = Graph::new();
    let o = g.source(0);
    let h = g.source(1);
    let l = g.source(2);
    let c = g.source(3);
    let v = g.source(4);
    let one = g.constant(1.0);
    let half = g.constant(0.5);
    let mut out = vec![];
    let mut pool = vec![];
    for &w in &cfg.windows {
        let r = rsi(&mut g, c, w);
        pool.push(r);
        add_candidate(&mut out, r, "tuned_indicator", format!("RSI({w})"), None);
        let r = zscore(&mut g, c, w);
        pool.push(r);
        add_candidate(
            &mut out,
            r,
            "tuned_indicator",
            format!("Bollinger_z({w})"),
            None,
        );
        let prev = g.unary(Op::Lag(w), c);
        let r = ratio_minus_one(&mut g, c, prev);
        pool.push(r);
        add_candidate(
            &mut out,
            r,
            "tuned_indicator",
            format!("Momentum({w})"),
            None,
        );
        let low = g.unary(Op::Min(w), l);
        let high = g.unary(Op::Max(w), h);
        let position = g.binary(Op::Sub, c, low);
        let range = g.binary(Op::Sub, high, low);
        let r = g.binary(Op::Div, position, range);
        pool.push(r);
        add_candidate(
            &mut out,
            r,
            "tuned_indicator",
            format!("Channel_position({w})"),
            None,
        );
        let ma = g.unary(Op::Mean(w), c);
        let r = ratio_minus_one(&mut g, c, ma);
        pool.push(r);
        add_candidate(
            &mut out,
            r,
            "tuned_indicator",
            format!("SMA_distance({w})"),
            None,
        );
        let vm = g.unary(Op::Mean(w), v);
        let vm = g.unary(Op::Lag(1), vm);
        let r = ratio_minus_one(&mut g, v, vm);
        pool.push(r);
        let prev = g.unary(Op::Lag(1), c);
        let ret = ratio_minus_one(&mut g, c, prev);
        let vol = g.unary(Op::Std(w), ret);
        pool.push(vol);
        let r = g.binary(Op::Div, ret, vol);
        pool.push(r);
    }
    for (i, &f) in cfg.windows.iter().enumerate() {
        for &s in cfg.windows.iter().skip(i + 1) {
            if f >= s {
                continue;
            }
            let r = ema_cross(&mut g, c, f, s);
            pool.push(r);
            add_candidate(
                &mut out,
                r,
                "tuned_indicator",
                format!("EMA_cross({f},{s})"),
                None,
            );
        }
    }
    let body = g.binary(Op::Sub, c, o);
    let range = g.binary(Op::Sub, h, l);
    let candle = g.binary(Op::Div, body, range);
    pool.push(candle);
    let rr = g.binary(Op::Div, range, c);
    pool.push(rr);
    let prev = g.unary(Op::Lag(1), c);
    let a = g.binary(Op::Sub, h, prev);
    let a = g.unary(Op::Abs, a);
    let b = g.binary(Op::Sub, l, prev);
    let b = g.unary(Op::Abs, b);
    let tr = g.binary(Op::Max2, range, a);
    let tr = g.binary(Op::Max2, tr, b);
    for &w in &cfg.windows {
        let mean = g.unary(Op::Mean(w), c);
        let gap = g.binary(Op::Sub, c, mean);
        let atr = g.unary(Op::Wilder(w), tr);
        let r = g.binary(Op::Div, gap, atr);
        pool.push(r);
        add_candidate(
            &mut out,
            r,
            "tuned_indicator",
            format!("ATR_normalized_distance({w})"),
            None,
        );
    }
    let fixed_gt = Some(Rule {
        threshold: 0.0,
        greater: true,
    });
    let r = rsi(&mut g, c, 14);
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "RSI(14)>50".into(),
        fixed_gt,
    );
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "RSI(14)<30".into(),
        Some(Rule {
            threshold: -0.4,
            greater: false,
        }),
    );
    let r = ema_cross(&mut g, c, 24, 96);
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "EMA(24)>EMA(96)".into(),
        fixed_gt,
    );
    let r = macd(&mut g, c, 12, 26, 9);
    pool.push(r);
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "MACD(12,26,9)_hist>0".into(),
        fixed_gt,
    );
    let ma = g.unary(Op::Mean(200), c);
    let r = ratio_minus_one(&mut g, c, ma);
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "Close>SMA(200)".into(),
        fixed_gt,
    );
    let r = zscore(&mut g, c, 20);
    add_candidate(
        &mut out,
        r,
        "fixed_indicator",
        "Bollinger(20)_z<-2".into(),
        Some(Rule {
            threshold: -2.0,
            greater: false,
        }),
    );
    add_candidate(&mut out, one, "control", "Buy_and_hold".into(), fixed_gt);
    add_candidate(
        &mut out,
        one,
        "control",
        "Cash".into(),
        Some(Rule {
            threshold: 2.0,
            greater: true,
        }),
    );
    let mut known: HashSet<_> = out.iter().map(|p| p.root).collect();
    let mut rng = Rng(cfg.seed);
    let mut made = 0;
    let mut attempts = 0;
    let base_pool = pool.len();
    while made < cfg.generated && attempts < cfg.generated.saturating_mul(100).max(1) {
        attempts += 1;
        let a = pool[rng.index(pool.len())];
        let b = pool[rng.index(base_pool)];
        let w = cfg.windows[rng.index(cfg.windows.len())];
        let k = cfg.lags[rng.index(cfg.lags.len())];
        let r = match cfg.templates[rng.index(cfg.templates.len())] {
            0 => {
                let a = g.unary(Op::Abs, a);
                g.binary(Op::Mul, a, b)
            }
            1 => {
                let a = g.unary(Op::Ema(w), a);
                g.binary(Op::Sub, a, b)
            }
            2 => {
                let p = g.binary(Op::Mul, a, b);
                g.unary(Op::Diff(k), p)
            }
            3 => {
                let p = g.binary(Op::Add, a, b);
                zscore(&mut g, p, w)
            }
            4 => {
                if rng.index(2) == 0 {
                    g.binary(Op::Min2, a, b)
                } else {
                    g.binary(Op::Max2, a, b)
                }
            }
            5 => {
                let ab = g.unary(Op::Abs, b);
                let den = g.binary(Op::Add, one, ab);
                g.binary(Op::Div, a, den)
            }
            6 => {
                let sum = g.binary(Op::Add, a, b);
                let avg = g.binary(Op::Mul, sum, half);
                g.unary(Op::Mean(w), avg)
            }
            _ => {
                let lag = g.unary(Op::Lag(k), a);
                let delta = g.binary(Op::Sub, lag, a);
                g.binary(Op::Mul, delta, b)
            }
        };
        if g.nodes[r].depth > cfg.max_depth
            || g.dependencies(&[r]).len() > cfg.max_nodes
            || !known.insert(r)
        {
            continue;
        }
        if g.nodes[r].unit != SCALAR {
            return Err("generator produced non-scalar feature".into());
        }
        made += 1;
        let name = format!("f_{}", &g.identity(r)[..16]);
        add_candidate(&mut out, r, "generated", name, None);
        // Allow nested unfamiliar subprograms, but keep the source bank dominant.
        if made % cfg.injection_stride == 0 {
            pool.push(r);
        }
    }
    if made != cfg.generated {
        return Err(format!(
            "only {made} unique programs after {attempts} proposals; widen limits"
        ));
    }
    Ok((g, out, attempts))
}
fn quantile(sorted: &[f64], q: f64) -> f64 {
    let pos = q * (sorted.len() - 1) as f64;
    let i = pos.floor() as usize;
    let a = pos - i as f64;
    sorted[i] * (1.0 - a) + sorted[(i + 1).min(sorted.len() - 1)] * a
}
fn eligible(c: &Config, a: Lite, b: Lite) -> bool {
    a.entries >= c.min_train_trades
        && b.entries >= c.min_validation_trades
        && a.log_return > 0.0
        && b.log_return > 0.0
        && a.exposure() >= c.min_exposure
        && a.exposure() <= c.max_exposure
        && b.exposure() >= c.min_exposure
        && b.exposure() <= c.max_exposure
}
fn score(c: &Config, folds: &[Lite], complexity: usize) -> f64 {
    let vals = folds
        .iter()
        .map(|s| {
            let v = s.sharpe(c.interval);
            if v.is_finite() {
                v
            } else {
                0.0
            }
        })
        .collect::<Vec<_>>();
    let mean = vals.iter().sum::<f64>() / vals.len() as f64;
    let std = (vals.iter().map(|s| (s - mean).powi(2)).sum::<f64>() / vals.len() as f64).sqrt();
    mean - c.stability_penalty * std - c.complexity_penalty * complexity as f64
}
fn better(a: &Selected, b: &Selected) -> bool {
    let aa = (a.score * 1e9).round();
    let bb = (b.score * 1e9).round();
    aa > bb || (aa == bb && a.id < b.id)
}

pub fn run(cfg: &Config) -> Result<String> {
    let clock = Instant::now();
    let d = Data::read(&cfg.data, cfg.interval)?;
    if d.timestamps[0] > cfg.train_start
        || d.timestamps.last().unwrap() + cfg.interval != cfg.validation_end
    {
        return Err("discovery CSV must include training history and END exactly at validation_end (exclusive); future rows are forbidden".into());
    }
    let train_lo = d.index(cfg.train_start);
    let val_lo = d.index(cfg.validation_start);
    let end = d.len();
    let mut markets = vec![
        Market::new(&d, train_lo, val_lo, cfg.costs)?,
        Market::new(&d, val_lo, end, cfg.costs)?,
    ];
    let mut block_ranges = vec![];
    for b in 0..cfg.blocks {
        let lo = val_lo + (end - val_lo) * b / cfg.blocks;
        let hi = val_lo + (end - val_lo) * (b + 1) / cfg.blocks;
        markets.push(Market::new(&d, lo, hi, cfg.costs)?);
        block_ranges.push((lo, hi));
    }
    let (g, candidates, proposals) = generate(cfg)?;
    report::create_out(&cfg.out)?;
    let out = Path::new(&cfg.out);
    let mut info: HashMap<Id, (String, String, usize)> = HashMap::new();
    for c in &candidates {
        info.entry(c.root).or_insert_with(|| {
            (
                g.identity(c.root),
                g.expression(c.root),
                g.dependencies(&[c.root]).len(),
            )
        });
    }
    let mut programs =
        BufWriter::new(fs::File::create(out.join("programs.tsv")).map_err(|e| e.to_string())?);
    writeln!(programs, "feature_id\tgroup\tname\tnodes\texpression").map_err(|e| e.to_string())?;
    for c in &candidates {
        let (id, expr, n) = &info[&c.root];
        writeln!(programs, "{id}\t{}\t{}\t{n}\t{expr}", c.group, c.name)
            .map_err(|e| e.to_string())?;
    }
    programs.flush().map_err(|e| e.to_string())?;
    let mut ledger =
        BufWriter::new(fs::File::create(out.join("discovery.jsonl")).map_err(|e| e.to_string())?);
    let mut winners = vec![];
    let mut fixed = vec![];
    let mut cursor = 0;
    let (
        mut physical_nodes,
        mut peak_payload,
        mut rule_count,
        mut invalid_fit,
        mut eligible_rules,
        mut sweep_count,
    ) = (0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    let setup_seconds = clock.elapsed().as_secs_f64();
    let compute = Instant::now();
    let (mut numerical_seconds, mut scoring_seconds) = (0.0, 0.0);
    while cursor < candidates.len() {
        let mut count = cfg.batch_size.min(candidates.len() - cursor);
        let batch;
        loop {
            let roots = candidates[cursor..cursor + count]
                .iter()
                .map(|x| x.root)
                .collect::<Vec<_>>();
            let estimate = (g.dependencies(&roots).len() + 4)
                .checked_mul(d.len())
                .and_then(|x| x.checked_mul(8))
                .ok_or("memory estimate overflow")?;
            if estimate <= cfg.memory_bytes {
                let timer = Instant::now();
                batch = engine::evaluate(&g, &d, &roots, cfg.memory_bytes)?;
                numerical_seconds += timer.elapsed().as_secs_f64();
                break;
            }
            if count == 1 {
                return Err(format!(
                    "one program exceeds numerical payload budget ({estimate} bytes)"
                ));
            }
            count = (count / 2).max(1);
        }
        physical_nodes += batch.nodes_computed;
        peak_payload = peak_payload.max(batch.payload_bytes);
        for cand in &candidates[cursor..cursor + count] {
            let x = &batch.values[&cand.root];
            let (fid, _expr, complexity) = &info[&cand.root];
            let mut rules = vec![];
            if let Some(r) = cand.fixed {
                rules.push(r);
            } else {
                let mut values = x[train_lo..val_lo]
                    .iter()
                    .copied()
                    .filter(|v| v.is_finite())
                    .collect::<Vec<_>>();
                if values.len() < 256 {
                    invalid_fit += 1;
                    continue;
                }
                values.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
                if values[values.len() - 1] - values[0] <= 1e-12 {
                    invalid_fit += 1;
                    continue;
                }
                let mut seen = HashSet::new();
                for &q in &cfg.quantiles {
                    let threshold = quantile(&values, q);
                    for greater in [false, true] {
                        if seen.insert((threshold.to_bits(), greater)) {
                            rules.push(Rule { threshold, greater });
                        }
                    }
                }
            }
            let timer = Instant::now();
            let scores = markets
                .iter()
                .map(|m| {
                    if cfg.scorer == "events" {
                        m.score_thresholds(x, &rules)
                    } else {
                        m.score_direct_summaries(x, &rules)
                    }
                })
                .collect::<Result<Vec<Vec<Lite>>>>()?;
            scoring_seconds += timer.elapsed().as_secs_f64();
            sweep_count += if cfg.scorer == "events" {
                markets.len()
            } else {
                0
            };
            rule_count += rules.len();
            let mut best: Option<Selected> = None;
            for (i, &rule) in rules.iter().enumerate() {
                let train = scores[0][i];
                let validation = scores[1][i];
                let folds = scores[2..].iter().map(|s| s[i]).collect::<Vec<_>>();
                let fitness = score(cfg, &folds, *complexity);
                let id = sha256(
                    format!(
                        "filang-readout-v1|{fid}|{}|{:016x}",
                        rule.greater,
                        rule.threshold.to_bits()
                    )
                    .as_bytes(),
                );
                let ok = cand.fixed.is_some() || eligible(cfg, train, validation);
                if ok && cand.fixed.is_none() {
                    eligible_rules += 1;
                }
                writeln!(ledger,"{{\"id\":{},\"feature_id\":{},\"group\":{},\"greater\":{},\"threshold\":{},\"training_net_pct\":{},\"validation_net_pct\":{},\"training_trades\":{},\"validation_trades\":{},\"validation_sharpe\":{},\"selection_score\":{},\"eligible\":{}}}",quote(&id),quote(fid),quote(&cand.group),rule.greater,num(rule.threshold),num(train.return_pct()),num(validation.return_pct()),train.entries,validation.entries,num(validation.sharpe(cfg.interval)),num(fitness),ok).map_err(|e|e.to_string())?;
                if !ok || !fitness.is_finite() {
                    continue;
                }
                let item = Selected {
                    root: cand.root,
                    group: cand.group.clone(),
                    name: cand.name.clone(),
                    id,
                    rule,
                    score: fitness,
                    train,
                    validation,
                    complexity: *complexity,
                };
                if best.as_ref().map_or(true, |b| better(&item, b)) {
                    best = Some(item);
                }
            }
            if let Some(b) = best {
                if cand.fixed.is_some() {
                    fixed.push(b);
                } else {
                    winners.push(b);
                }
            }
        }
        cursor += count;
        if cursor % 256 < count || cursor == candidates.len() {
            eprintln!(
                "features {cursor}/{}; readouts {rule_count}; numerical payload peak {:.1} MiB",
                candidates.len(),
                peak_payload as f64 / 1048576.0
            );
        }
    }
    ledger.flush().map_err(|e| e.to_string())?;
    winners.sort_by(|a, b| {
        if better(a, b) {
            std::cmp::Ordering::Less
        } else if better(b, a) {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    });
    let eligible_features = winners.len();
    let mut selected = vec![];
    for group in ["generated", "tuned_indicator"] {
        let count = if group == "generated" { cfg.top_k } else { 1 };
        selected.extend(
            winners
                .iter()
                .filter(|c| c.group == group)
                .take(count)
                .cloned(),
        );
    }
    selected.extend(fixed);
    let mut frozen=format!("# filang-selection-v1\n# execution=spot_open_v1\n# interval={}\n# fee_bps={}\n# slip_bps={}\n# evaluation_start={}\n# evaluation_end={}\n# discovery_sha256={}\n# discovery_rows={}\n# selection_resolution=0.000000001\nid\tgroup\tname\tgreater\tthreshold_bits\texpression\n",cfg.interval,cfg.costs.fee_bps,cfg.costs.slip_bps,cfg.evaluation_start,cfg.evaluation_end,d.digest,d.len());
    for s in &selected {
        writeln!(
            &mut frozen,
            "{}\t{}\t{}\t{}\t{:016x}\t{}",
            s.id,
            s.group,
            s.name,
            s.rule.greater,
            s.rule.threshold.to_bits(),
            info[&s.root].1
        )
        .expect("String writes are infallible");
    }
    let seal = sha256(frozen.as_bytes());
    report::write(out.join("frozen.tsv"), &frozen)?;
    report::write(out.join("frozen.tsv.sha256"), &(seal.clone() + "\n"))?;
    let mut rows = vec![];
    for s in &selected {
        let batch = engine::evaluate(&g, &d, &[s.root], cfg.memory_bytes)?;
        let m = markets[1].score(&batch.values[&s.root], s.rule)?;
        rows.push(format!("{{\"id\":{},\"group\":{},\"name\":{},\"expression\":{},\"threshold\":{},\"greater\":{},\"selection_score\":{},\"training_net_pct\":{},\"validation\":{}}}",quote(&s.id),quote(&s.group),quote(&s.name),quote(&info[&s.root].1),num(s.rule.threshold),s.rule.greater,num(s.score),num(s.train.return_pct()),report::metrics(&m,cfg.interval)));
    }
    let selected_json=format!("{{\"selection_order\":\"validation only; frozen before final evaluation\",\"candidates\":[{}]}}\n",rows.join(","));
    report::write(out.join("selected_validation.json"), &selected_json)?;
    let engine_sha = std::env::current_exe()
        .ok()
        .and_then(|p| fs::read(p).ok())
        .map(|b| sha256(&b))
        .unwrap_or_else(|| "unavailable".into());
    let summary=format!("{{\"engine_version\":\"0.1.0\",\"execution_contract\":\"spot_open_v1\",\"status\":\"discovery_complete_holdout_not_read\",\"data_sha256\":{},\"engine_sha256\":{},\"seed\":{},\"source_rows\":{},\"canonical_feature_programs\":{},\"generated_features\":{},\"generation_proposals\":{},\"readouts_evaluated\":{},\"market_metric_queries\":{},\"threshold_sweeps\":{},\"eligible_readouts\":{},\"eligible_features\":{},\"invalid_or_constant_fit_features\":{},\"physical_numerical_node_evaluations\":{},\"numerical_payload_peak_bytes\":{},\"batch_size\":{},\"scorer\":{},\"selected_candidates\":{},\"full_validation_replays\":{},\"frozen_sha256\":{},\"setup_seconds\":{},\"numerical_seconds\":{},\"scoring_seconds\":{},\"search_and_output_seconds\":{},\"total_internal_seconds\":{},\"validation_block_row_ranges\":[{}]}}\n",
        quote(&d.digest),quote(&engine_sha),cfg.seed,d.len(),info.len(),cfg.generated,proposals,rule_count,rule_count*markets.len(),sweep_count,eligible_rules,eligible_features,invalid_fit,physical_nodes,peak_payload,cfg.batch_size,quote(&cfg.scorer),selected.len(),selected.len(),quote(&seal),num(setup_seconds),num(numerical_seconds),num(scoring_seconds),num(compute.elapsed().as_secs_f64()),num(clock.elapsed().as_secs_f64()),block_ranges.iter().map(|(a,b)|format!("[{a},{b}]")).collect::<Vec<_>>().join(","));
    report::write(out.join("summary.json"), &summary)?;
    Ok(summary)
}

/// Evaluate only a sealed, previously selected list. Never rank by these results.
pub fn evaluate_frozen(
    data_path: &str,
    selection_path: &str,
    out_path: &str,
    stress: Option<Costs>,
) -> Result<String> {
    let clock = Instant::now();
    let text = fs::read_to_string(selection_path).map_err(|e| e.to_string())?;
    let seal = fs::read_to_string(format!("{selection_path}.sha256"))
        .map_err(|e| format!("selection seal required: {e}"))?;
    if seal.trim() != sha256(text.as_bytes()) {
        return Err("frozen selection hash mismatch".into());
    }
    let mut meta = HashMap::new();
    let mut lines = vec![];
    for l in text.lines() {
        if let Some(s) = l.strip_prefix("# ") {
            if let Some((k, v)) = s.split_once('=') {
                if meta.insert(k.to_string(), v.to_string()).is_some() {
                    return Err("duplicate frozen metadata".into());
                }
            }
        } else {
            lines.push(l);
        }
    }
    if !text.starts_with("# filang-selection-v1\n")
        || meta.get("execution").map(String::as_str) != Some("spot_open_v1")
    {
        return Err("unsupported frozen format/execution".into());
    }
    fn value<T: std::str::FromStr>(m: &HashMap<String, String>, k: &str) -> Result<T> {
        m.get(k)
            .ok_or_else(|| format!("missing frozen {k}"))?
            .parse()
            .map_err(|_| format!("bad frozen {k}"))
    }
    let interval = value::<i64>(&meta, "interval")?;
    let start = value::<i64>(&meta, "evaluation_start")?;
    let end = value::<i64>(&meta, "evaluation_end")?;
    let costs = stress
        .unwrap_or(Costs {
            fee_bps: value(&meta, "fee_bps")?,
            slip_bps: value(&meta, "slip_bps")?,
        })
        .validate()?;
    let d = Data::read(data_path, interval)?;
    if d.timestamps[0] > start || d.timestamps.last().unwrap() + interval < end {
        return Err("evaluation data do not cover declared holdout".into());
    }
    let discovery_rows = value::<usize>(&meta, "discovery_rows")?;
    let bytes = fs::read_to_string(data_path).map_err(|e| e.to_string())?;
    let prefix = bytes
        .lines()
        .take(discovery_rows + 1)
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    if meta.get("discovery_sha256").map(String::as_str) != Some(sha256(prefix.as_bytes()).as_str())
    {
        return Err("evaluation history differs from sealed discovery data".into());
    }
    if lines.first().copied() != Some("id\tgroup\tname\tgreater\tthreshold_bits\texpression") {
        return Err("bad frozen candidate header".into());
    }
    let market = Market::new(&d, d.index(start), d.index(end), costs)?;
    let mut g = Graph::new();
    let mut items = vec![];
    let mut ids = HashSet::new();
    for line in lines.iter().skip(1) {
        let p = line.split('\t').collect::<Vec<_>>();
        if p.len() != 6 {
            return Err("bad frozen row".into());
        }
        let root = g.parse(p[5])?;
        if g.nodes[root].unit != SCALAR {
            return Err("readout requires dimensionless root".into());
        }
        let rule = Rule {
            greater: p[3].parse().map_err(|_| "bad direction")?,
            threshold: f64::from_bits(u64::from_str_radix(p[4], 16).map_err(|_| "bad threshold")?),
        };
        if !rule.threshold.is_finite() {
            return Err("nonfinite threshold".into());
        }
        let expected = sha256(
            format!(
                "filang-readout-v1|{}|{}|{:016x}",
                g.identity(root),
                rule.greater,
                rule.threshold.to_bits()
            )
            .as_bytes(),
        );
        if expected != p[0] {
            return Err("candidate identity mismatch".into());
        }
        if !ids.insert(p[0].to_string()) {
            return Err("duplicate frozen candidate id".into());
        }
        items.push((
            p[0].to_string(),
            p[1].to_string(),
            p[2].to_string(),
            root,
            rule,
            p[5].to_string(),
        ));
    }
    if items.is_empty() || items.len() > 256 {
        return Err("frozen selection requires 1..256 candidates".into());
    }
    report::create_out(out_path)?;
    let mut rows = vec![];
    for (id, group, name, root, rule, expr) in &items {
        let batch = engine::evaluate(&g, &d, &[*root], 128 * 1024 * 1024)?;
        let x = &batch.values[root];
        let m = market.score(x, *rule)?;
        let row=format!("{{\"id\":{},\"group\":{},\"name\":{},\"expression\":{},\"greater\":{},\"threshold\":{},\"metrics\":{}}}",quote(id),quote(group),quote(name),quote(expr),rule.greater,num(rule.threshold),report::metrics(&m,interval));
        rows.push(row);
        eprintln!(
            "{:18} {:24} net={:8.2}% DD={:6.2}% trades={:4} Sharpe={:6.3}",
            group,
            name,
            m.lite.return_pct(),
            m.max_drawdown_pct,
            m.lite.entries,
            m.lite.sharpe(interval)
        );
        let mut trace = BufWriter::new(
            fs::File::create(Path::new(out_path).join(format!("{id}.csv")))
                .map_err(|e| e.to_string())?,
        );
        writeln!(
            trace,
            "signal_open_timestamp,feature,signal,entry_open_timestamp,period_end_open_timestamp"
        )
        .map_err(|e| e.to_string())?;
        for (t, &value) in x.iter().enumerate().skip(market.start).take(market.len) {
            writeln!(
                trace,
                "{},{},{},{},{}",
                d.timestamps[t],
                if value.is_finite() {
                    format!("{:.17}", value)
                } else {
                    String::new()
                },
                rule.active(value) as u8,
                d.timestamps[t + 1],
                d.timestamps[t + 2]
            )
            .map_err(|e| e.to_string())?;
        }
        trace.flush().map_err(|e| e.to_string())?;
    }
    let result=format!("{{\"engine_version\":\"0.1.0\",\"execution_contract\":\"spot_open_v1\",\"role\":\"frozen_final_evaluation_not_selection\",\"cost_scenario\":{},\"fee_bps\":{},\"slip_bps\":{},\"data_sha256\":{},\"frozen_sha256\":{},\"evaluation_start\":{},\"evaluation_end\":{},\"interval_seconds\":{},\"full_replays\":{},\"internal_seconds\":{},\"candidates\":[{}]}}\n",quote(if stress.is_some(){"predeclared_stress"}else{"primary"}),num(costs.fee_bps),num(costs.slip_bps),quote(&d.digest),quote(seal.trim()),start,end,interval,items.len(),num(clock.elapsed().as_secs_f64()),rows.join(","));
    report::write(Path::new(out_path).join("evaluation.json"), &result)?;
    Ok(result)
}
