//! Experiment commands for the exact bar-geometry source and frozen replay.
use crate::{
    backtest::{Costs, Market, Rule},
    data::{self, Data},
    geometry::{count_domain, GeometryEncoder, GeometryMode, GeometryPattern},
    geometry_run::{self, Config},
    hash::sha256,
    kernels::Backend,
    paged::metric_values,
    report::{self, num, quote},
    rules::{Mask, Program, Qualifier},
    Result,
};
use std::{
    collections::HashMap,
    fmt::Write as _,
    fs,
    io::{BufWriter, Write},
    path::{Path, PathBuf},
};

fn take(flags: &mut HashMap<String, String>, key: &str) -> Result<String> {
    flags.remove(key).ok_or_else(|| format!("missing {key}"))
}
fn option<T: std::str::FromStr>(
    flags: &mut HashMap<String, String>,
    key: &str,
    default: &str,
) -> Result<T> {
    flags
        .remove(key)
        .unwrap_or_else(|| default.into())
        .parse()
        .map_err(|_| format!("invalid {key}"))
}
fn finish(flags: &HashMap<String, String>) -> Result<()> {
    if flags.is_empty() {
        Ok(())
    } else {
        Err(format!("unknown geometry flags: {:?}", flags.keys()))
    }
}

pub fn cli(command: &str, mut flags: HashMap<String, String>) -> Result<String> {
    match command {
        "geometry-example" => example(&mut flags),
        "geometry-inspect" => {
            let path = take(&mut flags, "--config")?;
            finish(&flags)?;
            let raw = fs::read_to_string(path).map_err(|e| e.to_string())?;
            inspect(&Config::parse(&raw)?)
        }
        "geometry-prepare" | "geometry-sweep" => {
            let config = take(&mut flags, "--config")?;
            let out = take(&mut flags, "--out")?;
            let resume = option(&mut flags, "--resume", "false")?;
            let max_tasks = option(&mut flags, "--max-tasks", "0")?;
            let default_workers = std::thread::available_parallelism()
                .map(|v| v.get())
                .unwrap_or(1)
                .min(1024)
                .to_string();
            let workers = option(&mut flags, "--workers", &default_workers)?;
            let backend =
                Backend::resolve(&flags.remove("--backend").unwrap_or_else(|| "auto".into()))?;
            let proof = option(&mut flags, "--certificates", "true")?;
            let capture = option(&mut flags, "--capture", "false")?;
            finish(&flags)?;
            let raw = fs::read_to_string(config).map_err(|e| e.to_string())?;
            geometry_run::run(
                &raw,
                &out,
                resume,
                command == "geometry-prepare",
                max_tasks,
                workers,
                backend,
                proof,
                capture,
            )
        }
        "geometry-evaluate" => evaluate(&mut flags),
        "geometry-count" => {
            let bars: usize = option(&mut flags, "--bars", "2")?;
            let mode: GeometryMode = option(&mut flags, "--mode", "oriented")?;
            finish(&flags)?;
            Ok(format!(
                "{{\"version\":1,\"bars\":{bars},\"mode\":{},\"complete_patterns\":{}}}",
                quote(&mode.to_string()),
                quote(&count_domain(bars, mode)?.to_string())
            ))
        }
        _ => Err("unknown geometry command".into()),
    }
}

fn example(flags: &mut HashMap<String, String>) -> Result<String> {
    let out = take(flags, "--out")?;
    let profile = flags
        .remove("--profile")
        .unwrap_or_else(|| "trillion".into());
    let (windows, qualifiers) = match profile.as_str() {
        "smoke" => ("0,1;0,2", "plain"),
        "trillion" => ("0,1,2;0,2,4", "plain,persist:2,recent:3"),
        _ => return Err("geometry profile must be smoke or trillion".into()),
    };
    let data = flags
        .remove("--data")
        .unwrap_or_else(|| "data/btc4h/discovery.csv".into());
    let start = flags
        .remove("--start")
        .unwrap_or_else(|| "2024-01-01".into());
    let end = flags.remove("--end").unwrap_or_else(|| "2025-01-01".into());
    let interval: i64 = option(flags, "--interval-seconds", "14400")?;
    let mode: GeometryMode = option(flags, "--mode", "oriented")?;
    let windows = flags.remove("--windows").unwrap_or_else(|| windows.into());
    let qualifiers = flags
        .remove("--qualifiers")
        .unwrap_or_else(|| qualifiers.into());
    let rules = flags
        .remove("--rules")
        .unwrap_or_else(|| "(and s0 s1);(or s0 s1);(and s0 (not s1))".into());
    finish(flags)?;
    let text = format!(
        "# Complete global bar geometry; counts denote logical programs, not independent backtests.\nversion=1\ndata={data}\ninterval_seconds={interval}\nstart={start}\nend={end}\nmode={mode}\nwindows={windows}\nqualifiers={qualifiers}\nrules={rules}\nallow_same_bank=false\nnumeric_mib=64\nbank_mib=128\ntree_mib=256\nprepare_mib=128\ntask_states=128\nmax_task_nodes=100000000\nfee_bps=10\nslip_bps=10\n"
    );
    let config = Config::parse(&text)?;
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&out)
        .map_err(|e| e.to_string())?;
    file.write_all(text.as_bytes()).map_err(|e| e.to_string())?;
    Ok(format!(
        "{{\"status\":\"CREATED\",\"config\":{},\"profile\":{},\"requested_strategy_addresses\":{}}}",
        quote(&out),
        quote(&profile),
        quote(&config.logical()?.to_string())
    ))
}

