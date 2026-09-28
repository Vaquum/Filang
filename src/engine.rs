use crate::{
    data::Data,
    lang::{Graph, Id, Op},
    Result,
};
use std::collections::{HashMap, VecDeque};

pub struct Batch {
    pub values: HashMap<Id, Vec<f64>>,
    pub nodes_computed: usize,
    pub payload_bytes: usize,
}
/// Materialize only the dependency closure of a bounded batch. No cross-data cache.
pub fn evaluate(g: &Graph, d: &Data, roots: &[Id], budget: usize) -> Result<Batch> {
    if roots.iter().any(|r| *r >= g.nodes.len()) {
        return Err("unknown output node".into());
    }
    let deps = g.dependencies(roots);
    // Four series of reserve cover extrema queues and scorer working buffers.
    let bytes = (deps.len() + 4)
        .checked_mul(d.len())
        .and_then(|x| x.checked_mul(8))
        .ok_or("payload overflow")?;
    if bytes > budget {
        return Err(format!(
            "batch numerical payload {bytes} exceeds budget {budget}"
        ));
    }
    let mut values: HashMap<Id, Vec<f64>> = HashMap::new();
    for id in &deps {
        let node = &g.nodes[*id];
        let a = node.args.first().map(|i| values[i].as_slice());
        let b = node.args.get(1).map(|i| values[i].as_slice());
        let out = kernel(&node.op, a, b, d);
        values.insert(*id, out);
    }
    Ok(Batch {
        values,
        nodes_computed: deps.len(),
        payload_bytes: bytes,
    })
}
fn kernel(op: &Op, a: Option<&[f64]>, b: Option<&[f64]>, d: &Data) -> Vec<f64> {
    use Op::*;
    let n = d.len();
    match *op {
        Source(j) => d.columns[j as usize].clone(),
        Constant(bits) => vec![f64::from_bits(bits); n],
        Mean(w) | Std(w) => moments(a.unwrap(), w, matches!(op, Std(_))),
        Min(w) | Max(w) => extrema(a.unwrap(), w, matches!(op, Max(_))),
        Ema(w) | Wilder(w) => smooth(
            a.unwrap(),
            w,
            if matches!(op, Ema(_)) {
                2.0 / (w + 1) as f64
            } else {
                1.0 / w as f64
            },
        ),
        _ => {
            let a = a.unwrap();
            let mut out = vec![f64::NAN; n];
            for t in 0..n {
                let x = a[t];
                let y = b.map(|v| v[t]).unwrap_or(0.0);
                let v = match *op {
                    Lag(k) if t >= k => a[t - k],
                    Diff(k) if t >= k => x - a[t - k],
                    Abs => x.abs(),
                    Neg => -x,
                    Add if x.is_finite() && y.is_finite() => x + y,
                    Sub if x.is_finite() && y.is_finite() => x - y,
                    Mul if x.is_finite() && y.is_finite() => x * y,
                    Div if x.is_finite() && y.is_finite() && y.abs() > 1e-12 => x / y,
                    Min2 if x.is_finite() && y.is_finite() => x.min(y),
                    Max2 if x.is_finite() && y.is_finite() => x.max(y),
                    _ => f64::NAN,
                };
                if v.is_finite() {
                    out[t] = v;
                }
            }
            out
        }
    }
}
/// Sliding Welford moments; periodic deterministic rebasing bounds roundoff drift.
fn moments(a: &[f64], w: usize, std: bool) -> Vec<f64> {
    let mut out = vec![f64::NAN; a.len()];
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
            let v = if std {
                (m2 / w as f64).max(0.0).sqrt()
            } else {
                mean
            };
            if v.is_finite() {
                out[t] = v;
            }
        }
    }
    out
}
fn extrema(a: &[f64], w: usize, max: bool) -> Vec<f64> {
    let mut out = vec![f64::NAN; a.len()];
    let mut q: VecDeque<usize> = VecDeque::new();
    let mut valid_run = 0;
    for t in 0..a.len() {
        if !a[t].is_finite() {
            q.clear();
            valid_run = 0;
            continue;
        }
        valid_run += 1;
        while q.front().map_or(false, |j| *j + w <= t) {
            q.pop_front();
        }
        while q
            .back()
            .map_or(false, |j| if max { a[*j] <= a[t] } else { a[*j] >= a[t] })
        {
            q.pop_back();
        }
        q.push_back(t);
        if valid_run >= w {
            out[t] = a[*q.front().unwrap()];
        }
    }
    out
}
fn smooth(a: &[f64], w: usize, alpha: f64) -> Vec<f64> {
    let mut out = vec![f64::NAN; a.len()];
    let (mut count, mut seed, mut state) = (0, 0.0, 0.0);
    for (t, x) in a.iter().copied().enumerate() {
        if !x.is_finite() {
            count = 0;
            seed = 0.0;
            state = 0.0;
            continue;
        }
        if count < w {
            seed += x;
            count += 1;
            if count == w {
                state = seed / w as f64;
                out[t] = state;
            }
        } else {
            state = alpha * x + (1.0 - alpha) * state;
            out[t] = state;
        }
    }
    out
}
#[cfg(test)]
mod tests {
    use super::*;
    fn fixture(n: usize) -> Data {
        Data {
            timestamps: (0..n as i64).collect(),
            columns: std::array::from_fn(|_| {
                (0..n).map(|x| 100.0 + (x as f64 / 5.0).sin()).collect()
            }),
            interval: 1,
            digest: "fixture".into(),
        }
    }
    #[test]
    fn rolling_oracle() {
        let a = (0..2000)
            .map(|x| 10000.0 + (x as f64 / 7.0).sin())
            .collect::<Vec<_>>();
        for w in [1, 7, 32, 128] {
            let m = moments(&a, w, false);
            let s = moments(&a, w, true);
            for t in w - 1..a.len() {
                let z = &a[t + 1 - w..=t];
                let mu = z.iter().sum::<f64>() / w as f64;
                let sd = (z.iter().map(|x| (x - mu).powi(2)).sum::<f64>() / w as f64).sqrt();
                assert!((mu - m[t]).abs() < 1e-8);
                assert!((sd - s[t]).abs() < 1e-6);
            }
        }
    }
    #[test]
    fn warmup_and_invalid() {
        let a = [1.0, 2.0, 3.0, f64::NAN, 5.0, 6.0, 7.0];
        let m = moments(&a, 3, false);
        assert_eq!(m[2], 2.0);
        assert!(m[4].is_nan());
        assert_eq!(m[6], 6.0);
        let e = smooth(&a, 3, 0.5);
        assert_eq!(e[2], 2.0);
        assert!(e[5].is_nan());
        assert_eq!(e[6], 6.0);
        assert_eq!(extrema(&a, 3, true)[6], 7.0);
    }
    #[test]
    fn future_append_and_batch_identity() {
        let mut g = Graph::new();
        let r = g
            .parse("(div (sub close (ema 8 close)) (std 12 close))")
            .unwrap();
        let s = g
            .parse("(mean 5 (div (sub close (ema 8 close)) (std 12 close)))")
            .unwrap();
        let d = fixture(200);
        let a = evaluate(&g, &d, &[r, s], 1_000_000).unwrap();
        let b = evaluate(&g, &d.prefix(100), &[r], 1_000_000).unwrap();
        for t in 0..100 {
            assert_eq!(a.values[&r][t].to_bits(), b.values[&r][t].to_bits());
        }
        let c = evaluate(&g, &d, &[s], 1_000_000).unwrap();
        assert!(a.values[&s]
            .iter()
            .zip(&c.values[&s])
            .all(|(x, y)| x.to_bits() == y.to_bits()));
        assert!(evaluate(&g, &d, &[r], 1).is_err());
    }
}
