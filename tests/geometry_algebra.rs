use filang::{
    geometry::{BodyDirection, GeometryMode, GeometryPattern},
    geometry_algebra::{
        aggregate_blocks as aggregate_blocks_in_order,
        aggregate_partition as aggregate_partition_in_order, append_one, compose_overlap,
        composition_count, forget_orientation, overlap_compatible, prepend_one, project,
        CandleOrder,
    },
};
use std::collections::{HashMap, HashSet};

fn aggregate_blocks(pattern: &GeometryPattern, size: usize) -> Result<GeometryPattern, String> {
    aggregate_blocks_in_order(pattern, size, CandleOrder::OldestFirst)
}

fn aggregate_partition(
    pattern: &GeometryPattern,
    groups: &[usize],
) -> Result<GeometryPattern, String> {
    aggregate_partition_in_order(pattern, groups, CandleOrder::OldestFirst)
}

fn pattern(text: &str) -> GeometryPattern {
    text.parse().unwrap()
}

fn project_range(pattern: &GeometryPattern, from: usize, to: usize) -> GeometryPattern {
    project(pattern, &(from..to).collect::<Vec<_>>()).unwrap()
}

#[test]
fn projection_preserves_all_surviving_comparisons_and_composes() {
    let g = pattern("g1:o:0,1,2,3,u;4,5,6,7,d;1,2,5,6,u");
    let p = project(&g, &[0, 2]).unwrap();
    assert_eq!(p.to_string(), "g1:o:0,1,2,3,u;1,2,4,5,u");
    assert_eq!(project(&g, &[0, 1, 2]).unwrap(), g);
    assert_eq!(project(&p, &[1]).unwrap(), project(&g, &[2]).unwrap());
    assert_eq!(project(&g, &[]).unwrap().to_string(), "g1:o:");
    assert_eq!(
        forget_orientation(&g).unwrap().mode(),
        GeometryMode::Unoriented
    );
    assert_eq!(
        project(&forget_orientation(&g).unwrap(), &[0, 2]).unwrap(),
        forget_orientation(&p).unwrap()
    );
    assert!(project(&g, &[1, 1]).is_err());
    assert!(project(&g, &[2, 1]).is_err());
    assert!(project(&g, &[3]).is_err());
}

#[test]
fn composition_of_full_local_candles_has_delannoy_count() {
    let a = pattern("g1:u:0,1,2,3");
    let b = pattern("g1:u:0,1,2,3");
    assert_eq!(composition_count(&a, &b, 0).unwrap(), 321);
    assert!(compose_overlap(&a, &b, 0, 320).is_err());
    let completions = compose_overlap(&a, &b, 0, 321).unwrap();
    assert_eq!(completions.len(), 321);
    let unique: HashSet<_> = completions.iter().collect();
    assert_eq!(unique.len(), 321);
    for g in completions {
        assert_eq!(project(&g, &[0]).unwrap(), a);
        assert_eq!(project(&g, &[1]).unwrap(), b);
        assert_eq!(g.len(), 2);
    }
    let oriented = pattern("g1:o:0,1,2,3,d");
    assert_eq!(composition_count(&oriented, &oriented, 0).unwrap(), 321);
    let extensions = append_one(&oriented, &oriented, 321).unwrap();
    assert_eq!(extensions.len(), 321);
    assert!(extensions
        .iter()
        .all(|g| g.directions() == Some(&[BodyDirection::Down, BodyDirection::Down][..])));
    assert_eq!(prepend_one(&oriented, &oriented, 321).unwrap(), extensions);
    assert!(append_one(&a, &completions_dummy(), 10).is_err());
    assert!(prepend_one(&completions_dummy(), &a, 10).is_err());
}

fn completions_dummy() -> GeometryPattern {
    pattern("g1:u:0,0,0,0;1,1,1,1")
}

#[test]
fn zero_overlap_counts_match_delannoy_for_every_local_level_count() {
    // Independent closed-table control for 1, 2, 3, and 4 distinct levels.
    let shapes = [
        pattern("g1:u:0,0,0,0"),
        pattern("g1:u:0,0,1,1"),
        pattern("g1:u:0,0,1,2"),
        pattern("g1:u:0,1,2,3"),
    ];
    let delannoy = [
        [3u128, 5, 7, 9],
        [5, 13, 25, 41],
        [7, 25, 63, 129],
        [9, 41, 129, 321],
    ];
    for (i, a) in shapes.iter().enumerate() {
        for (j, b) in shapes.iter().enumerate() {
            assert_eq!(composition_count(a, b, 0).unwrap(), delannoy[i][j]);
        }
    }
}

#[test]
fn long_single_completion_uses_bounded_heap_not_recursive_call_stack() {
    let n = 3000usize;
    let rows = (0..n)
        .map(|i| [4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3])
        .collect();
    let g = GeometryPattern::new(rows, Some(vec![BodyDirection::Up; n])).unwrap();
    let empty = pattern("g1:o:");
    assert_eq!(composition_count(&g, &empty, 0).unwrap(), 1);
    assert_eq!(compose_overlap(&g, &empty, 0, 1).unwrap(), vec![g]);
}

