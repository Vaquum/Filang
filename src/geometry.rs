//! Complete qualitative body-and-wick geometry.
//!
//! A candle has the ordered boundaries `[low, body_low, body_high, high]`.
//! Equal adjacent boundaries express absent wicks and zero-height bodies.
//! Patterns retain the single global weak order of every boundary, including
//! nonadjacent candles. They are invariant under any strictly increasing price
//! remapping; lengths and ratios are intentionally not part of this language.
//!
//! The versioned wire format is `g1:u:r,r,r,r;...` for unoriented geometry and
//! `g1:o:r,r,r,r,d;...` for oriented geometry, where direction is `d`, `z`, or
//! `u`. Ranks are consecutive integers starting at zero. Candle order is the
//! order supplied by the caller; the encoding never sorts candles by time.

use crate::Result;
use std::{cmp::Ordering, collections::HashSet, fmt, str::FromStr};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GeometryMode {
    Unoriented,
    Oriented,
}

impl GeometryMode {
    pub fn parse(text: &str) -> Result<Self> {
        match text {
            "unoriented" => Ok(Self::Unoriented),
            "oriented" => Ok(Self::Oriented),
            _ => Err("geometry mode must be unoriented or oriented".into()),
        }
    }

    fn weights(self) -> [u128; 5] {
        match self {
            Self::Unoriented => [0, 1, 3, 3, 1],
            Self::Oriented => [0, 1, 4, 5, 2],
        }
    }
}

impl fmt::Display for GeometryMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Unoriented => "unoriented",
            Self::Oriented => "oriented",
        })
    }
}

