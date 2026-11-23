//! Exact order differences and scale-normalized comparison of observed windows.
use super::{BodyDirection, GeometryMode, GeometryPattern};
use crate::Result;
use std::collections::HashSet;

const SIZE_FLOOR: f64 = 0.02;
const SIZE_WEIGHT: f64 = 0.05;
const FLIP_WEIGHT: f64 = 0.3;

#[inline]
pub(super) fn half_flips(left: i8, right: i8) -> usize {
    usize::from((left - right).unsigned_abs())
}

#[inline]
fn relation(left: f64, right: f64) -> i8 {
    i8::from(left > right) - i8::from(left < right)
}

fn colour(direction: BodyDirection) -> i8 {
    match direction {
        BodyDirection::Down => -1,
        BodyDirection::Flat => 0,
        BodyDirection::Up => 1,
    }
}

#[derive(Clone, Copy, Debug)]
struct Comparison {
    left: u16,
    right: u16,
    expected: i8,
}

impl Comparison {
    fn at(self, endpoints: &[f64]) -> i8 {
        relation(
            endpoints[self.left as usize],
            endpoints[self.right as usize],
        )
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) struct Difference {
    pub left: usize,
    pub right: usize,
    pub expected: i8,
    pub observed: i8,
}

pub(crate) enum Exact {
    Match,
    OneAway(Difference),
    Different,
}

pub(crate) struct Shape {
    normalized: Vec<f64>,
    log_sizes: Vec<[f64; 2]>,
    pairs: Vec<Comparison>,
    colours: Vec<i8>,
}

impl Shape {
    pub fn new(rows: &[[f64; 4]], pattern: &GeometryPattern) -> Result<Self> {
        if !(1..=20).contains(&rows.len()) {
            return Err("Composer search needs 1–20 drawn bars".into());
        }
        let endpoints: Vec<_> = rows.iter().flat_map(|&row| boundaries(row)).collect();
        let (low, height) = span(&endpoints);
        let normalized: Vec<_> = endpoints
            .iter()
            .map(|point| (point - low) / height)
            .collect();
        let log_sizes = normalized
            .chunks_exact(4)
            .map(|ends| sizes(ends, 1.0))
            .collect();
        let ranks: Vec<_> = pattern.ranks().iter().flatten().copied().collect();
        let mut pairs = Vec::with_capacity(ranks.len() * (ranks.len() - 1) / 2);
        for a in 0..ranks.len() {
            for b in a + 1..ranks.len() {
                pairs.push(Comparison {
                    left: a as u16,
                    right: b as u16,
                    expected: ranks[a].cmp(&ranks[b]) as i8,
                });
            }
        }
        let colours = pattern
            .directions()
            .map_or_else(Vec::new, |dirs| dirs.iter().copied().map(colour).collect());
        Ok(Self {
            normalized,
            log_sizes,
            pairs,
            colours,
        })
    }

    pub fn colour_flips(&self, rows: &[[f64; 4]]) -> usize {
        self.colours
            .iter()
            .zip(rows)
            .map(|(&expected, &[o, _, _, c])| half_flips(expected, relation(c, o)))
            .sum()
    }

    pub fn colour_at(&self, i: usize, [o, _, _, c]: [f64; 4]) -> usize {
        self.colours
            .get(i)
            .map_or(0, |&expected| half_flips(expected, relation(c, o)))
    }

    pub fn exact_or_one_away(&self, endpoints: &[f64], colour_flips: usize) -> Exact {
        if colour_flips != 0 {
            return Exact::Different;
        }
        let mut difference = None;
        for &pair in &self.pairs {
            let observed = pair.at(endpoints);
            if observed != pair.expected {
                if difference.is_some() {
                    return Exact::Different;
                }
                difference = Some(Difference {
                    left: pair.left as usize,
                    right: pair.right as usize,
                    expected: pair.expected,
                    observed,
                });
            }
        }
        difference.map_or(Exact::Match, Exact::OneAway)
    }

    pub fn look(&self, endpoints: &[f64]) -> (f64, f64) {
        let (low, height) = span(endpoints);
        let shape = endpoints
            .iter()
            .zip(&self.normalized)
            .map(|(point, wanted)| ((point - low) / height - wanted).abs())
            .sum::<f64>()
            / endpoints.len() as f64;
        let size = endpoints
            .chunks_exact(4)
            .zip(&self.log_sizes)
            .map(|(ends, [body, range])| {
                let [b, r] = sizes(ends, height);
                (b - body).abs() + (r - range).abs()
            })
            .sum::<f64>();
        (
            shape,
            shape + SIZE_WEIGHT * size / (2 * self.log_sizes.len()) as f64,
        )
    }

