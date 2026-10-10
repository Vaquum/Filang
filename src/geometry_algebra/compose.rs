use super::project;
use crate::{geometry::GeometryPattern, Result};

/// Maximum number of dynamic-programming cells for a single composition
/// calculation. This affects this optional module only, never Filang's engine.
const MAX_COMPOSITION_CELLS: usize = 1_000_000;

fn check_inputs(left: &GeometryPattern, right: &GeometryPattern, shared: usize) -> Result<()> {
    if left.mode() != right.mode() {
        return Err("geometry algebra: both operands must have the same orientation mode".into());
    }
    if shared > left.len().min(right.len()) {
        return Err("geometry algebra: overlap exceeds a window's length".into());
    }
    Ok(())
}

/// Whether the suffix of left and prefix of right have exactly the same
/// induced endpoint weak order and, if oriented, the same body directions.
///
/// Compatibility permits composition, but does not determine the unobserved
/// comparisons between endpoints exclusive to the two windows.
pub fn overlap_compatible(
    left: &GeometryPattern,
    right: &GeometryPattern,
    shared: usize,
) -> Result<bool> {
    check_inputs(left, right, shared)?;
    let l: Vec<_> = (left.len() - shared..left.len()).collect();
    let r: Vec<_> = (0..shared).collect();
    Ok(project(left, &l)? == project(right, &r)?)
}

struct MergePlan<'a> {
    left: &'a GeometryPattern,
    right: &'a GeometryPattern,
    shared: usize,
    // A shared endpoint level must be matched to precisely its counterpart.
    // Non-shared levels may interleave or become equal across operands.
    l_anchor: Vec<Option<usize>>,
    r_anchor: Vec<Option<usize>>,
}

impl<'a> MergePlan<'a> {
    fn new(
        left: &'a GeometryPattern,
        right: &'a GeometryPattern,
        shared: usize,
    ) -> Result<Option<Self>> {
        if !overlap_compatible(left, right, shared)? {
            return Ok(None);
        }
        let mut l_anchor = vec![None; left.level_count()];
        let mut r_anchor = vec![None; right.level_count()];
        for row in 0..shared {
            let lrow = left.ranks()[left.len() - shared + row];
            let rrow = right.ranks()[row];
            for endpoint in 0..4 {
                let l = lrow[endpoint];
                let r = rrow[endpoint];
                if l_anchor[l].map_or(false, |previous| previous != r)
                    || r_anchor[r].map_or(false, |previous| previous != l)
                {
                    return Err("geometry algebra: inconsistent shared-level anchors".into());
                }
                l_anchor[l] = Some(r);
                r_anchor[r] = Some(l);
            }
        }
        Ok(Some(Self {
            left,
            right,
            shared,
            l_anchor,
            r_anchor,
        }))
    }

    fn can_left_only(&self, i: usize) -> bool {
        i < self.l_anchor.len() && self.l_anchor[i].is_none()
    }

    fn can_right_only(&self, j: usize) -> bool {
        j < self.r_anchor.len() && self.r_anchor[j].is_none()
    }

    fn can_tie(&self, i: usize, j: usize) -> bool {
        i < self.l_anchor.len()
            && j < self.r_anchor.len()
            && self.l_anchor[i].map_or(true, |anchor| anchor == j)
            && self.r_anchor[j].map_or(true, |anchor| anchor == i)
    }

    fn width(&self) -> usize {
        self.r_anchor.len() + 1
    }

    fn at(&self, i: usize, j: usize) -> usize {
        i * self.width() + j
    }

    /// Count every valid completion, without generating any complete pattern.
    /// This is a constrained Delannoy recurrence. A path chooses L, R, or
    /// both at each new global price level, with shared levels tied exactly.
    fn suffix_counts(&self) -> Result<Vec<u128>> {
        let l = self.l_anchor.len();
        let r = self.r_anchor.len();
        let cells = (l + 1)
            .checked_mul(r + 1)
            .ok_or("geometry algebra: composition matrix dimensions overflow")?;
        if cells > MAX_COMPOSITION_CELLS {
            return Err(
                "geometry algebra: composition matrix exceeds its explicit cell budget".into(),
            );
        }
        let mut counts = vec![0u128; cells];
        counts[self.at(l, r)] = 1;
        for i in (0..=l).rev() {
            for j in (0..=r).rev() {
                if i == l && j == r {
                    continue;
                }
                let mut total = 0u128;
                if self.can_left_only(i) {
                    total = total
                        .checked_add(counts[self.at(i + 1, j)])
                        .ok_or("geometry algebra: composition count exceeds u128")?;
                }
                if self.can_right_only(j) {
                    total = total
                        .checked_add(counts[self.at(i, j + 1)])
                        .ok_or("geometry algebra: composition count exceeds u128")?;
                }
                if self.can_tie(i, j) {
                    total = total
                        .checked_add(counts[self.at(i + 1, j + 1)])
                        .ok_or("geometry algebra: composition count exceeds u128")?;
                }
                counts[self.at(i, j)] = total;
            }
        }
        Ok(counts)
    }

