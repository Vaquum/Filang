use super::{
    predicate::{CandleRule, Field, Ratio},
    tape::{number, DAYS, TRENDS},
};
use crate::{
    geometry::{Dimension, GeometryPattern},
    rules::Cmp,
    Result,
};
use std::collections::HashMap;

pub(super) const MAX_BATCH: usize = 64;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Role {
    Event,
    Condition,
    State,
}

// These references carry the role at the point of use. Two roles may share
// one physical series, for example a checked custom event using a condition.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct Ref<T> {
    index: usize,
    kind: T,
}

impl<T: Copy> Ref<T> {
    pub fn index(self) -> usize {
        self.index
    }

    pub fn kind(self) -> T {
        self.kind
    }
}

pub(super) type Predicate = Ref<Role>;

#[derive(Clone, Copy)]
pub(super) struct Event(Predicate);

impl Event {
    pub fn index(self) -> usize {
        self.0.index()
    }

    pub fn predicate(self) -> Predicate {
        self.0
    }
}

#[derive(Clone, Copy)]
pub(super) struct State(Predicate);

impl State {
    pub fn index(self) -> usize {
        self.0.index()
    }
}

impl Predicate {
    pub fn new(index: usize, role: Role) -> Self {
        Self { index, kind: role }
    }

    pub fn event(self) -> Option<Event> {
        (self.kind == Role::Event).then_some(Event(self))
    }

    pub fn state(self) -> Option<State> {
        (self.kind == Role::State).then_some(State(self))
    }

