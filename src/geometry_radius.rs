//! Radius over observed orderings, including orientation and signed axes.
use super::{
    Counts, GeometryKey, GeometryMode, GeometryPattern, Keys, Posting, PreparedGeometry, Reading,
    WideKey,
};
use crate::{geometry::BodyDirection, Result};
use std::collections::BTreeMap;

const OUTSIDE: u32 = u32::MAX;

pub struct RadiusCounts {
    pub counts: Counts,
    /// Matching window counts by their exact distance from the submitted key.
    pub by_distance: BTreeMap<u32, usize>,
}

struct Membership {
    distance: Vec<u32>,
    valid: Vec<u64>,
}

impl Membership {
    fn matches(&self, slot: usize) -> bool {
        self.distance[slot] != OUTSIDE && self.valid[slot / 64] & (1 << (slot % 64)) != 0
    }

    fn counts(&self, matched: usize) -> Counts {
        let valid: usize = self
            .valid
            .iter()
            .map(|word| word.count_ones() as usize)
            .sum();
        Counts {
            matched,
            false_count: valid - matched,
            unknown: self.distance.len() - valid,
        }
    }

    fn stats(&self) -> RadiusCounts {
        let mut by_distance = BTreeMap::new();
        for (slot, &distance) in self.distance.iter().enumerate() {
            if self.matches(slot) {
                *by_distance.entry(distance).or_insert(0) += 1;
            }
        }
        RadiusCounts {
            counts: self.counts(by_distance.values().sum()),
            by_distance,
        }
    }
}

impl PreparedGeometry {
    /// Expand a pattern over the keys observed in this recording and reading.
    pub fn neighbourhood(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
    ) -> Result<RadiusCounts> {
        if radius == 0 {
            let counts = self.counts(pattern, reading)?;
            let mut by_distance = BTreeMap::new();
            if counts.matched > 0 {
                by_distance.insert(0, counts.matched);
            }
            return Ok(RadiusCounts {
                counts,
                by_distance,
            });
        }
        Ok(self.membership(pattern, reading, radius)?.stats())
    }

    pub fn counts_within(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
    ) -> Result<Counts> {
        if radius == 0 {
            return self.counts(pattern, reading);
        }
        let state = self.membership(pattern, reading, radius)?;
        let matched = (0..state.distance.len())
            .filter(|&slot| state.matches(slot))
            .count();
        Ok(state.counts(matched))
    }

    pub fn positions_within(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
        start: usize,
        limit: usize,
    ) -> Result<Vec<u32>> {
        if radius == 0 {
            return self.positions(pattern, reading, start, limit);
        }
        let result = self.membership(pattern, reading, radius)?;
        Ok((start..result.distance.len())
            .filter(|&slot| result.matches(slot))
            .take(limit)
            .map(|slot| slot as u32)
            .collect())
    }

    pub fn classify_within(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
        start: usize,
        limit: usize,
    ) -> Result<Vec<Option<bool>>> {
        if radius == 0 {
            return self.classify(pattern, reading, start, limit);
        }
        let result = self.membership(pattern, reading, radius)?;
        let end = result.distance.len().min(start.saturating_add(limit));
        Ok((start..end)
            .map(|slot| {
                (result.valid[slot / 64] & (1 << (slot % 64)) != 0)
                    .then_some(result.distance[slot] != OUTSIDE)
            })
            .collect())
    }

    pub(crate) fn radius_series(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
    ) -> Result<(String, RadiusCounts)> {
        let result = self.membership(pattern, reading, radius)?;
        let mut states = String::with_capacity(result.distance.len());
        for slot in 0..result.distance.len() {
            let symbol = if result.valid[slot / 64] & (1 << (slot % 64)) == 0 {
                '?'
            } else if result.distance[slot] == OUTSIDE {
                '0'
            } else {
                '1'
            };
            states.push(symbol);
        }
        Ok((states, result.stats()))
    }

    pub(crate) fn within_masks(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
    ) -> Result<(Vec<u64>, Vec<u64>)> {
        let state = self.membership(pattern, reading, radius)?;
        let mut bits = vec![0; state.valid.len()];
        for slot in 0..state.distance.len() {
            if state.matches(slot) {
                bits[slot / 64] |= 1 << (slot % 64);
            }
        }
        Ok((bits, state.valid))
    }