impl FromStr for GeometryMode {
    type Err = String;
    fn from_str(text: &str) -> Result<Self> {
        Self::parse(text)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BodyDirection {
    Down,
    Flat,
    Up,
}

impl BodyDirection {
    fn token(self) -> &'static str {
        match self {
            Self::Down => "d",
            Self::Flat => "z",
            Self::Up => "u",
        }
    }

    fn parse(text: &str) -> Result<Self> {
        match text {
            "d" => Ok(Self::Down),
            "z" => Ok(Self::Flat),
            "u" => Ok(Self::Up),
            _ => Err("geometry body direction must be d, z, or u".into()),
        }
    }

    fn from_ohlc(open: f64, close: f64) -> Self {
        if open < close {
            Self::Up
        } else if open > close {
            Self::Down
        } else {
            Self::Flat
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Boundary {
    Low,
    BodyLow,
    BodyHigh,
    High,
}

impl Boundary {
    fn index(self) -> usize {
        match self {
            Self::Low => 0,
            Self::BodyLow => 1,
            Self::BodyHigh => 2,
            Self::High => 3,
        }
    }
}

/// A canonical global boundary order. Private fields ensure every public
/// constructor checks rank density, internal candle order, and directions.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GeometryPattern {
    ranks: Vec<[usize; 4]>,
    directions: Option<Vec<BodyDirection>>,
}

impl GeometryPattern {
    pub fn new(ranks: Vec<[usize; 4]>, directions: Option<Vec<BodyDirection>>) -> Result<Self> {
        let pattern = Self { ranks, directions };
        pattern.validate()?;
        Ok(pattern)
    }

    /// OHLC rows are `[open, high, low, close]`. Finite negative and zero
    /// heights are legal abstract geometry; CSV price restrictions belong to
    /// the data reader. Opening gaps are legal, and equalities are exact.
    pub fn from_ohlc(rows: &[[f64; 4]], mode: GeometryMode) -> Result<Self> {
        let mut encoder = GeometryEncoder::new(rows.len(), mode)?;
        encoder.encode_ohlc(rows)?;
        Ok(encoder.pattern)
    }

    /// Endpoint rows are `[low, body_low, body_high, high]`. Oriented mode
    /// requires one direction per row; unoriented mode requires `None`.
    pub fn from_endpoints(
        rows: &[[f64; 4]],
        mode: GeometryMode,
        directions: Option<&[BodyDirection]>,
    ) -> Result<Self> {
        let mut encoder = GeometryEncoder::new(rows.len(), mode)?;
        encoder.encode_endpoints(rows, directions)?;
        Ok(encoder.pattern)
    }

    pub fn mode(&self) -> GeometryMode {
        if self.directions.is_some() {
            GeometryMode::Oriented
        } else {
            GeometryMode::Unoriented
        }
    }

    pub fn len(&self) -> usize {
        self.ranks.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ranks.is_empty()
    }

    pub fn ranks(&self) -> &[[usize; 4]] {
        &self.ranks
    }

    pub fn directions(&self) -> Option<&[BodyDirection]> {
        self.directions.as_deref()
    }

    pub fn level_count(&self) -> usize {
        self.ranks.iter().map(|r| r[3] + 1).max().unwrap_or(0)
    }

    pub fn validate(&self) -> Result<()> {
        let capacity = self
            .len()
            .checked_mul(4)
            .ok_or("geometry endpoint count overflow")?;
        if let Some(directions) = &self.directions {
            if directions.len() != self.len() {
                return Err("geometry direction count does not match candle count".into());
            }
        }
        // Check bounds before allocating by rank. Malformed serialized ranks
        // must not cause a huge allocation or an integer overflow.
        for (i, ranks) in self.ranks.iter().enumerate() {
            if ranks.windows(2).any(|w| w[0] > w[1]) {
                return Err(format!("geometry candle {i}: boundaries are not ordered"));
            }
            if ranks[3] >= capacity {
                return Err(format!("geometry candle {i}: rank outside endpoint count"));
            }
            if let Some(directions) = &self.directions {
                validate_direction(ranks[1] == ranks[2], directions[i], i)?;
            }
        }
        let levels = self.level_count();
        let mut used = vec![false; levels];
        for ranks in &self.ranks {
            for &rank in ranks {
                used[rank] = true;
            }
        }
        if used.iter().any(|used| !used) {
            return Err("geometry ranks must be dense and start at zero".into());
        }
        Ok(())
    }

    /// Compare any two boundaries, including boundaries on nonadjacent bars.
    pub fn boundary_cmp(
        &self,
        a_bar: usize,
        a_boundary: Boundary,
        b_bar: usize,
        b_boundary: Boundary,
    ) -> Result<Ordering> {
        let a = self
            .ranks
            .get(a_bar)
            .ok_or("geometry candle index out of range")?;
        let b = self
            .ranks
            .get(b_bar)
            .ok_or("geometry candle index out of range")?;
        Ok(a[a_boundary.index()].cmp(&b[b_boundary.index()]))
    }

    pub fn matches_ohlc(&self, rows: &[[f64; 4]]) -> Result<bool> {
        Ok(*self == Self::from_ohlc(rows, self.mode())?)
    }

    pub fn matches_endpoints(
        &self,
        rows: &[[f64; 4]],
        directions: Option<&[BodyDirection]>,
    ) -> Result<bool> {
        Ok(*self == Self::from_endpoints(rows, self.mode(), directions)?)
    }
}

impl fmt::Display for GeometryPattern {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(if self.mode() == GeometryMode::Unoriented {
            "g1:u:"
        } else {
            "g1:o:"
        })?;
        for (i, r) in self.ranks.iter().enumerate() {
            if i > 0 {
                f.write_str(";")?;
            }
            write!(f, "{},{},{},{}", r[0], r[1], r[2], r[3])?;
            if let Some(directions) = &self.directions {
                write!(f, ",{}", directions[i].token())?;
            }
        }
        Ok(())
    }
}

impl FromStr for GeometryPattern {
    type Err = String;
    fn from_str(text: &str) -> Result<Self> {
        let (mode, body) = if let Some(body) = text.strip_prefix("g1:u:") {
            (GeometryMode::Unoriented, body)
        } else if let Some(body) = text.strip_prefix("g1:o:") {
            (GeometryMode::Oriented, body)
        } else {
            return Err("geometry pattern must begin g1:u: or g1:o:".into());
        };
        let mut ranks = Vec::new();
        let mut directions = if mode == GeometryMode::Oriented {
            Some(Vec::new())
        } else {
            None
        };
        if !body.is_empty() {
            for row in body.split(';') {
                let mut fields = row.split(',');
                let mut r = [0usize; 4];
                for rank in &mut r {
                    let token = fields.next().ok_or("geometry candle needs four ranks")?;
                    if token.is_empty()
                        || !token.bytes().all(|b| b.is_ascii_digit())
                        || (token.len() > 1 && token.starts_with('0'))
                    {
                        return Err("geometry ranks must be canonical unsigned decimals".into());
                    }
                    *rank = token.parse().map_err(|_| "geometry rank overflow")?;
                }
                if let Some(directions) = &mut directions {
                    let token = fields.next().ok_or("oriented geometry needs a direction")?;
                    directions.push(BodyDirection::parse(token)?);
                }
                if fields.next().is_some() {
                    return Err("too many fields in geometry candle".into());
                }
                ranks.push(r);
            }
        }
        Self::new(ranks, directions)
    }
}

/// Reuses all storage across equal-width windows. Encoding performs no heap
/// allocation after construction; callers can look up the returned borrowed
/// pattern in a bank and clone it only on the first occurrence.
pub struct GeometryEncoder {
    values: Vec<f64>,
    order: Vec<usize>,
    pattern: GeometryPattern,
}

impl GeometryEncoder {
    pub fn new(n: usize, mode: GeometryMode) -> Result<Self> {
        let endpoints = n.checked_mul(4).ok_or("geometry endpoint count overflow")?;
        let mut values = Vec::new();
        values
            .try_reserve_exact(endpoints)
            .map_err(|_| "geometry encoder allocation failed")?;
        values.resize(endpoints, 0.0);
        let mut order = Vec::new();
        order
            .try_reserve_exact(endpoints)
            .map_err(|_| "geometry encoder allocation failed")?;
        order.extend(0..endpoints);
        let mut ranks = Vec::new();
        ranks
            .try_reserve_exact(n)
            .map_err(|_| "geometry encoder allocation failed")?;
        ranks.resize(n, [0; 4]);
        let directions = if mode == GeometryMode::Oriented {
            let mut directions = Vec::new();
            directions
                .try_reserve_exact(n)
                .map_err(|_| "geometry encoder allocation failed")?;
            directions.resize(n, BodyDirection::Flat);
            Some(directions)
        } else {
            None
        };
        Ok(Self {
            values,
            order,
            pattern: GeometryPattern { ranks, directions },
        })
    }

    pub fn encode_ohlc(&mut self, rows: &[[f64; 4]]) -> Result<&GeometryPattern> {
        if rows.len() != self.pattern.len() {
            return Err("geometry encoder candle count mismatch".into());
        }
        for (i, row) in rows.iter().enumerate() {
            if row.iter().any(|x| !x.is_finite()) {
                return Err(format!("geometry candle {i}: non-finite OHLC"));
            }
            let [open, high, low, close] = *row;
            let body_low = open.min(close);
            let body_high = open.max(close);
            if low > body_low || body_high > high {
                return Err(format!("geometry candle {i}: invalid OHLC boundaries"));
            }
            self.values[4 * i..4 * i + 4].copy_from_slice(&[low, body_low, body_high, high]);
            if let Some(directions) = &mut self.pattern.directions {
                directions[i] = BodyDirection::from_ohlc(open, close);
            }
        }
        self.rank_values();
        Ok(&self.pattern)
    }

    pub fn encode_endpoints(
        &mut self,
        rows: &[[f64; 4]],
        directions: Option<&[BodyDirection]>,
    ) -> Result<&GeometryPattern> {
        if rows.len() != self.pattern.len() {
            return Err("geometry encoder candle count mismatch".into());
        }
        match (self.pattern.mode(), directions) {
            (GeometryMode::Unoriented, None) => {}
            (GeometryMode::Oriented, Some(d)) if d.len() == rows.len() => {}
            _ => return Err("geometry directions do not match mode and candle count".into()),
        }
        for (i, row) in rows.iter().enumerate() {
            if row.iter().any(|x| !x.is_finite()) {
                return Err(format!("geometry candle {i}: non-finite boundary"));
            }
            if row.windows(2).any(|w| w[0] > w[1]) {
                return Err(format!("geometry candle {i}: boundaries are not ordered"));
            }
            if let Some(directions) = directions {
                validate_direction(row[1] == row[2], directions[i], i)?;
            }
            self.values[4 * i..4 * i + 4].copy_from_slice(row);
        }
        if let (Some(destination), Some(source)) = (&mut self.pattern.directions, directions) {
            destination.copy_from_slice(source);
        }
        self.rank_values();
        Ok(&self.pattern)
    }

    fn rank_values(&mut self) {
        let values = &self.values;
        self.order.sort_unstable_by(|a, b| {
            // Every input was checked finite. Use numeric equality, so the
            // IEEE representations -0.0 and +0.0 share one price level.
            values[*a]
                .partial_cmp(&values[*b])
                .expect("finite geometry values")
                .then_with(|| a.cmp(b))
        });
        let mut previous = None;
        let mut rank = 0;
        for &index in &self.order {
            let value = self.values[index];
            if let Some(prior) = previous {
                if value != prior {
                    rank += 1;
                }
            }
            self.pattern.ranks[index / 4][index % 4] = rank;
            previous = Some(value);
        }
    }
}

fn validate_direction(flat: bool, direction: BodyDirection, candle: usize) -> Result<()> {
    if flat != (direction == BodyDirection::Flat) {
        return Err(format!(
            "geometry candle {candle}: direction disagrees with body height"
        ));
    }
    Ok(())
}

/// Exact cardinality of the full legal n-candle universe. The empty sequence
/// has one pattern. Overflow is an error, never saturation or truncation.
pub fn count_domain(n: usize, mode: GeometryMode) -> Result<u128> {
    checked_total(&count_domain_by_levels(n, mode)?)
}

/// Exact counts indexed by the number of distinct global price levels.
///
/// Adding a candle with k local levels to r existing levels, with j cross
/// ties, gives r+k-j levels. Its merge coefficient is
/// `(r+k-j)! / ((r-j)! (k-j)! j!)`. The local-shape weights are
/// `[1,3,3,1]` without orientation and `[1,4,5,2]` with orientation.
pub fn count_domain_by_levels(n: usize, mode: GeometryMode) -> Result<Vec<u128>> {
    let weights = mode.weights();
    let mut counts = vec![1u128];
    // Grow one candle at a time: even a hostile enormous n encounters a
    // checked u128 overflow before requesting a large allocation.
    for _ in 0..n {
        let length = counts
            .len()
            .checked_add(4)
            .ok_or("geometry count dimension overflow")?;
        let mut next = vec![0u128; length];
        for (r, &count) in counts.iter().enumerate() {
            if count == 0 {
                continue;
            }
            for (k, &weight) in weights.iter().enumerate().skip(1) {
                for j in 0..=r.min(k) {
                    let levels = r + k - j;
                    let coefficient = choose(levels, k)?
                        .checked_mul(choose(k, j)?)
                        .ok_or("geometry domain count exceeds u128")?;
                    let increment = count
                        .checked_mul(weight)
                        .and_then(|x| x.checked_mul(coefficient))
                        .ok_or("geometry domain count exceeds u128")?;
                    next[levels] = next[levels]
                        .checked_add(increment)
                        .ok_or("geometry domain count exceeds u128")?;
                }
            }
        }
        checked_total(&next)?;
        counts = next;
    }
    Ok(counts)
}

fn checked_total(counts: &[u128]) -> Result<u128> {
    counts.iter().try_fold(0u128, |total, count| {
        total
            .checked_add(*count)
            .ok_or_else(|| "geometry domain count exceeds u128".into())
    })
}

fn gcd(mut a: u128, mut b: u128) -> u128 {
    while b != 0 {
        let remainder = a % b;
        a = b;
        b = remainder;
    }
    a
}

fn choose(n: usize, k: usize) -> Result<u128> {
    if k > n {
        return Ok(0);
    }
    let k = k.min(n - k);
    let mut result = 1u128;
    for i in 1..=k {
        let mut numerator = (n - k + i) as u128;
        let mut denominator = i as u128;
        let divisor = gcd(numerator, denominator);
        numerator /= divisor;
        denominator /= divisor;
        let divisor = gcd(result, denominator);
        result /= divisor;
        denominator /= divisor;
        debug_assert_eq!(denominator, 1);
        result = result
            .checked_mul(numerator)
            .ok_or("geometry domain count exceeds u128")?;
    }
    Ok(result)
}

/// Enumerate at most `limit` complete patterns, without materializing the
/// remaining universe. Enumeration order is stable for g1: local strictness
/// masks 0..7 (bits: lower wick, body, upper wick), direction Down before Up,
/// and merge steps old/new/tied.
/// This order is deterministic but is not lexicographic rank-vector order.
pub fn enumerate_patterns(
    n: usize,
    mode: GeometryMode,
    limit: usize,
) -> Result<Vec<GeometryPattern>> {
    count_domain(n, mode)?;
    let mut output = Vec::new();
    if limit == 0 {
        return Ok(output);
    }
    walk_patterns(&empty_pattern(mode), n, mode, &mut |pattern| {
        output.push(pattern.clone());
        output.len() < limit
    });
    Ok(output)
}

pub fn pair_catalogue(mode: GeometryMode) -> Result<Vec<GeometryPattern>> {
    enumerate_patterns(2, mode, usize::MAX)
}

/// Find a deterministic legal pattern outside the supplied set. At most
/// `observed.len()+1` complete candidates are inspected. An entirely observed
/// domain returns None. All supplied patterns must have the requested n/mode.
pub fn first_unobserved(
    n: usize,
    mode: GeometryMode,
    observed: &HashSet<GeometryPattern>,
) -> Result<Option<GeometryPattern>> {
    if observed.iter().any(|p| p.len() != n || p.mode() != mode) {
        return Err("observed geometry set has inconsistent candle count or mode".into());
    }
    first_unobserved_by(n, mode, observed.len(), |pattern| {
        observed.contains(pattern)
    })
}

/// Membership-callback variant, useful with a HashMap-backed pattern bank.
/// `observed_count` and `contains` must describe the same set of distinct
/// legal patterns with the requested n/mode. The bounded search detects a
/// membership callback that claims more observed patterns than that count.
pub fn first_unobserved_by<F>(
    n: usize,
    mode: GeometryMode,
    observed_count: usize,
    mut contains: F,
) -> Result<Option<GeometryPattern>>
where
    F: FnMut(&GeometryPattern) -> bool,
{
    let total = count_domain(n, mode)?;
    if observed_count as u128 > total {
        return Err("observed geometry count exceeds legal domain".into());
    }
    if observed_count as u128 == total {
        return Ok(None);
    }
    let mut examined = 0usize;
    let mut found = None;
    let mut inconsistent = false;
    walk_patterns(&empty_pattern(mode), n, mode, &mut |pattern| {
        if !contains(pattern) {
            found = Some(pattern.clone());
            return false;
        }
        // There can be at most observed_count successful membership checks
        // before the first missing pattern. Avoid observed_count+1 overflow.
        if examined == observed_count {
            inconsistent = true;
            return false;
        }
        examined += 1;
        true
    });
    if inconsistent || found.is_none() {
        return Err("geometry membership does not match observed count".into());
    }
    Ok(found)
}

fn empty_pattern(mode: GeometryMode) -> GeometryPattern {
    GeometryPattern {
        ranks: Vec::new(),
        directions: if mode == GeometryMode::Oriented {
            Some(Vec::new())
        } else {
            None
        },
    }
}

fn walk_patterns(
    prefix: &GeometryPattern,
    remaining: usize,
    mode: GeometryMode,
    visitor: &mut dyn FnMut(&GeometryPattern) -> bool,
) -> bool {
    if remaining == 0 {
        return visitor(prefix);
    }
    let old_levels = prefix.level_count();
    for mask in 0..8usize {
        let mut shape = [0usize; 4];
        for endpoint in 1..4 {
            shape[endpoint] = shape[endpoint - 1] + ((mask >> (endpoint - 1)) & 1);
        }
        let new_levels = shape[3] + 1;
        let directions: &[BodyDirection] = if mode == GeometryMode::Oriented && mask & 2 != 0 {
            &[BodyDirection::Down, BodyDirection::Up]
        } else {
            &[BodyDirection::Flat]
        };
        for &direction in directions {
            let mut old_map = vec![0usize; old_levels];
            let mut new_map = vec![0usize; new_levels];
            let complete = walk_merges(
                0,
                0,
                0,
                &mut old_map,
                &mut new_map,
                &mut |old_map, new_map| {
                    let mut ranks = Vec::with_capacity(prefix.len() + 1);
                    for row in &prefix.ranks {
                        ranks.push([
                            old_map[row[0]],
                            old_map[row[1]],
                            old_map[row[2]],
                            old_map[row[3]],
                        ]);
                    }
                    ranks.push([
                        new_map[shape[0]],
                        new_map[shape[1]],
                        new_map[shape[2]],
                        new_map[shape[3]],
                    ]);
                    let directions = if let Some(prior) = &prefix.directions {
                        let mut next = prior.clone();
                        next.push(direction);
                        Some(next)
                    } else {
                        None
                    };
                    walk_patterns(
                        &GeometryPattern { ranks, directions },
                        remaining - 1,
                        mode,
                        visitor,
                    )
                },
            );
            if !complete {
                return false;
            }
        }
    }
    true
}

fn walk_merges(
    old: usize,
    new: usize,
    level: usize,
    old_map: &mut [usize],
    new_map: &mut [usize],
    visitor: &mut dyn FnMut(&[usize], &[usize]) -> bool,
) -> bool {
    if old == old_map.len() && new == new_map.len() {
        return visitor(old_map, new_map);
    }
    if old < old_map.len() {
        old_map[old] = level;
        if !walk_merges(old + 1, new, level + 1, old_map, new_map, visitor) {
            return false;
        }
    }
    if new < new_map.len() {
        new_map[new] = level;
        if !walk_merges(old, new + 1, level + 1, old_map, new_map, visitor) {
            return false;
        }
    }
    if old < old_map.len() && new < new_map.len() {
        old_map[old] = level;
        new_map[new] = level;
        if !walk_merges(old + 1, new + 1, level + 1, old_map, new_map, visitor) {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    fn endpoints(rows: &[[f64; 4]]) -> GeometryPattern {
        GeometryPattern::from_endpoints(rows, GeometryMode::Unoriented, None).unwrap()
    }

    fn realize(pattern: &GeometryPattern) -> Vec<[f64; 4]> {
        pattern
            .ranks
            .iter()
            .enumerate()
            .map(|(i, r)| {
                let [low, body_low, body_high, high] = r.map(|x| x as f64);
                let down = pattern
                    .directions
                    .as_ref()
                    .map_or(false, |d| d[i] == BodyDirection::Down);
                if down {
                    [body_high, high, low, body_low]
                } else {
                    [body_low, high, low, body_high]
                }
            })
            .collect()
    }

    #[test]
    fn canonical_order_retains_ties_and_all_degeneracies() {
        let rows = [
            [0.0, 0.0, 0.0, 0.0],
            [-4.0, -4.0, -2.0, -2.0],
            [-3.0, -1.0, -1.0, 2.0],
        ];
        let p = endpoints(&rows);
        assert_eq!(p.ranks(), &[[4, 4, 4, 4], [0, 0, 2, 2], [1, 3, 3, 5]]);
        assert_eq!(p.level_count(), 6);
        assert_eq!(p.to_string(), "g1:u:4,4,4,4;0,0,2,2;1,3,3,5");
        assert_eq!(p.to_string().parse::<GeometryPattern>().unwrap(), p);
        assert_eq!(
            endpoints(&[[-0.0, 0.0, -0.0, 0.0]]).ranks(),
            &[[0, 0, 0, 0]]
        );
    }

    #[test]
    fn monotone_price_maps_match_but_direction_can_distinguish() {
        let a = [[1.0, 4.0, 0.0, 3.0], [2.0, 5.0, 1.0, 4.0]];
        let b = a.map(|row| row.map(|x: f64| x * x * x + 7.0));
        for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
            let p = GeometryPattern::from_ohlc(&a, mode).unwrap();
            assert!(p.matches_ohlc(&b).unwrap());
        }
        let reversed = [[3.0, 4.0, 0.0, 1.0], a[1]];
        assert!(GeometryPattern::from_ohlc(&a, GeometryMode::Unoriented)
            .unwrap()
            .matches_ohlc(&reversed)
            .unwrap());
        assert!(!GeometryPattern::from_ohlc(&a, GeometryMode::Oriented)
            .unwrap()
            .matches_ohlc(&reversed)
            .unwrap());
    }

    #[test]
    fn adjacent_pair_codes_do_not_replace_global_order() {
        let a = [0.0, 1.0, 2.0, 3.0];
        let b = [10.0, 11.0, 12.0, 13.0];
        let c = [4.0, 5.0, 6.0, 7.0];
        let other_c = [-4.0, -3.0, -2.0, -1.0];
        assert_eq!(endpoints(&[b, c]), endpoints(&[b, other_c]));
        let first = endpoints(&[a, b, c]);
        let second = endpoints(&[a, b, other_c]);
        assert_ne!(first, second);
        assert_eq!(
            first
                .boundary_cmp(2, Boundary::Low, 0, Boundary::High)
                .unwrap(),
            Ordering::Greater
        );
        assert_eq!(
            second
                .boundary_cmp(2, Boundary::High, 0, Boundary::Low)
                .unwrap(),
            Ordering::Less
        );
        assert!(first
            .boundary_cmp(3, Boundary::High, 0, Boundary::Low)
            .is_err());
    }

    #[test]
    fn cross_part_geometry_survives_same_body_and_range_relations() {
        let a = [0.0, 2.0, 4.0, 6.0];
        let p = endpoints(&[a, [1.0, 3.0, 5.0, 7.0]]);
        let q = endpoints(&[a, [2.5, 3.0, 5.0, 7.0]]);
        assert_ne!(p, q);
        assert_eq!(
            p.boundary_cmp(1, Boundary::Low, 0, Boundary::BodyLow)
                .unwrap(),
            Ordering::Less
        );
        assert_eq!(
            q.boundary_cmp(1, Boundary::Low, 0, Boundary::BodyLow)
                .unwrap(),
            Ordering::Greater
        );
    }

    #[test]
    fn reject_invalid_numeric_geometry_and_orientation() {
        for row in [
            [1.0, 0.0, 0.0, 1.0],
            [1.0, 2.0, 1.5, 1.0],
            [f64::NAN, 2.0, 0.0, 1.0],
            [1.0, f64::INFINITY, 0.0, 1.0],
            [1.0, 2.0, f64::NEG_INFINITY, 1.0],
        ] {
            assert!(GeometryPattern::from_ohlc(&[row], GeometryMode::Unoriented).is_err());
        }
        assert!(GeometryPattern::from_endpoints(
            &[[0.0, 2.0, 1.0, 3.0]],
            GeometryMode::Unoriented,
            None
        )
        .is_err());
        assert!(GeometryPattern::from_endpoints(
            &[[0.0; 4]],
            GeometryMode::Oriented,
            Some(&[BodyDirection::Up])
        )
        .is_err());
        assert!(GeometryPattern::from_endpoints(
            &[[0.0, 1.0, 2.0, 3.0]],
            GeometryMode::Oriented,
            Some(&[BodyDirection::Flat])
        )
        .is_err());
        assert!(
            GeometryPattern::from_endpoints(&[[0.0; 4]], GeometryMode::Oriented, None).is_err()
        );
        assert!(GeometryPattern::from_endpoints(
            &[[0.0; 4]],
            GeometryMode::Unoriented,
            Some(&[BodyDirection::Flat])
        )
        .is_err());
    }

    #[test]
    fn strict_parser_rejects_noncanonical_or_impossible_patterns() {
        for text in [
            "g2:u:0,0,0,0",
            "g1:x:0,0,0,0",
            "g1:u:0,0,0",
            "g1:u:0,0,0,0;",
            "g1:u:0,0,0,0,u",
            "g1:u:0,0,0,2",
            "g1:u:1,1,1,1",
            "g1:u:0,2,1,3",
            "g1:u:-1,0,0,0",
            "g1:u:00,0,0,0",
            "g1:u:+0,0,0,0",
            "g1:u: 0,0,0,0",
            "g1:o:0,0,0,0,u",
            "g1:o:0,1,2,3,z",
            "g1:o:0,0,0,0",
            "g1:o:0,0,0,0,x",
        ] {
            assert!(text.parse::<GeometryPattern>().is_err(), "accepted {text}");
        }
        let huge = format!("g1:u:0,0,0,{}", usize::MAX);
        assert!(huge.parse::<GeometryPattern>().is_err());
        assert!(GeometryPattern::new(vec![[0; 4]], Some(Vec::new())).is_err());
    }

    #[test]
    fn exact_domain_counts_and_checked_overflow() {
        let expected = [
            ("1", "1"),
            ("8", "12"),
            ("2568", "7452"),
            ("5592968", "32160252"),
            ("44418808968", "508608936252"),
            ("936239675880968", "21386422752715452"),
            ("43216321851028552968", "1971122519237375505852"),
            ("3840691551111678501624968", "349946534568771563626027452"),
            (
                "599170270107067142441692696968",
                "109093488682843434702978214200252",
            ),
            (
                "153066871555466967822330084645768968",
                "55702085623739099432122993642929144252",
            ),
        ];
        for (n, (unoriented, oriented)) in expected.iter().enumerate() {
            assert_eq!(
                count_domain(n, GeometryMode::Unoriented).unwrap(),
                unoriented.parse::<u128>().unwrap()
            );
            assert_eq!(
                count_domain(n, GeometryMode::Oriented).unwrap(),
                oriented.parse::<u128>().unwrap()
            );
        }
        for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
            assert!(count_domain(10, mode).is_err());
            assert!(count_domain(usize::MAX, mode).is_err());
        }
        assert_eq!(
            count_domain_by_levels(2, GeometryMode::Unoriented).unwrap(),
            vec![0, 1, 23, 153, 471, 780, 720, 350, 70]
        );
    }

    #[test]
    fn complete_pair_catalogues_are_unique_realizable_and_round_trip() {
        for (mode, expected) in [
            (GeometryMode::Unoriented, 2568),
            (GeometryMode::Oriented, 7452),
        ] {
            let patterns = pair_catalogue(mode).unwrap();
            assert_eq!(patterns.len(), expected);
            let unique: HashSet<_> = patterns.iter().cloned().collect();
            assert_eq!(unique.len(), expected);
            for pattern in &patterns {
                pattern.validate().unwrap();
                assert_eq!(
                    pattern.to_string().parse::<GeometryPattern>().unwrap(),
                    *pattern
                );
                assert_eq!(
                    GeometryPattern::from_ohlc(&realize(pattern), mode).unwrap(),
                    *pattern
                );
            }
            if mode == GeometryMode::Unoriented {
                assert_eq!(
                    patterns
                        .iter()
                        .filter(|p| p.ranks.iter().all(|r| r[1] < r[2]))
                        .count(),
                    1284
                );
                let strict: Vec<_> = patterns
                    .iter()
                    .filter(|p| p.ranks.iter().all(|r| r.windows(2).all(|w| w[0] < w[1])))
                    .collect();
                assert_eq!(strict.len(), 321);
                for (ties, expected) in [70, 140, 90, 20, 1].iter().enumerate() {
                    assert_eq!(
                        strict
                            .iter()
                            .filter(|p| p.level_count() == 8 - ties)
                            .count(),
                        *expected
                    );
                }
            } else {
                assert_eq!(
                    patterns
                        .iter()
                        .filter(|p| p.ranks.iter().all(|r| r[1] < r[2]))
                        .count(),
                    5136
                );
            }
        }
    }

    #[test]
    fn empty_domain_and_single_bar_shapes_are_explicit() {
        for (mode, count) in [(GeometryMode::Unoriented, 8), (GeometryMode::Oriented, 12)] {
            assert_eq!(enumerate_patterns(1, mode, 100).unwrap().len(), count);
            let empty = enumerate_patterns(0, mode, 2).unwrap();
            assert_eq!(empty.len(), 1);
            assert!(empty[0].is_empty());
            assert_eq!(
                empty[0].to_string().parse::<GeometryPattern>().unwrap(),
                empty[0]
            );
            assert!(empty[0].matches_ohlc(&[]).unwrap());
            let set: HashSet<_> = empty.into_iter().collect();
            assert!(first_unobserved(0, mode, &set).unwrap().is_none());
        }
    }

    #[test]
    fn complement_representative_search_is_bounded_and_deterministic() {
        let mode = GeometryMode::Unoriented;
        let patterns = pair_catalogue(mode).unwrap();
        let observed: HashSet<_> = patterns.iter().take(127).cloned().collect();
        assert_eq!(
            first_unobserved(2, mode, &observed).unwrap(),
            Some(patterns[127].clone())
        );
        let all: HashSet<_> = patterns.into_iter().collect();
        assert_eq!(first_unobserved(2, mode, &all).unwrap(), None);
        assert!(first_unobserved(3, mode, &all).is_err());
        let prefix = enumerate_patterns(9, mode, 101).unwrap();
        let observed: HashSet<_> = prefix.iter().take(100).cloned().collect();
        let mut calls = 0;
        let missing = first_unobserved_by(9, mode, observed.len(), |p| {
            calls += 1;
            observed.contains(p)
        })
        .unwrap();
        assert_eq!(calls, 101);
        assert_eq!(missing, Some(prefix[100].clone()));
        assert!(first_unobserved_by(2, mode, 1, |_| true).is_err());
        assert!(first_unobserved_by(1, mode, 9, |_| false).is_err());
        assert!(enumerate_patterns(9, mode, 0).unwrap().is_empty());
    }

    #[test]
    fn reusable_encoder_preserves_storage_and_recovers_after_invalid_input() {
        let mode = GeometryMode::Oriented;
        let a = [[1.0, 4.0, 0.0, 3.0], [4.0, 5.0, 1.0, 2.0]];
        let b = [[8.0, 8.0, 8.0, 8.0], [-1.0, 3.0, -5.0, 2.0]];
        let mut encoder = GeometryEncoder::new(2, mode).unwrap();
        let pointers = (
            encoder.values.as_ptr(),
            encoder.order.as_ptr(),
            encoder.pattern.ranks.as_ptr(),
            encoder.pattern.directions.as_ref().unwrap().as_ptr(),
        );
        for rows in [a, b, a] {
            assert_eq!(
                encoder.encode_ohlc(&rows).unwrap(),
                &GeometryPattern::from_ohlc(&rows, mode).unwrap()
            );
            assert_eq!(
                pointers,
                (
                    encoder.values.as_ptr(),
                    encoder.order.as_ptr(),
                    encoder.pattern.ranks.as_ptr(),
                    encoder.pattern.directions.as_ref().unwrap().as_ptr()
                )
            );
        }
        assert!(encoder.encode_ohlc(&[[f64::NAN; 4], b[1]]).is_err());
        assert_eq!(
            encoder.encode_ohlc(&a).unwrap(),
            &GeometryPattern::from_ohlc(&a, mode).unwrap()
        );
        assert!(encoder.encode_ohlc(&[]).is_err());
        assert!(GeometryEncoder::new(usize::MAX, mode).is_err());
    }
}
