//! The qualitative algebra with dimensions on (docs/G1_DIMENSIONS.md,
//! section 8): projection re-ranks each axis, a dimension can be forgotten,
//! overlap composition completes each axis separately, and aggregation is
//! refused. Numeric oracles are built from counters, never from the algebra.
use filang::{
    geometry::{Counters, Dimension, DimensionSet, GeometryMode, GeometryPattern},
    geometry_algebra::{
        aggregate_blocks, aggregate_partition, append_one, compose_overlap, composition_count,
        forget_dimension, forget_orientation, overlap_compatible, prepend_one, project,
        CandleOrder,
    },
};
use std::collections::{HashMap, HashSet};

fn pattern(text: &str) -> GeometryPattern {
    text.parse().unwrap()
}

fn set(text: &str) -> DimensionSet {
    DimensionSet::parse(text).unwrap()
}

/// Counters with the wanted volume, delta and trade count.
fn counters(volume: i64, delta: i64, trades: i64) -> Counters {
    assert_eq!((volume + delta) % 2, 0);
    Counters::new(volume as f64, ((volume + delta) / 2) as f64, trades as f64).unwrap()
}

#[test]
fn projection_reranks_every_axis_and_keeps_the_reference() {
    let g = pattern("g1:o:0,1,2,3,u;4,5,6,7,d;1,2,5,6,u|volume:2,0,1|delta:3,0,2/1");
    let p = project(&g, &[0, 2]).unwrap();
    assert_eq!(
        p.to_string(),
        "g1:o:0,1,2,3,u;1,2,4,5,u|volume:1,0|delta:2,1/0"
    );
    // Dropping the only net seller leaves the reference lowest, still there.
    assert_eq!(
        project(&g, &[1]).unwrap().to_string(),
        "g1:o:0,1,2,3,d|volume:0|delta:0/1"
    );
    assert_eq!(project(&g, &[0, 1, 2]).unwrap(), g);
    assert_eq!(project(&p, &[1]).unwrap(), project(&g, &[2]).unwrap());
    // No candle survives: the price part is the zero-candle pattern, each
    // dimension stays on with no rank, and a reference stands alone.
    let empty = project(&g, &[]).unwrap();
    assert_eq!(empty.to_string(), "g1:o:|volume:|delta:/0");
    assert_eq!(empty.dimension_set(), g.dimension_set());
    assert_eq!(pattern(&empty.to_string()), empty);
    assert_eq!(project(&empty, &[]).unwrap(), empty);
    assert!(project(&g, &[1, 1]).is_err());
    assert!(project(&g, &[2, 1]).is_err());
    assert!(project(&g, &[3]).is_err());
    // A pattern with no dimension on projects exactly as it did.
    assert_eq!(
        project(&g.price(), &[0, 2]).unwrap().to_string(),
        "g1:o:0,1,2,3,u;1,2,4,5,u"
    );
    assert_eq!(project(&g.price(), &[0, 2]).unwrap(), p.price());
}

#[test]
fn forgetting_a_dimension_is_a_projection_that_commutes() {
    let g = pattern("g1:o:0,1,2,3,u;4,5,6,7,d;1,2,5,6,u|volume:2,0,1|delta:3,0,2/1|size:0,0,1");
    let without_delta = forget_dimension(&g, Dimension::Delta).unwrap();
    assert_eq!(
        without_delta.to_string(),
        "g1:o:0,1,2,3,u;4,5,6,7,d;1,2,5,6,u|volume:2,0,1|size:0,0,1"
    );
    // Idempotent, the identity on a dimension that is off, and the order in
    // which dimensions are forgotten does not matter.
    assert_eq!(
        forget_dimension(&without_delta, Dimension::Delta).unwrap(),
        without_delta
    );
    assert_eq!(forget_dimension(&g, Dimension::Trades).unwrap(), g);
    let mut every_order = HashSet::new();
    for order in [
        [Dimension::Volume, Dimension::Delta, Dimension::Size],
        [Dimension::Size, Dimension::Volume, Dimension::Delta],
        [Dimension::Delta, Dimension::Size, Dimension::Volume],
    ] {
        let mut current = g.clone();
        for dimension in order {
            current = forget_dimension(&current, dimension).unwrap();
        }
        every_order.insert(current);
    }
    assert_eq!(every_order, HashSet::from([g.price()]));
    assert!(!g.price().has_dimensions());
    assert_eq!(
        forget_dimension(&g.price(), Dimension::Volume).unwrap(),
        g.price()
    );
    for dimension in Dimension::ALL {
        let forgotten = forget_dimension(&g, dimension).unwrap();
        assert!(!forgotten.dimension_set().contains(dimension));
        assert_eq!(forgotten.price(), g.price());
        for indices in [vec![], vec![1], vec![0, 2], vec![0, 1, 2]] {
            assert_eq!(
                project(&forgotten, &indices).unwrap(),
                forget_dimension(&project(&g, &indices).unwrap(), dimension).unwrap()
            );
        }
        assert_eq!(
            forget_orientation(&forgotten).unwrap(),
            forget_dimension(&forget_orientation(&g).unwrap(), dimension).unwrap()
        );
    }
    let unoriented = forget_orientation(&g).unwrap();
    assert_eq!(unoriented.mode(), GeometryMode::Unoriented);
    assert_eq!(unoriented.dimensions(), g.dimensions());
    assert_eq!(
        project(&unoriented, &[0, 2]).unwrap(),
        forget_orientation(&project(&g, &[0, 2]).unwrap()).unwrap()
    );
}

