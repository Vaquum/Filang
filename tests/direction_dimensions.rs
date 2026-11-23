//! The grouped direction sweep with dimensions on, checked against an
//! explicit chronological oracle on a nine-column recording with gaps and
//! bars that have no trades. With no dimension on, the same recording must
//! give byte for byte what its six-column form gives.
use filang::{
    data::date,
    direction::{EVENT_HEADER, PATTERN_HEADER},
    geometry::{
        count_domain_decimal_with_dimensions, Counters, DimensionSet, GeometryMode,
        GeometryPattern, COUNTER_COLUMNS,
    },
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
    rows: Vec<(i64, [f64; 4], Counters)>,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "filang-direction-dimensions-{name}-{}-{now}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let start = date("2024-01-01").unwrap();
        let mut rows = Vec::new();
        let mut six = String::from("timestamp,open,high,low,close,volume\n");
        let mut nine = format!("{COUNTER_COLUMNS}\n");
        for day in 0..40i64 {
            // Missing bars remain missing under both forms.
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
            // Few distinct volumes so they tie; exact balance is common; two
            // bars have no trades, so they have no size and no imbalance.
            let idle = day == 12 || day == 30;
            let volume = if idle { 0 } else { 1000 + (day * 3 % 4) * 500 };
            let taker_buy = volume * [3, 5, 7, 5, 4][(day % 5) as usize] / 10;
            let trades = if idle { 0 } else { 10 + (day * 7 % 3) * 10 };
            let timestamp = start + day * DAY;
            writeln!(
                six,
                "{timestamp},{},{},{},{},100",
                row[0], row[1], row[2], row[3]
            )
            .unwrap();
            // One amount is written with an exponent, as a recording may.
            let volume_text = if day == 3 {
                format!("{}e2", volume / 100)
            } else {
                volume.to_string()
            };
            writeln!(
                nine,
                "{},{},{},{},{},100,{volume_text},{taker_buy},{trades}",
                timestamp * 1000,
                row[0],
                row[1],
                row[2],
                row[3]
            )
            .unwrap();
            rows.push((
                timestamp,
                row,
                Counters::new(volume as f64, taker_buy as f64, trades as f64).unwrap(),
            ));
        }
        fs::write(root.join("six.csv"), six).unwrap();
        fs::write(root.join("nine.csv"), nine).unwrap();
        Self { root, rows }
    }

    fn args(&self, data: &str, out: &str, extra: &[(&str, &str)]) -> Vec<String> {
        let mut args = vec!["geometry-direction-sweep".to_owned()];
        for (key, value) in [
            ("--data", self.root.join(data).to_str().unwrap().to_owned()),
            ("--out", self.root.join(out).to_str().unwrap().to_owned()),
            ("--interval-seconds", DAY.to_string()),
            ("--history-start", "2024-01-01".into()),
            ("--validation-start", "2024-01-17".into()),
            ("--test-start", "2024-01-27".into()),
            ("--end", "2024-02-10".into()),
            ("--bars", "2,3".into()),
            ("--modes", "oriented,unoriented".into()),
            ("--workers", "2".into()),
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

fn sign(a: f64, b: f64) -> i8 {
    if a < b {
        -1
    } else if a > b {
        1
    } else {
        0
    }
}

fn field<'a>(json: &'a str, key: &str) -> &'a str {
    let marker = format!("\"{key}\":");
    let at = json
        .find(&marker)
        .unwrap_or_else(|| panic!("missing {key} in {json}"));
    let rest = &json[at + marker.len()..];
    let end = if rest.starts_with('[') {
        rest.find(']').unwrap() + 1
    } else {
        rest.find(|c| c == ',' || c == '}').unwrap()
    };
    &rest[..end]
}