#[test]
fn incompatible_overlaps_return_zero_and_bad_inputs_are_rejected() {
    let first = pattern("g1:u:0,0,0,0;1,1,1,1");
    let matching = pattern("g1:u:0,0,0,0;1,1,1,1");
    let incompatible = pattern("g1:u:0,0,1,1;0,0,1,1");
    assert!(overlap_compatible(&first, &matching, 1).unwrap());
    assert!(!overlap_compatible(&first, &incompatible, 1).unwrap());
    assert_eq!(composition_count(&first, &incompatible, 1).unwrap(), 0);
    assert!(compose_overlap(&first, &incompatible, 1, 0)
        .unwrap()
        .is_empty());
    assert!(overlap_compatible(&first, &matching, 3).is_err());
    assert!(overlap_compatible(&first, &pattern("g1:o:0,0,0,0,z"), 0).is_err());
}

#[test]
fn the_shared_candle_does_not_determine_nonadjacent_order() {
    let first = GeometryPattern::from_endpoints(
        &[
            [10., 11., 12., 13.],
            [20., 21., 22., 23.],
            [14., 15., 16., 17.],
        ],
        GeometryMode::Unoriented,
        None,
    )
    .unwrap();
    let second = GeometryPattern::from_endpoints(
        &[[10., 11., 12., 13.], [20., 21., 22., 23.], [6., 7., 8., 9.]],
        GeometryMode::Unoriented,
        None,
    )
    .unwrap();
    assert_ne!(first, second);
    let left = project(&first, &[0, 1]).unwrap();
    let right = project(&first, &[1, 2]).unwrap();
    assert_eq!(left, project(&second, &[0, 1]).unwrap());
    assert_eq!(right, project(&second, &[1, 2]).unwrap());
    let completions: HashSet<_> = compose_overlap(&left, &right, 1, 1000)
        .unwrap()
        .into_iter()
        .collect();
    assert!(completions.contains(&first));
    assert!(completions.contains(&second));
    assert_eq!(
        completions.len() as u128,
        composition_count(&left, &right, 1).unwrap()
    );
    for g in completions {
        assert_eq!(project_range(&g, 0, 2), left);
        assert_eq!(project_range(&g, 1, 3), right);
    }
}

#[test]
fn flat_candle_three_way_composition_matches_independent_numeric_oracle() {
    // Enumerate all realizations of three flat candles over four numeric
    // levels. Every weak order of three variables embeds in four levels.
    // This oracle has no dependency on the composition recurrence.
    let mut oracle: HashMap<(GeometryPattern, GeometryPattern), HashSet<GeometryPattern>> =
        HashMap::new();
    for a in 0..4 {
        for b in 0..4 {
            for c in 0..4 {
                let data = [[a as f64; 4], [b as f64; 4], [c as f64; 4]];
                let global = GeometryPattern::from_ohlc(&data, GeometryMode::Oriented).unwrap();
                let left = project_range(&global, 0, 2);
                let right = project_range(&global, 1, 3);
                oracle.entry((left, right)).or_default().insert(global);
            }
        }
    }
    assert_eq!(oracle.len(), 9); // relation of A/B crossed with B/C
    for ((left, right), expected) in oracle {
        let found: HashSet<_> = compose_overlap(&left, &right, 1, 100)
            .unwrap()
            .into_iter()
            .collect();
        assert_eq!(found, expected, "left={} right={}", left, right);
        assert_eq!(
            composition_count(&left, &right, 1).unwrap(),
            expected.len() as u128
        );
    }
}

#[test]
fn composition_is_associative_as_a_set_of_completions() {
    let rows = [
        [1., 1., 1., 1.],
        [3., 3., 3., 3.],
        [2., 2., 2., 2.],
        [4., 4., 4., 4.],
    ];
    let four = GeometryPattern::from_ohlc(&rows, GeometryMode::Oriented).unwrap();
    let a = project_range(&four, 0, 2);
    let b = project_range(&four, 1, 3);
    let c = project_range(&four, 2, 4);
    let mut left = HashSet::new();
    for ab in compose_overlap(&a, &b, 1, 100).unwrap() {
        left.extend(compose_overlap(&ab, &c, 1, 100).unwrap());
    }
    let mut right = HashSet::new();
    for bc in compose_overlap(&b, &c, 1, 100).unwrap() {
        right.extend(compose_overlap(&a, &bc, 1, 100).unwrap());
    }
    assert_eq!(left, right);
    assert!(left.contains(&four));
}

fn numeric_aggregate(rows: &[[f64; 4]], groups: &[usize]) -> Vec<[f64; 4]> {
    let mut offset = 0;
    groups
        .iter()
        .map(|&size| {
            let block = &rows[offset..offset + size];
            offset += size;
            [
                block[0][0],
                block.iter().map(|x| x[1]).fold(f64::NEG_INFINITY, f64::max),
                block.iter().map(|x| x[2]).fold(f64::INFINITY, f64::min),
                block.last().unwrap()[3],
            ]
        })
        .collect()
}