pub fn inspect(config: &Config) -> Result<String> {
    let mut windows = Vec::new();
    for lags in &config.windows {
        let patterns = count_domain(lags.len(), config.mode)?;
        let conditions = patterns
            .checked_mul(config.qualifiers.len() as u128)
            .ok_or("geometry condition count overflow")?;
        windows.push(format!(
            "{{\"lags\":[{}],\"bars\":{},\"complete_patterns\":{},\"logical_conditions\":{}}}",
            lags.iter()
                .map(usize::to_string)
                .collect::<Vec<_>>()
                .join(","),
            lags.len(),
            quote(&patterns.to_string()),
            quote(&conditions.to_string())
        ));
    }
    Ok(format!(
        "{{\"version\":1,\"status\":\"PLAN_ONLY\",\"source\":\"geometry\",\"mode\":{},\"windows\":[{}],\"qualifiers\":{},\"templates\":{},\"allow_same_bank\":{},\"requested_strategy_addresses\":{},\"physical_work\":\"data_dependent_not_yet_executed\"}}",
        quote(&config.mode.to_string()),
        windows.join(","),
        config.qualifiers.len(),
        config.rules.len(),
        config.allow_same_bank,
        quote(&config.logical()?.to_string())
    ))
}

struct Selected {
    lags: Vec<usize>,
    qualifier: Qualifier,
    pattern: GeometryPattern,
}

fn sealed_text(path: &Path) -> Result<(String, String)> {
    let bytes = fs::read(path).map_err(|e| format!("read selection {}: {e}", path.display()))?;
    let digest = sha256(&bytes);
    let seal = fs::read_to_string(PathBuf::from(format!("{}.sha256", path.display())))
        .map_err(|e| format!("read selection checksum: {e}"))?;
    if seal.trim() != digest {
        return Err(format!("selection checksum mismatch: {}", path.display()));
    }
    let text = String::from_utf8(bytes).map_err(|_| "selection is not UTF-8")?;
    Ok((text, digest))
}

fn selection(text: &str) -> Result<Vec<Selected>> {
    let mut lines = text.lines();
    if lines.next() != Some("slot\tlags\tqualifier\tpattern") {
        return Err("geometry selection header".into());
    }
    let mut selected = Vec::new();
    for (slot, line) in lines.enumerate() {
        let fields: Vec<_> = line.split('\t').collect();
        if fields.len() != 4 || fields[0].parse::<usize>() != Ok(slot) || slot >= 2 {
            return Err("geometry selection slot/fields".into());
        }
        let lags: Vec<usize> = fields[1]
            .split(',')
            .map(|v| v.parse().map_err(|_| "geometry selection lag".to_owned()))
            .collect::<Result<_>>()?;
        if lags.first() != Some(&0) || lags.windows(2).any(|w| w[0] >= w[1]) {
            return Err("geometry selection lags must start at zero and increase".into());
        }
        let pattern: GeometryPattern = fields[3].parse()?;
        if pattern.len() != lags.len() {
            return Err("geometry selection pattern/window arity".into());
        }
        selected.push(Selected {
            lags,
            qualifier: Qualifier::parse(fields[2])?,
            pattern,
        });
    }
    if selected.len() != 2 {
        return Err("geometry selection requires two slots".into());
    }
    Ok(selected)
}

fn selected_mask(data: &Data, selected: &Selected) -> Result<Mask> {
    let len = data.len().checked_sub(2).ok_or("geometry replay history")?;
    let mut mask = Mask::empty(len);
    let mut encoder = GeometryEncoder::new(selected.lags.len(), selected.pattern.mode())?;
    let mut rows = vec![[0.; 4]; selected.lags.len()];
    let lag = *selected.lags.last().ok_or("empty geometry window")?;
    for t in lag..len {
        for (row, &offset) in rows.iter_mut().zip(&selected.lags) {
            let at = t - offset;
            *row = [
                data.columns[0][at],
                data.columns[1][at],
                data.columns[2][at],
                data.columns[3][at],
            ];
        }
        mask.set(t, encoder.encode_ohlc(&rows)? == &selected.pattern, true);
    }
    geometry_run::qualify(&mask, selected.qualifier)
}

