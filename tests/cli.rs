use filang::{
    backtest::{Costs, Market, Rule},
    data::Data,
};
use std::{
    fs,
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};
#[test]
fn cli_end_to_end_and_integrity_guards() {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let out = std::env::temp_dir().join(format!("filang-e2e-{}-{unique}", std::process::id()));
    let p = out.to_str().unwrap();
    let bin = env!("CARGO_BIN_EXE_filang");
    let result = Command::new(bin)
        .args(["demo", "--out", p])
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(out.join("search/frozen.tsv.sha256").is_file());
    assert!(out.join("evaluation/evaluation.json").is_file());
    let report = fs::read_to_string(out.join("evaluation/evaluation.json")).unwrap();
    assert!(report.contains("frozen_final_evaluation_not_selection"));
    let rerun = Command::new(bin)
        .args(["demo", "--out", p])
        .output()
        .unwrap();
    assert!(!rerun.status.success());
    let sel = out.join("search/frozen.tsv");
    let mut changed = fs::read_to_string(&sel).unwrap();
    changed.push('\n');
    fs::write(&sel, changed).unwrap();
    let bad = Command::new(bin)
        .args([
            "evaluate",
            "--data",
            out.join("all.csv").to_str().unwrap(),
            "--selection",
            sel.to_str().unwrap(),
            "--out",
            out.join("bad").to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(!bad.status.success());
    assert!(String::from_utf8_lossy(&bad.stderr).contains("hash mismatch"));
    let cfg_path = out.join("demo.cfg");
    let cfg = fs::read_to_string(&cfg_path)
        .unwrap()
        .replace(
            &format!("data={p}/discovery.csv"),
            &format!("data={p}/all.csv"),
        )
        .replace(&format!("out={p}/search"), &format!("out={p}/leaky"));
    fs::write(&cfg_path, cfg).unwrap();
    let bad = Command::new(bin)
        .args(["search", "--config", cfg_path.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(!bad.status.success());
    assert!(String::from_utf8_lossy(&bad.stderr).contains("future rows are forbidden"));
    fs::remove_dir_all(&out).unwrap();
}
#[test]
fn public_scorer_rejects_invalid_requests() {
    let d=Data::parse("timestamp,open,high,low,close,volume\n0,1,2,1,2,3\n1,2,3,1,2,3\n2,2,3,1,2,3\n3,2,3,1,2,3\n",1).unwrap();
    let m = Market::new(
        &d,
        0,
        4,
        Costs {
            fee_bps: 5.0,
            slip_bps: 5.0,
        },
    )
    .unwrap();
    assert!(m
        .score(
            &[],
            Rule {
                greater: true,
                threshold: 1.0
            }
        )
        .is_err());
    assert!(m
        .score_thresholds(
            &[1.0; 4],
            &[Rule {
                greater: true,
                threshold: f64::NAN
            }]
        )
        .is_err());
    assert!(Market::new(
        &d,
        usize::MAX,
        4,
        Costs {
            fee_bps: 0.0,
            slip_bps: 0.0
        }
    )
    .is_err());
}
