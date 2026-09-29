use filang::{
    backtest::{Costs, Metrics},
    data::Data,
    kernels::Backend,
    paged::{metric_values, BinarySink, Executor, PageSource, Scorer, Sink},
    program_run::{OpenPages, PeriodPages},
    walk_config::WalkConfig,
    Result,
};
fn fixture(n: usize) -> Data {
    Data {
        timestamps: (0..n).map(|i| i as i64 * 14400).collect(),
        columns: std::array::from_fn(|_| {
            (0..n)
                .map(|i| {
                    100.0
                        * (0.01 * (i as f64 / 4.0).sin()
                            + 0.1 * (i as f64 / 71.0).sin()
                            + 0.0001 * i as f64)
                            .exp()
                })
                .collect()
        }),
        interval: 14400,
        digest: "page-fixture-v1".into(),
    }
}
#[derive(Default)]
struct Capture {
    rows: Vec<(u64, usize, usize, [f64; 10])>,
}
impl Sink for Capture {
    fn emit(&mut self, a: u64, q: usize, s: usize, m: &Metrics, t: i64) -> Result<()> {
        self.rows.push((a, q, s, metric_values(m, t)));
        Ok(())
    }
}
fn compare(a: &Capture, b: &Capture) {
    assert_eq!(a.rows.len(), b.rows.len());
    for (x, y) in a.rows.iter().zip(&b.rows) {
        assert_eq!((x.0, x.1, x.2), (y.0, y.1, y.2));
        for (i, (&v, &w)) in x.3.iter().zip(&y.3).enumerate() {
            if [5, 9].contains(&i) {
                assert_eq!(v, w);
            } else {
                assert!(
                    v.is_nan() && w.is_nan() || (v - w).abs() <= 1e-7 + 1e-9 * w.abs(),
                    "metric {i}: {v} != {w}"
                );
            }
        }
    }
}
fn costs() -> [Costs; 2] {
    [
        Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        },
        Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
    ]
}
fn rules(n: usize) -> Vec<filang::backtest::Rule> {
    (0..n)
        .flat_map(|i| {
            [false, true].map(move |greater| filang::backtest::Rule {
                greater,
                threshold: 0.04 * (i as f64 / (n.max(2) - 1) as f64 - 0.5),
            })
        })
        .collect()
}
#[test]
fn periods_all_backends_pages_and_full_metrics() {
    let d = fixture(1500);
    for count in [1, 13] {
        let mut reference = None;
        for scorer in [
            Scorer::Replay,
            Scorer::Legacy,
            Scorer::Events,
            Scorer::Delta,
            Scorer::Rebuild,
            Scorer::Auto,
        ] {
            for size in [1, 17] {
                let mut source = PeriodPages::new(
                    "sma".into(),
                    "talib".into(),
                    12..=33,
                    1,
                    size,
                    rules(count),
                    [96, 9],
                )
                .unwrap();
                let mut engine = Executor::new(
                    &d,
                    300..1450,
                    vec![800, 801],
                    &costs(),
                    Backend::resolve("auto").unwrap(),
                    scorer,
                    64 * 1024 * 1024,
                )
                .unwrap();
                let mut sink = Capture::default();
                engine.run(&mut source, &mut sink).unwrap();
                if let Some(ref r) = reference {
                    compare(r, &sink);
                } else {
                    reference = Some(sink);
                }
            }
        }
    }
}
#[test]
fn real_open_generator_runs_same_executor_near_trillion_boundary() {
    let d = fixture(1000);
    let mut cfg = WalkConfig::parse(include_str!("../examples/btc4h-walk.cfg")).unwrap();
    cfg.page_size = 8;
    let mut expected = None;
    for scorer in [Scorer::Replay, Scorer::Events, Scorer::Delta, Scorer::Auto] {
        let mut source = OpenPages::new(cfg.clone(), 999_999_999_992, 8, rules(2)).unwrap();
        let mut engine = Executor::new(
            &d,
            400..1000,
            vec![],
            &costs(),
            Backend::Scalar,
            scorer,
            64 * 1024 * 1024,
        )
        .unwrap();
        let mut sink = Capture::default();
        engine.run(&mut source, &mut sink).unwrap();
        assert_eq!(engine.work.programs, 8);
        if let Some(ref r) = expected {
            compare(r, &sink);
        } else {
            expected = Some(sink);
        }
    }
}
#[test]
fn output_summary_matches_streamed_binary_digest() {
    let d = fixture(1000);
    let path = std::env::temp_dir().join(format!(
        "filang-paged-{}-{}.bin",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let mut digests = vec![];
    for full in [true, false] {
        let mut source = PeriodPages::new(
            "ema".into(),
            "talib".into(),
            4..=16,
            1,
            5,
            rules(2),
            [96, 9],
        )
        .unwrap();
        let mut engine = Executor::new(
            &d,
            300..1000,
            vec![],
            &costs(),
            Backend::Scalar,
            Scorer::Auto,
            64 * 1024 * 1024,
        )
        .unwrap();
        let mut sink = BinarySink::new(if full { Some(&path) } else { None }).unwrap();
        engine.run(&mut source, &mut sink).unwrap();
        digests.push(sink.finish().unwrap());
    }
    assert_eq!(digests[0], digests[1]);
    let b = std::fs::read(&path).unwrap();
    assert_eq!(filang::hash::sha256(&b), digests[0].0);
    std::fs::remove_file(path).unwrap();
}
#[test]
fn earlier_metrics_ignore_appended_future_and_chunking() {
    let short = fixture(1000);
    let mut long = fixture(1800);
    for col in &mut long.columns {
        for v in &mut col[1000..] {
            *v *= 3.0;
        }
    }
    let mut expected = None;
    for d in [&short, &long] {
        let mut src = PeriodPages::new(
            "ema".into(),
            "talib".into(),
            4..=30,
            1,
            8,
            rules(3),
            [96, 9],
        )
        .unwrap();
        let mut e = Executor::new(
            d,
            300..1000,
            vec![],
            &costs(),
            Backend::Scalar,
            Scorer::Auto,
            64 * 1024 * 1024,
        )
        .unwrap();
        let mut sink = Capture::default();
        e.run(&mut src, &mut sink).unwrap();
        if let Some(ref a) = expected {
            compare(a, &sink);
        } else {
            expected = Some(sink);
        }
    }
}
#[test]
fn bounded_source_has_no_eager_domain_or_bad_budget() {
    let mut s = PeriodPages::new(
        "sma".into(),
        "talib".into(),
        2..=100000,
        1,
        3,
        rules(1),
        [96, 9],
    )
    .unwrap();
    assert_eq!(s.next_page().unwrap().unwrap().requests.len(), 3);
    let d = fixture(1000);
    assert!(Executor::new(
        &d,
        0..1000,
        vec![],
        &costs(),
        Backend::Scalar,
        Scorer::Auto,
        1
    )
    .is_err());
}
