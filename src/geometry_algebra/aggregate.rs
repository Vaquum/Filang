use super::project::canonicalize_rows;
use crate::{
    geometry::{BodyDirection, GeometryMode, GeometryPattern},
    Result,
};
use std::cmp::Ordering;

/// Order of candle rows supplied to aggregation. Existing Filang consumers
/// may store a window newest-first; algebra must not silently reinterpret it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CandleOrder {
    OldestFirst,
    NewestFirst,
}

/// Exact OHLC aggregation of consecutive nonempty groups, expressed entirely
/// in canonical endpoint ranks. group_lengths must sum to pattern.len().
///
/// Oriented input is essential: open is the chronologically first constituent
/// candle's open and close is the chronologically final candle's close. Neither
/// can generally be recovered from an unoriented body interval.
///
/// CandleOrder declares how existing pattern rows were arranged. Output groups
/// retain that same arrangement. This operation makes no assumptions about
/// input timestamps, missing periods, execution, or volume aggregation.
pub fn aggregate_partition(
    pattern: &GeometryPattern,
    group_lengths: &[usize],
    order: CandleOrder,
) -> Result<GeometryPattern> {
    if pattern.mode() != GeometryMode::Oriented {
        return Err("geometry algebra: exact aggregation requires oriented geometry".into());
    }
    if group_lengths.iter().any(|&size| size == 0) {
        return Err("geometry algebra: aggregation groups must be nonempty".into());
    }
    let total = group_lengths.iter().try_fold(0usize, |acc, &size| {
        acc.checked_add(size)
            .ok_or("geometry algebra: aggregation group lengths overflow")
    })?;
    if total != pattern.len() {
        return Err("geometry algebra: aggregation groups must partition all candles".into());
    }
    let mut rows = Vec::with_capacity(group_lengths.len());
    let mut directions = Vec::with_capacity(group_lengths.len());
    let input = pattern.ranks();
    let body_directions = pattern.directions().unwrap();
    let mut start = 0usize;
    for &size in group_lengths {
        let end = start + size;
        let (first, last) = match order {
            CandleOrder::OldestFirst => (start, end - 1),
            CandleOrder::NewestFirst => (end - 1, start),
        };
        let open = match body_directions[first] {
            BodyDirection::Up | BodyDirection::Flat => input[first][1],
            BodyDirection::Down => input[first][2],
        };
        let close = match body_directions[last] {
            BodyDirection::Down | BodyDirection::Flat => input[last][1],
            BodyDirection::Up => input[last][2],
        };
        let low = input[start..end].iter().map(|row| row[0]).min().unwrap();
        let high = input[start..end].iter().map(|row| row[3]).max().unwrap();
        rows.push([low, open.min(close), open.max(close), high]);
        directions.push(match open.cmp(&close) {
            Ordering::Less => BodyDirection::Up,
            Ordering::Greater => BodyDirection::Down,
            Ordering::Equal => BodyDirection::Flat,
        });
        start = end;
    }
    canonicalize_rows(rows, Some(directions))
}

/// Aggregate adjacent fixed-size blocks into one candle per block, including
/// their complete global endpoint relationships. The length must be divisible
/// by block_size; zero is rejected. An empty oriented pattern remains empty.
///
/// With the same order and alignment, successive aggregation composes exactly:
/// A_m(A_k(g)) = A_(mk)(g).
pub fn aggregate_blocks(
    pattern: &GeometryPattern,
    block_size: usize,
    order: CandleOrder,
) -> Result<GeometryPattern> {
    if block_size == 0 {
        return Err("geometry algebra: aggregation block size must be positive".into());
    }
    if pattern.len() % block_size != 0 {
        return Err("geometry algebra: length not divisible by aggregation block size".into());
    }
    let groups = vec![block_size; pattern.len() / block_size];
    aggregate_partition(pattern, &groups, order)
}
