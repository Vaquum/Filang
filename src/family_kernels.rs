//! Multi-output temporal kernels: share state, not merely identical arrays.
use crate::{kernels::Backend, Result};
/// Same operation order as the independent Mean/Std reference, one state machine.
pub fn moments_pair(a: &[f64], w: usize) -> (Vec<f64>, Vec<f64>) {
    let mut means = vec![f64::NAN; a.len()];
    let mut stds = means.clone();
    let (mut count, mut mean, mut m2) = (0usize, 0.0, 0.0);
    for t in 0..a.len() {
        if t >= w && a[t - w].is_finite() {
            let old = a[t - w];
            if count <= 1 {
                count = 0;
                mean = 0.0;
                m2 = 0.0;
            } else {
                let next = (count as f64 * mean - old) / (count - 1) as f64;
                m2 -= (old - mean) * (old - next);
                mean = next;
                count -= 1;
            }
        }
        if a[t].is_finite() {
            count += 1;
            let delta = a[t] - mean;
            mean += delta / count as f64;
            m2 += delta * (a[t] - mean);
        }
        if count == w {
            if t % 512 == 0 {
                mean = a[t + 1 - w..=t].iter().sum::<f64>() / w as f64;
                m2 = a[t + 1 - w..=t]
                    .iter()
                    .map(|x| (x - mean) * (x - mean))
                    .sum();
            }
            let sd = (m2 / w as f64).max(0.0).sqrt();
            if mean.is_finite() {
                means[t] = mean;
            }
            if sd.is_finite() {
                stds[t] = sd;
            }
        }
    }
    (means, stds)
}
/// Explicit rolling-total numerical profile. Unlike Welford this uses raw
/// first/second moments, with add/output/subtract ordering and a 1e-14 floor.
/// It is a selectable atom contract, not an optimization of Welford statistics.
pub fn raw_moments(a: &[f64], w: usize) -> (Vec<f64>, Vec<f64>) {
    let mut m = vec![f64::NAN; a.len()];
    let mut s = m.clone();
    let (mut run, mut sum, mut square) = (0usize, 0.0, 0.0);
    for t in 0..a.len() {
        if !a[t].is_finite() {
            run = 0;
            sum = 0.0;
            square = 0.0;
            continue;
        }
        run += 1;
        sum += a[t];
        square += a[t] * a[t];
        if run >= w {
            let mean = sum / w as f64;
            let second = square / w as f64;
            let old = a[t + 1 - w];
            sum -= old;
            square -= old * old;
            let variance = second - mean * mean;
            m[t] = mean;
            s[t] = if variance < 1e-14 {
                0.0
            } else {
                variance.sqrt()
            };
        }
    }
    (m, s)
}
/// A lane is a period/coefficient, never a different time step. Each lane keeps
/// the reference's chronological recurrence and SMA seed. No fused multiply-add.
pub fn recurrences(a: &[f64], specs: &[(usize, f64)], backend: Backend) -> Result<Vec<Vec<f64>>> {
    Backend::resolve(backend.name())?;
    if specs
        .iter()
        .any(|(w, alpha)| *w == 0 || !alpha.is_finite() || *alpha <= 0.0 || *alpha > 1.0)
    {
        return Err("invalid recurrence family".into());
    }
    let mut result = Vec::with_capacity(specs.len());
    for chunk in specs.chunks(4) {
        let mut out = vec![vec![f64::NAN; a.len()]; chunk.len()];
        let mut alpha = [0.0; 4];
        let mut beta = [0.0; 4];
        let mut state = [0.0; 4];
        for (i, &(_, v)) in chunk.iter().enumerate() {
            alpha[i] = v;
            beta[i] = 1.0 - v;
        }
        let max_w = chunk.iter().map(|p| p.0).max().unwrap();
        let (mut run, mut seed) = (0usize, 0.0);
        for (t, &x) in a.iter().enumerate() {
            if !x.is_finite() {
                run = 0;
                seed = 0.0;
                state = [0.0; 4];
                continue;
            }
            run += 1;
            if run <= max_w {
                seed += x;
                for (i, &(w, aa)) in chunk.iter().enumerate() {
                    match run.cmp(&w) {
                        std::cmp::Ordering::Equal => {
                            state[i] = seed / w as f64;
                            out[i][t] = state[i];
                        }
                        std::cmp::Ordering::Greater => {
                            state[i] = aa * x + (1.0 - aa) * state[i];
                            out[i][t] = state[i];
                        }
                        std::cmp::Ordering::Less => {}
                    }
                }
            } else {
                match backend {
                    #[cfg(target_arch = "aarch64")]
                    Backend::Neon => {
                        // SAFETY: checked ISA; four-element arrays; only complete lanes.
                        unsafe { step_neon(&mut state, &alpha, &beta, x) };
                    }
                    #[cfg(target_arch = "x86_64")]
                    Backend::Avx2 => {
                        // SAFETY: checked ISA; four-element arrays; unaligned loads/stores.
                        unsafe { step_avx(&mut state, &alpha, &beta, x) };
                    }
                    _ => {
                        for i in 0..4 {
                            state[i] = alpha[i] * x + beta[i] * state[i];
                        }
                    }
                }
                for i in 0..chunk.len() {
                    out[i][t] = state[i];
                }
            }
        }
        result.extend(out);
    }
    Ok(result)
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn step_neon(s: &mut [f64; 4], a: &[f64; 4], b: &[f64; 4], x: f64) {
    use std::arch::aarch64::*;
    let xx = vdupq_n_f64(x);
    for i in [0, 2] {
        let ax = vmulq_f64(vld1q_f64(a.as_ptr().add(i)), xx);
        let bs = vmulq_f64(vld1q_f64(b.as_ptr().add(i)), vld1q_f64(s.as_ptr().add(i)));
        vst1q_f64(s.as_mut_ptr().add(i), vaddq_f64(ax, bs));
    }
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn step_avx(s: &mut [f64; 4], a: &[f64; 4], b: &[f64; 4], x: f64) {
    use std::arch::x86_64::*;
    let ax = _mm256_mul_pd(_mm256_loadu_pd(a.as_ptr()), _mm256_set1_pd(x));
    let bs = _mm256_mul_pd(_mm256_loadu_pd(b.as_ptr()), _mm256_loadu_pd(s.as_ptr()));
    _mm256_storeu_pd(s.as_mut_ptr(), _mm256_add_pd(ax, bs));
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{data::Data, engine, lang::Op};
    fn check(a: &[f64], b: &[f64]) {
        for (x, y) in a.iter().zip(b) {
            assert!(
                x.to_bits() == y.to_bits() || (x.is_nan() && y.is_nan()),
                "{x} != {y}"
            );
        }
    }
    #[test]
    fn multi_output_matches_reference_bits() {
        let a = (0..1551)
            .map(|i| {
                if i % 401 == 0 {
                    f64::NAN
                } else {
                    100.0 + (i as f64 / 9.0).sin()
                }
            })
            .collect::<Vec<_>>();
        let d = Data {
            timestamps: vec![0; a.len()],
            columns: std::array::from_fn(|_| a.clone()),
            interval: 1,
            digest: "fixture".into(),
        };
        for w in [1, 2, 7, 31, 200] {
            let (m, s) = moments_pair(&a, w);
            check(&m, &engine::kernel(&Op::Mean(w), Some(&a), None, &d));
            check(&s, &engine::kernel(&Op::Std(w), Some(&a), None, &d));
        }
        let specs = [
            (1, 1.0),
            (2, 2.0 / 3.0),
            (7, 0.25),
            (20, 2.0 / 21.0),
            (31, 1.0 / 31.0),
        ];
        for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
            let out = recurrences(&a, &specs, backend).unwrap();
            for (i, &(w, _)) in specs.iter().enumerate() {
                let op = if i == 4 { Op::Wilder(w) } else { Op::Ema(w) };
                check(&out[i], &engine::kernel(&op, Some(&a), None, &d));
            }
        }
    }
}
