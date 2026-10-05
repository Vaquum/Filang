//! Finite authoring/configuration for the generic joint engine. Indicator labels
//! are metadata only. All executor inputs are numerical expressions and rule IR.
use crate::{
    backtest::Costs,
    cohort,
    data::{self, Data},
    hash::{sha256, Sha256},
    joint::{self, Alternative, BoxResult, Plan},
    kernels::Backend,
    lang::Graph,
    paged::{metric_values, Executor, Scorer},
    regions::Grid,
    report::{self, num, quote},
    rules::{self, Predicate, Program, Qualifier},
    Result,
};
use std::{
    collections::{BTreeMap, HashMap},
    fmt::Write as _,
    fs,
    io::{BufWriter, Write},
    path::Path,
    sync::Arc,
    time::Instant,
};
#[derive(Clone)]
pub struct OptionSpec {
    pub id: usize,
    pub slot: usize,
    pub label: String,
    pub tag: String,
    pub predicate: Predicate,
    pub qualifiers: Vec<Qualifier>,
    pub grid: Grid,
    pub x: usize,
    pub y: Option<usize>,
    pub source_line: String,
}
pub struct Domain {
    pub graph: Graph,
    pub options: Vec<OptionSpec>,
    pub slots: usize,
    pub programs: Vec<Program>,
    pub parameter_text: String,
    pub rule_text: String,
}
impl Domain {
    pub fn parse(parameter_text: &str, rule_text: &str) -> Result<Self> {
        if parameter_text.len() > 4 << 20 || rule_text.len() > 65536 {
            return Err("domain file budget".into());
        }
        let mut graph = Graph::new();
        let mut options = Vec::new();
        let mut max = 0usize;
        for line in parameter_text
            .lines()
            .filter(|l| !l.trim().is_empty() && !l.starts_with('#'))
        {
            let f = line.split('\t').collect::<Vec<_>>();
            if f.len() != 8 {
                return Err(
                    "parameter TSV needs slot,label,tag,predicate,qualifiers,grid,x,y".into(),
                );
            }
            let slot = f[0].parse::<usize>().map_err(|_| "bad slot integer")?;
            if slot >= 8 || options.len() >= 4096 {
                return Err("domain option/slot limit".into());
            }
            if [f[1], f[2]].iter().any(|s| {
                s.is_empty()
                    || s.len() > 128
                    || !s
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_-.".contains(&c))
            }) {
                return Err("labels/tags must be short ASCII identifiers".into());
            }
            if options
                .iter()
                .any(|o: &OptionSpec| o.slot == slot && o.label == f[1])
            {
                return Err("duplicate slot label".into());
            }
            let predicate = Predicate::parse(f[3])?;
            let qualifiers = f[4]
                .split('+')
                .map(Qualifier::parse)
                .collect::<Result<Vec<_>>>()?;
            if qualifiers.len() > 8 {
                return Err("qualifier chain limit".into());
            }
            let grid = Grid::parse(f[5])?;
            let x = graph.parse(f[6])?;
            let y = if f[7] == "-" {
                None
            } else {
                Some(graph.parse(f[7])?)
            };
            predicate.validate(&graph, x, y, grid)?;
            max = max.max(slot);
            options.push(OptionSpec {
                id: options.len(),
                slot,
                label: f[1].into(),
                tag: f[2].into(),
                predicate,
                qualifiers,
                grid,
                x,
                y,
                source_line: line.into(),
            });
        }
        if options.is_empty() {
            return Err("empty predicate domain".into());
        }
        let slots = max + 1;
        if (0..slots).any(|s| !options.iter().any(|o| o.slot == s)) {
            return Err("slots must be contiguous".into());
        }
        let programs = rule_text
            .lines()
            .filter(|l| !l.trim().is_empty() && !l.starts_with('#'))
            .map(|l| Program::parse(l, slots))
            .collect::<Result<Vec<_>>>()?;
        if programs.is_empty()
            || programs.len() > 128
            || programs.iter().any(|p| p.used_slots().len() != slots)
        {
            return Err("1..128 templates must each use all slots".into());
        }
        Ok(Self {
            graph,
            options,
            slots,
            programs,
            parameter_text: parameter_text.into(),
            rule_text: rule_text.into(),
        })
    }
    pub fn shape(&self) -> Vec<Vec<Alternative>> {
        let mut out = vec![Vec::new(); self.slots];
        for o in &self.options {
            out[o.slot].push(Alternative {
                id: o.id,
                tag: o.tag.clone(),
                count: o.grid.count,
                cells: Arc::new(Vec::new()),
            });
        }
        out
    }
}
fn take(m: &mut BTreeMap<String, String>, k: &str) -> Result<String> {
    m.remove(k).ok_or_else(|| format!("missing {k}"))
}
fn parse<T: std::str::FromStr>(
    m: &mut BTreeMap<String, String>,
    k: &str,
    default: &str,
) -> Result<T> {
    m.remove(k)
        .unwrap_or_else(|| default.into())
        .parse()
        .map_err(|_| format!("invalid {k}"))
}
#[derive(Clone)]
pub struct Config {
    pub data: String,
    pub out: String,
    pub parameters: String,
    pub templates: String,
    pub start: i64,
    pub end: i64,
    pub interval: i64,
    pub memory: usize,
    pub cache: usize,
    pub costs: Vec<Costs>,
    pub different: bool,
    pub plan: Plan,
    pub backend: Backend,
    pub output: String,
    pub capture: bool,
    pub gate: Option<String>,
    pub diagnostic: bool,
    pub max_boxes: u64,
}
impl Config {
    pub fn parse(text: &str) -> Result<Self> {
        let mut m = BTreeMap::new();
        for l in text
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
        {
            let (k, v) = l.split_once('=').ok_or("config key=value")?;
            if m.insert(k.trim().into(), v.trim().into()).is_some() {
                return Err("duplicate config key".into());
            }
        }
        if take(&mut m, "version")? != "1" {
            return Err("strategy schema version".into());
        }
        let costs = take(&mut m, "costs")?
            .split(',')
            .map(|s| {
                let (f, l) = s.split_once(':').ok_or("cost fee:slip")?;
                Costs {
                    fee_bps: f.parse().map_err(|_| "fee")?,
                    slip_bps: l.parse().map_err(|_| "slippage")?,
                }
                .validate()
            })
            .collect::<Result<Vec<_>>>()?;
        let c = Self {
            data: take(&mut m, "data")?,
            out: take(&mut m, "out")?,
            parameters: take(&mut m, "parameters")?,
            templates: take(&mut m, "templates")?,
            start: data::date(&take(&mut m, "start")?)?,
            end: data::date(&take(&mut m, "end")?)?,
            interval: parse(&mut m, "interval_seconds", "14400")?,
            memory: parse::<usize>(&mut m, "memory_mib", "128")?
                .checked_mul(1 << 20)
                .ok_or("memory overflow")?,
            cache: parse::<usize>(&mut m, "cache_mib", "8")?
                .checked_mul(1 << 20)
                .ok_or("cache overflow")?,
            costs,
            different: parse(&mut m, "different_tags", "true")?,
            plan: Plan::parse(&m.remove("plan").unwrap_or_else(|| "cofactor".into()))?,
            backend: Backend::resolve(&m.remove("backend").unwrap_or_else(|| "auto".into()))?,
            output: m.remove("output").unwrap_or_else(|| "boxes".into()),
            capture: parse(&mut m, "capture", "true")?,
            gate: m.remove("gate"),
            diagnostic: parse(&mut m, "diagnostic", "false")?,
            max_boxes: parse(&mut m, "max_boxes", "100000000")?,
        };
        if !m.is_empty() {
            return Err(format!("unknown strategy keys {:?}", m.keys()));
        }
        if c.start >= c.end
            || c.interval <= 0
            || c.memory < 16 << 20
            || c.cache > c.memory
            || c.costs.is_empty()
            || c.costs.len() > 8
            || !matches!(c.output.as_str(), "boxes" | "summary")
            || c.max_boxes == 0
        {
            return Err("strategy timeline/resource/output configuration".into());
        }
        Ok(c)
    }
    pub fn domain(&self) -> Result<Domain> {
        Domain::parse(
            &fs::read_to_string(&self.parameters).map_err(|e| e.to_string())?,
            &fs::read_to_string(&self.templates).map_err(|e| e.to_string())?,
        )
    }
}
pub fn inspect(c: &Config) -> Result<String> {
    let d = c.domain()?;
    let shape = d.shape();
    let count = joint::domain_count(&shape, c.different, true)?
        .checked_mul(d.programs.len() as u64)
        .ok_or("domain count overflow")?;
    Ok(format!("{{\"status\":\"plan_only\",\"slots\":{},\"predicate_alternatives\":{},\"templates\":{},\"valid_alternative_tuples\":{},\"logical_strategy_addresses\":{},\"no_evaluations_performed\":true}}",d.slots,d.options.len(),d.programs.len(),joint::domain_count(&shape,c.different,false)?*d.programs.len() as u64,count))
}
fn option_json(o: &OptionSpec, g: &Graph) -> String {
    let f = o.source_line.split('\t').collect::<Vec<_>>();
    format!("{{\"id\":{},\"slot\":{},\"label\":{},\"tag\":{},\"predicate\":{},\"qualifiers\":{},\"grid\":{},\"x\":{},\"y\":{}}}",o.id,o.slot,quote(&o.label),quote(&o.tag),quote(f[3]),quote(f[4]),quote(&o.grid.text()),quote(&g.expression(o.x)),o.y.map_or_else(||"null".into(),|y|quote(&g.expression(y))))
}
fn box_json(r: &BoxResult, interval: i64) -> String {
    format!(
        "{{\"template\":{},\"choices\":[{}],\"ranges\":[{}],\"metrics\":[{}]}}",
        r.template,
        r.choices
            .iter()
            .map(usize::to_string)
            .collect::<Vec<_>>()
            .join(","),
        r.ranges
            .iter()
            .map(|(l, h)| format!("[{l},{h}]"))
            .collect::<Vec<_>>()
            .join(","),
        r.metrics
            .iter()
            .map(|m| report::metrics(m, interval))
            .collect::<Vec<_>>()
            .join(",")
    )
}
fn preferable(a: &BoxResult, b: &BoxResult) -> bool {
    let x = (a.metrics[0].lite.log_return * 1e9).round();
    let y = (b.metrics[0].lite.log_return * 1e9).round();
    x > y || (x == y && (a.template, &a.choices, &a.ranges) < (b.template, &b.choices, &b.ranges))
}
pub fn run(c: &Config, raw: &str) -> Result<String> {
    let clock = Instant::now();
    let domain = c.domain()?;
    let d = Data::read(&c.data, c.interval)?;
    if d.timestamps[0] > c.start || d.timestamps.last().unwrap() + c.interval != c.end {
        return Err(
            "input must retain warmup and end exactly at exclusive end; future rows forbidden"
                .into(),
        );
    }
    if !c.diagnostic {
        cohort::validate_gate(
            c.gate.as_ref().ok_or(
                "strategy sweep needs numerical reference gate or explicit diagnostic=true",
            )?,
            &d.digest,
        )?;
    }
    let range = d.index(c.start)..d.len();
    if range.end - range.start < 4 {
        return Err("strategy range too short".into());
    }
    let need_full = domain.programs.iter().any(|p| !p.pointwise());
    let mut ex = Executor::new(
        &d,
        range.clone(),
        vec![],
        &c.costs,
        c.backend,
        Scorer::Auto,
        c.memory,
    )?;
    let mut roots = domain
        .options
        .iter()
        .flat_map(|o| [Some(o.x), o.y].into_iter().flatten())
        .collect::<Vec<_>>();
    roots.sort_unstable();
    roots.dedup();
    let prepare = Instant::now();
    ex.prepare_shared(
        &domain.graph,
        &crate::family::boundaries(&domain.graph, &roots),
    )?;
    let arrays = ex.numerical_roots(&domain.graph, &roots, None)?;
    let mut numerical = roots.iter().copied().zip(arrays).collect::<HashMap<_, _>>();
    let numerical_seconds = prepare.elapsed().as_secs_f64();
    let prepare = Instant::now();
    let mut slots = vec![Vec::new(); domain.slots];
    let mut bank: HashMap<String, Arc<Vec<rules::Cell>>> = HashMap::new();
    let (mut cell_count, mut cell_bytes, mut predicate_reuse) = (0usize, 0usize, 0usize);
    for o in &domain.options {
        let key = format!(
            "{}|{:?}|{:?}|{:?}|{}",
            o.x,
            o.y,
            o.predicate,
            o.qualifiers,
            o.grid.text()
        );
        let cells = if let Some(cells) = bank.get(&key) {
            predicate_reuse += 1;
            cells.clone()
        } else {
            let mut cells = rules::cells(
                &o.predicate,
                &numerical[&o.x],
                o.y.map(|id| numerical[&id].as_slice()),
                o.grid,
                &o.qualifiers,
                c.memory.saturating_sub(cell_bytes),
            )?;
            if !need_full {
                let mut merged: Vec<rules::Cell> = Vec::new();
                for mut cell in cells {
                    cell.mask = cell.mask.slice(range.start, range.end - 2)?;
                    if let Some(last) = merged.last_mut() {
                        if last.mask == cell.mask {
                            last.hi = cell.hi;
                            continue;
                        }
                    }
                    merged.push(cell);
                }
                cells = merged;
            }
            let bytes = cells
                .iter()
                .map(|c| c.mask.payload() + std::mem::size_of::<rules::Cell>())
                .sum::<usize>();
            cell_bytes = cell_bytes
                .checked_add(bytes)
                .ok_or("predicate payload overflow")?;
            if cell_bytes > c.memory {
                return Err("predicate bank budget exceeded".into());
            }
            cell_count += cells.len();
            let cells = Arc::new(cells);
            bank.insert(key, cells.clone());
            cells
        };
        slots[o.slot].push(Alternative {
            id: o.id,
            tag: o.tag.clone(),
            count: o.grid.count,
            cells,
        });
    }
    numerical.clear();
    ex.clear_shared();
    let predicate_seconds = prepare.elapsed().as_secs_f64();
    let logical = joint::domain_count(&slots, c.different, true)?
        .checked_mul(domain.programs.len() as u64)
        .ok_or("domain overflow")?;
    if c.plan == Plan::Expanded && logical > 1_000_000 {
        return Err("expanded reference cap; choose small grid".into());
    }
    report::create_out(&c.out)?;
    let dir = Path::new(&c.out);
    report::write(dir.join("experiment.cfg"), raw)?;
    report::write(dir.join("parameters.tsv"), &domain.parameter_text)?;
    report::write(dir.join("rules.txt"), &domain.rule_text)?;
    let record_bytes = 8 + domain.slots * 24 + c.costs.len() * 80;
    let manifest=format!("{{\"version\":1,\"role\":\"retrospective_joint_systems_search_not_untouched_confirmation\",\"data\":{},\"data_sha256\":{},\"engine_sha256\":{},\"domain_sha256\":{},\"start_index\":{},\"end_index\":{},\"rows\":{},\"interval\":{},\"slots\":{},\"different_tags\":{},\"full_predicate_timeline\":{},\"binary_record_bytes\":{},\"costs\":[{}],\"templates\":[{}],\"options\":[{}],\"logical_addresses\":{},\"capture\":{},\"output\":{},\"plan\":{}}}\n",quote(&c.data),quote(&d.digest),quote(&crate::anchor_run::engine_id()?),quote(&sha256(format!("{}|{}|{}|{}|{}",domain.parameter_text,domain.rule_text,c.different,c.start,c.end).as_bytes())),range.start,range.end,d.len(),c.interval,domain.slots,c.different,need_full,record_bytes,c.costs.iter().map(|v|format!("[{},{}]",num(v.fee_bps),num(v.slip_bps))).collect::<Vec<_>>().join(","),domain.programs.iter().map(|p|quote(&p.text)).collect::<Vec<_>>().join(","),domain.options.iter().map(|o|option_json(o,&domain.graph)).collect::<Vec<_>>().join(","),logical,c.capture,quote(&c.output),quote(&format!("{:?}",c.plan)));
    report::write(dir.join("manifest.json"), &manifest)?;
    if c.capture {
        let mut w = BufWriter::new(
            fs::File::create(dir.join("predicate-cells.bin")).map_err(|e| e.to_string())?,
        );
        for opts in &slots {
            for o in opts {
                let mask = &o.cells[0].mask;
                for n in [
                    o.id as u64,
                    o.cells.len() as u64,
                    mask.len as u64,
                    o.count,
                    mask.bits.len() as u64,
                ] {
                    w.write_all(&n.to_le_bytes()).map_err(|e| e.to_string())?;
                }
                for cell in o.cells.iter() {
                    for n in [cell.lo, cell.hi] {
                        w.write_all(&n.to_le_bytes()).map_err(|e| e.to_string())?;
                    }
                    for v in cell.mask.bits.iter().chain(&cell.mask.valid) {
                        w.write_all(&v.to_le_bytes()).map_err(|e| e.to_string())?;
                    }
                }
            }
        }
        w.flush().map_err(|e| e.to_string())?;
    }
    let mut output = if c.output == "boxes" {
        Some(BufWriter::new(
            fs::File::create(dir.join("boxes.bin")).map_err(|e| e.to_string())?,
        ))
    } else {
        None
    };
    let mut digest = Sha256::default();
    let mut best: Option<BoxResult> = None;
    let (mut bytes, mut mixed_coverage, mut flat_coverage) = (0u64, 0u64, 0u64);
    let mut records = vec![0u8; record_bytes];
    let solve = Instant::now();
    let mut sweep = joint::Sweep::new(
        &mut ex,
        &d,
        range,
        &c.costs,
        c.backend,
        c.plan,
        c.different,
        c.cache,
        need_full,
        c.max_boxes,
    )?;
    sweep.run(&slots, &domain.programs, |r| {
        let mut at = 0;
        for value in std::iter::once(r.template as u64).chain(
            r.choices
                .iter()
                .zip(&r.ranges)
                .flat_map(|(choice, (lo, hi))| [*choice as u64, *lo, *hi]),
        ) {
            records[at..at + 8].copy_from_slice(&value.to_le_bytes());
            at += 8;
        }
        for m in &r.metrics {
            for v in metric_values(m, d.interval) {
                records[at..at + 8].copy_from_slice(&v.to_le_bytes());
                at += 8;
            }
        }
        digest.update(&records);
        bytes = bytes
            .checked_add(record_bytes as u64)
            .ok_or("byte count overflow")?;
        if let Some(w) = output.as_mut() {
            w.write_all(&records).map_err(|e| e.to_string())?;
        }
        let width = r.width()?;
        let active = r.metrics[0].lite.active;
        if active == 0 {
            flat_coverage += width;
        } else if active < r.metrics[0].lite.periods {
            mixed_coverage += width;
        }
        if best.as_ref().map_or(true, |b| preferable(r, b)) {
            best = Some(r.clone());
        }
        Ok(())
    })?;
    if let Some(w) = output.as_mut() {
        w.flush().map_err(|e| e.to_string())?;
    }
    let work = sweep.work.clone();
    drop(sweep);
    let solve_seconds = solve.elapsed().as_secs_f64();
    if let Some(b) = &best {
        report::write(dir.join("best.json"), &(box_json(b, c.interval) + "\n"))?;
        let mut t = String::from("# slot\tlabel\ttag\tpredicate\tqualifiers\tgrid\tx\ty\n");
        for (slot, (&id, &(lo, _))) in b.choices.iter().zip(&b.ranges).enumerate() {
            let spec = &domain.options[id];
            let mut f = spec
                .source_line
                .split('\t')
                .map(str::to_owned)
                .collect::<Vec<_>>();
            let grid = Grid {
                start: (spec.grid.start as i128 + lo as i128 * spec.grid.step as i128) as i64,
                count: 1,
                ..spec.grid
            };
            grid.validate()?;
            f[0] = slot.to_string();
            f[5] = grid.text();
            t += &(f.join("\t") + "\n");
        }
        report::write(dir.join("best-parameters.tsv"), &t)?;
        report::write(
            dir.join("best-rule.txt"),
            &(domain.programs[b.template].text.clone() + "\n"),
        )?;
    }
    let summary=format!("{{\"status\":\"PASS\",\"coverage_complete\":true,\"logical_strategy_addresses\":{},\"numerical_roots\":{},\"predicate_options\":{},\"unique_predicate_plans\":{},\"predicate_plan_reuses\":{},\"predicate_cells\":{},\"predicate_payload_bytes\":{},\"cache_budget_bytes\":{},\"execution_payload_bytes\":{},\"result_bytes_computed\":{},\"result_bytes_written\":{},\"result_sha256\":{},\"mixed_position_addresses\":{},\"all_flat_addresses\":{},\"backend\":{},\"native_workers\":1,\"work\":{},\"execution_work\":{},\"numerical_seconds\":{},\"predicate_seconds\":{},\"solve_and_output_seconds\":{},\"whole_internal_seconds\":{},\"best_descriptive_not_validated\":{}}}\n",logical,roots.len(),domain.options.len(),bank.len(),predicate_reuse,cell_count,cell_bytes,c.cache,ex.state_bytes(),bytes,if c.output=="boxes"{bytes}else{0},quote(&digest.finish()),mixed_coverage,flat_coverage,quote(c.backend.name()),work.json(),ex.state_work().json(),num(numerical_seconds),num(predicate_seconds),num(solve_seconds),num(clock.elapsed().as_secs_f64()),best.as_ref().map_or_else(||"null".into(),|b|box_json(b,c.interval)));
    report::write(dir.join("summary.json"), &summary)?;
    Ok(summary)
}
/// Example authoring only. The generic evaluator never dispatches on these names.
pub fn example(out: &str, count: u64, neighbors: bool, temporal: bool, slots: usize) -> Result<()> {
    if count < 3 || count % 2 == 0 || !(2..=3).contains(&slots) {
        return Err("example requires odd grid >=3 and 2 or 3 slots".into());
    }
    report::create_out(out)?;
    let dir = Path::new(out);
    let mut text = String::from("# slot\tlabel\ttag\tpredicate\tqualifiers\tgrid\tx\ty\n");
    for slot in 0..slots {
        for kind in cohort::KINDS {
            let (n, _, old) = cohort::defaults(kind)?;
            let grid = Grid {
                start: i64::try_from(old.start as i128 * (count - 1) as i128)
                    .map_err(|_| "example grid overflow")?,
                step: old
                    .step
                    .checked_mul(old.count - 1)
                    .ok_or("example grid overflow")?,
                count,
                denominator: old
                    .denominator
                    .checked_mul(count - 1)
                    .ok_or("example grid overflow")?,
            };
            grid.validate()?;
            let variants = if neighbors {
                vec![(n, 0., 0.), (n - 1, -0.005, 0.05), (n + 1, 0.005, 0.05)]
            } else {
                vec![(n, 0., 0.)]
            };
            for (i, (n, a, b)) in variants.into_iter().enumerate() {
                let (mut g, ids) = cohort::stripe(kind, n, a)?;
                let r = cohort::output(&mut g, kind, ids, b, 0.)?;
                let value = g.nodes[r].args[0];
                for q in if temporal {
                    vec!["plain", "persist:2", "recent:3"]
                } else {
                    vec!["plain"]
                } {
                    writeln!(
                        &mut text,
                        "{slot}\t{kind}_{i}_{}\t{kind}\tthreshold:gt\t{q}\t{}\t{}\t-",
                        q.replace(':', "_"),
                        grid.text(),
                        g.expression(value)
                    )
                    .unwrap();
                }
            }
        }
    }
    report::write(dir.join("parameters.tsv"), &text)?;
    let rules = if slots == 2 {
        "(and s0 s1)\n(or s0 s1)\n(and s0 (not s1))\n"
    } else {
        "(and (and s0 s1) s2)\n(and s0 (or s1 (not s2)))\n(recent 3 (and s0 (and s1 s2)))\n"
    };
    report::write(dir.join("rules.txt"), rules)?;
    report::write(dir.join("sweep.cfg"),&format!("version=1\ndata=data/btc4h/discovery.csv\nout=runs/joint\nparameters={out}/parameters.tsv\ntemplates={out}/rules.txt\nstart=2024-01-01\nend=2025-01-01\ninterval_seconds=14400\ncosts=10:10\nmemory_mib=128\ncache_mib=8\ndifferent_tags=true\nplan=cofactor\nbackend=auto\noutput=boxes\ncapture=true\ngate=runs/joint-parity/gate.txt\nmax_boxes=100000000\n"))?;
    Ok(())
}
pub fn cli(cmd: &str, mut flags: HashMap<String, String>) -> Result<String> {
    if cmd == "strategy-example" {
        let out = flags.remove("--out").ok_or("--out required")?;
        let count = flags
            .remove("--grid-count")
            .unwrap_or_else(|| "20001".into())
            .parse()
            .map_err(|_| "grid count")?;
        let slots = flags
            .remove("--slots")
            .unwrap_or_else(|| "2".into())
            .parse()
            .map_err(|_| "slot count")?;
        let neighbors = flags
            .remove("--neighbors")
            .unwrap_or_else(|| "true".into())
            .parse()
            .map_err(|_| "neighbors Boolean")?;
        let temporal = flags
            .remove("--qualifiers")
            .unwrap_or_else(|| "true".into())
            .parse()
            .map_err(|_| "qualifiers Boolean")?;
        if !flags.is_empty() {
            return Err("unknown example flags".into());
        }
        example(&out, count, neighbors, temporal, slots)?;
        return Ok(format!("Created {out}/sweep.cfg"));
    }
    let path = flags.remove("--config").ok_or("--config required")?;
    let raw = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut c = Config::parse(&raw)?;
    if let Some(s) = flags.remove("--out") {
        c.out = s;
    }
    if let Some(s) = flags.remove("--gate") {
        c.gate = Some(s);
    }
    if let Some(s) = flags.remove("--plan") {
        c.plan = Plan::parse(&s)?;
    }
    if let Some(s) = flags.remove("--output") {
        if !matches!(s.as_str(), "boxes" | "summary") {
            return Err("output boxes/summary".into());
        }
        c.output = s;
    }
    if let Some(s) = flags.remove("--backend") {
        c.backend = Backend::resolve(&s)?;
    }
    if let Some(s) = flags.remove("--cache-mib") {
        c.cache = s
            .parse::<usize>()
            .map_err(|_| "cache budget")?
            .checked_mul(1 << 20)
            .ok_or("cache overflow")?;
        if c.cache > c.memory {
            return Err("cache exceeds memory budget".into());
        }
    }
    if let Some(s) = flags.remove("--capture") {
        c.capture = s.parse().map_err(|_| "capture Boolean")?;
    }
    if !flags.is_empty() {
        return Err(format!("unknown strategy flags {:?}", flags.keys()));
    }
    if cmd == "strategy-inspect" {
        inspect(&c)
    } else {
        run(&c, &raw)
    }
}
