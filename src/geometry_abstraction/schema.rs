//! Caller-chosen qualitative comparisons: a schema is a projection of the
//! existing complete Filang endpoint-order geometry, not a learned model.

use crate::{
    geometry::{BodyDirection, Boundary, GeometryMode, GeometryPattern},
    Result,
};
use std::cmp::Ordering;

/// Resource boundary of this optional research layer. This is independent of
/// the existing geometry encoder's supported widths.
pub const MAX_ABSTRACTION_ENDPOINTS: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Endpoint {
    pub candle: usize,
    pub boundary: Boundary,
}

impl Endpoint {
    pub fn new(candle: usize, boundary: Boundary) -> Self {
        Self { candle, boundary }
    }

    fn part(self) -> usize {
        match self.boundary {
            Boundary::Low => 0,
            Boundary::BodyLow => 1,
            Boundary::BodyHigh => 2,
            Boundary::High => 3,
        }
    }

    pub(super) fn index(self) -> usize {
        self.candle * 4 + self.part()
    }
}

impl PartialOrd for Endpoint {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Endpoint {
    fn cmp(&self, other: &Self) -> Ordering {
        (self.candle, self.part()).cmp(&(other.candle, other.part()))
    }
}

/// A canonical pair of distinct endpoint labels. Comparison values always
/// mean relation of the smaller endpoint label to the larger endpoint label.
/// The pair's order is by candle index and then [L,b,t,H], not by price.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EndpointPair {
    pub(super) first: Endpoint,
    pub(super) second: Endpoint,
}

impl EndpointPair {
    pub fn first(self) -> Endpoint {
        self.first
    }

    pub fn second(self) -> Endpoint {
        self.second
    }

    pub fn new(a: Endpoint, b: Endpoint) -> Result<Self> {
        match a.cmp(&b) {
            Ordering::Equal => Err("geometry abstraction: pair endpoints must differ".into()),
            Ordering::Less => Ok(Self {
                first: a,
                second: b,
            }),
            Ordering::Greater => Ok(Self {
                first: b,
                second: a,
            }),
        }
    }

    fn validate(self, bars: usize) -> Result<()> {
        if self.first.candle >= bars || self.second.candle >= bars {
            return Err("geometry abstraction: comparison endpoint is outside schema".into());
        }
        Ok(())
    }
}

pub(super) fn pair_relation(pattern: &GeometryPattern, pair: EndpointPair) -> Ordering {
    pattern.ranks()[pair.first.candle][pair.first.part()]
        .cmp(&pattern.ranks()[pair.second.candle][pair.second.part()])
}

/// Exact, normalized selection of endpoint comparisons and optional oriented
/// body-direction observations. No probability, price lengths, or target
/// variables enter a schema.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Schema {
    bars: usize,
    mode: GeometryMode,
    pairs: Vec<EndpointPair>,
    direction_bars: Vec<usize>,
}

impl Schema {
    pub fn new(
        bars: usize,
        mode: GeometryMode,
        mut pairs: Vec<EndpointPair>,
        mut direction_bars: Vec<usize>,
    ) -> Result<Self> {
        let endpoints = bars
            .checked_mul(4)
            .ok_or("geometry abstraction: endpoint count overflow")?;
        if endpoints > MAX_ABSTRACTION_ENDPOINTS {
            return Err("geometry abstraction: schema exceeds endpoint budget".into());
        }
        pairs.sort_unstable();
        pairs.dedup();
        for &pair in &pairs {
            pair.validate(bars)?;
        }
        direction_bars.sort_unstable();
        direction_bars.dedup();
        if !direction_bars.is_empty() && mode != GeometryMode::Oriented {
            return Err("geometry abstraction: unoriented schema has no body directions".into());
        }
        if direction_bars.iter().any(|&i| i >= bars) {
            return Err("geometry abstraction: direction candle index outside schema".into());
        }
        Ok(Self {
            bars,
            mode,
            pairs,
            direction_bars,
        })
    }

    pub fn empty(bars: usize, mode: GeometryMode) -> Result<Self> {
        Self::new(bars, mode, vec![], vec![])
    }

