//! Source adapters into paged::Executor. Period macros, the existing open
//! generator, and streamed expressions use identical numerical/scoring/sink APIs.
use crate::{
    anchor_run, anchors,
    backtest::{Costs, Rule},
    data::{self, Data},
    hash::{sha256, Sha256},
    kernels::Backend,
    lang::Graph,
    paged::{BinarySink, Executor, Page, PageSource, Request, Scorer},
    report, walk,
    walk_config::WalkConfig,
    Result,
};
use std::{
    collections::HashMap,
    fs::File,
    io::{BufRead, BufReader, BufWriter, Write},
    path::Path,
    time::Instant,
};
pub struct PeriodPages {
    pub kind: String,
    pub profile: String,
    pub next: usize,
    pub end: usize,
    pub step: usize,
    pub rules: Vec<Rule>,
    pub page_size: usize,
    pub slow: usize,
    pub signal: usize,
    address: u64,
}
impl PeriodPages {
    pub fn new(
        kind: String,
        profile: String,
        range: std::ops::RangeInclusive<usize>,
        step: usize,
        page_size: usize,
        rules: Vec<Rule>,
        secondary: [usize; 2],
    ) -> Result<Self> {
        let (start, end) = (*range.start(), *range.end());
        let [slow, signal] = secondary;
        if start < 2
            || start > end
            || end > 100000
            || step == 0
            || page_size == 0
            || page_size > 256
            || rules.is_empty()
        {
            return Err("invalid period domain".into());
        }
        if !["talib", "filang_v1"].contains(&profile.as_str()) {
            return Err("unknown numerical profile".into());
        }
        Ok(Self {
            kind,
            profile,
            next: start,
            end,
            step,
            rules,
            page_size,
            slow,
            signal,
            address: 0,
        })
    }
}
impl PageSource for PeriodPages {
    fn next_page(&mut self) -> Result<Option<Page>> {
        let mut graph = Graph::new();
        let mut requests = vec![];
        while requests.len() < self.page_size && self.next <= self.end {
            let p = self.next;
            self.next = self.next.checked_add(self.step).ok_or("period overflow")?;
            let periods = if self.kind == "macd" || self.kind == "ema_cross" {
                [p, self.slow, self.signal]
            } else {
                [p, p, p]
            };
            let root = anchors::expand(&mut graph, &self.kind, periods, &self.profile)?;
            requests.push(Request {
                address: self.address,
                root,
                rules: self.rules.clone(),
            });
            self.address += 1;
        }
        if requests.is_empty() {
            Ok(None)
        } else {
            Ok(Some(Page { graph, requests }))
        }
    }
}
/// Wraps the actual versioned generator already used by walk-search. Work is
/// proportional to this page, never to address_start. A financial discovery policy
/// is intentionally absent: this command evaluates supplied requests only.
pub struct OpenPages {
    config: WalkConfig,
    next: u64,
    stop: u64,
    rules: Vec<Rule>,
}
impl OpenPages {
    pub fn new(config: WalkConfig, start: u64, count: u64, rules: Vec<Rule>) -> Result<Self> {
        if start % config.page_size as u64 != 0 || count == 0 || rules.is_empty() {
            return Err("open range must start at a page boundary and be nonempty".into());
        }
        let stop = start.checked_add(count).ok_or("address overflow")?;
        Ok(Self {
            config,
            next: start,
            stop,
            rules,
        })
    }
}
impl PageSource for OpenPages {
    fn next_page(&mut self) -> Result<Option<Page>> {
        if self.next >= self.stop {
            return Ok(None);
        }
        let count = (self.stop - self.next).min(self.config.page_size as u64) as usize;
        let (g, c, _) = walk::page(
            &self.config,
            self.next / self.config.page_size as u64,
            count,
        )?;
        let mut requests = Vec::new();
        for a in c.into_iter().filter(|a| a.group == "generated") {
            requests.push(Request {
                address: self.next + requests.len() as u64,
                root: a.root,
                rules: self.rules.clone(),
            });
        }
        if requests.len() != count {
            return Err("generator page count mismatch".into());
        }
        self.next += count as u64;
        Ok(Some(Page { graph: g, requests }))
    }
}
pub struct ExpressionPages {
    reader: BufReader<File>,
    size: usize,
    next: u64,
    rules: Vec<Rule>,
    hash: Sha256,
}
impl ExpressionPages {
    pub fn new(path: &str, size: usize, rules: Vec<Rule>) -> Result<Self> {
        if size == 0 || size > 256 {
            return Err("invalid page size".into());
        }
        Ok(Self {
            reader: BufReader::new(File::open(path).map_err(|e| e.to_string())?),
            size,
            next: 0,
            rules,
            hash: Sha256::default(),
        })
    }
}
impl PageSource for ExpressionPages {
    fn next_page(&mut self) -> Result<Option<Page>> {
        let mut graph = Graph::new();
        let mut requests = vec![];
        let mut line = String::new();
        while requests.len() < self.size {
            line.clear();
            if self
                .reader
                .read_line(&mut line)
                .map_err(|e| e.to_string())?
                == 0
            {
                break;
            }
            self.hash.update(line.as_bytes());
            let expr = line.trim();
            if expr.is_empty() || expr.starts_with('#') {
                continue;
            }
            let root = graph.parse(expr)?;
            requests.push(Request {
                address: self.next,
                root,
                rules: self.rules.clone(),
            });
            self.next += 1;
        }
        if requests.is_empty() {
            Ok(None)
        } else {
            Ok(Some(Page { graph, requests }))
        }
    }
}
fn take(m: &mut HashMap<String, String>, k: &str) -> Result<String> {
    m.remove(k).ok_or_else(|| format!("missing {k}"))
}
fn number<T: std::str::FromStr>(
    m: &mut HashMap<String, String>,
    k: &str,
    default: &str,
) -> Result<T> {
    m.remove(k)
        .unwrap_or_else(|| default.into())
        .parse()
        .map_err(|_| format!("bad {k}"))
}
pub fn run(mut flags: HashMap<String, String>) -> Result<String> {
    let clock = Instant::now();
    let data_path = take(&mut flags, "--data")?;
    let out_path = take(&mut flags, "--out")?;
    let source_name = take(&mut flags, "--source")?;
    let interval = number::<i64>(&mut flags, "--interval", "14400")?;
    let start = data::date(&take(&mut flags, "--start")?)?;
    let end = data::date(&take(&mut flags, "--end")?)?;
    let backend = Backend::resolve(&flags.remove("--backend").unwrap_or_else(|| "auto".into()))?;
    let scorer = Scorer::parse(&flags.remove("--scorer").unwrap_or_else(|| "auto".into()))?;
    let page_size = number::<usize>(&mut flags, "--page-size", "32")?;
    let memory = number::<usize>(&mut flags, "--memory-mib", "128")?
        .checked_mul(1024 * 1024)
        .ok_or("budget overflow")?;
    let output = flags.remove("--output").unwrap_or_else(|| "all".into());
    if !["all", "summary"].contains(&output.as_str()) {
        return Err("output all/summary".into());
    }
    let capture = flags
        .remove("--capture")
        .unwrap_or_else(|| "false".into())
        .parse::<bool>()
        .map_err(|_| "bad capture")?;
    if capture && output != "all" {
        return Err("captured proof requires exhaustive output".into());
    }
    let rule_text = flags.remove("--rules").unwrap_or_else(|| "gt:0".into());
    let rules = rule_text
        .split(',')
        .map(|s| {
            let (d, t) = s.split_once(':').ok_or("rule gt:number or lt:number")?;
            if !["gt", "lt"].contains(&d) {
                return Err("unknown direction".into());
            }
            let threshold = t.parse::<f64>().map_err(|_| "bad threshold")?;
            if !threshold.is_finite() {
                return Err("nonfinite rule".into());
            }
            Ok(Rule {
                greater: d == "gt",
                threshold,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let gap_dates = flags.remove("--gaps").unwrap_or_default();
    let gate = flags.remove("--gate");
    let diagnostic = flags
        .remove("--diagnostic")
        .unwrap_or_else(|| "false".into())
        .parse::<bool>()
        .map_err(|_| "bad diagnostic")?;
    if gate.is_none() && !diagnostic {
        return Err("a passing --gate is required; --diagnostic true explicitly marks systems-only tests without a parity claim".into());
    }
    let source_args = flags.clone();
    let source_file_hash = match source_name.as_str() {
        "open" => Some(crate::hash::file_sha256(
            flags
                .get("--generator-config")
                .ok_or("missing generator config")?,
        )?),
        "expressions" => Some(crate::hash::file_sha256(
            flags.get("--expressions").ok_or("missing expressions")?,
        )?),
        _ => None,
    };
    let mut source: Box<dyn PageSource> = match source_name.as_str() {
        "periods" => {
            let kind = take(&mut flags, "--kind")?;
            let profile = flags.remove("--profile").unwrap_or_else(|| "talib".into());
            let lo = number(&mut flags, "--period-start", "2")?;
            let hi = number(&mut flags, "--period-end", "256")?;
            let step = number(&mut flags, "--period-step", "1")?;
            let slow = number(&mut flags, "--slow", "96")?;
            let signal = number(&mut flags, "--signal", "9")?;
            Box::new(PeriodPages::new(
                kind,
                profile,
                lo..=hi,
                step,
                page_size,
                rules,
                [slow, signal],
            )?)
        }
        "open" => {
            let mut config = WalkConfig::load(&take(&mut flags, "--generator-config")?)?;
            config.page_size = page_size;
            let start = number(&mut flags, "--address-start", "0")?;
            let count = number(&mut flags, "--addresses", "256")?;
            Box::new(OpenPages::new(config, start, count, rules)?)
        }
        "expressions" => Box::new(ExpressionPages::new(
            &take(&mut flags, "--expressions")?,
            page_size,
            rules,
        )?),
        _ => return Err("source periods/open/expressions".into()),
    };
    if !flags.is_empty() {
        return Err(format!("unknown program-sweep flags: {:?}", flags.keys()));
    }
    let d = Data::read(&data_path, interval)?;
    if let Some(g) = gate.as_ref() {
        anchor_run::validate_gate(g, &d.digest)?;
    }
    if start >= end || d.timestamps[0] > start || d.timestamps.last().unwrap() + interval < end {
        return Err("data do not cover evaluation dates".into());
    }
    let gaps = if gap_dates.is_empty() {
        vec![]
    } else {
        gap_dates
            .split(',')
            .map(data::date)
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .flat_map(|s| {
                let i = d.index(s);
                [i.saturating_sub(2), i.saturating_sub(1)]
            })
            .collect()
    };
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
        d.index(start)..d.index(end),
        gaps,
        &costs,
        backend,
        scorer,
        memory,
    )?;
    report::create_out(&out_path)?;
    let out = Path::new(&out_path);
    let binary = out.join("metrics.bin");
    let mut sink = BinarySink::new(if output == "all" {
        Some(binary.as_path())
    } else {
        None
    })?;
    // The domain contract is stored once; no per-request manifest for open sweeps.
    let mut args = source_args.into_iter().collect::<Vec<_>>();
    args.sort();
    let domain=format!("{{\"source\":{},\"source_arguments\":{{{}}},\"rules\":{},\"page_size\":{},\"start\":{},\"end\":{},\"gaps\":{},\"data_sha256\":{},\"engine_sha256\":{},\"scenarios\":[[5,5],[10,10]],\"execution\":\"spot_open_v1\",\"role\":\"systems_parity_regression_not_selection\"}}",report::quote(&source_name),args.iter().map(|(k,v)|format!("{}:{}",report::quote(k),report::quote(v))).collect::<Vec<_>>().join(","),report::quote(&rule_text),page_size,start,end,report::quote(&gap_dates),report::quote(&d.digest),report::quote(&anchor_run::engine_id()?));
    let domain = format!(
        "{{\"language_version\":1,\"source_file_sha256\":{},\"request_domain\":{}}}",
        source_file_hash
            .as_ref()
            .map_or("null".into(), |h| report::quote(h)),
        domain
    );
    report::write(out.join("domain.json"), &domain)?;
    if capture {
        let mut features =
            BufWriter::new(File::create(out.join("features.bin")).map_err(|e| e.to_string())?);
        let mut specs =
            BufWriter::new(File::create(out.join("requests.jsonl")).map_err(|e| e.to_string())?);
        while let Some(page) = source.next_page()? {
            for r in &page.requests {
                writeln!(
                    specs,
                    "{{\"address\":\"{}\",\"feature_id\":{},\"expression\":{},\"rules\":[{}]}}",
                    r.address,
                    report::quote(&page.graph.identity(r.root)),
                    report::quote(&page.graph.expression(r.root)),
                    r.rules
                        .iter()
                        .map(|v| format!(
                            "{{\"greater\":{},\"threshold\":{}}}",
                            v.greater,
                            report::num(v.threshold)
                        ))
                        .collect::<Vec<_>>()
                        .join(",")
                )
                .map_err(|e| e.to_string())?;
            }
            executor.page(&page, &mut sink, Some(&mut features))?;
        }
        features.flush().map_err(|e| e.to_string())?;
        specs.flush().map_err(|e| e.to_string())?;
    } else {
        executor.run(source.as_mut(), &mut sink)?;
    }
    let (hash, n, bytes) = sink.finish()?;
    let summary=format!("{{\"status\":\"PASS\",\"role\":\"systems_parity_regression_not_selection\",\"domain_sha256\":{},\"full_metric_queries\":{},\"metrics_sha256\":{},\"written_metric_bytes\":{},\"computed_metric_bytes\":{},\"backend\":{},\"execution_state_payload\":{},\"total_internal_seconds\":{},\"page_work\":{},\"transition_work\":{}}}\n",report::quote(&sha256(domain.as_bytes())),n,report::quote(&hash),if output=="all"{bytes}else{0},bytes,report::quote(backend.name()),executor.state_bytes(),clock.elapsed().as_secs_f64(),executor.work.json(),executor.state_work().json());
    report::write(out.join("summary.json"), &summary)?;
    Ok(summary)
}
