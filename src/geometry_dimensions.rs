//! Optional, switchable dimensions beside price (docs/G1_DIMENSIONS.md).
//!
//! Price is the axis a pattern always has, with four points per candle. Each
//! dimension is one more axis with one point per candle, ranked only against
//! itself; `delta` and `imbalance` also rank the reference point zero. Nothing
//! here compares a value on one axis with a value on another.
//!
//! A dimension part is written `name:r,r,...` or, with a reference,
//! `name:r,r,.../r`, after the price part and a `|`. Parts follow the order
//! volume, trades, delta, size, imbalance, each at most once.
//!
//! # Key words
//!
//! A key with a dimension on is the unchanged four-word price key followed by
//! one `u64` per switched-on dimension, in that same order:
//!
//! ```text
//! bits  0..39   candle ranks, four bits each, candle i at bits 4i..4i+3
//! bits 40..43   the reference point's rank; zero when the dimension has none
//! bits 44..51   the dimension: volume 1, trades 2, delta 3, size 4, imbalance 5
//! bits 52..63   zero
//! ```
//!
//! Ranks of candles beyond the window are zero. Because the dimension field is
//! never zero, a dimension word is never zero, and a key with no dimension on
//! has no such word: it is the 0.9 key.
use super::{
    canonical_rank, choose, decimal_domain, empty_pattern, enumerate_patterns, first_unobserved_by,
    walk_patterns, BodyDirection, DecimalNatural, GeometryEncoder, GeometryKey, GeometryMode,
    GeometryPattern, GEOMETRY_KEY_MAX_BARS,
};
use crate::Result;
use std::{cmp::Ordering, fmt, str::FromStr};

/// The largest trade count a 64-bit float holds exactly, as the recording
/// contract requires.
const MAX_WHOLE_COUNT: f64 = 9_007_199_254_740_991.0;

/// An axis a pattern can switch on beside price. The order of the variants is
/// the order their parts are written and their key words are appended.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Dimension {
    Volume,
    Trades,
    Delta,
    Size,
    Imbalance,
}

impl Dimension {
    pub const ALL: [Self; 5] = [
        Self::Volume,
        Self::Trades,
        Self::Delta,
        Self::Size,
        Self::Imbalance,
    ];

    pub fn name(self) -> &'static str {
        match self {
            Self::Volume => "volume",
            Self::Trades => "trades",
            Self::Delta => "delta",
            Self::Size => "size",
            Self::Imbalance => "imbalance",
        }
    }

    pub fn parse(text: &str) -> Result<Self> {
        Self::ALL
            .iter()
            .copied()
            .find(|dimension| dimension.name() == text)
            .ok_or_else(|| {
                "geometry dimension must be volume, trades, delta, size or imbalance".into()
            })
    }

    /// Whether the reference point zero is ranked with the candles.
    pub fn has_reference(self) -> bool {
        matches!(self, Self::Delta | Self::Imbalance)
    }

    /// Points on this axis for a window: one per candle, and the reference.
    pub fn points(self, candles: usize) -> usize {
        candles.saturating_add(self.has_reference() as usize)
    }

    /// One candle's value: the 64-bit float its formula gives when evaluated
    /// exactly as written, one rounding per operation and none fused. `None`
    /// is a value that does not exist, which is kept apart from any number.
    pub fn value(self, counters: Counters) -> Option<f64> {
        let Counters {
            volume,
            taker_buy_volume,
            trades,
        } = counters;
        match self {
            Self::Volume => Some(volume),
            Self::Trades => Some(trades),
            Self::Delta => Some(2.0 * taker_buy_volume - volume),
            Self::Size => {
                if trades > 0.0 {
                    Some(volume / trades)
                } else {
                    None
                }
            }
            Self::Imbalance => {
                if volume > 0.0 {
                    Some((2.0 * taker_buy_volume - volume) / volume)
                } else {
                    None
                }
            }
        }
    }

    fn bit(self) -> u8 {
        1 << self as u8
    }

    fn code(self) -> u64 {
        self as u64 + 1
    }

    fn from_code(code: u64) -> Option<Self> {
        Self::ALL
            .iter()
            .copied()
            .find(|dimension| dimension.code() == code)
    }
}

impl fmt::Display for Dimension {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

impl FromStr for Dimension {
    type Err = String;
    fn from_str(text: &str) -> Result<Self> {
        Self::parse(text)
    }
}

/// One candle's counters: USDT traded, taker-buy USDT and the trade count.
/// Construction checks them once, so encoding does not check them again.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Counters {
    volume: f64,
    taker_buy_volume: f64,
    trades: f64,
}

impl Counters {
    pub fn new(volume: f64, taker_buy_volume: f64, trades: f64) -> Result<Self> {
        let all = [volume, taker_buy_volume, trades];
        if all.iter().any(|x| !x.is_finite() || *x < 0.0) {
            return Err("geometry counters must be finite and nonnegative".into());
        }
        if taker_buy_volume > volume {
            return Err("geometry taker-buy volume exceeds volume".into());
        }
        if trades.fract() != 0.0 || trades > MAX_WHOLE_COUNT {
            return Err("geometry trade count must be a whole number held exactly".into());
        }
        Ok(Self {
            volume,
            taker_buy_volume,
            trades,
        })
    }

    /// The three counter fields of one row of the nine-column recording, as
    /// text. An amount is digits, an optional fraction and an optional
    /// exponent, which is how the shortest text of a very small float reads.
    /// A trade count is digits only. Signs, spaces, `inf` and `nan` are not
    /// amounts, and a number too large to hold is refused.
    pub fn parse(volume: &str, taker_buy_volume: &str, trades: &str) -> Result<Self> {
        let volume = amount(volume).ok_or("volume is not a nonnegative finite amount")?;
        let taker_buy_volume = amount(taker_buy_volume)
            .ok_or("taker_buy_volume is not a nonnegative finite amount")?;
        if trades.is_empty() || !trades.bytes().all(|b| b.is_ascii_digit()) {
            return Err("trade_count is not a whole number".into());
        }
        let trades = trades
            .parse::<f64>()
            .map_err(|_| "trade_count is not a whole number")?;
        Self::new(volume, taker_buy_volume, trades)
    }

    pub fn volume(self) -> f64 {
        self.volume
    }

    pub fn taker_buy_volume(self) -> f64 {
        self.taker_buy_volume
    }

    pub fn trades(self) -> f64 {
        self.trades
    }
}

/// The header of the recording that carries counters beside prices: Cube's
/// names, with `volume` in USDT. The six-column form carries none.
pub const COUNTER_COLUMNS: &str =
    "open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count";

/// `digits [ "." digits ] [ "e" [ "+" | "-" ] digits ]`, read by the float
/// parser, which rounds correctly; a value that overflows is not an amount.
fn amount(text: &str) -> Option<f64> {
    let digits = |part: &str| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit());
    let (mantissa, exponent) = match text.split_once('e') {
        Some((mantissa, exponent)) => (mantissa, Some(exponent)),
        None => (text, None),
    };
    let (whole, fraction) = match mantissa.split_once('.') {
        Some((whole, fraction)) => (whole, Some(fraction)),
        None => (mantissa, None),
    };
    if !digits(whole) || fraction.map_or(false, |fraction| !digits(fraction)) {
        return None;
    }
    if let Some(exponent) = exponent {
        let unsigned = exponent
            .strip_prefix('+')
            .or_else(|| exponent.strip_prefix('-'))
            .unwrap_or(exponent);
        if !digits(unsigned) {
            return None;
        }
    }
    text.parse::<f64>().ok().filter(|value| value.is_finite())
}

/// Which dimensions are on. Any set is legal; the empty set is 0.9 geometry.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct DimensionSet(u8);

impl DimensionSet {
    pub const NONE: Self = Self(0);

    pub fn all() -> Self {
        Self::ALL_BITS
    }

    const ALL_BITS: Self = Self(0b1_1111);

    /// Comma-separated names in any order, each at most once. Empty text is
    /// the empty set. Unknown names and repeats are rejected.
    pub fn parse(text: &str) -> Result<Self> {
        let mut set = Self::NONE;
        if text.trim().is_empty() {
            return Ok(set);
        }
        for name in text.split(',') {
            let dimension = Dimension::parse(name.trim())?;
            if set.contains(dimension) {
                return Err(format!("geometry dimension {dimension} is named twice"));
            }
            set = set.with(dimension);
        }
        Ok(set)
    }

