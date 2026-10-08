//! The real feature-only command is checked against an independent endpoint
//! ordering oracle, including original row indices, gaps, and future exclusion.
use filang::{
    data::date,
    dense_io,
    geometry::GeometryKey,
    hash::{file_sha256, sha256},
};
use std::{
    fmt::Write as _,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    time::{SystemTime, UNIX_EPOCH},
};

const DAY: i64 = 86400;
struct Fixture {
    root: PathBuf,
    rows: Vec<(i64, [f64; 4])>,
}
impl Fixture {
    fn new(name: &str) -> Self {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "filang-geometry-keys-{name}-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        let mut rows = Vec::new();
        for day in 0..44 {
            if day == 12 || day == 30 {
                continue;
            }
            let base = 100.0 + ((day * 7) % 11) as f64;
            let row = match day % 6 {
                0 => [base, base, base, base],
                1 => [base, base + 2.0, base, base + 2.0],
                2 => [base + 2.0, base + 2.0, base, base],
                3 => [base, base + 4.0, base - 1.0, base + 1.0],
                4 => [base + 1.0, base + 4.0, base - 1.0, base],
                _ => [base, base + 2.0, base - 2.0, base],
            };
            rows.push((date("2024-01-01").unwrap() + day * DAY, row));
        }
        let fixture = Self { root, rows };
        fixture.write_csv();
        fixture
    }

    fn write_csv(&self) {
        let mut csv = "timestamp,open,high,low,close,volume\n".to_owned();
        for (timestamp, row) in &self.rows {
            writeln!(
                csv,
                "{timestamp},{},{},{},{},1",
                row[0], row[1], row[2], row[3]
            )
            .unwrap();
        }
        fs::write(self.root.join("data.csv"), csv).unwrap();
    }