    fn materialize(&self, lmap: &[usize], rmap: &[usize]) -> Result<GeometryPattern> {
        let rows = self
            .left
            .ranks()
            .iter()
            .map(|r| r.map(|rank| lmap[rank]))
            .chain(
                self.right.ranks()[self.shared..]
                    .iter()
                    .map(|r| r.map(|rank| rmap[rank])),
            )
            .collect();
        let directions = self.left.directions().map(|l| {
            let mut all = l.to_vec();
            all.extend_from_slice(&self.right.directions().unwrap()[self.shared..]);
            all
        });
        GeometryPattern::new(rows, directions)
    }

    fn collect(&self, counts: &[u128], output: &mut Vec<GeometryPattern>) -> Result<()> {
        // Explicit DFS frames avoid a call-stack limit for a long but
        // deterministic one-completion chain. Backtracking reuses rank maps.
        struct Frame {
            i: usize,
            j: usize,
            rank: usize,
            branch: u8,
        }
        let mut lmap = vec![0; self.l_anchor.len()];
        let mut rmap = vec![0; self.r_anchor.len()];
        let mut stack = vec![Frame {
            i: 0,
            j: 0,
            rank: 0,
            branch: 0,
        }];
        while let Some(frame) = stack.last_mut() {
            if frame.i == self.l_anchor.len() && frame.j == self.r_anchor.len() {
                output.push(self.materialize(&lmap, &rmap)?);
                stack.pop();
                continue;
            }
            let i = frame.i;
            let j = frame.j;
            let rank = frame.rank;
            let branch = frame.branch;
            frame.branch += 1;
            let next = match branch {
                0 if self.can_left_only(i) && counts[self.at(i + 1, j)] != 0 => {
                    lmap[i] = rank;
                    Some((i + 1, j))
                }
                1 if self.can_right_only(j) && counts[self.at(i, j + 1)] != 0 => {
                    rmap[j] = rank;
                    Some((i, j + 1))
                }
                2 if self.can_tie(i, j) && counts[self.at(i + 1, j + 1)] != 0 => {
                    lmap[i] = rank;
                    rmap[j] = rank;
                    Some((i + 1, j + 1))
                }
                _ => None,
            };
            if let Some((next_i, next_j)) = next {
                stack.push(Frame {
                    i: next_i,
                    j: next_j,
                    rank: rank + 1,
                    branch: 0,
                });
            } else if branch >= 2 {
                stack.pop();
            }
        }
        Ok(())
    }
}

/// Exact number of complete geometries extending the two operand patterns
/// with the specified shared suffix/prefix. Incompatible windows have count 0.
///
/// Rejects unsupported DP memory and u128 cardinality overflow explicitly.
/// This count is a structural fact, not an observed sample frequency.
pub fn composition_count(
    left: &GeometryPattern,
    right: &GeometryPattern,
    shared: usize,
) -> Result<u128> {
    match MergePlan::new(left, right, shared)? {
        None => Ok(0),
        Some(plan) => Ok(plan.suffix_counts()?[0]),
    }
}

/// Enumerate *all* canonical geometries consistent with two overlapping
/// operand patterns. Each output contains the full left window, followed by
/// the non-shared suffix of the right window.
///
/// If the exact count exceeds max_results, returns an error and no partial
/// results. For huge domains use composition_count instead.
pub fn compose_overlap(
    left: &GeometryPattern,
    right: &GeometryPattern,
    shared: usize,
    max_results: usize,
) -> Result<Vec<GeometryPattern>> {
    let plan = match MergePlan::new(left, right, shared)? {
        Some(plan) => plan,
        None => return Ok(Vec::new()),
    };
    let counts = plan.suffix_counts()?;
    if counts[0] > max_results as u128 {
        return Err(format!(
            "geometry algebra: {} completions exceed max_results={max_results}",
            counts[0]
        ));
    }
    let mut output = Vec::new();
    output
        .try_reserve_exact(counts[0] as usize)
        .map_err(|_| "geometry algebra: cannot reserve completion output")?;
    plan.collect(&counts, &mut output)?;
    debug_assert_eq!(output.len() as u128, counts[0]);
    Ok(output)
}

/// Extend a complete window by one specified local candle shape/direction.
/// The relative positioning of its price levels to previous candles is
/// unresolved and is exhaustively returned, subject to max_results.
pub fn append_one(
    prefix: &GeometryPattern,
    candle: &GeometryPattern,
    max_results: usize,
) -> Result<Vec<GeometryPattern>> {
    if candle.len() != 1 {
        return Err("geometry algebra: extension operand must contain one candle".into());
    }
    compose_overlap(prefix, candle, 0, max_results)
}

/// Extend a complete window by one specified candle in the first row position.
/// Useful when the caller stores recent bars first and a later observed candle
/// enters at the front of its window. This is not a forecast.
pub fn prepend_one(
    candle: &GeometryPattern,
    suffix: &GeometryPattern,
    max_results: usize,
) -> Result<Vec<GeometryPattern>> {
    if candle.len() != 1 {
        return Err("geometry algebra: extension operand must contain one candle".into());
    }
    compose_overlap(candle, suffix, 0, max_results)
}