    pub fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub fn len(self) -> usize {
        self.0.count_ones() as usize
    }

    pub fn contains(self, dimension: Dimension) -> bool {
        self.0 & dimension.bit() != 0
    }

    pub fn with(self, dimension: Dimension) -> Self {
        Self(self.0 | dimension.bit())
    }

    pub fn without(self, dimension: Dimension) -> Self {
        Self(self.0 & !dimension.bit())
    }

    /// The dimensions that are on, in the order their parts are written.
    pub fn iter(self) -> impl Iterator<Item = Dimension> {
        Dimension::ALL
            .into_iter()
            .filter(move |dimension| self.contains(*dimension))
    }

    /// Whether the declared domain of a window of `candles` contains patterns
    /// no recording can produce. `imbalance` is `delta` over `volume`, so their
    /// sides of zero must agree; `size` is `volume` over `trades`, so their
    /// three orders constrain each other once there are two candles.
    pub fn includes_patterns_that_cannot_occur(self, candles: usize) -> bool {
        let has = |dimension| self.contains(dimension);
        candles >= 1 && has(Dimension::Delta) && has(Dimension::Imbalance)
            || candles >= 2
                && has(Dimension::Volume)
                && has(Dimension::Trades)
                && has(Dimension::Size)
    }

    /// A JSON array of the names, for reports.
    pub fn json(self) -> String {
        let names = self
            .iter()
            .map(|dimension| format!("\"{dimension}\""))
            .collect::<Vec<_>>();
        format!("[{}]", names.join(","))
    }
}

impl fmt::Display for DimensionSet {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for (i, dimension) in self.iter().enumerate() {
            if i > 0 {
                f.write_str(",")?;
            }
            f.write_str(dimension.name())?;
        }
        Ok(())
    }
}

impl FromStr for DimensionSet {
    type Err = String;
    fn from_str(text: &str) -> Result<Self> {
        Self::parse(text)
    }
}

/// One dimension's part of a pattern: a dense rank for each candle and, where
/// the dimension has a reference point, the rank of that point among them.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct DimensionPart {
    dimension: Dimension,
    ranks: Vec<usize>,
    reference: Option<usize>,
}

impl DimensionPart {
    /// `reference` is required exactly when the dimension has a reference
    /// point. Ranks must be dense from zero, the reference included.
    pub fn new(dimension: Dimension, ranks: Vec<usize>, reference: Option<usize>) -> Result<Self> {
        let part = Self {
            dimension,
            ranks,
            reference,
        };
        part.validate(part.ranks.len())?;
        Ok(part)
    }

    pub fn dimension(&self) -> Dimension {
        self.dimension
    }

    pub fn ranks(&self) -> &[usize] {
        &self.ranks
    }

    pub fn reference(&self) -> Option<usize> {
        self.reference
    }

    /// Distinct levels on this axis, the reference point's included.
    pub fn level_count(&self) -> usize {
        self.ranks
            .iter()
            .chain(self.reference.iter())
            .map(|rank| rank + 1)
            .max()
            .unwrap_or(0)
    }

    /// Whether these values, one per candle and all of them present, stand
    /// in this part's order: equal exactly where ranks are equal, and
    /// increasing with rank, the reference point zero among them. `levels`
    /// is scratch that is resized here and can be reused across windows.
    pub fn matches_values(&self, values: &[f64], levels: &mut Vec<f64>) -> bool {
        if values.len() != self.ranks.len() {
            return false;
        }
        levels.clear();
        levels.resize(self.level_count(), f64::NAN);
        if let Some(reference) = self.reference {
            levels[reference] = 0.0;
        }
        for (&rank, &value) in self.ranks.iter().zip(values) {
            if !levels[rank].is_nan() && levels[rank] != value {
                return false;
            }
            levels[rank] = value;
        }
        // Ranks are dense, so every level now holds one value.
        levels.windows(2).all(|pair| pair[0] < pair[1])
    }

    fn validate(&self, candles: usize) -> Result<()> {
        let name = self.dimension.name();
        if self.ranks.len() != candles {
            return Err(format!(
                "geometry {name} part needs one rank for each candle"
            ));
        }
        if self.reference.is_some() != self.dimension.has_reference() {
            return Err(if self.dimension.has_reference() {
                format!("geometry {name} part ends with \"/\" and the rank of zero")
            } else {
                format!("geometry {name} part has no reference point, so it takes no \"/\"")
            });
        }
        // Check bounds before allocating by rank, as the price part does.
        let points = self.dimension.points(candles);
        let dense = || format!("geometry {name} ranks must be dense and start at zero");
        if self
            .ranks
            .iter()
            .chain(self.reference.iter())
            .any(|rank| *rank >= points)
        {
            return Err(dense());
        }
        let mut used = vec![false; self.level_count()];
        for &rank in self.ranks.iter().chain(self.reference.iter()) {
            used[rank] = true;
        }
        if used.iter().any(|used| !used) {
            return Err(dense());
        }
        Ok(())
    }

    /// Parse one part for a window of `candles`. Anything the grammar does
    /// not write is rejected. A zero-candle pattern, which only the algebra
    /// constructs, has no rank to write: its parts read `volume:` and
    /// `delta:/0`.
    pub(super) fn parse(text: &str, candles: usize) -> Result<Self> {
        let (name, body) = text.split_once(':').ok_or(
            "geometry dimension part must be a dimension, a colon and one rank for each candle",
        )?;
        let dimension = Dimension::parse(name)?;
        let (rank_text, reference) = match body.split_once('/') {
            Some((ranks, reference)) => (ranks, Some(canonical_rank(reference)?)),
            None => (body, None),
        };
        let mut ranks = Vec::new();
        if candles > 0 || !rank_text.is_empty() {
            for token in rank_text.split(',') {
                ranks.push(canonical_rank(token)?);
            }
        }
        let part = Self {
            dimension,
            ranks,
            reference,
        };
        part.validate(candles)?;
        Ok(part)
    }

    pub(super) fn pack(&self) -> u64 {
        let mut word = self.dimension.code() << 44;
        for (i, &rank) in self.ranks.iter().enumerate() {
            word |= (rank as u64) << (4 * i);
        }
        if let Some(reference) = self.reference {
            word |= (reference as u64) << 40;
        }
        word
    }

    fn unpack(word: u64, candles: usize) -> Result<Self> {
        let dimension = Dimension::from_code((word >> 44) & 255)
            .ok_or("geometry dimension word names no dimension")?;
        let part = Self {
            dimension,
            ranks: (0..candles)
                .map(|i| ((word >> (4 * i)) & 15) as usize)
                .collect(),
            reference: dimension
                .has_reference()
                .then(|| ((word >> 40) & 15) as usize),
        };
        part.validate(candles)?;
        if part.pack() != word {
            return Err("geometry dimension word has noncanonical unused bits".into());
        }
        Ok(part)
    }
}

impl fmt::Display for DimensionPart {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:", self.dimension.name())?;
        for (i, rank) in self.ranks.iter().enumerate() {
            if i > 0 {
                f.write_str(",")?;
            }
            write!(f, "{rank}")?;
        }
        if let Some(reference) = self.reference {
            write!(f, "/{reference}")?;
        }
        Ok(())
    }
}

/// Parts must follow the canonical order, each at most once, and each must be
/// a valid part for the window.
pub(super) fn validate_parts(parts: &[DimensionPart], candles: usize) -> Result<()> {
    for (i, part) in parts.iter().enumerate() {
        if i > 0 && parts[i - 1].dimension >= part.dimension {
            return Err(
                "geometry dimension parts follow the order volume, trades, delta, size, imbalance, each at most once"
                    .into(),
            );
        }
        part.validate(candles)?;
    }
    Ok(())
}

impl GeometryPattern {
    /// A price pattern with dimension parts switched on. The parts must be in
    /// canonical order, each at most once, with one rank per candle.
    pub fn with_dimensions(
        ranks: Vec<[usize; 4]>,
        directions: Option<Vec<BodyDirection>>,
        dimensions: Vec<DimensionPart>,
    ) -> Result<Self> {
        let pattern = Self {
            ranks,
            directions,
            dimensions,
        };
        pattern.validate()?;
        Ok(pattern)
    }

