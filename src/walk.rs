//! Streaming native family discovery: one bounded program page, shared across time folds.
//! The only growing output is the requested final archive, not one record per readout.
use crate::{
    backtest::{Lite, Market, Rule},
    data::Data,
    engine::{self, Prepared},
    hash::sha256,
    lang::Graph,
    packed::Mask,
    quantiles,
    report::{self, num, quote},
    search::{self, Candidate},
    walk_config::WalkConfig,
    Result,
};
use std::{collections::BTreeMap, fmt::Write as _, fs, path::Path, time::Instant};
#[derive(Clone, Debug)]
pub struct Pick {
    pub expression: String,
    pub feature_id: String,
    pub name: String,
    pub policy_id: String,
    pub q: usize,
    pub greater: bool,
    pub threshold: f64,
    pub score: f64,
    pub address: Option<u64>,
}
fn compare(a: &Pick, b: &Pick) -> std::cmp::Ordering {
    let x = (a.score * 1e9).round();
    let y = (b.score * 1e9).round();
    y.partial_cmp(&x)
        .unwrap()
        .then(a.policy_id.cmp(&b.policy_id))
}
fn insert(archive: &mut Vec<Pick>, item: Pick, cap: usize) {
    if let Some(i) = archive.iter().position(|x| x.feature_id == item.feature_id) {
        if compare(&item, &archive[i]) != std::cmp::Ordering::Less {
            return;
        }
        archive.remove(i);
    }
    let pos = archive
        .binary_search_by(|x| compare(x, &item))
        .unwrap_or_else(|i| i);
    if pos < cap {
        archive.insert(pos, item);
        archive.truncate(cap);
    }
}
#[derive(Clone, Debug, Default)]
struct Work {
    addresses: u64,
    readouts: u64,
    contexts: u64,
    naive_contexts: u64,
    nodes: u64,
    hits: u64,
    simd: u64,
    peak: usize,
    proposals: u64,
    numerical: f64,
    scoring: f64,
}
impl Work {
    fn merge(&mut self, b: &Self) {
        self.addresses += b.addresses;
        self.readouts += b.readouts;
        self.contexts += b.contexts;
        self.naive_contexts += b.naive_contexts;
        self.nodes += b.nodes;
        self.hits += b.hits;
        self.simd += b.simd;
        self.peak = self.peak.max(b.peak);
        self.proposals += b.proposals;
        self.numerical += b.numerical;
        self.scoring += b.scoring;
    }
}
struct PageResult {
    pools: Vec<[Vec<Pick>; 3]>,
    work: Work,
}
fn mix(mut x: u64) -> u64 {
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^ (x >> 31)
}
pub fn page(c: &WalkConfig, index: u64, count: usize) -> Result<(Graph, Vec<Candidate>, usize)> {
    let mut cfg = c.base.clone();
    cfg.generated = count;
    cfg.seed = mix(c.base.seed ^ index.wrapping_mul(0x9e3779b97f4a7c15));
    search::generate(&cfg)
}
fn score(c: &WalkConfig, p: &[Lite], s: &[Lite], complexity: usize) -> Option<f64> {
    if p.iter().filter(|v| v.log_return > 0.0).count() < c.min_positive
        || s.iter().map(|v| v.log_return).sum::<f64>() <= 0.0
        || p.iter().any(|v| {
            v.entries < c.min_trades
                || v.exposure() < c.base.min_exposure
                || v.exposure() > c.base.max_exposure
        })
    {
        return None;
    }
    let mut vals = s
        .iter()
        .map(|v| v.sharpe(c.base.interval))
        .collect::<Vec<_>>();
    if vals.iter().any(|v| !v.is_finite()) {
        return None;
    }
    for v in &mut vals {
        *v = v.clamp(-5.0, 5.0);
    }
    let mean = vals.iter().sum::<f64>() / vals.len() as f64;
    let sd = (vals.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / vals.len() as f64).sqrt();
    vals.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = vals.len();
    let median = if n % 2 == 0 {
        (vals[n / 2 - 1] + vals[n / 2]) / 2.0
    } else {
        vals[n / 2]
    };
    let fitness = median
        - c.base.stability_penalty * sd
        - 0.25 * (-vals[0]).max(0.0)
        - c.base.complexity_penalty * complexity as f64;
    if fitness > 0.0 {
        Some(fitness)
    } else {
        None
    }
}
fn page_search(
    c: &WalkConfig,
    d: &Data,
    bank: Option<&Prepared>,
    markets: &[[Market; 2]],
    index: u64,
    count: usize,
    known_budget: usize,
) -> Result<PageResult> {
    let (g, mut candidates, proposals) = page(c, index, count)?;
    if index != 0 {
        candidates.retain(|v| v.group == "generated");
    }
    let mut pools = (0..c.outer.len() - 1)
        .map(|_| std::array::from_fn(|_| vec![]))
        .collect::<Vec<[Vec<Pick>; 3]>>();
    let ends = c.edges.iter().map(|t| d.index(*t)).collect::<Vec<_>>();
    let fit_start = d.index(c.base.train_start);
    let nq = c.base.quantiles.len();
    let mut work = Work {
        addresses: count as u64,
        proposals: proposals as u64,
        ..Work::default()
    };
    let (mut cursor, mut generated_slot) = (0, 0usize);
    while cursor < candidates.len() {
        let mut size = c.base.batch_size.min(candidates.len() - cursor);
        let batch;
        loop {
            let roots = candidates[cursor..cursor + size]
                .iter()
                .map(|v| v.root)
                .collect::<Vec<_>>();
            let clock = Instant::now();
            match engine::evaluate_with(&g, d, &roots, c.base.memory_bytes, c.backend, bank) {
                Ok(b) => {
                    batch = b;
                    work.numerical += clock.elapsed().as_secs_f64();
                    break;
                }
                Err(e) if e.contains("exceeds budget") && size > 1 => {
                    size = (size / 2).max(1);
                }
                Err(e) => return Err(e),
            }
        }
        work.nodes += batch.nodes_computed as u64;
        work.hits += batch.cached_nodes as u64;
        work.simd += batch.simd_nodes as u64;
        work.peak = work.peak.max(batch.payload_bytes);
        for cand in &candidates[cursor..cursor + size] {
            let address = if cand.group == "generated" {
                let a = index
                    .checked_mul(c.page_size as u64)
                    .and_then(|a| a.checked_add(generated_slot as u64))
                    .ok_or("address overflow")?;
                generated_slot += 1;
                Some(a)
            } else {
                None
            };
            if cand.fixed.is_some() {
                continue;
            }
            let x = batch.series(cand.root, bank)?;
            let clock = Instant::now();
            let cutoffs =
                quantiles::prefixes(x, fit_start, &ends, &c.base.quantiles, c.prefix_reuse)?;
            let rules = cutoffs
                .iter()
                .map(|row| {
                    row.iter()
                        .flat_map(|&threshold| {
                            [false, true].map(move |greater| Rule { greater, threshold })
                        })
                        .collect::<Vec<_>>()
                })
                .collect::<Vec<_>>();
            let calc = |j: usize| -> Result<Vec<Vec<Lite>>> {
                let valid = rules[j]
                    .iter()
                    .enumerate()
                    .filter(|(_, r)| r.threshold.is_finite())
                    .collect::<Vec<_>>();
                let rs = valid.iter().map(|(_, r)| **r).collect::<Vec<_>>();
                let scores = if c.scenario_reuse {
                    markets[j][0].score_scenarios(x, &rs, &[c.base.costs, c.stress])?
                } else {
                    markets[j]
                        .iter()
                        .map(|m| {
                            if c.base.scorer == "events" {
                                m.score_thresholds(x, &rs)
                            } else {
                                m.score_direct_summaries(x, &rs)
                            }
                        })
                        .collect::<Result<Vec<_>>>()?
                };
                let mut full = vec![vec![Lite::default(); nq * 2]; 2];
                for (ci, row) in scores.into_iter().enumerate() {
                    for ((original, _), v) in valid.iter().zip(row) {
                        full[ci][*original] = v;
                    }
                }
                Ok(full)
            };
            let cache = if c.window_reuse {
                Some((0..markets.len()).map(calc).collect::<Result<Vec<_>>>()?)
            } else {
                None
            };
            if c.window_reuse {
                work.contexts += markets.len() as u64;
                work.readouts += rules[..markets.len()]
                    .iter()
                    .map(|row| row.iter().filter(|r| r.threshold.is_finite()).count() as u64 * 2)
                    .sum::<u64>();
            }
            let expr = g.expression(cand.root);
            let fid = g.identity(cand.root);
            let complexity = g.dependencies(&[cand.root]).len();
            for (fold, &start) in c.outer[..c.outer.len() - 1].iter().enumerate() {
                let end_index = c.edges.iter().position(|t| *t == start).unwrap();
                let lo = end_index - c.inner;
                work.naive_contexts += c.inner as u64;
                let local;
                if let Some(ref cached) = cache {
                    local = cached[lo..end_index].to_vec();
                } else {
                    local = (lo..end_index).map(calc).collect::<Result<Vec<_>>>()?;
                    work.contexts += c.inner as u64;
                    work.readouts += rules[lo..end_index]
                        .iter()
                        .map(|row| {
                            row.iter().filter(|r| r.threshold.is_finite()).count() as u64 * 2
                        })
                        .sum::<u64>();
                }
                let raw = (0..nq * 2)
                    .map(|r| {
                        let primary = local.iter().map(|s| s[0][r]).collect::<Vec<_>>();
                        let stress = local.iter().map(|s| s[1][r]).collect::<Vec<_>>();
                        score(c, &primary, &stress, complexity)
                    })
                    .collect::<Vec<_>>();
                let mut best: Option<Pick> = None;
                for q in 0..nq {
                    for direction in 0..2 {
                        let range = q.saturating_sub(c.neighbor_radius)
                            ..(q + c.neighbor_radius + 1).min(nq);
                        let neighbors = range
                            .map(|q| raw[q * 2 + direction])
                            .collect::<Option<Vec<_>>>();
                        let fitness = match neighbors {
                            Some(v) => v.into_iter().fold(f64::INFINITY, f64::min),
                            None => continue,
                        };
                        let threshold = cutoffs[end_index][q];
                        if !threshold.is_finite() {
                            continue;
                        }
                        let policy_id = sha256(
                            format!(
                                "walk-policy-v1|{fid}|{}|{:016x}",
                                direction == 1,
                                c.base.quantiles[q].to_bits()
                            )
                            .as_bytes(),
                        );
                        let pick = Pick {
                            expression: expr.clone(),
                            feature_id: fid.clone(),
                            name: cand.name.clone(),
                            policy_id,
                            q,
                            greater: direction == 1,
                            threshold,
                            score: fitness,
                            address,
                        };
                        if best
                            .as_ref()
                            .map_or(true, |b| compare(&pick, b) == std::cmp::Ordering::Less)
                        {
                            best = Some(pick);
                        }
                    }
                }
                if let Some(pick) = best {
                    let group = if cand.group == "generated" { 0 } else { 2 };
                    insert(&mut pools[fold][group], pick.clone(), c.archive);
                    if address.map_or(false, |a| a < known_budget as u64) {
                        insert(&mut pools[fold][1], pick, c.archive);
                    }
                }
            }
            work.scoring += clock.elapsed().as_secs_f64();
        }
        cursor += size;
    }
    Ok(PageResult { pools, work })
}
fn mask_for(c: &WalkConfig, d: &Data, pick: &Pick, fold: usize) -> Result<Mask> {
    let mut g = Graph::new();
    let root = g.parse(&pick.expression)?;
    let end = c.edges.iter().position(|t| *t == c.outer[fold]).unwrap();
    let lo = end - c.inner;
    let prefix = d.prefix(d.index(c.outer[fold]));
    let batch = engine::evaluate_with(&g, &prefix, &[root], c.base.memory_bytes, c.backend, None)?;
    let x = batch.series(root, None)?;
    let ends = c.edges[lo..end]
        .iter()
        .map(|t| prefix.index(*t))
        .collect::<Vec<_>>();
    let qs = quantiles::prefixes(
        x,
        prefix.index(c.base.train_start),
        &ends,
        &[c.base.quantiles[pick.q]],
        c.prefix_reuse,
    )?;
    let mut mask = Mask::empty();
    for (j, row) in qs.iter().enumerate() {
        let a = ends[j];
        let b = prefix.index(c.edges[lo + j + 1]) - 2;
        mask.append(&Mask::threshold(
            &x[a..b],
            Rule {
                threshold: row[0],
                greater: pick.greater,
            },
            c.backend,
        )?);
    }
    Ok(mask)
}
fn diverse(
    c: &WalkConfig,
    d: &Data,
    archive: &[Pick],
    fold: usize,
    mask_count: &mut u64,
) -> Result<(Vec<Pick>, f64)> {
    let mut selected = vec![];
    let mut masks: Vec<Mask> = vec![];
    let mut max_overlap = 0.0f64;
    for pick in archive {
        let mask = mask_for(c, d, pick, fold)?;
        *mask_count += 1;
        let mut max = 0.0f64;
        for prior in &masks {
            max = max.max(mask.abs_correlation(prior, c.backend)?);
        }
        if max <= c.max_corr {
            selected.push(pick.clone());
            masks.push(mask);
            max_overlap = max_overlap.max(max);
            if selected.len() == c.base.top_k {
                break;
            }
        }
    }
    Ok((selected, max_overlap))
}
pub fn inspect(c: &WalkConfig) -> String {
    format!("{{\"feature_addresses\":\"{}\",\"address_start\":\"{}\",\"generation_pages\":\"{}\",\"page_size\":{},\"outer_folds\":{},\"unique_inner_windows\":{},\"naive_fold_windows\":{},\"threads\":{},\"backend\":{},\"status\":\"plan_only_no_feature_evaluation\"}}",c.addresses,c.address_start,c.page_count(),c.page_size,c.outer.len()-1,c.edges.len()-1,(c.outer.len()-1)*c.inner,c.threads,quote(c.backend.name()))
}
pub fn run(c: &WalkConfig) -> Result<String> {
    let clock = Instant::now();
    let d = Data::read(&c.base.data, c.base.interval)?;
    if d.timestamps[0] > c.base.train_start
        || d.timestamps.last().unwrap() + d.interval != c.base.validation_end
    {
        return Err(
            "walk discovery must end at final selection as-of; later rows forbidden".into(),
        );
    }
    for &t in c.edges.iter().chain(c.outer[..c.outer.len() - 1].iter()) {
        if d.index(t) < d.len() && d.timestamps[d.index(t)] != t {
            return Err("unaligned fold boundary".into());
        }
    }
    let mut seed_config = c.base.clone();
    seed_config.generated = 0;
    let (base_graph, controls, _) = search::generate(&seed_config)?;
    let known_budget = controls
        .iter()
        .filter(|v| v.group == "tuned_indicator")
        .count();
    let bank = if c.prepared {
        Some(engine::prepare(
            &base_graph,
            &d,
            c.base.memory_bytes,
            c.backend,
        )?)
    } else {
        None
    };
    let markets = c
        .edges
        .windows(2)
        .map(|w| {
            Ok([
                Market::new(&d, d.index(w[0]), d.index(w[1]), c.base.costs)?,
                Market::new(&d, d.index(w[0]), d.index(w[1]), c.stress)?,
            ])
        })
        .collect::<Result<Vec<_>>>()?;
    report::create_out(&c.base.out)?;
    let output = Path::new(&c.base.out);
    let mut pools = (0..c.outer.len() - 1)
        .map(|_| std::array::from_fn(|_| vec![]))
        .collect::<Vec<[Vec<Pick>; 3]>>();
    let mut total = Work::default();
    let first_page = c.address_start / c.page_size as u64;
    let pages = c.page_count();
    let mut next = 0;
    let mut next_report = 1u64;
    while next < pages {
        let width = (pages - next).min(c.threads as u64);
        let chunks =
            std::thread::scope(|scope| {
                let mut handles = vec![];
                for slot in 0..width {
                    let offset = next + slot;
                    let index = first_page + offset;
                    let count = (c.addresses - offset * c.page_size as u64).min(c.page_size as u64)
                        as usize;
                    let d = &d;
                    let markets = &markets;
                    let bank = bank.as_ref();
                    handles.push(scope.spawn(move || {
                        page_search(c, d, bank, markets, index, count, known_budget)
                    }));
                }
                handles
                    .into_iter()
                    .map(|h| {
                        h.join()
                            .map_err(|_| "native page worker panicked".to_string())?
                    })
                    .collect::<Result<Vec<_>>>()
            })?;
        for page in chunks {
            total.merge(&page.work);
            for (fold, groups) in page.pools.into_iter().enumerate() {
                for (group, items) in groups.into_iter().enumerate() {
                    for item in items {
                        insert(&mut pools[fold][group], item, c.archive);
                    }
                }
            }
        }
        next += width;
        if next >= next_report || next == pages {
            eprintln!(
                "walk addresses {}/{}; physical windows {}; native backend {}",
                total.addresses,
                c.addresses,
                total.contexts,
                c.backend.name()
            );
            while next_report <= next && next_report < u64::MAX {
                next_report = next_report.saturating_mul(2);
            }
        }
    }
    // Partial-address campaigns still evaluate the known indicator bank once.
    if first_page != 0 {
        let extra = page_search(c, &d, bank.as_ref(), &markets, 0, 0, known_budget)?;
        total.merge(&extra.work);
        for (fold, groups) in extra.pools.into_iter().enumerate() {
            for item in groups[2].iter() {
                insert(&mut pools[fold][2], item.clone(), c.archive);
            }
        }
    }
    let search_seconds = clock.elapsed().as_secs_f64();
    let raw = fs::read_to_string(&c.base.data).map_err(|e| e.to_string())?;
    let mut frozen=format!("# filang-walk-selection-v1\n# execution=spot_open_v1\n# role=retrospective_walkforward_not_untouched\n# interval={}\n# fee_bps={}\n# slip_bps={}\n# stress_fee_bps={}\n# stress_slip_bps={}\n# discovery_rows={}\n# discovery_sha256={}\n# generator=paged-v1\n",d.interval,c.base.costs.fee_bps,c.base.costs.slip_bps,c.stress.fee_bps,c.stress.slip_bps,d.len(),d.digest);
    writeln!(&mut frozen,"# seed={}\n# generation_page_size={}\n# feature_addresses={}\n# address_start={}\n# quantiles={}",c.base.seed,c.page_size,c.addresses,c.address_start,c.base.quantiles.iter().map(|q|format!("{q:.17}")).collect::<Vec<_>>().join(",")).unwrap();
    let mut lineage = String::new();
    let mut evidence = vec![];
    let mut mask_count = 0;
    let mut retained = 0;
    for (fold, &start) in c.outer[..c.outer.len() - 1].iter().enumerate() {
        let rows = d.index(start);
        let prefix = raw.lines().take(rows + 1).collect::<Vec<_>>().join("\n") + "\n";
        writeln!(
            &mut frozen,
            "# prefix_{fold}={rows},{}",
            sha256(prefix.as_bytes())
        )
        .unwrap();
    }
    frozen.push_str("fold\tstart\tend\tportfolio\tname\tfeature_id\tgreater\tthreshold_bits\tquantile_index\tscore\texpression\n");
    for (fold, fold_pools) in pools.iter().enumerate() {
        let mut portfolios: BTreeMap<String, Vec<Pick>> = BTreeMap::new();
        let groups = ["generated", "matched_generated", "indicator"];
        for (group, label) in groups.iter().enumerate() {
            let (selection, overlap) = diverse(c, &d, &fold_pools[group], fold, &mut mask_count)?;
            let count = selection.len();
            portfolios.insert(
                format!("{label}_top1"),
                fold_pools[group].first().cloned().into_iter().collect(),
            );
            portfolios.insert(format!("{label}_diverse"), selection);
            evidence.push(format!("{{\"fold\":{fold},\"group\":{},\"archive_retained\":{},\"selected\":{},\"maximum_absolute_behavior_correlation\":{},\"cash_fallback\":{}}}",quote(label),fold_pools[group].len(),count,num(overlap),count==0));
        }
        for (i, cand) in controls.iter().filter(|v| v.fixed.is_some()).enumerate() {
            let rule = cand.fixed.unwrap();
            let p = Pick {
                expression: base_graph.expression(cand.root),
                feature_id: base_graph.identity(cand.root),
                name: cand.name.clone(),
                policy_id: String::new(),
                q: usize::MAX,
                greater: rule.greater,
                threshold: rule.threshold,
                score: 0.0,
                address: None,
            };
            portfolios.insert(
                if cand.name == "Cash" {
                    "cash".into()
                } else if cand.name == "Buy_and_hold" {
                    "buy_hold".into()
                } else {
                    format!("fixed_{i}")
                },
                vec![p],
            );
        }
        for (label, mut picks) in portfolios {
            if picks.is_empty() {
                let root = base_graph
                    .nodes
                    .iter()
                    .position(|n| n.op == crate::lang::Op::Constant(1.0f64.to_bits()))
                    .unwrap();
                picks.push(Pick {
                    expression: base_graph.expression(root),
                    feature_id: base_graph.identity(root),
                    name: "Cash fallback: no eligible/diverse candidate".into(),
                    policy_id: String::new(),
                    q: usize::MAX,
                    greater: true,
                    threshold: 2.0,
                    score: 0.0,
                    address: None,
                });
            }
            for pick in picks {
                writeln!(&mut lineage,"{{\"fold\":{},\"portfolio\":{},\"feature_id\":{},\"policy_id\":{},\"generator_address\":{},\"quantile\":{},\"threshold\":{},\"greater\":{}}}",fold,quote(&label),quote(&pick.feature_id),quote(&pick.policy_id),pick.address.map_or("null".into(),|a|quote(&a.to_string())),if pick.q==usize::MAX{"null".into()}else{num(c.base.quantiles[pick.q])},num(pick.threshold),pick.greater).unwrap();
                retained += 1;
                writeln!(
                    &mut frozen,
                    "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:016x}\t{}\t{:.9}\t{}",
                    fold,
                    c.outer[fold],
                    c.outer[fold + 1],
                    label,
                    pick.name,
                    pick.feature_id,
                    pick.greater,
                    pick.threshold.to_bits(),
                    if pick.q == usize::MAX {
                        "fixed".into()
                    } else {
                        pick.q.to_string()
                    },
                    pick.score,
                    pick.expression
                )
                .unwrap();
            }
        }
    }
    report::write(output.join("lineage.jsonl"), &lineage)?;
    let seal = sha256(frozen.as_bytes());
    report::write(output.join("walk.tsv"), &frozen)?;
    report::write(output.join("walk.tsv.sha256"), &(seal.clone() + "\n"))?;
    report::write(
        output.join("selection.json"),
        &format!(
            "{{\"role\":\"historical_selection_only\",\"groups\":[{}]}}\n",
            evidence.join(",")
        ),
    )?;
    let summary=format!("{{\"version\":2,\"role\":\"retrospective_walkforward_not_untouched\",\"generator\":\"paged-v1\",\"generated_addresses\":\"{}\",\"global_unique_features\":null,\"global_uniqueness_note\":\"exact within each page only; no unbounded global seen-set\",\"pages\":\"{}\",\"page_size\":{},\"outer_folds\":{},\"indicator_feature_budget\":{},\"matched_generated_address_budget\":{},\"physical_contexts\":{},\"unfactored_context_requests\":{},\"scenario_readout_metrics\":{},\"numerical_nodes_computed\":{},\"prepared_node_hits\":{},\"simd_arithmetic_nodes\":{},\"basis_payload_bytes\":{},\"worker_payload_peak_bytes\":{},\"threads\":{},\"backend\":{},\"archive_bound_per_group_per_fold\":{},\"diversity_mask_replays\":{},\"retained_members\":{},\"per_readout_records_written\":0,\"search_seconds\":{},\"total_seconds\":{},\"worker_numerical_seconds_sum\":{},\"worker_scoring_seconds_sum\":{},\"frozen_sha256\":{},\"data_sha256\":{}}}\n",total.addresses,pages,c.page_size,c.outer.len()-1,known_budget,(known_budget as u64).saturating_sub(c.address_start).min(c.addresses),total.contexts,total.naive_contexts,total.readouts,total.nodes,total.hits,total.simd,bank.as_ref().map_or(0,|b|b.batch.payload_bytes),total.peak,c.threads,quote(c.backend.name()),c.archive,mask_count,retained,num(search_seconds),num(clock.elapsed().as_secs_f64()),num(total.numerical),num(total.scoring),quote(&seal),quote(&d.digest));
    report::write(output.join("summary.json"), &summary)?;
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn random_access_last_trillion_page_is_bounded_and_deterministic() {
        let c = WalkConfig::parse(include_str!("../examples/trillion-plan.cfg")).unwrap();
        let page_id = c.page_count() - 1;
        assert_eq!(page_id, 3_906_249_999);
        let (a, ca, _) = page(&c, page_id, c.page_size).unwrap();
        let (b, cb, _) = page(&c, page_id, c.page_size).unwrap();
        let ids_a = ca
            .iter()
            .filter(|p| p.group == "generated")
            .map(|p| a.identity(p.root))
            .collect::<Vec<_>>();
        let ids_b = cb
            .iter()
            .filter(|p| p.group == "generated")
            .map(|p| b.identity(p.root))
            .collect::<Vec<_>>();
        assert_eq!(ids_a, ids_b);
        assert_eq!(ids_a.len(), c.page_size);
        assert!(a.nodes.len() < 20_000);
        // Only a bounded page of definitions was generated. No historical data scored here.
    }
}
