//! Typed predicate/rule IR, version 1. Conservative validity: all operands must
//! be available, including for OR. NOT complements only the valid universe.
//! Qualifiers consume the full causal timeline before the scored range is sliced.
use crate::{
    kernels::Backend,
    lang::{Graph, Id},
    regions::Grid,
    rule_kernels::{self, Logic},
    Result,
};
use std::collections::{BTreeSet, HashMap};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Mask {
    pub bits: Vec<u64>,
    pub valid: Vec<u64>,
    pub len: usize,
}
impl Mask {
    pub fn empty(len: usize) -> Self {
        Self {
            bits: vec![0; (len + 63) / 64],
            valid: vec![0; (len + 63) / 64],
            len,
        }
    }
    pub fn at(&self, t: usize) -> (bool, bool) {
        (
            (self.bits[t / 64] >> (t % 64)) & 1 != 0,
            (self.valid[t / 64] >> (t % 64)) & 1 != 0,
        )
    }
    pub fn set(&mut self, t: usize, value: bool, valid: bool) {
        let b = 1u64 << (t % 64);
        if valid {
            self.valid[t / 64] |= b;
        } else {
            self.valid[t / 64] &= !b;
        }
        if valid && value {
            self.bits[t / 64] |= b;
        } else {
            self.bits[t / 64] &= !b;
        }
    }
    pub fn slice(&self, start: usize, end: usize) -> Result<Self> {
        if start > end || end > self.len {
            return Err("mask range".into());
        }
        let mut out = Self::empty(end - start);
        let shift = start % 64;
        let first = start / 64;
        for (src, dst) in [(&self.bits, &mut out.bits), (&self.valid, &mut out.valid)] {
            for (j, w) in dst.iter_mut().enumerate() {
                let i = first + j;
                *w = src[i] >> shift;
                if shift > 0 && i + 1 < src.len() {
                    *w |= src[i + 1] << (64 - shift);
                }
            }
            if (end - start) % 64 != 0 {
                if let Some(w) = dst.last_mut() {
                    *w &= (1u64 << ((end - start) % 64)) - 1;
                }
            }
        }
        Ok(out)
    }
    pub fn constant_like(&self, value: bool) -> Self {
        Self {
            bits: if value {
                self.valid.clone()
            } else {
                vec![0; self.bits.len()]
            },
            valid: self.valid.clone(),
            len: self.len,
        }
    }
    pub fn payload(&self) -> usize {
        (self.bits.len() + self.valid.len()) * 8 + std::mem::size_of::<Self>()
    }
    pub fn combine(&self, b: &Self, op: Logic, backend: Backend) -> Result<Self> {
        if self.len != b.len {
            return Err("rule timeline mismatch".into());
        }
        let mut out = Self::empty(self.len);
        rule_kernels::combine(&self.valid, &b.valid, &mut out.valid, Logic::And, backend)?;
        rule_kernels::combine(&self.bits, &b.bits, &mut out.bits, op, backend)?;
        for (bits, valid) in out.bits.iter_mut().zip(&out.valid) {
            *bits &= *valid;
        }
        Ok(out)
    }
    pub fn not(&self) -> Self {
        Self {
            bits: self
                .bits
                .iter()
                .zip(&self.valid)
                .map(|(b, v)| !b & v)
                .collect(),
            valid: self.valid.clone(),
            len: self.len,
        }
    }
    pub fn qualify(&self, q: Qualifier) -> Result<Self> {
        match q {
            Qualifier::Plain => Ok(self.clone()),
            Qualifier::Onset => {
                let mut out = Self::empty(self.len);
                for t in 1..self.len {
                    let (x, v) = self.at(t);
                    let (p, pv) = self.at(t - 1);
                    out.set(t, x && !p, v && pv);
                }
                Ok(out)
            }
            Qualifier::Persist(n) | Qualifier::Recent(n) => {
                if n == 0 || n > 100000 {
                    return Err("qualifier window outside 1..100000".into());
                }
                let mut out = Self::empty(self.len);
                let (mut valid, mut count) = (0usize, 0usize);
                for t in 0..self.len {
                    let (x, v) = self.at(t);
                    valid += v as usize;
                    count += x as usize;
                    if t >= n {
                        let (x, v) = self.at(t - n);
                        valid -= v as usize;
                        count -= x as usize;
                    }
                    if t + 1 >= n && valid == n {
                        out.set(
                            t,
                            if matches!(q, Qualifier::Persist(_)) {
                                count == n
                            } else {
                                count > 0
                            },
                            true,
                        );
                    }
                }
                Ok(out)
            }
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Cmp {
    Gt,
    Ge,
    Lt,
    Le,
    Eq,
    Ne,
}
impl Cmp {
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "gt" => Ok(Self::Gt),
            "ge" => Ok(Self::Ge),
            "lt" => Ok(Self::Lt),
            "le" => Ok(Self::Le),
            "eq" => Ok(Self::Eq),
            "ne" => Ok(Self::Ne),
            _ => Err("comparison gt/ge/lt/le/eq/ne".into()),
        }
    }
    pub fn test(self, a: f64, b: f64) -> bool {
        match self {
            Self::Gt => a > b,
            Self::Ge => a >= b,
            Self::Lt => a < b,
            Self::Le => a <= b,
            Self::Eq => a == b,
            Self::Ne => a != b,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Qualifier {
    Plain,
    Persist(usize),
    Recent(usize),
    Onset,
}
impl Qualifier {
    pub fn parse(s: &str) -> Result<Self> {
        if s == "plain" {
            return Ok(Self::Plain);
        }
        if s == "onset" {
            return Ok(Self::Onset);
        }
        let (name, n) = s
            .split_once(':')
            .ok_or("qualifier plain/onset/persist:N/recent:N")?;
        let n = n.parse::<usize>().map_err(|_| "bad qualifier count")?;
        if n == 0 || n > 100000 {
            return Err("qualifier window outside 1..100000".into());
        }
        match name {
            "persist" => Ok(Self::Persist(n)),
            "recent" => Ok(Self::Recent(n)),
            _ => Err("unknown qualifier".into()),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Predicate {
    Threshold(Cmp),
    Relative(Cmp),
    Cross(bool),
    Slope(bool, usize),
}
impl Predicate {
    pub fn parse(s: &str) -> Result<Self> {
        let (a, b) = s
            .split_once(':')
            .ok_or("predicate requires type:argument")?;
        match a {
            "threshold" => Ok(Self::Threshold(Cmp::parse(b)?)),
            "relative" => Ok(Self::Relative(Cmp::parse(b)?)),
            "cross" => match b {
                "above" => Ok(Self::Cross(true)),
                "below" => Ok(Self::Cross(false)),
                _ => Err("cross above/below".into()),
            },
            "slope" => {
                let (d, k) = b
                    .split_once(':')
                    .ok_or("slope:rising:N or slope:falling:N")?;
                let k = k.parse::<usize>().map_err(|_| "bad slope lag")?;
                if k == 0 || k > 100000 || !matches!(d, "rising" | "falling") {
                    return Err("invalid slope".into());
                }
                Ok(Self::Slope(d == "rising", k))
            }
            _ => Err("unknown predicate".into()),
        }
    }
    pub fn validate(&self, g: &Graph, x: Id, y: Option<Id>, grid: Grid) -> Result<()> {
        if let Self::Slope(_, k) = self {
            if *k == 0 || *k > 100000 {
                return Err("slope lag outside 1..100000".into());
            }
        }
        grid.validate()?;
        if x >= g.nodes.len() || y.map_or(false, |i| i >= g.nodes.len()) {
            return Err("predicate input node".into());
        }
        let pair = matches!(self, Self::Relative(_) | Self::Cross(_));
        if pair != y.is_some() {
            return Err("predicate arity".into());
        }
        if let Some(y) = y {
            if g.nodes[x].unit != g.nodes[y].unit {
                return Err("predicate comparisons require equal units".into());
            }
        }
        if !matches!(self, Self::Threshold(_)) && (grid.count != 1 || grid.value(0) != 0.) {
            return Err("non-threshold predicates require the inactive grid 0:1:1:1".into());
        }
        Ok(())
    }
    pub fn evaluate(
        &self,
        x: &[f64],
        y: Option<&[f64]>,
        cut: f64,
        qualifiers: &[Qualifier],
    ) -> Result<Mask> {
        if matches!(self, Self::Slope(_, n) if *n==0 || *n>100000) {
            return Err("slope lag outside 1..100000".into());
        }
        if !cut.is_finite() || y.map_or(false, |a| a.len() != x.len()) {
            return Err("predicate numerical context".into());
        }
        if matches!(self, Self::Relative(_) | Self::Cross(_)) != y.is_some() {
            return Err("predicate arity".into());
        }
        let mut out = Mask::empty(x.len());
        for t in 0..x.len() {
            let a = x[t];
            match *self {
                Self::Threshold(c) => out.set(t, c.test(a, cut), a.is_finite()),
                Self::Relative(c) => {
                    let b = y.unwrap()[t];
                    out.set(t, c.test(a, b), a.is_finite() && b.is_finite());
                }
                Self::Cross(above) if t > 0 => {
                    let yy = y.unwrap();
                    let valid = a.is_finite()
                        && yy[t].is_finite()
                        && x[t - 1].is_finite()
                        && yy[t - 1].is_finite();
                    let v = if above {
                        a > yy[t] && x[t - 1] <= yy[t - 1]
                    } else {
                        a < yy[t] && x[t - 1] >= yy[t - 1]
                    };
                    out.set(t, v, valid);
                }
                Self::Slope(up, k) if t >= k => {
                    let b = x[t - k];
                    out.set(
                        t,
                        if up { a > b } else { a < b },
                        a.is_finite() && b.is_finite(),
                    );
                }
                _ => {}
            }
        }
        for &q in qualifiers {
            out = out.qualify(q)?;
        }
        Ok(out)
    }
}
#[derive(Clone, Debug)]
pub struct Cell {
    pub lo: u64,
    pub hi: u64,
    pub mask: Mask,
}
/// Grid cutpoints are calculated without enumerating the grid. This works for
/// signed values and inclusive/equality predicates without subtraction rewrites.
pub fn cells(
    predicate: &Predicate,
    x: &[f64],
    y: Option<&[f64]>,
    grid: Grid,
    qualifiers: &[Qualifier],
    budget: usize,
) -> Result<Vec<Cell>> {
    grid.validate()?;
    if !matches!(predicate, Predicate::Threshold(_)) {
        if grid.count != 1 || grid.value(0) != 0. {
            return Err("non-threshold predicate requires singleton zero grid".into());
        }
        let m = predicate.evaluate(x, y, 0., qualifiers)?;
        if m.payload() > budget {
            return Err("predicate bank budget".into());
        }
        return Ok(vec![Cell {
            lo: 0,
            hi: 1,
            mask: m,
        }]);
    }
    let cmp = match predicate {
        Predicate::Threshold(c) => *c,
        _ => unreachable!(),
    };
    let mut edges = vec![0, grid.count];
    for &x in x {
        if !x.is_finite() {
            continue;
        }
        let l = grid.lower_bound(x);
        let mut u = l;
        while u < grid.count && grid.value(u) == x {
            // Jump over representational ties by binary search, not a grid walk.
            let (mut lo, mut hi) = (u, grid.count);
            while lo < hi {
                let mid = lo + (hi - lo) / 2;
                if grid.value(mid) <= x {
                    lo = mid + 1;
                } else {
                    hi = mid;
                }
            }
            u = lo;
        }
        match cmp {
            Cmp::Gt | Cmp::Le => edges.push(l),
            Cmp::Ge | Cmp::Lt => edges.push(u),
            Cmp::Eq | Cmp::Ne => {
                edges.push(l);
                edges.push(u);
            }
        }
    }
    edges.sort_unstable();
    edges.dedup();
    let mut out: Vec<Cell> = Vec::new();
    let mut used = 0usize;
    for pair in edges.windows(2) {
        let (lo, hi) = (pair[0], pair[1]);
        if lo == hi || lo >= grid.count {
            continue;
        }
        let mask = predicate.evaluate(x, y, grid.value(lo), qualifiers)?;
        if let Some(last) = out.last_mut() {
            if last.mask == mask {
                last.hi = hi;
                continue;
            }
        }
        used = used
            .checked_add(mask.payload() + std::mem::size_of::<Cell>())
            .ok_or("predicate budget overflow")?;
        if used > budget {
            return Err(
                "predicate cell bank exceeds budget; reduce alternatives or history".into(),
            );
        }
        out.push(Cell { lo, hi, mask });
    }
    Ok(out)
}
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Node {
    Slot(usize),
    And(usize, usize),
    Or(usize, usize),
    Not(usize),
    Persist(usize, usize),
    Recent(usize, usize),
    Onset(usize),
}
#[derive(Clone, Debug)]
pub struct Program {
    pub nodes: Vec<Node>,
    pub root: usize,
    pub slots: usize,
    pub text: String,
}
impl Program {
    pub fn parse(text: &str, slots: usize) -> Result<Self> {
        if slots == 0 || slots > 8 || text.len() > 64000 {
            return Err("rule program input limits".into());
        }
        let tokens = text
            .replace('(', " ( ")
            .replace(')', " ) ")
            .split_whitespace()
            .map(str::to_owned)
            .collect::<Vec<_>>();
        fn take<'a>(t: &'a [String], p: &mut usize) -> Result<&'a str> {
            let x = t.get(*p).ok_or("incomplete rule expression")?;
            *p += 1;
            Ok(x)
        }
        fn parse(
            t: &[String],
            p: &mut usize,
            nodes: &mut Vec<Node>,
            intern: &mut HashMap<Node, usize>,
            slots: usize,
            depth: usize,
        ) -> Result<usize> {
            if depth > 64 || nodes.len() > 256 {
                return Err("rule depth/node budget".into());
            }
            let token = take(t, p)?;
            let node = if let Some(s) = token.strip_prefix('s') {
                let i = s.parse::<usize>().map_err(|_| "bad slot")?;
                if i >= slots {
                    return Err("slot outside domain".into());
                }
                Node::Slot(i)
            } else {
                if token != "(" {
                    return Err("expected rule operation".into());
                }
                let op = take(t, p)?;
                let window = if matches!(op, "persist" | "recent") {
                    let n = take(t, p)?.parse::<usize>().map_err(|_| "rule window")?;
                    if n == 0 || n > 100000 {
                        return Err("rule window outside 1..100000".into());
                    }
                    n
                } else {
                    0
                };
                let a = parse(t, p, nodes, intern, slots, depth + 1)?;
                let result = match op {
                    "and" => Node::And(a, parse(t, p, nodes, intern, slots, depth + 1)?),
                    "or" => Node::Or(a, parse(t, p, nodes, intern, slots, depth + 1)?),
                    "not" => Node::Not(a),
                    "persist" => Node::Persist(a, window),
                    "recent" => Node::Recent(a, window),
                    "onset" => Node::Onset(a),
                    _ => return Err("unknown rule opcode".into()),
                };
                if take(t, p)? != ")" {
                    return Err("expected rule closing parenthesis".into());
                }
                result
            };
            if let Some(&i) = intern.get(&node) {
                return Ok(i);
            }
            let i = nodes.len();
            nodes.push(node.clone());
            intern.insert(node, i);
            Ok(i)
        }
        let mut at = 0;
        let mut nodes = Vec::new();
        let root = parse(&tokens, &mut at, &mut nodes, &mut HashMap::new(), slots, 0)?;
        if at != tokens.len() {
            return Err("trailing rule tokens".into());
        }
        Ok(Self {
            nodes,
            root,
            slots,
            text: text.into(),
        })
    }
    pub fn used_slots(&self) -> BTreeSet<usize> {
        self.nodes
            .iter()
            .filter_map(|n| {
                if let Node::Slot(s) = n {
                    Some(*s)
                } else {
                    None
                }
            })
            .collect()
    }
    pub fn pointwise(&self) -> bool {
        !self
            .nodes
            .iter()
            .any(|n| matches!(n, Node::Persist(..) | Node::Recent(..) | Node::Onset(_)))
    }
    pub fn evaluate(&self, inputs: &[&Mask], backend: Backend) -> Result<Mask> {
        if inputs.len() != self.slots || inputs.iter().any(|m| m.len != inputs[0].len) {
            return Err("rule slot/timeline mismatch".into());
        }
        let mut result: Vec<Mask> = Vec::with_capacity(self.nodes.len());
        for n in &self.nodes {
            let m = match *n {
                Node::Slot(s) => inputs[s].clone(),
                Node::And(a, b) => result[a].combine(&result[b], Logic::And, backend)?,
                Node::Or(a, b) => result[a].combine(&result[b], Logic::Or, backend)?,
                Node::Not(a) => result[a].not(),
                Node::Persist(a, n) => result[a].qualify(Qualifier::Persist(n))?,
                Node::Recent(a, n) => result[a].qualify(Qualifier::Recent(n))?,
                Node::Onset(a) => result[a].qualify(Qualifier::Onset)?,
            };
            result.push(m);
        }
        Ok(result.swap_remove(self.root))
    }
    /// Shannon cofactors apply only to pointwise Boolean graphs. Compound temporal
    /// rules use evaluate(), because changing one row can influence later rows.
    pub fn cofactors(
        &self,
        inputs: &[&Mask],
        slot: usize,
        backend: Backend,
    ) -> Result<(Mask, Mask)> {
        if !self.pointwise() || slot >= inputs.len() {
            return Err("cofactor plan needs pointwise graph and valid slot".into());
        }
        let zero = inputs[slot].constant_like(false);
        let one = inputs[slot].constant_like(true);
        let mut refs = inputs.to_vec();
        refs[slot] = &zero;
        let a = self.evaluate(&refs, backend)?;
        refs[slot] = &one;
        let b = self.evaluate(&refs, backend)?;
        if a.valid != b.valid {
            return Err("cofactor validity unexpectedly depends on Boolean value".into());
        }
        Ok((a, b))
    }
}
