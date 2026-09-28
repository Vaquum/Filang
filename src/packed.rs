//! Packed behavior identity/diversity and bit-sliced majority voting.
use crate::{
    backtest::Rule,
    kernels::{self, Backend},
    Result,
};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Mask {
    pub words: Vec<u64>,
    pub len: usize,
    pub count: u64,
}
impl Mask {
    pub fn empty() -> Self {
        Self {
            words: vec![],
            len: 0,
            count: 0,
        }
    }
    pub fn threshold(x: &[f64], rule: Rule, backend: Backend) -> Result<Self> {
        let words = kernels::threshold(x, rule, backend)?;
        let count = words.iter().map(|w| w.count_ones() as u64).sum();
        Ok(Self {
            words,
            len: x.len(),
            count,
        })
    }
    pub fn append(&mut self, other: &Self) {
        let old = self.len;
        self.len += other.len;
        self.words.resize((self.len + 63) / 64, 0);
        for (i, &word) in other.words.iter().enumerate() {
            let j = old / 64 + i;
            let shift = old % 64;
            self.words[j] |= word << shift;
            if shift > 0 && j + 1 < self.words.len() {
                self.words[j + 1] |= word >> (64 - shift);
            }
        }
        self.count += other.count;
    }
    pub fn abs_correlation(&self, other: &Self, backend: Backend) -> Result<f64> {
        if self.len != other.len {
            return Err("behavior population mismatch".into());
        }
        let n = self.len as f64;
        let a = self.count as f64;
        let b = other.count as f64;
        if a == 0.0 || b == 0.0 || a == n || b == n {
            return Ok(if self.words == other.words { 1.0 } else { 0.0 });
        }
        let ab = kernels::intersection(&self.words, &other.words, backend)? as f64;
        Ok(((n * ab - a * b) / (a * (n - a) * b * (n - b)).sqrt())
            .abs()
            .min(1.0))
    }
    pub fn unpack(&self) -> Vec<bool> {
        (0..self.len)
            .map(|i| self.words[i / 64] & (1 << (i % 64)) != 0)
            .collect()
    }
}
/// Strict majority; ties stay flat. No per-observation floating point work.
pub fn majority(masks: &[Mask], len: usize) -> Result<Mask> {
    if masks.len() > 31 || masks.iter().any(|m| m.len != len) {
        return Err("majority requires <=31 equal-length masks".into());
    }
    let mut out = Mask {
        words: vec![0; (len + 63) / 64],
        len,
        count: 0,
    };
    if masks.is_empty() {
        return Ok(out);
    }
    for w in 0..out.words.len() {
        let mut planes = [0u64; 5];
        for m in masks {
            let mut carry = m.words[w];
            for p in &mut planes {
                let next = *p & carry;
                *p ^= carry;
                carry = next;
            }
        }
        let cutoff = masks.len() / 2;
        let (mut equal, mut greater) = (!0u64, 0u64);
        for bit in (0..5).rev() {
            if cutoff & (1 << bit) == 0 {
                greater |= equal & planes[bit];
                equal &= !planes[bit];
            } else {
                equal &= planes[bit];
            }
        }
        out.words[w] = greater;
    }
    if len % 64 != 0 {
        if let Some(last) = out.words.last_mut() {
            *last &= (1u64 << (len % 64)) - 1;
        }
    }
    out.count = out.words.iter().map(|w| w.count_ones() as u64).sum();
    Ok(out)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn packed_append_correlation_and_votes() {
        let be = Backend::resolve("auto").unwrap();
        for n in [0, 1, 63, 64, 65, 257] {
            let all = (0..31)
                .map(|s| {
                    let x = (0..n)
                        .map(|i| ((i * 17 + s * 11) % 23) as f64)
                        .collect::<Vec<_>>();
                    Mask::threshold(
                        &x,
                        Rule {
                            greater: true,
                            threshold: 10.0,
                        },
                        be,
                    )
                    .unwrap()
                })
                .collect::<Vec<_>>();
            for k in 0..=31 {
                let v = majority(&all[..k], n).unwrap().unpack();
                for (i, &value) in v.iter().enumerate() {
                    assert_eq!(
                        value,
                        (all[..k]
                            .iter()
                            .filter(|m| m.words[i / 64] & (1 << (i % 64)) != 0)
                            .count()
                            * 2)
                            > k
                    );
                }
            }
        }
        let a = Mask::threshold(
            &[0.0, 1.0, 0.0],
            Rule {
                greater: true,
                threshold: 0.5,
            },
            be,
        )
        .unwrap();
        let mut b = a.clone();
        b.append(&a);
        assert_eq!(b.unpack(), vec![false, true, false, false, true, false]);
        assert_eq!(a.abs_correlation(&a, be).unwrap(), 1.0);
    }
}
