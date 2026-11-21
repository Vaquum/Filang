use super::{
    predicate::{CandleRule, Ratio},
    tape::{number, DAYS, TRENDS},
};
use crate::{geometry::GeometryPattern, Result};
use std::collections::HashSet;

pub(super) const MAX_BATCH: usize = 64;

pub(super) enum Node {
    Pattern(CandleRule),
    Geometry(GeometryPattern),
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
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Type {
    Bool,
    Day,
    Trend,
}

pub(super) struct Query {
    pub find: usize,
    pub context: Option<usize>,
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
                "g1" => {
                    let pattern: GeometryPattern = words.next().ok_or("missing G1")?.parse()?;
                    if pattern.is_empty() {
                        return Err("empty G1 event".into());
                    }
                    Node::Geometry(pattern)
                }
                "wick" => Node::Wick(
                    Ratio::parse(words.next().ok_or("missing body ratio")?)?,
                    Ratio::parse(words.next().ok_or("missing wick ratio")?)?,
                ),
                "range" => Node::Range(
                    steps(number(words.next(), "range duration")?, frame)?,
                    Ratio::parse(words.next().ok_or("missing range ratio")?)?,
                ),
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
                    if types[lhs] == Type::Bool {
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
