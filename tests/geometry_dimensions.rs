//! Binds the Rust encoder, parser and key to every shared dimension vector
//! (`study/verify/dimension-vectors.json`), which the study engine and
//! Composer read to the same codes, and checks the count command's reports.
//! The vectors file is read by a small reader written for it: the core has no
//! JSON dependency.
use filang::geometry::{
    count_domain_decimal_with_dimensions, Counters, Dimension, DimensionSet,
    GeometryDimensionEncoder, GeometryDimensionKey, GeometryEncoder, GeometryKey, GeometryMode,
    GeometryPattern,
};
use std::{collections::BTreeMap, fs, process::Command};

#[derive(Debug, Clone, PartialEq)]
enum Json {
    Null,
    Bool(bool),
    // Kept as written, so a counter is parsed once, by the float parser.
    Number(String),
    Text(String),
    List(Vec<Json>),
    Object(BTreeMap<String, Json>),
}

struct Reader<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl Reader<'_> {
    fn space(&mut self) {
        while self.at < self.bytes.len() && self.bytes[self.at].is_ascii_whitespace() {
            self.at += 1;
        }
    }

    fn expect(&mut self, byte: u8) {
        self.space();
        assert_eq!(
            self.bytes.get(self.at),
            Some(&byte),
            "expected {:?} at byte {}",
            byte as char,
            self.at
        );
        self.at += 1;
    }

    fn peek(&mut self) -> u8 {
        self.space();
        self.bytes[self.at]
    }

    fn word(&mut self, word: &str, value: Json) -> Json {
        assert!(self.bytes[self.at..].starts_with(word.as_bytes()));
        self.at += word.len();
        value
    }

    fn text(&mut self) -> String {
        self.expect(b'"');
        let mut out = Vec::new();
        loop {
            let byte = self.bytes[self.at];
            self.at += 1;
            match byte {
                b'"' => break,
                b'\\' => {
                    let escaped = self.bytes[self.at];
                    self.at += 1;
                    out.push(match escaped {
                        b'"' | b'\\' | b'/' => escaped,
                        b'n' => b'\n',
                        b't' => b'\t',
                        other => panic!("unsupported escape \\{}", other as char),
                    });
                }
                other => out.push(other),
            }
        }
        String::from_utf8(out).unwrap()
    }

    fn value(&mut self) -> Json {
        match self.peek() {
            b'{' => {
                self.at += 1;
                let mut fields = BTreeMap::new();
                if self.peek() == b'}' {
                    self.at += 1;
                    return Json::Object(fields);
                }
                loop {
                    let key = self.text();
                    self.expect(b':');
                    assert!(fields.insert(key, self.value()).is_none(), "repeated key");
                    if self.peek() == b',' {
                        self.at += 1;
                    } else {
                        self.expect(b'}');
                        return Json::Object(fields);
                    }
                }
            }
            b'[' => {
                self.at += 1;
                let mut items = Vec::new();
                if self.peek() == b']' {
                    self.at += 1;
                    return Json::List(items);
                }
                loop {
                    items.push(self.value());
                    if self.peek() == b',' {
                        self.at += 1;
                    } else {
                        self.expect(b']');
                        return Json::List(items);
                    }
                }
            }
            b'"' => Json::Text(self.text()),
            b'n' => self.word("null", Json::Null),
            b't' => self.word("true", Json::Bool(true)),
            b'f' => self.word("false", Json::Bool(false)),
            _ => {
                let start = self.at;
                while self.at < self.bytes.len()
                    && matches!(
                        self.bytes[self.at],
                        b'0'..=b'9' | b'-' | b'+' | b'.' | b'e' | b'E'
                    )
                {
                    self.at += 1;
                }
                assert!(self.at > start, "unexpected byte at {start}");
                Json::Number(String::from_utf8(self.bytes[start..self.at].to_vec()).unwrap())
            }
        }
    }
}

impl Json {
    fn parse(text: &str) -> Self {
        let mut reader = Reader {
            bytes: text.as_bytes(),
            at: 0,
        };
        let value = reader.value();
        reader.space();
        assert_eq!(reader.at, reader.bytes.len(), "trailing JSON");
        value
    }

    fn get(&self, key: &str) -> &Json {
        match self {
            Json::Object(fields) => fields
                .get(key)
                .unwrap_or_else(|| panic!("missing key {key}")),
            other => panic!("expected an object, found {other:?}"),
        }
    }

