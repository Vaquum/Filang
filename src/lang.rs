use crate::{hash::sha256, Result};
use std::collections::{BTreeSet, HashMap};

pub type Id = usize;
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct Unit(pub i8, pub i8);
pub const SCALAR: Unit = Unit(0, 0);
#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub enum Op {
    Source(u8),
    Constant(u64),
    Add,
    Sub,
    Mul,
    Div,
    Div0,
    Min2,
    Max2,
    Abs,
    Neg,
    Lag(usize),
    Skip(usize),
    Diff(usize),
    Mean(usize),
    MeanSum(usize),
    StdSum(usize),
    Std(usize),
    Min(usize),
    Max(usize),
    Ema(usize),
    Wilder(usize),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Node {
    pub op: Op,
    pub args: Vec<Id>,
    pub unit: Unit,
    pub depth: usize,
}
#[derive(Clone, Default)]
pub struct Graph {
    pub nodes: Vec<Node>,
    index: HashMap<(Op, Vec<Id>), Id>,
}
impl Graph {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn add(&mut self, op: Op, args: Vec<Id>) -> Result<Id> {
        use Op::*;
        let arity = match op {
            Source(_) | Constant(_) => 0,
            Add | Sub | Mul | Div | Div0 | Min2 | Max2 => 2,
            _ => 1,
        };
        if args.len() != arity || args.iter().any(|i| *i >= self.nodes.len()) {
            return Err("bad graph arity/predecessor".into());
        }
        match op {
            Source(x) if x > 4 => return Err("unknown source".into()),
            Constant(b) if !f64::from_bits(b).is_finite() => {
                return Err("constant must be finite".into())
            }
            Lag(n) | Skip(n) | Diff(n) | Mean(n) | MeanSum(n) | StdSum(n) | Std(n) | Min(n)
            | Max(n) | Ema(n) | Wilder(n)
                if n == 0 || n > 100_000 =>
            {
                return Err("window/lag outside 1..100000".into())
            }
            _ => {}
        }
        let unit = match op {
            Source(4) => Unit(0, 1),
            Source(_) => Unit(1, 0),
            Constant(_) => SCALAR,
            Add | Sub | Min2 | Max2 => {
                let a = self.nodes[args[0]].unit;
                if a != self.nodes[args[1]].unit {
                    return Err("addition/comparison requires equal units".into());
                }
                a
            }
            Mul | Div | Div0 => {
                let a = self.nodes[args[0]].unit;
                let b = self.nodes[args[1]].unit;
                let s = if op == Mul { 1 } else { -1 };
                Unit(
                    a.0.checked_add(s * b.0).ok_or("unit overflow")?,
                    a.1.checked_add(s * b.1).ok_or("unit overflow")?,
                )
            }
            _ => self.nodes[args[0]].unit,
        };
        let depth = 1 + args.iter().map(|i| self.nodes[*i].depth).max().unwrap_or(0);
        if depth > 64 {
            return Err("program exceeds maximum depth 64".into());
        }
        let key = (op.clone(), args.clone());
        if let Some(id) = self.index.get(&key) {
            return Ok(*id);
        }
        let id = self.nodes.len();
        self.nodes.push(Node {
            op,
            args,
            unit,
            depth,
        });
        self.index.insert(key, id);
        Ok(id)
    }
    pub fn source(&mut self, n: u8) -> Id {
        self.add(Op::Source(n), vec![]).expect("valid source")
    }
    pub fn constant(&mut self, v: f64) -> Id {
        self.add(Op::Constant(v.to_bits()), vec![])
            .expect("finite internal constant")
    }
    pub fn unary(&mut self, op: Op, a: Id) -> Id {
        self.add(op, vec![a]).expect("typed internal unary")
    }
    pub fn binary(&mut self, op: Op, a: Id, b: Id) -> Id {
        self.add(op, vec![a, b]).expect("typed internal binary")
    }
    pub fn dependencies(&self, roots: &[Id]) -> Vec<Id> {
        fn visit(g: &Graph, n: Id, set: &mut BTreeSet<Id>) {
            if set.insert(n) {
                for a in &g.nodes[n].args {
                    visit(g, *a, set);
                }
            }
        }
        let mut set = BTreeSet::new();
        for r in roots {
            visit(self, *r, &mut set);
        }
        set.into_iter().collect()
    }
    pub fn expression(&self, id: Id) -> String {
        use Op::*;
        let node = &self.nodes[id];
        let prefix = match node.op {
            Source(n) => return ["open", "high", "low", "close", "volume"][n as usize].to_string(),
            Constant(b) => return format!("(constant {b:016x})"),
            Add => "add".into(),
            Sub => "sub".into(),
            Mul => "mul".into(),
            Div => "div".into(),
            Div0 => "div0".into(),
            Min2 => "min2".into(),
            Max2 => "max2".into(),
            Abs => "abs".into(),
            Neg => "neg".into(),
            Lag(n) => format!("lag {n}"),
            Skip(n) => format!("skip {n}"),
            Diff(n) => format!("diff {n}"),
            Mean(n) => format!("mean {n}"),
            MeanSum(n) => format!("mean_sum {n}"),
            StdSum(n) => format!("std_sum {n}"),
            Std(n) => format!("std {n}"),
            Min(n) => format!("min {n}"),
            Max(n) => format!("max {n}"),
            Ema(n) => format!("ema {n}"),
            Wilder(n) => format!("wilder {n}"),
        };
        format!(
            "({} {})",
            prefix,
            node.args
                .iter()
                .map(|x| self.expression(*x))
                .collect::<Vec<_>>()
                .join(" ")
        )
    }
    pub fn identity(&self, id: Id) -> String {
        sha256(format!("filang-expr-v1|{}", self.expression(id)).as_bytes())
    }
    pub fn parse(&mut self, text: &str) -> Result<Id> {
        if text.len() > 64_000 {
            return Err("program text too long".into());
        }
        let tokens = text
            .replace('(', " ( ")
            .replace(')', " ) ")
            .split_whitespace()
            .map(str::to_string)
            .collect::<Vec<_>>();
        let mut at = 0;
        fn take<'a>(ts: &'a [String], at: &mut usize) -> Result<&'a str> {
            let s = ts.get(*at).ok_or("unexpected end of expression")?;
            *at += 1;
            Ok(s)
        }
        fn expr(g: &mut Graph, ts: &[String], at: &mut usize, depth: usize) -> Result<Id> {
            if depth > 64 {
                return Err("expression depth limit".into());
            }
            let token = take(ts, at)?;
            if let Some(i) = ["open", "high", "low", "close", "volume"]
                .iter()
                .position(|x| *x == token)
            {
                return g.add(Op::Source(i as u8), vec![]);
            }
            if token != "(" {
                return Err(format!("expected operation, got {token}"));
            }
            let name = take(ts, at)?;
            let mut args = vec![];
            let op = match name {
                "constant" => Op::Constant(
                    u64::from_str_radix(take(ts, at)?, 16).map_err(|_| "bad constant bits")?,
                ),
                "add" | "sub" | "mul" | "div" | "div0" | "min2" | "max2" => {
                    args.push(expr(g, ts, at, depth + 1)?);
                    args.push(expr(g, ts, at, depth + 1)?);
                    match name {
                        "add" => Op::Add,
                        "sub" => Op::Sub,
                        "mul" => Op::Mul,
                        "div" => Op::Div,
                        "div0" => Op::Div0,
                        "min2" => Op::Min2,
                        _ => Op::Max2,
                    }
                }
                "abs" | "neg" => {
                    args.push(expr(g, ts, at, depth + 1)?);
                    if name == "abs" {
                        Op::Abs
                    } else {
                        Op::Neg
                    }
                }
                "lag" | "skip" | "diff" | "mean" | "mean_sum" | "std_sum" | "std" | "min"
                | "max" | "ema" | "wilder" => {
                    let n = take(ts, at)?.parse::<usize>().map_err(|_| "bad window")?;
                    args.push(expr(g, ts, at, depth + 1)?);
                    match name {
                        "lag" => Op::Lag(n),
                        "skip" => Op::Skip(n),
                        "diff" => Op::Diff(n),
                        "mean" => Op::Mean(n),
                        "mean_sum" => Op::MeanSum(n),
                        "std_sum" => Op::StdSum(n),
                        "std" => Op::Std(n),
                        "min" => Op::Min(n),
                        "max" => Op::Max(n),
                        "ema" => Op::Ema(n),
                        _ => Op::Wilder(n),
                    }
                }
                _ => return Err(format!("unsupported opcode {name}")),
            };
            if take(ts, at)? != ")" {
                return Err("expected closing parenthesis".into());
            }
            g.add(op, args)
        }
        let root = expr(self, &tokens, &mut at, 0)?;
        if at != tokens.len() {
            return Err("trailing expression tokens".into());
        }
        Ok(root)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn types_and_roundtrip() {
        let mut g = Graph::new();
        let a = g
            .parse("(div (sub close (mean 32 close)) (std 32 close))")
            .unwrap();
        let s = g.expression(a);
        assert_eq!(g.parse(&s).unwrap(), a);
        let b = g.parse("(add close volume)");
        assert!(b.is_err());
        assert!(g.parse("(ema 0 close)").is_err());
        assert!(g.parse("(new_magic close)").is_err());
        assert_eq!(g.nodes[a].unit, SCALAR);
        assert_eq!(g.identity(a).len(), 64);
    }
}