    /// The same price part with exactly these dimension parts on.
    pub fn with_parts(&self, dimensions: Vec<DimensionPart>) -> Result<Self> {
        validate_parts(&dimensions, self.len())?;
        Ok(Self {
            ranks: self.ranks.clone(),
            directions: self.directions.clone(),
            dimensions,
        })
    }

    /// OHLC rows are `[open, high, low, close]`, with one `Counters` per row.
    /// `None` means a candle has no value on a switched-on dimension: the
    /// window is invalid for that set of dimensions, whatever its prices.
    pub fn from_ohlc_counters(
        rows: &[[f64; 4]],
        counters: &[Counters],
        mode: GeometryMode,
        dimensions: DimensionSet,
    ) -> Result<Option<Self>> {
        let mut encoder = GeometryDimensionEncoder::new(rows.len(), mode, dimensions)?;
        let valid = encoder.encode_ohlc(rows, counters)?.is_some();
        Ok(if valid {
            Some(encoder.price.pattern)
        } else {
            None
        })
    }

    /// Three-valued: `Some(true)` or `Some(false)` on a valid window, `None`
    /// when a candle has no value on a dimension this pattern has on.
    pub fn matches_ohlc_counters(
        &self,
        rows: &[[f64; 4]],
        counters: &[Counters],
    ) -> Result<Option<bool>> {
        let observed = Self::from_ohlc_counters(rows, counters, self.mode(), self.dimension_set())?;
        Ok(observed.map(|observed| observed == *self))
    }

    /// The parts that are on, in canonical order. Empty for a 0.9 pattern.
    pub fn dimensions(&self) -> &[DimensionPart] {
        &self.dimensions
    }

    pub fn has_dimensions(&self) -> bool {
        !self.dimensions.is_empty()
    }

    pub fn dimension_set(&self) -> DimensionSet {
        self.dimensions
            .iter()
            .fold(DimensionSet::NONE, |set, part| set.with(part.dimension))
    }

    pub fn dimension(&self, dimension: Dimension) -> Option<&DimensionPart> {
        self.dimensions
            .iter()
            .find(|part| part.dimension == dimension)
    }

    /// The pattern with every dimension off: its 0.9 price pattern.
    pub fn price(&self) -> Self {
        Self {
            ranks: self.ranks.clone(),
            directions: self.directions.clone(),
            dimensions: Vec::new(),
        }
    }
}

/// A price key followed by one word per switched-on dimension. With no
/// dimension on it carries exactly the four words of `GeometryKey` and no
/// others. Ordering is the price words, then the dimension words in order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GeometryDimensionKey {
    price: GeometryKey,
    // Canonical order, packed to the front; unused words are zero. A real
    // dimension word is never zero.
    words: [u64; 5],
}

impl GeometryDimensionKey {
    pub fn from_pattern(pattern: &GeometryPattern) -> Result<Self> {
        let price = GeometryKey::from_price(pattern)?;
        let mut words = [0u64; 5];
        for (word, part) in words.iter_mut().zip(&pattern.dimensions) {
            *word = part.pack();
        }
        Ok(Self { price, words })
    }

    /// The unchanged four-word price key.
    pub fn price(self) -> GeometryKey {
        self.price
    }

    /// One word per switched-on dimension, in canonical order.
    pub fn dimension_words(&self) -> &[u64] {
        let count = self.words.iter().take_while(|word| **word != 0).count();
        &self.words[..count]
    }

    /// Check the price words as `GeometryKey::from_words` does, then every
    /// dimension word: its dimension, the order of the words, rank density
    /// with the reference, and every unused bit.
    pub fn from_words(price: [u64; 4], dimension_words: &[u64]) -> Result<Self> {
        let price = GeometryKey::from_words(price)?;
        if dimension_words.len() > Dimension::ALL.len() {
            return Err("geometry key has more dimension words than dimensions".into());
        }
        let mut parts = Vec::with_capacity(dimension_words.len());
        let mut words = [0u64; 5];
        for (slot, &word) in words.iter_mut().zip(dimension_words) {
            parts.push(DimensionPart::unpack(word, price.len())?);
            *slot = word;
        }
        validate_parts(&parts, price.len())?;
        Ok(Self { price, words })
    }

    pub fn len(self) -> usize {
        self.price.len()
    }

    pub fn is_empty(self) -> bool {
        self.price.is_empty()
    }

    pub fn mode(self) -> GeometryMode {
        self.price.mode()
    }

    pub fn dimensions(self) -> DimensionSet {
        self.dimension_words()
            .iter()
            .filter_map(|word| Dimension::from_code((word >> 44) & 255))
            .fold(DimensionSet::NONE, DimensionSet::with)
    }

    pub fn to_pattern(self) -> GeometryPattern {
        let mut pattern = self.price.to_pattern();
        pattern.dimensions = self
            .dimension_words()
            .iter()
            .map(|word| DimensionPart::unpack(*word, self.len()).expect("validated dimension word"))
            .collect();
        pattern
    }
}

impl fmt::Display for GeometryDimensionKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.price)?;
        for &word in self.dimension_words() {
            let dimension = Dimension::from_code((word >> 44) & 255).ok_or(fmt::Error)?;
            write!(f, "|{}:", dimension.name())?;
            for i in 0..self.len() {
                if i > 0 {
                    f.write_str(",")?;
                }
                write!(f, "{}", (word >> (4 * i)) & 15)?;
            }
            if dimension.has_reference() {
                write!(f, "/{}", (word >> 40) & 15)?;
            }
        }
        Ok(())
    }
}

/// Dense ranks of one axis's points, written into `part`. `values` holds the
/// candles' values and then, where the dimension has one, the reference point
/// zero. One sort of at most `candles + 1` values, with no allocation.
fn rank_into(values: &[f64], order: &mut [usize], part: &mut DimensionPart) {
    let candles = part.ranks.len();
    let order = &mut order[..values.len()];
    for (i, slot) in order.iter_mut().enumerate() {
        *slot = i;
    }
    // Order and equality are those of the floats, so -0.0 and +0.0 tie.
    // Checked counters cannot produce NaN.
    order.sort_unstable_by(|a, b| {
        values[*a]
            .partial_cmp(&values[*b])
            .unwrap_or(Ordering::Equal)
            .then_with(|| a.cmp(b))
    });
    let mut previous = None;
    let mut rank = 0;
    for &index in order.iter() {
        let value = values[index];
        if let Some(prior) = previous {
            if value != prior {
                rank += 1;
            }
        }
        if index < candles {
            part.ranks[index] = rank;
        } else {
            part.reference = Some(rank);
        }
        previous = Some(value);
    }
}

/// Scratch for ranking one axis across many consecutive windows.
pub(super) struct AxisEncoder {
    part: DimensionPart,
    values: Vec<f64>,
    order: Vec<usize>,
}

impl AxisEncoder {
    pub(super) fn new(dimension: Dimension, candles: usize) -> Self {
        let points = dimension.points(candles);
        Self {
            part: DimensionPart {
                dimension,
                ranks: vec![0; candles],
                reference: dimension.has_reference().then_some(0),
            },
            values: vec![0.0; points],
            order: vec![0; points],
        }
    }

    pub(super) fn encode(&mut self, values: &[f64]) -> &DimensionPart {
        self.values[..values.len()].copy_from_slice(values);
        rank_into(&self.values, &mut self.order, &mut self.part);
        &self.part
    }
}

/// Encodes windows of prices and counters for a chosen set of dimensions,
/// reusing all storage. The price part is encoded by the unchanged
/// `GeometryEncoder`; each dimension then costs one small sort.
pub struct GeometryDimensionEncoder {
    // Its pattern holds the preallocated dimension parts.
    price: GeometryEncoder,
    set: DimensionSet,
    values: Vec<f64>,
    order: Vec<usize>,
}

impl GeometryDimensionEncoder {
    pub fn new(n: usize, mode: GeometryMode, dimensions: DimensionSet) -> Result<Self> {
        let mut price = GeometryEncoder::new(n, mode)?;
        let points = n.checked_add(1).ok_or("geometry endpoint count overflow")?;
        let failed = |_| "geometry encoder allocation failed";
        let mut values = Vec::new();
        values.try_reserve_exact(points).map_err(failed)?;
        values.resize(points, 0.0);
        let mut order = Vec::new();
        order.try_reserve_exact(points).map_err(failed)?;
        order.resize(points, 0);
        for dimension in dimensions.iter() {
            let mut ranks = Vec::new();
            ranks.try_reserve_exact(n).map_err(failed)?;
            ranks.resize(n, 0);
            price.pattern.dimensions.push(DimensionPart {
                dimension,
                ranks,
                reference: dimension.has_reference().then_some(0),
            });
        }
        Ok(Self {
            price,
            set: dimensions,
            values,
            order,
        })
    }