fn evaluate(flags: &mut HashMap<String, String>) -> Result<String> {
    let data_path = take(flags, "--data")?;
    let selection_path = PathBuf::from(take(flags, "--selection")?);
    let out = take(flags, "--out")?;
    let begin = take(flags, "--start")?;
    let finish_date = take(flags, "--end")?;
    let start = data::date(&begin)?;
    let end = data::date(&finish_date)?;
    let interval = option(flags, "--interval-seconds", "14400")?;
    let costs = Costs {
        fee_bps: option(flags, "--fee-bps", "10")?,
        slip_bps: option(flags, "--slip-bps", "10")?,
    }
    .validate()?;
    let backend = Backend::resolve(&flags.remove("--backend").unwrap_or_else(|| "auto".into()))?;
    finish(flags)?;
    let (selected_text, selected_hash) = sealed_text(&selection_path)?;
    let rule_path = selection_path
        .parent()
        .ok_or("geometry selection parent")?
        .join("best-rule.txt");
    let (rule_text, rule_hash) = sealed_text(&rule_path)?;
    let selected = selection(&selected_text)?;
    let program = Program::parse(rule_text.trim(), 2)?;
    crate::dense_tree::Table::from_program(&program)?;
    let data = Data::read(&data_path, interval)?;
    if start >= end
        || data.timestamps[0] > start
        || data.timestamps.last().unwrap().checked_add(interval) != Some(end)
    {
        return Err("geometry replay must retain causal history and end exactly at end-exclusive boundary; future rows are forbidden".into());
    }
    let start_index = data.index(start);
    if data.timestamps.get(start_index) != Some(&start) {
        return Err("geometry replay start must be an exact bar boundary".into());
    }
    let market = Market::new(&data, start_index, data.len(), costs)?;
    let masks = selected
        .iter()
        .map(|v| selected_mask(&data, v))
        .collect::<Result<Vec<_>>>()?;
    let decisions = program.evaluate(&masks.iter().collect::<Vec<_>>(), backend)?;
    let mut signal = vec![0.; decisions.len];
    for (t, value) in signal.iter_mut().enumerate() {
        *value = if decisions.at(t).0 { 1. } else { 0. };
    }
    // A frozen representative is replayed through the independent chronological
    // Market path; sample-specific predicate-bank aliases are never reused.
    let metrics = market.score(
        &signal,
        Rule {
            threshold: 0.5,
            greater: true,
        },
    )?;
    let values = metric_values(&metrics, interval);
    let valid = (start_index..decisions.len)
        .filter(|&t| decisions.at(t).1)
        .count();
    let active = (start_index..decisions.len)
        .filter(|&t| decisions.at(t).0)
        .count();
    let result = format!(
        "{{\"version\":1,\"status\":\"PASS\",\"role\":\"frozen_geometry_replay\",\"data_sha256\":{},\"selection_sha256\":{},\"rule_sha256\":{},\"start\":{},\"end\":{},\"interval_seconds\":{},\"fee_bps\":{},\"slip_bps\":{},\"valid_decisions\":{},\"active_decisions\":{},\"log_return\":{},\"metric_names\":{},\"metrics\":[{}]}}\n",
        quote(&data.digest),
        quote(&selected_hash),
        quote(&rule_hash),
        quote(&begin),
        quote(&finish_date),
        interval,
        num(costs.fee_bps),
        num(costs.slip_bps),
        valid,
        active,
        num(metrics.lite.log_return),
        metric_names_json(),
        values.iter().map(|v| num(*v)).collect::<Vec<_>>().join(",")
    );
    report::create_out(&out)?;
    let root = Path::new(&out);
    fs::write(root.join("evaluation.json"), &result).map_err(|e| e.to_string())?;
    fs::write(root.join("selection.tsv"), selected_text).map_err(|e| e.to_string())?;
    fs::write(root.join("rule.txt"), rule_text).map_err(|e| e.to_string())?;
    let file = fs::File::create(root.join("decisions.csv")).map_err(|e| e.to_string())?;
    let mut writer = BufWriter::new(file);
    writer
        .write_all(b"timestamp,valid,active\n")
        .map_err(|e| e.to_string())?;
    for t in start_index..decisions.len {
        let (truth, valid) = decisions.at(t);
        writeln!(
            writer,
            "{},{},{}",
            data.timestamps[t], valid as u8, truth as u8
        )
        .map_err(|e| e.to_string())?;
    }
    writer.flush().map_err(|e| e.to_string())?;
    Ok(result)
}

/// Named metric order retained by sweep and frozen replay artifacts.
pub fn metric_names_json() -> String {
    let names = [
        "net_return_pct",
        "gross_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "sharpe",
        "entries",
        "exposure_pct",
        "mean_period_bps",
        "mean_trade_bps",
        "periods",
    ];
    let mut text = String::from("[");
    for (i, name) in names.iter().enumerate() {
        if i != 0 {
            text.push(',');
        }
        write!(text, "{}", quote(name)).unwrap();
    }
    text.push(']');
    text
}
