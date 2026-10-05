//! Exact joint parameter boxes over predicate alternatives. No individual-score
//! preselection, indicator dispatch, or per-logical-address allocation.
use crate::{
    backtest::{Market, Metrics},
    data::Data,
    kernels::Backend,
    paged::Executor,
    rule_kernels,
    rules::{Cell, Mask, Program},
    Result,
};
use std::{
    collections::{BTreeMap, HashMap},
    sync::Arc,
};
#[derive(Clone, Debug)]
pub struct Alternative {
    pub id: usize,
    pub tag: String,
    pub count: u64,
    pub cells: Arc<Vec<Cell>>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Plan {
    Expanded,
    Cells,
    Cofactor,
}
impl Plan {
    pub fn parse(s: &str) -> Result<Self> {
        match s {
            "expanded" => Ok(Self::Expanded),
            "cells" => Ok(Self::Cells),
            "cofactor" => Ok(Self::Cofactor),
            _ => Err("plan expanded/cells/cofactor".into()),
        }
    }
}
#[derive(Clone, Debug)]
pub struct BoxResult {
    pub template: usize,
    pub choices: Vec<usize>,
    pub ranges: Vec<(u64, u64)>,
    pub metrics: Vec<Metrics>,
}
impl BoxResult {
    pub fn width(&self) -> Result<u64> {
        self.ranges.iter().try_fold(1u64, |a, (lo, hi)| {
            a.checked_mul(hi - lo)
                .ok_or_else(|| "box volume overflow".into())
        })
    }
}
#[derive(Default, Clone, Debug)]
pub struct Work {
    pub tuples: u64,
    pub cartesian_cells: u64,
    pub rule_evaluations: u64,
    pub cofactor_builds: u64,
    pub mux_words: u64,
    pub boxes: u64,
    pub logical: u64,
    pub state_calls: u64,
    pub replay_calls: u64,
    pub cache_hits: u64,
    pub cache_checks: u64,
    pub cache_peak: usize,
    pub coalesced_cells: u64,
    pub constant_cofactors: u64,
    pub flat_boxes: u64,
    pub full_boxes: u64,
}
impl Work {
    pub fn json(&self) -> String {
        format!("{{\"alternative_tuples\":{},\"cartesian_cells_visited\":{},\"rule_graph_evaluations\":{},\"cofactor_builds\":{},\"mux_words\":{},\"result_boxes\":{},\"logical_addresses_resolved\":{},\"state_calls\":{},\"chronological_replays\":{},\"exact_cache_hits\":{},\"exact_cache_comparisons\":{},\"cache_peak_entries\":{},\"coalesced_last_axis_cells\":{},\"constant_cofactor_regions\":{},\"all_flat_boxes\":{},\"all_invested_boxes\":{}}}",self.tuples,self.cartesian_cells,self.rule_evaluations,self.cofactor_builds,self.mux_words,self.boxes,self.logical,self.state_calls,self.replay_calls,self.cache_hits,self.cache_checks,self.cache_peak,self.coalesced_cells,self.constant_cofactors,self.flat_boxes,self.full_boxes)
    }
}
struct Entry {
    key: u64,
    words: Vec<u64>,
    metrics: Vec<Metrics>,
}
struct Cache {
    entries: Vec<Entry>,
    index: HashMap<u64, Vec<usize>>,
    next: usize,
    cap: usize,
}
fn mask_key(words: &[u64]) -> u64 {
    words.iter().fold(0xcbf29ce484222325, |h, w| {
        (h ^ w).wrapping_mul(0x100000001b3)
    })
}
impl Cache {
    fn new(bytes: usize, words: usize, scenarios: usize) -> Self {
        let charge = words * 8 + scenarios * std::mem::size_of::<Metrics>() + 256;
        Self {
            entries: Vec::new(),
            index: HashMap::new(),
            next: 0,
            cap: (bytes / charge).min(100000),
        }
    }
    fn get(&self, key: u64, words: &[u64], checks: &mut u64) -> Option<Vec<Metrics>> {
        self.index.get(&key).and_then(|ids| {
            ids.iter().find_map(|&i| {
                *checks += 1;
                if self.entries[i].words == words {
                    Some(self.entries[i].metrics.clone())
                } else {
                    None
                }
            })
        })
    }
    fn put(&mut self, key: u64, words: &[u64], metrics: &[Metrics]) {
        if self.cap == 0 {
            return;
        }
        let e = Entry {
            key,
            words: words.to_vec(),
            metrics: metrics.to_vec(),
        };
        let id = if self.entries.len() < self.cap {
            let i = self.entries.len();
            self.entries.push(e);
            i
        } else {
            let i = self.next;
            let old = self.entries[i].key;
            if let Some(v) = self.index.get_mut(&old) {
                v.retain(|&j| j != i);
                if v.is_empty() {
                    self.index.remove(&old);
                }
            }
            self.entries[i] = e;
            self.next = (i + 1) % self.cap;
            i
        };
        self.index.entry(key).or_default().push(id);
    }
}
/// Count valid Cartesian addresses by inclusion-exclusion over slot partitions.
/// This does not enumerate alternatives' Cartesian product or threshold values.
pub fn domain_count(
    slots: &[Vec<Alternative>],
    different_tags: bool,
    weighted: bool,
) -> Result<u64> {
    if slots.is_empty() || slots.len() > 8 || slots.iter().any(Vec::is_empty) {
        return Err("nonempty 1..8 slot domain required".into());
    }
    let mut groups: BTreeMap<&str, Vec<i128>> = BTreeMap::new();
    for (s, opts) in slots.iter().enumerate() {
        for o in opts {
            let v = groups.entry(&o.tag).or_insert_with(|| vec![0; slots.len()]);
            v[s] = v[s]
                .checked_add(if weighted { o.count as i128 } else { 1 })
                .ok_or("domain overflow")?;
        }
    }
    if !different_tags {
        let n = (0..slots.len()).try_fold(1i128, |a, s| {
            a.checked_mul(groups.values().map(|v| v[s]).sum())
                .ok_or("domain overflow")
        })?;
        return u64::try_from(n).map_err(|_| "domain exceeds u64".into());
    }
    let size = 1usize << slots.len();
    let mut common = vec![0i128; size];
    for (mask, item) in common.iter_mut().enumerate().skip(1) {
        for vals in groups.values() {
            let mut p = 1i128;
            for (s, &v) in vals.iter().enumerate() {
                if mask >> s & 1 != 0 {
                    p = p.checked_mul(v).ok_or("domain overflow")?;
                }
            }
            *item = item.checked_add(p).ok_or("domain overflow")?;
        }
    }
    let mut dp = vec![0i128; size];
    dp[0] = 1;
    for mask in 1..size {
        let first = mask & mask.wrapping_neg();
        let mut sub = mask;
        loop {
            if sub & first != 0 {
                let n = sub.count_ones() as usize;
                let mut coefficient = 1i128;
                for k in 1..n {
                    coefficient *= k as i128;
                }
                if n % 2 == 0 {
                    coefficient = -coefficient;
                }
                let term = coefficient
                    .checked_mul(common[sub])
                    .and_then(|v| v.checked_mul(dp[mask ^ sub]))
                    .ok_or("domain overflow")?;
                dp[mask] = dp[mask].checked_add(term).ok_or("domain overflow")?;
            }
            if sub == 0 {
                break;
            }
            sub = (sub - 1) & mask;
        }
    }
    u64::try_from(dp[size - 1]).map_err(|_| "domain exceeds u64".into())
}
pub struct Sweep<'a, 'd> {
    pub executor: &'a mut Executor<'d>,
    pub backend: Backend,
    pub plan: Plan,
    pub different_tags: bool,
    pub work: Work,
    cache: Cache,
    markets: Vec<Market>,
    start: usize,
    end: usize,
    full_timeline: bool,
    max_boxes: u64,
    interval: i64,
}
impl<'a, 'd> Sweep<'a, 'd> {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        executor: &'a mut Executor<'d>,
        d: &Data,
        range: std::ops::Range<usize>,
        costs: &[crate::backtest::Costs],
        backend: Backend,
        plan: Plan,
        different_tags: bool,
        cache_bytes: usize,
        full_timeline: bool,
        max_boxes: u64,
    ) -> Result<Self> {
        let len = range
            .end
            .checked_sub(range.start + 2)
            .ok_or("joint interval too short")?;
        let markets = costs
            .iter()
            .map(|&c| Market::new(d, range.start, range.end, c))
            .collect::<Result<_>>()?;
        Ok(Self {
            executor,
            backend,
            plan,
            different_tags,
            work: Work::default(),
            cache: Cache::new(cache_bytes, (len + 63) / 64, costs.len()),
            markets,
            start: range.start,
            end: range.end - 2,
            full_timeline,
            max_boxes,
            interval: d.interval,
        })
    }
    pub fn run<F>(
        &mut self,
        slots: &[Vec<Alternative>],
        programs: &[Program],
        mut emit: F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        let expected = domain_count(slots, self.different_tags, true)?
            .checked_mul(programs.len() as u64)
            .ok_or("domain overflow")?;
        if self.plan == Plan::Expanded && expected > 1_000_000 {
            return Err("expanded reference cap 1000000 addresses; use cells/cofactor".into());
        }
        for p in programs {
            if p.slots != slots.len() || p.used_slots().len() != slots.len() {
                return Err("every template must consume every declared slot".into());
            }
        }
        for (i, p) in programs.iter().enumerate() {
            self.choices(slots, p, i, &mut Vec::new(), &mut emit)?;
        }
        if self.work.logical != expected {
            return Err(format!(
                "coverage mismatch {} != {expected}",
                self.work.logical
            ));
        }
        Ok(())
    }
    fn choices<F>(
        &mut self,
        slots: &[Vec<Alternative>],
        program: &Program,
        template: usize,
        choices: &mut Vec<Alternative>,
        emit: &mut F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        if choices.len() == slots.len() {
            self.work.tuples += 1;
            if self.plan == Plan::Expanded {
                return self.expanded_prefix(
                    program,
                    template,
                    choices,
                    &mut Vec::new(),
                    &mut Vec::new(),
                    emit,
                );
            }
            return self.cell_product(program, template, choices, &mut Vec::new(), emit);
        }
        for alt in &slots[choices.len()] {
            if self.different_tags && choices.iter().any(|a| a.tag == alt.tag) {
                continue;
            }
            choices.push(alt.clone());
            self.choices(slots, program, template, choices, emit)?;
            choices.pop();
        }
        Ok(())
    }
    fn cell_product<F>(
        &mut self,
        p: &Program,
        template: usize,
        choices: &[Alternative],
        cells: &mut Vec<usize>,
        emit: &mut F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        if cells.len() + 1 == choices.len() {
            return self.last_axis(p, template, choices, cells, emit);
        }
        let axis = cells.len();
        for i in 0..choices[axis].cells.len() {
            cells.push(i);
            self.cell_product(p, template, choices, cells, emit)?;
            cells.pop();
        }

        Ok(())
    }
    fn expanded_prefix<F>(
        &mut self,
        p: &Program,
        template: usize,
        choices: &[Alternative],
        cells: &mut Vec<usize>,
        points: &mut Vec<(usize, u64)>,
        emit: &mut F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        if cells.len() == choices.len() {
            let inputs = cells
                .iter()
                .enumerate()
                .map(|(s, &c)| &choices[s].cells[c].mask)
                .collect::<Vec<_>>();
            let m = p.evaluate(&inputs, Backend::Scalar)?;
            self.work.rule_evaluations += 1;
            self.work.cartesian_cells += 1;
            let ranges = points.iter().map(|(_, q)| (*q, *q + 1)).collect::<Vec<_>>();
            return self.output(template, choices, ranges, &self.positions(&m)?, emit);
        }
        let axis = cells.len();
        for (i, cell) in choices[axis].cells.iter().enumerate() {
            for q in cell.lo..cell.hi {
                cells.push(i);
                points.push((axis, q));
                self.expanded_prefix(p, template, choices, cells, points, emit)?;
                points.pop();
                cells.pop();
            }
        }
        Ok(())
    }
    fn positions(&self, m: &Mask) -> Result<Vec<u64>> {
        if self.full_timeline {
            Ok(m.slice(self.start, self.end)?.bits)
        } else {
            Ok(m.bits.clone())
        }
    }
    fn last_axis<F>(
        &mut self,
        p: &Program,
        template: usize,
        choices: &[Alternative],
        prefix: &[usize],
        emit: &mut F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        let last = choices.len() - 1;
        let mut inputs = prefix
            .iter()
            .enumerate()
            .map(|(s, &i)| &choices[s].cells[i].mask)
            .collect::<Vec<_>>();
        inputs.push(&choices[last].cells[0].mask);
        let cofactor = if self.plan == Plan::Cofactor && p.pointwise() {
            self.work.cofactor_builds += 1;
            self.work.rule_evaluations += 2;
            Some(p.cofactors(&inputs, last, self.backend)?)
        } else {
            None
        };
        let ranges = prefix
            .iter()
            .enumerate()
            .map(|(s, &i)| {
                let c = &choices[s].cells[i];
                (c.lo, c.hi)
            })
            .collect::<Vec<_>>();
        if let Some((a, b)) = &cofactor {
            if a.bits == b.bits {
                self.work.constant_cofactors += 1;
                let mut r = ranges;
                r.push((0, choices[last].count));
                return self.output(template, choices, r, &self.positions(a)?, emit);
            }
        }
        let mut pending: Option<(u64, u64, Vec<u64>)> = None;
        for cell in choices[last].cells.iter() {
            self.work.cartesian_cells += 1;
            let words = if let Some((a, b)) = &cofactor {
                if cell.mask.valid != inputs[last].valid {
                    return Err("threshold-dependent validity needs non-cofactor plan".into());
                }
                let mut bits = vec![0; a.bits.len()];
                rule_kernels::select(&a.bits, &b.bits, &cell.mask.bits, &mut bits, self.backend)?;
                self.work.mux_words += bits.len() as u64;
                if self.full_timeline {
                    self.positions(&Mask {
                        bits,
                        valid: a.valid.clone(),
                        len: a.len,
                    })?
                } else {
                    bits
                }
            } else {
                inputs[last] = &cell.mask;
                self.work.rule_evaluations += 1;
                self.positions(&p.evaluate(&inputs, self.backend)?)?
            };
            if let Some((_, hi, old)) = pending.as_mut() {
                if *old == words {
                    *hi = cell.hi;
                    self.work.coalesced_cells += 1;
                    continue;
                }
            }
            if let Some((lo, hi, old)) = pending.take() {
                let mut r = ranges.clone();
                r.push((lo, hi));
                self.output(template, choices, r, &old, emit)?;
            }
            pending = Some((cell.lo, cell.hi, words));
        }
        if let Some((lo, hi, words)) = pending {
            let mut r = ranges;
            r.push((lo, hi));
            self.output(template, choices, r, &words, emit)?;
        }
        Ok(())
    }
    fn output<F>(
        &mut self,
        template: usize,
        choices: &[Alternative],
        ranges: Vec<(u64, u64)>,
        words: &[u64],
        emit: &mut F,
    ) -> Result<()>
    where
        F: FnMut(&BoxResult) -> Result<()>,
    {
        if self.work.boxes >= self.max_boxes {
            return Err("physical result box budget reached; campaign incomplete".into());
        }
        let key = mask_key(words);
        let metrics = if self.plan == Plan::Expanded {
            let pos = (0..self.end - self.start)
                .map(|i| words[i / 64] >> (i % 64) & 1 != 0)
                .collect::<Vec<_>>();
            self.work.replay_calls += self.markets.len() as u64;
            self.markets
                .iter()
                .map(|m| {
                    crate::backtest::metrics_from_ledger(&m.position_ledger(&pos)?, self.interval)
                })
                .collect::<Result<Vec<_>>>()?
        } else if let Some(ms) = self.cache.get(key, words, &mut self.work.cache_checks) {
            self.work.cache_hits += 1;
            ms
        } else {
            self.work.state_calls += 1;
            let ms = self.executor.score_positions(words)?;
            self.cache.put(key, words, &ms);
            ms
        };
        self.work.cache_peak = self.work.cache_peak.max(self.cache.entries.len());
        let active = words.iter().map(|w| w.count_ones() as usize).sum::<usize>();
        self.work.flat_boxes += (active == 0) as u64;
        self.work.full_boxes += (active == self.end - self.start) as u64;
        let result = BoxResult {
            template,
            choices: choices.iter().map(|a| a.id).collect(),
            ranges,
            metrics,
        };
        self.work.logical = self
            .work
            .logical
            .checked_add(result.width()?)
            .ok_or("coverage overflow")?;
        self.work.boxes += 1;
        emit(&result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn behavior_hash_is_only_an_index_and_fifo_is_bounded() {
        let mut cache = Cache::new(600, 1, 0);
        let mut checks = 0;
        cache.put(7, &[1], &[]);
        assert!(cache.get(7, &[2], &mut checks).is_none());
        cache.put(7, &[2], &[]);
        assert!(cache.get(7, &[1], &mut checks).is_some());
        cache.put(8, &[3], &[]);
        assert!(cache.get(7, &[1], &mut checks).is_none());
        assert!(cache.get(7, &[2], &mut checks).is_some());
        assert!(cache.entries.len() <= cache.cap);
    }
}
