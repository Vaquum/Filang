//! Prepared exact queries over a recording. A width indexes observed price
//! and axis keys independently, so toggling axes never builds their product.

use super::{
    decimal_price_domain, dimensions::AxisEncoder, Counters, DecimalNatural, Dimension,
    DimensionPart, DimensionSet, GeometryEncoder, GeometryKey, GeometryMode, GeometryPattern,
    GEOMETRY_KEY_MAX_BARS,
};
use crate::Result;
use std::{collections::HashMap, hash::Hash, sync::Arc};

/// A recording contains grid slots, including missing bars.
pub const MAX_SLOTS: usize = 1_000_000;
/// Bound storage and preparation work independently of the compact key width.
pub const MAX_WIDTH: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Reading {
    Recorded,
    Chained,
}

impl Reading {
    pub fn parse(name: &str) -> Result<Self> {
        match name {
            "recorded" => Ok(Self::Recorded),
            "chained" => Ok(Self::Chained),
            _ => Err("reading must be recorded or chained".into()),
        }
    }

    /// The first bar keeps its own open. Later chained bars open at the
    /// previous recorded close and widen to contain that open.
    pub(crate) fn candle(self, mut ohlc: [f64; 4], previous_close: Option<f64>) -> [f64; 4] {
        if let (Self::Chained, Some(open)) = (self, previous_close) {
            ohlc[0] = open;
            ohlc[1] = ohlc[1].max(open);
            ohlc[2] = ohlc[2].min(open);
        }
        ohlc
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Bar {
    ohlc: [f64; 4],
    counters: Option<Counters>,
}

impl Bar {
    pub fn new(ohlc: [f64; 4], counters: Option<Counters>) -> Result<Self> {
        let [o, h, l, c] = ohlc;
        if ohlc.iter().any(|p| !p.is_finite()) || l > o.min(c) || h < o.max(c) {
            return Err("invalid geometry bar OHLC".into());
        }
        Ok(Self { ohlc, counters })
    }

    fn value(self, axis: Dimension) -> Option<f64> {
        axis.value(self.counters?)
    }
}

#[derive(Clone)]
pub struct Recording(Arc<[Option<Bar>]>);

fn check_width(width: usize) -> Result<()> {
    if !(1..=MAX_WIDTH).contains(&width) {
        return Err(format!("geometry width must be in 1..={MAX_WIDTH}"));
    }
    Ok(())
}

/// Exact size of the declared space, including any combinations made
/// unrealizable by dependent axes. Counting does not visit patterns.
pub fn declared_count(
    width: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
) -> Result<String> {
    check_width(width)?;
    let mut count = decimal_price_domain(width, mode)?;
    if !dimensions.is_empty() {
        let mut levels = vec![DecimalNatural::from_usize(1)];
        let mut bell = [DecimalNatural::default(), DecimalNatural::default()];
        for points in 1..=width + 1 {
            let mut next = vec![DecimalNatural::default(); points + 1];
            for k in 1..=points {
                next[k].add_multiple(&levels[k - 1], k as u32);
                if let Some(same) = levels.get(k) {
                    next[k].add_multiple(same, k as u32);
                }
                if points >= width {
                    bell[points - width].add_multiple(&next[k], 1);
                }
            }
            levels = next;
        }
        for axis in dimensions.iter() {
            count = count.multiply(&bell[usize::from(axis.has_reference())]);
        }
    }
    Ok(count.to_string())
}

impl Recording {
    pub fn new(bars: Vec<Option<Bar>>) -> Result<Self> {
        if bars.len() > MAX_SLOTS {
            return Err(format!("geometry recording exceeds {MAX_SLOTS} grid slots"));
        }
        Ok(Self(bars.into()))
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn prepare(&self, width: usize) -> Result<PreparedGeometry> {
        check_width(width)?;
        Ok(PreparedGeometry {
            recording: self.clone(),
            width,
            prices: HashMap::new(),
            axes: Default::default(),
            valid_counts: HashMap::new(),
        })
    }

    /// Read the inclusive end slot. A prefix, gap, or missing selected value
    /// produces an unknown window.
    pub fn pattern_at(
        &self,
        end: usize,
        width: usize,
        mode: GeometryMode,
        reading: Reading,
        dimensions: DimensionSet,
    ) -> Result<Option<GeometryPattern>> {
        check_width(width)?;
        if end >= self.len() {
            return Err("geometry end slot is outside the recording".into());
        }
        if end + 1 < width {
            return Ok(None);
        }
        let bars = &self.0[end + 1 - width..=end];
        let mut rows = vec![[0.0; 4]; width];
        if !load(bars, &mut rows, reading) {
            return Ok(None);
        }
        let mut parts = Vec::with_capacity(dimensions.len());
        for dimension in dimensions.iter() {
            let values: Option<Vec<_>> = bars
                .iter()
                .map(|bar| bar.as_ref()?.value(dimension))
                .collect();
            let values = match values {
                Some(values) => values,
                None => return Ok(None),
            };
            parts.push(AxisEncoder::new(dimension, width).encode(&values).clone());
        }
        let mut encoder = GeometryEncoder::new(width, mode)?;
        let price = encoder.encode_ohlc(&rows)?;
        Ok(Some(price.with_parts(parts)?))
    }
}

/// Encode a drawn window. Marks supply coordinates on each axis directly,
/// including signed coordinates around zero on axes that have a reference.
pub fn encode_drawing(
    rows: &[[f64; 4]],
    mode: GeometryMode,
    reading: Reading,
    axes: &[(Dimension, &[f64])],
) -> Result<GeometryPattern> {
    check_width(rows.len())?;
    let mut adjusted = Vec::with_capacity(rows.len());
    let mut previous_close = None;
    for &row in rows {
        Bar::new(row, None)?;
        adjusted.push(reading.candle(row, previous_close));
        previous_close = Some(row[3]);
    }
    let mut parts = Vec::with_capacity(axes.len());
    for &(axis, values) in axes {
        if values.len() != rows.len() || values.iter().any(|x| !x.is_finite()) {
            return Err(format!("invalid drawing marks on {axis}"));
        }
        parts.push(AxisEncoder::new(axis, rows.len()).encode(values).clone());
    }
    parts.sort_unstable_by_key(DimensionPart::dimension);
    GeometryEncoder::new(rows.len(), mode)?
        .encode_ohlc(&adjusted)?
        .with_parts(parts)
}

fn load(bars: &[Option<Bar>], rows: &mut [[f64; 4]], reading: Reading) -> bool {
    let mut previous_close = None;
    for (bar, row) in bars.iter().zip(rows) {
        let bar = match bar {
            Some(bar) => bar,
            None => return false,
        };
        *row = reading.candle(bar.ohlc, previous_close);
        previous_close = Some(bar.ohlc[3]);
    }
    true
}

/// Exact slot counts, including missing and incomplete windows.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Counts {
    pub matched: usize,
    pub false_count: usize,
    pub unknown: usize,
}

struct Postings<K> {
    slots: HashMap<K, Vec<u32>>,
    validity: Vec<u64>,
    valid_count: usize,
}

impl<K: Eq + Hash> Postings<K> {
    fn new(len: usize) -> Self {
        Self {
            slots: HashMap::new(),
            validity: vec![0; (len + 63) / 64],
            valid_count: 0,
        }
    }

    fn insert(&mut self, key: K, end: usize) {
        self.slots.entry(key).or_default().push(end as u32);
        self.validity[end / 64] |= 1 << (end % 64);
        self.valid_count += 1;
    }

    fn get(&self, key: &K) -> &[u32] {
        self.slots.get(key).map_or(&[], Vec::as_slice)
    }
}

enum Keys<Compact, Wide> {
    Compact(Postings<Compact>),
    Wide(Postings<Wide>),
}

impl<C, W> Keys<C, W> {
    fn validity(&self) -> &[u64] {
        match self {
            Self::Compact(postings) => &postings.validity,
            Self::Wide(postings) => &postings.validity,
        }
    }

    fn valid_count(&self) -> usize {
        match self {
            Self::Compact(postings) => postings.valid_count,
            Self::Wide(postings) => postings.valid_count,
        }
    }
}

type PriceKeys = Keys<GeometryKey, GeometryPattern>;
type AxisKeys = Keys<u64, DimensionPart>;

/// Cache lifetime is explicit. Drop this value to release a width's indexes.
/// More than one reading or orientation can share the same prepared axes.
pub struct PreparedGeometry {
    recording: Recording,
    width: usize,
    prices: HashMap<(GeometryMode, Reading), PriceKeys>,
    axes: [Option<AxisKeys>; 5],
    valid_counts: HashMap<DimensionSet, usize>,
}

impl PreparedGeometry {
    /// Prepare one price reading and the requested axes. Already prepared
    /// keys are reused. Price-only callers load no axis or counter data here.
    pub fn prepare(
        &mut self,
        mode: GeometryMode,
        reading: Reading,
        dimensions: DimensionSet,
    ) -> Result<()> {
        use std::collections::hash_map::Entry;
        if let Entry::Vacant(entry) = self.prices.entry((mode, reading)) {
            entry.insert(index_prices(&self.recording, self.width, mode, reading)?);
        }
        for axis in dimensions.iter() {
            let entry = &mut self.axes[axis as usize];
            if entry.is_none() {
                *entry = Some(index_axis(&self.recording, self.width, axis));
            }
        }
        if !self.valid_counts.contains_key(&dimensions) {
            let price = &self.prices[&(mode, reading)];
            let selected: Vec<_> = dimensions
                .iter()
                .map(|axis| self.axes[axis as usize].as_ref().unwrap().validity())
                .collect();
            let valid = if selected.is_empty() {
                price.valid_count()
            } else {
                price
                    .validity()
                    .iter()
                    .enumerate()
                    .map(|(i, &word)| {
                        selected
                            .iter()
                            .fold(word, |valid, axis| valid & axis[i])
                            .count_ones() as usize
                    })
                    .sum()
            };
            self.valid_counts.insert(dimensions, valid);
        }
        Ok(())
    }

    /// Count without collecting rows. Warm work visits the smallest
    /// matching posting list, and a price-only count is a key lookup.
    pub fn counts(&mut self, pattern: &GeometryPattern, reading: Reading) -> Result<Counts> {
        self.prepare_pattern(pattern, reading)?;
        let lists = self.lists(pattern, reading)?;
        let matched = if lists.len == 1 {
            lists.slots[0].len()
        } else {
            lists.matches().count()
        };
        let valid = self.valid_counts[&pattern.dimension_set()];
        Ok(Counts {
            matched,
            false_count: valid - matched,
            unknown: self.recording.len() - valid,
        })
    }

    /// Materialize a bounded page in chronological order. Counts remain
    /// independent of the page size.
    pub fn positions(
        &mut self,
        pattern: &GeometryPattern,
        reading: Reading,
        start_slot: usize,
        limit: usize,
    ) -> Result<Vec<u32>> {
        self.prepare_pattern(pattern, reading)?;
        let mut lists = self.lists(pattern, reading)?;
        for slots in &mut lists.slots[..lists.len] {
            *slots = &slots[slots.partition_point(|slot| (*slot as usize) < start_slot)..];
        }
        Ok(lists.matches().take(limit).collect())
    }

    fn prepare_pattern(&mut self, pattern: &GeometryPattern, reading: Reading) -> Result<()> {
        if pattern.len() != self.width {
            return Err("geometry pattern and prepared width disagree".into());
        }
        self.prepare(pattern.mode(), reading, pattern.dimension_set())
    }

    fn lists(&self, pattern: &GeometryPattern, reading: Reading) -> Result<MatchLists<'_>> {
        let price = &self.prices[&(pattern.mode(), reading)];
        let mut slots = [&[][..]; 6];
        slots[0] = match price {
            Keys::Compact(postings) => postings.get(&GeometryKey::from_price(pattern)?),
            Keys::Wide(postings) if pattern.has_dimensions() => postings.get(&pattern.price()),
            Keys::Wide(postings) => postings.get(pattern),
        };
        for (i, part) in pattern.dimensions().iter().enumerate() {
            slots[i + 1] = match self.axes[part.dimension() as usize].as_ref().unwrap() {
                Keys::Compact(postings) => postings.get(&part.pack()),
                Keys::Wide(postings) => postings.get(part),
            };
        }
        Ok(MatchLists {
            slots,
            len: 1 + pattern.dimensions().len(),
        })
    }
}

struct MatchLists<'a> {
    slots: [&'a [u32]; 6],
    len: usize,
}

impl MatchLists<'_> {
    fn matches(&self) -> impl Iterator<Item = u32> + '_ {
        let mut lists = self.slots;
        lists[..self.len].sort_unstable_by_key(|list| list.len());
        lists[0].iter().copied().filter(move |slot| {
            lists[1..self.len]
                .iter()
                .all(|list| list.binary_search(slot).is_ok())
        })
    }
}

