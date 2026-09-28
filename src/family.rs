//! Objective-aware family compiler. Stateful dependencies are shared; terminal
//! pointwise programs execute in bounded tiles and lower directly to packed bits.
use crate::{
    backtest::Rule,
    data::Data,
    engine, family_kernels,
    kernels::{self, Backend},
    lang::{Graph, Id, Op},
    packed::Mask,
    Result,
};
use std::collections::{BTreeMap, HashMap, HashSet};
const TILE: usize = 256;
#[derive(Clone, Copy, Default, Debug)]
pub struct Work {
    pub nodes: usize,
    pub temporal_passes: usize,
    pub grouped_moment_nodes: usize,
    pub recurrence_lanes: usize,
    pub simd_recurrence_lanes: usize,
    pub cached: usize,
    pub payload: usize,
}
pub struct Store {
    pub values: HashMap<Id, Vec<f64>>,
    pub work: Work,
    nodes: Vec<crate::lang::Node>,
    digest: String,
    rows: usize,
}
impl Store {
    pub fn series<'a>(&'a self, id: Id, bank: Option<&'a Store>) -> Result<&'a [f64]> {
        self.values
            .get(&id)
            .or_else(|| bank.and_then(|b| b.values.get(&id)))
            .map(Vec::as_slice)
            .ok_or_else(|| format!("family missing node {id}"))
    }
}
fn temporal(o: &Op) -> bool {
    matches!(
        o,
        Op::Lag(_)
            | Op::Skip(_)
            | Op::Diff(_)
            | Op::Mean(_)
            | Op::MeanSum(_)
            | Op::StdSum(_)
            | Op::Std(_)
            | Op::Min(_)
            | Op::Max(_)
            | Op::Ema(_)
            | Op::Wilder(_)
    )
}
/// Only nodes consumed by temporal operators require full numerical histories.
pub fn boundaries(g: &Graph, roots: &[Id]) -> Vec<Id> {
    g.dependencies(roots)
        .into_iter()
        .filter(|id| temporal(&g.nodes[*id].op) || matches!(g.nodes[*id].op, Op::Source(_)))
        .collect()
}
pub fn prepare(
    g: &Graph,
    d: &Data,
    roots: &[Id],
    budget: usize,
    backend: Backend,
    bank: Option<&Store>,
) -> Result<Store> {
    Backend::resolve(backend.name())?;
    if roots.iter().any(|id| *id >= g.nodes.len()) {
        return Err("unknown family root".into());
    }
    if let Some(b) = bank {
        if b.digest != d.digest
            || b.rows != d.len()
            || g.nodes.get(..b.nodes.len()) != Some(b.nodes.as_slice())
        {
            return Err("family bank context mismatch".into());
        }
    }
    let deps = g.dependencies(roots);
    let missing = deps
        .iter()
        .filter(|id| bank.map_or(true, |b| !b.values.contains_key(id)))
        .copied()
        .collect::<Vec<_>>();
    let payload = (missing.len() + 8)
        .checked_mul(d.len())
        .and_then(|n| n.checked_mul(8))
        .ok_or("family payload overflow")?;
    if payload > budget {
        return Err(format!("family payload {payload} exceeds {budget}"));
    }
    let mut moments: BTreeMap<(Id, usize, bool), Vec<Id>> = BTreeMap::new();
    let mut rec: BTreeMap<Id, Vec<Id>> = BTreeMap::new();
    for &id in &missing {
        match g.nodes[id].op {
            Op::Mean(w) | Op::Std(w) | Op::MeanSum(w) | Op::StdSum(w) => moments
                .entry((
                    g.nodes[id].args[0],
                    w,
                    matches!(g.nodes[id].op, Op::MeanSum(_) | Op::StdSum(_)),
                ))
                .or_default()
                .push(id),
            Op::Ema(_) | Op::Wilder(_) => rec.entry(g.nodes[id].args[0]).or_default().push(id),
            _ => {}
        }
    }
    let mut store = Store {
        values: HashMap::new(),
        work: Work {
            cached: deps.len() - missing.len(),
            payload,
            ..Work::default()
        },
        nodes: g.nodes.clone(),
        digest: d.digest.clone(),
        rows: d.len(),
    };
    for id in missing {
        if store.values.contains_key(&id) {
            continue;
        }
        let n = &g.nodes[id];
        match n.op {
            Op::Mean(w) | Op::Std(w) | Op::MeanSum(w) | Op::StdSum(w)
                if moments[&(n.args[0], w, matches!(n.op, Op::MeanSum(_) | Op::StdSum(_)))]
                    .len()
                    == 2 =>
            {
                let raw = matches!(n.op, Op::MeanSum(_) | Op::StdSum(_));
                let (m, s) = if raw {
                    family_kernels::raw_moments(store.series(n.args[0], bank)?, w)
                } else {
                    family_kernels::moments_pair(store.series(n.args[0], bank)?, w)
                };
                let mut mean = Some(m);
                let mut deviation = Some(s);
                for &j in &moments[&(n.args[0], w, raw)] {
                    let out = if matches!(g.nodes[j].op, Op::Mean(_) | Op::MeanSum(_)) {
                        mean.take().unwrap()
                    } else {
                        deviation.take().unwrap()
                    };
                    store.values.insert(j, out);
                }
                store.work.nodes += 2;
                store.work.grouped_moment_nodes += 2;
                store.work.temporal_passes += 1;
            }
            Op::Ema(_) | Op::Wilder(_) => {
                let ids = &rec[&n.args[0]];
                let specs = ids
                    .iter()
                    .map(|j| match g.nodes[*j].op {
                        Op::Ema(w) => (w, 2.0 / (w + 1) as f64),
                        Op::Wilder(w) => (w, 1.0 / w as f64),
                        _ => unreachable!(),
                    })
                    .collect::<Vec<_>>();
                let outs =
                    family_kernels::recurrences(store.series(n.args[0], bank)?, &specs, backend)?;
                for (&j, out) in ids.iter().zip(outs) {
                    store.values.insert(j, out);
                }
                store.work.nodes += ids.len();
                store.work.recurrence_lanes += ids.len();
                store.work.temporal_passes += (ids.len() + 3) / 4;
                if backend != Backend::Scalar {
                    store.work.simd_recurrence_lanes += ids.len();
                }
            }
            _ => {
                let a = n.args.first().map(|i| store.series(*i, bank)).transpose()?;
                let b = n.args.get(1).map(|i| store.series(*i, bank)).transpose()?;
                let out = if matches!(n.op, Op::Add | Op::Sub | Op::Mul | Op::Div) {
                    kernels::binary(&n.op, a.unwrap(), b.unwrap(), backend)?
                } else {
                    engine::kernel(&n.op, a, b, d)
                };
                store.values.insert(id, out);
                store.work.nodes += 1;
                if temporal(&n.op) {
                    store.work.temporal_passes += 1;
                }
            }
        }
    }
    Ok(store)
}
#[derive(Clone)]
enum Instruction {
    Leaf(Id),
    Constant(f64),
    Point(Op, usize, Option<usize>),
}
pub struct Program {
    code: Vec<Instruction>,
    pub point_nodes: usize,
}
impl Program {
    pub fn compile(g: &Graph, root: Id, store: &Store, bank: Option<&Store>) -> Result<Self> {
        if root >= g.nodes.len() {
            return Err("unknown fused root".into());
        }
        fn visit(
            g: &Graph,
            id: Id,
            store: &Store,
            bank: Option<&Store>,
            code: &mut Vec<Instruction>,
            slots: &mut HashMap<Id, usize>,
        ) -> Result<usize> {
            if let Some(&s) = slots.get(&id) {
                return Ok(s);
            }
            let n = &g.nodes[id];
            let instruction = if store.values.contains_key(&id)
                || bank.map_or(false, |b| b.values.contains_key(&id))
            {
                Instruction::Leaf(id)
            } else {
                match n.op {
                    Op::Constant(b) => Instruction::Constant(f64::from_bits(b)),
                    ref op if !temporal(op) => {
                        let a = visit(g, n.args[0], store, bank, code, slots)?;
                        let b = n
                            .args
                            .get(1)
                            .map(|i| visit(g, *i, store, bank, code, slots))
                            .transpose()?;
                        Instruction::Point(op.clone(), a, b)
                    }
                    _ => return Err("temporal node missing at fusion boundary".into()),
                }
            };
            let slot = code.len();
            code.push(instruction);
            slots.insert(id, slot);
            Ok(slot)
        }
        let mut code = vec![];
        visit(g, root, store, bank, &mut code, &mut HashMap::new())?;
        let point_nodes = code
            .iter()
            .filter(|c| matches!(c, Instruction::Point(..)))
            .count();
        if code.len() > 512 {
            return Err("fused program exceeds 512 instructions".into());
        }
        Ok(Self { code, point_nodes })
    }
    pub fn execute(
        &self,
        store: &Store,
        bank: Option<&Store>,
        rules: &[Rule],
        backend: Backend,
        capture: bool,
    ) -> Result<(Vec<Mask>, Option<Vec<f64>>)> {
        Backend::resolve(backend.name())?;
        if rules.iter().any(|r| !r.threshold.is_finite()) {
            return Err("nonfinite fused threshold".into());
        }
        let n = store.rows;
        let mut scratch = vec![vec![f64::NAN; TILE]; self.code.len()];
        let mut masks = vec![Mask::empty(); rules.len()];
        let mut values = if capture {
            Some(Vec::with_capacity(n))
        } else {
            None
        };
        for lo in (0..n).step_by(TILE) {
            let len = TILE.min(n - lo);
            for (i, op) in self.code.iter().enumerate() {
                let (prior, rest) = scratch.split_at_mut(i);
                let dst = &mut rest[0][..len];
                match op {
                    Instruction::Leaf(id) => {
                        dst.copy_from_slice(&store.series(*id, bank)?[lo..lo + len])
                    }
                    Instruction::Constant(v) => dst.fill(*v),
                    Instruction::Point(op, a, b) => {
                        let x = &prior[*a][..len];
                        let y = b.map(|j| &prior[j][..len]);
                        if matches!(op, Op::Add | Op::Sub | Op::Mul | Op::Div) {
                            kernels::binary_into(op, x, y.unwrap(), dst, backend)?;
                        } else {
                            for t in 0..len {
                                let xx = x[t];
                                let yy = y.map_or(0.0, |v| v[t]);
                                let v = match op {
                                    Op::Div0 if xx.is_finite() && yy.is_finite() => {
                                        if yy.abs() > 1e-12 {
                                            xx / yy
                                        } else {
                                            0.0
                                        }
                                    }
                                    Op::Abs => xx.abs(),
                                    Op::Neg => -xx,
                                    Op::Min2 if xx.is_finite() && yy.is_finite() => xx.min(yy),
                                    Op::Max2 if xx.is_finite() && yy.is_finite() => xx.max(yy),
                                    _ => f64::NAN,
                                };
                                dst[t] = if v.is_finite() { v } else { f64::NAN };
                            }
                        }
                    }
                }
            }
            let out = &scratch.last().unwrap()[..len];
            if let Some(v) = values.as_mut() {
                v.extend_from_slice(out);
            }
            for (mask, &rule) in masks.iter_mut().zip(rules) {
                mask.append(&Mask::threshold(out, rule, backend)?);
            }
        }
        Ok((masks, values))
    }
}
/// Structural dependency closure used for audit counters, not a global seen set.
pub fn distinct_roots(roots: &[Id]) -> usize {
    roots.iter().copied().collect::<HashSet<_>>().len()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture(n: usize) -> Data {
        Data {
            timestamps: (0..n as i64).collect(),
            columns: std::array::from_fn(|j| {
                (0..n)
                    .map(|t| {
                        if t % 347 == 0 {
                            f64::NAN
                        } else {
                            100.0 + j as f64 + (t as f64 / 13.0).sin()
                        }
                    })
                    .collect()
            }),
            interval: 1,
            digest: "family-tests".into(),
        }
    }
    #[test]
    fn arbitrary_atom_programs_fuse_and_group_without_labels() {
        let d = fixture(1101);
        let mut g = Graph::new();
        let a = g.source(3);
        let b = g.source(4);
        let ratio = g.binary(Op::Div, a, b);
        let m = g.unary(Op::Mean(11), ratio);
        let std = g.unary(Op::Std(11), ratio);
        let e = g.unary(Op::Ema(7), ratio);
        let f = g.unary(Op::Ema(19), ratio);
        let sub = g.binary(Op::Sub, e, m);
        let z = g.binary(Op::Div, sub, std);
        let mixed = g.binary(Op::Mul, z, f);
        let roots = [mixed, z, e, f];
        for backend in [Backend::Scalar, Backend::resolve("auto").unwrap()] {
            let fast = prepare(
                &g,
                &d,
                &boundaries(&g, &roots),
                32 * 1024 * 1024,
                backend,
                None,
            )
            .unwrap();
            assert_eq!(fast.work.grouped_moment_nodes, 2);
            assert!(fast.work.recurrence_lanes >= 2);
            let direct = engine::evaluate(&g, &d, &roots, 32 * 1024 * 1024).unwrap();
            for &r in &roots {
                let p = Program::compile(&g, r, &fast, None).unwrap();
                let rules = [
                    Rule {
                        threshold: 0.0,
                        greater: true,
                    },
                    Rule {
                        threshold: 0.02,
                        greater: false,
                    },
                ];
                let (masks, values) = p.execute(&fast, None, &rules, backend, true).unwrap();
                for (x, y) in values.unwrap().iter().zip(&direct.values[&r]) {
                    assert!(x.to_bits() == y.to_bits() || (x.is_nan() && y.is_nan()));
                }
                for (mask, rule) in masks.iter().zip(rules) {
                    assert_eq!(
                        *mask,
                        Mask::threshold(&direct.values[&r], rule, Backend::Scalar).unwrap()
                    );
                }
            }
            let earlier = d.prefix(600);
            let f = prepare(
                &g,
                &earlier,
                &boundaries(&g, &roots),
                32 * 1024 * 1024,
                backend,
                None,
            )
            .unwrap();
            let p = Program::compile(&g, mixed, &f, None).unwrap();
            let before = p.execute(&f, None, &[], backend, true).unwrap().1.unwrap();
            for (x, y) in before.iter().zip(&direct.values[&mixed]) {
                assert!(x.to_bits() == y.to_bits() || (x.is_nan() && y.is_nan()));
            }
        }
    }
    #[test]
    fn budget_and_context_are_not_optional() {
        let d = fixture(100);
        let mut g = Graph::new();
        let c = g.source(3);
        let root = g.unary(Op::Mean(20), c);
        assert!(prepare(&g, &d, &[root], 1, Backend::Scalar, None).is_err());
        let bank = prepare(&g, &d, &[root], 100000, Backend::Scalar, None).unwrap();
        let mut other = d;
        other.digest = "other".into();
        assert!(prepare(&g, &other, &[root], 100000, Backend::Scalar, Some(&bank)).is_err());
    }
}
