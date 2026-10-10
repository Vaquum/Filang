use crate::{
    geometry::{BodyDirection, GeometryPattern},
    Result,
};

/// Reassign ranks in a collection of ordered candle rows without changing any
/// surviving endpoint comparison. Only checked native patterns are produced.
/// Used by projection and aggregation, not exposed to the existing engine.
pub(super) fn canonicalize_rows(
    mut rows: Vec<[usize; 4]>,
    directions: Option<Vec<BodyDirection>>,
) -> Result<GeometryPattern> {
    let mut levels: Vec<usize> = rows.iter().flat_map(|row| row.iter().copied()).collect();
    levels.sort_unstable();
    levels.dedup();
    for row in &mut rows {
        for rank in row {
            *rank = levels
                .binary_search(rank)
                .expect("collected rank must exist");
        }
    }
    GeometryPattern::new(rows, directions)
}

/// Restrict a complete pattern to strictly increasing candle indices, then
/// re-canonicalize the surviving global weak order. Empty selection is legal.
///
/// Index order is preserved rather than rearranged: selection may omit rows,
/// but it cannot permute the meaning of chronological positions.
pub fn project(pattern: &GeometryPattern, indices: &[usize]) -> Result<GeometryPattern> {
    if indices.iter().any(|&i| i >= pattern.len()) {
        return Err("geometry algebra: projection index out of range".into());
    }
    if indices.windows(2).any(|window| window[0] >= window[1]) {
        return Err("geometry algebra: projection indices must strictly increase".into());
    }
    let rows = indices.iter().map(|&i| pattern.ranks()[i]).collect();
    let directions = pattern
        .directions()
        .map(|all| indices.iter().map(|&i| all[i]).collect());
    canonicalize_rows(rows, directions)
}

/// Forget body directions while retaining the same complete endpoint weak
/// order. This is a many-to-one map; it has no inverse in general.
pub fn forget_orientation(pattern: &GeometryPattern) -> Result<GeometryPattern> {
    GeometryPattern::new(pattern.ranks().to_vec(), None)
}