#[test]
fn a_pattern_with_dimensions_refines_the_same_pattern_with_one_off() {
    // From counters: encoding with a dimension off equals encoding with it
    // on and then forgetting it, so the refinements of one pattern partition
    // its windows.
    let rows = [[1., 4., 0., 3.], [3., 5., 2., 2.], [2., 6., 1., 5.]];
    let all = DimensionSet::all();
    let mut seen = 0;
    for volumes in [[10, 10, 30], [30, 20, 10], [20, 20, 20]] {
        for deltas in [[-2, 0, 4], [6, 6, -6], [0, 0, 0], [2, 4, 6]] {
            for trades in [[1, 2, 3], [5, 5, 1]] {
                let bars: Vec<_> = (0..3)
                    .map(|i| counters(volumes[i], deltas[i], trades[i]))
                    .collect();
                let full =
                    GeometryPattern::from_ohlc_counters(&rows, &bars, GeometryMode::Oriented, all)
                        .unwrap()
                        .unwrap();
                for dimension in Dimension::ALL {
                    let narrower = GeometryPattern::from_ohlc_counters(
                        &rows,
                        &bars,
                        GeometryMode::Oriented,
                        all.without(dimension),
                    )
                    .unwrap()
                    .unwrap();
                    assert_eq!(forget_dimension(&full, dimension).unwrap(), narrower);
                    assert_eq!(
                        narrower.matches_ohlc_counters(&rows, &bars).unwrap(),
                        Some(true)
                    );
                }
                for indices in [vec![0usize, 2], vec![1], vec![1, 2]] {
                    let kept_rows: Vec<_> = indices.iter().map(|&i| rows[i]).collect();
                    let kept_bars: Vec<_> = indices.iter().map(|&i| bars[i]).collect();
                    assert_eq!(
                        project(&full, &indices).unwrap(),
                        GeometryPattern::from_ohlc_counters(
                            &kept_rows,
                            &kept_bars,
                            GeometryMode::Oriented,
                            all
                        )
                        .unwrap()
                        .unwrap()
                    );
                }
                seen += 1;
            }
        }
    }
    assert_eq!(seen, 24);
}

