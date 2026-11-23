// Build this probe against each release library with the same Rust toolchain.
use filang::geometry::{
    explore::{encode_drawing, Bar, Reading, Recording},
    Counters, Dimension, DimensionSet, GeometryMode,
};
use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    hint::black_box,
    io::{BufRead, BufReader},
    time::Instant,
};

fn dense() -> Recording {
    let quote = Counters::new(16.0, 8.0, 4.0).unwrap();
    Recording::new(
        (0..1_000_000)
            .map(|i| {
                (i % 8191 != 0).then(|| Bar::new([10.0, 11.0, 9.0, 10.0], Some(quote)).unwrap())
            })
            .collect(),
    )
    .unwrap()
}

fn cube(path: &str) -> Recording {
    let mut rows = Vec::new();
    let mut previous = None;
    let file = BufReader::new(std::fs::File::open(path).unwrap());
    for row in file.lines().skip(1) {
        let row = row.unwrap();
        let cells: Vec<_> = row.split(',').collect();
        assert_eq!(cells.len(), 9);
        let timestamp: u64 = cells[0].parse().unwrap();
        if let Some(previous) = previous {
            assert_eq!(timestamp, previous + 900_000);
        }
        previous = Some(timestamp);
        let read = |i: usize| cells[i].parse::<f64>().unwrap();
        let counters = Counters::new(read(6), read(7), read(8)).unwrap();
        rows.push(Some(
            Bar::new([read(1), read(2), read(3), read(4)], Some(counters)).unwrap(),
        ));
    }
    assert_eq!(rows.len(), 66_000);
    Recording::new(rows).unwrap()
}

fn main() {
    let arguments: Vec<_> = std::env::args().collect();
    let is_dense = arguments[1] == "dense";
    let width = if is_dense {
        24
    } else {
        arguments[1].parse().unwrap()
    };
    let recording = if is_dense {
        dense()
    } else {
        cube(&arguments[2])
    };
    let mode = GeometryMode::Oriented;
    let reading = Reading::Chained;
    let dimensions = DimensionSet::all();
    let zeros = vec![0.0; width];
    let absent = encode_drawing(
        &vec![[0.0; 4]; width],
        mode,
        reading,
        &Dimension::ALL.map(|axis| (axis, zeros.as_slice())),
    )
    .unwrap();
    let mut corpus: Vec<_> = if is_dense {
        vec![recording
            .pattern_at(100, width, mode, reading, dimensions)
            .unwrap()
            .unwrap()]
    } else {
        (width..recording.len())
            .step_by(251)
            .filter_map(|end| {
                recording
                    .pattern_at(end, width, mode, reading, dimensions)
                    .unwrap()
            })
            .take(256)
            .collect()
    };
    corpus.push(absent);
    let mut index = recording.prepare(width).unwrap();
    let start = Instant::now();
    index.prepare(mode, reading, dimensions).unwrap();
    let prepare_ms = start.elapsed().as_secs_f64() * 1000.0;

    let mut receipt = DefaultHasher::new();
    let expected: Vec<_> = corpus
        .iter()
        .map(|code| {
            let counts = index.counts(code, reading).unwrap();
            code.hash(&mut receipt);
            (counts.matched, counts.false_count, counts.unknown).hash(&mut receipt);
            for (start, limit) in [(0, 21), (63, 69), (64, 64), (recording.len() - 41, 128)] {
                index
                    .positions(code, reading, start, limit)
                    .unwrap()
                    .hash(&mut receipt);
                index
                    .classify(code, reading, start, limit)
                    .unwrap()
                    .hash(&mut receipt);
            }
            counts
        })
        .collect();
    assert_eq!(expected.last().unwrap().matched, 0);
    if is_dense {
        assert_eq!(expected[0].matched, 997_048);
        assert_eq!(expected[0].false_count, 0);
        assert_eq!(expected[0].unknown, 2_952);
    }
    let rounds = if is_dense { 21 } else { 80 };
    let start = Instant::now();
    for _ in 0..rounds {
        for (code, want) in corpus.iter().zip(&expected) {
            let got = black_box(index.counts(black_box(code), reading).unwrap());
            assert_eq!(&got, want);
        }
    }
    let count_ms = start.elapsed().as_secs_f64() * 1000.0 / rounds as f64;
    println!(
        "{{\"width\":{width},\"slots\":{},\"queries\":{},\"prepare_ms\":{prepare_ms},\"count_ms\":{count_ms},\"receipt\":\"{:016x}\"}}",
        recording.len(), corpus.len(), receipt.finish()
    );
}
