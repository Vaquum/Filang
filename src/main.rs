use filang::{backtest::Costs, config::Config, data, report, search, Result};
use std::{collections::HashMap, env, fs, path::Path};
const HELP:&str="Filang 0.3.0 (research prototype)\n\n  filang search --config FILE\n  filang inspect --config FILE\n  filang evaluate --data CSV --selection frozen.tsv --out DIR [--fee-bps N --slip-bps N]\n  filang walk-search --config FILE\n  filang walk-inspect --config FILE\n  filang walk-evaluate --data CSV --selection walk.tsv --out DIR [--scenario stress]\n  filang anchor-parity --data CSV --out DIR [--mode direct|shared|family]\n  filang anchor-sweep --data CSV --gate FILE --radius N --thresholds N --out DIR\n  filang demo --out DIR\n\nCore is dependency-free. HF preparation is an optional Python adapter.\n";
fn arguments() -> Result<(String, HashMap<String, String>)> {
    let mut it = env::args().skip(1);
    let command = it.next().unwrap_or_else(|| "help".into());
    let mut flags = HashMap::new();
    while let Some(k) = it.next() {
        if !k.starts_with("--") {
            return Err(format!("unexpected argument {k}"));
        }
        let v = it.next().ok_or_else(|| format!("missing value for {k}"))?;
        if flags.insert(k.clone(), v).is_some() {
            return Err(format!("duplicate {k}"));
        }
    }
    Ok((command, flags))
}
fn take(m: &mut HashMap<String, String>, k: &str) -> Result<String> {
    m.remove(k).ok_or_else(|| format!("missing {k}"))
}
fn finish(m: &HashMap<String, String>) -> Result<()> {
    if m.is_empty() {
        Ok(())
    } else {
        Err(format!("unknown flags: {:?}", m.keys().collect::<Vec<_>>()))
    }
}
fn main() {
    if let Err(e) = entry() {
        eprintln!("filang: {e}");
        std::process::exit(1);
    }
}
fn entry() -> Result<()> {
    let (cmd, mut flags) = arguments()?;
    match cmd.as_str() {
        "help" | "--help" | "-h" => {
            print!("{HELP}");
        }
        "anchor-parity" | "anchor-sweep" => {
            let data = take(&mut flags, "--data")?;
            let out = take(&mut flags, "--out")?;
            let mode = flags.remove("--mode").unwrap_or_else(|| "family".into());
            let backend = filang::kernels::Backend::resolve(
                &flags.remove("--backend").unwrap_or_else(|| "auto".into()),
            )?;
            let capture = flags
                .remove("--capture")
                .unwrap_or_else(|| {
                    if cmd == "anchor-parity" {
                        "true"
                    } else {
                        "false"
                    }
                    .into()
                })
                .parse::<bool>()
                .map_err(|_| "bad capture flag")?;
            let gate = if cmd == "anchor-sweep" {
                Some(take(&mut flags, "--gate")?)
            } else {
                None
            };
            let (g, requests) = if cmd == "anchor-sweep" {
                let radius = take(&mut flags, "--radius")?
                    .parse::<usize>()
                    .map_err(|_| "bad radius")?;
                let thresholds = take(&mut flags, "--thresholds")?
                    .parse::<usize>()
                    .map_err(|_| "bad thresholds")?;
                filang::anchors::neighborhood(radius, thresholds)?
            } else {
                filang::anchors::catalog()?
            };
            finish(&flags)?;
            let options = filang::anchor_run::Options {
                data,
                out,
                mode,
                backend,
                capture,
                batch: 32,
                memory: 128 * 1024 * 1024,
            };
            println!(
                "{}",
                filang::anchor_run::run(&g, &requests, &options, gate.as_deref())?
            );
        }
        "walk-search" | "walk-inspect" => {
            let path = take(&mut flags, "--config")?;
            let out = flags.remove("--out");
            finish(&flags)?;
            let raw = fs::read_to_string(path).map_err(|e| e.to_string())?;
            let mut cfg = filang::walk_config::WalkConfig::parse(&raw)?;
            if let Some(p) = out {
                cfg.base.out = p;
            }
            if cmd == "walk-inspect" {
                println!("{}", filang::walk::inspect(&cfg));
            } else {
                let summary = filang::walk::run(&cfg)?;
                report::write(Path::new(&cfg.base.out).join("experiment.cfg"), &raw)?;
                println!("{summary}");
            }
        }
        "walk-evaluate" => {
            let data = take(&mut flags, "--data")?;
            let selection = take(&mut flags, "--selection")?;
            let out = take(&mut flags, "--out")?;
            let scenario = flags
                .remove("--scenario")
                .unwrap_or_else(|| "primary".into());
            if scenario != "primary" && scenario != "stress" {
                return Err("scenario must be primary or stress".into());
            }
            let backend = filang::kernels::Backend::resolve(
                &flags.remove("--backend").unwrap_or_else(|| "auto".into()),
            )?;
            finish(&flags)?;
            let _ =
                filang::walk_evaluate::run(&data, &selection, &out, scenario == "stress", backend)?;
            println!("Walk evaluation: {out}/evaluation.json");
        }
        "search" | "inspect" => {
            let path = take(&mut flags, "--config")?;
            let output_override = flags.remove("--out");
            finish(&flags)?;
            let raw = fs::read_to_string(&path).map_err(|e| e.to_string())?;
            let mut cfg = Config::parse(&raw)?;
            if let Some(path) = output_override {
                cfg.out = path;
            }
            if cmd == "inspect" {
                let (g, c, p) = search::generate(&cfg)?;
                println!("programs={} DAG_definition_nodes={} generation_proposals={} generated_requested={}",c.len(),g.nodes.len(),p,cfg.generated);
            } else {
                let result = search::run(&cfg)?;
                report::write(Path::new(&cfg.out).join("experiment.cfg"), &raw)?;
                println!("{result}");
            }
        }
        "evaluate" => {
            let path = take(&mut flags, "--data")?;
            let sel = take(&mut flags, "--selection")?;
            let out = take(&mut flags, "--out")?;
            let stress = if flags.contains_key("--fee-bps") || flags.contains_key("--slip-bps") {
                Some(Costs {
                    fee_bps: take(&mut flags, "--fee-bps")?
                        .parse()
                        .map_err(|_| "bad fee")?,
                    slip_bps: take(&mut flags, "--slip-bps")?
                        .parse()
                        .map_err(|_| "bad slippage")?,
                })
            } else {
                None
            };
            finish(&flags)?;
            let _ = search::evaluate_frozen(&path, &sel, &out, stress)?;
            println!("Evaluation: {out}/evaluation.json");
        }
        "demo" => {
            let out = take(&mut flags, "--out")?;
            finish(&flags)?;
            report::create_out(&out)?;
            let all = format!("{out}/all.csv");
            data::write_synthetic(&all, 5000)?;
            let raw = fs::read_to_string(&all).map_err(|e| e.to_string())?;
            let cutoff = data::date("2021-07-01")?;
            let discovery = raw
                .lines()
                .enumerate()
                .filter(|(i, l)| {
                    *i == 0 || l.split(',').next().unwrap().parse::<i64>().unwrap() < cutoff
                })
                .map(|(_, l)| l)
                .collect::<Vec<_>>()
                .join("\n")
                + "\n";
            let discovery_path = format!("{out}/discovery.csv");
            report::write(&discovery_path, &discovery)?;
            let config=format!("version=1\ndata={discovery_path}\nout={out}/search\ntrain_start=2020-02-01\nvalidation_start=2021-01-01\nvalidation_end=2021-07-01\nevaluation_start=2021-07-01\nevaluation_end=2022-01-01\ninterval_seconds=14400\ngenerated_features=96\nseed=42\nwindows=4,8,16,32\nquantiles=0.1,0.3,0.5,0.7,0.9\nbatch_size=16\nmemory_mib=64\ntop_k=2\nfee_bps=5\nslip_bps=5\nvalidation_blocks=2\nmin_train_trades=2\nmin_validation_trades=2\nmin_exposure=0.02\nmax_exposure=0.98\nstability_penalty=0.5\ncomplexity_penalty=0.001\nmax_depth=16\nmax_nodes=64\nscorer=events\n");
            report::write(format!("{out}/demo.cfg"), &config)?;
            let cfg = Config::parse(&config)?;
            let _ = search::run(&cfg)?;
            let _ = search::evaluate_frozen(
                &all,
                &format!("{out}/search/frozen.tsv"),
                &format!("{out}/evaluation"),
                None,
            )?;
            println!("Synthetic demonstration complete: {out}");
        }
        _ => return Err(format!("unknown command {cmd}\n{HELP}")),
    }
    Ok(())
}