    fn list(&self) -> &[Json] {
        match self {
            Json::List(items) => items,
            other => panic!("expected a list, found {other:?}"),
        }
    }

    fn text(&self) -> &str {
        match self {
            Json::Text(text) => text,
            other => panic!("expected text, found {other:?}"),
        }
    }

    fn number(&self) -> f64 {
        match self {
            Json::Number(text) => text.parse().unwrap(),
            other => panic!("expected a number, found {other:?}"),
        }
    }
}

struct Vector {
    name: String,
    rows: Vec<[f64; 4]>,
    counters: Vec<Counters>,
    as_recorded: String,
    chained: String,
    // One entry per dimension in canonical order; None is a part of null.
    parts: Vec<Option<String>>,
}

fn vectors() -> Vec<Vector> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/study/verify/dimension-vectors.json"
    );
    let document = Json::parse(&fs::read_to_string(path).unwrap());
    let names: Vec<_> = document
        .get("dimensions")
        .list()
        .iter()
        .map(Json::text)
        .collect();
    assert_eq!(
        names,
        Dimension::ALL.map(Dimension::name),
        "the shared vectors and the core disagree on the order of the dimensions"
    );
    document
        .get("vectors")
        .list()
        .iter()
        .map(|vector| {
            let bars: Vec<Vec<f64>> = vector
                .get("bars")
                .list()
                .iter()
                .map(|bar| bar.list().iter().map(Json::number).collect())
                .collect();
            assert!(bars.iter().all(|bar| bar.len() == 7));
            Vector {
                name: vector.get("name").text().to_owned(),
                rows: bars
                    .iter()
                    .map(|bar| [bar[0], bar[1], bar[2], bar[3]])
                    .collect(),
                counters: bars
                    .iter()
                    .map(|bar| Counters::new(bar[4], bar[5], bar[6]).unwrap())
                    .collect(),
                as_recorded: vector.get("as_recorded").text().to_owned(),
                chained: vector.get("chained").text().to_owned(),
                parts: Dimension::ALL
                    .iter()
                    .map(
                        |dimension| match vector.get("parts").get(dimension.name()) {
                            Json::Null => None,
                            part => Some(part.text().to_owned()),
                        },
                    )
                    .collect(),
            }
        })
        .collect()
}

/// The window read as a chain: the first bar as recorded, every later bar
/// opening at the close of the bar before it, its low and high widened to
/// include that open. Counters are the bar's own under both readings.
fn chain(rows: &[[f64; 4]]) -> Vec<[f64; 4]> {
    let mut out = rows.to_vec();
    for i in 1..rows.len() {
        let open = rows[i - 1][3];
        out[i] = [open, rows[i][1].max(open), rows[i][2].min(open), rows[i][3]];
    }
    out
}

/// The same price code with its directions dropped.
fn unoriented(code: &str) -> String {
    let rows: Vec<_> = code["g1:o:".len()..]
        .split(';')
        .map(|row| row.rsplit_once(',').unwrap().0)
        .collect();
    format!("g1:u:{}", rows.join(";"))
}

fn every_set() -> Vec<DimensionSet> {
    (0u8..32)
        .map(|mask| {
            Dimension::ALL
                .iter()
                .enumerate()
                .filter(|(i, _)| mask >> i & 1 == 1)
                .fold(DimensionSet::NONE, |set, (_, dimension)| {
                    set.with(*dimension)
                })
        })
        .collect()
}

