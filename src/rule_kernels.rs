//! Packed Boolean kernels. Validity is a separate plane; no fast-math.
use crate::{kernels::Backend, Result};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Logic {
    And,
    Or,
}
pub fn combine(a: &[u64], b: &[u64], out: &mut [u64], op: Logic, backend: Backend) -> Result<()> {
    if a.len() != b.len() || a.len() != out.len() {
        return Err("Boolean slice length mismatch".into());
    }
    Backend::resolve(backend.name())?;
    let mut done = 0;
    #[cfg(target_arch = "aarch64")]
    if backend == Backend::Neon {
        // SAFETY: runtime ISA check above and equal slices; kernel bounds every load.
        done = unsafe { neon(a, b, out, op) };
    }
    #[cfg(target_arch = "x86_64")]
    if backend == Backend::Avx2 {
        // SAFETY: runtime ISA check above and equal slices; unaligned bounded loads.
        done = unsafe { avx(a, b, out, op) };
    }
    for i in done..a.len() {
        out[i] = match op {
            Logic::And => a[i] & b[i],
            Logic::Or => a[i] | b[i],
        };
    }
    Ok(())
}
pub fn select(
    zero: &[u64],
    one: &[u64],
    selector: &[u64],
    out: &mut [u64],
    backend: Backend,
) -> Result<()> {
    if zero.len() != one.len() || zero.len() != selector.len() || zero.len() != out.len() {
        return Err("cofactor slice length mismatch".into());
    }
    Backend::resolve(backend.name())?;
    let mut done = 0;
    #[cfg(target_arch = "aarch64")]
    if backend == Backend::Neon {
        // SAFETY: ISA validated and all four slices have equal, checked lengths.
        done = unsafe { select_neon(zero, one, selector, out) };
    }
    #[cfg(target_arch = "x86_64")]
    if backend == Backend::Avx2 {
        // SAFETY: ISA validated and all four slices have equal, checked lengths.
        done = unsafe { select_avx(zero, one, selector, out) };
    }
    for i in done..zero.len() {
        out[i] = (zero[i] & !selector[i]) | (one[i] & selector[i]);
    }
    Ok(())
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn neon(a: &[u64], b: &[u64], out: &mut [u64], op: Logic) -> usize {
    use std::arch::aarch64::*;
    let mut i = 0;
    while i + 2 <= a.len() {
        let x = vld1q_u64(a.as_ptr().add(i));
        let y = vld1q_u64(b.as_ptr().add(i));
        let z = match op {
            Logic::And => vandq_u64(x, y),
            Logic::Or => vorrq_u64(x, y),
        };
        vst1q_u64(out.as_mut_ptr().add(i), z);
        i += 2;
    }
    i
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn avx(a: &[u64], b: &[u64], out: &mut [u64], op: Logic) -> usize {
    use std::arch::x86_64::*;
    let mut i = 0;
    while i + 4 <= a.len() {
        let x = _mm256_loadu_si256(a.as_ptr().add(i) as *const __m256i);
        let y = _mm256_loadu_si256(b.as_ptr().add(i) as *const __m256i);
        let z = match op {
            Logic::And => _mm256_and_si256(x, y),
            Logic::Or => _mm256_or_si256(x, y),
        };
        _mm256_storeu_si256(out.as_mut_ptr().add(i) as *mut __m256i, z);
        i += 4;
    }
    i
}
#[cfg(target_arch = "aarch64")]
#[target_feature(enable = "neon")]
unsafe fn select_neon(a: &[u64], b: &[u64], s: &[u64], out: &mut [u64]) -> usize {
    use std::arch::aarch64::*;
    let mut i = 0;
    while i + 2 <= a.len() {
        let m = vld1q_u64(s.as_ptr().add(i));
        let x = vld1q_u64(a.as_ptr().add(i));
        let y = vld1q_u64(b.as_ptr().add(i));
        // Select independent predicate bits, rather than whole floating-point lanes.
        let z = vorrq_u64(vbicq_u64(x, m), vandq_u64(y, m));
        vst1q_u64(out.as_mut_ptr().add(i), z);
        i += 2;
    }
    i
}
#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn select_avx(a: &[u64], b: &[u64], s: &[u64], out: &mut [u64]) -> usize {
    use std::arch::x86_64::*;
    let mut i = 0;
    while i + 4 <= a.len() {
        let x = _mm256_loadu_si256(a.as_ptr().add(i) as *const __m256i);
        let y = _mm256_loadu_si256(b.as_ptr().add(i) as *const __m256i);
        let m = _mm256_loadu_si256(s.as_ptr().add(i) as *const __m256i);
        let z = _mm256_or_si256(_mm256_andnot_si256(m, x), _mm256_and_si256(m, y));
        _mm256_storeu_si256(out.as_mut_ptr().add(i) as *mut __m256i, z);
        i += 4;
    }
    i
}
