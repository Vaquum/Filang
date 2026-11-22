//! End-to-end checks of the bank-pair sweep with dimensions declared: the
//! nine-column recording, declared counts, window validity, the catalogue and
//! its symbolic complement, and frozen replay. With no dimension declared the
//! nine-column recording must reproduce the six-column run.
use filang::{
    data,
    geometry::{
        count_domain_with_dimensions, Counters, DimensionSet, GeometryMode, GeometryPattern,
        COUNTER_COLUMNS,
    },
};
use std::{
    collections::HashSet,
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

const START: &str = "2024-01-09";
const END: &str = "2024-01-29";
const INTERVAL: &str = "86400";
const BARS: usize = 28;
// Bars without trades: they have volume and delta, but no size or imbalance.
const IDLE: [usize; 2] = [6, 17];

struct Fixture {
    root: PathBuf,
    rows: Vec<[f64; 4]>,
    counters: Vec<Counters>,
}

impl Fixture {
    fn new(name: &str) -> Self {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "filang-geometry-dimensions-{name}-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let start = data::date("2024-01-01").unwrap();
        let mut six = String::from("timestamp,open,high,low,close,volume\n");
        let mut nine = format!("{COUNTER_COLUMNS}\n");
        let (mut rows, mut counters) = (Vec::new(), Vec::new());
        for i in 0..BARS {
            let base = 1000.0 + ((i * 7) % 11) as f64 * 0.2 + i as f64 * 0.04;
            let row = match i % 12 {
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
            let idle = IDLE.contains(&i);
            let volume = if idle { 0 } else { 2000 + (i * 5 % 3) * 1000 };
            let taker_buy = volume * [3, 5, 7, 5][i % 4] / 10;
            let trades = if idle { 0 } else { 20 + (i * 3 % 4) * 10 };
            let seconds = start + i as i64 * 86400;
            let prices = format!(
                "{:.12},{:.12},{:.12},{:.12},100",
                row[0], row[1], row[2], row[3]
            );
            writeln!(six, "{seconds},{prices}").unwrap();
            writeln!(
                nine,
                "{},{prices},{volume},{taker_buy},{trades}",
                seconds * 1000
            )
            .unwrap();
            // The engine reads the prices from this text; so does the oracle.
            let parsed: Vec<f64> = prices.split(',').map(|x| x.parse().unwrap()).collect();
            rows.push([parsed[0], parsed[1], parsed[2], parsed[3]]);
            counters.push(Counters::new(volume as f64, taker_buy as f64, trades as f64).unwrap());
        }
        fs::write(root.join("six.csv"), six).unwrap();
        fs::write(root.join("nine.csv"), nine).unwrap();
        Self {
            root,
            rows,
            counters,
        }
    }

    fn path(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }

    fn example(&self, name: &str, data: &str, dimensions: Option<&str>) -> PathBuf {
        let config = self.path(&format!("{name}.cfg"));
        let data = self.path(data);
        let mut options = vec![
            ("--out", text(&config)),
            ("--profile", "smoke"),
            ("--data", text(&data)),
            ("--start", START),
            ("--end", END),
            ("--interval-seconds", INTERVAL),
        ];
        if let Some(dimensions) = dimensions {
            options.push(("--dimensions", dimensions));
        }
        success(&arguments("geometry-example", &options));
        let old = fs::read_to_string(&config).unwrap();
        fs::write(
            &config,
            old.replace("fee_bps=10", "fee_bps=1")
                .replace("slip_bps=10", "slip_bps=1"),
        )
        .unwrap();
        config
    }

    fn sweep(&self, command: &str, config: &Path, out: &str) -> Vec<String> {
        let out = self.path(out);
        arguments(
            command,
            &[
                ("--config", text(config)),
                ("--out", text(&out)),
                ("--workers", "2"),
                ("--backend", "scalar"),
                ("--certificates", "true"),
                ("--capture", "true"),
            ],
        )
    }

    fn evaluate(&self, data: &str, run: &str, out: &str) -> Vec<String> {
        let (data, selection, out) = (
            self.path(data),
            self.path(run).join("best-geometry.tsv"),
            self.path(out),
        );
        arguments(
            "geometry-evaluate",
            &[
                ("--data", text(&data)),
                ("--selection", text(&selection)),
                ("--start", START),
                ("--end", END),
                ("--out", text(&out)),
                ("--interval-seconds", INTERVAL),
                ("--fee-bps", "1"),
                ("--slip-bps", "1"),
                ("--backend", "scalar"),
            ],
        )
    }

    /// The observed patterns of one bank in order of first occurrence, and
    /// how many windows of the causal prefix are invalid for the dimensions.
    fn oracle(&self, lags: &[usize], dimensions: DimensionSet) -> (Vec<String>, usize) {
        let cut = BARS - 2;
        let (mut seen, mut order, mut invalid) = (HashSet::new(), Vec::new(), 0);
        for t in lags[lags.len() - 1]..cut {
            let rows: Vec<_> = lags.iter().map(|lag| self.rows[t - lag]).collect();
            let counters: Vec<_> = lags.iter().map(|lag| self.counters[t - lag]).collect();
            match GeometryPattern::from_ohlc_counters(
                &rows,
                &counters,
                GeometryMode::Oriented,
                dimensions,
            )
            .unwrap()
            {
                Some(pattern) => {
                    let code = pattern.to_string();
                    if seen.insert(code.clone()) {
                        order.push(code);
                    }
                }
                None => invalid += 1,
            }
        }
        (order, invalid)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn text(path: &Path) -> &str {
    path.to_str().unwrap()
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
        .unwrap()
}

fn success(arguments: &[String]) -> String {
    let output = invoke(arguments);
    assert!(
        output.status.success(),
        "command {arguments:?}\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

fn failure(arguments: &[String]) -> String {
    let output = invoke(arguments);
    assert!(
        !output.status.success(),
        "unexpected success: {arguments:?}"
    );
    String::from_utf8(output.stderr).unwrap()
}

/// The text of a scalar, string or flat array field of a native JSON report.
fn field<'a>(json: &'a str, key: &str) -> &'a str {
    let marker = format!("\"{key}\":");
    let at = json
        .find(&marker)
        .unwrap_or_else(|| panic!("missing {key} in {json}"));
    let rest = &json[at + marker.len()..];
    let end = if rest.starts_with('[') {
        rest.find(']').unwrap() + 1
    } else if let Some(quoted) = rest.strip_prefix('"') {
        quoted.find('"').unwrap() + 2
    } else {
        rest.find(|c| c == ',' || c == '}').unwrap()
    };
    &rest[..end]
}

/// A sealed catalogue's rows, without its header or its checksum footer.
fn catalogue(path: &Path) -> Vec<Vec<String>> {
    let bytes = fs::read(path).unwrap();
    let body = std::str::from_utf8(&bytes[..bytes.len() - 64]).unwrap();
    let mut lines = body.lines();
    assert_eq!(lines.next(), Some("id\tkind\tmultiplicity\tpattern"));
    lines
        .map(|line| line.split('\t').map(str::to_owned).collect())
        .collect()
}

fn set(text: &str) -> DimensionSet {
    DimensionSet::parse(text).unwrap()
}

#[test]
fn a_sweep_with_dimensions_declares_refines_and_replays() {
    let fixture = Fixture::new("sweep");
    let dimensions = set("volume,delta");
    let config = fixture.example("on", "nine.csv", Some("delta,volume"));
    // The declaration is written once, in the order the parts are written.
    let raw = fs::read_to_string(&config).unwrap();
    assert!(raw.contains("\nmode=oriented\ndimensions=volume,delta\nwindows=0,1;0,2\n"));
    let per_bank = count_domain_with_dimensions(2, GeometryMode::Oriented, dimensions).unwrap();
    assert_eq!(per_bank, 290_628);
    let requested = 3 * 2 * per_bank * per_bank;
    let plan = success(&arguments(
        "geometry-inspect",
        &[("--config", text(&config))],
    ));
    assert_eq!(field(&plan, "dimensions"), "[\"volume\",\"delta\"]");
    assert_eq!(
        field(&plan, "count_includes_patterns_that_cannot_occur"),
        "false"
    );
    assert_eq!(field(&plan, "complete_patterns"), "\"290628\"");
    assert_eq!(
        field(&plan, "requested_strategy_addresses"),
        format!("\"{requested}\"")
    );
    success(&fixture.sweep("geometry-sweep", &config, "on"));
    let summary = fs::read_to_string(fixture.path("on/summary.json")).unwrap();
    assert_eq!(field(&summary, "status"), "\"PASS\"");
    assert_eq!(field(&summary, "coverage_complete"), "true");
    for key in [
        "requested_strategy_addresses",
        "resolved_strategy_addresses",
    ] {
        assert_eq!(field(&summary, key), format!("\"{requested}\""));
    }
    assert_eq!(field(&summary, "dimensions"), "[\"volume\",\"delta\"]");
    assert_eq!(
        field(&summary, "windows_without_a_dimension_value"),
        "\"0\""
    );
    assert_eq!(
        field(&summary, "count_includes_patterns_that_cannot_occur"),
        "false"
    );
    // The same recording with no dimension declared is the control.
    let control = fixture.example("off", "nine.csv", None);
    assert!(!fs::read_to_string(&control)
        .unwrap()
        .contains("\ndimensions="));
    success(&fixture.sweep("geometry-sweep", &control, "off"));
    for (bank, lags) in [[0usize, 1], [0, 2]].iter().enumerate() {
        let rows = catalogue(&fixture.path(&format!("on/banks/patterns-{bank:02}.tsv")));
        let (expected, invalid) = fixture.oracle(lags, dimensions);
        assert_eq!(invalid, 0);
        let (observed, complement) = rows.split_at(rows.len() - 1);
        assert_eq!(
            observed
                .iter()
                .map(|row| row[3].clone())
                .collect::<Vec<_>>(),
            expected
        );
        for (id, row) in observed.iter().enumerate() {
            assert_eq!(row[..3], [id.to_string(), "observed".into(), "1".into()]);
            let pattern: GeometryPattern = row[3].parse().unwrap();
            assert_eq!(pattern.dimension_set(), dimensions);
        }
        // The symbolic complement: every other declared pattern, counted
        // exactly, with a representative that was not observed.
        assert_eq!(complement[0][1], "unobserved");
        assert_eq!(
            complement[0][2].parse::<u128>().unwrap(),
            per_bank - observed.len() as u128
        );
        let representative: GeometryPattern = complement[0][3].parse().unwrap();
        assert_eq!(representative.dimension_set(), dimensions);
        assert_eq!(representative.len(), 2);
        assert!(!expected.contains(&complement[0][3]));
        // Each pattern with dimensions on refines a pattern of the control,
        // and together they cover exactly the control's observed patterns.
        let control_rows = catalogue(&fixture.path(&format!("off/banks/patterns-{bank:02}.tsv")));
        let control_observed: Vec<_> = control_rows[..control_rows.len() - 1]
            .iter()
            .map(|row| row[3].clone())
            .collect();
        assert_eq!(control_observed, fixture.oracle(lags, DimensionSet::NONE).0);
        let mut prices = Vec::new();
        for code in &expected {
            let price = code.parse::<GeometryPattern>().unwrap().price().to_string();
            if !prices.contains(&price) {
                prices.push(price);
            }
        }
        assert_eq!(prices, control_observed);
        assert!(expected.len() >= control_observed.len());
        let statistics =
            fs::read_to_string(fixture.path(&format!("on/banks/preparation-{bank:02}.json")))
                .unwrap();
        assert_eq!(field(&statistics, "dimensions"), "[\"volume\",\"delta\"]");
        assert_eq!(field(&statistics, "windows_without_a_dimension_value"), "0");
        assert_eq!(field(&statistics, "total_patterns"), "\"290628\"");
        assert_eq!(
            field(&statistics, "observed_patterns"),
            expected.len().to_string()
        );
        let plain =
            fs::read_to_string(fixture.path(&format!("off/banks/preparation-{bank:02}.json")))
                .unwrap();
        assert!(!plain.contains("\"dimension") && !plain.contains("cannot_occur"));
    }
    assert!(!fs::read_to_string(fixture.path("off/summary.json"))
        .unwrap()
        .contains("\"dimension"));
    // The frozen winner carries its dimension parts and replays on the
    // recording, and is refused on a recording without counters.
    let selection = fs::read_to_string(fixture.path("on/best-geometry.tsv")).unwrap();
    for line in selection.lines().skip(1) {
        let pattern: GeometryPattern = line.split('\t').nth(3).unwrap().parse().unwrap();
        assert_eq!(pattern.dimension_set(), dimensions);
    }
    let replay = success(&fixture.evaluate("nine.csv", "on", "replay"));
    assert_eq!(field(&replay, "status"), "\"PASS\"");
    let best = fs::read_to_string(fixture.path("on/best.json")).unwrap();
    let numbers = |json: &str| -> Vec<Option<f64>> {
        let array = field(json, "metrics");
        array[1..array.len() - 1]
            .split(',')
            .map(|value| value.trim().parse().ok())
            .collect()
    };
    let (expected, actual) = (numbers(&best), numbers(&replay));
    assert_eq!(expected.len(), 10);
    for (a, b) in expected.iter().zip(&actual) {
        match (a, b) {
            (Some(a), Some(b)) => assert!((a - b).abs() <= 1e-10, "{a} versus {b}"),
            (None, None) => {}
            other => panic!("metric null status differs: {other:?}"),
        }
    }
    assert!(failure(&fixture.evaluate("six.csv", "on", "refused")).contains("carries no counters"));
    // A declared dimension is refused on a recording without counters.
    let six = fixture.example("six-on", "six.csv", Some("volume"));
    assert!(failure(&fixture.sweep("geometry-sweep", &six, "six-on"))
        .contains("need a recording with counters"));
    assert!(!fixture.path("six-on/summary.json").exists());
}

#[test]
fn absent_values_invalidate_windows_and_dependent_sets_are_reported() {
    let fixture = Fixture::new("validity");
    // size has no value on a bar without trades.
    let config = fixture.example("size", "nine.csv", Some("size"));
    success(&fixture.sweep("geometry-sweep", &config, "size"));
    let mut total_invalid = 0;
    for (bank, lags) in [[0usize, 1], [0, 2]].iter().enumerate() {
        let (expected, invalid) = fixture.oracle(lags, set("size"));
        // Two bars without trades, each in two windows of this bank.
        assert_eq!(invalid, 4);
        total_invalid += invalid;
        let windows = BARS - 2 - lags[1];
        let statistics =
            fs::read_to_string(fixture.path(&format!("size/banks/preparation-{bank:02}.json")))
                .unwrap();
        assert_eq!(field(&statistics, "windows_without_a_dimension_value"), "4");
        assert_eq!(
            field(&statistics, "windows_encoded"),
            (windows - invalid).to_string()
        );
        let rows = catalogue(&fixture.path(&format!("size/banks/patterns-{bank:02}.tsv")));
        assert_eq!(
            rows[..rows.len() - 1]
                .iter()
                .map(|row| row[3].clone())
                .collect::<Vec<_>>(),
            expected
        );
        // The invalid windows are invalid for every pattern of the bank:
        // read the bank's validity planes, which every state shares when
        // the only qualifier is plain.
        let bank_bytes = fs::read(fixture.path(&format!("size/banks/bank-{bank:02}.bin"))).unwrap();
        let body = &bank_bytes[..bank_bytes.len() - 64];
        let word = |at: usize| u64::from_le_bytes(body[at..at + 8].try_into().unwrap());
        let (scored, states) = (word(72) as usize, word(80) as usize);
        let scored_start = 8; // 2024-01-09 is the ninth bar
        assert_eq!(scored, BARS - scored_start - 2);
        assert_eq!(scored, 18);
        let mut expected_valid = 0u64;
        for t in scored_start..BARS - 2 {
            let reads_idle = lags.iter().any(|lag| IDLE.contains(&(t - lag)));
            if !reads_idle {
                expected_valid |= 1 << (t - scored_start);
            }
        }
        let width = 16 + 24 + 8 + 8;
        assert_eq!(body.len(), 88 + states * width);
        let mut union = 0u64;
        for state in 0..states {
            let at = 88 + state * width;
            let (truth, valid) = (word(at + 40), word(at + 48));
            assert_eq!(valid, expected_valid, "bank {bank} state {state}");
            assert_eq!(truth & !valid, 0);
            assert_eq!(union & truth, 0, "a window has two patterns");
            union |= truth;
        }
        // Every valid window has exactly one pattern; no invalid one has any.
        assert_eq!(union, expected_valid);
    }
    let summary = fs::read_to_string(fixture.path("size/summary.json")).unwrap();
    assert_eq!(field(&summary, "status"), "\"PASS\"");
    assert_eq!(field(&summary, "coverage_complete"), "true");
    assert_eq!(
        field(&summary, "windows_without_a_dimension_value"),
        format!("\"{total_invalid}\"")
    );
    // The winner replays, with the same windows invalid.
    let replay = success(&fixture.evaluate("nine.csv", "size", "size-replay"));
    assert_eq!(field(&replay, "status"), "\"PASS\"");
    assert!(
        field(&replay, "valid_decisions").parse::<usize>().unwrap() < 18,
        "{replay}"
    );
    // A domain that declares a dependent core says that its count includes
    // patterns that cannot occur; one that does not, does not.
    for (name, dimensions, factor, impossible) in [
        ("pair", "delta,imbalance", 169u128, true),
        ("triple", "size,trades,volume", 27, true),
        ("free", "volume,trades,delta", 117, false),
    ] {
        let config = fixture.example(name, "nine.csv", Some(dimensions));
        let plan = success(&arguments(
            "geometry-inspect",
            &[("--config", text(&config))],
        ));
        assert_eq!(
            field(&plan, "count_includes_patterns_that_cannot_occur"),
            impossible.to_string()
        );
        assert_eq!(
            field(&plan, "complete_patterns"),
            format!("\"{}\"", 7452 * factor)
        );
        success(&fixture.sweep("geometry-prepare", &config, name));
        let statistics =
            fs::read_to_string(fixture.path(&format!("{name}/banks/preparation-00.json"))).unwrap();
        assert_eq!(
            field(&statistics, "count_includes_patterns_that_cannot_occur"),
            impossible.to_string()
        );
        assert_eq!(
            field(&statistics, "total_patterns"),
            format!("\"{}\"", 7452 * factor)
        );
        let summary = fs::read_to_string(fixture.path(&format!("{name}/summary.json"))).unwrap();
        assert_eq!(
            field(&summary, "count_includes_patterns_that_cannot_occur"),
            impossible.to_string()
        );
    }
    // Malformed declarations and windows too wide to count are refused.
    let good = fs::read_to_string(fixture.path("pair.cfg")).unwrap();
    for (from, to) in [
        ("dimensions=delta,imbalance", "dimensions=flow"),
        ("dimensions=delta,imbalance", "dimensions=delta,delta"),
        ("dimensions=delta,imbalance", "dimensions=delta,"),
        (
            "dimensions=delta,imbalance",
            "dimensions=delta\ndimensions=volume",
        ),
        ("windows=0,1;0,2", "windows=0,1,2,3,4,5,6,7,8;0,2"),
    ] {
        assert!(good.contains(from));
        let bad = fixture.path("bad.cfg");
        fs::write(&bad, good.replace(from, to)).unwrap();
        failure(&arguments("geometry-inspect", &[("--config", text(&bad))]));
    }
}

#[test]
fn a_nine_column_recording_with_no_dimension_on_reproduces_the_six_column_run() {
    let fixture = Fixture::new("parity");
    let six = fixture.example("six", "six.csv", None);
    let nine = fixture.example("nine", "nine.csv", None);
    success(&fixture.sweep("geometry-sweep", &six, "six"));
    success(&fixture.sweep("geometry-sweep", &nine, "nine"));
    // An empty declaration is no declaration.
    let empty = fixture.path("empty.cfg");
    fs::write(
        &empty,
        fs::read_to_string(&nine)
            .unwrap()
            .replace("\nwindows=", "\ndimensions=\nwindows="),
    )
    .unwrap();
    success(&fixture.sweep("geometry-sweep", &empty, "empty"));
    let plan = |config: &Path| {
        success(&arguments(
            "geometry-inspect",
            &[("--config", text(config))],
        ))
    };
    assert_eq!(plan(&six), plan(&nine));
    assert_eq!(plan(&six), plan(&empty));
    assert!(!plan(&empty).contains("\"dimension"));
    let expected = fs::read_to_string(fixture.path("six/summary.json")).unwrap();
    for run in ["nine", "empty"] {
        // Catalogues and memberships are the same bytes. The bank differs
        // only in the context it is bound to, which names the input file.
        for bank in 0..2 {
            for name in ["patterns", "members"] {
                let file = format!("banks/{name}-{bank:02}.tsv");
                assert_eq!(
                    fs::read(fixture.path("six").join(&file)).unwrap(),
                    fs::read(fixture.path(run).join(&file)).unwrap(),
                    "{run} {file}"
                );
            }
            let file = format!("banks/bank-{bank:02}.bin");
            let (a, b) = (
                fs::read(fixture.path("six").join(&file)).unwrap(),
                fs::read(fixture.path(run).join(&file)).unwrap(),
            );
            assert_eq!(a.len(), b.len());
            assert_eq!(a[..8], b[..8]);
            assert_eq!(a[72..a.len() - 64], b[72..b.len() - 64], "{run} {file}");
        }
        let summary = fs::read_to_string(fixture.path(run).join("summary.json")).unwrap();
        for key in [
            "requested_strategy_addresses",
            "resolved_strategy_addresses",
            "metric_regions_evaluated",
            "total_raw_pattern_universe",
            "observed_encoded_rows",
            "observed_pattern_instances",
            "metrics",
        ] {
            assert_eq!(field(&summary, key), field(&expected, key), "{run} {key}");
        }
        assert!(!summary.contains("\"dimension"));
        assert_eq!(
            fs::read(fixture.path("six/best-geometry.tsv")).unwrap(),
            fs::read(fixture.path(run).join("best-geometry.tsv")).unwrap()
        );
    }
}
