use filang::{
    anchors,
    backtest::{Costs, Market, Rule},
    data::Data,
    engine,
    kernels::Backend,
    lang::{Graph, Op},
    micro::{self, Config},
    paged::{metric_values, Executor, Scorer},
    regions::Grid,
};
fn data(n: usize) -> Data {
    Data {
        timestamps: (0..n).map(|i| i as i64 * 14400).collect(),
        columns: std::array::from_fn(|j| {
            (0..n)
                .map(|i| match j {
                    0 => 100. + (i as f64 / 13.).sin(),
                    1 => 102. + (i as f64 / 13.).sin(),
                    2 => 98. + (i as f64 / 13.).sin(),
                    3 => 100. + (i as f64 / 11.).sin(),
                    _ => 100. + (i % 17) as f64,
                })
                .collect()
        }),
        interval: 14400,
        digest: "fixture".into(),
    }
}
fn same(a: [f64; 10], b: [f64; 10]) {
    for (i, (x, y)) in a.iter().zip(b).enumerate() {
        if i == 5 || i == 9 {
            assert_eq!(*x, y);
        } else {
            assert!(
                (x.is_nan() && y.is_nan()) || (x - y).abs() <= 1e-7 + 1e-9 * x.abs(),
                "metric {i}: {x} vs {y}"
            );
        }
    }
}
#[test]
fn exact_anchor_expression_and_expanded_neighbors() {
    let (mut g, ids) = micro::stripe(200, 0.).unwrap();
    let root = micro::output(&mut g, ids, 0., 1.).unwrap();
    let mut other = Graph::new();
    let r = anchors::expand(&mut other, "sma", [200; 3], "talib").unwrap();
    assert_eq!(g.identity(root), other.identity(r));
    let d = data(700);
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
    let grid = Grid::parse("990:1:21:1000").unwrap();
    for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
        let mut ex = Executor::new(
            &d,
            0..d.len(),
            vec![501],
            &costs,
            backend,
            Scorer::Auto,
            32 << 20,
        )
        .unwrap();
        for n in [10, 11, 200] {
            for a in [-0.01, 0., 0.01] {
                let (base, ids) = micro::stripe(n, a).unwrap();
                ex.prepare_shared(&base, &ids).unwrap();
                for b in [0., 0.025, 0.1] {
                    let mut g = base.clone();
                    let r = micro::output(&mut g, ids, b, 1.).unwrap();
                    let mut cover = 0;
                    ex.constant_regions(&g, r, grid, false, |lo, hi, ms| {
                        assert_eq!(lo, cover);
                        for q in lo..hi {
                            let mut oracle = base.clone();
                            let root = micro::output(&mut oracle, ids, b, grid.value(q)).unwrap();
                            let batch = engine::evaluate(&oracle, &d, &[root], 32 << 20).unwrap();
                            let mut x = batch.values[&root].clone();
                            x[501] = f64::NAN;
                            for (ci, cost) in costs.iter().enumerate() {
                                let m = Market::new(&d, 0, d.len(), *cost)
                                    .unwrap()
                                    .score(
                                        &x,
                                        Rule {
                                            threshold: 0.,
                                            greater: true,
                                        },
                                    )
                                    .unwrap();
                                same(
                                    metric_values(&m, d.interval),
                                    metric_values(&ms[ci], d.interval),
                                );
                            }
                        }
                        cover = hi;
                        Ok(())
                    })
                    .unwrap();
                    assert_eq!(cover, grid.count);
                }
            }
        }
    }
}
#[test]
fn config_domain_and_future_causality() {
    let c = Config::parse(include_str!("../examples/sma-micro.cfg")).unwrap();
    assert_eq!(c.bases().unwrap(), 5043);
    assert_eq!(c.count().unwrap(), 10091043);
    assert!(Config::parse(
        &include_str!("../examples/sma-micro.cfg")
            .replace("mean_grid=0:1:41:400", "mean_grid=1:1:41:400")
    )
    .is_err());
    let short = data(300);
    let long = data(500);
    let (mut g, ids) = micro::stripe(20, 0.001).unwrap();
    let r = micro::output(&mut g, ids, 0.05, 1.000001).unwrap();
    let x = engine::evaluate(&g, &short, &[r], 16 << 20).unwrap();
    let y = engine::evaluate(&g, &long, &[r], 16 << 20).unwrap();
    for (a, b) in x.values[&r].iter().zip(&y.values[&r]) {
        assert!(a.to_bits() == b.to_bits() || (a.is_nan() && b.is_nan()));
    }
}
#[test]
fn anonymous_programs_use_same_region_plan_and_shared_context_guards() {
    let d = data(260);
    let cost = [Costs {
        fee_bps: 3.,
        slip_bps: 4.,
    }];
    let mut g = Graph::new();
    let close = g.source(3);
    let mean = g.unary(Op::Mean(7), close);
    let mut ex = Executor::new(
        &d,
        0..d.len(),
        vec![],
        &cost,
        Backend::Scalar,
        Scorer::Auto,
        16 << 20,
    )
    .unwrap();
    ex.prepare_shared(&g, &[mean]).unwrap();
    let relative = g.binary(Op::Div, close, mean);
    let squared = g.binary(Op::Mul, relative, relative);
    let one = g.constant(1.);
    let root = g.binary(Op::Sub, squared, one);
    let grid = Grid::parse("999:1:3:1000").unwrap();
    let mut got = vec![];
    ex.constant_regions(&g, root, grid, false, |lo, hi, ms| {
        for _ in lo..hi {
            got.push(metric_values(&ms[0], d.interval));
        }
        Ok(())
    })
    .unwrap();
    let mut q = 0;
    ex.constant_regions(&g, root, grid, true, |lo, hi, ms| {
        assert_eq!(hi, lo + 1);
        same(got[q], metric_values(&ms[0], d.interval));
        q += 1;
        Ok(())
    })
    .unwrap();
    assert_eq!(q, 3);
    assert!(ex
        .constant_regions(&g, squared, grid, false, |_, _, _| Ok(()))
        .is_err());
    let mut incompatible = Graph::new();
    incompatible.source(0);
    incompatible.unary(Op::Mean(7), 0);
    assert!(ex.numerical_roots(&incompatible, &[1], None).is_err());
}
