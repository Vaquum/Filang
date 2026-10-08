//! End-to-end checks of complete-domain geometry experiments. These tests use
//! the real binary, persisted checkpoints, and independent frozen Market replay.
use filang::{data, geometry::GeometryPattern, hash::sha256};
use std::{
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

const START: &str = "2024-01-09";
const END: &str = "2024-01-29";
const INTERVAL: &str = "86400";

struct Fixture {
    root: PathBuf,
    data: PathBuf,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "filang-geometry-cli-{name}-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let data = root.join("daily.csv");
        write_candles(&data, 28, false);
        Self { root, data }
    }

    fn path(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }

    fn example(&self, profile: &str) -> PathBuf {
        let config = self.path(&format!("{profile}.cfg"));
        success(&arguments(
            "geometry-example",
            &[
                ("--out", path(&config)),
                ("--profile", profile),
                ("--data", path(&self.data)),
                ("--start", START),
                ("--end", END),
                ("--interval-seconds", INTERVAL),
            ],
        ));
        // Keep costs nonzero while limiting annualized numerical magnitudes in
        // this short fixture. The same costs are supplied to frozen replay.
        replace_key(&config, "fee_bps", "1");
        replace_key(&config, "slip_bps", "1");
        config
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn path(path: &Path) -> &str {
    path.to_str().unwrap()
}

fn write_candles(path: &Path, n: usize, invalid: bool) {
    let start = data::date("2024-01-01").unwrap();
    let mut csv = String::from("timestamp,open,high,low,close,volume\n");
    for i in 0..n {
        let base = 1000.0 + ((i * 7) % 11) as f64 * 0.2 + i as f64 * 0.04;
        let mut row = match i % 12 {
            0 => [base, base, base, base],
            1 => [base, base + 1.0, base, base + 1.0],
            2 => [base + 1.0, base + 1.0, base, base],
            3 => [base, base + 1.0, base - 0.5, base + 1.0],
            4 => [base + 1.0, base + 1.8, base, base],
            5 => [base, base, base - 0.75, base],
            6 => [base, base + 0.75, base, base],
            7 => [base, base + 1.0, base - 1.0, base],
            8 => [base + 0.3, base + 1.6, base - 0.4, base + 1.1],
            9 => [base + 1.1, base + 1.6, base - 0.4, base + 0.3],
            10 => [base, base + 1.6, base, base + 1.0],
            _ => [base + 1.0, base + 1.0, base - 0.6, base],
        };
        if invalid && i == 10 {
            row[0] = f64::NAN;
        }
        writeln!(
            csv,
            "{},{:.12},{:.12},{:.12},{:.12},100",
            start + i as i64 * 86400,
            row[0],
            row[1],
            row[2],
            row[3]
        )
        .unwrap();
    }
    fs::write(path, csv).unwrap();
}

fn replace_key(path: &Path, key: &str, value: &str) {
    let prefix = format!("{key}=");
    let old = fs::read_to_string(path).unwrap();
    let mut count = 0;
    let mut changed = String::new();
    for line in old.lines() {
        if line.starts_with(&prefix) {
            writeln!(changed, "{key}={value}").unwrap();
            count += 1;
        } else {
            writeln!(changed, "{line}").unwrap();
        }
    }
    assert_eq!(count, 1, "missing or duplicate test config key {key}");
    fs::write(path, changed).unwrap();
}

fn arguments(command: &str, options: &[(&str, &str)]) -> Vec<String> {
    let mut arguments = vec![command.to_owned()];
    for (key, value) in options {
        arguments.push((*key).to_owned());
        arguments.push((*value).to_owned());
    }
    arguments
}

fn invoke(arguments: &[String]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_filang"))
        .args(arguments)
        .output()
        .unwrap_or_else(|error| panic!("failed to execute {arguments:?}: {error}"))
}

fn success(arguments: &[String]) -> String {
    let output = invoke(arguments);
    assert!(
        output.status.success(),
        "command {arguments:?}\nstatus: {}\nstdout: {}\nstderr: {}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

fn failure(arguments: &[String]) -> String {
    let output = invoke(arguments);
    assert!(
        !output.status.success(),
        "unexpected success: {arguments:?}\n{}",
        String::from_utf8_lossy(&output.stdout)
    );
    String::from_utf8(output.stderr).unwrap()
}

fn experiment_args(
    command: &str,
    config: &Path,
    out: &Path,
    workers: &str,
    extra: &[(&str, &str)],
) -> Vec<String> {
    let mut options = vec![
        ("--config", path(config)),
        ("--out", path(out)),
        ("--workers", workers),
        ("--backend", "scalar"),
        ("--certificates", "true"),
        ("--capture", "true"),
    ];
    options.extend_from_slice(extra);
    arguments(command, &options)
}

fn evaluation_args(data: &Path, selection: &Path, out: &Path) -> Vec<String> {
    arguments(
        "geometry-evaluate",
        &[
            ("--data", path(data)),
            ("--selection", path(selection)),
            ("--start", START),
            ("--end", END),
            ("--out", path(out)),
            ("--interval-seconds", INTERVAL),
            ("--fee-bps", "1"),
            ("--slip-bps", "1"),
            ("--backend", "scalar"),
        ],
    )
}

/// Extract a complete value from the small native JSON reports. Balanced
/// containers and escaped strings are handled so nested best.metrics is read
/// without depending on whitespace, array length, or field order.
fn json_field<'a>(json: &'a str, key: &str) -> &'a str {
    let marker = format!("\"{key}\"");
    let at = json
        .find(&marker)
        .unwrap_or_else(|| panic!("missing {key} in {json}"));
    let rest = json[at + marker.len()..].trim_start();
    let rest = rest.strip_prefix(':').unwrap().trim_start();
    let bytes = rest.as_bytes();
    assert!(!bytes.is_empty());
    let mut quoted = false;
    let mut escaped = false;
    let mut depth = 0usize;
    let container = bytes[0] == b'[' || bytes[0] == b'{';
    let string = bytes[0] == b'"';
    for (i, &byte) in bytes.iter().enumerate() {
        if quoted {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
                if string && depth == 0 {
                    return &rest[..i + 1];
                }
            }
            continue;
        }
        match byte {
            b'"' => quoted = true,
            b'[' | b'{' => depth += 1,
            b']' | b'}' => {
                if depth == 0 {
                    return rest[..i].trim_end();
                }
                depth -= 1;
                if container && depth == 0 {
                    return &rest[..i + 1];
                }
            }
            b',' if depth == 0 => return rest[..i].trim_end(),
            _ => {}
        }
    }
    rest.trim_end()
}

fn json_string(json: &str, key: &str) -> String {
    let value = json_field(json, key);
    assert!(value.starts_with('"') && value.ends_with('"'));
    value[1..value.len() - 1].to_owned()
}

fn json_count(json: &str, key: &str) -> u128 {
    json_field(json, key).trim_matches('"').parse().unwrap()
}

fn metrics(json: &str) -> Vec<Option<f64>> {
    let array = json_field(json, "metrics");
    assert!(array.starts_with('[') && array.ends_with(']'));
    array[1..array.len() - 1]
        .split(',')
        .map(|value| {
            let value = value.trim();
            if value == "null" {
                None
            } else {
                Some(value.parse().unwrap())
            }
        })
        .collect()
}

fn assert_metrics_equal(expected: &str, actual: &str) {
    let expected = metrics(expected);
    let actual = metrics(actual);
    assert_eq!(expected.len(), 10);
    assert_eq!(actual.len(), 10);
    for (i, (a, b)) in expected.iter().zip(&actual).enumerate() {
        match (a, b) {
            (Some(a), Some(b)) => assert!(
                (a - b).abs() <= 1e-10,
                "metric {i} differs: {a:.17} versus {b:.17}"
            ),
            (None, None) => {}
            _ => panic!("metric {i} has different null status: {a:?} versus {b:?}"),
        }
    }
}

fn summary(out: &Path) -> String {
    fs::read_to_string(out.join("summary.json")).unwrap()
}

fn assert_complete(summary: &str, requested: u128) {
    assert_eq!(json_string(summary, "status"), "PASS");
    assert_eq!(json_field(summary, "coverage_complete"), "true");
    assert_eq!(
        json_count(summary, "requested_strategy_addresses"),
        requested
    );
    assert_eq!(
        json_count(summary, "resolved_strategy_addresses"),
        requested
    );
    assert!(json_count(summary, "completed_tasks") > 0);
    assert!(json_count(summary, "metric_regions_evaluated") > 0);
    assert!(json_count(summary, "metric_regions_evaluated") < requested);
}

fn assert_selection(path: &Path, bars: usize) {
    let text = fs::read_to_string(path).unwrap();
    let mut lines = text.lines();
    assert_eq!(lines.next(), Some("slot\tlags\tqualifier\tpattern"));
    let rows: Vec<_> = lines.collect();
    assert_eq!(rows.len(), 2);
    for (slot, row) in rows.iter().enumerate() {
        let fields: Vec<_> = row.split('\t').collect();
        assert_eq!(fields.len(), 4);
        assert_eq!(fields[0].parse::<usize>().unwrap(), slot);
        assert_eq!(fields[1].split(',').count(), bars);
        let pattern: GeometryPattern = fields[3].parse().unwrap();
        assert_eq!(pattern.len(), bars);
        assert!(fields[3].starts_with("g1:o:"));
    }
    let seal = fs::read_to_string(format!("{}.sha256", path.display())).unwrap();
    assert_eq!(seal.trim(), sha256(text.as_bytes()));
}

#[test]
fn smoke_prepare_pause_resume_matches_fresh_and_frozen_replay() {
    let fixture = Fixture::new("resume");
    let config = fixture.example("smoke");
    let requested = 6 * 7452u128 * 7452;
    let plan = success(&arguments(
        "geometry-inspect",
        &[("--config", path(&config))],
    ));
    assert_eq!(json_string(&plan, "status"), "PLAN_ONLY");
    assert_eq!(json_count(&plan, "requested_strategy_addresses"), requested);
    assert_eq!(
        json_string(&plan, "physical_work"),
        "data_dependent_not_yet_executed"
    );

    let fresh = fixture.path("fresh");
    success(&experiment_args(
        "geometry-sweep",
        &config,
        &fresh,
        "1",
        &[],
    ));
    let fresh_summary = summary(&fresh);
    assert_complete(&fresh_summary, requested);
    assert!(json_count(&fresh_summary, "completed_tasks") > 1);

    let resumed = fixture.path("resumed");
    success(&experiment_args(
        "geometry-prepare",
        &config,
        &resumed,
        "1",
        &[],
    ));
    let prepared = summary(&resumed);
    assert_eq!(json_string(&prepared, "status"), "PREPARED");
    assert_eq!(json_field(&prepared, "coverage_complete"), "false");
    assert_eq!(json_count(&prepared, "resolved_strategy_addresses"), 0);
    assert_eq!(json_count(&prepared, "completed_tasks"), 0);
    assert!(!resumed.join("best-geometry.tsv").exists());
    success(&experiment_args(
        "geometry-sweep",
        &config,
        &resumed,
        "1",
        &[("--resume", "true"), ("--max-tasks", "1")],
    ));
    let paused = summary(&resumed);
    assert_eq!(json_string(&paused, "status"), "PAUSED");
    assert_eq!(json_field(&paused, "coverage_complete"), "false");
    assert_eq!(json_count(&paused, "new_tasks"), 1);
    assert_eq!(json_count(&paused, "completed_tasks"), 1);
    assert!(json_count(&paused, "resolved_strategy_addresses") > 0);
    assert!(json_count(&paused, "resolved_strategy_addresses") < requested);
    success(&experiment_args(
        "geometry-sweep",
        &config,
        &resumed,
        "2",
        &[("--resume", "true")],
    ));
    let resumed_summary = summary(&resumed);
    assert_complete(&resumed_summary, requested);
    assert_eq!(json_count(&resumed_summary, "native_workers"), 2);
    assert_eq!(json_count(&resumed_summary, "reused_tasks"), 1);
    assert_eq!(
        json_count(&resumed_summary, "new_tasks") + 1,
        json_count(&resumed_summary, "completed_tasks")
    );
    assert_eq!(
        json_string(&fresh_summary, "result_digest"),
        json_string(&resumed_summary, "result_digest")
    );
    assert_eq!(
        json_field(&fresh_summary, "best"),
        json_field(&resumed_summary, "best")
    );
    for file in [
        "best-geometry.tsv",
        "best-geometry.tsv.sha256",
        "best-rule.txt",
        "best-rule.txt.sha256",
    ] {
        assert_eq!(
            fs::read(fresh.join(file)).unwrap(),
            fs::read(resumed.join(file)).unwrap(),
            "winner artifact differs: {file}"
        );
    }

    let selected = resumed.join("best-geometry.tsv");
    assert_selection(&selected, 2);
    let evaluation = fixture.path("evaluation");
    success(&evaluation_args(&fixture.data, &selected, &evaluation));
    let replay = fs::read_to_string(evaluation.join("evaluation.json")).unwrap();
    assert_eq!(json_string(&replay, "status"), "PASS");
    assert_eq!(json_string(&replay, "role"), "frozen_geometry_replay");
    assert_eq!(json_count(&replay, "valid_decisions"), 18);
    assert!(json_count(&replay, "active_decisions") > 0);
    assert_metrics_equal(json_field(&resumed_summary, "best"), &replay);
    let decisions = fs::read_to_string(evaluation.join("decisions.csv")).unwrap();
    assert_eq!(decisions.lines().next(), Some("timestamp,valid,active"));
    assert_eq!(decisions.lines().count(), 19);
    let mut active = 0u128;
    for (i, line) in decisions.lines().skip(1).enumerate() {
        let row: Vec<_> = line.split(',').collect();
        assert_eq!(row.len(), 3);
        assert_eq!(
            row[0].parse::<i64>().unwrap(),
            data::date(START).unwrap() + i as i64 * 86400
        );
        assert_eq!(row[1], "1");
        assert!(row[2] == "0" || row[2] == "1");
        active += row[2].parse::<u128>().unwrap();
    }
    assert_eq!(active, json_count(&replay, "active_decisions"));

    // Both frozen inputs are authenticated before any evaluation directory is
    // created. Restore the originals so each failure exercises a separate seal.
    for file in ["best-geometry.tsv", "best-rule.txt"] {
        let artifact = resumed.join(file);
        let original = fs::read(&artifact).unwrap();
        let mut altered = original.clone();
        altered.push(b'\n');
        fs::write(&artifact, altered).unwrap();
        let rejected = fixture.path(&format!("rejected-{file}"));
        let error = failure(&evaluation_args(&fixture.data, &selected, &rejected));
        assert!(
            error.contains("checksum mismatch"),
            "unexpected tamper error: {error}"
        );
        assert!(!rejected.exists());
        fs::write(&artifact, original).unwrap();
    }
    let future = fixture.path("future.csv");
    write_candles(&future, 29, false);
    let rejected = fixture.path("rejected-future-replay");
    let error = failure(&evaluation_args(&future, &selected, &rejected));
    assert!(
        error.contains("future rows are forbidden"),
        "unexpected future error: {error}"
    );
    assert!(!rejected.exists());
}

#[test]
fn trillion_profile_resolves_exact_domain_without_trillions_of_metric_calls() {
    let fixture = Fixture::new("trillion");
    let config = fixture.example("trillion");
    // Two ordered bank pairs, three Boolean templates, three qualifiers on
    // each slot, and the complete oriented three-candle domain on each slot.
    let requested = 54 * 32160252u128 * 32160252;
    assert!(requested > 1_000_000_000_000);
    let plan = success(&arguments(
        "geometry-inspect",
        &[("--config", path(&config))],
    ));
    assert_eq!(json_string(&plan, "status"), "PLAN_ONLY");
    assert_eq!(json_count(&plan, "requested_strategy_addresses"), requested);
    let out = fixture.path("complete");
    success(&experiment_args("geometry-sweep", &config, &out, "2", &[]));
    let report = summary(&out);
    assert_complete(&report, requested);
    assert!(json_count(&report, "metric_regions_evaluated") < 1_000_000);
    assert!(json_count(&report, "signature_pair_products_resolved") < 1_000_000);
    let selection = out.join("best-geometry.tsv");
    assert_selection(&selection, 3);
    let evaluation = fixture.path("evaluation");
    success(&evaluation_args(&fixture.data, &selection, &evaluation));
    let replay = fs::read_to_string(evaluation.join("evaluation.json")).unwrap();
    assert_metrics_equal(json_field(&report, "best"), &replay);
    assert_eq!(json_count(&replay, "valid_decisions"), 18);
}

#[test]
fn invalid_or_future_training_data_and_noncausal_windows_fail_before_output() {
    let fixture = Fixture::new("guards");
    let original = fixture.example("smoke");
    let raw = fs::read_to_string(&original).unwrap();
    for (name, rows, invalid, expected_error) in [
        ("invalid", 28, true, "invalid OHLCV"),
        ("future", 29, false, "future rows are forbidden"),
    ] {
        let data = fixture.path(&format!("{name}.csv"));
        write_candles(&data, rows, invalid);
        let config = fixture.path(&format!("{name}.cfg"));
        fs::write(&config, &raw).unwrap();
        replace_key(&config, "data", path(&data));
        let out = fixture.path(&format!("rejected-{name}"));
        let error = failure(&experiment_args(
            "geometry-prepare",
            &config,
            &out,
            "1",
            &[],
        ));
        assert!(
            error.contains(expected_error),
            "unexpected {name} error: {error}"
        );
        assert!(!out.exists(), "rejected {name} data created output");
    }
    let noncausal = fixture.path("noncausal.cfg");
    fs::write(&noncausal, &raw).unwrap();
    replace_key(&noncausal, "windows", "0,-1;0,2");
    failure(&arguments(
        "geometry-inspect",
        &[("--config", path(&noncausal))],
    ));

    // The explicit mode override selects the smaller complete geometric
    // domain; it does not silently retain body-direction multiplicity.
    let unoriented = fixture.path("unoriented.cfg");
    success(&arguments(
        "geometry-example",
        &[
            ("--out", path(&unoriented)),
            ("--profile", "smoke"),
            ("--mode", "unoriented"),
            ("--data", path(&fixture.data)),
            ("--start", START),
            ("--end", END),
            ("--interval-seconds", INTERVAL),
        ],
    ));
    let plan = success(&arguments(
        "geometry-inspect",
        &[("--config", path(&unoriented))],
    ));
    assert_eq!(json_string(&plan, "mode"), "unoriented");
    assert_eq!(
        json_count(&plan, "requested_strategy_addresses"),
        6 * 2568u128 * 2568
    );
}