    fn membership(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        radius: u32,
    ) -> Result<Membership> {
        self.prepare_pattern(pattern, reading)?;
        let len = self.recording.len();
        let price = &self.prices[&(pattern.mode(), reading)];
        let mut distance = vec![OUTSIDE; len];
        let mut valid = price.validity().to_vec();
        let target: Vec<_> = pattern.ranks().iter().flatten().copied().collect();
        let mut ranks = vec![0; target.len()];
        match price {
            Keys::Compact(postings) => {
                for (&key, posting) in &postings.slots {
                    let cost = compact_price(pattern, &target, &mut ranks, key, radius);
                    if cost <= radius {
                        visit(posting, |slot| distance[slot] = cost);
                    }
                }
            }
            Keys::Wide(postings) => {
                for (key, posting) in &postings.slots {
                    let cost = wide_price(pattern, &target, &mut ranks, key, radius);
                    if cost <= radius {
                        visit(posting, |slot| distance[slot] = cost);
                    }
                }
            }
        }
        for part in pattern.dimensions() {
            let axis = self.axes[part.dimension() as usize]
                .as_ref()
                .expect("prepared axis");
            for (valid, axis) in valid.iter_mut().zip(axis.validity()) {
                *valid &= axis;
            }
            let target: Vec<_> = part
                .ranks()
                .iter()
                .copied()
                .chain(part.reference())
                .collect();
            let ranks = &mut ranks[..target.len()];
            let mut sum = |posting, cost| {
                // Every window belongs to at most one observed key on this axis.
                visit(posting, |slot| {
                    let next = distance[slot].saturating_add(cost);
                    distance[slot] = if next <= radius { next } else { OUTSIDE };
                });
            };
            match axis {
                Keys::Compact(postings) => {
                    for (&key, posting) in &postings.slots {
                        for (i, rank) in ranks.iter_mut().enumerate() {
                            let bit = if i == self.width { 40 } else { 4 * i };
                            *rank = ((key >> bit) & 15) as usize;
                        }
                        sum(posting, order_distance(&target, ranks, radius));
                    }
                }
                Keys::Wide(postings) => {
                    for (key, posting) in &postings.slots {
                        for (rank, &word) in ranks.iter_mut().zip(key.0.iter()) {
                            *rank = word as usize;
                        }
                        sum(posting, order_distance(&target, ranks, radius));
                    }
                }
            }
        }
        Ok(Membership { distance, valid })
    }
}

fn visit(posting: &Posting, mut apply: impl FnMut(usize)) {
    match posting {
        Posting::Offsets(offsets) => {
            for &slot in offsets {
                apply(slot as usize);
            }
        }
        Posting::Bitmap(bitmap) => {
            for (i, &word) in bitmap.words.iter().enumerate() {
                let mut word = word;
                while word != 0 {
                    let bit = word.trailing_zeros() as usize;
                    apply(i * 64 + bit);
                    word &= word - 1;
                }
            }
        }
    }
}

fn compact_price(
    pattern: &GeometryPattern,
    target: &[usize],
    ranks: &mut [usize],
    key: GeometryKey,
    bound: u32,
) -> u32 {
    price_cost(pattern, target, ranks, bound, |i| {
        let row = key.rank_row(i);
        (row, key.body_direction(i, &row))
    })
}

fn wide_price(
    pattern: &GeometryPattern,
    target: &[usize],
    ranks: &mut [usize],
    key: &WideKey,
    bound: u32,
) -> u32 {
    price_cost(pattern, target, ranks, bound, |i| {
        let ends = &key.0[i * 4..i * 4 + 4];
        let row = [
            (ends[0] & 0x7fff) as usize,
            ends[1] as usize,
            ends[2] as usize,
            ends[3] as usize,
        ];
        let direction = if row[1] == row[2] {
            BodyDirection::Flat
        } else if ends[0] & (1 << 15) != 0 {
            BodyDirection::Up
        } else {
            BodyDirection::Down
        };
        (row, direction)
    })
}

fn price_cost(
    pattern: &GeometryPattern,
    target: &[usize],
    ranks: &mut [usize],
    bound: u32,
    mut row_at: impl FnMut(usize) -> ([usize; 4], BodyDirection),
) -> u32 {
    let mut cost = 0;
    for (i, values) in ranks.chunks_exact_mut(4).enumerate() {
        let (row, direction) = row_at(i);
        values.copy_from_slice(&row);
        if let Some(directions) = pattern.directions() {
            cost += half_flips(colour(directions[i]), colour(direction));
            if cost > bound {
                return OUTSIDE;
            }
        }
    }
    cost.saturating_add(order_distance(target, ranks, bound - cost))
}

#[inline]
fn colour(direction: BodyDirection) -> i8 {
    match direction {
        BodyDirection::Down => -1,
        BodyDirection::Flat => 0,
        BodyDirection::Up => 1,
    }
}

#[inline]
pub(crate) fn half_flips(left: i8, right: i8) -> u32 {
    u32::from((left - right).unsigned_abs())
}

fn order_distance(left: &[usize], right: &[usize], bound: u32) -> u32 {
    let mut total = 0;
    for j in 1..left.len() {
        for i in 0..j {
            total += half_flips(left[i].cmp(&left[j]) as i8, right[i].cmp(&right[j]) as i8);
            if total > bound {
                return OUTSIDE;
            }
        }
    }
    total
}

pub(super) fn distance(left: &GeometryPattern, right: &GeometryPattern) -> usize {
    let a: Vec<_> = left.ranks().iter().flatten().copied().collect();
    let b: Vec<_> = right.ranks().iter().flatten().copied().collect();
    let mut total = order_distance(&a, &b, u32::MAX);
    if left.mode() == GeometryMode::Oriented {
        let direction = left
            .directions()
            .unwrap()
            .iter()
            .zip(right.directions().unwrap());
        total += direction
            .map(|(&a, &b)| half_flips(colour(a), colour(b)))
            .sum::<u32>();
    }
    for (a, b) in left.dimensions().iter().zip(right.dimensions()) {
        let levels = |part: &crate::geometry::DimensionPart| {
            part.ranks()
                .iter()
                .copied()
                .chain(part.reference())
                .collect::<Vec<_>>()
        };
        total += order_distance(&levels(a), &levels(b), u32::MAX);
    }
    total as usize
}
