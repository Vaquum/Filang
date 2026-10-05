//! Exact set-product certificates over predicate signatures, independent of
//! indicator labels and numerical parameter generation. Conservative validity.
use crate::{
    dense_bank::{validate_mask, Coordinate, Entry},
    kernels::Backend,
    rules::{Mask, Program},
    Result,
};
#[derive(Clone, Debug)]
pub struct Node {
    pub lo: usize,
    pub hi: usize,
    pub children: Option<(usize, usize)>,
    pub count: u128,
    pub first: Coordinate,
    all: Vec<u64>,
    any: Vec<u64>,
    valid_all: Vec<u64>,
    valid_any: Vec<u64>,
}
pub struct Tree<'a> {
    pub entries: &'a [Entry],
    pub order: Vec<usize>,
    pub nodes: Vec<Node>,
    pub root: usize,
    pub rows: usize,
    pub payload: usize,
}
impl<'a> Tree<'a> {
    pub fn new(entries: &'a [Entry], budget: usize) -> Result<Self> {
        if entries.is_empty() {
            return Err("empty predicate state bank".into());
        }
        let rows = entries[0].mask.len;
        let words = (rows + 63) / 64;
        let payload = entries
            .len()
            .checked_mul(2)
            .and_then(|n| n.checked_mul(words * 32 + 256))
            .ok_or("tree payload overflow")?;
        if payload > budget {
            return Err("predicate tree budget exceeded".into());
        }
        for e in entries {
            validate_mask(&e.mask, rows)?;
            if e.count == 0 {
                return Err("empty predicate member set".into());
            }
        }
        let mut order: Vec<_> = (0..entries.len()).collect();
        order.sort_unstable_by(|&a, &b| {
            entries[a]
                .mask
                .bits
                .cmp(&entries[b].mask.bits)
                .then(entries[a].mask.valid.cmp(&entries[b].mask.valid))
                .then(a.cmp(&b))
        });
        let mut tree = Self {
            entries,
            order,
            nodes: Vec::with_capacity(entries.len() * 2),
            root: 0,
            rows,
            payload,
        };
        tree.root = tree.build(0, entries.len())?;
        Ok(tree)
    }
    fn build(&mut self, lo: usize, hi: usize) -> Result<usize> {
        let n = if hi - lo == 1 {
            let e = &self.entries[self.order[lo]];
            Node {
                lo,
                hi,
                children: None,
                count: e.count,
                first: e.first,
                all: e.mask.bits.clone(),
                any: e.mask.bits.clone(),
                valid_all: e.mask.valid.clone(),
                valid_any: e.mask.valid.clone(),
            }
        } else {
            let mid = lo + (hi - lo) / 2;
            let a = self.build(lo, mid)?;
            let b = self.build(mid, hi)?;
            let aa = &self.nodes[a];
            let bb = &self.nodes[b];
            Node {
                lo,
                hi,
                children: Some((a, b)),
                count: aa
                    .count
                    .checked_add(bb.count)
                    .ok_or("tree count overflow")?,
                first: aa.first.min(bb.first),
                all: aa.all.iter().zip(&bb.all).map(|(a, b)| a & b).collect(),
                any: aa.any.iter().zip(&bb.any).map(|(a, b)| a | b).collect(),
                valid_all: aa
                    .valid_all
                    .iter()
                    .zip(&bb.valid_all)
                    .map(|(a, b)| a & b)
                    .collect(),
                valid_any: aa
                    .valid_any
                    .iter()
                    .zip(&bb.valid_any)
                    .map(|(a, b)| a | b)
                    .collect(),
            }
        };
        let id = self.nodes.len();
        self.nodes.push(n);
        Ok(id)
    }
    pub fn frontier(&self, max_leaves: usize) -> Result<Vec<usize>> {
        if max_leaves == 0 {
            return Err("zero task block".into());
        }
        fn walk(t: &Tree<'_>, id: usize, max: usize, out: &mut Vec<usize>) {
            let n = &t.nodes[id];
            if n.hi - n.lo <= max {
                out.push(id);
            } else {
                let (a, b) = n.children.unwrap();
                walk(t, a, max, out);
                walk(t, b, max, out);
            }
        }
        let mut out = Vec::new();
        walk(self, self.root, max_leaves, &mut out);
        Ok(out)
    }
}
#[derive(Clone, Copy, Debug)]
pub struct Table {
    pub truth: [bool; 4],
}
impl Table {
    pub fn from_program(p: &Program) -> Result<Self> {
        if p.slots != 2 || p.used_slots().len() != 2 || !p.pointwise() {
            return Err(
                "dense set certificates require a pointwise two-slot rule using both slots".into(),
            );
        }
        let mut truth = [false; 4];
        for (i, v) in truth.iter_mut().enumerate() {
            let mut a = Mask::empty(1);
            let mut b = Mask::empty(1);
            a.set(0, i & 2 != 0, true);
            b.set(0, i & 1 != 0, true);
            *v = p.evaluate(&[&a, &b], Backend::Scalar)?.at(0).0;
        }
        Ok(Self { truth })
    }
    fn bounds(&self, a: &Node, b: &Node, w: usize) -> (u64, u64) {
        let pa = [!a.all[w], a.any[w]];
        let pb = [!b.all[w], b.any[w]];
        let (mut yes, mut no) = (0, 0);
        for (i, &av) in pa.iter().enumerate() {
            for (j, &bv) in pb.iter().enumerate() {
                let possible = av & bv;
                if self.truth[i * 2 + j] {
                    yes |= possible;
                } else {
                    no |= possible;
                }
            }
        }
        (
            !no & a.valid_all[w] & b.valid_all[w],
            yes & a.valid_any[w] & b.valid_any[w],
        )
    }
}
#[derive(Clone, Copy, Default, Debug)]
pub struct Work {
    pub node_pairs: u64,
    pub proved_regions: u64,
    pub leaf_pairs: u64,
    pub signature_pairs: u128,
    pub logical: u128,
    pub bound_words: u64,
}
#[derive(Clone, Debug)]
pub struct Region {
    pub left: usize,
    pub right: usize,
    pub count: u128,
    pub left_first: Coordinate,
    pub right_first: Coordinate,
}
/// Visit products of signature sets whose final positions are provably identical.
/// Bounds are exact bit sets, not financial score bounds or a pruning heuristic.
#[allow(clippy::too_many_arguments)]
pub fn visit<F>(
    left: &Tree<'_>,
    right: &Tree<'_>,
    left_root: usize,
    right_root: usize,
    table: Table,
    proof: bool,
    max_nodes: u64,
    mut emit: F,
) -> Result<Work>
where
    F: FnMut(&Region, &[u64]) -> Result<()>,
{
    if left.rows != right.rows || left_root >= left.nodes.len() || right_root >= right.nodes.len() {
        return Err("tree context/range mismatch".into());
    }
    struct Walk<'a, 'b, 'c, 'd, F> {
        l: &'a Tree<'b>,
        r: &'c Tree<'d>,
        t: Table,
        proof: bool,
        max: u64,
        w: Work,
        scratch: Vec<u64>,
        emit: F,
    }
    impl<F> Walk<'_, '_, '_, '_, F>
    where
        F: FnMut(&Region, &[u64]) -> Result<()>,
    {
        fn go(&mut self, ai: usize, bi: usize) -> Result<()> {
            if self.w.node_pairs >= self.max {
                return Err(
                    "physical pair-node budget exhausted; current task is not committed".into(),
                );
            }
            self.w.node_pairs += 1;
            let a = &self.l.nodes[ai];
            let b = &self.r.nodes[bi];
            let leaves = a.children.is_none() && b.children.is_none();
            let mut exact = self.proof || leaves;
            if exact {
                for w in 0..self.scratch.len() {
                    let (lo, hi) = self.t.bounds(a, b, w);
                    self.w.bound_words += 1;
                    if lo != hi {
                        exact = false;
                        break;
                    }
                    self.scratch[w] = lo;
                }
            }
            if exact {
                let count = a
                    .count
                    .checked_mul(b.count)
                    .ok_or("pair coverage overflow")?;
                let region = Region {
                    left: ai,
                    right: bi,
                    count,
                    left_first: a.first,
                    right_first: b.first,
                };
                (self.emit)(&region, &self.scratch)?;
                self.w.logical = self
                    .w
                    .logical
                    .checked_add(count)
                    .ok_or("coverage overflow")?;
                self.w.signature_pairs = self
                    .w
                    .signature_pairs
                    .checked_add(((a.hi - a.lo) as u128) * ((b.hi - b.lo) as u128))
                    .ok_or("signature pairs overflow")?;
                if leaves {
                    self.w.leaf_pairs += 1;
                } else {
                    self.w.proved_regions += 1;
                }
                return Ok(());
            }
            if leaves {
                return Err("nonexact leaf certificate".into());
            }
            if b.children.is_none() || a.children.is_some() && (a.hi - a.lo) >= (b.hi - b.lo) {
                let (x, y) = a.children.unwrap();
                self.go(x, bi)?;
                self.go(y, bi)
            } else {
                let (x, y) = b.children.unwrap();
                self.go(ai, x)?;
                self.go(ai, y)
            }
        }
    }
    let mut walk = Walk {
        l: left,
        r: right,
        t: table,
        proof,
        max: max_nodes,
        w: Work::default(),
        scratch: vec![0; (left.rows + 63) / 64],
        emit: &mut emit,
    };
    walk.go(left_root, right_root)?;
    let expected = left.nodes[left_root]
        .count
        .checked_mul(right.nodes[right_root].count)
        .ok_or("expected count overflow")?;
    if walk.w.logical != expected {
        return Err("tree coverage mismatch".into());
    }
    Ok(walk.w)
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::dense_bank::Builder;
    #[test]
    fn all_two_slot_rules_masks_and_weighted_coverage() {
        let mut bank = Builder::new(7, 1 << 20).unwrap();
        for i in 0..55u64 {
            let mut m = Mask::empty(7);
            for t in 0..7 {
                m.set(t, (i >> (t % 6)) & 1 != 0, (i + 3 * t as u64) % 7 != 0);
            }
            bank.intern(
                &m,
                (i + 1) as u128,
                Coordinate {
                    atom: i,
                    ..Coordinate::default()
                },
            )
            .unwrap();
        }
        let tree = Tree::new(&bank.entries, 1 << 24).unwrap();
        for text in [
            "(and s0 s1)",
            "(or s0 s1)",
            "(and s0 (not s1))",
            "(not (and (not s0) (not s1)))",
        ] {
            let p = Program::parse(text, 2).unwrap();
            let table = Table::from_program(&p).unwrap();
            for proof in [false, true] {
                let mut seen = vec![false; tree.entries.len() * tree.entries.len()];
                let work = visit(
                    &tree,
                    &tree,
                    tree.root,
                    tree.root,
                    table,
                    proof,
                    100000,
                    |r, words| {
                        for i in tree.nodes[r.left].lo..tree.nodes[r.left].hi {
                            for j in tree.nodes[r.right].lo..tree.nodes[r.right].hi {
                                assert!(!seen[i * tree.entries.len() + j]);
                                seen[i * tree.entries.len() + j] = true;
                                let want = p
                                    .evaluate(
                                        &[
                                            &tree.entries[tree.order[i]].mask,
                                            &tree.entries[tree.order[j]].mask,
                                        ],
                                        Backend::Scalar,
                                    )
                                    .unwrap();
                                assert_eq!(want.bits, words);
                            }
                        }
                        Ok(())
                    },
                )
                .unwrap();
                assert!(seen.iter().all(|v| *v));
                assert_eq!(work.logical, bank.addresses * bank.addresses);
            }
        }
    }
}