    fn args(&self, out: &str, extra: &[(&str, &str)]) -> Vec<String> {
        let mut flags = vec![
            (
                "--data",
                self.root.join("data.csv").to_str().unwrap().to_owned(),
            ),
            ("--out", self.root.join(out).to_str().unwrap().to_owned()),
            ("--interval-seconds", DAY.to_string()),
            ("--history-start", "2024-01-03".into()),
            ("--end", "2024-02-14".into()),
            ("--bars", "10".into()),
        ];
        for &(key, value) in extra {
            if let Some(flag) = flags.iter_mut().find(|v| v.0 == key) {
                flag.1 = value.into();
            } else {
                flags.push((key, value.into()));
            }
        }
        let mut args = vec!["geometry-key-export".into()];
        for (key, value) in flags {
            args.extend([key.into(), value]);
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
fn success(args: &[String]) {
    let result = invoke(args);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}
fn failure(args: &[String]) {
    let result = invoke(args);
    assert!(!result.status.success(), "unexpected success: {args:?}");
}
fn u64_at(bytes: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(bytes[at..at + 8].try_into().unwrap())
}
fn records(out: &Path) -> Vec<(usize, [u64; 4])> {
    let bytes = dense_io::read(&out.join("keys.bin"), 1_000_000).unwrap();
    assert_eq!(&bytes[..8], b"FGKEYS01");
    assert_eq!(bytes.len(), 168 + u64_at(&bytes, 160) as usize * 40);
    bytes[168..]
        .chunks_exact(40)
        .map(|r| {
            (
                u64_at(r, 0) as usize,
                [u64_at(r, 8), u64_at(r, 16), u64_at(r, 24), u64_at(r, 32)],
            )
        })
        .collect()
}

/// Sorting the raw distinct endpoints directly is independent of compact key
/// packing, the reusable encoder, and the exporter's consecutive-run counter.
fn oracle(rows: &[(i64, [f64; 4])], t: usize, n: usize) -> String {
    let endpoints: Vec<[f64; 4]> = (0..n)
        .map(|lag| {
            let [o, h, l, c] = rows[t - lag].1;
            [l, o.min(c), o.max(c), h]
        })
        .collect();
    let mut levels: Vec<f64> = endpoints.iter().flatten().copied().collect();
    levels.sort_by(|a, b| a.partial_cmp(b).unwrap());
    levels.dedup();
    let mut result = "g1:o:".to_owned();
    for (lag, values) in endpoints.iter().enumerate() {
        if lag != 0 {
            result.push(';');
        }
        for value in values {
            write!(
                result,
                "{},",
                levels.iter().position(|v| v == value).unwrap()
            )
            .unwrap();
        }
        let row = rows[t - lag].1;
        result.push(if row[3] > row[0] {
            'u'
        } else if row[3] < row[0] {
            'd'
        } else {
            'z'
        });
    }
    result
}

#[test]
fn exact_keys_original_indices_gaps_and_last_causal_rows() {
    let fixture = Fixture::new("oracle");
    for n in [2, 3, 5, 10] {
        let folder = format!("n{n}");
        success(&fixture.args(&folder, &[("--bars", &n.to_string())]));
        let out = fixture.root.join(folder);
        let got = records(&out);
        let start = date("2024-01-03").unwrap();
        let expected: Vec<_> = (n - 1..fixture.rows.len())
            .filter(|&t| {
                fixture.rows[t + 1 - n].0 >= start
                    && (1..n)
                        .all(|lag| fixture.rows[t - lag + 1].0 - fixture.rows[t - lag].0 == DAY)
            })
            .collect();
        assert_eq!(got.iter().map(|r| r.0).collect::<Vec<_>>(), expected);
        assert_eq!(got.last().unwrap().0, fixture.rows.len() - 1);
        for (t, words) in got {
            let key = GeometryKey::from_words(words).unwrap();
            assert_eq!(key.len(), n);
            assert_eq!(key.to_string(), oracle(&fixture.rows, t, n));
        }
        let bytes = fs::read(out.join("keys.bin")).unwrap();
        assert_eq!(
            &bytes[8..72],
            sha256(&fs::read(out.join("context.json")).unwrap()).as_bytes()
        );
        assert_eq!(
            &bytes[72..136],
            file_sha256(fixture.root.join("data.csv"))
                .unwrap()
                .as_bytes()
        );
        assert_eq!(u64_at(&bytes, 136), fixture.rows.len() as u64);
        assert_eq!(u64_at(&bytes, 144), DAY as u64);
        assert_eq!(u64_at(&bytes, 152), n as u64);
    }
}

#[test]
fn future_prices_do_not_change_past_features() {
    let mut fixture = Fixture::new("causality");
    success(&fixture.args("before", &[]));
    let before = records(&fixture.root.join("before"));
    let changed = fixture.rows.len() - 2;
    for (_, values) in &mut fixture.rows[changed..] {
        *values = [3.0, 7.0, 1.0, 2.0];
    }
    fixture.write_csv();
    success(&fixture.args("after", &[]));
    let after = records(&fixture.root.join("after"));
    assert_eq!(
        before.iter().filter(|r| r.0 < changed).collect::<Vec<_>>(),
        after.iter().filter(|r| r.0 < changed).collect::<Vec<_>>()
    );
    assert_ne!(before.last(), after.last());
}

#[test]
fn completed_resume_is_immutable_and_checks_all_evidence() {
    let fixture = Fixture::new("resume");
    success(&fixture.args("run", &[]));
    let out = fixture.root.join("run");
    let names = [
        "keys.bin",
        "context.json",
        "timings.json",
        "manifest.json",
        "manifest.sha256",
    ];
    let original: Vec<_> = names
        .iter()
        .map(|name| fs::read(out.join(name)).unwrap())
        .collect();
    let resume = fixture.args("run", &[("--resume", "true")]);
    success(&resume);
    for (name, bytes) in names.iter().zip(&original) {
        assert_eq!(&fs::read(out.join(name)).unwrap(), bytes);
    }
    failure(&fixture.args("run", &[]));
    failure(&fixture.args("run", &[("--resume", "true"), ("--bars", "2")]));
    for (index, name) in names.iter().enumerate() {
        let mut damaged = original[index].clone();
        damaged[0] ^= 1;
        fs::write(out.join(name), damaged).unwrap();
        failure(&resume);
        fs::write(out.join(name), &original[index]).unwrap();
    }
    // No final marker means no bundle was committed. Restart only owned files.
    fs::remove_file(out.join("manifest.sha256")).unwrap();
    fs::write(out.join("keys.pending"), b"interrupted record").unwrap();
    success(&resume);
    assert_eq!(fs::read(out.join("keys.bin")).unwrap(), original[0]);
    success(&resume);
}

#[test]
fn rejects_invalid_bounds_unknown_flags_and_orphan_artifacts() {
    let fixture = Fixture::new("reject");
    for flags in [
        vec![("--interval-seconds", "0")],
        vec![("--bars", "11")],
        vec![("--max-rows", "9")],
        vec![("--end", "2024-02-15")],
        vec![("--validation-start", "2024-01-10")],
    ] {
        failure(&fixture.args("bad", &flags));
    }
    let orphan = fixture.root.join("orphan");
    fs::create_dir(&orphan).unwrap();
    fs::write(orphan.join("keys.bin"), b"do not overwrite").unwrap();
    failure(&fixture.args("orphan", &[("--resume", "true")]));
    assert_eq!(
        fs::read(orphan.join("keys.bin")).unwrap(),
        b"do not overwrite"
    );
}
