use filang::{
    data::{self, date},
    kernels::Backend,
    walk,
    walk_config::WalkConfig,
    walk_evaluate,
};
use std::{
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};
fn config(data: &str, out: &str) -> String {
    let base = include_str!("../examples/btc4h-walk.cfg");
    let changes = [
        ("data", data),
        ("out", out),
        ("train_start", "2020-02-01"),
        ("validation_start", "2020-07-01"),
        ("validation_end", "2023-01-01"),
        ("evaluation_start", "2023-01-01"),
        ("evaluation_end", "2023-07-01"),
        ("windows", "4,8,16"),
        ("quantiles", "0.1,0.3,0.5,0.7,0.9"),
        ("feature_addresses", "32"),
        ("generation_page_size", "8"),
        ("threads", "2"),
        ("archive_size", "12"),
        ("top_k", "2"),
        (
            "walk_edges",
            "2020-07-01,2021-01-01,2021-07-01,2022-01-01,2022-07-01,2023-01-01",
        ),
        (
            "walk_outer",
            "2021-07-01,2022-01-01,2022-07-01,2023-01-01,2023-07-01",
        ),
        ("walk_inner", "2"),
        ("min_positive_windows", "1"),
        ("min_window_trades", "1"),
        ("neighbor_radius", "0"),
    ];
    base.lines()
        .map(|line| {
            let k = line.split('=').next().unwrap();
            changes
                .iter()
                .find(|(key, _)| *key == k)
                .map_or_else(|| line.to_string(), |(_, v)| format!("{k}={v}"))
        })
        .collect::<Vec<_>>()
        .join("\n")
        + "\n"
}
fn cut(raw: &str, end: i64) -> String {
    raw.lines()
        .enumerate()
        .filter(|(i, l)| *i == 0 || l.split(',').next().unwrap().parse::<i64>().unwrap() < end)
        .map(|(_, l)| l)
        .collect::<Vec<_>>()
        .join("\n")
        + "\n"
}
fn first_fold(path: &Path) -> Vec<String> {
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .filter(|l| l.starts_with("0\t"))
        .map(str::to_string)
        .collect()
}
#[test]
fn native_walk_reference_future_invariance_and_sealed_replay() {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("filang-walk-{}-{nonce}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let all = dir.join("all.csv");
    data::write_synthetic(all.to_str().unwrap(), 10000).unwrap();
    let raw = fs::read_to_string(&all).unwrap();
    let discovery = dir.join("discovery.csv");
    fs::write(&discovery, cut(&raw, date("2023-01-01").unwrap())).unwrap();
    let text = config(
        discovery.to_str().unwrap(),
        dir.join("fast").to_str().unwrap(),
    );
    let cfg = WalkConfig::parse(&text).unwrap();
    walk::run(&cfg).unwrap();
    let frozen = dir.join("fast/walk.tsv");
    let original = fs::read_to_string(&frozen).unwrap();
    assert!(!first_fold(&frozen).is_empty());
    let reference = text
        .replace("kernel_backend=auto", "kernel_backend=scalar")
        .replace("threads=2", "threads=1")
        .replace("reuse_basis=true", "reuse_basis=false")
        .replace(
            "reuse_prefix_quantiles=true",
            "reuse_prefix_quantiles=false",
        )
        .replace("reuse_cost_scenarios=true", "reuse_cost_scenarios=false")
        .replace("reuse_windows=true", "reuse_windows=false")
        .replace("scorer=events", "scorer=scan")
        .replace(
            dir.join("fast").to_str().unwrap(),
            dir.join("reference").to_str().unwrap(),
        );
    walk::run(&WalkConfig::parse(&reference).unwrap()).unwrap();
    assert_eq!(
        original,
        fs::read_to_string(dir.join("reference/walk.tsv")).unwrap(),
        "shared/SIMD/parallel versus direct scalar plans"
    );
    let short = dir.join("short.csv");
    fs::write(&short, cut(&raw, date("2021-07-01").unwrap())).unwrap();
    let shorter = text
        .replace(discovery.to_str().unwrap(), short.to_str().unwrap())
        .replace(
            dir.join("fast").to_str().unwrap(),
            dir.join("short-run").to_str().unwrap(),
        )
        .replace("validation_end=2023-01-01", "validation_end=2021-07-01")
        .replace("evaluation_start=2023-01-01", "evaluation_start=2021-07-01")
        .replace("evaluation_end=2023-07-01", "evaluation_end=2022-01-01")
        .replace(
            "walk_edges=2020-07-01,2021-01-01,2021-07-01,2022-01-01,2022-07-01,2023-01-01",
            "walk_edges=2020-07-01,2021-01-01,2021-07-01",
        )
        .replace(
            "walk_outer=2021-07-01,2022-01-01,2022-07-01,2023-01-01,2023-07-01",
            "walk_outer=2021-07-01,2022-01-01",
        );
    walk::run(&WalkConfig::parse(&shorter).unwrap()).unwrap();
    assert_eq!(
        first_fold(&frozen),
        first_fold(&dir.join("short-run/walk.tsv")),
        "later fold addition changed earlier choices"
    );
    let altered = fs::read_to_string(&discovery)
        .unwrap()
        .lines()
        .enumerate()
        .map(|(i, l)| {
            let mut p = l.split(',').map(str::to_string).collect::<Vec<_>>();
            if i > 0 && p[0].parse::<i64>().unwrap() >= date("2021-07-01").unwrap() {
                for v in &mut p[1..5] {
                    *v = format!("{:.12}", v.parse::<f64>().unwrap() * 1.5);
                }
            }
            p.join(",")
        })
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    fs::write(dir.join("altered.csv"), altered).unwrap();
    let mutated = text
        .replace(
            discovery.to_str().unwrap(),
            dir.join("altered.csv").to_str().unwrap(),
        )
        .replace(
            dir.join("fast").to_str().unwrap(),
            dir.join("mutated").to_str().unwrap(),
        );
    walk::run(&WalkConfig::parse(&mutated).unwrap()).unwrap();
    assert_eq!(
        first_fold(&frozen),
        first_fold(&dir.join("mutated/walk.tsv")),
        "future prices changed earlier choices"
    );
    let report = walk_evaluate::run(
        all.to_str().unwrap(),
        frozen.to_str().unwrap(),
        dir.join("evaluation").to_str().unwrap(),
        false,
        Backend::resolve("auto").unwrap(),
    )
    .unwrap();
    assert!(report.contains("retrospective_walkforward_not_untouched"));
    assert!(report.contains("generated_diverse"));
    assert!(report.contains("buy_hold_continuous"));
    fs::write(&frozen, original + "\n").unwrap();
    assert!(walk_evaluate::run(
        all.to_str().unwrap(),
        frozen.to_str().unwrap(),
        dir.join("bad").to_str().unwrap(),
        false,
        Backend::Scalar
    )
    .unwrap_err()
    .contains("hash mismatch"));
    let large = text.replace("feature_addresses=32", "feature_addresses=1000000000000");
    let c = WalkConfig::parse(&large).unwrap();
    assert_eq!(c.page_count(), 125000000000);
    assert!(walk::inspect(&c).contains("plan_only"));
    fs::remove_dir_all(dir).unwrap();
}