    /// Optional score pruning uses only nonnegative terms, preserving ranking.
    pub fn rank(&self, endpoints: &[f64], colours: usize, bound: f64) -> Option<(f64, usize, f64)> {
        let colour_score = colours as f64 / 2.0;
        if colour_score > bound {
            return None;
        }
        let (shape, look) = self.look(endpoints);
        let base = colour_score + look;
        if base > bound {
            return None;
        }
        let mut flips = 0;
        for &pair in &self.pairs {
            flips += half_flips(pair.expected, pair.at(endpoints));
        }
        let score = base + FLIP_WEIGHT * (flips as f64 / 2.0) / self.pairs.len() as f64;
        (score <= bound).then_some((score, colours + flips, shape))
    }
}

#[inline]
pub(crate) fn boundaries([open, high, low, close]: [f64; 4]) -> [f64; 4] {
    [low, open.min(close), open.max(close), high]
}

fn span(endpoints: &[f64]) -> (f64, f64) {
    let (mut low, mut high) = (f64::INFINITY, f64::NEG_INFINITY);
    for ends in endpoints.chunks_exact(4) {
        low = low.min(ends[0]);
        high = high.max(ends[3]);
    }
    (low, if high > low { high - low } else { 1.0 })
}

fn sizes(ends: &[f64], height: f64) -> [f64; 2] {
    [
        ((ends[2] - ends[1]) / height + SIZE_FLOOR).ln(),
        ((ends[3] - ends[0]) / height + SIZE_FLOOR).ln(),
    ]
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub(crate) enum Price {
    Open,
    High,
    Low,
    Close,
    BodyLow,
    BodyHigh,
}

impl Price {
    pub(crate) fn endpoint(part: &str, row: [f64; 4], mode: GeometryMode) -> Self {
        match part {
            "L" => Self::Low,
            "H" => Self::High,
            "B" if mode == GeometryMode::Unoriented => Self::BodyLow,
            "T" if mode == GeometryMode::Unoriented => Self::BodyHigh,
            "B" if row[3] >= row[0] => Self::Open,
            "B" => Self::Close,
            "T" if row[3] >= row[0] => Self::Close,
            "T" => Self::Open,
            _ => unreachable!("validated drawing point"),
        }
    }

    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::High => "high",
            Self::Low => "low",
            Self::Close => "close",
            Self::BodyLow => "body_low",
            Self::BodyHigh => "body_high",
        }
    }