#[test]
fn composition_counts_are_the_product_over_the_axes() {
    let a = pattern("g1:u:0,1,2,3");
    assert_eq!(composition_count(&a, &a, 0).unwrap(), 321);
    // One free point against one free point: lower, equal or higher.
    let volume = pattern("g1:u:0,1,2,3|volume:0");
    assert_eq!(composition_count(&volume, &volume, 0).unwrap(), 321 * 3);
    // The reference is one point shared by both operands.
    let buying = pattern("g1:u:0,1,2,3|delta:1/0");
    let selling = pattern("g1:u:0,1,2,3|delta:0/1");
    let balanced = pattern("g1:u:0,1,2,3|delta:0/0");
    assert_eq!(composition_count(&buying, &buying, 0).unwrap(), 321 * 3);
    assert_eq!(composition_count(&buying, &selling, 0).unwrap(), 321);
    assert_eq!(composition_count(&buying, &balanced, 0).unwrap(), 321);
    assert_eq!(composition_count(&balanced, &balanced, 0).unwrap(), 321);
    let both = pattern("g1:u:0,1,2,3|volume:0|delta:1/0");
    assert_eq!(composition_count(&both, &both, 0).unwrap(), 321 * 3 * 3);
    assert!(compose_overlap(&both, &both, 0, 321 * 9 - 1).is_err());
    let completions = compose_overlap(&both, &both, 0, 321 * 9).unwrap();
    assert_eq!(completions.len(), 321 * 9);
    let unique: HashSet<_> = completions.iter().cloned().collect();
    assert_eq!(unique.len(), 321 * 9);
    for completion in &completions {
        assert_eq!(project(completion, &[0]).unwrap(), both);
        assert_eq!(project(completion, &[1]).unwrap(), both);
        assert_eq!(completion.dimension_set(), set("volume,delta"));
    }
    // The price completions are the 0.9 completions, in the 0.9 order, each
    // followed by its dimension completions.
    let price = compose_overlap(&a, &a, 0, 321).unwrap();
    let prices: Vec<_> = completions.iter().map(GeometryPattern::price).collect();
    assert_eq!(
        prices
            .chunks(9)
            .map(|chunk| chunk[0].clone())
            .collect::<Vec<_>>(),
        price
    );
    assert!(prices
        .chunks(9)
        .all(|chunk| chunk.iter().all(|p| *p == chunk[0])));
    assert_eq!(append_one(&both, &both, 321 * 9).unwrap(), completions);
    assert_eq!(prepend_one(&both, &both, 321 * 9).unwrap(), completions);
    // A shared candle fixes its own rank on every axis.
    let left = pattern("g1:o:0,1,2,3,u;4,5,6,7,d|volume:0,1|delta:0,2/1");
    let right = pattern("g1:o:4,5,6,7,d;0,1,2,3,u|volume:1,0|delta:1,2/0");
    assert!(overlap_compatible(&left, &right, 1).unwrap());
    let price_count = composition_count(&left.price(), &right.price(), 1).unwrap();
    // volume: the third candle is below the second, so below, tied with or
    // above the first. delta: it is above the second, which is net buying,
    // and so above the reference and the first.
    assert_eq!(
        composition_count(&left, &right, 1).unwrap(),
        price_count * 3
    );
    let completions = compose_overlap(&left, &right, 1, usize::MAX).unwrap();
    assert_eq!(completions.len() as u128, price_count * 3);
    for completion in &completions {
        assert_eq!(project(completion, &[0, 1]).unwrap(), left);
        assert_eq!(project(completion, &[1, 2]).unwrap(), right);
        assert_eq!(
            completion.dimension(Dimension::Delta).unwrap().to_string(),
            "delta:0,2,3/1"
        );
    }
    // The shared candle disagrees on one axis only: incompatible.
    let other = pattern("g1:o:4,5,6,7,d;0,1,2,3,u|volume:1,0|delta:0,1/1");
    assert!(!overlap_compatible(&left, &other, 1).unwrap());
    assert_eq!(composition_count(&left, &other, 1).unwrap(), 0);
    assert!(compose_overlap(&left, &other, 1, 10).unwrap().is_empty());
    // Operands must have the same dimensions on, as they must share a mode.
    assert!(overlap_compatible(&left, &left.price(), 1).is_err());
    assert!(composition_count(&volume, &buying, 0).is_err());
    assert!(compose_overlap(&volume, &a, 0, 10).is_err());
    assert!(append_one(&volume, &a, 10).is_err());
}

