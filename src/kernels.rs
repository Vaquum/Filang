//! Runtime-dispatched leaf kernels. No FMA/reassociation or reduced precision.
//! Every unsafe entry has a checked architecture feature and slice-length boundary.
use crate::{backtest::Rule, lang::Op, Result};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Backend {
    Scalar,
    Neon,
    Avx2,
}
impl Backend {
    pub fn resolve(name: &str) -> Result<Self> {
        let detected = {
            #[cfg(target_arch = "aarch64")]
            {
                if std::arch::is_aarch64_feature_detected!("neon") {
                    Self::Neon
                } else {
                    Self::Scalar
                }
            }
            #[cfg(target_arch = "x86_64")]
            {
                if std::arch::is_x86_feature_detected!("avx2") {
                    Self::Avx2
                } else {
                    Self::Scalar
                }
            }
            #[cfg(not(any(target_arch = "aarch64", target_arch = "x86_64")))]
            {
                Self::Scalar
            }
        };
        match name {
            "auto" => Ok(detected),
            "scalar" => Ok(Self::Scalar),
            "neon" if detected == Self::Neon => Ok(detected),
            "avx2" if detected == Self::Avx2 => Ok(detected),
            _ => Err(format!("unsupported or unavailable kernel backend: {name}")),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Scalar => "scalar",
            Self::Neon => "neon",
            Self::Avx2 => "avx2",
        }
    }
    fn checked(self) -> Result<()> {
        Self::resolve(self.name()).map(|_| ())
    }
}
fn scalar_binary(op: &Op, x: f64, y: f64) -> f64 {
    if !x.is_finite() || !y.is_finite() {
        return f64::NAN;
    }
    let v = match op {
        Op::Add => x + y,
        Op::Sub => x - y,
        Op::Mul => x * y,
        Op::Div if y.abs() > 1e-12 => x / y,
        _ => f64::NAN,
    };
    if v.is_finite() {
        v
    } else {
        f64::NAN
    }
}
pub fn binary(op: &Op, a: &[f64], b: &[f64], backend: Backend) -> Result<Vec<f64>> {
    if a.len() != b.len() || !matches!(op, Op::Add | Op::Sub | Op::Mul | Op::Div) {
        return Err("binary kernel contract".into());
    }
    backend.checked()?;
    let mut out = vec![f64::NAN; a.len()];
    let mut done = 0;
    #[cfg(target_arch = "aarch64")]
    if backend == Backend::Neon {
        done = unsafe { neon_binary(op, a, b, &mut out) };
    }
    #[cfg(target_arch = "x86_64")]
    if backend == Backend::Avx2 {
        done = unsafe { avx_binary(op, a, b, &mut out) };
    }
    for i in done..a.len() {
        out[i] = scalar_binary(op, a[i], b[i]);
    }
    Ok(out)
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn neon_binary(op: &Op, a: &[f64], b: &[f64], out: &mut [f64]) -> usize {
    use std::arch::aarch64::*;
    let mut i = 0;
    let max = vdupq_n_f64(f64::MAX);
    let nan = vdupq_n_f64(f64::NAN);
    let eps = vdupq_n_f64(1e-12);
    while i + 2 <= a.len() {
        let x = vld1q_f64(a.as_ptr().add(i));
        let y = vld1q_f64(b.as_ptr().add(i));
        let mut valid = vandq_u64(vcleq_f64(vabsq_f64(x), max), vcleq_f64(vabsq_f64(y), max));
        let v = match op {
            Op::Add => vaddq_f64(x, y),
            Op::Sub => vsubq_f64(x, y),
            Op::Mul => vmulq_f64(x, y),
            _ => {
                valid = vandq_u64(valid, vcgtq_f64(vabsq_f64(y), eps));
                vdivq_f64(x, y)
            }
        };
        valid = vandq_u64(valid, vcleq_f64(vabsq_f64(v), max));
        vst1q_f64(out.as_mut_ptr().add(i), vbslq_f64(valid, v, nan));
        i += 2;
    }
    i
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn avx_binary(op: &Op, a: &[f64], b: &[f64], out: &mut [f64]) -> usize {
    use std::arch::x86_64::*;
    let mut i = 0;
    let sign = _mm256_set1_pd(-0.0);
    let max = _mm256_set1_pd(f64::MAX);
    let nan = _mm256_set1_pd(f64::NAN);
    while i + 4 <= a.len() {
        let x = _mm256_loadu_pd(a.as_ptr().add(i));
        let y = _mm256_loadu_pd(b.as_ptr().add(i));
        let mut valid = _mm256_and_pd(
            _mm256_cmp_pd::<_CMP_LE_OQ>(_mm256_andnot_pd(sign, x), max),
            _mm256_cmp_pd::<_CMP_LE_OQ>(_mm256_andnot_pd(sign, y), max),
        );
        let v = match op {
            Op::Add => _mm256_add_pd(x, y),
            Op::Sub => _mm256_sub_pd(x, y),
            Op::Mul => _mm256_mul_pd(x, y),
            _ => {
                valid = _mm256_and_pd(
                    valid,
                    _mm256_cmp_pd::<_CMP_GT_OQ>(_mm256_andnot_pd(sign, y), _mm256_set1_pd(1e-12)),
                );
                _mm256_div_pd(x, y)
            }
        };
        valid = _mm256_and_pd(
            valid,
            _mm256_cmp_pd::<_CMP_LE_OQ>(_mm256_andnot_pd(sign, v), max),
        );
        _mm256_storeu_pd(out.as_mut_ptr().add(i), _mm256_blendv_pd(nan, v, valid));
        i += 4;
    }
    i
}
/// Packed bits in chronological order; padding is always zero.
pub fn threshold(x: &[f64], rule: Rule, backend: Backend) -> Result<Vec<u64>> {
    if !rule.threshold.is_finite() {
        return Err("nonfinite threshold".into());
    }
    backend.checked()?;
    let mut bits = vec![0u64; (x.len() + 63) / 64];
    let mut done = 0;
    #[cfg(target_arch = "aarch64")]
    if backend == Backend::Neon {
        done = unsafe { neon_threshold(x, rule, &mut bits) };
    }
    #[cfg(target_arch = "x86_64")]
    if backend == Backend::Avx2 {
        done = unsafe { avx_threshold(x, rule, &mut bits) };
    }
    for i in done..x.len() {
        if rule.active(x[i]) {
            bits[i / 64] |= 1 << (i % 64);
        }
    }
    Ok(bits)
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn neon_threshold(x: &[f64], r: Rule, out: &mut [u64]) -> usize {
    use std::arch::aarch64::*;
    let mut i = 0;
    let threshold = vdupq_n_f64(r.threshold);
    let max = vdupq_n_f64(f64::MAX);
    while i + 2 <= x.len() {
        let v = vld1q_f64(x.as_ptr().add(i));
        let cmp = if r.greater {
            vcgtq_f64(v, threshold)
        } else {
            vcltq_f64(v, threshold)
        };
        let m = vandq_u64(cmp, vcleq_f64(vabsq_f64(v), max));
        let b = (vgetq_lane_u64::<0>(m) & 1) | ((vgetq_lane_u64::<1>(m) & 1) << 1);
        out[i / 64] |= b << (i % 64);
        i += 2;
    }
    i
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn avx_threshold(x: &[f64], r: Rule, out: &mut [u64]) -> usize {
    use std::arch::x86_64::*;
    let mut i = 0;
    let threshold = _mm256_set1_pd(r.threshold);
    let max = _mm256_set1_pd(f64::MAX);
    let sign = _mm256_set1_pd(-0.0);
    while i + 4 <= x.len() {
        let v = _mm256_loadu_pd(x.as_ptr().add(i));
        let cmp = if r.greater {
            _mm256_cmp_pd::<_CMP_GT_OQ>(v, threshold)
        } else {
            _mm256_cmp_pd::<_CMP_LT_OQ>(v, threshold)
        };
        let mask = _mm256_and_pd(
            cmp,
            _mm256_cmp_pd::<_CMP_LE_OQ>(_mm256_andnot_pd(sign, v), max),
        );
        out[i / 64] |= (_mm256_movemask_pd(mask) as u64) << (i % 64);
        i += 4;
    }
    i
}
pub fn intersection(a: &[u64], b: &[u64], backend: Backend) -> Result<u64> {
    if a.len() != b.len() {
        return Err("bitmap length mismatch".into());
    }
    backend.checked()?;
    let (mut sum, mut done) = (0u64, 0);
    #[cfg(target_arch = "aarch64")]
    if backend == Backend::Neon {
        (sum, done) = unsafe { neon_intersection(a, b) };
    }
    #[cfg(target_arch = "x86_64")]
    if backend == Backend::Avx2 {
        (sum, done) = unsafe { avx_intersection(a, b) };
    }
    for i in done..a.len() {
        sum += (a[i] & b[i]).count_ones() as u64;
    }
    Ok(sum)
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn neon_intersection(a: &[u64], b: &[u64]) -> (u64, usize) {
    use std::arch::aarch64::*;
    let (mut sum, mut i) = (0, 0);
    while i + 2 <= a.len() {
        let v = vandq_u64(vld1q_u64(a.as_ptr().add(i)), vld1q_u64(b.as_ptr().add(i)));
        sum += vaddvq_u8(vcntq_u8(vreinterpretq_u8_u64(v))) as u64;
        i += 2;
    }
    (sum, i)
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn avx_intersection(a: &[u64], b: &[u64]) -> (u64, usize) {
    use std::arch::x86_64::*;
    let (mut sum, mut i) = (0, 0);
    let mut lanes = [0u64; 4];
    while i + 4 <= a.len() {
        let v = _mm256_and_si256(
            _mm256_loadu_si256(a.as_ptr().add(i).cast()),
            _mm256_loadu_si256(b.as_ptr().add(i).cast()),
        );
        _mm256_storeu_si256(lanes.as_mut_ptr().cast(), v);
        sum += lanes.iter().map(|w| w.count_ones() as u64).sum::<u64>();
        i += 4;
    }
    (sum, i)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn simd_matches_scalar_boundaries() {
        let backend = Backend::resolve("auto").unwrap();
        eprintln!("tested native backend {}", backend.name());
        for n in [0, 1, 2, 3, 4, 5, 63, 64, 65, 129] {
            let special = [
                0.0,
                -0.0,
                f64::NAN,
                f64::INFINITY,
                f64::NEG_INFINITY,
                1e-12,
                -1e-12,
                1.0000001e-12,
                f64::MAX,
                -f64::MAX,
                3.1,
                -2.5,
            ];
            let a = (0..n)
                .map(|i| special[i % special.len()])
                .collect::<Vec<_>>();
            let b = (0..n)
                .map(|i| special[(i * 7 + 3) % special.len()])
                .collect::<Vec<_>>();
            for op in [Op::Add, Op::Sub, Op::Mul, Op::Div] {
                let s = binary(&op, &a, &b, Backend::Scalar).unwrap();
                let v = binary(&op, &a, &b, backend).unwrap();
                for (x, y) in s.iter().zip(v) {
                    assert!(
                        x.to_bits() == y.to_bits() || (x.is_nan() && y.is_nan()),
                        "{op:?} {x} {y}"
                    );
                }
            }
            for greater in [false, true] {
                for threshold_value in [-1e-12, 0.0, 1e-12, 2.0] {
                    let r = Rule {
                        greater,
                        threshold: threshold_value,
                    };
                    let s = threshold(&a, r, Backend::Scalar).unwrap();
                    let v = threshold(&a, r, backend).unwrap();
                    assert_eq!(s, v);
                    assert_eq!(
                        intersection(&s, &v, backend).unwrap(),
                        s.iter().map(|w| w.count_ones() as u64).sum::<u64>()
                    );
                }
            }
        }
        assert!(Backend::resolve("not-an-isa").is_err());
    }
}