fn index_prices(
    recording: &Recording,
    width: usize,
    mode: GeometryMode,
    reading: Reading,
) -> Result<PriceKeys> {
    let mut rows = vec![[0.0; 4]; width];
    let mut encoder = GeometryEncoder::new(width, mode)?;
    let scan = |rows: &mut [[f64; 4]],
                visit: &mut dyn FnMut(usize, &[[f64; 4]]) -> Result<()>|
     -> Result<()> {
        for (start, bars) in recording.0.windows(width).enumerate() {
            if load(bars, rows, reading) {
                visit(start + width - 1, rows)?;
            }
        }
        Ok(())
    };
    if width <= GEOMETRY_KEY_MAX_BARS {
        let mut postings = Postings::new(recording.len());
        scan(&mut rows, &mut |end, rows| {
            postings.insert(encoder.encode_key_ohlc(rows)?, end);
            Ok(())
        })?;
        Ok(Keys::Compact(postings))
    } else {
        let mut postings = Postings::new(recording.len());
        scan(&mut rows, &mut |end, rows| {
            postings.insert(encoder.encode_ohlc(rows)?.clone(), end);
            Ok(())
        })?;
        Ok(Keys::Wide(postings))
    }
}

fn index_axis(recording: &Recording, width: usize, axis: Dimension) -> AxisKeys {
    let values: Vec<_> = recording
        .0
        .iter()
        .map(|bar| bar.and_then(|bar| bar.value(axis)).unwrap_or(f64::NAN))
        .collect();
    let mut encoder = AxisEncoder::new(axis, width);
    let mut run = 0;
    let mut prepared = values.iter().enumerate().filter_map(|(end, value)| {
        run = if value.is_nan() { 0 } else { run + 1 };
        (run >= width).then_some(end)
    });
    if width <= GEOMETRY_KEY_MAX_BARS {
        let mut postings = Postings::new(recording.len());
        for end in &mut prepared {
            let part = encoder.encode(&values[end + 1 - width..=end]);
            postings.insert(part.pack(), end);
        }
        Keys::Compact(postings)
    } else {
        let mut postings = Postings::new(recording.len());
        for end in prepared {
            let part = encoder.encode(&values[end + 1 - width..=end]);
            postings.insert(part.clone(), end);
        }
        Keys::Wide(postings)
    }
}
