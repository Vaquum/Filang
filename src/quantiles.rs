//! All historical prefix quantiles from one sort and a growing Fenwick tree.
//! Later values may affect coordinate labels but never prefix counts or cutoffs.
use crate::Result;
fn sorted_q(values: &[f64], q: f64) -> f64 {
    let p = q * (values.len() - 1) as f64;
    let i = p.floor() as usize;
    let a = p - i as f64;
    values[i] * (1.0 - a) + values[(i + 1).min(values.len() - 1)] * a
}
pub fn prefixes(
    x: &[f64],
    start: usize,
    ends: &[usize],
    qs: &[f64],
    factorized: bool,
) -> Result<Vec<Vec<f64>>> {
    if ends.is_empty()
        || ends.windows(2).any(|e| e[0] >= e[1])
        || ends[0] <= start
        || *ends.last().unwrap() > x.len()
        || qs.iter().any(|q| !q.is_finite() || *q <= 0.0 || *q >= 1.0)
    {
        return Err("invalid prefix quantile request".into());
    }
    if !factorized {
        return Ok(ends
            .iter()
            .map(|end| {
                let mut a = x[start..*end]
                    .iter()
                    .copied()
                    .filter(|v| v.is_finite())
                    .collect::<Vec<_>>();
                a.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
                qs.iter()
                    .map(|&q| {
                        if a.len() < 256 || a.last().unwrap() - a[0] <= 1e-12 {
                            f64::NAN
                        } else {
                            sorted_q(&a, q)
                        }
                    })
                    .collect()
            })
            .collect());
    }
    let mut coords = x[start..*ends.last().unwrap()]
        .iter()
        .copied()
        .filter(|v| v.is_finite())
        .collect::<Vec<_>>();
    coords.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
    coords.dedup_by(|a, b| *a == *b);
    let mut tree = vec![0usize; coords.len() + 1];
    let (mut cursor, mut count) = (start, 0usize);
    let mut out = vec![];
    for &end in ends {
        for &v in &x[cursor..end] {
            if v.is_finite() {
                let mut j = coords
                    .binary_search_by(|a| a.partial_cmp(&v).unwrap())
                    .unwrap()
                    + 1;
                while j < tree.len() {
                    tree[j] += 1;
                    j += j & j.wrapping_neg();
                }
                count += 1;
            }
        }
        cursor = end;
        let mut row = vec![f64::NAN; qs.len()];
        if count >= 256 && coords[kth(&tree, count)] - coords[kth(&tree, 1)] > 1e-12 {
            for (i, &q) in qs.iter().enumerate() {
                let p = q * (count - 1) as f64;
                let lo = p.floor() as usize;
                let a = p - lo as f64;
                row[i] = coords[kth(&tree, lo + 1)] * (1.0 - a)
                    + coords[kth(&tree, (lo + 2).min(count))] * a;
            }
        }
        out.push(row);
    }
    Ok(out)
}
fn kth(tree: &[usize], mut k: usize) -> usize {
    let mut pos = 0;
    let mut step = 1;
    while step < tree.len() {
        step <<= 1;
    }
    while step > 0 {
        let next = pos + step;
        if next < tree.len() && tree[next] < k {
            k -= tree[next];
            pos = next;
        }
        step >>= 1;
    }
    pos
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fenwick_matches_sorts_and_future_perturbation() {
        let mut x = (0..3000)
            .map(|i| {
                if i % 37 == 0 {
                    f64::NAN
                } else {
                    ((i * 119) % 271) as f64 / 3.0
                }
            })
            .collect::<Vec<_>>();
        let q = [0.01, 0.15, 0.5, 0.8, 0.99];
        let ends = [500, 900, 2000, 3000];
        let a = prefixes(&x, 30, &ends, &q, true).unwrap();
        let b = prefixes(&x, 30, &ends, &q, false).unwrap();
        assert_eq!(a, b);
        for v in &mut x[900..] {
            *v = -1000.0;
        }
        let c = prefixes(&x, 30, &ends, &q, true).unwrap();
        assert_eq!(&a[..2], &c[..2]);
        assert!(prefixes(&x, 30, &[0], &q, true).is_err());
    }
}