    pub fn declared_as(self, role: Role) -> Self {
        Self::new(self.index, role)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum PriceKind {
    Endpoint,
    PriorLow,
    PriorHigh,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum CategoryKind {
    Day,
    Trend,
}

pub(super) type Price = Ref<PriceKind>;
pub(super) type Axis = Ref<Dimension>;
pub(super) type Category = Ref<CategoryKind>;

#[derive(Clone, Copy)]
pub(super) enum Group {
    Predicate(Predicate),
    Category(Category),
}

impl Group {
    pub fn category(index: usize, kind: CategoryKind) -> Self {
        Self::Category(Ref { index, kind })
    }

    pub fn index(self) -> usize {
        match self {
            Self::Predicate(value) => value.index(),
            Self::Category(value) => value.index(),
        }
    }
}

// Outcome offsets are positive and only constructible from an on-grid
// duration. They never occur among the inputs to a detector or condition.
#[derive(Clone, Copy)]
pub(super) struct Horizon(usize);

impl Horizon {
    pub fn new(ms: i64, frame: i64) -> Result<Self> {
        Ok(Self(steps(ms, frame)?))
    }

    pub fn steps(self) -> usize {
        self.0
    }
}

pub(super) struct Instruction {
    pub text: String,
    pub predicates: Vec<Predicate>,
}

pub(super) enum Node {
    Pattern(CandleRule),
    /// A G1 pattern, and whether the window is read as a chain: every bar after the first opening at the
    /// close of the bar before it, with its low and high widened to include that open.
    Geometry(GeometryPattern, bool),
    GeometryWithin(GeometryPattern, bool, u32),
    Wick(Ratio, Ratio),
    Breakout(usize),
    Range(usize, Ratio),
    Held(State, usize),
    Weekday,
    Tail(i64),
    Trend(i64),
    Category(u8),
    Equal(Category, Category, bool),
    Not(Predicate),
    Logic(Vec<Predicate>, bool),
    Price(Field, usize),
    Prior(usize, bool),
    Axis(Dimension, usize),
    AxisPrior(Dimension, usize, bool),
    AxisZero,
    AxisRelate(Axis, Cmp, Axis),
    AxisMultiple(Dimension, usize, f64, Option<f64>),
    Relate(Price, Cmp, Price),
    Near(Price, Price, Ratio),
    Share(Field, usize, Ratio, Ratio),
    Multiple(usize, Ratio, Option<Ratio>),
    Reclaim(Price, usize, usize, bool),
    Window(Event, usize),
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Type {
    Bool,
    Category(CategoryKind),
    Price(PriceKind),
    Axis(Dimension),
}

pub(super) struct Query {
    pub find: Event,
    pub context: Option<Predicate>,
    pub filters: Vec<Predicate>,
    pub group: Option<Group>,
    pub horizons: Vec<Horizon>,
    pub column_labels: Vec<String>,
}

pub(super) struct Plan {
    nodes: Vec<Node>,
    queries: Vec<Query>,
    notes: HashMap<usize, String>,
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

fn price_ref(value: Option<&str>, types: &[Type]) -> Result<Price> {
    let index = reference(value, types, None)?;
    match types[index] {
        Type::Price(kind) => Ok(Ref { index, kind }),
        _ => Err("expected an endpoint price or prior level".into()),
    }
}

fn predicate_ref(
    value: Option<&str>,
    types: &[Type],
    operand: Option<Predicate>,
) -> Result<Predicate> {
    let index = reference(value, types, Some(Type::Bool))?;
    operand
        .filter(|reference| reference.index() == index)
        .ok_or_else(|| "missing checked predicate operand".into())
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
    pub fn nodes(&self) -> &[Node] {
        &self.nodes
    }

    pub fn queries(&self) -> &[Query] {
        &self.queries
    }

    pub fn notes(&self) -> &HashMap<usize, String> {
        &self.notes
    }

    pub fn build(
        instructions: &[Instruction],
        queries: Vec<Query>,
        notes: HashMap<usize, String>,
        frame: i64,
    ) -> Result<Self> {
        let n = instructions.len();
        if !(1..=2_048).contains(&n) {
            return Err("plan must contain 1–2048 nodes".into());
        }
        let mut nodes = Vec::with_capacity(n);
        let mut types = Vec::with_capacity(n);
        for instruction in instructions {
            let mut words = instruction.text.split_whitespace();
            let mut predicates = instruction.predicates.iter().copied();
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
                    kind = Type::Price(PriceKind::Endpoint);
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
                    kind = Type::Price(if high {
                        PriceKind::PriorHigh
                    } else {
                        PriceKind::PriorLow
                    });
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
                    let axis = match types[left] {
                        Type::Axis(axis) => axis,
                        _ => return Err("axis relation needs a dimension".into()),
                    };
                    let comparison = Cmp::parse(words.next().ok_or("missing axis comparison")?)?;
                    let right = reference(words.next(), &types, Some(types[left]))?;
                    Node::AxisRelate(
                        Ref {
                            index: left,
                            kind: axis,
                        },
                        comparison,
                        Ref {
                            index: right,
                            kind: axis,
                        },
                    )
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
                    let inner = predicate_ref(words.next(), &types, predicates.next())?
                        .event()
                        .ok_or("candle window requires an event")?;
                    let n = offset(words.next())?;
                    if n == 0 {
                        return Err("candle window is empty".into());
                    }
                    Node::Window(inner, n)
                }
                "reclaim" => {
                    let id = price_ref(words.next(), &types)?;
                    if id.kind() == PriceKind::Endpoint {
                        return Err("reclaim needs a prior range level".into());
                    }
                    let (min, max) = (offset(words.next())?, offset(words.next())?);
                    if min > max {
                        return Err("reclaim minimum exceeds maximum".into());
                    }
                    Node::Reclaim(id, min, max, id.kind() == PriceKind::PriorHigh)
                }
                "breakout" => Node::Breakout(steps(number(words.next(), "lookback")?, frame)?),
                "held" => Node::Held(
                    predicate_ref(words.next(), &types, predicates.next())?
                        .state()
                        .ok_or("held requires a state")?,
                    steps(number(words.next(), "held duration")?, frame)? + 1,
                ),
                "weekday" => {
                    kind = Type::Category(CategoryKind::Day);
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
                    kind = Type::Category(CategoryKind::Trend);
                    let duration = number(words.next(), "trend frame")?;
                    steps(duration, frame)?;
                    Node::Trend(duration)
                }
                "category" => {
                    let value = words.next().ok_or("missing category")?;
                    if let Some(day) = DAYS.iter().position(|name| *name == value) {
                        kind = Type::Category(CategoryKind::Day);
                        Node::Category(day as u8)
                    } else if let Some(trend) = TRENDS.iter().position(|name| *name == value) {
                        kind = Type::Category(CategoryKind::Trend);
                        Node::Category(6 + trend as u8)
                    } else {
                        return Err("unknown study category".into());
                    }
                }
                "eq" | "ne" => {
                    let lhs = reference(words.next(), &types, None)?;
                    let category = match types[lhs] {
                        Type::Category(category) => category,
                        _ => return Err("comparison needs categories".into()),
                    };
                    let rhs = reference(words.next(), &types, Some(types[lhs]))?;
                    Node::Equal(
                        Ref {
                            index: lhs,
                            kind: category,
                        },
                        Ref {
                            index: rhs,
                            kind: category,
                        },
                        op == "eq",
                    )
                }
                "not" => Node::Not(predicate_ref(words.next(), &types, predicates.next())?),
                "and" | "or" => {
                    let items = words
                        .by_ref()
                        .map(|id| predicate_ref(Some(id), &types, predicates.next()))
                        .collect::<Result<Vec<_>>>()?;
                    if items.is_empty() {
                        return Err("logic requires at least one operand".into());
                    }
                    Node::Logic(items, op == "and")
                }
                _ => return Err("unknown Filang study operator".into()),
            };
            if words.next().is_some() || predicates.next().is_some() {
                return Err("trailing study node operands".into());
            }
            nodes.push(node);
            types.push(kind);
        }
        for query in &queries {
            let mask = |predicate: Predicate| types.get(predicate.index()) == Some(&Type::Bool);
            if !mask(query.find.predicate())
                || query.context.map_or(false, |value| !mask(value))
                || query.filters.iter().any(|value| !mask(*value))
                || query.group.map_or(false, |group| match group {
                    Group::Predicate(value) => !mask(value),
                    Group::Category(value) => {
                        types.get(value.index()) != Some(&Type::Category(value.kind()))
                    }
                })
            {
                return Err("query references do not match the checked plan".into());
            }
        }
        Ok(Self {
            nodes,
            queries,
            notes,
        })
    }
}
