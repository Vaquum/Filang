use super::{
    predicate::{CandleRule, Field, Ratio},
    tape::{number, DAYS, TRENDS},
};
use crate::{
    geometry::{Dimension, GeometryPattern},
    rules::Cmp,
    Result,
};
use std::collections::HashSet;

pub(super) const MAX_BATCH: usize = 64;

pub(super) enum Node {
    Pattern(CandleRule),
    /// A G1 pattern, and whether the window is read as a chain: every bar after the first opening at the
    /// close of the bar before it, with its low and high widened to include that open.
    Geometry(GeometryPattern, bool),
    GeometryWithin(GeometryPattern, bool, u32),
    Wick(Ratio, Ratio),
    Breakout(usize),
    Range(usize, Ratio),
    Held(usize, usize),
    Weekday,
    Tail(i64),
    Trend(i64),
    Category(u8),
    Equal(usize, usize, bool),
    Not(usize),
    Logic(Vec<usize>, bool),
    Price(Field, usize),
    Prior(usize, bool),
    Axis(Dimension, usize),
    AxisPrior(Dimension, usize, bool),
    AxisZero,
    AxisRelate(usize, Cmp, usize),
    AxisMultiple(Dimension, usize, f64, Option<f64>),
    Relate(usize, Cmp, usize),
    Near(usize, usize, Ratio),
    Share(Field, usize, Ratio, Ratio),
    Multiple(usize, Ratio, Option<Ratio>),
    Reclaim(usize, usize, usize, bool),
    Window(usize, usize),
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Type {
    Bool,
    Day,
    Trend,
    Price,
    PriorLow,
    PriorHigh,
    Axis(Dimension),
}

pub(super) struct Query {
    pub find: usize,
    pub context: Option<usize>,
    pub filters: Vec<usize>,
    pub group: Option<usize>,
    pub horizons: Vec<usize>,
}

pub(super) struct Plan {
    pub nodes: Vec<Node>,
    pub queries: Vec<Query>,
}

fn steps(ms: i64, frame: i64) -> Result<usize> {
    if ms > 0 && ms % frame == 0 && ms <= 7 * 86_400_000 {
        Ok((ms / frame) as usize)
    } else {
        Err("duration must be on the study grid and at most seven days".into())
    }
}

fn reference(value: Option<&str>, types: &[Type], want: Option<Type>) -> Result<usize> {
    let index: usize = number(value, "plan reference")?;
    match types.get(index) {
        Some(actual) if want.map_or(true, |t| *actual == t) => Ok(index),
        _ => Err("plan reference is forward, missing or wrong type".into()),
    }
}

fn price_ref(value: Option<&str>, types: &[Type]) -> Result<usize> {
    let id = reference(value, types, None)?;
    if matches!(types[id], Type::Price | Type::PriorLow | Type::PriorHigh) {
        Ok(id)
    } else {
        Err("expected an endpoint price or prior level".into())
    }
}

fn axis(words: &mut std::str::SplitWhitespace<'_>) -> Result<Dimension> {
    words
        .next()
        .ok_or_else(|| "missing dimension".to_owned())?
        .parse()
}

fn axis_ratio(text: &str) -> Result<f64> {
    let (num, den) = text
        .split_once('/')
        .ok_or("expected numerator and denominator")?;
    let num = num
        .parse::<f64>()
        .ok()
        .filter(|n| *n >= 0.0)
        .ok_or("invalid numerator")?;
    let den = den
        .parse::<f64>()
        .ok()
        .filter(|d| *d > 0.0)
        .ok_or("invalid denominator")?;
    Ok(num / den)
}

fn offset(value: Option<&str>) -> Result<usize> {
    let n = number(value, "candle offset")?;
    if n <= 64 {
        Ok(n)
    } else {
        Err("candle offset exceeds 64".into())
    }
}

impl Plan {
    pub fn parse(text: &str, frame: i64) -> Result<Self> {
        let mut parts = text.trim_end_matches(['\n', '\r']).split('\t');
        if parts.next() != Some("filang-study-v1") {
            return Err("expected a Filang study v1 plan".into());
        }
        let n: usize = number(parts.next(), "plan node count")?;
        if !(1..=2_048).contains(&n) {
            return Err("plan must contain 1–2048 nodes".into());
        }
        let mut nodes = Vec::with_capacity(n);
        let mut types = Vec::with_capacity(n);
        for _ in 0..n {
            let mut words = parts.next().ok_or("missing plan node")?.split_whitespace();
            let op = words.next().ok_or("empty plan node")?;
            let mut kind = Type::Bool;
            let node = match op {
                "pattern" => Node::Pattern(CandleRule::parse(
                    number(words.next(), "pattern length")?,
                    &mut words,
                )?),
                "g1" | "g1c" | "g1r" | "g1cr" => {
                    let pattern: GeometryPattern = words.next().ok_or("missing G1")?.parse()?;
                    if pattern.is_empty() {
                        return Err("empty G1 event".into());
                    }
                    let chained = matches!(op, "g1c" | "g1cr");
                    let radius: u32 = if op.ends_with('r') {
                        number(words.next(), "geometry radius")?
                    } else {
                        0
                    };
                    if radius == 0 {
                        Node::Geometry(pattern, chained)
                    } else {
                        Node::GeometryWithin(pattern, chained, radius)
                    }
                }
                "wick" => Node::Wick(
                    Ratio::parse(words.next().ok_or("missing body ratio")?)?,
                    Ratio::parse(words.next().ok_or("missing wick ratio")?)?,
                ),
                "range" => Node::Range(
                    steps(number(words.next(), "range duration")?, frame)?,
                    Ratio::parse(words.next().ok_or("missing range ratio")?)?,
                ),
                "price" => {
                    kind = Type::Price;
                    let field = Field::parse(words.next().ok_or("missing candle price point")?)?;
                    if !matches!(
                        field,
                        Field::Open
                            | Field::Close
                            | Field::High
                            | Field::Low
                            | Field::BodyLow
                            | Field::BodyHigh
                    ) {
                        return Err("expected a candle endpoint".into());
                    }
                    Node::Price(field, offset(words.next())?)
                }
                "prior-low" | "prior-high" => {
                    let high = op == "prior-high";
                    kind = if high {
                        Type::PriorHigh
                    } else {
                        Type::PriorLow
                    };
                    Node::Prior(steps(number(words.next(), "prior window")?, frame)?, high)
                }
                "axis" => {
                    let axis = axis(&mut words)?;
                    kind = Type::Axis(axis);
                    Node::Axis(axis, offset(words.next())?)
                }
                "axis-zero" => {
                    let axis = axis(&mut words)?;
                    if !axis.has_reference() {
                        return Err("zero reference requires delta or imbalance".into());
                    }
                    kind = Type::Axis(axis);
                    Node::AxisZero
                }
                "axis-prior-low" | "axis-prior-high" => {
                    let axis = axis(&mut words)?;
                    kind = Type::Axis(axis);
                    let window = steps(number(words.next(), "axis prior window")?, frame)?;
                    Node::AxisPrior(axis, window, op == "axis-prior-high")
                }
                "axis-relate" => {
                    let left = reference(words.next(), &types, None)?;
                    if !matches!(types[left], Type::Axis(_)) {
                        return Err("axis relation needs a dimension".into());
                    }
                    let comparison = Cmp::parse(words.next().ok_or("missing axis comparison")?)?;
                    let right = reference(words.next(), &types, Some(types[left]))?;
                    Node::AxisRelate(left, comparison, right)
                }
                "axis-multiple" => {
                    let axis = axis(&mut words)?;
                    if axis.has_reference() {
                        return Err("signed dimensions have no median multiple".into());
                    }
                    let window = steps(number(words.next(), "axis median window")?, frame)?;
                    let min = axis_ratio(words.next().ok_or("missing minimum multiple")?)?;
                    let max = match words.next() {
                        Some("-") => None,
                        Some(text) => Some(axis_ratio(text)?),
                        None => return Err("missing maximum multiple or dash".into()),
                    };
                    Node::AxisMultiple(axis, window, min, max)
                }
                "relate" => Node::Relate(
                    price_ref(words.next(), &types)?,
                    Cmp::parse(words.next().ok_or("missing price comparison")?)?,
                    price_ref(words.next(), &types)?,
                ),
                "near" => Node::Near(
                    price_ref(words.next(), &types)?,
                    price_ref(words.next(), &types)?,
                    Ratio::parse(words.next().ok_or("missing distance")?)?,
                ),
                "share" => {
                    let part = match words.next() {
                        Some("body") => Field::Body,
                        Some("lower_wick") => Field::Lower,
                        Some("upper_wick") => Field::Upper,
                        _ => return Err("unknown candle part".into()),
                    };
                    Node::Share(
                        part,
                        offset(words.next())?,
                        Ratio::parse(words.next().ok_or("missing minimum share")?)?,
                        Ratio::parse(words.next().ok_or("missing maximum share")?)?,
                    )
                }
                "multiple" => Node::Multiple(
                    steps(number(words.next(), "median window")?, frame)?,
                    Ratio::magnitude(words.next().ok_or("missing minimum multiple")?)?,
                    match words.next() {
                        Some("-") => None,
                        Some(x) => Some(Ratio::magnitude(x)?),
                        None => return Err("missing maximum multiple or dash".into()),
                    },
                ),
                "window" => {
                    let inner = reference(words.next(), &types, Some(Type::Bool))?;
                    let n = offset(words.next())?;
                    if n == 0 {
                        return Err("candle window is empty".into());
                    }
                    Node::Window(inner, n)
                }
                "reclaim" => {
                    let id = price_ref(words.next(), &types)?;
                    if types[id] == Type::Price {
                        return Err("reclaim needs a prior range level".into());
                    }
                    let (min, max) = (offset(words.next())?, offset(words.next())?);
                    if min > max {
                        return Err("reclaim minimum exceeds maximum".into());
                    }
                    Node::Reclaim(id, min, max, types[id] == Type::PriorHigh)
                }
                "breakout" => Node::Breakout(steps(number(words.next(), "lookback")?, frame)?),
                "held" => Node::Held(
                    reference(words.next(), &types, Some(Type::Bool))?,
                    steps(number(words.next(), "held duration")?, frame)? + 1,
                ),
                "weekday" => {
                    kind = Type::Day;
                    Node::Weekday
                }
                "tail" => {
                    let duration: i64 = number(words.next(), "session tail duration")?;
                    if !(60_000..=86_400_000).contains(&duration) {
                        return Err("invalid session tail duration".into());
                    }
                    Node::Tail(duration)
                }
                "trend" => {
                    kind = Type::Trend;
                    let duration = number(words.next(), "trend frame")?;
                    steps(duration, frame)?;
                    Node::Trend(duration)
                }
                "category" => {
                    let value = words.next().ok_or("missing category")?;
                    if let Some(day) = DAYS.iter().position(|name| *name == value) {
                        kind = Type::Day;
                        Node::Category(day as u8)
                    } else if let Some(trend) = TRENDS.iter().position(|name| *name == value) {
                        kind = Type::Trend;
                        Node::Category(6 + trend as u8)
                    } else {
                        return Err("unknown study category".into());
                    }
                }
                "eq" | "ne" => {
                    let lhs = reference(words.next(), &types, None)?;
                    if !matches!(types[lhs], Type::Day | Type::Trend) {
                        return Err("comparison needs categories".into());
                    }
                    Node::Equal(
                        lhs,
                        reference(words.next(), &types, Some(types[lhs]))?,
                        op == "eq",
                    )
                }
                "not" => Node::Not(reference(words.next(), &types, Some(Type::Bool))?),
                "and" | "or" => {
                    let items = words
                        .by_ref()
                        .map(|id| reference(Some(id), &types, Some(Type::Bool)))
                        .collect::<Result<Vec<_>>>()?;
                    if items.is_empty() {
                        return Err("logic requires at least one operand".into());
                    }
                    Node::Logic(items, op == "and")
                }
                _ => return Err("unknown Filang study operator".into()),
            };
            if words.next().is_some() {
                return Err("trailing study node operands".into());
            }
            nodes.push(node);
            types.push(kind);
        }
        let mut queries = Vec::new();
        for part in parts {
            if queries.len() == MAX_BATCH {
                return Err("study batch exceeds 64 candidates".into());
            }
            let mut words = part.split_whitespace();
            let find = reference(words.next(), &types, Some(Type::Bool))?;
            let optional = |s, t| match s {
                Some("-") => Ok(None),
                value => reference(value, &types, t).map(Some),
            };
            let context = optional(words.next(), Some(Type::Bool))?;
            let group = optional(words.next(), None)?;
            if group.map_or(false, |id| {
                !matches!(types[id], Type::Bool | Type::Day | Type::Trend)
            }) {
                return Err("group needs a Boolean or category".into());
            }
            let mut seen = HashSet::new();
            let horizons = words
                .map(|s| {
                    let h = steps(number(Some(s), "outcome horizon")?, frame)?;
                    if !seen.insert(h) {
                        return Err("duplicate outcome horizon".into());
                    }
                    Ok(h)
                })
                .collect::<Result<Vec<_>>>()?;
            queries.push(Query {
                find,
                context,
                filters: Vec::new(),
                group,
                horizons,
            });
        }
        if queries.is_empty() {
            return Err("study batch is empty".into());
        }
        Ok(Self { nodes, queries })
    }
}
