//! Exact factorization of a complete Filang pattern into a caller-selected
//! qualitative signature and a finite residual reconstruction certificate.
//! No information about a full pattern is discarded when the residual is kept.

use super::schema::{all_endpoints, pair_relation, EndpointPair, Schema, Signature};
use crate::{
    geometry::{BodyDirection, GeometryMode, GeometryPattern},
    Result,
};
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet},
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Residual {
    /// Comparison edges omitted from the schema, sufficient together with
    /// its selected edges to reconstruct the entire endpoint weak order.
    comparisons: Vec<(EndpointPair, Ordering)>,
    /// Exact oriented directions omitted from the schema.
    directions: Vec<(usize, BodyDirection)>,
}

impl Residual {
    pub fn comparisons(&self) -> &[(EndpointPair, Ordering)] {
        &self.comparisons
    }

    pub fn directions(&self) -> &[(usize, BodyDirection)] {
        &self.directions
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactFactorization {
    signature: Signature,
    residual: Residual,
}

impl ExactFactorization {
    /// Emit an exact linear-size witness: equality links inside each global
    /// level, strict links between neighboring global levels, and omitted
    /// body directions. The witness has at most 4*n-1 comparison edges.
    ///
    /// Chosen schema edges already carry their values in the signature, so
    /// any matching witness edge is omitted rather than duplicated.
    pub fn from_pattern(schema: &Schema, pattern: &GeometryPattern) -> Result<Self> {
        let signature = schema.signature(pattern)?;
        let mut levels = vec![Vec::new(); pattern.level_count()];
        for endpoint in all_endpoints(pattern.len()) {
            let index = endpoint.index();
            let rank = pattern.ranks()[index / 4][index % 4];
            levels[rank].push(endpoint);
        }
        let mut comparisons = Vec::new();
        let mut add = |a, b| -> Result<()> {
            let pair = EndpointPair::new(a, b)?;
            if schema.comparisons().binary_search(&pair).is_err() {
                comparisons.push((pair, pair_relation(pattern, pair)));
            }
            Ok(())
        };
        for group in &levels {
            for &member in group.iter().skip(1) {
                add(group[0], member)?;
            }
        }
        for pair in levels.windows(2) {
            add(pair[0][0], pair[1][0])?;
        }
        // Schema equality is canonical. The residual ordering has no bearing
        // on reconstruction, but sort for deterministic inspection.
        comparisons.sort_unstable_by_key(|(pair, _)| *pair);
        let directions = match pattern.directions() {
            Some(dirs) => dirs
                .iter()
                .enumerate()
                .filter(|(i, _)| schema.direction_bars().binary_search(i).is_err())
                .map(|(i, &direction)| (i, direction))
                .collect(),
            None => Vec::new(),
        };
        Ok(Self {
            signature,
            residual: Residual {
                comparisons,
                directions,
            },
        })
    }

    pub fn signature(&self) -> &Signature {
        &self.signature
    }

    pub fn residual(&self) -> &Residual {
        &self.residual
    }

    /// Recover and validate the unique full native geometry implied by the
    /// signature plus residual. Rejects a missing, cyclic, conflicting, or
    /// semantically invalid description; never guesses a missing comparison.
    ///
    /// This is an independent graph reconstruction, not a stored clone of
    /// the original GeometryPattern and not an inverse of signature alone.
    pub fn reconstruct(&self) -> Result<GeometryPattern> {
        let schema = self.signature.schema();
        let bars = schema.bars();
        let endpoint_count = bars * 4;
        let mut ds = DisjointSet::new(endpoint_count);
        let constraints = schema
            .comparisons()
            .iter()
            .copied()
            .zip(self.signature.relations().iter().copied())
            .chain(self.residual.comparisons.iter().copied())
            .collect::<Vec<_>>();

        // Equal endpoints are one price level, regardless of how many
        // differently labeled equalities identify the same level.
        for &(pair, relation) in &constraints {
            if pair.first.candle >= bars || pair.second.candle >= bars {
                return Err("geometry abstraction: residual references invalid endpoint".into());
            }
            if relation == Ordering::Equal {
                ds.join(pair.first.index(), pair.second.index());
            }
        }
        let mut classes = BTreeMap::<usize, usize>::new();
        let mut class_at = Vec::with_capacity(endpoint_count);
        for endpoint in 0..endpoint_count {
            let root = ds.root(endpoint);
            let next = classes.len();
            let group = *classes.entry(root).or_insert(next);
            class_at.push(group);
        }

        // Every strict comparison is a directed edge on the quotient graph.
        let group_count = classes.len();
        let mut edge_set = BTreeSet::<(usize, usize)>::new();
        for &(pair, relation) in &constraints {
            let a = class_at[pair.first.index()];
            let b = class_at[pair.second.index()];
            match relation {
                Ordering::Equal => {
                    if a != b {
                        return Err("geometry abstraction: inconsistent equality".into());
                    }
                }
                Ordering::Less | Ordering::Greater => {
                    if a == b {
                        return Err(
                            "geometry abstraction: strict relation contradicts equality".into()
                        );
                    }
                    let edge = if relation == Ordering::Less {
                        (a, b)
                    } else {
                        (b, a)
                    };
                    edge_set.insert(edge);
                }
            }
        }
        let mut incoming = vec![0usize; group_count];
        let mut outgoing = vec![Vec::new(); group_count];
        for (a, b) in edge_set {
            incoming[b] += 1;
            outgoing[a].push(b);
        }

        // A unique topological order is equivalent to a fully determined
        // strict order of distinct global endpoint equality classes.
        let mut used = vec![false; group_count];
        let mut ranks_for_class = vec![0usize; group_count];
        for rank in 0..group_count {
            let roots = (0..group_count)
                .filter(|&i| !used[i] && incoming[i] == 0)
                .collect::<Vec<_>>();
            let root = match roots.as_slice() {
                [] => return Err("geometry abstraction: cyclic strict relations".into()),
                [one] => *one,
                _ => {
                    return Err(
                        "geometry abstraction: insufficient comparisons for unique order".into(),
                    )
                }
            };
            used[root] = true;
            ranks_for_class[root] = rank;
            for &next in &outgoing[root] {
                incoming[next] -= 1;
            }
        }

        let mut rows = vec![[0usize; 4]; bars];
        for (i, group) in class_at.iter().enumerate() {
            rows[i / 4][i % 4] = ranks_for_class[*group];
        }
        let directions = if schema.mode() == GeometryMode::Oriented {
            let mut chosen = vec![None; bars];
            for (&i, &d) in schema
                .direction_bars()
                .iter()
                .zip(self.signature.directions())
                .chain(self.residual.directions.iter().map(|(i, d)| (i, d)))
            {
                if i >= bars || chosen[i].map_or(false, |old| old != d) {
                    return Err(
                        "geometry abstraction: conflicting or out-of-range direction".into(),
                    );
                }
                chosen[i] = Some(d);
            }
            Some(
                chosen
                    .into_iter()
                    .collect::<Option<Vec<_>>>()
                    .ok_or("geometry abstraction: incomplete body direction information")?,
            )
        } else {
            if !self.residual.directions.is_empty() {
                return Err("geometry abstraction: unoriented residual contains directions".into());
            }
            None
        };
        GeometryPattern::new(rows, directions)
    }
}

#[derive(Clone)]
struct DisjointSet {
    parent: Vec<usize>,
}

impl DisjointSet {
    fn new(count: usize) -> Self {
        Self {
            parent: (0..count).collect(),
        }
    }

    fn root(&mut self, x: usize) -> usize {
        let mut current = x;
        while self.parent[current] != current {
            current = self.parent[current];
        }
        let root = current;
        let mut cursor = x;
        while self.parent[cursor] != cursor {
            let next = self.parent[cursor];
            self.parent[cursor] = root;
            cursor = next;
        }
        root
    }

    fn join(&mut self, a: usize, b: usize) {
        let ar = self.root(a);
        let br = self.root(b);
        if ar != br {
            // Endpoint count is explicitly bounded in schema construction,
            // so no recursion or unbounded path compression is necessary.
            self.parent[ar] = br;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn incomplete_conflicting_and_invalid_witnesses_fail_closed() {
        let schema = Schema::empty(1, GeometryMode::Oriented).unwrap();
        let pattern: GeometryPattern = "g1:o:0,1,2,3,u".parse().unwrap();
        let f = ExactFactorization::from_pattern(&schema, &pattern).unwrap();
        assert_eq!(f.reconstruct().unwrap(), pattern);
        let mut incomplete = f.clone();
        incomplete.residual.comparisons.pop();
        assert!(incomplete.reconstruct().is_err());
        let mut invalid = f.clone();
        invalid.residual.directions[0].1 = BodyDirection::Flat;
        assert!(invalid.reconstruct().is_err());
        let mut reversed = f.clone();
        reversed.residual.comparisons[0].1 = Ordering::Greater;
        assert!(reversed.reconstruct().is_err());
        let mut missing = f;
        missing.residual.directions.clear();
        assert!(missing.reconstruct().is_err());
    }
}