    pub fn dimensions(&self) -> DimensionSet {
        self.set
    }

    /// `Ok(None)` is a window in which a candle has no value on a dimension
    /// that is on. It is invalid, which is not the same as matching nothing.
    pub fn encode_ohlc(
        &mut self,
        rows: &[[f64; 4]],
        counters: &[Counters],
    ) -> Result<Option<&GeometryPattern>> {
        if counters.len() != rows.len() {
            return Err("geometry encoder needs one set of counters for each candle".into());
        }
        self.price.encode_ohlc(rows)?;
        Ok(if self.rank_dimensions(counters) {
            Some(&self.price.pattern)
        } else {
            None
        })
    }

    pub fn encode_endpoints(
        &mut self,
        rows: &[[f64; 4]],
        directions: Option<&[BodyDirection]>,
        counters: &[Counters],
    ) -> Result<Option<&GeometryPattern>> {
        if counters.len() != rows.len() {
            return Err("geometry encoder needs one set of counters for each candle".into());
        }
        self.price.encode_endpoints(rows, directions)?;
        Ok(if self.rank_dimensions(counters) {
            Some(&self.price.pattern)
        } else {
            None
        })
    }

    /// The fixed-size key with its dimension words, without allocating.
    pub fn encode_key_ohlc(
        &mut self,
        rows: &[[f64; 4]],
        counters: &[Counters],
    ) -> Result<Option<GeometryDimensionKey>> {
        if self.price.pattern.len() > GEOMETRY_KEY_MAX_BARS {
            return Err("compact geometry key supports at most ten candles".into());
        }
        match self.encode_ohlc(rows, counters)? {
            Some(pattern) => GeometryDimensionKey::from_pattern(pattern).map(Some),
            None => Ok(None),
        }
    }

    pub fn encode_key_endpoints(
        &mut self,
        rows: &[[f64; 4]],
        directions: Option<&[BodyDirection]>,
        counters: &[Counters],
    ) -> Result<Option<GeometryDimensionKey>> {
        if self.price.pattern.len() > GEOMETRY_KEY_MAX_BARS {
            return Err("compact geometry key supports at most ten candles".into());
        }
        match self.encode_endpoints(rows, directions, counters)? {
            Some(pattern) => GeometryDimensionKey::from_pattern(pattern).map(Some),
            None => Ok(None),
        }
    }

    fn rank_dimensions(&mut self, counters: &[Counters]) -> bool {
        let n = counters.len();
        for part in &mut self.price.pattern.dimensions {
            for (slot, &candle) in self.values[..n].iter_mut().zip(counters) {
                match part.dimension.value(candle) {
                    Some(value) => *slot = value,
                    None => return false,
                }
            }
            let points = part.dimension.points(n);
            if points > n {
                self.values[n] = 0.0;
            }
            rank_into(&self.values[..points], &mut self.order, part);
        }
        true
    }
}

/// The ordered Bell number a(m): the weak orders of m labelled points.
/// `a(m) = sum over k = 1..m of C(m,k) * a(m-k)`, with `a(0) = 1`. Overflow
/// is an error, never saturation or truncation.
pub fn ordered_bell(points: usize) -> Result<u128> {
    let overflow = "geometry dimension count exceeds u128";
    // a(31) already exceeds u128; refuse a hostile size before any work.
    if points > 40 {
        return Err(overflow.into());
    }
    let mut values = vec![1u128];
    for m in 1..=points {
        let mut total = 0u128;
        for k in 1..=m {
            total = choose(m, k)?
                .checked_mul(values[m - k])
                .and_then(|term| total.checked_add(term))
                .ok_or(overflow)?;
        }
        values.push(total);
    }
    Ok(values[points])
}

/// Exact cardinality of the declared domain of an n-candle window with these
/// dimensions on: the 0.9 price count times one factor per dimension, a(n)
/// without a reference point and a(n + 1) with one. With none on this is
/// `count_domain`.
pub fn count_domain_with_dimensions(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
) -> Result<u128> {
    let mut total = super::count_domain(n, mode)?;
    for dimension in dimensions.iter() {
        total = total
            .checked_mul(ordered_bell(dimension.points(n))?)
            .ok_or("geometry domain count exceeds u128")?;
    }
    Ok(total)
}

/// `value * factor`, exactly: one scaled addition per base-10^9 digit of the
/// factor, each shifted by that digit's place.
fn scaled(value: &DecimalNatural, mut factor: u128) -> DecimalNatural {
    let mut product = DecimalNatural::default();
    let mut shifted = value.clone();
    while factor != 0 {
        product.add_multiple(&shifted, (factor % DecimalNatural::BASE as u128) as u32);
        factor /= DecimalNatural::BASE as u128;
        if !shifted.limbs.is_empty() {
            shifted.limbs.insert(0, 0);
        }
    }
    product
}

fn decimal_dimension_domain(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
) -> Result<DecimalNatural> {
    // The price count bounds n at ten candles before any factor is computed.
    let mut total = decimal_domain(n, mode)?;
    for dimension in dimensions.iter() {
        total = scaled(&total, ordered_bell(dimension.points(n))?);
    }
    Ok(total)
}

/// Exact decimal cardinality through ten candles with these dimensions on.
pub fn count_domain_decimal_with_dimensions(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
) -> Result<String> {
    Ok(decimal_dimension_domain(n, mode, dimensions)?.to_string())
}

/// Exact size of the complement of a set of distinct observed patterns in the
/// declared domain with these dimensions on.
pub fn count_domain_unobserved_decimal_with_dimensions(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
    observed: usize,
) -> Result<String> {
    let mut total = decimal_dimension_domain(n, mode, dimensions)?;
    total.subtract(&DecimalNatural::from_usize(observed))?;
    Ok(total.to_string())
}

/// Exact decimal count of the patterns a recording can produce when `delta`
/// and `imbalance` are the two dimensions on: the price count times
/// `count_delta_imbalance_occurring`. Prices do not constrain counters.
pub fn count_delta_imbalance_occurring_decimal(n: usize, mode: GeometryMode) -> Result<String> {
    let price = decimal_domain(n, mode)?;
    Ok(scaled(&price, count_delta_imbalance_occurring(n)?).to_string())
}

/// How many of the `a(n + 1)^2` declared combinations of a `delta` part and an
/// `imbalance` part a recording can produce. Each candle is net buying, net
/// selling or balanced on both axes at once; within a side the two orders are
/// free. Summing over the ways to split n candles into p buying, q selling
/// and z balanced: `n!/(p! q! z!) * a(p)^2 * a(q)^2`.
pub fn count_delta_imbalance_occurring(n: usize) -> Result<u128> {
    let overflow = "geometry dimension count exceeds u128";
    let mut total = 0u128;
    for p in 0..=n {
        for q in 0..=n - p {
            let ways = choose(n, p)?
                .checked_mul(choose(n - p, q)?)
                .ok_or(overflow)?;
            let buying = ordered_bell(p)?;
            let selling = ordered_bell(q)?;
            let term = [buying, buying, selling, selling]
                .iter()
                .try_fold(ways, |product, factor| product.checked_mul(*factor))
                .ok_or(overflow)?;
            total = total.checked_add(term).ok_or(overflow)?;
        }
    }
    Ok(total)
}

/// Advance a dense rank vector to its lexicographic successor among the weak
/// orders of its points. After the last one it returns false and leaves the
/// first: every point tied at rank zero.
fn next_weak_order(points: &mut [usize]) -> bool {
    let m = points.len();
    debug_assert!(m <= 64);
    for i in (0..m).rev() {
        let prefix = points[..i].iter().fold(0u64, |set, rank| set | 1 << rank);
        for candidate in points[i] + 1..m {
            let used = prefix | 1 << candidate;
            let levels = 64 - used.leading_zeros() as usize;
            let missing = levels - used.count_ones() as usize;
            if missing > m - i - 1 {
                continue;
            }
            points[i] = candidate;
            // The smallest completion: zeros, then each missing rank once.
            let free = m - i - 1 - missing;
            for point in &mut points[i + 1..i + 1 + free] {
                *point = 0;
            }
            let mut at = i + 1 + free;
            for rank in 0..levels {
                if used & 1 << rank == 0 {
                    points[at] = rank;
                    at += 1;
                }
            }
            return true;
        }
    }
    for point in points.iter_mut() {
        *point = 0;
    }
    false
}

