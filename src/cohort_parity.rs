//! Emit baseline and deterministic perturbation histories for independent checks.
use crate::{
    backtest::{Costs, Market, Rule},
    cohort,
    data::{self, Data},
    engine,
    paged::metric_values,
    report::{self, num, quote},
    Result,
};
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};
pub fn run(data_path: &str, out: &str) -> Result<()> {
    let d = Data::read(data_path, 14400)?;
    let start = d.index(data::date("2021-01-01")?);
    if d.timestamps.last().unwrap() + d.interval != data::date("2025-01-01")? {
        return Err("cohort parity requires sealed discovery prefix".into());
    }
    report::create_out(out)?;
    let dir = Path::new(out);
    let mut features =
        BufWriter::new(File::create(dir.join("features.bin")).map_err(|e| e.to_string())?);
    let mut metrics =
        BufWriter::new(File::create(dir.join("metrics.bin")).map_err(|e| e.to_string())?);
    let mut traces =
        BufWriter::new(File::create(dir.join("traces.bin")).map_err(|e| e.to_string())?);
    let markets = [
        Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        },
        Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
    ]
    .iter()
    .map(|&cost| Market::new(&d, start, d.len(), cost))
    .collect::<Result<Vec<_>>>()?;
    let mut requests = vec![];
    for kind in cohort::KINDS {
        let (n, center, grid) = cohort::defaults(kind)?;
        for (label, w, a, b, c) in [
            ("anchor", n, 0., 0., center),
            ("lower_endpoint", n - 1, -0.01, 0.1, grid.value(0)),
            (
                "upper_endpoint",
                n + 1,
                0.01,
                0.05,
                grid.value(grid.count - 1),
            ),
        ] {
            let (mut g, ids) = cohort::stripe(kind, w, a)?;
            let root = cohort::output(&mut g, kind, ids, b, c)?;
            let batch = engine::evaluate(&g, &d, &[root], 128 << 20)?;
            let x = &batch.values[&root];
            for v in x {
                features
                    .write_all(&v.to_le_bytes())
                    .map_err(|e| e.to_string())?;
            }
            for market in &markets {
                let rule = Rule {
                    greater: true,
                    threshold: 0.,
                };
                let m = market.score(x, rule)?;
                for v in metric_values(&m, d.interval) {
                    metrics
                        .write_all(&v.to_le_bytes())
                        .map_err(|e| e.to_string())?;
                }
                let p = x[start..d.len() - 2]
                    .iter()
                    .map(|v| rule.active(*v))
                    .collect::<Vec<_>>();
                let rows = market.position_ledger(&p)?;
                let (mut equity, mut trade) = (0.0, 0.0);
                for row in rows {
                    equity += row.net.ln_1p();
                    if row.active {
                        trade += row.net.ln_1p();
                    }
                    let gain = if row.exit { trade.exp_m1() } else { f64::NAN };
                    for v in [
                        row.active as u8 as f64,
                        row.entry as u8 as f64,
                        row.exit as u8 as f64,
                        row.gross,
                        row.net,
                        equity.exp(),
                        gain,
                    ] {
                        traces
                            .write_all(&v.to_le_bytes())
                            .map_err(|e| e.to_string())?;
                    }
                    if row.exit {
                        trade = 0.;
                    }
                }
            }
            requests.push(format!("{{\"family\":{},\"case\":{},\"n\":{},\"a\":{},\"b\":{},\"c\":{},\"expression\":{},\"feature_id\":{}}}",quote(kind),quote(label),w,num(a),num(b),num(c),quote(&g.expression(root)),quote(&g.identity(root))));
        }
    }
    features.flush().map_err(|e| e.to_string())?;
    metrics.flush().map_err(|e| e.to_string())?;
    traces.flush().map_err(|e| e.to_string())?;
    report::write(dir.join("manifest.json"),&format!("{{\"version\":1,\"role\":\"reference_parity_not_selection\",\"data_sha256\":{},\"engine_sha256\":{},\"catalog_sha256\":{},\"rows\":{},\"start_index\":{},\"end_index\":{},\"interval\":{},\"requests\":[{}]}}\n",quote(&d.digest),quote(&crate::anchor_run::engine_id()?),quote(&cohort::catalog_id()?),d.len(),start,d.len(),d.interval,requests.join(",")))?;
    Ok(())
}
