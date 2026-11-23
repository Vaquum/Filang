use filang::geometry::{
    count_domain_decimal_with_dimensions,
    explore::{declared_count, distance, encode_drawing, Bar, Counts, Reading, Recording},
    Counters, Dimension, DimensionSet, GeometryMode, GeometryPattern,
};
use std::collections::HashMap;

fn recording() -> Recording {
    Recording::new(
        (0..110)
            .map(|i| {
                if i == 16 || i == 33 || i == 88 {
                    return None;
                }
                let o = (i * 13 % 31) as f64;
                let c = (i * 7 % 31) as f64;
                let volume = (i * 3 % 7) as f64;
                let taker_buy = volume * (i % 4) as f64 / 4.0;
                let trades = (i * 5 % 11) as f64;
                Some(
                    Bar::new(
                        [o, o.max(c) + 1.0, o.min(c) - 1.0, c],
                        (i != 60).then(|| Counters::new(volume, taker_buy, trades).unwrap()),
                    )
                    .unwrap(),
                )
            })
            .collect(),
    )
    .unwrap()
}

fn sets() -> impl Iterator<Item = DimensionSet> {
    (0..32).map(|bits| {
        Dimension::ALL
            .into_iter()
            .enumerate()
            .filter(|(i, _)| bits & (1 << i) != 0)
            .fold(DimensionSet::NONE, |set, (_, axis)| set.with(axis))
    })
}

#[test]
fn observed_postings_equal_direct_windows_with_every_set_of_dimensions() {
    let tape = recording();
    for width in [1, 4, 10, 11, 30, 112] {
        let mut prepared = tape.prepare(width).unwrap();
        for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
            for reading in [Reading::Recorded, Reading::Chained] {
                for dimensions in sets() {
                    let mut direct: HashMap<GeometryPattern, Vec<u32>> = HashMap::new();
                    let mut unknown = 0;
                    for end in 0..tape.len() {
                        match tape
                            .pattern_at(end, width, mode, reading, dimensions)
                            .unwrap()
                        {
                            Some(pattern) => direct.entry(pattern).or_default().push(end as u32),
                            None => unknown += 1,
                        }
                    }
                    for (pattern, slots) in direct {
                        assert_eq!(
                            prepared.counts(&pattern, reading).unwrap(),
                            Counts {
                                matched: slots.len(),
                                false_count: tape.len() - unknown - slots.len(),
                                unknown,
                            },
                        );
                        let want: Vec<_> = slots.into_iter().filter(|i| *i >= 30).take(3).collect();
                        assert_eq!(prepared.positions(&pattern, reading, 30, 3).unwrap(), want);
                    }
                    let rows = vec![[0.0; 4]; width];
                    let values = vec![0.0; width];
                    let axes: Vec<_> = dimensions
                        .iter()
                        .map(|axis| (axis, values.as_slice()))
                        .collect();
                    let flat = encode_drawing(&rows, mode, reading, &axes).unwrap();
                    assert_eq!(
                        prepared.counts(&flat, reading).unwrap(),
                        Counts {
                            matched: 0,
                            false_count: tape.len() - unknown,
                            unknown
                        },
                    );
                }
            }
        }
    }
}

#[test]
fn declared_domain_multiplies_exact_counts_and_supports_wide_windows() {
    for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
        for n in 1..=10 {
            for dimensions in sets() {
                assert_eq!(
                    declared_count(n, mode, dimensions).unwrap(),
                    count_domain_decimal_with_dimensions(n, mode, dimensions).unwrap(),
                );
            }
        }
    }
    let all = declared_count(30, GeometryMode::Oriented, DimensionSet::all()).unwrap();
    assert!(all.len() > 300 && all.chars().all(|c| c.is_ascii_digit()));
}

#[test]
fn distance_counts_ties_reversals_and_orientation_in_half_flips() {
    let up: GeometryPattern = "g1:o:0,1,2,3,u|delta:1/0".parse().unwrap();
    let down: GeometryPattern = "g1:o:0,1,2,3,d|delta:1/0".parse().unwrap();
    let flat_axis: GeometryPattern = "g1:o:0,1,2,3,u|delta:0/0".parse().unwrap();
    let selling: GeometryPattern = "g1:o:0,1,2,3,u|delta:0/1".parse().unwrap();
    assert_eq!(distance(&up, &up).unwrap(), 0);
    assert_eq!(distance(&up, &down).unwrap(), 2);
    assert_eq!(distance(&up, &flat_axis).unwrap(), 1);
    assert_eq!(distance(&up, &selling).unwrap(), 2);
    assert!(distance(&up, &up.price()).is_err());
}