/// Visit every pattern of the declared domain: price patterns in the 0.9
/// enumeration order, and for each the weak orders of every switched-on
/// dimension in lexicographic rank order, the last dimension changing first.
fn walk_dimensioned(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
    visitor: &mut dyn FnMut(&GeometryPattern) -> bool,
) -> bool {
    walk_patterns(&empty_pattern(mode), n, mode, &mut |price| {
        let mut pattern = price.clone();
        let mut points = Vec::new();
        for dimension in dimensions.iter() {
            pattern.dimensions.push(DimensionPart {
                dimension,
                ranks: vec![0; n],
                reference: dimension.has_reference().then_some(0),
            });
            points.push(vec![0usize; dimension.points(n)]);
        }
        loop {
            if !visitor(&pattern) {
                return false;
            }
            let mut k = points.len();
            loop {
                if k == 0 {
                    return true;
                }
                k -= 1;
                let advanced = next_weak_order(&mut points[k]);
                let part = &mut pattern.dimensions[k];
                part.ranks.copy_from_slice(&points[k][..n]);
                if part.reference.is_some() {
                    part.reference = Some(points[k][n]);
                }
                if advanced {
                    break;
                }
            }
        }
    })
}

/// Enumerate at most `limit` patterns of the declared domain with these
/// dimensions on, in the deterministic order of `walk_dimensioned`.
pub fn enumerate_patterns_with_dimensions(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
    limit: usize,
) -> Result<Vec<GeometryPattern>> {
    if dimensions.is_empty() {
        return enumerate_patterns(n, mode, limit);
    }
    count_domain_with_dimensions(n, mode, dimensions)?;
    let mut output = Vec::new();
    if limit == 0 {
        return Ok(output);
    }
    walk_dimensioned(n, mode, dimensions, &mut |pattern| {
        output.push(pattern.clone());
        output.len() < limit
    });
    Ok(output)
}

