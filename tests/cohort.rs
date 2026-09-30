use filang::{
    backtest::{Costs, Market, Rule},
    cohort,
    data::Data,
    engine,
    kernels::Backend,
    lang::{Graph, Op},
    paged::{metric_values, Executor, Scorer},
    regions::{self, Grid},
};
fn data(n: usize) -> Data {
    Data {
        timestamps: (0..n).map(|i| i as i64 * 14400).collect(),
        columns: std::array::from_fn(|j| {
            (0..n)
                .map(|i| {
                    let base = 100. + (i as f64 / 11.).sin();
                    match j {
                        0 => base + 0.1 * (i as f64).cos(),
                        1 => base + 3.,
                        2 => base - 3.,
                        3 => base,
                        _ => 100. + (i % 13) as f64,
                    }
                })
                .collect()
        }),
        interval: 14400,
        digest: "cohort_fixture".into(),
    }
}
fn same(a: [f64; 10], b: [f64; 10]) {
    for (i, (x, y)) in a.iter().zip(b).enumerate() {
        if i == 5 || i == 9 {
            assert_eq!(*x, y);
        } else {
            assert!(
                (x.is_nan() && y.is_nan()) || (x - y).abs() <= 1e-7 + 1e-9 * x.abs(),
                "metric {i}: {x} != {y}"
            );
        }
    }
}
#[test]
fn general_mean_absolute_deviation_contract() {
    let mut d = data(8);
    d.columns[3] = vec![1., 2., 3., f64::NAN, 4., 5., 6., 7.];
    let mut g = Graph::new();
    let c = g.source(3);
    assert!(g.add(Op::MeanAbsDev(0), vec![c]).is_err());
    assert!(g.add(Op::MeanAbsDev(100001), vec![c]).is_err());
    let r = g.parse("(mad_mean 3 close)").unwrap();
    let out = engine::evaluate(&g, &d, &[r], 1 << 20).unwrap();
    let x = &out.values[&r];
    assert!((x[2] - 2. / 3.).abs() < 1e-15);
    assert!(x[3..6].iter().all(|v| v.is_nan()));
    assert!((x[6] - 2. / 3.).abs() < 1e-15);
    assert_eq!(g.nodes[r].unit, g.nodes[c].unit);
    assert_eq!(g.parse(&g.expression(r)).unwrap(), r);
}
#[test]
fn signed_certificate_extremes_ties_and_subnormals() {
    let g = Grid::parse("-4:1:9:2").unwrap();
    let tiny = f64::from_bits(1);
    let values = [
        -2.,
        -1.,
        -tiny,
        -0.,
        0.,
        tiny,
        1.,
        2.,
        f64::NAN,
        f64::INFINITY,
    ];
    regions::certificate(&values, g).unwrap();
    assert!(regions::certificate(&[f64::MAX], g).is_err());
    for x in values {
        for i in 0..g.count {
            let c = g.value(i);
            let y = x - c;
            assert_eq!(x.is_finite() && x > c, y.is_finite() && y > 0.);
        }
    }
}
#[test]
fn ten_families_expanded_and_regions_all_backends() {
    let d = data(640);
    let costs = [
        Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        },
        Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
    ];
    for kind in cohort::KINDS {
        let (n, center, grid) = cohort::defaults(kind).unwrap();
        let grid = Grid {
            step: grid.step * 250,
            count: 9,
            ..grid
        };
        for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
            let mut ex = Executor::new(
                &d,
                0..d.len(),
                vec![],
                &costs,
                backend,
                Scorer::Auto,
                64 << 20,
            )
            .unwrap();
            for a in [0., 0.0005] {
                let (base, ids) = cohort::stripe(kind, n, a).unwrap();
                ex.prepare_shared(&base, &ids).unwrap();
                for b in [0., 0.05] {
                    let mut g = base.clone();
                    let root = cohort::output(&mut g, kind, ids, b, center).unwrap();
                    let mut covered = 0;
                    ex.constant_regions(&g, root, grid, false, |lo, hi, ms| {
                        assert_eq!(lo, covered);
                        for q in lo..hi {
                            let mut direct = base.clone();
                            let r =
                                cohort::output(&mut direct, kind, ids, b, grid.value(q)).unwrap();
                            let v = engine::evaluate(&direct, &d, &[r], 64 << 20).unwrap();
                            for (ci, &cost) in costs.iter().enumerate() {
                                let m = Market::new(&d, 0, d.len(), cost)
                                    .unwrap()
                                    .score(
                                        &v.values[&r],
                                        Rule {
                                            greater: true,
                                            threshold: 0.,
                                        },
                                    )
                                    .unwrap();
                                same(
                                    metric_values(&m, d.interval),
                                    metric_values(&ms[ci], d.interval),
                                );
                            }
                        }
                        covered = hi;
                        Ok(())
                    })
                    .unwrap();
                    assert_eq!(covered, grid.count);
                }
            }
        }
    }
}
#[test]
fn earlier_cohort_values_unchanged_by_future_append() {
    let d = data(800);
    let prefix = d.prefix(450);
    for kind in cohort::KINDS {
        let (n, c, _) = cohort::defaults(kind).unwrap();
        let (mut g, ids) = cohort::stripe(kind, n, 0.005).unwrap();
        let r = cohort::output(&mut g, kind, ids, 0.05, c).unwrap();
        let a = engine::evaluate(&g, &prefix, &[r], 64 << 20).unwrap();
        let b = engine::evaluate(&g, &d, &[r], 64 << 20).unwrap();
        for (x, y) in a.values[&r].iter().zip(&b.values[&r]) {
            assert!(x.to_bits() == y.to_bits() || (x.is_nan() && y.is_nan()));
        }
    }
}
#[test]
fn ten_configs_and_exact_sma_identity() {
    let mut total = 0;
    for kind in cohort::KINDS {
        let raw = std::fs::read_to_string(format!(
            "{}/examples/micro10/{kind}.cfg",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap();
        let c = filang::micro::Config::parse(&raw).unwrap();
        assert_eq!(c.family, kind);
        assert_eq!(c.bases().unwrap(), 5043);
        total += c.count().unwrap();
    }
    assert_eq!(total, 100910430);
    let (mut g, ids) = cohort::stripe("sma", 200, 0.).unwrap();
    let r = cohort::output(&mut g, "sma", ids, 0., 1.).unwrap();
    let (mut old, ids) = filang::micro::stripe(200, 0.).unwrap();
    let q = filang::micro::output(&mut old, ids, 0., 1.).unwrap();
    assert_eq!(g.identity(r), old.identity(q));
}

#[test]
fn independent_talib_reference_fixtures_on_each_native_backend() {
    let d = Data::parse(include_str!("fixtures/cohort_ohlcv.csv"), 14400).unwrap();
    let bytes = include_bytes!("fixtures/cohort_reference.bin");
    assert_eq!(bytes.len(), 10 * d.len() * 8);
    for (j, kind) in cohort::KINDS.iter().enumerate() {
        let (n, c, _) = cohort::defaults(kind).unwrap();
        let (mut g, ids) = cohort::stripe(kind, n, 0.).unwrap();
        let root = cohort::output(&mut g, kind, ids, 0., c).unwrap();
        for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
            let store = filang::family::prepare(
                &g,
                &d,
                &filang::family::boundaries(&g, &[root]),
                64 << 20,
                backend,
                None,
            )
            .unwrap();
            let p = filang::family::Program::compile(&g, root, &store, None).unwrap();
            let x = p
                .execute(&store, None, &[], backend, true)
                .unwrap()
                .1
                .unwrap();
            for (t, &got) in x.iter().enumerate() {
                let off = (j * d.len() + t) * 8;
                let want = f64::from_le_bytes(bytes[off..off + 8].try_into().unwrap());
                assert_eq!(got.is_finite(), want.is_finite(), "{kind} {t} validity");
                assert!(
                    (got.is_nan() && want.is_nan())
                        || (got - want).abs() <= 1e-8 + 1e-9 * want.abs(),
                    "{kind} {t}: {got} != {want}"
                );
                assert_eq!(
                    got.is_finite() && got > 0.,
                    want.is_finite() && want > 0.,
                    "{kind} {t} decision"
                );
            }
        }
    }
}

#[test]
fn explicit_parity_range_keeps_warmup_and_rejects_future_rows() {
    use std::{
        fs,
        time::{SystemTime, UNIX_EPOCH},
    };
    let tag = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("filang-year-parity-{}-{tag}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let input = dir.join("input.csv");
    let csv = include_str!("fixtures/cohort_ohlcv.csv")
        .lines()
        .take(301)
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    fs::write(&input, csv).unwrap();
    let a = dir.join("a");
    let b = dir.join("b");
    filang::cohort_parity::run_range(
        input.to_str().unwrap(),
        a.to_str().unwrap(),
        "1970-02-10",
        "1970-02-20",
    )
    .unwrap();
    filang::cohort_parity::run_range(
        input.to_str().unwrap(),
        b.to_str().unwrap(),
        "1970-02-15",
        "1970-02-20",
    )
    .unwrap();
    assert_eq!(
        fs::read(a.join("features.bin")).unwrap(),
        fs::read(b.join("features.bin")).unwrap()
    );
    let manifest = fs::read_to_string(b.join("manifest.json")).unwrap();
    assert!(manifest.contains("\"start_index\":270"));
    assert!(manifest.contains("\"end_index\":300"));
    let invalid = dir.join("invalid");
    assert!(filang::cohort_parity::run_range(
        input.to_str().unwrap(),
        invalid.to_str().unwrap(),
        "1970-02-10",
        "1970-02-19"
    )
    .is_err());
    assert!(!invalid.exists());
    assert!(filang::cohort_parity::run_range(
        input.to_str().unwrap(),
        invalid.to_str().unwrap(),
        "1970-02-21",
        "1970-02-20"
    )
    .is_err());
    assert!(
        filang::cohort_parity::run(input.to_str().unwrap(), invalid.to_str().unwrap()).is_err()
    );
    fs::remove_dir_all(dir).unwrap();
}
