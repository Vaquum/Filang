//! Replay sealed walk-forward policies without reselection, including abstention folds.
use crate::{
    backtest::{metrics_from_ledger, Costs, Market, Period, Rule},
    data::Data,
    engine,
    hash::sha256,
    kernels::Backend,
    lang::{Graph, Id, SCALAR},
    packed::{majority, Mask},
    report::{self, num, quote},
    Result,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};
#[derive(Clone)]
struct Member {
    root: Id,
    rule: Rule,
    name: String,
    fid: String,
}
fn numeric<T: std::str::FromStr>(m: &BTreeMap<String, String>, k: &str) -> Result<T> {
    m.get(k)
        .ok_or_else(|| format!("missing {k}"))?
        .parse()
        .map_err(|_| format!("invalid {k}"))
}
pub fn run(
    data_path: &str,
    selection_path: &str,
    out: &str,
    stress: bool,
    backend: Backend,
) -> Result<String> {
    let clock = Instant::now();
    let text = fs::read_to_string(selection_path).map_err(|e| e.to_string())?;
    let seal = fs::read_to_string(format!("{selection_path}.sha256")).map_err(|e| e.to_string())?;
    if sha256(text.as_bytes()) != seal.trim() {
        return Err("walk selection hash mismatch".into());
    }
    if !text.starts_with("# filang-walk-selection-v1\n") {
        return Err("unsupported walk format".into());
    }
    let mut meta = BTreeMap::new();
    let mut lines = vec![];
    for line in text.lines() {
        if let Some(s) = line.strip_prefix("# ") {
            if let Some((k, v)) = s.split_once('=') {
                if meta.insert(k.into(), v.into()).is_some() {
                    return Err("duplicate metadata".into());
                }
            }
        } else {
            lines.push(line);
        }
    }
    if meta.get("execution").map(String::as_str) != Some("spot_open_v1")
        || meta.get("role").map(String::as_str) != Some("retrospective_walkforward_not_untouched")
    {
        return Err("unknown execution/research contract".into());
    }
    let interval = numeric::<i64>(&meta, "interval")?;
    let costs = Costs {
        fee_bps: numeric(&meta, if stress { "stress_fee_bps" } else { "fee_bps" })?,
        slip_bps: numeric(
            &meta,
            if stress {
                "stress_slip_bps"
            } else {
                "slip_bps"
            },
        )?,
    }
    .validate()?;
    let d = Data::read(data_path, interval)?;
    let raw = fs::read_to_string(data_path).map_err(|e| e.to_string())?;
    let discovery_rows = numeric::<usize>(&meta, "discovery_rows")?;
    if discovery_rows > d.len() {
        return Err("data shorter than discovery".into());
    }
    let prefix = raw
        .lines()
        .take(discovery_rows + 1)
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    if meta.get("discovery_sha256").map(String::as_str) != Some(sha256(prefix.as_bytes()).as_str())
    {
        return Err("evaluation history differs from sealed discovery".into());
    }
    if lines.first().copied()!=Some("fold\tstart\tend\tportfolio\tname\tfeature_id\tgreater\tthreshold_bits\tquantile_index\tscore\texpression"){return Err("bad walk header".into());}
    let mut g = Graph::new();
    let mut groups: BTreeMap<(usize, String), Vec<Member>> = BTreeMap::new();
    let mut ranges: BTreeMap<usize, (i64, i64)> = BTreeMap::new();
    for line in lines.iter().skip(1) {
        let p = line.split('\t').collect::<Vec<_>>();
        if p.len() != 11 {
            return Err("bad walk member".into());
        }
        let fold = p[0].parse::<usize>().map_err(|_| "bad fold")?;
        let start = p[1].parse::<i64>().map_err(|_| "bad start")?;
        let end = p[2].parse::<i64>().map_err(|_| "bad end")?;
        if fold >= 64
            || start >= end
            || d.timestamps[0] > start
            || *d.timestamps.last().unwrap() + interval < end
            || !p[3]
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
        {
            return Err("invalid walk range or portfolio".into());
        }
        if let Some(old) = ranges.insert(fold, (start, end)) {
            if old != (start, end) {
                return Err("inconsistent fold range".into());
            }
        }
        let root = g.parse(p[10])?;
        if g.nodes[root].unit != SCALAR || g.identity(root) != p[5] {
            return Err("feature identity/unit mismatch".into());
        }
        let rule = Rule {
            greater: p[6].parse().map_err(|_| "bad direction")?,
            threshold: f64::from_bits(
                u64::from_str_radix(p[7], 16).map_err(|_| "bad threshold bits")?,
            ),
        };
        if !rule.threshold.is_finite() {
            return Err("invalid threshold".into());
        }
        let members = groups.entry((fold, p[3].into())).or_default();
        if members.len() >= 31 || members.iter().any(|m| m.fid == p[5]) {
            return Err("too many or duplicate ensemble members".into());
        }
        members.push(Member {
            root,
            rule,
            name: p[4].into(),
            fid: p[5].into(),
        });
    }
    if ranges.is_empty() || groups.len() > 4096 {
        return Err("empty/oversized walk selection".into());
    }
    let mut previous_end = None;
    for (expected, (&fold, &(start, end))) in ranges.iter().enumerate() {
        if fold != expected || previous_end.map_or(false, |last| last != start) {
            return Err("folds must be numbered, contiguous and chronological".into());
        }
        previous_end = Some(end);
        let key = format!("prefix_{fold}");
        let info = meta.get(&key).ok_or("missing fold prefix")?;
        let (rows, hash) = info.split_once(',').ok_or("bad prefix metadata")?;
        let rows = rows.parse::<usize>().map_err(|_| "bad prefix row count")?;
        if rows != d.index(start) || rows > discovery_rows {
            return Err("prefix extends beyond selection as-of".into());
        }
        let prefix = raw.lines().take(rows + 1).collect::<Vec<_>>().join("\n") + "\n";
        if sha256(prefix.as_bytes()) != hash {
            return Err("fold prefix mismatch".into());
        }
    }
    let portfolios = groups
        .keys()
        .map(|(_, p)| p.clone())
        .collect::<BTreeSet<_>>();
    for fold in ranges.keys() {
        for p in &portfolios {
            if !groups.contains_key(&(*fold, p.clone())) {
                return Err("portfolio missing an outer fold".into());
            }
        }
    }
    let markets = ranges
        .iter()
        .map(|(&i, &(s, e))| Ok((i, Market::new(&d, d.index(s), d.index(e), costs)?)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let master_start = d.index(ranges[&0].0);
    let master_end = d.index(ranges[&(ranges.len() - 1)].1);
    let master_len = master_end - master_start - 2;
    let mut ledgers = portfolios
        .iter()
        .map(|p| (p.clone(), vec![Period::default(); master_len]))
        .collect::<BTreeMap<_, _>>();
    let mut masks = groups
        .iter()
        .map(|(key, m)| (key.clone(), vec![None; m.len()]))
        .collect::<BTreeMap<(usize, String), Vec<Option<Mask>>>>();
    type Occurrences = BTreeMap<Id, Vec<((usize, String), usize)>>;
    let mut uses: Occurrences = BTreeMap::new();
    for (key, members) in &groups {
        for (i, m) in members.iter().enumerate() {
            uses.entry(m.root).or_default().push((key.clone(), i));
        }
    }
    let roots = uses.keys().copied().collect::<Vec<_>>();
    let (mut cursor, mut nodes, mut simd) = (0, 0, 0);
    while cursor < roots.len() {
        let mut size = 32.min(roots.len() - cursor);
        let batch;
        loop {
            match engine::evaluate_with(
                &g,
                &d,
                &roots[cursor..cursor + size],
                128 * 1024 * 1024,
                backend,
                None,
            ) {
                Ok(b) => {
                    batch = b;
                    break;
                }
                Err(e) if e.contains("exceeds budget") && size > 1 => size = (size / 2).max(1),
                Err(e) => return Err(e),
            }
        }
        nodes += batch.nodes_computed;
        simd += batch.simd_nodes;
        for &root in &roots[cursor..cursor + size] {
            let x = batch.series(root, None)?;
            for (key, i) in &uses[&root] {
                let market = &markets[&key.0];
                let m = &groups[key][*i];
                masks.get_mut(key).unwrap()[*i] = Some(Mask::threshold(
                    &x[market.start..market.start + market.len],
                    m.rule,
                    backend,
                )?);
            }
        }
        cursor += size;
    }
    report::create_out(out)?;
    let mut fold_reports = vec![];
    for (key, members) in &groups {
        let market = &markets[&key.0];
        let input = masks
            .remove(key)
            .unwrap()
            .into_iter()
            .collect::<Option<Vec<_>>>()
            .ok_or("missing member mask")?;
        let mask = majority(&input, market.len)?;
        let ledger = market.position_ledger(&mask.unpack())?;
        let metrics = metrics_from_ledger(&ledger, interval)?;
        let offset = market.start - master_start;
        ledgers.get_mut(&key.1).unwrap()[offset..offset + market.len].copy_from_slice(&ledger);
        let name = if members.len() == 1 {
            members[0].name.as_str()
        } else {
            key.1.as_str()
        };
        let (s, e) = ranges[&key.0];
        fold_reports.push(format!("{{\"fold\":{},\"start\":{s},\"end\":{e},\"portfolio\":{},\"name\":{},\"members\":{},\"metrics\":{}}}",key.0,quote(&key.1),quote(name),members.len(),report::metrics(&metrics,interval)));
    }
    let uninterrupted = Market::new(&d, master_start, master_end, costs)?;
    ledgers.insert(
        "buy_hold_continuous".into(),
        uninterrupted.position_ledger(&vec![true; master_len])?,
    );
    let mut totals = vec![];
    for (label, ledger) in &ledgers {
        let m = metrics_from_ledger(ledger, interval)?;
        let positive = groups
            .keys()
            .filter(|(f, p)| {
                p == label && {
                    let market = &markets[f];
                    let offset = market.start - master_start;
                    ledger[offset..offset + market.len]
                        .iter()
                        .map(|r| r.net.ln_1p())
                        .sum::<f64>()
                        > 0.0
                }
            })
            .count();
        totals.push(format!(
            "{{\"portfolio\":{},\"positive_folds\":{},\"metrics\":{}}}",
            quote(label),
            if label == "buy_hold_continuous" {
                "null".into()
            } else {
                positive.to_string()
            },
            report::metrics(&m, interval)
        ));
        let mut file = BufWriter::new(
            fs::File::create(Path::new(out).join(format!("{label}.csv")))
                .map_err(|e| e.to_string())?,
        );
        writeln!(
            file,
            "signal_timestamp,entry_timestamp,end_timestamp,active,entry,exit,net,gross"
        )
        .map_err(|e| e.to_string())?;
        for (i, r) in ledger.iter().enumerate() {
            let t = master_start + i;
            writeln!(
                file,
                "{},{},{},{},{},{},{:.17},{:.17}",
                d.timestamps[t],
                d.timestamps[t + 1],
                d.timestamps[t + 2],
                r.active as u8,
                r.entry as u8,
                r.exit as u8,
                r.net,
                r.gross
            )
            .map_err(|e| e.to_string())?;
        }
        file.flush().map_err(|e| e.to_string())?;
        eprintln!(
            "walk {:24} net={:8.2}% drawdown={:6.2}% trades={}",
            label,
            m.lite.return_pct(),
            m.max_drawdown_pct,
            m.lite.entries
        );
    }
    let result=format!("{{\"version\":2,\"role\":\"retrospective_walkforward_not_untouched\",\"execution\":\"spot_open_v1\",\"cost_scenario\":{},\"fee_bps\":{},\"slip_bps\":{},\"interval_seconds\":{},\"folds\":{},\"rebalance_gap_intervals\":{},\"selection_sha256\":{},\"data_sha256\":{},\"backend\":{},\"numerical_nodes_computed\":{},\"simd_arithmetic_nodes\":{},\"total_seconds\":{},\"portfolios\":[{}],\"fold_results\":[{}]}}\n",quote(if stress{"stress"}else{"primary"}),num(costs.fee_bps),num(costs.slip_bps),interval,ranges.len(),2*(ranges.len()-1),quote(seal.trim()),quote(&d.digest),quote(backend.name()),nodes,simd,num(clock.elapsed().as_secs_f64()),totals.join(","),fold_reports.join(","));
    report::write(Path::new(out).join("evaluation.json"), &result)?;
    Ok(result)
}