/// Find a deterministic pattern of the declared domain outside an observed
/// set, inspecting at most `observed_count + 1` candidates. `observed_count`
/// and `contains` must describe the same set of distinct patterns of this
/// window, mode and set of dimensions. A fully observed domain returns None.
pub fn first_unobserved_with_dimensions_by<F>(
    n: usize,
    mode: GeometryMode,
    dimensions: DimensionSet,
    observed_count: usize,
    mut contains: F,
) -> Result<Option<GeometryPattern>>
where
    F: FnMut(&GeometryPattern) -> bool,
{
    if dimensions.is_empty() {
        return first_unobserved_by(n, mode, observed_count, contains);
    }
    let total = count_domain_with_dimensions(n, mode, dimensions)?;
    if observed_count as u128 > total {
        return Err("observed geometry count exceeds legal domain".into());
    }
    if observed_count as u128 == total {
        return Ok(None);
    }
    let mut examined = 0usize;
    let mut found = None;
    let mut inconsistent = false;
    walk_dimensioned(n, mode, dimensions, &mut |pattern| {
        if !contains(pattern) {
            found = Some(pattern.clone());
            return false;
        }
        if examined == observed_count {
            inconsistent = true;
            return false;
        }
        examined += 1;
        true
    });
    if inconsistent || found.is_none() {
        return Err("geometry membership does not match observed count".into());
    }
    Ok(found)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn counters(volume: f64, taker_buy: f64, trades: f64) -> Counters {
        Counters::new(volume, taker_buy, trades).unwrap()
    }

    #[test]
    fn ordered_bell_numbers_and_declared_domains_match_the_contract() {
        let expected: [u128; 12] = [
            1,
            1,
            3,
            13,
            75,
            541,
            4_683,
            47_293,
            545_835,
            7_087_261,
            102_247_563,
            1_622_632_573,
        ];
        for (points, value) in expected.iter().enumerate() {
            assert_eq!(ordered_bell(points).unwrap(), *value);
        }
        for n in 1..=10 {
            for dimension in Dimension::ALL {
                let factor = expected[n + dimension.has_reference() as usize];
                assert_eq!(ordered_bell(dimension.points(n)).unwrap(), factor);
            }
        }
        assert!(ordered_bell(30).is_ok());
        assert!(ordered_bell(31).is_err());
        assert!(ordered_bell(usize::MAX).is_err());
        let set = |text: &str| DimensionSet::parse(text).unwrap();
        let oriented = GeometryMode::Oriented;
        for (dimensions, count) in [
            ("", 7_452u128),
            ("volume", 22_356),
            ("delta", 96_876),
            ("volume,delta", 290_628),
            ("delta,volume", 290_628),
            ("volume,trades,delta,size,imbalance", 7_452 * 4_563),
        ] {
            let dimensions = set(dimensions);
            assert_eq!(
                count_domain_with_dimensions(2, oriented, dimensions).unwrap(),
                count
            );
            assert_eq!(
                count_domain_decimal_with_dimensions(2, oriented, dimensions).unwrap(),
                count.to_string()
            );
            assert_eq!(
                count_domain_unobserved_decimal_with_dimensions(2, oriented, dimensions, 452)
                    .unwrap(),
                (count - 452).to_string()
            );
        }
        // With none on, both APIs are the 0.9 APIs.
        for mode in [GeometryMode::Unoriented, GeometryMode::Oriented] {
            for n in 0..=10 {
                assert_eq!(
                    count_domain_decimal_with_dimensions(n, mode, DimensionSet::NONE).unwrap(),
                    super::super::count_domain_decimal(n, mode).unwrap()
                );
                if n < 10 {
                    assert_eq!(
                        count_domain_with_dimensions(n, mode, DimensionSet::NONE).unwrap(),
                        super::super::count_domain(n, mode).unwrap()
                    );
                }
            }
        }
        // Ten candles with all five on: the decimal path multiplies exactly.
        assert_eq!(
            count_domain_decimal_with_dimensions(10, oriented, DimensionSet::all()).unwrap(),
            "124179648663075861400888921726431267366556272886692680824127608594485605595475860576276"
        );
        assert!(count_domain_with_dimensions(10, oriented, set("volume")).is_err());
        assert!(count_domain_with_dimensions(9, oriented, DimensionSet::all()).is_err());
        assert!(count_domain_decimal_with_dimensions(11, oriented, set("volume")).is_err());
        assert_eq!(count_delta_imbalance_occurring(0).unwrap(), 1);
        assert_eq!(count_delta_imbalance_occurring(1).unwrap(), 3);
        assert_eq!(count_delta_imbalance_occurring(2).unwrap(), 25);
        assert_eq!(count_delta_imbalance_occurring(3).unwrap(), 459);
        assert_eq!(
            count_delta_imbalance_occurring_decimal(2, oriented).unwrap(),
            (7_452 * 25).to_string()
        );
        // The scaled addition carries across limbs for a multi-limb factor.
        let big = scaled(
            &DecimalNatural::from_usize(4_000_000_007),
            123_456_789_012_345_678_901_234_567,
        );
        assert_eq!(big.to_string(), "493827156913580238691358020308641969");
        assert_eq!(scaled(&DecimalNatural::default(), 5).to_string(), "0");
        assert_eq!(scaled(&DecimalNatural::from_usize(5), 0).to_string(), "0");
    }

    #[test]
    fn weak_orders_enumerate_exactly_once_in_lexicographic_order() {
        for m in 0..=7usize {
            let mut points = vec![0usize; m];
            let mut seen = HashSet::new();
            let mut previous: Option<Vec<usize>> = None;
            loop {
                let used: HashSet<_> = points.iter().copied().collect();
                assert!((0..used.len()).all(|rank| used.contains(&rank)));
                if let Some(previous) = &previous {
                    assert!(*previous < points);
                }
                assert!(seen.insert(points.clone()));
                previous = Some(points.clone());
                if !next_weak_order(&mut points) {
                    break;
                }
            }
            assert!(points.iter().all(|rank| *rank == 0));
            assert_eq!(seen.len() as u128, ordered_bell(m).unwrap());
        }
    }

    #[test]
    fn values_are_the_formulas_as_written_and_absent_is_kept_apart() {
        let c = counters(652854.14, 335797.36, 100.0);
        assert_eq!(Dimension::Volume.value(c), Some(652854.14));
        assert_eq!(Dimension::Trades.value(c), Some(100.0));
        assert_eq!(Dimension::Delta.value(c), Some(2.0 * 335797.36 - 652854.14));
        assert_eq!(Dimension::Size.value(c), Some(652854.14 / 100.0));
        assert_eq!(
            Dimension::Imbalance.value(c),
            Some((2.0 * 335797.36 - 652854.14) / 652854.14)
        );
        let idle = counters(0.0, 0.0, 0.0);
        assert_eq!(Dimension::Volume.value(idle), Some(0.0));
        assert_eq!(Dimension::Trades.value(idle), Some(0.0));
        assert_eq!(Dimension::Delta.value(idle), Some(0.0));
        assert_eq!(Dimension::Size.value(idle), None);
        assert_eq!(Dimension::Imbalance.value(idle), None);
        for (volume, taker_buy, trades) in [
            (f64::NAN, 0.0, 1.0),
            (f64::INFINITY, 1.0, 1.0),
            (1.0, f64::NAN, 1.0),
            (1.0, 0.5, f64::INFINITY),
            (-1.0, 0.0, 1.0),
            (1.0, -0.5, 1.0),
            (1.0, 0.5, -1.0),
            (1000.0, 1001.0, 10.0),
            (1000.0, 600.0, 10.5),
            (1000.0, 600.0, 9_007_199_254_740_992.0),
        ] {
            assert!(Counters::new(volume, taker_buy, trades).is_err());
        }
        assert!(Counters::new(1000.0, 1000.0, 9_007_199_254_740_991.0).is_ok());
    }

    #[test]
    fn counter_text_reads_back_to_the_same_floats_and_bad_text_is_refused() {
        for value in [
            10076955.5409877f64,
            0.1 + 0.2,
            652854.14,
            1678986.8,
            1e-6,
            123456789012345.67,
            5e-324,
            1.7976931348623157e308,
        ] {
            // Rust writes the shortest text that reads back; a very small or
            // very large float is written with an exponent.
            for text in [format!("{value}"), format!("{value:e}")] {
                let read = Counters::parse(&text, "0", "7").unwrap();
                assert_eq!(read.volume().to_bits(), value.to_bits(), "{text}");
            }
        }
        let read = Counters::parse("1e3", "6.0e+2", "0010").unwrap();
        assert_eq!(
            (read.volume(), read.taker_buy_volume(), read.trades()),
            (1000.0, 600.0, 10.0)
        );
        assert_eq!(
            Counters::parse("25e-1", "0", "9007199254740991")
                .unwrap()
                .volume(),
            2.5
        );
        for (volume, taker_buy, trades) in [
            ("1000", "1001", "10"),
            ("1000", "600", "10.5"),
            ("-1", "0", "1"),
            ("NaN", "0", "1"),
            ("nan", "0", "1"),
            ("Infinity", "600", "10"),
            ("inf", "600", "10"),
            ("1e999", "600", "10"),
            ("1000", "", "10"),
            ("1000", "600", ""),
            ("1000", "600", "1e1"),
            ("1000", "600", "-1"),
            ("1000", "600", "+1"),
            ("1000", "600", "9007199254740992"),
            ("1000", "600", "99999999999999999999999999"),
            ("+1000", "600", "10"),
            ("1000 ", "600", "10"),
            (" 1000", "600", "10"),
            ("1000.", "600", "10"),
            (".5", "0", "10"),
            ("1E3", "600", "10"),
            ("1e", "0", "10"),
            ("1e+", "0", "10"),
            ("1e1.5", "0", "10"),
            ("1_000", "600", "10"),
            ("0x10", "0", "10"),
            ("1000", "6e2e1", "10"),
        ] {
            assert!(
                Counters::parse(volume, taker_buy, trades).is_err(),
                "accepted {volume:?} {taker_buy:?} {trades:?}"
            );
        }
    }

    #[test]
    fn dimension_sets_parse_any_order_and_know_their_dependent_cores() {
        let set = |text: &str| DimensionSet::parse(text).unwrap();
        assert!(set("").is_empty());
        assert!(set("  ").is_empty());
        assert_eq!(set("delta, volume").to_string(), "volume,delta");
        assert_eq!(set("volume,delta").json(), "[\"volume\",\"delta\"]");
        assert_eq!(DimensionSet::all().len(), 5);
        assert_eq!(
            DimensionSet::all().to_string(),
            "volume,trades,delta,size,imbalance"
        );
        for text in [
            "flow",
            "volume,volume",
            "volume,",
            ",volume",
            "Volume",
            "volume;delta",
        ] {
            assert!(DimensionSet::parse(text).is_err(), "accepted {text}");
        }
        assert!(!set("volume,trades,delta").includes_patterns_that_cannot_occur(9));
        assert!(!set("volume,size,delta").includes_patterns_that_cannot_occur(9));
        assert!(set("delta,imbalance").includes_patterns_that_cannot_occur(1));
        assert!(!set("delta,imbalance").includes_patterns_that_cannot_occur(0));
        assert!(set("volume,trades,size").includes_patterns_that_cannot_occur(2));
        assert!(!set("volume,trades,size").includes_patterns_that_cannot_occur(1));
        assert!(DimensionSet::all().includes_patterns_that_cannot_occur(1));
        assert!(!DimensionSet::NONE.includes_patterns_that_cannot_occur(10));
    }

    #[test]
    fn text_round_trips_and_malformed_parts_are_rejected() {
        for text in [
            "g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1",
            "g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1|delta:0,2/1",
            "g1:o:0,1,2,3,u|delta:1/0",
            "g1:u:0,1,2,3;0,1,2,3;0,1,2,3|volume:0,0,1|delta:2,0,1/1",
            "g1:o:0,1,2,3,u|volume:0|trades:0|delta:0/0|size:0|imbalance:0/1",
            "g1:u:|volume:|delta:/0",
            "g1:o:|imbalance:/0",
        ] {
            let pattern: GeometryPattern = text.parse().unwrap();
            assert_eq!(pattern.to_string(), text);
            assert!(pattern.has_dimensions());
            let key = GeometryDimensionKey::from_pattern(&pattern).unwrap();
            assert_eq!(key.to_string(), text);
            assert_eq!(key.to_pattern(), pattern);
            assert_eq!(key.dimensions(), pattern.dimension_set());
            assert_eq!(
                GeometryDimensionKey::from_words(key.price().words(), key.dimension_words())
                    .unwrap(),
                key
            );
            assert_eq!(
                key.price(),
                GeometryKey::from_pattern(&pattern.price()).unwrap()
            );
            // A price key is never a weakened dimension key.
            assert!(GeometryKey::from_pattern(&pattern).is_err());
            assert!(pattern
                .matches_ohlc(&vec![[0.0; 4]; pattern.len()])
                .is_err());
        }
        let base = "g1:o:0,1,2,3,u";
        for tail in [
            "|",
            "|volume:",
            "|volume:00",
            "|volume:0,1",
            "|volume:0/1",
            "|volume:1",
            "|delta:1",
            "|delta:0/",
            "|delta:2/0",
            "|delta:0/2",
            "|flow:0",
            "|Volume:0",
            "|volume:0|volume:0",
            "|delta:1/0|volume:0",
            "|volume:0 ",
            "|volume:-0",
            "|volume:0|",
            "|imbalance:0/0/0",
            "|volume",
            "|volume:0,",
            "|volume:,0",
            "|volume:+0",
            "|delta:0/+0",
            "|delta:0/00",
            "|delta:/0",
            "|delta:0/0 ",
            " |volume:0",
            "|volume:0|delta:0",
            "|trades:0|volume:0",
            "|imbalance:0/0|delta:0/0",
            "|volume:99999999999999999999999999",
        ] {
            let text = format!("{base}{tail}");
            assert!(text.parse::<GeometryPattern>().is_err(), "accepted {text}");
        }
        assert!("g1:o:0,1,2,3,u;4,5,6,7,u|volume:0"
            .parse::<GeometryPattern>()
            .is_err());
        assert!("g1:u:|volume:0".parse::<GeometryPattern>().is_err());
        assert!("g1:u:|delta:".parse::<GeometryPattern>().is_err());
        // A 0.9 pattern is a 0.10 pattern with no dimension on.
        let plain: GeometryPattern = "g1:o:0,1,2,3,u;4,5,6,7,d".parse().unwrap();
        assert!(!plain.has_dimensions());
        assert!(plain.dimension_set().is_empty());
        assert_eq!(plain.price(), plain);
        let key = GeometryDimensionKey::from_pattern(&plain).unwrap();
        assert!(key.dimension_words().is_empty());
        assert_eq!(key.price(), GeometryKey::from_pattern(&plain).unwrap());
        assert_eq!(key.to_string(), plain.to_string());
    }

    #[test]
    fn parts_and_patterns_reject_wrong_shapes_and_orders() {
        let part = |dimension, ranks: &[usize], reference| {
            DimensionPart::new(dimension, ranks.to_vec(), reference)
        };
        assert!(part(Dimension::Volume, &[0, 1], None).is_ok());
        assert!(part(Dimension::Volume, &[0, 2], None).is_err());
        assert!(part(Dimension::Volume, &[1, 1], None).is_err());
        assert!(part(Dimension::Volume, &[0, 1], Some(0)).is_err());
        assert!(part(Dimension::Delta, &[0, 1], None).is_err());
        assert!(part(Dimension::Delta, &[0, 2], Some(1)).is_ok());
        assert!(part(Dimension::Delta, &[0, 3], Some(1)).is_err());
        assert!(part(Dimension::Delta, &[usize::MAX], Some(0)).is_err());
        let volume = part(Dimension::Volume, &[0, 1], None).unwrap();
        let delta = part(Dimension::Delta, &[0, 2], Some(1)).unwrap();
        assert_eq!(volume.level_count(), 2);
        assert_eq!(delta.level_count(), 3);
        let price: GeometryPattern = "g1:u:0,1,2,3;0,1,2,3".parse().unwrap();
        let both = price
            .with_parts(vec![volume.clone(), delta.clone()])
            .unwrap();
        assert_eq!(
            both.to_string(),
            "g1:u:0,1,2,3;0,1,2,3|volume:0,1|delta:0,2/1"
        );
        assert_eq!(both.dimension(Dimension::Delta), Some(&delta));
        assert_eq!(both.dimension(Dimension::Size), None);
        assert_eq!(both.price(), price);
        assert!(price
            .with_parts(vec![delta.clone(), volume.clone()])
            .is_err());
        assert!(price
            .with_parts(vec![volume.clone(), volume.clone()])
            .is_err());
        let one: GeometryPattern = "g1:u:0,1,2,3".parse().unwrap();
        assert!(one.with_parts(vec![volume.clone()]).is_err());
        assert!(GeometryPattern::with_dimensions(
            vec![[0, 1, 2, 3], [0, 1, 2, 3]],
            None,
            vec![volume, delta]
        )
        .is_ok());
        // Patterns that differ only in a dimension part are different patterns
        // with different hashes and a deterministic order.
        let other: GeometryPattern = "g1:u:0,1,2,3;0,1,2,3|volume:1,0|delta:0,2/1"
            .parse()
            .unwrap();
        assert_ne!(both, other);
        assert!(both < other);
        assert!(price < both);
        let set: HashSet<_> = [price, both, other].into_iter().collect();
        assert_eq!(set.len(), 3);
    }

    #[test]
    fn key_words_have_the_documented_layout_and_reject_bad_raw_words() {
        assert_eq!(std::mem::size_of::<GeometryKey>(), 32);
        let pattern: GeometryPattern = "g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1|delta:0,2/1"
            .parse()
            .unwrap();
        let key = GeometryDimensionKey::from_pattern(&pattern).unwrap();
        let price = GeometryKey::from_pattern(&pattern.price()).unwrap();
        assert_eq!(key.price().words(), price.words());
        let volume = 1u64 << 44 | 1 << 4;
        let delta = 3u64 << 44 | 1 << 40 | 2 << 4;
        assert_eq!(key.dimension_words(), &[volume, delta]);
        let words = price.words();
        let accept = |dimension_words: &[u64]| {
            GeometryDimensionKey::from_words(words, dimension_words).is_ok()
        };
        assert!(accept(&[]));
        assert!(accept(&[volume]));
        assert!(accept(&[delta]));
        assert!(accept(&[volume, delta]));
        for bad in [
            vec![delta, volume],
            vec![volume, volume],
            vec![0],
            vec![volume, 0],
            vec![volume | 1 << 52],
            vec![volume | 1 << 63],
            vec![volume | 1 << 40],
            vec![volume | 1 << 8],
            vec![6u64 << 44 | 1 << 4],
            vec![1u64 << 44 | 2 << 4],
            vec![3u64 << 44 | 2 << 40],
            vec![3u64 << 44 | 1 << 40 | 2 << 4 | 1 << 12],
            vec![volume; 6],
        ] {
            assert!(!accept(&bad), "accepted {bad:?}");
        }
        let mut broken = words;
        broken[3] |= 1 << 63;
        assert!(GeometryDimensionKey::from_words(broken, &[volume]).is_err());
        // Ten candles, eleven distinct levels with the reference: 52 bits.
        let ranks: Vec<_> = (0..10)
            .map(|i| [4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3])
            .collect();
        let wide = GeometryPattern::with_dimensions(
            ranks,
            None,
            vec![
                DimensionPart::new(Dimension::Imbalance, (1..=10).rev().collect(), Some(0))
                    .unwrap(),
            ],
        )
        .unwrap();
        let wide_key = GeometryDimensionKey::from_pattern(&wide).unwrap();
        let word = wide_key.dimension_words()[0];
        assert_eq!(word >> 44, 5);
        assert_eq!(64 - word.leading_zeros(), 47);
        assert_eq!(word & 15, 10);
        assert_eq!((word >> 36) & 15, 1);
        assert_eq!((word >> 40) & 15, 0);
        assert_eq!(wide_key.to_pattern(), wide);
        assert_eq!(wide_key.to_string(), wide.to_string());
        // Keys order by price words first, then dimension words.
        let other: GeometryPattern = "g1:o:4,5,6,7,d;0,1,2,3,d|volume:1,0|delta:0,2/1"
            .parse()
            .unwrap();
        let other_key = GeometryDimensionKey::from_pattern(&other).unwrap();
        assert_eq!(key.price(), other_key.price());
        assert!(other_key < key);
        assert!(GeometryDimensionKey::from_pattern(&pattern.price()).unwrap() < other_key);
        let long = GeometryPattern::from_ohlc_counters(
            &[[0.0; 4]; 11],
            &[counters(1.0, 0.5, 1.0); 11],
            GeometryMode::Oriented,
            DimensionSet::parse("volume").unwrap(),
        )
        .unwrap()
        .unwrap();
        assert!(GeometryDimensionKey::from_pattern(&long).is_err());
        assert_eq!(long.to_string().parse::<GeometryPattern>().unwrap(), long);
    }

    #[test]
    fn complete_small_domains_are_unique_round_trip_and_match_their_counts() {
        let set = |text: &str| DimensionSet::parse(text).unwrap();
        for (n, mode, dimensions) in [
            (2, GeometryMode::Oriented, "volume"),
            (
                1,
                GeometryMode::Oriented,
                "volume,trades,delta,size,imbalance",
            ),
            (1, GeometryMode::Unoriented, "delta,imbalance"),
            (2, GeometryMode::Unoriented, "delta"),
            (0, GeometryMode::Oriented, "volume,delta"),
        ] {
            let dimensions = set(dimensions);
            let expected = count_domain_with_dimensions(n, mode, dimensions).unwrap() as usize;
            let patterns =
                enumerate_patterns_with_dimensions(n, mode, dimensions, usize::MAX).unwrap();
            assert_eq!(patterns.len(), expected);
            let mut keys = HashSet::new();
            let unique: HashSet<_> = patterns.iter().cloned().collect();
            assert_eq!(unique.len(), expected);
            for pattern in &patterns {
                pattern.validate().unwrap();
                assert_eq!(pattern.len(), n);
                assert_eq!(pattern.mode(), mode);
                assert_eq!(pattern.dimension_set(), dimensions);
                assert_eq!(
                    pattern.to_string().parse::<GeometryPattern>().unwrap(),
                    *pattern
                );
                let key = GeometryDimensionKey::from_pattern(pattern).unwrap();
                assert_eq!(key.to_pattern(), *pattern);
                assert_eq!(key.to_string(), pattern.to_string());
                assert_eq!(
                    GeometryDimensionKey::from_words(key.price().words(), key.dimension_words())
                        .unwrap(),
                    key
                );
                keys.insert(key);
            }
            assert_eq!(keys.len(), expected);
            // The bounded complement search finds the first pattern left out.
            let observed: HashSet<_> = patterns.iter().take(expected.min(37)).cloned().collect();
            let mut calls = 0;
            let missing = first_unobserved_with_dimensions_by(
                n,
                mode,
                dimensions,
                observed.len(),
                |pattern| {
                    calls += 1;
                    observed.contains(pattern)
                },
            )
            .unwrap();
            if observed.len() == expected {
                assert_eq!(missing, None);
            } else {
                assert_eq!(missing, Some(patterns[observed.len()].clone()));
                assert_eq!(calls, observed.len() + 1);
            }
            assert!(
                first_unobserved_with_dimensions_by(n, mode, dimensions, expected + 1, |_| false)
                    .is_err()
            );
        }
        assert_eq!(
            enumerate_patterns_with_dimensions(
                2,
                GeometryMode::Oriented,
                DimensionSet::NONE,
                usize::MAX
            )
            .unwrap(),
            enumerate_patterns(2, GeometryMode::Oriented, usize::MAX).unwrap()
        );
        assert!(
            enumerate_patterns_with_dimensions(5, GeometryMode::Oriented, set("volume"), 0)
                .unwrap()
                .is_empty()
        );
        // Nine candles with a dimension on exceed the checked-integer API.
        assert!(
            enumerate_patterns_with_dimensions(9, GeometryMode::Oriented, set("volume"), 0)
                .is_err()
        );
        assert!(first_unobserved_with_dimensions_by(
            2,
            GeometryMode::Oriented,
            set("volume"),
            1,
            |_| true
        )
        .is_err());
    }

    #[test]
    fn encoder_ranks_each_axis_alone_and_keeps_invalid_apart_from_false() {
        let mode = GeometryMode::Oriented;
        let rows = [[10.1, 10.15, 10.0, 10.02], [10.03, 10.09, 10.025, 10.08]];
        let bars = [
            counters(120000.0, 42500.0, 300.0),
            counters(480000.0, 345000.0, 900.0),
        ];
        let all = DimensionSet::all();
        let pattern = GeometryPattern::from_ohlc_counters(&rows, &bars, mode, all)
            .unwrap()
            .unwrap();
        assert_eq!(
            pattern.to_string(),
            "g1:o:0,1,6,7,d;2,3,4,5,u|volume:0,1|trades:0,1|delta:0,2/1|size:0,1|imbalance:0,2/1"
        );
        assert_eq!(
            pattern.price(),
            GeometryPattern::from_ohlc(&rows, mode).unwrap()
        );
        assert_eq!(
            pattern.matches_ohlc_counters(&rows, &bars).unwrap(),
            Some(true)
        );
        let swapped = [bars[1], bars[0]];
        assert_eq!(
            pattern.matches_ohlc_counters(&rows, &swapped).unwrap(),
            Some(false)
        );
        // A bar without trades has volume and delta but no size or imbalance.
        let idle = [bars[0], counters(0.0, 0.0, 0.0)];
        assert_eq!(pattern.matches_ohlc_counters(&rows, &idle).unwrap(), None);
        let narrow = GeometryPattern::from_ohlc_counters(
            &rows,
            &idle,
            mode,
            DimensionSet::parse("volume,trades,delta").unwrap(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(
            narrow.to_string(),
            "g1:o:0,1,6,7,d;2,3,4,5,u|volume:1,0|trades:1,0|delta:0,1/1"
        );
        for missing in ["size", "imbalance", "volume,size"] {
            assert_eq!(
                GeometryPattern::from_ohlc_counters(
                    &rows,
                    &idle,
                    mode,
                    DimensionSet::parse(missing).unwrap()
                )
                .unwrap(),
                None
            );
        }
        // Reused storage, keys equal to packed patterns, and recovery after an
        // invalid window and after an input error.
        let mut encoder = GeometryDimensionEncoder::new(2, mode, all).unwrap();
        assert_eq!(encoder.dimensions(), all);
        let pointers = |e: &GeometryDimensionEncoder| {
            (
                e.values.as_ptr(),
                e.order.as_ptr(),
                e.price.pattern.dimensions.as_ptr(),
                e.price.pattern.dimensions[4].ranks.as_ptr(),
            )
        };
        let before = pointers(&encoder);
        assert_eq!(encoder.encode_ohlc(&rows, &bars).unwrap(), Some(&pattern));
        assert_eq!(encoder.encode_ohlc(&rows, &idle).unwrap(), None);
        assert!(encoder.encode_ohlc(&rows, &bars[..1]).is_err());
        assert!(encoder
            .encode_ohlc(&[[f64::NAN; 4], rows[1]], &bars)
            .is_err());
        assert_eq!(
            encoder.encode_key_ohlc(&rows, &bars).unwrap(),
            Some(GeometryDimensionKey::from_pattern(&pattern).unwrap())
        );
        assert_eq!(encoder.encode_key_ohlc(&rows, &idle).unwrap(), None);
        assert_eq!(before, pointers(&encoder));
        let endpoints = [[10.0, 10.02, 10.1, 10.15], [10.025, 10.03, 10.08, 10.09]];
        let directions = [BodyDirection::Down, BodyDirection::Up];
        assert_eq!(
            encoder
                .encode_endpoints(&endpoints, Some(&directions), &bars)
                .unwrap(),
            Some(&pattern)
        );
        assert_eq!(
            encoder
                .encode_key_endpoints(&endpoints, Some(&directions), &bars)
                .unwrap()
                .unwrap()
                .to_pattern(),
            pattern
        );
        // With no dimension on the encoder is the price encoder.
        let mut plain = GeometryDimensionEncoder::new(2, mode, DimensionSet::NONE).unwrap();
        let mut price = GeometryEncoder::new(2, mode).unwrap();
        assert_eq!(
            plain.encode_ohlc(&rows, &idle).unwrap(),
            Some(price.encode_ohlc(&rows).unwrap())
        );
        assert_eq!(
            plain
                .encode_key_ohlc(&rows, &idle)
                .unwrap()
                .unwrap()
                .price(),
            price.encode_key_ohlc(&rows).unwrap()
        );
        // Reading a part against values agrees with encoding the values.
        let mut levels = Vec::new();
        for (candles, expected) in [(&bars, true), (&swapped, false)] {
            for part in pattern.dimensions() {
                let values: Vec<_> = candles
                    .iter()
                    .map(|candle| part.dimension().value(*candle).unwrap())
                    .collect();
                assert_eq!(part.matches_values(&values, &mut levels), expected);
                assert!(!part.matches_values(&values[..1], &mut levels));
            }
        }
        let tied = "g1:o:0,1,2,3,u;0,1,2,3,u|volume:0,0|delta:0,0/0"
            .parse::<GeometryPattern>()
            .unwrap();
        assert!(tied.dimensions()[0].matches_values(&[5.0, 5.0], &mut levels));
        assert!(!tied.dimensions()[0].matches_values(&[5.0, 6.0], &mut levels));
        assert!(tied.dimensions()[1].matches_values(&[0.0, -0.0], &mut levels));
        assert!(!tied.dimensions()[1].matches_values(&[1.0, 1.0], &mut levels));
        // A strictly increasing change of one axis's scale changes nothing.
        let scaled = [
            counters(360000.0, 127500.0, 301.0),
            counters(1440000.0, 1035000.0, 1900.0),
        ];
        let volume_delta = DimensionSet::parse("volume,trades,delta").unwrap();
        assert_eq!(
            GeometryPattern::from_ohlc_counters(&rows, &scaled, mode, volume_delta).unwrap(),
            GeometryPattern::from_ohlc_counters(&rows, &bars, mode, volume_delta).unwrap()
        );
    }
}
