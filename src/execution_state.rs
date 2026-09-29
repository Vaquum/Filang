//! Full-risk state for arbitrary changes between packed position programs.
//! Time and costs are fixed in this context. No feature or indicator identity is used.
//! The same dirty tree topology serves every cost scenario. A run-product monoid
//! supports both joining and splitting trades; no insertion-only union-find state.
use super::{Costs, Lite, Market, Metrics};
use crate::{data::Data, Result};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransitionMode {
    Auto,
    Delta,
    Rebuild,
}
impl TransitionMode {
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "auto" => Ok(Self::Auto),
            "delta" => Ok(Self::Delta),
            "rebuild" => Ok(Self::Rebuild),
            _ => Err("transition must be auto/delta/rebuild".into()),
        }
    }
}
#[derive(Clone, Debug, Default)]
pub struct ChangeWork {
    pub all_off: u64,
    pub all_on: u64,
    pub requests: u64,
    pub identical: u64,
    pub full_replays: u64,
    pub replay_periods: u64,
    pub decoded_changes: u64,
    pub rebuilds: u64,
    pub deltas: u64,
    pub words_compared: u64,
    pub flips: u64,
    pub activations: u64,
    pub deactivations: u64,
    pub joins: u64,
    pub splits: u64,
    pub dirty_leaves: u64,
    pub tree_merges: u64,
    pub scenario_leaf_updates: u64,
    pub scenario_tree_merges: u64,
    pub flip_histogram: [u64; 8],
}
impl ChangeWork {
    pub fn json(&self) -> String {
        format!("{{\"full_replays\":{},\"replay_periods\":{},\"decoded_changes\":{},\"all_off\":{},\"all_on\":{},\"requests\":{},\"identical\":{},\"rebuilds\":{},\"deltas\":{},\"words_compared\":{},\"flips\":{},\"activations\":{},\"deactivations\":{},\"interval_joins\":{},\"interval_splits\":{},\"dirty_leaves\":{},\"tree_merges\":{},\"scenario_leaf_updates\":{},\"scenario_tree_merges\":{},\"flip_histogram\":[{}]}}",self.full_replays,self.replay_periods,self.decoded_changes,self.all_off,self.all_on,self.requests,self.identical,self.rebuilds,self.deltas,self.words_compared,self.flips,self.activations,self.deactivations,self.joins,self.splits,self.dirty_leaves,self.tree_merges,self.scenario_leaf_updates,self.scenario_tree_merges,self.flip_histogram.iter().map(u64::to_string).collect::<Vec<_>>().join(","))
    }
}
/// Ordered segment summary. head/tail/net_runs are *returns* of active runs.
/// Joining two touching runs adds a.tail*b.head to the sum of their net returns:
/// (1+a)(1+b)-1 = a+b+ab. This avoids transcendental work and permits deactivation.
#[derive(Clone, Copy, Default, Debug)]
struct Node {
    total: f64,
    high: f64,
    low: f64,
    drawdown: f64,
    gross: f64,
    sum: f64,
    squares: f64,
    net_runs: f64,
    head: f64,
    tail: f64,
    active: usize,
    entries: usize,
    len: usize,
    left: bool,
    right: bool,
}
impl Node {
    fn flat() -> Self {
        Self {
            len: 1,
            ..Self::default()
        }
    }
    fn leaf(m: &Market, t: usize, words: &[u64]) -> Self {
        if !bit(words, t) {
            return Self::flat();
        }
        let entry = t == 0 || !bit(words, t - 1);
        let exit = t + 1 == m.len || !bit(words, t + 1);
        let c = m.terms[t][entry as usize + 2 * exit as usize];
        Self {
            total: c[0],
            high: c[0].max(0.0),
            low: c[0].min(0.0),
            drawdown: (-c[0]).max(0.0),
            gross: m.terms[t][0][0],
            sum: c[1],
            squares: c[2],
            net_runs: c[1],
            head: c[1],
            tail: c[1],
            active: 1,
            entries: entry as usize,
            len: 1,
            left: true,
            right: true,
        }
    }
    fn merge(a: Self, b: Self) -> Self {
        if a.len == 0 {
            return b;
        }
        if b.len == 0 {
            return a;
        }
        let touch = a.right && b.left;
        let head = if a.active == a.len && b.left {
            a.head + b.head + a.head * b.head
        } else {
            a.head
        };
        let tail = if b.active == b.len && a.right {
            a.tail + b.tail + a.tail * b.tail
        } else {
            b.tail
        };
        Self {
            total: a.total + b.total,
            high: a.high.max(a.total + b.high),
            low: a.low.min(a.total + b.low),
            drawdown: a.drawdown.max(b.drawdown).max(a.high - a.total - b.low),
            gross: a.gross + b.gross,
            sum: a.sum + b.sum,
            squares: a.squares + b.squares,
            net_runs: a.net_runs + b.net_runs + if touch { a.tail * b.head } else { 0.0 },
            head,
            tail,
            active: a.active + b.active,
            entries: a.entries + b.entries,
            len: a.len + b.len,
            left: a.left,
            right: b.right,
        }
    }
    fn metrics(self, interval: i64) -> Result<Metrics> {
        if [
            self.total,
            self.high,
            self.low,
            self.drawdown,
            self.gross,
            self.sum,
            self.squares,
            self.net_runs,
            self.head,
            self.tail,
        ]
        .iter()
        .any(|v| !v.is_finite())
        {
            return Err("nonfinite execution summary; no result emitted".into());
        }
        let lite = Lite {
            periods: self.len,
            entries: self.entries,
            active: self.active,
            log_return: self.total,
            sum: self.sum,
            sum_sq: self.squares,
        };
        let m = Metrics {
            lite,
            gross_return_pct: self.gross.exp_m1() * 100.0,
            max_drawdown_pct: -(-self.drawdown).exp_m1() * 100.0,
            cagr_pct: (self.total * 31557600.0 / (self.len as f64 * interval as f64)).exp_m1()
                * 100.0,
            mean_trade_bps: if self.entries > 0 {
                self.net_runs / self.entries as f64 * 10000.0
            } else {
                f64::NAN
            },
        };
        if !m.lite.return_pct().is_finite()
            || !m.gross_return_pct.is_finite()
            || !m.cagr_pct.is_finite()
        {
            return Err("overflow in requested execution metric".into());
        }
        Ok(m)
    }
}
fn bit(w: &[u64], i: usize) -> bool {
    w[i / 64] >> (i % 64) & 1 != 0
}
/// Bound to one data/timeline/price/cost context for its lifetime. The API accepts
/// exact positions only; new data or costs require constructing a new context.
pub struct ReusableExecution {
    markets: Vec<Market>,
    trees: Vec<Vec<Node>>,
    words: Vec<u64>,
    base: usize,
    len: usize,
    changed: Vec<usize>,
    leaves: Vec<usize>,
    parents: Vec<usize>,
    level: Vec<usize>,
    next_level: Vec<usize>,
    initialized: bool,
    tree_valid: bool,
    cached: Option<Vec<Metrics>>,
    pub work: ChangeWork,
    pub payload_bytes: usize,
}
impl ReusableExecution {
    pub fn new(d: &Data, start: usize, end: usize, costs: &[Costs], budget: usize) -> Result<Self> {
        if costs.is_empty() || costs.len() > 64 || end > d.len() || start >= end || end - start < 4
        {
            return Err("invalid reusable execution context".into());
        }
        let len = end - start - 2;
        let base = len
            .checked_next_power_of_two()
            .ok_or("tree size overflow")?;
        // Include precomputed market terms, five index buffers and packed state.
        let payload = base
            .checked_mul(2)
            .and_then(|v| v.checked_mul(std::mem::size_of::<Node>()))
            .and_then(|v| v.checked_mul(costs.len()))
            .and_then(|v| {
                v.checked_add(
                    len.checked_mul(costs.len() * 120 + 7 * std::mem::size_of::<usize>())?,
                )
            })
            .ok_or("execution payload overflow")?;
        if payload > budget {
            return Err(format!(
                "execution state requires {payload} bytes, exceeds budget {budget}"
            ));
        }
        let markets = costs
            .iter()
            .map(|&c| Market::new(d, start, end, c))
            .collect::<Result<Vec<_>>>()?;
        let trees = costs
            .iter()
            .map(|_| vec![Node::default(); base * 2])
            .collect();
        Ok(Self {
            markets,
            trees,
            words: vec![0; (len + 63) / 64],
            base,
            len,
            changed: Vec::with_capacity(len),
            leaves: Vec::with_capacity(len),
            parents: Vec::with_capacity(base),
            level: Vec::with_capacity(len),
            next_level: Vec::with_capacity(len),
            initialized: false,
            tree_valid: false,
            cached: None,
            work: ChangeWork::default(),
            payload_bytes: payload,
        })
    }
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn reference_markets(&self) -> &[Market] {
        &self.markets
    }
    pub fn scenarios(&self) -> usize {
        self.markets.len()
    }
    pub fn score(&mut self, target: &[u64], mode: TransitionMode) -> Result<Vec<Metrics>> {
        if target.len() != self.words.len()
            || (self.len % 64 != 0 && target.last().unwrap() >> (self.len % 64) != 0)
        {
            return Err("packed position length/padding mismatch".into());
        }
        let (mut flips, mut on, mut off, mut active_count) = (0usize, 0u64, 0u64, 0usize);
        for (&old, &new) in self.words.iter().zip(target) {
            flips += (old ^ new).count_ones() as usize;
            on += (!old & new).count_ones() as u64;
            off += (old & !new).count_ones() as u64;
            active_count += new.count_ones() as usize;
        }
        self.work.requests += 1;
        self.work.words_compared += target.len() as u64;
        self.work.flips += flips as u64;
        self.work.activations += on;
        self.work.deactivations += off;
        self.work.all_off += (active_count == 0) as u64;
        self.work.all_on += (active_count == self.len) as u64;
        let fraction = flips as f64 / self.len as f64;
        let h = if flips == 0 {
            0
        } else if fraction <= 0.001 {
            1
        } else if fraction <= 0.01 {
            2
        } else if fraction <= 0.05 {
            3
        } else if fraction <= 0.1 {
            4
        } else if fraction <= 0.25 {
            5
        } else if fraction <= 0.5 {
            6
        } else {
            7
        };
        self.work.flip_histogram[h] += 1;
        if self.initialized && flips == 0 && mode != TransitionMode::Rebuild {
            self.work.identical += 1;
            return Ok(self.cached.as_ref().expect("initialized cache").clone());
        }
        // Dense targets do not decode each changed bit or maintain tree summaries
        // we cannot cheaply reuse. Re-enter the tree path when locality returns.
        if mode == TransitionMode::Auto && flips > self.len / 8 {
            self.words.copy_from_slice(target);
            return self.full_replay();
        }
        self.changed.clear();
        for (j, (&old, &new)) in self.words.iter().zip(target).enumerate() {
            let mut diff = old ^ new;
            while diff != 0 {
                self.changed.push(j * 64 + diff.trailing_zeros() as usize);
                diff &= diff - 1;
            }
        }
        self.work.decoded_changes += self.changed.len() as u64;
        // Only sparse transitions perform incremental interval operations.
        for &t in &self.changed {
            let left = t > 0 && bit(&self.words, t - 1);
            let right = t + 1 < self.len && bit(&self.words, t + 1);
            if bit(target, t) {
                self.work.joins += (left && right) as u64;
            } else {
                self.work.splits += (left && right) as u64;
            }
            self.words[t / 64] ^= 1 << (t % 64);
        }
        self.leaves.clear();
        self.parents.clear();
        for &t in &self.changed {
            for j in t.saturating_sub(1)..(t + 2).min(self.len) {
                if self.leaves.last().map_or(true, |&last| j > last) {
                    self.leaves.push(j);
                }
            }
        }
        let mut rebuild = !self.tree_valid || mode == TransitionMode::Rebuild;
        // Avoid constructing a large dirty plan when already more costly than rebuilding.
        if mode == TransitionMode::Auto && self.leaves.len() * 3 >= self.len {
            rebuild = true;
        }
        if !rebuild {
            self.level.clear();
            for &j in &self.leaves {
                let p = (self.base + j) / 2;
                if self.level.last() != Some(&p) {
                    self.level.push(p);
                }
            }
            while !self.level.is_empty() {
                self.parents.extend_from_slice(&self.level);
                self.next_level.clear();
                for &j in &self.level {
                    if j > 1 {
                        let p = j / 2;
                        if self.next_level.last() != Some(&p) {
                            self.next_level.push(p);
                        }
                    }
                }
                std::mem::swap(&mut self.level, &mut self.next_level);
            }
            if mode == TransitionMode::Auto
                && self.parents.len() + self.leaves.len() >= self.base + self.len
            {
                rebuild = true;
            }
        }
        if rebuild {
            self.work.rebuilds += 1;
            self.work.dirty_leaves += self.len as u64;
            self.work.tree_merges += (self.base - 1) as u64;
            for (tree, m) in self.trees.iter_mut().zip(&self.markets) {
                for t in 0..self.len {
                    tree[self.base + t] = Node::leaf(m, t, &self.words);
                }
                for i in (1..self.base).rev() {
                    tree[i] = Node::merge(tree[i * 2], tree[i * 2 + 1]);
                }
            }
            self.work.scenario_leaf_updates += (self.len * self.markets.len()) as u64;
            self.work.scenario_tree_merges += ((self.base - 1) * self.markets.len()) as u64;
        } else {
            self.work.deltas += 1;
            self.work.dirty_leaves += self.leaves.len() as u64;
            self.work.tree_merges += self.parents.len() as u64;
            for (tree, m) in self.trees.iter_mut().zip(&self.markets) {
                for &t in &self.leaves {
                    tree[self.base + t] = Node::leaf(m, t, &self.words);
                }
                for &i in &self.parents {
                    tree[i] = Node::merge(tree[i * 2], tree[i * 2 + 1]);
                }
            }
            self.work.scenario_leaf_updates += (self.leaves.len() * self.markets.len()) as u64;
            self.work.scenario_tree_merges += (self.parents.len() * self.markets.len()) as u64;
        }
        self.initialized = true;
        self.tree_valid = true;
        let metrics = self.metrics()?;
        self.cached = Some(metrics.clone());
        Ok(metrics)
    }
    fn full_replay(&mut self) -> Result<Vec<Metrics>> {
        let mut states = vec![
            Node {
                len: self.len,
                ..Node::default()
            };
            self.markets.len()
        ];
        let mut trade = vec![0.0f64; self.markets.len()];
        let mut gross = 0.0;
        for t in 0..self.len {
            if !bit(&self.words, t) {
                continue;
            }
            let entry = t == 0 || !bit(&self.words, t - 1);
            let exit = t + 1 == self.len || !bit(&self.words, t + 1);
            let cat = entry as usize + 2 * exit as usize;
            gross += self.markets[0].terms[t][0][0];
            for ((node, m), run) in states.iter_mut().zip(&self.markets).zip(&mut trade) {
                let c = m.terms[t][cat];
                node.active += 1;
                node.entries += entry as usize;
                node.total += c[0];
                node.sum += c[1];
                node.squares += c[2];
                node.high = node.high.max(node.total);
                node.drawdown = node.drawdown.max(node.high - node.total);
                *run += c[0];
                if exit {
                    node.net_runs += run.exp_m1();
                    *run = 0.0;
                }
            }
        }
        for node in &mut states {
            node.gross = gross;
        }
        let metrics = states
            .into_iter()
            .map(|n| n.metrics(self.markets[0].interval))
            .collect::<Result<Vec<_>>>()?;
        self.work.full_replays += 1;
        self.work.replay_periods += self.len as u64;
        self.initialized = true;
        self.tree_valid = false;
        self.cached = Some(metrics.clone());
        Ok(metrics)
    }
    fn metrics(&self) -> Result<Vec<Metrics>> {
        self.trees
            .iter()
            .map(|t| t[1].metrics(self.markets[0].interval))
            .collect()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn data(n: usize) -> Data {
        Data {
            timestamps: (0..n).map(|i| i as i64 * 14400).collect(),
            columns: std::array::from_fn(|_| {
                (0..n)
                    .map(|i| 100.0 * (0.09 * (i as f64 / 7.0).sin() + 0.0003 * i as f64).exp())
                    .collect()
            }),
            interval: 14400,
            digest: "state-fixture".into(),
        }
    }
    fn cmp(a: &Metrics, b: &Metrics) {
        assert_eq!(
            (a.lite.active, a.lite.entries, a.lite.periods),
            (b.lite.active, b.lite.entries, b.lite.periods)
        );
        for (x, y) in [
            a.lite.log_return,
            a.lite.sum,
            a.lite.sum_sq,
            a.gross_return_pct,
            a.max_drawdown_pct,
            a.cagr_pct,
            a.mean_trade_bps,
        ]
        .into_iter()
        .zip([
            b.lite.log_return,
            b.lite.sum,
            b.lite.sum_sq,
            b.gross_return_pct,
            b.max_drawdown_pct,
            b.cagr_pct,
            b.mean_trade_bps,
        ]) {
            assert!(
                x.is_nan() && y.is_nan() || (x - y).abs() <= 1e-7 + 1e-9 * y.abs(),
                "{x} != {y}"
            );
        }
    }
    #[test]
    fn arbitrary_flips_splits_joins_scenarios_and_tails() {
        for n in [7, 66, 129, 300] {
            let d = data(n);
            let costs = [
                Costs {
                    fee_bps: 0.,
                    slip_bps: 0.,
                },
                Costs {
                    fee_bps: 5.,
                    slip_bps: 5.,
                },
                Costs {
                    fee_bps: 10.,
                    slip_bps: 10.,
                },
            ];
            let ms = costs
                .iter()
                .map(|&c| Market::new(&d, 0, n, c).unwrap())
                .collect::<Vec<_>>();
            let mut state = ReusableExecution::new(&d, 0, n, &costs, 32 * 1024 * 1024).unwrap();
            let mut words = vec![0; (n - 2 + 63) / 64];
            let mut rng = 3u64;
            for k in 0..300 {
                rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1);
                for j in 0..if k % 23 == 0 { n - 2 } else { 1 } {
                    let t = (rng as usize + j * 31) % (n - 2);
                    words[t / 64] ^= 1 << (t % 64);
                }
                let got = state
                    .score(
                        &words,
                        if k % 3 == 0 {
                            TransitionMode::Delta
                        } else {
                            TransitionMode::Auto
                        },
                    )
                    .unwrap();
                let p = (0..n - 2).map(|t| bit(&words, t)).collect::<Vec<_>>();
                for (i, m) in ms.iter().enumerate() {
                    let direct =
                        super::super::metrics_from_ledger(&m.position_ledger(&p).unwrap(), 14400)
                            .unwrap();
                    cmp(&got[i], &direct);
                }
                if k % 7 == 0 {
                    let again = state.score(&words, TransitionMode::Delta).unwrap();
                    cmp(&got[0], &again[0]);
                }
            }
            assert!(
                state.work.splits > 0
                    && state.work.joins > 0
                    && state.work.rebuilds > 0
                    && state.work.identical > 0
            );
        }
    }
    #[test]
    fn node_join_and_split_identity() {
        let d = data(20);
        let costs = [Costs {
            fee_bps: 5.,
            slip_bps: 5.,
        }];
        let mut state = ReusableExecution::new(&d, 0, 20, &costs, 1024 * 1024).unwrap();
        for bits in [0, 0b111111, 0b110111, 0b111111, 1, 0, 0b111111] {
            let words = [bits];
            let a = state.score(&words, TransitionMode::Delta).unwrap();
            let b = state.score(&words, TransitionMode::Rebuild).unwrap();
            cmp(&a[0], &b[0]);
        }
        assert!(state.score(&[u64::MAX], TransitionMode::Auto).is_err());
        assert!(ReusableExecution::new(&d, 0, 20, &costs, 1).is_err());
    }
}
