use crate::{
    geometry::{BodyDirection, Dimension, DimensionPart, GeometryPattern},
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
    let price = canonicalize_rows(rows, directions)?;
    if !pattern.has_dimensions() {
        return Ok(price);
    }
    // Each axis is re-ranked on its own over the surviving candles. A
    // reference point is not a candle, so it always stays.
    let parts = pattern
        .dimensions()
        .iter()
        .map(|part| {
            let mut ranks: Vec<usize> = indices.iter().map(|&i| part.ranks()[i]).collect();
            let mut reference = part.reference();
            let mut levels: Vec<usize> = ranks.iter().chain(reference.iter()).copied().collect();
            levels.sort_unstable();
            levels.dedup();
            for rank in ranks.iter_mut().chain(reference.iter_mut()) {
                *rank = levels
                    .binary_search(rank)
                    .expect("collected rank must exist");
            }
            DimensionPart::new(part.dimension(), ranks, reference)
        })
        .collect::<Result<Vec<_>>>()?;
    price.with_parts(parts)
}

/// Forget body directions while retaining the same complete endpoint weak
/// order. This is a many-to-one map; it has no inverse in general. Dimension
/// parts are kept as they are.
pub fn forget_orientation(pattern: &GeometryPattern) -> Result<GeometryPattern> {
    let price = GeometryPattern::new(pattern.ranks().to_vec(), None)?;
    if !pattern.has_dimensions() {
        return Ok(price);
    }
    price.with_parts(pattern.dimensions().to_vec())
}

/// Turn one dimension off: drop its part and keep everything else. The result
/// matches every window the input matches, and every window that differs from
/// it only on that axis. Forgetting a dimension that is already off returns
/// the pattern unchanged, so this is a projection. It commutes with `project`
/// and with `forget_orientation`.
pub fn forget_dimension(
    pattern: &GeometryPattern,
    dimension: Dimension,
) -> Result<GeometryPattern> {
    pattern.with_parts(
        pattern
            .dimensions()
            .iter()
            .filter(|part| part.dimension() != dimension)
            .cloned()
            .collect(),
    )
}