fn rand_u32(seed: &mut u64) -> u32 {
    *seed ^= *seed << 13;
    *seed ^= *seed >> 7;
    *seed ^= *seed << 17;
    (*seed >> 12) as u32
}

#[test]
fn exact_aggregation_matches_numeric_ohlc_and_composes_across_scales() {
    let mut seed = 0x0b5e_0f1a_2026_100au64;
    for _ in 0..1500 {
        let rows: Vec<[f64; 4]> = (0..8)
            .map(|_| {
                let open = (rand_u32(&mut seed) % 17) as f64 + 1.;
                let close = (rand_u32(&mut seed) % 17) as f64 + 1.;
                let high = open.max(close) + (rand_u32(&mut seed) % 3) as f64;
                let low = open.min(close) - (rand_u32(&mut seed) % 3) as f64;
                [open, high, low, close]
            })
            .collect();
        let original = GeometryPattern::from_ohlc(&rows, GeometryMode::Oriented).unwrap();
        for size in [1, 2, 4, 8] {
            let expected = GeometryPattern::from_ohlc(
                &numeric_aggregate(&rows, &vec![size; rows.len() / size]),
                GeometryMode::Oriented,
            )
            .unwrap();
            assert_eq!(aggregate_blocks(&original, size).unwrap(), expected);
        }
        let groups = [1, 3, 2, 2];
        let expected =
            GeometryPattern::from_ohlc(&numeric_aggregate(&rows, &groups), GeometryMode::Oriented)
                .unwrap();
        assert_eq!(aggregate_partition(&original, &groups).unwrap(), expected);

        // The direction study stores current-first windows; the exact same
        // operation must work without silently reversing opens and closes.
        let newest_first: Vec<_> = rows.iter().copied().rev().collect();
        let reversed = GeometryPattern::from_ohlc(&newest_first, GeometryMode::Oriented).unwrap();
        let expected_reversed: Vec<_> = numeric_aggregate(&rows, &[2, 2, 2, 2])
            .into_iter()
            .rev()
            .collect();
        let expected_reversed =
            GeometryPattern::from_ohlc(&expected_reversed, GeometryMode::Oriented).unwrap();
        assert_eq!(
            aggregate_blocks_in_order(&reversed, 2, CandleOrder::NewestFirst).unwrap(),
            expected_reversed
        );
        let twice_reversed = aggregate_blocks_in_order(
            &aggregate_blocks_in_order(&reversed, 2, CandleOrder::NewestFirst).unwrap(),
            2,
            CandleOrder::NewestFirst,
        )
        .unwrap();
        assert_eq!(
            twice_reversed,
            aggregate_blocks_in_order(&reversed, 4, CandleOrder::NewestFirst).unwrap()
        );
        assert_eq!(
            aggregate_blocks(&aggregate_blocks(&original, 2).unwrap(), 2).unwrap(),
            aggregate_blocks(&original, 4).unwrap()
        );
        let adjusted: Vec<_> = rows.iter().map(|row| row.map(|v| v * 3. + 7.)).collect();
        assert_eq!(
            GeometryPattern::from_ohlc(&adjusted, GeometryMode::Oriented).unwrap(),
            original
        );
    }
}

#[test]
fn aggregation_does_not_infer_missing_orientations_or_accept_partial_groups() {
    let rows_a = [[1., 4., 0., 3.], [3., 4., 0., 1.]];
    let rows_b = [[3., 4., 0., 1.], [3., 4., 0., 1.]];
    let u_a = GeometryPattern::from_ohlc(&rows_a, GeometryMode::Unoriented).unwrap();
    let u_b = GeometryPattern::from_ohlc(&rows_b, GeometryMode::Unoriented).unwrap();
    assert_eq!(u_a, u_b);
    assert!(aggregate_blocks(&u_a, 2).is_err());
    let a = GeometryPattern::from_ohlc(&rows_a, GeometryMode::Oriented).unwrap();
    let b = GeometryPattern::from_ohlc(&rows_b, GeometryMode::Oriented).unwrap();
    assert_ne!(
        aggregate_blocks(&a, 2).unwrap(),
        aggregate_blocks(&b, 2).unwrap()
    );
    assert!(aggregate_blocks(&a, 0).is_err());
    assert!(aggregate_blocks(&a, 3).is_err());
    assert!(aggregate_partition(&a, &[1]).is_err());
    assert!(aggregate_partition(&a, &[1, 0, 1]).is_err());
    assert_eq!(
        aggregate_blocks(&pattern("g1:o:"), 3).unwrap(),
        pattern("g1:o:")
    );
}

#[test]
fn empty_patterns_have_defined_projection_and_composition_laws() {
    let empty = pattern("g1:u:");
    let one = pattern("g1:u:0,0,0,0");
    assert_eq!(
        compose_overlap(&empty, &one, 0, 1).unwrap(),
        vec![one.clone()]
    );
    assert_eq!(
        compose_overlap(&one, &empty, 0, 1).unwrap(),
        vec![one.clone()]
    );
    assert_eq!(compose_overlap(&empty, &empty, 0, 1).unwrap(), vec![empty]);
}
