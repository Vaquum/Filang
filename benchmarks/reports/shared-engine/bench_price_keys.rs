//! Key-encoding throughput with every dimension off. This file uses only the
//! 0.9 API, so the same source builds against the baseline and the branch.
//! It encodes every contiguous window of a six-column recording, current
//! candle first, and folds the key words into a digest: equal digests mean
//! equal keys on every window.
//!
//! bench_price_keys <csv> <interval-seconds> <bars> <mode> <passes>
use filang::{
    data::Data,
    geometry::{GeometryEncoder, GeometryMode},
};
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let data = Data::read(&args[1], args[2].parse().unwrap()).unwrap();
    let bars: usize = args[3].parse().unwrap();
    let mode = GeometryMode::parse(&args[4]).unwrap();
    let passes: usize = args[5].parse().unwrap();
    let mut encoder = GeometryEncoder::new(bars, mode).unwrap();
    let mut rows = [[0.0f64; 4]; 10];
    let mut digest = 0xcbf2_9ce4_8422_2325u64;
    let mut windows = 0u64;
    let began = Instant::now();
    for _ in 0..passes {
        for t in bars - 1..data.len() {
            for (lag, row) in rows[..bars].iter_mut().enumerate() {
                let index = t - lag;
                for (value, column) in row.iter_mut().zip(&data.columns) {
                    *value = column[index];
                }
            }
            let key = encoder.encode_key_ohlc(&rows[..bars]).unwrap();
            for word in key.words() {
                digest = (digest ^ word).wrapping_mul(0x0000_0100_0000_01b3);
            }
            windows += 1;
        }
    }
    let seconds = began.elapsed().as_secs_f64();
    println!(
        "{{\"bars\":{bars},\"mode\":\"{mode}\",\"passes\":{passes},\"windows\":{windows},\"seconds\":{seconds:.9},\"windows_per_second\":{:.1},\"key_digest\":\"{digest:016x}\"}}",
        windows as f64 / seconds
    );
}
