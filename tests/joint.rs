use filang::{
    backtest::{Costs, Market},
    data::Data,
    joint::{domain_count, Alternative, Plan, Sweep},
    kernels::Backend,
    paged::{metric_values, Executor, Scorer},
    regions::Grid,
    rule_kernels::{self, Logic},
    rules::{self, Cmp, Mask, Node, Predicate, Program, Qualifier},
};
use std::{collections::BTreeMap, sync::Arc};
fn fixture(n: usize) -> Data {
    Data {
        timestamps: (0..n).map(|i| i as i64 * 14400).collect(),
        columns: std::array::from_fn(|j| {
            (0..n)
                .map(|t| {
                    let p = 100. + (t as f64 / 13.).sin();
                    match j {
                        0 => p,
                        1 => p + 2.,
                        2 => p - 2.,
                        3 => p + 0.2 * (t as f64 / 5.).sin(),
                        _ => 10. + (t % 7) as f64,
                    }
                })
                .collect()
        }),
        interval: 14400,
        digest: "joint-fixture".into(),
    }
}
fn scalar(p: &Program, inputs: &[&Mask]) -> Mask {
    let n = inputs[0].len;
    let mut rows: Vec<Vec<Option<bool>>> = Vec::new();
    for node in &p.nodes {
        let mut out = vec![None; n];
        for (t, item) in out.iter_mut().enumerate() {
            *item = match *node {
                Node::Slot(s) => {
                    let (x, v) = inputs[s].at(t);
                    if v {
                        Some(x)
                    } else {
                        None
                    }
                }
                Node::And(a, b) => match (rows[a][t], rows[b][t]) {
                    (Some(x), Some(y)) => Some(x && y),
                    _ => None,
                },
                Node::Or(a, b) => match (rows[a][t], rows[b][t]) {
                    (Some(x), Some(y)) => Some(x || y),
                    _ => None,
                },
                Node::Not(a) => rows[a][t].map(|v| !v),
                Node::Onset(a) if t > 0 => match (rows[a][t], rows[a][t - 1]) {
                    (Some(x), Some(y)) => Some(x && !y),
                    _ => None,
                },
                Node::Persist(a, k) | Node::Recent(a, k) if t + 1 >= k => {
                    let w = &rows[a][t + 1 - k..=t];
                    if w.iter().all(Option::is_some) {
                        Some(if matches!(node, Node::Persist(..)) {
                            w.iter().all(|x| x == &Some(true))
                        } else {
                            w.contains(&Some(true))
                        })
                    } else {
                        None
                    }
                }
                _ => None,
            };
        }
        rows.push(out);
    }
    let mut out = Mask::empty(n);
    for (t, x) in rows[p.root].iter().enumerate() {
        out.set(t, x.unwrap_or(false), x.is_some());
    }
    out
}
fn same(a: &[f64; 10], b: &[f64; 10]) {
    for i in 0..10 {
        if i == 5 || i == 9 {
            assert_eq!(a[i], b[i]);
        } else {
            assert!(
                (a[i].is_nan() && b[i].is_nan()) || (a[i] - b[i]).abs() <= 1e-7 + 1e-9 * b[i].abs(),
                "metric {i}: {} != {}",
                a[i],
                b[i]
            );
        }
    }
}
#[test]
fn rule_truth_validity_temporal_and_simd_tails() {
    for len in [1, 2, 63, 64, 65, 129, 301] {
        let mut a = Mask::empty(len);
        let mut b = a.clone();
        let mut c = a.clone();
        for t in 0..len {
            a.set(t, t % 3 == 0, t % 17 != 0);
            b.set(t, t % 5 < 3, t % 13 != 0);
            c.set(t, t % 7 < 4, t % 19 != 0);
        }
        for text in [
            "(and s0 (or s1 (not s2)))",
            "(or (and s0 s1) (and (not s0) s2))",
            "(persist 3 (or s0 (and s1 s2)))",
            "(recent 5 (and s0 (not (or s1 s2))))",
            "(onset (and s0 (or s1 s2)))",
        ] {
            let p = Program::parse(text, 3).unwrap();
            let inputs = [&a, &b, &c];
            let expected = scalar(&p, &inputs);
            for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
                assert_eq!(p.evaluate(&inputs, backend).unwrap(), expected);
                if p.pointwise() {
                    let (z, o) = p.cofactors(&inputs, 2, backend).unwrap();
                    let mut bits = vec![0; a.bits.len()];
                    rule_kernels::select(&z.bits, &o.bits, &c.bits, &mut bits, backend).unwrap();
                    assert_eq!(bits, expected.bits, "len={len} rule={text} backend={backend:?} zero={:?} one={:?} selector={:?}",z.bits,o.bits,c.bits);
                }
            }
        }
        let mut out = vec![0; a.bits.len()];
        rule_kernels::combine(
            &a.bits,
            &b.bits,
            &mut out,
            Logic::And,
            Backend::resolve("auto").unwrap(),
        )
        .unwrap();
        assert_eq!(
            out,
            a.bits
                .iter()
                .zip(&b.bits)
                .map(|(x, y)| x & y)
                .collect::<Vec<_>>()
        );
        for start in 0..len {
            assert_eq!(a.slice(start, len).unwrap().at(0), a.at(start));
        }
    }
}
#[test]
fn every_comparator_cell_qualifier_and_crossing() {
    let x = [
        f64::NAN,
        -1.,
        -0.,
        0.,
        f64::from_bits(1),
        0.5,
        1.,
        f64::INFINITY,
        -0.5,
    ];
    let y = [0., -1., 0., 0.5, 0., 0., 1., 2., -1.];
    let grid = Grid::parse("-4:1:9:4").unwrap();
    for cmp in [Cmp::Gt, Cmp::Ge, Cmp::Lt, Cmp::Le, Cmp::Eq, Cmp::Ne] {
        let predicate = Predicate::Threshold(cmp);
        for qs in [
            vec![Qualifier::Plain],
            vec![Qualifier::Persist(2)],
            vec![Qualifier::Recent(3), Qualifier::Onset],
        ] {
            let cells = rules::cells(&predicate, &x, None, grid, &qs, 1 << 20).unwrap();
            let mut covered = 0;
            for cell in cells {
                assert_eq!(cell.lo, covered);
                for q in cell.lo..cell.hi {
                    let c = grid.value(q);
                    let mut direct = Mask::empty(x.len());
                    for (t, &v) in x.iter().enumerate() {
                        direct.set(t, cmp.test(v, c), v.is_finite());
                    }
                    for &qual in &qs {
                        direct = direct.qualify(qual).unwrap();
                    }
                    assert_eq!(cell.mask, direct);
                }
                covered = cell.hi;
            }
            assert_eq!(covered, grid.count);
        }
    }
    let cross = Predicate::Cross(true)
        .evaluate(&x, Some(&y), 0., &[])
        .unwrap();
    for t in 1..x.len() {
        let valid = [x[t], y[t], x[t - 1], y[t - 1]]
            .iter()
            .all(|x| x.is_finite());
        assert_eq!(
            cross.at(t),
            (valid && x[t] > y[t] && x[t - 1] <= y[t - 1], valid)
        );
    }
    assert!(Program::parse("(and s0 s2)", 2).is_err());
    assert!(Program::parse("(recent 0 s0)", 1).is_err());
    assert!(Program::parse("(magic s0)", 1).is_err());
}
fn brute(slots: &[Vec<Alternative>], used: &mut Vec<String>, depth: usize, weighted: bool) -> u64 {
    if depth == slots.len() {
        return 1;
    }
    let mut out = 0;
    for a in &slots[depth] {
        if used.contains(&a.tag) {
            continue;
        }
        used.push(a.tag.clone());
        out += brute(slots, used, depth + 1, weighted) * if weighted { a.count } else { 1 };
        used.pop();
    }
    out
}
#[test]
fn cartesian_domain_counts_without_address_enumeration() {
    for n in 1..=6 {
        let slots = (0..n)
            .map(|s| {
                (0..5)
                    .map(|i| Alternative {
                        id: s * 5 + i,
                        tag: format!("t{}", (i + s) % 7),
                        count: (i + s + 1) as u64,
                        cells: Arc::new(vec![]),
                    })
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        for w in [true, false] {
            assert_eq!(
                domain_count(&slots, true, w).unwrap(),
                brute(&slots, &mut vec![], 0, w)
            );
        }
    }
    let slots = vec![
        vec![Alternative {
            id: 0,
            tag: "a".into(),
            count: 1_000_001,
            cells: Arc::new(vec![]),
        }],
        vec![Alternative {
            id: 1,
            tag: "b".into(),
            count: 1_000_001,
            cells: Arc::new(vec![]),
        }],
    ];
    assert_eq!(domain_count(&slots, true, true).unwrap(), 1_000_002_000_001);
}
#[test]
fn joint_boxes_match_every_expanded_metric_including_temporal_rules() {
    let d = fixture(192);
    let costs = [
        Costs {
            fee_bps: 10.,
            slip_bps: 10.,
        },
        Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        },
    ];
    let range = 30..d.len();
    let grid = Grid::parse("-1:1:3:2").unwrap();
    for slots_n in [2, 3] {
        for full in [false, true] {
            let texts = if slots_n == 2 {
                vec![
                    "(and s0 s1)",
                    "(or s0 (not s1))",
                    if full {
                        "(recent 3 (and s0 s1))"
                    } else {
                        "(and (not s0) s1)"
                    },
                ]
            } else {
                vec![
                    "(and (or s0 s1) s2)",
                    "(or (and s0 s1) (and (not s1) s2))",
                    if full {
                        "(persist 2 (or s0 (and s1 s2)))"
                    } else {
                        "(and s0 (and s1 s2))"
                    },
                ]
            };
            let programs = texts
                .iter()
                .map(|t| Program::parse(t, slots_n).unwrap())
                .collect::<Vec<_>>();
            let slots = (0..slots_n)
                .map(|s| {
                    (0..2)
                        .map(|i| {
                            let x = (0..d.len())
                                .map(|t| {
                                    if t % 51 == 0 {
                                        f64::NAN
                                    } else {
                                        ((t + s * 11 + i * 7) as f64 / 9.).sin()
                                    }
                                })
                                .collect::<Vec<_>>();
                            let mut cells = rules::cells(
                                &Predicate::Threshold(if i == 0 { Cmp::Gt } else { Cmp::Le }),
                                &x,
                                None,
                                grid,
                                &[Qualifier::Recent(2)],
                                1 << 20,
                            )
                            .unwrap();
                            if !full {
                                for c in &mut cells {
                                    c.mask = c.mask.slice(range.start, range.end - 2).unwrap();
                                }
                            }
                            Alternative {
                                id: s * 2 + i,
                                tag: format!("g{s}"),
                                count: grid.count,
                                cells: Arc::new(cells),
                            }
                        })
                        .collect::<Vec<_>>()
                })
                .collect::<Vec<_>>();
            let mut expected: BTreeMap<String, [f64; 10]> = BTreeMap::new();
            for (backend, plan, cache) in [
                (Backend::Scalar, Plan::Expanded, 0),
                (Backend::Scalar, Plan::Cells, 0),
                (Backend::resolve("auto").unwrap(), Plan::Cofactor, 1 << 20),
            ] {
                let mut ex = Executor::new(
                    &d,
                    range.clone(),
                    vec![],
                    &costs,
                    backend,
                    Scorer::Auto,
                    32 << 20,
                )
                .unwrap();
                let mut sweep = Sweep::new(
                    &mut ex,
                    &d,
                    range.clone(),
                    &costs,
                    backend,
                    plan,
                    true,
                    cache,
                    full,
                    1_000_000,
                )
                .unwrap();
                let mut seen = 0u64;
                sweep
                    .run(&slots, &programs, |r| {
                        let mut points = vec![Vec::<u64>::new()];
                        for &(lo, hi) in &r.ranges {
                            let mut next = vec![];
                            for p in points {
                                for q in lo..hi {
                                    let mut c = p.clone();
                                    c.push(q);
                                    next.push(c);
                                }
                            }
                            points = next;
                        }
                        for point in points {
                            seen += 1;
                            let selected = r
                                .choices
                                .iter()
                                .enumerate()
                                .map(|(s, &id)| slots[s].iter().find(|a| a.id == id).unwrap())
                                .collect::<Vec<_>>();
                            let masks = point
                                .iter()
                                .enumerate()
                                .map(|(s, &q)| {
                                    &selected[s]
                                        .cells
                                        .iter()
                                        .find(|c| c.lo <= q && q < c.hi)
                                        .unwrap()
                                        .mask
                                })
                                .collect::<Vec<_>>();
                            let mut mask = scalar(&programs[r.template], &masks);
                            if full {
                                mask = mask.slice(range.start, range.end - 2).unwrap();
                            }
                            let pos = (0..mask.len).map(|t| mask.at(t).0).collect::<Vec<_>>();
                            for (ci, cost) in costs.iter().enumerate() {
                                let reference =
                                    Market::new(&d, range.start, range.end, *cost).unwrap();
                                let metric = filang::backtest::metrics_from_ledger(
                                    &reference.position_ledger(&pos).unwrap(),
                                    d.interval,
                                )
                                .unwrap();
                                let got = metric_values(&r.metrics[ci], d.interval);
                                same(&got, &metric_values(&metric, d.interval));
                                let key = format!("{}:{:?}:{point:?}:{ci}", r.template, r.choices);
                                if plan == Plan::Expanded {
                                    assert!(expected.insert(key, got).is_none());
                                } else {
                                    same(&got, &expected[&key]);
                                }
                            }
                        }
                        Ok(())
                    })
                    .unwrap();
                assert_eq!(
                    seen,
                    domain_count(&slots, true, true).unwrap() * programs.len() as u64
                );
                assert_eq!(sweep.work.logical, seen);
            }
        }
    }
}
#[test]
fn future_append_and_input_rejection() {
    let data = fixture(80);
    let all = fixture(160);
    let predicate = Predicate::Slope(true, 3);
    let a = predicate
        .evaluate(&data.columns[3], None, 0., &[Qualifier::Recent(4)])
        .unwrap();
    let b = predicate
        .evaluate(&all.columns[3], None, 0., &[Qualifier::Recent(4)])
        .unwrap();
    assert_eq!(a, b.slice(0, 80).unwrap());
    let mut g = filang::lang::Graph::new();
    let p = g.source(3);
    let v = g.source(4);
    assert!(Predicate::Relative(Cmp::Gt)
        .validate(&g, p, Some(v), Grid::parse("0:1:1:1").unwrap())
        .is_err());
    assert!(filang::joint_run::Domain::parse(
        "0\tx\tp\tthreshold:gt\tplain\t0:1:3:1\tclose\t-\n",
        "(and s0 s1)"
    )
    .is_err());
}

#[test]
fn actual_joint_trillion_domain_is_resolved_as_disjoint_boxes() {
    let d = fixture(32);
    let grid = Grid::parse("-500000:1:1000001:1000000").unwrap();
    let costs = [Costs {
        fee_bps: 10.,
        slip_bps: 10.,
    }];
    let values = [
        (0..30).map(|i| (i as f64 / 5.).sin()).collect::<Vec<_>>(),
        (0..30).map(|i| (i as f64 / 7.).cos()).collect::<Vec<_>>(),
    ];
    let slots = (0..2)
        .map(|s| {
            vec![Alternative {
                id: s,
                tag: format!("{s}"),
                count: grid.count,
                cells: Arc::new(
                    rules::cells(
                        &Predicate::Threshold(Cmp::Gt),
                        &values[s],
                        None,
                        grid,
                        &[],
                        1 << 20,
                    )
                    .unwrap(),
                ),
            }]
        })
        .collect::<Vec<_>>();
    let p = Program::parse("(and s0 (not s1))", 2).unwrap();
    let mut ex = Executor::new(
        &d,
        0..32,
        vec![],
        &costs,
        Backend::Scalar,
        Scorer::Auto,
        16 << 20,
    )
    .unwrap();
    let mut run = Sweep::new(
        &mut ex,
        &d,
        0..32,
        &costs,
        Backend::Scalar,
        Plan::Cofactor,
        true,
        1 << 20,
        false,
        10000,
    )
    .unwrap();
    run.run(&slots, &[p], |b| {
        for a in [b.ranges[0].0, b.ranges[0].1 - 1] {
            for c in [b.ranges[1].0, b.ranges[1].1 - 1] {
                let pos = (0..30)
                    .map(|i| values[0][i] > grid.value(a) && values[1][i] <= grid.value(c))
                    .collect::<Vec<_>>();
                let market = Market::new(&d, 0, 32, costs[0]).unwrap();
                let m = filang::backtest::metrics_from_ledger(
                    &market.position_ledger(&pos).unwrap(),
                    d.interval,
                )
                .unwrap();
                same(
                    &metric_values(&b.metrics[0], d.interval),
                    &metric_values(&m, d.interval),
                );
            }
        }
        Ok(())
    })
    .unwrap();
    assert_eq!(run.work.logical, 1_000_002_000_001);
    assert!(run.work.boxes < 1000);
}

#[test]
fn public_joint_api_rejects_cross_context_and_incomplete_cells() {
    let d = fixture(32);
    let other = fixture(32);
    let costs = [Costs {
        fee_bps: 10.,
        slip_bps: 10.,
    }];
    let mut ex = Executor::new(
        &d,
        0..32,
        vec![],
        &costs,
        Backend::Scalar,
        Scorer::Auto,
        16 << 20,
    )
    .unwrap();
    assert!(ex.validate_joint_context(&other, &(0..32), &costs).is_err());
    assert!(ex.validate_joint_context(&d, &(1..32), &costs).is_err());
    assert!(ex
        .validate_joint_context(
            &d,
            &(0..32),
            &[Costs {
                fee_bps: 5.,
                slip_bps: 10.
            }]
        )
        .is_err());
    let grid = Grid::parse("-1:1:3:1").unwrap();
    let x = (0..30).map(|i| (i as f64 / 4.).sin()).collect::<Vec<_>>();
    let cells = rules::cells(&Predicate::Threshold(Cmp::Gt), &x, None, grid, &[], 1 << 20).unwrap();
    let p = Program::parse("(and s0 s1)", 2).unwrap();
    let good = vec![
        vec![Alternative {
            id: 0,
            tag: "a".into(),
            count: 3,
            cells: Arc::new(cells.clone()),
        }],
        vec![Alternative {
            id: 1,
            tag: "b".into(),
            count: 3,
            cells: Arc::new(cells.clone()),
        }],
    ];
    for case in 0..5 {
        let mut slots = good.clone();
        match case {
            0 => slots[0][0].count = 4,
            1 => {
                let mut c = cells.clone();
                c[0].lo = 1;
                slots[0][0].cells = Arc::new(c);
            }
            2 => slots[1][0].id = 0,
            3 => {
                let mut c = cells.clone();
                c[0].mask.valid[0] = 0;
                slots[0][0].cells = Arc::new(c);
            }
            _ => slots[0][0].cells = Arc::new(vec![]),
        }
        let mut sweep = Sweep::new(
            &mut ex,
            &d,
            0..32,
            &costs,
            Backend::Scalar,
            Plan::Cofactor,
            true,
            0,
            false,
            10000,
        )
        .unwrap();
        assert!(sweep.run(&slots, &[p.clone()], |_| Ok(())).is_err());
    }
    let temporal = Program::parse("(recent 2 (and s0 s1))", 2).unwrap();
    let mut sweep = Sweep::new(
        &mut ex,
        &d,
        0..32,
        &costs,
        Backend::Scalar,
        Plan::Cofactor,
        true,
        0,
        false,
        10000,
    )
    .unwrap();
    assert!(sweep.run(&good, &[temporal], |_| Ok(())).is_err());
    assert!(rules::cells(
        &Predicate::Relative(Cmp::Gt),
        &x,
        Some(&x),
        grid,
        &[],
        1 << 20
    )
    .is_err());
    assert!(Predicate::Slope(true, 0)
        .evaluate(&x, None, 0., &[])
        .is_err());
}

#[test]
fn partitioned_domain_replay_preserves_coordinates_coverage_and_metrics() {
    let d = fixture(96);
    let costs = [Costs {
        fee_bps: 10.,
        slip_bps: 10.,
    }];
    let grid = Grid::parse("-1:1:3:2").unwrap();
    let slots = (0..2)
        .map(|s| {
            (0..2)
                .map(|i| {
                    let values = (0..94)
                        .map(|t| ((t + s * 7 + i * 11) as f64 / 9.).sin())
                        .collect::<Vec<_>>();
                    Alternative {
                        id: s * 2 + i,
                        tag: format!("{s}"),
                        count: grid.count,
                        cells: Arc::new(
                            rules::cells(
                                &Predicate::Threshold(Cmp::Gt),
                                &values,
                                None,
                                grid,
                                &[],
                                1 << 20,
                            )
                            .unwrap(),
                        ),
                    }
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();
    let p = Program::parse("(or s0 (not s1))", 2).unwrap();
    let evaluate = |domain: &[Vec<Alternative>]| {
        let mut ex = Executor::new(
            &d,
            0..96,
            vec![],
            &costs,
            Backend::Scalar,
            Scorer::Auto,
            16 << 20,
        )
        .unwrap();
        let mut sweep = Sweep::new(
            &mut ex,
            &d,
            0..96,
            &costs,
            Backend::Scalar,
            Plan::Cofactor,
            true,
            1 << 20,
            false,
            10000,
        )
        .unwrap();
        let mut out = BTreeMap::new();
        sweep
            .run(domain, &[p.clone()], |b| {
                out.insert(
                    (b.choices.clone(), b.ranges.clone()),
                    metric_values(&b.metrics[0], d.interval),
                );
                Ok(())
            })
            .unwrap();
        (out, sweep.work.logical)
    };
    let (full, coverage) = evaluate(&slots);
    let mut merged = BTreeMap::new();
    let mut partial_coverage = 0;
    for a in &slots[0] {
        let (part, n) = evaluate(&[vec![a.clone()], slots[1].clone()]);
        partial_coverage += n;
        for (k, v) in part {
            assert!(merged.insert(k, v).is_none());
        }
    }
    assert_eq!(coverage, partial_coverage);
    assert_eq!(full.len(), merged.len());
    for (k, v) in &full {
        same(v, &merged[k]);
    }
}