    pub(crate) fn value(self, [o, h, l, c]: [f64; 4]) -> f64 {
        match self {
            Self::Open => o,
            Self::High => h,
            Self::Low => l,
            Self::Close => c,
            Self::BodyLow => o.min(c),
            Self::BodyHigh => o.max(c),
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) enum Pin {
    Colour(usize),
    Relation((usize, Price), (usize, Price)),
}

#[derive(Clone, Copy)]
pub(crate) struct Hold {
    pin: Pin,
    relation: i8,
}

impl Hold {
    pub fn last(self) -> usize {
        match self.pin {
            Pin::Colour(bar) => bar,
            Pin::Relation(a, b) => a.0.max(b.0),
        }
    }

    pub fn first(self) -> usize {
        match self.pin {
            Pin::Colour(bar) => bar,
            Pin::Relation(a, b) => a.0.min(b.0),
        }
    }

    pub fn is_local(self) -> bool {
        match self.pin {
            Pin::Colour(_) => true,
            Pin::Relation(a, b) => a.0 == b.0,
        }
    }

    pub fn matches(self, rows: &[[f64; 4]]) -> bool {
        self.relation == pin_relation(self.pin, rows)
    }
}

fn pin_relation(pin: Pin, rows: &[[f64; 4]]) -> i8 {
    match pin {
        Pin::Colour(i) => relation(rows[i][3], rows[i][0]),
        Pin::Relation((a, pa), (b, pb)) => relation(pa.value(rows[a]), pb.value(rows[b])),
    }
}

pub(crate) fn holds(
    rows: &[[f64; 4]],
    pins: &[Pin],
    skeleton: usize,
    mode: GeometryMode,
) -> Vec<Hold> {
    let mut colours = HashSet::new();
    let mut relations = HashSet::new();
    let mut out = Vec::new();
    let mut push = |pin| {
        let distinct = match pin {
            Pin::Colour(bar) => mode == GeometryMode::Oriented && colours.insert(bar),
            Pin::Relation(a, b) => a != b && relations.insert((a.min(b), a.max(b))),
        };
        if distinct {
            out.push(Hold {
                pin,
                relation: pin_relation(pin, rows),
            });
        }
    };
    for &pin in pins {
        push(pin);
    }
    let marks = landmarks(rows, skeleton);
    if !marks.is_empty() {
        let mut points: Vec<_> = marks.clone();
        if mode == GeometryMode::Oriented {
            points.insert(0, (0, Price::Open));
            points.push((rows.len() - 1, Price::Close));
        }
        for (i, &a) in points.iter().enumerate() {
            for &b in &points[i + 1..] {
                push(Pin::Relation(a, b));
            }
        }
        for &(bar, price) in &marks {
            for neighbor in [
                bar.checked_sub(1),
                (bar + 1 < rows.len()).then_some(bar + 1),
            ]
            .into_iter()
            .flatten()
            {
                push(Pin::Relation((bar, price), (neighbor, price)));
            }
        }
    }
    out
}

fn landmarks(rows: &[[f64; 4]], level: usize) -> Vec<(usize, Price)> {
    if level == 0 {
        return Vec::new();
    }
    let mut marks = Vec::new();
    let n = rows.len();
    let mut strengths = Vec::new();
    for price in [Price::High, Price::Low] {
        for (i, &row) in rows.iter().enumerate() {
            let value = price.value(row);
            let mut strength = n;
            for distance in 1..n {
                let neighbors = [
                    i.checked_sub(distance),
                    (i + distance < n).then_some(i + distance),
                ];
                let blocks = neighbors.into_iter().flatten().any(|j| {
                    let other = price.value(rows[j]);
                    if price == Price::High {
                        value <= other
                    } else {
                        value >= other
                    }
                });
                if blocks {
                    strength = distance - 1;
                    break;
                }
            }
            if strength > 0 {
                strengths.push(strength);
                marks.push(((i, price), strength));
            }
        }
    }
    strengths.sort_unstable_by(|a, b| b.cmp(a));
    strengths.dedup();
    let minimum = strengths.get(level.min(strengths.len()).saturating_sub(1));
    marks
        .into_iter()
        .filter_map(|(point, strength)| minimum.filter(|&&x| strength >= x).map(|_| point))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geometry::explore::distance;

    #[test]
    fn matching_uses_g1_half_flips_and_a_distinct_look_score() {
        let drawn = [[20., 50., 15., 40.], [40., 85., 30., 60.]];
        let pattern = GeometryPattern::from_ohlc(&drawn, GeometryMode::Oriented).unwrap();
        let shape = Shape::new(&drawn, &pattern).unwrap();
        let endpoint_values =
            |rows: &[[f64; 4]]| rows.iter().flat_map(|&r| boundaries(r)).collect::<Vec<_>>();
        let scaled = drawn.map(|candle| candle.map(|value| value * 2. + 10.));
        assert!(matches!(
            shape.exact_or_one_away(&endpoint_values(&scaled), shape.colour_flips(&scaled)),
            Exact::Match
        ));
        let (score, flips, _) = shape
            .rank(
                &endpoint_values(&scaled),
                shape.colour_flips(&scaled),
                f64::INFINITY,
            )
            .unwrap();
        assert!(score.abs() < 1e-14);
        assert_eq!(flips, 0);

        let changed = [[20., 50., 15., 40.], [42., 85., 30., 60.]];
        let ends = endpoint_values(&changed);
        let actual = shape.exact_or_one_away(&ends, 0);
        assert!(matches!(
            actual,
            Exact::OneAway(Difference {
                left: 2,
                right: 5,
                expected: 0,
                observed: -1
            })
        ));
        let (score, flips, _) = shape.rank(&ends, 0, f64::INFINITY).unwrap();
        let expected = GeometryPattern::from_ohlc(&changed, GeometryMode::Oriented).unwrap();
        assert_eq!(flips, distance(&pattern, &expected).unwrap());
        assert!(shape.rank(&ends, 0, score / 2.0).is_none());
    }
}
