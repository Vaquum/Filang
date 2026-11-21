use super::tape::Tape;
use crate::rules::Mask;

/// Twice the median avoids tick rounding for even windows.
pub(super) fn prior_medians(tape: &Tape, window: usize) -> Vec<i64> {
    let mut sorted = Vec::with_capacity(window);
    let mut run = 0;
    let span = |i: usize| tape.bars[i].map(|b| b.h - b.l);
    (0..tape.bars.len())
        .map(|i| {
            let median = if run >= window {
                sorted[(window - 1) / 2] + sorted[window / 2]
            } else {
                0
            };
            match span(i) {
                Some(x) => {
                    if run >= window {
                        let leaving = span(i - window).expect("complete median window");
                        let index = sorted
                            .binary_search(&leaving)
                            .expect("median window member");
                        sorted.remove(index);
                    }
                    let index = sorted.partition_point(|y| *y < x);
                    sorted.insert(index, x);
                    run += 1;
                }
                None => {
                    sorted.clear();
                    run = 0;
                }
            }
            median
        })
        .collect()
}

/// Each breach can contribute only its first strict recovery. Several
/// breaches can prove one occurrence. Keep the nearest proven witness.
pub(super) fn reclaims(
    tape: &Tape,
    levels: &[i64],
    min: usize,
    max: usize,
    high: bool,
) -> (Mask, Vec<u32>) {
    let n = tape.bars.len();
    let mut mask = Mask::empty(n);
    let mut breaches = vec![u32::MAX; n];
    let sign = if high { -1 } else { 1 };
    for (i, witness) in breaches.iter_mut().enumerate() {
        let current = match tape.bars[i] {
            Some(bar) => bar.c * sign,
            None => continue,
        };
        let (mut earlier, mut gap, mut unknown) = (i64::MIN, false, false);
        for lag in 0..=max {
            let j = match i.checked_sub(lag) {
                Some(j) => j,
                None => {
                    if earlier < current {
                        unknown = true;
                    }
                    break;
                }
            };
            if lag > 0 {
                if let Some(b) = tape.bars[j] {
                    earlier = earlier.max(b.c * sign);
                } else {
                    gap = true;
                }
            }
            if lag < min {
                continue;
            }
            // Any older breach includes these same intervening closes.
            if earlier >= current {
                break;
            }
            if levels[j] == 0 {
                unknown = true;
                continue;
            }
            let level = levels[j] * sign;
            if current <= level || earlier > level {
                continue;
            }
            if let Some(b) = tape.bars[j] {
                let extreme = if high { -b.h } else { b.l };
                if b.o * sign < level || extreme >= level {
                    continue;
                }
                if !gap {
                    *witness = j as u32;
                    break;
                }
            }
            unknown = true;
        }
        let matched = *witness != u32::MAX;
        mask.set(i, matched, matched || !unknown);
    }
    (mask, breaches)
}
