//! Deterministic, finite-input quotient by an exact qualitative signature.
//! These counts apply only to the supplied slice, never to all legal patterns.

use super::schema::{Schema, Signature};
use crate::{geometry::GeometryPattern, Result};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservedClass {
    signature: Signature,
    /// Original input offsets. Repeated inputs remain separate observations.
    indices: Vec<usize>,
}

impl ObservedClass {
    pub fn signature(&self) -> &Signature {
        &self.signature
    }

    pub fn indices(&self) -> &[usize] {
        &self.indices
    }

    pub fn len(&self) -> usize {
        self.indices.len()
    }

    pub fn is_empty(&self) -> bool {
        self.indices.is_empty()
    }
}

/// Group caller-provided complete patterns by equal chosen observations.
/// The returned partition is exact, deterministic and independent of
/// encounter order except for its retained original indices. A class's size
/// is its frequency *in this input*, not its unobserved legal multiplicity.
pub fn partition_input(
    schema: &Schema,
    patterns: &[GeometryPattern],
) -> Result<Vec<ObservedClass>> {
    // The basis is constant: index only the selected value vectors, then
    // attach one exact schema per class, not a schema clone per observation.
    let mut groups = BTreeMap::<_, Vec<usize>>::new();
    for (i, pattern) in patterns.iter().enumerate() {
        let values = schema.values_for(pattern)?;
        groups.entry(values).or_default().push(i);
    }
    Ok(groups
        .into_iter()
        .map(|((relations, directions), indices)| ObservedClass {
            signature: schema.attach(relations, directions),
            indices,
        })
        .collect())
}