    /// Full comparison basis: every endpoint pair plus every oriented body
    /// direction. Completeness is exact, but O((4n)^2) storage is deliberate.
    pub fn complete(bars: usize, mode: GeometryMode) -> Result<Self> {
        let endpoint_count = bars
            .checked_mul(4)
            .ok_or("geometry abstraction: endpoint count overflow")?;
        if endpoint_count > MAX_ABSTRACTION_ENDPOINTS {
            return Err("geometry abstraction: schema exceeds endpoint budget".into());
        }
        let mut pairs = Vec::new();
        for i in 0..endpoint_count {
            for j in i + 1..endpoint_count {
                pairs.push(EndpointPair::new(endpoint_at(i), endpoint_at(j))?);
            }
        }
        let dirs = if mode == GeometryMode::Oriented {
            (0..bars).collect()
        } else {
            Vec::new()
        };
        Self::new(bars, mode, pairs, dirs)
    }

    pub fn bars(&self) -> usize {
        self.bars
    }

    pub fn mode(&self) -> GeometryMode {
        self.mode
    }

    pub fn comparisons(&self) -> &[EndpointPair] {
        &self.pairs
    }

    pub fn direction_bars(&self) -> &[usize] {
        &self.direction_bars
    }

    pub fn with_comparison(&self, pair: EndpointPair) -> Result<Self> {
        let mut pairs = self.pairs.clone();
        pairs.push(pair);
        Self::new(self.bars, self.mode, pairs, self.direction_bars.clone())
    }

    pub fn with_direction(&self, candle: usize) -> Result<Self> {
        let mut directions = self.direction_bars.clone();
        directions.push(candle);
        Self::new(self.bars, self.mode, self.pairs.clone(), directions)
    }

    fn check_domain(&self, other: &Self) -> Result<()> {
        if self.bars != other.bars || self.mode != other.mode {
            return Err("geometry abstraction: schema domains differ".into());
        }
        Ok(())
    }

    /// Syntactic lattice join: preserve every comparison and direction
    /// selected by either schema. This refines each operand.
    pub fn join(&self, other: &Self) -> Result<Self> {
        self.check_domain(other)?;
        let mut pairs = self.pairs.clone();
        pairs.extend_from_slice(&other.pairs);
        let mut dirs = self.direction_bars.clone();
        dirs.extend_from_slice(&other.direction_bars);
        Self::new(self.bars, self.mode, pairs, dirs)
    }

    /// Syntactic lattice meet: keep only selected observations common to
    /// both schemas. This is a coarsening of each operand.
    pub fn meet(&self, other: &Self) -> Result<Self> {
        self.check_domain(other)?;
        let pairs = self
            .pairs
            .iter()
            .filter(|pair| other.pairs.binary_search(pair).is_ok())
            .copied()
            .collect();
        let dirs = self
            .direction_bars
            .iter()
            .filter(|i| other.direction_bars.binary_search(i).is_ok())
            .copied()
            .collect();
        Self::new(self.bars, self.mode, pairs, dirs)
    }

    pub fn is_refinement_of(&self, coarse: &Self) -> bool {
        self.bars == coarse.bars
            && self.mode == coarse.mode
            && coarse
                .pairs
                .iter()
                .all(|pair| self.pairs.binary_search(pair).is_ok())
            && coarse
                .direction_bars
                .iter()
                .all(|i| self.direction_bars.binary_search(i).is_ok())
    }

    pub(super) fn values_for(
        &self,
        pattern: &GeometryPattern,
    ) -> Result<(Vec<Ordering>, Vec<BodyDirection>)> {
        if pattern.len() != self.bars || pattern.mode() != self.mode {
            return Err("geometry abstraction: pattern width or mode differs from schema".into());
        }
        let relations = self
            .pairs
            .iter()
            .map(|&pair| pair_relation(pattern, pair))
            .collect();
        let directions = match pattern.directions() {
            Some(all) => self.direction_bars.iter().map(|&i| all[i]).collect(),
            None => Vec::new(),
        };
        Ok((relations, directions))
    }

    pub(super) fn attach(
        &self,
        relations: Vec<Ordering>,
        directions: Vec<BodyDirection>,
    ) -> Signature {
        Signature {
            schema: self.clone(),
            relations,
            directions,
        }
    }

