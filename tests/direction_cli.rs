//! The real native command is checked against an explicit chronological
//! oracle, including gaps, phase boundaries, flat labels and frozen counts.
use filang::{
    data::date,
    direction::{EVENT_HEADER, PATTERN_HEADER},
    geometry::{GeometryMode, GeometryPattern},
};
use std::{
    collections::HashMap,
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

const DAY: i64 = 86400;

struct Fixture {
    root: PathBuf,
    csv: PathBuf,
    rows: Vec<(i64, [f64; 4])>,
}
impl Fixture {
    fn new(name: &str) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "filang-direction-{name}-{}-{now}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let csv = root.join("daily.csv");
        let start = date("2024-01-01").unwrap();
        let mut rows = Vec::new();
        let mut text = String::from("timestamp,open,high,low,close,volume\n");
        for day in 0..40 {
            // Missing bars remain missing. The downstream stream must not
            // interpret neighboring rows across either hole as lag one.
            if day == 7 || day == 24 {
                continue;
            }
            let base = 100.0 + ((day * 5) % 9) as f64;
            let row = match day % 8 {
                0 => [base, base, base, base],
                1 => [base, base + 2.0, base, base + 2.0],
                2 => [base + 2.0, base + 2.0, base, base],
                3 => [base, base + 4.0, base - 1.0, base + 1.0],
                4 => [base + 1.0, base + 4.0, base - 1.0, base],
                5 => [base, base, base - 2.0, base],
                6 => [base, base + 2.0, base, base],
                _ => [base, base + 3.0, base - 3.0, base],
            };
            let timestamp = start + day * DAY;
            writeln!(
                text,
                "{timestamp},{},{},{},{},100",
                row[0], row[1], row[2], row[3]
            )
            .unwrap();
            rows.push((timestamp, row));
        }
        fs::write(&csv, text).unwrap();
        Self { root, csv, rows }
    }

    fn args(&self, out: &str, workers: usize, extra: &[(&str, &str)]) -> Vec<String> {
        let mut args = vec!["geometry-direction-sweep".into()];
        for (key, value) in [
            ("--data", self.csv.to_str().unwrap().to_owned()),
            ("--out", self.root.join(out).to_str().unwrap().to_owned()),
            ("--interval-seconds", DAY.to_string()),
            ("--history-start", "2024-01-01".into()),
            ("--validation-start", "2024-01-17".into()),
            ("--test-start", "2024-01-27".into()),
            ("--end", "2024-02-10".into()),
            ("--bars", "2,3,10".into()),
            ("--modes", "oriented,unoriented".into()),
            ("--workers", workers.to_string()),
        ] {
            args.push(key.into());
            args.push(value);
        }
        for (key, value) in extra {
            args.push((*key).into());
            args.push((*value).into());
        }
        args
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn invoke(args: &[String]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_filang"))
        .args(args)
        .output()
        .unwrap()
}
fn success(args: &[String]) -> String {
    let output = invoke(args);
    assert!(
        output.status.success(),
        "{args:?}\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}
fn failure(args: &[String]) -> String {
    let output = invoke(args);
    assert!(!output.status.success(), "unexpected success: {args:?}");
    String::from_utf8(output.stderr).unwrap()
}
fn text(path: impl AsRef<Path>) -> String {
    fs::read_to_string(path).unwrap()
}
fn number(json: &str, key: &str) -> u64 {
    json.split(&format!("\"{key}\":"))
        .nth(1)
        .unwrap()
        .split(|c: char| !c.is_ascii_digit())
        .next()
        .unwrap()
        .parse()
        .unwrap()
}
fn sign(a: f64, b: f64) -> i8 {
    (a > b) as i8 - (a < b) as i8
}

#[test]
fn chronological_labels_counts_gaps_and_ten_bar_universes() {
    let fixture = Fixture::new("oracle");
    let manifest = success(&fixture.args("run", 3, &[]));
    assert_eq!(number(&manifest, "gap_count"), 2);
    assert_eq!(number(&manifest, "missing_grid_bars"), 2);
    let boundary_a = date("2024-01-17").unwrap();
    let boundary_b = date("2024-01-27").unwrap();
    let end = date("2024-02-10").unwrap();
    let mut distinct_targets = 0;
    let mut flat_targets = 0;
    for bars in [2usize, 3, 10] {
        for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
            let task = fixture.root.join(format!("run/tasks/n{bars:02}-{mode}"));
            let mut ids = HashMap::<String, usize>::new();
            let mut patterns = Vec::<(String, [u64; 18])>::new();
            let mut events = EVENT_HEADER.to_owned();
            let mut gap_purged = 0;
            let mut boundary_purged = 0;
            for t in bars - 1..fixture.rows.len() - 1 {
                let window = &fixture.rows[t + 1 - bars..=t + 1];
                if window.windows(2).any(|pair| pair[1].0 - pair[0].0 != DAY) {
                    gap_purged += 1;
                    continue;
                }
                let timestamp = fixture.rows[t].0;
                let target_timestamp = fixture.rows[t + 1].0;
                let (split, name, split_end) = if timestamp < boundary_a {
                    (0, "train", boundary_a)
                } else if timestamp < boundary_b {
                    (1, "validation", boundary_b)
                } else {
                    (2, "test", end)
                };
                if target_timestamp >= split_end || target_timestamp + DAY > split_end {
                    boundary_purged += 1;
                    continue;
                }
                let rows = fixture.rows[t + 1 - bars..=t]
                    .iter()
                    .rev()
                    .map(|row| row.1)
                    .collect::<Vec<_>>();
                let pattern = GeometryPattern::from_ohlc(&rows, mode).unwrap().to_string();
                let id = if let Some(id) = ids.get(&pattern) {
                    *id
                } else {
                    let id = patterns.len();
                    ids.insert(pattern.clone(), id);
                    patterns.push((pattern, [0; 18]));
                    id
                };
                let target_cc = sign(fixture.rows[t + 1].1[3], fixture.rows[t].1[3]);
                let target_body = sign(fixture.rows[t + 1].1[3], fixture.rows[t + 1].1[0]);
                let current_cc = sign(fixture.rows[t].1[3], fixture.rows[t - 1].1[3]);
                let current_body = sign(fixture.rows[t].1[3], fixture.rows[t].1[0]);
                patterns[id].1[split * 6 + (target_cc + 1) as usize] += 1;
                patterns[id].1[split * 6 + 3 + (target_body + 1) as usize] += 1;
                writeln!(events, "{timestamp}\t{target_timestamp}\t{name}\t{id}\t{target_cc}\t{target_body}\t{current_cc}\t{current_body}").unwrap();
                distinct_targets += (target_cc != target_body) as usize;
                flat_targets += (target_cc == 0 || target_body == 0) as usize;
            }
            assert_eq!(text(task.join("events.tsv")), events);
            let mut catalogue = PATTERN_HEADER.to_owned();
            for (id, (pattern, counts)) in patterns.iter().enumerate() {
                write!(catalogue, "{id}\t{pattern}").unwrap();
                for count in counts {
                    write!(catalogue, "\t{count}").unwrap();
                }
                catalogue.push('\n');
            }
            assert_eq!(text(task.join("patterns.tsv")), catalogue);
            let summary = text(task.join("summary.json"));
            assert_eq!(number(&summary, "gap_purged"), gap_purged);
            assert_eq!(number(&summary, "boundary_purged"), boundary_purged);
            assert_eq!(number(&summary, "observed_patterns"), patterns.len() as u64);
            assert_eq!(
                number(&summary, "events"),
                (events.lines().count() - 1) as u64
            );
            assert_eq!(
                number(&summary, "candidate_decisions"),
                number(&summary, "events") + gap_purged + boundary_purged
            );
            let train_patterns = patterns
                .iter()
                .filter(|(_, counts)| counts[..6].iter().sum::<u64>() > 0)
                .count();
            assert_eq!(
                number(&summary, "training_observed_patterns"),
                train_patterns as u64
            );
            if bars == 10 {
                let expected = match mode {
                    GeometryMode::Unoriented => "60654091922379541904994268730790100840968",
                    GeometryMode::Oriented => "44121589533882676853417959154810808313579452",
                };
                assert!(summary.contains(&format!("\"universe_patterns\":\"{expected}\"")));
            }
        }
    }
    assert!(
        distinct_targets > 0,
        "fixture must distinguish the two outcomes"
    );
    assert!(flat_targets > 0, "fixture must retain flat outcomes");
}

#[test]
fn worker_changes_resume_and_tamper_detection_preserve_exact_artifacts() {
    let fixture = Fixture::new("resume");
    let first = success(&fixture.args("resumed", 1, &[("--max-tasks", "1")]));
    assert!(first.contains("\"status\":\"PAUSED\""));
    assert_eq!(number(&first, "completed_tasks"), 1);
    let resumed = success(&fixture.args("resumed", 4, &[("--resume", "true")]));
    assert_eq!(number(&resumed, "resumed_tasks"), 1);
    assert_eq!(number(&resumed, "completed_tasks"), 6);
    success(&fixture.args("fresh", 2, &[]));
    for bars in [2, 3, 10] {
        for mode in ["unoriented", "oriented"] {
            for file in [
                "events.tsv",
                "patterns.tsv",
                "summary.json",
                "task.identity",
            ] {
                let suffix = format!("tasks/n{bars:02}-{mode}/{file}");
                assert_eq!(
                    text(fixture.root.join("resumed").join(&suffix)),
                    text(fixture.root.join("fresh").join(&suffix)),
                    "{suffix}"
                );
            }
        }
    }
    let corrupted = fixture.root.join("resumed/tasks/n02-unoriented/events.tsv");
    let mut bad = text(&corrupted);
    bad.push_str("tampered\n");
    fs::write(corrupted, bad).unwrap();
    assert!(
        failure(&fixture.args("resumed", 3, &[("--resume", "true")])).contains("checksum mismatch")
    );
    let changed = text(&fixture.csv).replace(",100\n", ",101\n");
    fs::write(&fixture.csv, changed).unwrap();
    assert!(failure(&fixture.args("fresh", 3, &[("--resume", "true")]))
        .contains("context/input/executable mismatch"));
}

#[test]
fn strict_input_resource_and_argument_errors_are_explicit() {
    let fixture = Fixture::new("guards");
    assert!(failure(&fixture.args("workers", 0, &[])).contains("workers must"));
    assert!(
        failure(&fixture.args("memory", 1, &[("--memory-mib", "15")])).contains("memory_mib must")
    );
    assert!(failure(&fixture.args("rows", 1, &[("--max-rows", "10")])).contains("exceeds max_rows"));
    let bounded = success(&fixture.args("bounded", 6, &[("--memory-mib", "16")]));
    assert_eq!(number(&bounded, "effective_workers"), 1);
    let original = text(&fixture.csv);
    let mut rows = original.lines().map(str::to_owned).collect::<Vec<_>>();
    rows[2] = rows[1].clone();
    fs::write(&fixture.csv, format!("{}\n", rows.join("\n"))).unwrap();
    assert!(failure(&fixture.args("duplicate", 1, &[])).contains("duplicate/out-of-order"));
    let original_first = fixture.rows[0].0.to_string();
    let off_grid = original.replacen(&original_first, &(fixture.rows[0].0 + 1).to_string(), 1);
    fs::write(&fixture.csv, off_grid).unwrap();
    assert!(failure(&fixture.args("offgrid", 1, &[])).contains("off-grid"));
    fs::write(&fixture.csv, original).unwrap();
    let mut arguments = fixture.args("width", 1, &[]);
    let i = arguments
        .iter()
        .position(|value| value == "--bars")
        .unwrap();
    arguments[i + 1] = "11".into();
    assert!(failure(&arguments).contains("2..=10"));
    arguments[i + 1] = "2,2".into();
    assert!(failure(&arguments).contains("duplicate"));
}