#[test]
fn every_shared_vector_reads_to_its_code_for_every_set_of_dimensions() {
    let vectors = vectors();
    assert!(vectors.len() >= 11, "the shared vectors went missing");
    let sets = every_set();
    assert_eq!(sets.len(), 32);
    let (mut codes, mut invalid) = (0, 0);
    for vector in &vectors {
        let readings = [
            (vector.rows.clone(), vector.as_recorded.clone()),
            (chain(&vector.rows), vector.chained.clone()),
        ];
        for (rows, oriented_price) in &readings {
            for (mode, price) in [
                (GeometryMode::Oriented, oriented_price.clone()),
                (GeometryMode::Unoriented, unoriented(oriented_price)),
            ] {
                // With every dimension off the code is the price code, from
                // the unchanged encoder and its four-word key.
                let plain = GeometryPattern::from_ohlc(rows, mode).unwrap();
                assert_eq!(plain.to_string(), price, "{}", vector.name);
                let plain_key = GeometryEncoder::new(rows.len(), mode)
                    .unwrap()
                    .encode_key_ohlc(rows)
                    .unwrap();
                assert_eq!(plain_key, GeometryKey::from_pattern(&plain).unwrap());
                for &set in &sets {
                    let parts: Vec<_> = Dimension::ALL
                        .iter()
                        .zip(&vector.parts)
                        .filter(|(dimension, _)| set.contains(**dimension))
                        .map(|(_, part)| part.clone())
                        .collect();
                    let expected = parts
                        .iter()
                        .cloned()
                        .collect::<Option<Vec<_>>>()
                        .map(|parts| {
                            let mut code = price.clone();
                            for part in parts {
                                code.push('|');
                                code.push_str(&part);
                            }
                            code
                        });
                    let label = format!("{}: {mode} with {set}", vector.name);
                    let observed =
                        GeometryPattern::from_ohlc_counters(rows, &vector.counters, mode, set)
                            .unwrap();
                    assert_eq!(
                        observed.as_ref().map(ToString::to_string),
                        expected,
                        "{label}"
                    );
                    let mut encoder = GeometryDimensionEncoder::new(rows.len(), mode, set).unwrap();
                    let key = encoder.encode_key_ohlc(rows, &vector.counters).unwrap();
                    assert_eq!(key.map(|key| key.to_string()), expected, "{label}");
                    let (expected, observed, key) = match (expected, observed, key) {
                        (Some(expected), Some(observed), Some(key)) => (expected, observed, key),
                        (None, None, None) => {
                            invalid += 1;
                            continue;
                        }
                        other => panic!("{label}: {other:?}"),
                    };
                    codes += 1;
                    // The parser reads the shared code to the same pattern,
                    // and the pattern fits its own window.
                    let parsed: GeometryPattern = expected.parse().unwrap();
                    assert_eq!(parsed, observed, "{label}");
                    assert_eq!(parsed.dimension_set(), set);
                    assert_eq!(parsed.price(), plain);
                    assert_eq!(
                        parsed
                            .matches_ohlc_counters(rows, &vector.counters)
                            .unwrap(),
                        Some(true)
                    );
                    // The key is the unchanged price key and one word for
                    // each dimension that is on, and reads back to the code.
                    assert_eq!(key.price(), plain_key, "{label}");
                    assert_eq!(key.dimension_words().len(), set.len());
                    assert_eq!(key, GeometryDimensionKey::from_pattern(&parsed).unwrap());
                    assert_eq!(key.to_pattern(), parsed);
                    assert_eq!(key.dimensions(), set);
                    assert_eq!(
                        GeometryDimensionKey::from_words(
                            key.price().words(),
                            key.dimension_words()
                        )
                        .unwrap(),
                        key
                    );
                }
            }
        }
    }
    // Eleven windows, two readings, two modes and 32 sets, of which the bar
    // without trades has no code for any set holding size or imbalance.
    assert_eq!(codes + invalid, vectors.len() * 2 * 2 * 32);
    assert!(invalid >= 2 * 2 * 24);
    assert!(codes > invalid);
}

#[test]
fn a_code_that_differs_on_one_axis_is_false_and_a_missing_value_is_invalid() {
    let vectors = vectors();
    let find = |prefix: &str| {
        vectors
            .iter()
            .find(|vector| vector.name.starts_with(prefix))
            .unwrap_or_else(|| panic!("no vector named {prefix}"))
    };
    let two = find("two bars: volume rises");
    let fits = |vector: &Vector, tail: &str| {
        let pattern: GeometryPattern = format!("{}{tail}", vector.as_recorded).parse().unwrap();
        pattern
            .matches_ohlc_counters(&vector.rows, &vector.counters)
            .unwrap()
    };
    assert_eq!(fits(two, "|volume:1,0"), Some(false));
    assert_eq!(fits(two, "|volume:0,0"), Some(false));
    assert_eq!(fits(two, "|delta:1,2/0"), Some(false));
    assert_eq!(fits(two, "|volume:0,1|delta:0,2/1"), Some(true));
    let idle = find("a bar without trades");
    assert_eq!(fits(idle, "|size:0,0"), None);
    assert_eq!(fits(idle, "|volume:1,0|imbalance:1,0/0"), None);
    assert_eq!(fits(idle, "|volume:1,0|delta:1,0/0"), Some(true));
    // The formula is evaluated as written: equal on paper, unequal as floats.
    let paper = find("equal imbalance on paper");
    assert_eq!(fits(paper, "|imbalance:1,2/0"), Some(true));
    assert_eq!(fits(paper, "|imbalance:1,1/0"), Some(false));
}

