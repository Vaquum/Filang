//! Streaming predicate cells on an explicit scored range. Monotone temporal
//! qualifiers lower to value selection, never floating-point reassociation.
use crate::{
    regions::Grid,
    rules::{Cmp, Mask, Predicate, Qualifier},
    Result,
};
use std::{borrow::Cow, collections::VecDeque, ops::Range};

fn extrema(x: &[f64], n: usize, maximum: bool) -> Result<Vec<f64>> {
    if n == 0 || n > 100000 {
        return Err("qualifier window outside 1..100000".into());
    }
    let mut out = vec![f64::NAN; x.len()];
    let mut queue: VecDeque<usize> = VecDeque::new();
    let mut run = 0;
    for (t, &v) in x.iter().enumerate() {
        if !v.is_finite() {
            queue.clear();
            run = 0;
            continue;
        }
        run += 1;
        while queue.front().map_or(false, |&i| i + n <= t) {
            queue.pop_front();
        }
        while queue
            .back()
            .map_or(false, |&i| if maximum { x[i] <= v } else { x[i] >= v })
        {
            queue.pop_back();
        }
        queue.push_back(t);
        if run >= n {
            out[t] = x[*queue.front().unwrap()];
        }
    }
    Ok(out)
}

/// Return an exactly comparison-equivalent numerical series for monotone
/// threshold qualifiers. Complete input validity windows precede range slicing.
pub fn qualified<'a>(x: &'a [f64], cmp: Cmp, qualifiers: &[Qualifier]) -> Result<Cow<'a, [f64]>> {
    if !matches!(cmp, Cmp::Gt | Cmp::Ge | Cmp::Lt | Cmp::Le)
        || qualifiers.iter().any(|q| matches!(q, Qualifier::Onset))
    {
        return Err("nonmonotone predicate requires general cell preparation".into());
    }
    let above = matches!(cmp, Cmp::Gt | Cmp::Ge);
    let mut values = Cow::Borrowed(x);
    for &q in qualifiers {
        let (n, maximum) = match q {
            Qualifier::Plain => continue,
            Qualifier::Persist(n) => (n, !above),
            Qualifier::Recent(n) => (n, above),
            Qualifier::Onset => unreachable!(),
        };
        values = Cow::Owned(extrema(&values, n, maximum)?);
    }
    Ok(values)
}
fn upper_bound(grid: Grid, x: f64) -> u64 {
    let (mut lo, mut hi) = (0, grid.count);
    while lo < hi {
        let mid = lo + (hi - lo) / 2;
        if grid.value(mid) <= x {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    lo
}
#[derive(Clone, Copy, Default, Debug)]
pub struct Work {
    pub cells: u64,
    pub events: u64,
    pub addresses: u64,
}

/// Stream complete disjoint [lo,hi) threshold cells; storage O(input rows),
/// independent of grid count. Consumers must copy a mask only when retaining it.
pub fn visit<F>(
    x: &[f64],
    cmp: Cmp,
    grid: Grid,
    qualifiers: &[Qualifier],
    range: Range<usize>,
    mut emit: F,
) -> Result<Work>
where
    F: FnMut(u64, u64, &Mask) -> Result<()>,
{
    grid.validate()?;
    if range.start > range.end || range.end > x.len() {
        return Err("scoped predicate range".into());
    }
    let values = qualified(x, cmp, qualifiers)?;
    let values = &values[range];
    let mut mask = Mask::empty(values.len());
    let mut events = Vec::new();
    for (t, &v) in values.iter().enumerate() {
        let valid = v.is_finite();
        mask.set(t, valid && cmp.test(v, grid.value(0)), valid);
        if valid {
            let q = if matches!(cmp, Cmp::Gt | Cmp::Le) {
                grid.lower_bound(v)
            } else {
                upper_bound(grid, v)
            };
            if q > 0 && q < grid.count {
                events.push((q, t));
            }
        }
    }
    events.sort_unstable();
    let mut work = Work {
        events: events.len() as u64,
        ..Work::default()
    };
    let (mut lo, mut at) = (0, 0);
    loop {
        let hi = events.get(at).map_or(grid.count, |e| e.0);
        if hi > lo {
            emit(lo, hi, &mask)?;
            work.cells += 1;
            work.addresses += hi - lo;
        }
        if hi == grid.count {
            break;
        }
        while at < events.len() && events[at].0 == hi {
            let t = events[at].1;
            mask.bits[t / 64] ^= 1 << (t % 64);
            at += 1;
        }
        lo = hi;
    }
    Ok(work)
}

/// General contract-compatible fallback for Eq/Ne/onset predicates.
pub fn visit_or_reference<F>(
    x: &[f64],
    cmp: Cmp,
    grid: Grid,
    qualifiers: &[Qualifier],
    range: Range<usize>,
    budget: usize,
    mut emit: F,
) -> Result<Work>
where
    F: FnMut(u64, u64, &Mask) -> Result<()>,
{
    if range.start > range.end || range.end > x.len() {
        return Err("scoped predicate range".into());
    }
    if matches!(cmp, Cmp::Gt | Cmp::Ge | Cmp::Lt | Cmp::Le)
        && !qualifiers.iter().any(|q| matches!(q, Qualifier::Onset))
    {
        return visit(x, cmp, grid, qualifiers, range, emit);
    }
    let cells = crate::rules::cells(
        &Predicate::Threshold(cmp),
        x,
        None,
        grid,
        qualifiers,
        budget,
    )?;
    let mut work = Work::default();
    for c in cells {
        let m = c.mask.slice(range.start, range.end)?;
        emit(c.lo, c.hi, &m)?;
        work.cells += 1;
        work.addresses += c.hi - c.lo;
    }
    Ok(work)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn monotone_pushdown_matches_unsimplified_on_full_validity_ties_and_boundaries() {
        let x: Vec<_> = (0..357)
            .map(|i| {
                if i % 71 == 0 {
                    f64::NAN
                } else {
                    ((i * 37 % 41) as f64 - 20.) / 10.
                }
            })
            .collect();
        let grid = Grid::parse("-20:1:41:10").unwrap();
        for cmp in [Cmp::Gt, Cmp::Ge, Cmp::Lt, Cmp::Le, Cmp::Eq, Cmp::Ne] {
            for qs in [
                vec![],
                vec![Qualifier::Plain],
                vec![Qualifier::Persist(2)],
                vec![Qualifier::Recent(3)],
                vec![Qualifier::Persist(5), Qualifier::Recent(4)],
                vec![Qualifier::Onset],
            ] {
                for start in [0, 1, 63, 129] {
                    let mut next = 0;
                    visit_or_reference(
                        &x,
                        cmp,
                        grid,
                        &qs,
                        start..x.len() - 1,
                        1 << 24,
                        |lo, hi, m| {
                            assert_eq!(lo, next);
                            for q in lo..hi {
                                let want = Predicate::Threshold(cmp)
                                    .evaluate(&x, None, grid.value(q), &qs)
                                    .unwrap()
                                    .slice(start, x.len() - 1)
                                    .unwrap();
                                assert_eq!(*m, want, "cmp={cmp:?} q={q} qualifiers={qs:?}");
                            }
                            next = hi;
                            Ok(())
                        },
                    )
                    .unwrap();
                    assert_eq!(next, grid.count);
                }
            }
        }
        assert!(visit(
            &x,
            Cmp::Gt,
            grid,
            &[Qualifier::Persist(0)],
            0..x.len(),
            |_, _, _| Ok(())
        )
        .is_err());
    }
    #[test]
    fn cells_do_not_allocate_by_grid_cardinality() {
        let g = Grid::parse("-1000000000000:1:2000000000001:1000000000000").unwrap();
        let x = [-1., 0., 1., f64::NAN];
        let w = visit(&x, Cmp::Gt, g, &[], 0..4, |_, _, _| Ok(())).unwrap();
        assert_eq!(w.addresses, g.count);
        assert!(w.cells <= 5);
    }
}
