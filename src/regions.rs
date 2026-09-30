//! Exact, sample-scoped constant-parameter regions over ordinary atom outputs.
//! No indicator names, stored results, epsilon-shifted predicates or approximate pruning.
use crate::{
    backtest::{Metrics, ReusableExecution, TransitionMode},
    Result,
};

/// Grid value = (start + index*step)/denominator. Integer arithmetic is exact;
/// conversion and division happen once per value, never accumulated additions.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Grid {
    pub start: i64,
    pub step: u64,
    pub count: u64,
    pub denominator: u64,
}
impl Grid {
    pub fn parse(text: &str) -> Result<Self> {
        let s: Vec<_> = text.split(':').collect();
        if s.len() != 4 {
            return Err("grid requires start_tick:step_tick:count:denominator".into());
        }
        let g = Self {
            start: s[0].parse().map_err(|_| "grid start")?,
            step: s[1].parse().map_err(|_| "grid step")?,
            count: s[2].parse().map_err(|_| "grid count")?,
            denominator: s[3].parse().map_err(|_| "grid denominator")?,
        };
        g.validate()?;
        Ok(g)
    }
    pub fn validate(self) -> Result<()> {
        const LIMIT: i128 = 1i128 << 52;
        if self.count == 0
            || self.step == 0
            || self.denominator == 0
            || self.denominator as i128 > LIMIT
        {
            return Err("grid requires positive count/step and denominator <=2^52".into());
        }
        let last = ((self.count - 1) as i128)
            .checked_mul(self.step as i128)
            .and_then(|n| n.checked_add(self.start as i128))
            .ok_or("grid integer overflow")?;
        if (self.start as i128).abs() > LIMIT || last.abs() > LIMIT {
            return Err("grid ticks exceed exact integer envelope".into());
        }
        Ok(())
    }
    pub fn value(self, i: u64) -> f64 {
        assert!(i < self.count);
        (self.start as i128 + i as i128 * self.step as i128) as f64 / self.denominator as f64
    }
    /// First grid index with value >= x; count denotes beyond the last value.
    pub fn lower_bound(self, x: f64) -> u64 {
        let (mut lo, mut hi) = (0, self.count);
        while lo < hi {
            let mid = lo + (hi - lo) / 2;
            if self.value(mid) < x {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        lo
    }
    pub fn member(self, x: f64) -> Result<u64> {
        let i = self.lower_bound(x);
        if i < self.count && self.value(i) == x {
            Ok(i)
        } else {
            Err(format!("grid excludes required anchor {x}"))
        }
    }
    pub fn text(self) -> String {
        format!(
            "{}:{}:{}:{}",
            self.start, self.step, self.count, self.denominator
        )
    }
}
#[derive(Default, Clone, Debug)]
pub struct RegionWork {
    pub input_rows: u64,
    pub crossing_events: u64,
    pub regions: u64,
    pub addresses: u64,
    /// Compact evidence: row count, grid count, word count, event count, then
    /// initial words and ordered (grid_index,row_index) changes. Not per address.
    pub proof: Vec<u8>,
}

/// Certificate for (x-c)>0 iff x>c: both finite operands are nonnegative,
/// subtraction cannot overflow or reverse the sign of an exact nonzero difference.
/// Nonfinite x remains an inactive signal, matching the ordinary pointwise atom.
/// This is NOT a generic license to reassociate floating-point expressions.
pub fn certificate(x: &[f64], grid: Grid) -> Result<()> {
    grid.validate()?;
    if grid.value(0) < 0.0 || x.iter().any(|v| v.is_finite() && *v < 0.0) {
        return Err("constant-subtraction region plan requires nonnegative finite operands; use expanded replay".into());
    }
    Ok(())
}

/// Emit contiguous [lo,hi) grid intervals with exactly identical positions.
/// All addresses are covered, but only distinct grid-transition states are scored.
/// Grid cardinality does not allocate a result array or generate a per-address hash.
pub fn sweep<F>(
    x: &[f64],
    grid: Grid,
    state: &mut ReusableExecution,
    mut emit: F,
) -> Result<RegionWork>
where
    F: FnMut(u64, u64, &[Metrics]) -> Result<()>,
{
    certificate(x, grid)?;
    if x.len() != state.len() {
        return Err("region/state row mismatch".into());
    }
    let (first, last) = (grid.value(0), grid.value(grid.count - 1));
    let mut words = vec![0u64; (x.len() + 63) / 64];
    let mut events = Vec::new();
    for (t, &v) in x.iter().enumerate() {
        if !v.is_finite() || v <= first {
            continue;
        }
        words[t / 64] |= 1 << (t % 64);
        if v <= last {
            let q = grid.lower_bound(v);
            if q > 0 && q < grid.count {
                events.push((q, t));
            }
        }
    }
    events.sort_unstable();
    let mut work = RegionWork {
        input_rows: x.len() as u64,
        crossing_events: events.len() as u64,
        ..RegionWork::default()
    };
    for n in [
        x.len() as u64,
        grid.count,
        words.len() as u64,
        events.len() as u64,
    ] {
        work.proof.extend_from_slice(&n.to_le_bytes());
    }
    for w in &words {
        work.proof.extend_from_slice(&w.to_le_bytes());
    }
    for &(q, t) in &events {
        work.proof.extend_from_slice(&q.to_le_bytes());
        work.proof.extend_from_slice(&(t as u64).to_le_bytes());
    }
    let (mut lo, mut cursor) = (0, 0);
    loop {
        let hi = if cursor < events.len() {
            events[cursor].0
        } else {
            grid.count
        };
        if hi > lo {
            let metrics = state.score(&words, TransitionMode::Auto)?;
            emit(lo, hi, &metrics)?;
            work.regions += 1;
            work.addresses = work
                .addresses
                .checked_add(hi - lo)
                .ok_or("region coverage overflow")?;
        }
        if hi == grid.count {
            break;
        }
        while cursor < events.len() && events[cursor].0 == hi {
            let t = events[cursor].1;
            words[t / 64] &= !(1 << (t % 64));
            cursor += 1;
        }
        lo = hi;
    }
    Ok(work)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        backtest::{Costs, Market, Rule},
        data::Data,
    };
    fn fixture(n: usize) -> Data {
        Data {
            timestamps: (0..n as i64).collect(),
            columns: std::array::from_fn(|_| {
                (0..n).map(|i| 100.0 + (i as f64 / 7.).sin()).collect()
            }),
            interval: 14400,
            digest: "fixture".into(),
        }
    }
    #[test]
    fn grids_ties_invalids_and_all_region_endpoints() {
        let d = fixture(131);
        let cost = Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        };
        let mut s = ReusableExecution::new(&d, 0, d.len(), &[cost], 16 << 20).unwrap();
        let m = Market::new(&d, 0, d.len(), cost).unwrap();
        let g = Grid::parse("0:1:101:50").unwrap();
        let x: Vec<_> = (0..m.len)
            .map(|i| {
                if i % 17 == 0 {
                    f64::NAN
                } else {
                    (i % 103) as f64 / 50.
                }
            })
            .collect();
        let mut covered = 0;
        sweep(&x, g, &mut s, |lo, hi, ms| {
            assert_eq!(lo, covered);
            for q in lo..hi {
                let mut f: Vec<_> = x.iter().map(|v| v - g.value(q)).collect();
                f.extend([0., 0.]);
                let r = m
                    .score(
                        &f,
                        Rule {
                            threshold: 0.,
                            greater: true,
                        },
                    )
                    .unwrap();
                assert_eq!(r.lite.entries, ms[0].lite.entries);
                assert_eq!(r.lite.active, ms[0].lite.active);
                assert!((r.lite.log_return - ms[0].lite.log_return).abs() < 1e-12);
                assert!((r.max_drawdown_pct - ms[0].max_drawdown_pct).abs() < 1e-10);
            }
            covered = hi;
            Ok(())
        })
        .unwrap();
        assert_eq!(covered, g.count);
    }
    #[test]
    fn trillion_constant_grid_is_resolved_without_enumeration() {
        let d = fixture(12);
        let mut s = ReusableExecution::new(
            &d,
            0,
            12,
            &[Costs {
                fee_bps: 0.,
                slip_bps: 0.,
            }],
            1 << 20,
        )
        .unwrap();
        let g = Grid::parse("500000000000:1:1000000000000:1000000000000").unwrap();
        let x = [1., 1., 0.75, 1.25, f64::NAN, 2., 0., 0.5, 1., 1.5];
        let mut n = 0;
        let w = sweep(&x, g, &mut s, |_, _, _| {
            n += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!(w.addresses, 1_000_000_000_000);
        assert!(n <= x.len() + 1);
        assert!(certificate(&[-1.], g).is_err());
        assert!(Grid::parse("0:0:1:1").is_err());
    }
}