fn count(arguments: &[&str]) -> String {
    let output = Command::new(env!("CARGO_BIN_EXE_filang"))
        .arg("geometry-count")
        .args(arguments)
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
    String::from_utf8(output.stdout).unwrap().trim().to_owned()
}

#[test]
fn count_cli_reports_declared_domains_and_is_unchanged_with_no_dimension_on() {
    let report = |dimensions: &str, patterns: &str, impossible: bool| {
        let names: Vec<_> = dimensions.split(',').map(|n| format!("\"{n}\"")).collect();
        format!(
            "{{\"version\":1,\"bars\":2,\"mode\":\"oriented\",\"dimensions\":[{}],\"complete_patterns\":\"{patterns}\",\"count_includes_patterns_that_cannot_occur\":{impossible}",
            names.join(",")
        )
    };
    let plain = "{\"version\":1,\"bars\":2,\"mode\":\"oriented\",\"complete_patterns\":\"7452\"}";
    assert_eq!(count(&["--bars", "2", "--mode", "oriented"]), plain);
    assert_eq!(count(&["--bars", "2", "--dimensions", ""]), plain);
    for (dimensions, patterns) in [
        ("volume", "22356"),
        ("delta", "96876"),
        ("volume,delta", "290628"),
    ] {
        assert_eq!(
            count(&["--bars", "2", "--dimensions", dimensions]),
            report(dimensions, patterns, false) + "}"
        );
    }
    // Any order is accepted and reported in the order the parts are written.
    assert_eq!(
        count(&["--bars", "2", "--dimensions", "delta,volume"]),
        report("volume,delta", "290628", false) + "}"
    );
    // The two dependent cores: the declared count, and the statement that it
    // includes patterns that cannot occur.
    assert_eq!(
        count(&["--bars", "2", "--dimensions", "delta,imbalance"]),
        report("delta,imbalance", "1259388", true) + ",\"patterns_that_can_occur\":\"186300\"}"
    );
    assert_eq!(
        count(&["--bars", "2", "--dimensions", "volume,trades,size"]),
        report("volume,trades,size", "201204", true) + "}"
    );
    assert_eq!(
        count(&[
            "--bars",
            "2",
            "--dimensions",
            "volume,trades,delta,size,imbalance"
        ]),
        report("volume,trades,delta,size,imbalance", "34003476", true) + "}"
    );
    // The factor for each dimension and window length, through ten candles.
    let bell: [u128; 12] = [
        1,
        1,
        3,
        13,
        75,
        541,
        4_683,
        47_293,
        545_835,
        7_087_261,
        102_247_563,
        1_622_632_573,
    ];
    for bars in 1..=9usize {
        let price: u128 = count_domain_decimal_with_dimensions(
            bars,
            GeometryMode::Unoriented,
            DimensionSet::NONE,
        )
        .unwrap()
        .parse()
        .unwrap();
        for dimension in Dimension::ALL {
            let factor = bell[bars + dimension.has_reference() as usize];
            let text = count(&[
                "--bars",
                &bars.to_string(),
                "--mode",
                "unoriented",
                "--dimensions",
                dimension.name(),
            ]);
            match price.checked_mul(factor) {
                Some(product) => assert!(
                    text.contains(&format!("\"complete_patterns\":\"{product}\"")),
                    "{text}"
                ),
                None => assert!(text.contains("\"complete_patterns\":\"")),
            }
        }
    }
    for bad in ["flow", "volume,volume", "volume,", "Volume"] {
        let output = Command::new(env!("CARGO_BIN_EXE_filang"))
            .args(["geometry-count", "--bars", "2", "--dimensions", bad])
            .output()
            .unwrap();
        assert!(!output.status.success(), "accepted {bad}");
    }
}
