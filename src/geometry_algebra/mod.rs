//! Exact qualitative operations on Filang's canonical candle geometry.
//!
//! This is an optional layer over the existing GeometryPattern representation.
//! It does not participate in data preparation, strategy search, execution,
//! or scoring. All results are canonical native patterns; no numeric prices,
//! new wire formats, or new geometry semantics are defined.
//!
//! Candle order always follows the caller's row order. For overlapping
//! successive windows in that order, the left suffix equals the right prefix.
//!
//! A pattern with dimensions on (docs/G1_DIMENSIONS.md) is one weak order per
//! axis. Projection re-ranks every axis; `forget_dimension` drops one;
//! composition completes each axis separately, so its count is the product
//! over the axes; aggregation is refused, because a merged candle's value on
//! a dimension is not determined by an order.
//!
//! See docs/QUALITATIVE_GEOMETRY_ALGEBRA.md for laws and resource boundaries.

mod aggregate;
mod compose;
mod project;

pub use aggregate::{aggregate_blocks, aggregate_partition, CandleOrder};
pub use compose::{
    append_one, compose_overlap, composition_count, overlap_compatible, prepend_one,
};
pub use project::{forget_dimension, forget_orientation, project};