    pub fn signature(&self, pattern: &GeometryPattern) -> Result<Signature> {
        let (relations, directions) = self.values_for(pattern)?;
        Ok(self.attach(relations, directions))
    }

    /// Plug into the Phase 1 projection without changing the core geometry
    /// encoder. Indices are increasing positions in the source row order.
    pub fn signature_on_projection(
        &self,
        source: &GeometryPattern,
        indices: &[usize],
    ) -> Result<Signature> {
        let projected = crate::geometry_algebra::project(source, indices)?;
        self.signature(&projected)
    }

    /// Pull this schema's selected comparisons back along a Phase 1 window
    /// projection. For source indices I:
    ///
    /// values(signature_S(project_I(g))) ==
    /// values(signature_(lift_I(S))(g)).
    ///
    /// The schema identities differ; their selected *values* are identical.
    pub fn lift_to(&self, source_bars: usize, indices: &[usize]) -> Result<Self> {
        if indices.len() != self.bars {
            return Err("geometry abstraction: lift indices must match schema width".into());
        }
        if indices.iter().any(|&i| i >= source_bars) || indices.windows(2).any(|w| w[0] >= w[1]) {
            return Err(
                "geometry abstraction: lifted candle indices must increase within source".into(),
            );
        }
        let pairs = self
            .pairs
            .iter()
            .map(|pair| {
                EndpointPair::new(
                    Endpoint::new(indices[pair.first.candle], pair.first.boundary),
                    Endpoint::new(indices[pair.second.candle], pair.second.boundary),
                )
            })
            .collect::<Result<Vec<_>>>()?;
        let directions = self.direction_bars.iter().map(|&i| indices[i]).collect();
        Self::new(source_bars, self.mode, pairs, directions)
    }

    /// Project a finer signature onto an actual subset of the finer schema.
    /// No complete original pattern is needed. It never guesses relations
    /// implied transitively by other observations: this is literal projection.
    pub fn coarsen(&self, fine: &Signature) -> Result<Signature> {
        if !fine.schema.is_refinement_of(self) {
            return Err("geometry abstraction: target signature is not a schema refinement".into());
        }
        let relations = self
            .pairs
            .iter()
            .map(|pair| {
                let index = fine.schema.pairs.binary_search(pair).unwrap();
                fine.relations[index]
            })
            .collect();
        let directions = self
            .direction_bars
            .iter()
            .map(|bar| {
                let index = fine.schema.direction_bars.binary_search(bar).unwrap();
                fine.directions[index]
            })
            .collect();
        Ok(Signature {
            schema: self.clone(),
            relations,
            directions,
        })
    }
}

fn endpoint_at(index: usize) -> Endpoint {
    let boundary = match index % 4 {
        0 => Boundary::Low,
        1 => Boundary::BodyLow,
        2 => Boundary::BodyHigh,
        _ => Boundary::High,
    };
    Endpoint::new(index / 4, boundary)
}

pub(super) fn all_endpoints(bars: usize) -> Vec<Endpoint> {
    (0..bars * 4).map(endpoint_at).collect()
}

/// A partial qualitative description, identified by its *entire* schema,
/// not a lossy hash or an unversioned vector of relation values.
///
/// Within one schema, equality of signatures defines an exact equivalence
/// relation on legal complete geometries.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Signature {
    schema: Schema,
    relations: Vec<Ordering>,
    directions: Vec<BodyDirection>,
}

impl Signature {
    pub fn schema(&self) -> &Schema {
        &self.schema
    }

    pub fn relations(&self) -> &[Ordering] {
        &self.relations
    }

    pub fn directions(&self) -> &[BodyDirection] {
        &self.directions
    }

    pub fn matches(&self, pattern: &GeometryPattern) -> Result<bool> {
        Ok(self.schema.signature(pattern)? == *self)
    }

    pub fn relation(&self, pair: EndpointPair) -> Option<Ordering> {
        self.schema
            .pairs
            .binary_search(&pair)
            .ok()
            .map(|i| self.relations[i])
    }

    pub fn direction(&self, candle: usize) -> Option<BodyDirection> {
        self.schema
            .direction_bars
            .binary_search(&candle)
            .ok()
            .map(|i| self.directions[i])
    }
}