#[test]
fn composition_is_exactly_the_set_of_windows_that_project_to_both_operands() {
    // Every window of three flat candles over small counters, the second and
    // third at one price and the first below, at or above it. The counters
    // realise every order of volume and of delta with the reference,
    // independently, so the windows realise every completion on every axis.
    let dimensions = set("volume,delta");
    let volumes = [10, 20, 30];
    let deltas = [-6, -4, -2, 0, 2, 4, 6];
    let mut candles = Vec::new();
    for volume in volumes {
        for delta in deltas {
            candles.push(counters(volume, delta, 1));
        }
    }
    type Oracle = HashMap<(GeometryPattern, GeometryPattern), HashSet<GeometryPattern>>;
    let mut overlapping: Oracle = HashMap::new();
    let mut disjoint: Oracle = HashMap::new();
    let mut globals = HashSet::new();
    for first in [0.0, 1.0, 2.0] {
        let rows = [[first; 4], [1.0; 4], [1.0; 4]];
        for a in &candles {
            for b in &candles {
                for c in &candles {
                    let global = GeometryPattern::from_ohlc_counters(
                        &rows,
                        &[*a, *b, *c],
                        GeometryMode::Oriented,
                        dimensions,
                    )
                    .unwrap()
                    .unwrap();
                    if !globals.insert(global.clone()) {
                        continue;
                    }
                    overlapping
                        .entry((
                            project(&global, &[0, 1]).unwrap(),
                            project(&global, &[1, 2]).unwrap(),
                        ))
                        .or_default()
                        .insert(global.clone());
                    disjoint
                        .entry((
                            project(&global, &[0]).unwrap(),
                            project(&global, &[1, 2]).unwrap(),
                        ))
                        .or_default()
                        .insert(global);
                }
            }
        }
    }
    // Three places for the first candle's price, 13 orders of three volumes,
    // 75 of three deltas and the reference.
    assert_eq!(globals.len(), 3 * 13 * 75);
    for (oracle, shared) in [(&overlapping, 1), (&disjoint, 0)] {
        let mut total = 0;
        for ((left, right), expected) in oracle {
            assert!(overlap_compatible(left, right, shared).unwrap());
            assert_eq!(
                composition_count(left, right, shared).unwrap(),
                expected.len() as u128
            );
            let composed = compose_overlap(left, right, shared, expected.len()).unwrap();
            assert_eq!(composed.len(), expected.len());
            assert_eq!(&composed.into_iter().collect::<HashSet<_>>(), expected);
            total += expected.len();
        }
        assert_eq!(total, globals.len());
    }
    // Set-valued associativity: composing (A,B) with C and A with (B,C) give
    // the same set, which holds every window above and every other price
    // arrangement of three flat candles: 13 orders on each of three axes,
    // and 75 on the one with a reference.
    let mut left_first = HashSet::new();
    let mut right_first = HashSet::new();
    let singles: HashSet<_> = globals
        .iter()
        .map(|global| project(global, &[0]).unwrap())
        .collect();
    assert_eq!(singles.len(), 3);
    for a in &singles {
        for b in &singles {
            for ab in compose_overlap(a, b, 0, 10_000).unwrap() {
                for c in &singles {
                    left_first.extend(compose_overlap(&ab, c, 0, 10_000).unwrap());
                }
            }
            for c in &singles {
                for bc in compose_overlap(b, c, 0, 10_000).unwrap() {
                    right_first.extend(compose_overlap(a, &bc, 0, 10_000).unwrap());
                }
            }
        }
    }
    assert_eq!(left_first, right_first);
    assert_eq!(left_first.len(), 13 * 13 * 75);
    assert!(globals.is_subset(&left_first));
}

#[test]
fn aggregation_refuses_a_pattern_with_a_dimension_on() {
    let plain = pattern("g1:o:0,1,2,3,u;1,2,4,5,u");
    assert!(aggregate_blocks(&plain, 2, CandleOrder::OldestFirst).is_ok());
    for text in [
        "g1:o:0,1,2,3,u;1,2,4,5,u|volume:0,1",
        "g1:o:0,1,2,3,u;1,2,4,5,u|delta:0,0/0",
        "g1:o:0,1,2,3,u;1,2,4,5,u|volume:0,0|trades:0,1|size:1,0",
        "g1:o:|volume:",
    ] {
        let g = pattern(text);
        for order in [CandleOrder::OldestFirst, CandleOrder::NewestFirst] {
            assert!(aggregate_blocks(&g, 1, order).is_err(), "{text}");
            assert!(aggregate_blocks(&g, 2, order).is_err(), "{text}");
            assert!(
                aggregate_partition(&g, &[g.len()], order).is_err(),
                "{text}"
            );
        }
        // Forgetting every dimension first is the caller's explicit choice.
        assert!(aggregate_blocks(&g.price(), 1, CandleOrder::OldestFirst).is_ok());
    }
}
