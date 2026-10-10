//! Opt-in structural abstraction of the existing Filang geometry language.
//!
//! Schemas contain caller-selected endpoint comparisons and body directions.
//! Their signatures induce exact equivalence classes on complete geometries,
//! with no learned parameters, hidden tolerances, or assumptions about which
//! qualitative relations carry predictive information.
//!
//! Full geometries may be decomposed into a signature and a small, exact
//! residual certificate. The pair reconstructs the original native pattern.
//!
//! This namespace consumes geometry::GeometryPattern and does not modify the
//! Phase 1 geometry algebra, the search engine, or any dataset-specific path.
//! See docs/QUALITATIVE_GEOMETRY_ABSTRACTION.md.

mod certificate;
mod classes;
mod schema;

pub use certificate::{ExactFactorization, Residual};
pub use classes::{partition_input, ObservedClass};
pub use schema::{Endpoint, EndpointPair, Schema, Signature, MAX_ABSTRACTION_ENDPOINTS};