#[test]
fn direction_sweep_with_dimensions_matches_a_chronological_oracle() {
    let fixture = Fixture::new("oracle");
    let boundary_a = date("2024-01-17").unwrap();
    let boundary_b = date("2024-01-27").unwrap();
    let end = date("2024-02-10").unwrap();
    for (run, dimensions) in [
        ("volume", "volume"),
        ("delta", "delta"),
        ("both", "delta,volume"),
        ("size", "size"),
        ("pair", "delta,imbalance"),
    ] {
        let set = DimensionSet::parse(dimensions).unwrap();
        let manifest = success(&fixture.args("nine.csv", run, &[("--dimensions", dimensions)]));
        assert!(manifest.contains("\"status\":\"COMPLETE\""));
        assert_eq!(field(&manifest, "dimensions"), set.json());
        let mut purged_anywhere = 0;
        for bars in [2usize, 3] {
            for mode in [GeometryMode::Oriented, GeometryMode::Unoriented] {
                let task = fixture.root.join(format!("{run}/tasks/n{bars:02}-{mode}"));
                let mut ids = HashMap::<String, usize>::new();
                let mut patterns = Vec::<(String, [u64; 18])>::new();
                let mut events = EVENT_HEADER.to_owned();
                let (mut gap_purged, mut boundary_purged, mut dimension_purged) = (0, 0, 0);
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
                    // Current candle first, as the sweep reads its windows.
                    let current_first: Vec<_> =
                        fixture.rows[t + 1 - bars..=t].iter().rev().collect();
                    let rows: Vec<_> = current_first.iter().map(|row| row.1).collect();
                    let counters: Vec<_> = current_first.iter().map(|row| row.2).collect();
                    let pattern =
                        match GeometryPattern::from_ohlc_counters(&rows, &counters, mode, set)
                            .unwrap()
                        {
                            Some(pattern) => pattern.to_string(),
                            None => {
                                dimension_purged += 1;
                                continue;
                            }
                        };
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
                }
                assert_eq!(text(task.join("events.tsv")), events, "{run} {bars} {mode}");
                let mut catalogue = PATTERN_HEADER.to_owned();
                for (id, (pattern, counts)) in patterns.iter().enumerate() {
                    // Every catalogue line is a canonical code with exactly
                    // the declared dimensions on.
                    let parsed: GeometryPattern = pattern.parse().unwrap();
                    assert_eq!(parsed.dimension_set(), set);
                    write!(catalogue, "{id}\t{pattern}").unwrap();
                    for count in counts {
                        write!(catalogue, "\t{count}").unwrap();
                    }
                    catalogue.push('\n');
                }
                assert_eq!(text(task.join("patterns.tsv")), catalogue);
                let summary = text(task.join("summary.json"));
                let universe = count_domain_decimal_with_dimensions(bars, mode, set).unwrap();
                assert_eq!(
                    field(&summary, "universe_patterns"),
                    format!("\"{universe}\"")
                );
                let universe: u128 = universe.parse().unwrap();
                assert_eq!(
                    field(&summary, "unobserved_patterns"),
                    format!("\"{}\"", universe - patterns.len() as u128)
                );
                assert_eq!(field(&summary, "dimensions"), set.json());
                for (key, expected) in [
                    ("gap_purged", gap_purged),
                    ("boundary_purged", boundary_purged),
                    ("dimension_purged", dimension_purged),
                    ("observed_patterns", patterns.len()),
                    ("events", events.lines().count() - 1),
                ] {
                    assert_eq!(field(&summary, key), expected.to_string(), "{key}");
                }
                assert_eq!(
                    field(&summary, "count_includes_patterns_that_cannot_occur"),
                    (run == "pair").to_string()
                );
                purged_anywhere += dimension_purged;
            }
        }
        // Only a dimension that can be absent purges a window.
        assert_eq!(purged_anywhere > 0, run == "size" || run == "pair", "{run}");
    }
    // The same run resumes, and a run with other dimensions is another run.
    success(&fixture.args(
        "nine.csv",
        "both",
        &[("--dimensions", "volume,delta"), ("--resume", "true")],
    ));
    assert!(failure(&fixture.args(
        "nine.csv",
        "both",
        &[("--dimensions", "volume"), ("--resume", "true")]
    ))
    .contains("mismatch"));
}

#[test]
fn no_dimension_on_is_the_same_sweep_and_a_dimension_needs_counters() {
    let fixture = Fixture::new("parity");
    success(&fixture.args("six.csv", "six", &[]));
    success(&fixture.args("nine.csv", "nine", &[]));
    success(&fixture.args("nine.csv", "empty", &[("--dimensions", "")]));
    for bars in [2, 3] {
        for mode in ["oriented", "unoriented"] {
            let task = format!("tasks/n{bars:02}-{mode}");
            for file in ["events.tsv", "patterns.tsv"] {
                let expected = fs::read(fixture.root.join("six").join(&task).join(file)).unwrap();
                for run in ["nine", "empty"] {
                    assert_eq!(
                        fs::read(fixture.root.join(run).join(&task).join(file)).unwrap(),
                        expected,
                        "{run} {task} {file}"
                    );
                }
            }
            let summary = text(fixture.root.join("nine").join(&task).join("summary.json"));
            assert!(!summary.contains("\"dimension") && !summary.contains("cannot_occur"));
        }
    }
    // The two no-dimension runs on one file share one identity.
    assert_eq!(
        text(fixture.root.join("nine/run.config.json")),
        text(fixture.root.join("empty/run.config.json"))
    );
    assert!(!text(fixture.root.join("nine/run.config.json")).contains("\"dimensions\""));
    // A dimension is refused, not weakened, on a recording without counters.
    assert!(
        failure(&fixture.args("six.csv", "refused", &[("--dimensions", "volume")]))
            .contains("need a recording with counters")
    );
    assert!(!fixture.root.join("refused").exists());
    for bad in ["flow", "volume,volume", "volume,"] {
        failure(&fixture.args("nine.csv", "bad", &[("--dimensions", bad)]));
    }
    // A recording whose counters cannot be right is refused whole.
    let nine = text(fixture.root.join("nine.csv"));
    for (from, to) in [
        (",1000,300,10\n", ",1000,1001,10\n"),
        (",1000,300,10\n", ",1000,300,10.5\n"),
        (",1000,300,10\n", ",-1000,300,10\n"),
        (",1000,300,10\n", ",inf,300,10\n"),
        (",1000,300,10\n", ",1000,300\n"),
    ] {
        assert!(nine.contains(from), "{from}");
        fs::write(fixture.root.join("broken.csv"), nine.replacen(from, to, 1)).unwrap();
        failure(&fixture.args("broken.csv", "broken", &[]));
    }
}
