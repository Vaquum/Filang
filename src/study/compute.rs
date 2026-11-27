use super::{
    candles::{median_sums, prior_medians, reclaims},
    plan::{Node, Plan},
    tape::{Calendar, Tape, DAYS, TRENDS},
};
use crate::{
    geometry::{
        explore::{PreparedGeometry, Reading, Recording},
        Dimension, GeometryEncoder, GeometryKey, GeometryMode, GeometryPattern,
        GEOMETRY_KEY_MAX_BARS,
    },
    rules::Mask,
    Result,
};
use std::{
    collections::{HashMap, VecDeque},
    hash::Hash,
    rc::Rc,
};

const BUDGET: usize = 64 * 1024 * 1024;

pub(super) enum Series {
    Bool(Mask),
    Category(Vec<u8>),
    Prices(Vec<i64>),
    Axis(Vec<f64>),
    Reclaim(Mask, Vec<u32>, usize),
}

impl Series {
    pub fn mask(&self) -> Result<&Mask> {
        match self {
            Self::Bool(m) | Self::Reclaim(m, _, _) => Ok(m),
            _ => Err("plan expected Boolean series".into()),
        }
    }

    fn category(&self) -> Result<&[u8]> {
        match self {
            Self::Category(s) => Ok(s),
            _ => Err("plan expected categorical series".into()),
        }
    }

    pub(super) fn prices(&self) -> Result<&[i64]> {
        match self {
            Self::Prices(xs) => Ok(xs),
            _ => Err("plan expected a price series".into()),
        }
    }

    pub(super) fn axis(&self) -> Result<&[f64]> {
        match self {
            Self::Axis(values) => Ok(values),
            _ => Err("plan expected dimension values".into()),
        }
    }

    pub fn reclaim(&self, slot: usize, series: &[Series]) -> Result<Option<(usize, i64)>> {
        if let Self::Reclaim(_, witnesses, reference) = self {
            let breach = witnesses[slot];
            if breach != u32::MAX {
                let j = breach as usize;
                return Ok(Some((j, series[*reference].prices()?[j])));
            }
        }
        Ok(None)
    }

    pub fn group(&self, slot: usize) -> &'static str {
        match self {
            Self::Bool(mask) | Self::Reclaim(mask, _, _) => match mask.at(slot) {
                (true, true) => "true",
                (false, true) => "false",
                (_, false) => "unknown",
            },
            Self::Prices(_) | Self::Axis(_) => "unknown",
            Self::Category(s) => match s[slot] {
                x @ 0..=5 => DAYS[x as usize],
                x @ 6..=8 => TRENDS[(x - 6) as usize],
                _ => "unknown",
            },
        }
    }
}

/// Strong Kleene over packed truth and validity. Research masks keep their
/// conservative validity contract. A bit outside validity is always zero.
fn join(out: &mut Mask, rhs: &Mask, and: bool) {
    for i in 0..out.bits.len() {
        let (a, b) = (out.bits[i], rhs.bits[i]);
        let af = out.valid[i] & !a;
        let bf = rhs.valid[i] & !b;
        let (yes, no) = if and {
            (a & b, af | bf)
        } else {
            (a | b, af & bf)
        };
        out.bits[i] = yes;
        out.valid[i] = yes | no;
    }
}

type Envelope = Option<(i64, i64)>;
type Key = Option<GeometryKey>;

pub(super) struct Eval<'a> {
    pub tape: &'a Tape,
    calendar: &'a Calendar,
    windows: HashMap<usize, Rc<Vec<Envelope>>>,
    // by window length, orientation and reading (as recorded or chained): the two readings never share keys
    keys: HashMap<(usize, bool, bool), Rc<Vec<Key>>>,
    radius_indexes: HashMap<usize, PreparedGeometry>,
    radius_recording: Option<Recording>,
    // one value per slot on a dimension, NaN where the bar or the value is absent
    dimensions: HashMap<Dimension, Rc<Vec<f64>>>,
    medians: HashMap<usize, Rc<Vec<i64>>>,
    axis_medians: HashMap<(Dimension, usize), Rc<Vec<f64>>>,
    used: usize,
    pub rolling_windows: usize,
    pub geometry_windows: usize,
}

impl<'a> Eval<'a> {
    pub fn new(tape: &'a Tape, calendar: &'a Calendar) -> Self {
        Self {
            tape,
            calendar,
            windows: HashMap::new(),
            keys: HashMap::new(),
            radius_indexes: HashMap::new(),
            radius_recording: None,
            dimensions: HashMap::new(),
            medians: HashMap::new(),
            axis_medians: HashMap::new(),
            used: 0,
            rolling_windows: 0,
            geometry_windows: 0,
        }
    }

    pub fn median_windows(&self) -> usize {
        self.medians.len() + self.axis_medians.len()
    }

    pub(super) fn envelope_at(&self, window: usize, slot: usize) -> Envelope {
        self.windows
            .get(&window)
            .and_then(|values| values.get(slot).copied().flatten())
    }

    pub(super) fn median_at(&self, window: usize, slot: usize) -> i64 {
        self.medians.get(&window).map_or(0, |values| values[slot])
    }

    pub(super) fn axis_median_at(&self, dimension: Dimension, window: usize, slot: usize) -> f64 {
        self.axis_medians
            .get(&(dimension, window))
            .map_or(f64::NAN, |values| values[slot])
    }

    fn charge(&mut self, bytes: usize) -> Result<()> {
        self.used += bytes;
        if self.used > BUDGET {
            return Err("study series exceed 64 MiB; narrow the input or batch".into());
        }
        Ok(())
    }

    pub fn series(&mut self, plan: &Plan) -> Result<Vec<Series>> {
        let nodes = plan.nodes();
        let mut out = Vec::with_capacity(nodes.len());
        let n = self.tape.bars.len();
        for node in nodes {
            self.charge(match node {
                Node::Weekday | Node::Trend(_) | Node::Category(_) => n,
                Node::Price(..) | Node::Prior(..) => n * std::mem::size_of::<i64>(),
                Node::Axis(..) | Node::AxisPrior(..) | Node::AxisZero => {
                    n * std::mem::size_of::<f64>()
                }
                Node::Reclaim(..) => n * std::mem::size_of::<u32>() + ((n + 63) / 64) * 16,
                _ => Mask::empty(0).payload() + ((n + 63) / 64) * 16,
            })?;
            out.push(self.eval(node, &out)?);
        }
        Ok(out)
    }

    fn mask(&self, mut rule: impl FnMut(usize) -> Option<bool>) -> Series {
        let n = self.tape.bars.len();
        let mut m = Mask::empty(n);
        for i in 0..n {
            if let Some(result) = rule(i) {
                m.set(i, result, true);
            }
        }
        Series::Bool(m)
    }

    fn eval(&mut self, node: &Node, series: &[Series]) -> Result<Series> {
        let tape = self.tape;
        let n = tape.bars.len();
        Ok(match node {
            Node::Pattern(rule) => {
                self.mask(|i| rule.eval(tape.bars[i]?, i.checked_sub(1).and_then(|j| tape.bars[j])))
            }
            Node::Geometry(pattern, chained) => self.geometry(pattern, *chained)?,
            Node::GeometryWithin(pattern, chained, radius) => {
                self.geometry_within(pattern, *chained, *radius)?
            }
            Node::Price(field, lag) => Series::Prices(
                (0..n)
                    .map(|i| {
                        i.checked_sub(*lag)
                            .and_then(|j| tape.bars[j])
                            .map_or(0, |b| field.value(b))
                    })
                    .collect(),
            ),
            Node::Prior(window, high) => {
                let extremes = self.envelope(*window)?;
                Series::Prices(
                    (0..n)
                        .map(|i| {
                            if i < *window || !tape.complete(i - window, i) {
                                return 0;
                            }
                            if let Some((low, hi)) = extremes[i - 1] {
                                if *high {
                                    hi
                                } else {
                                    low
                                }
                            } else {
                                0
                            }
                        })
                        .collect(),
                )
            }
            Node::Axis(dimension, lag) => {
                let values = self.dimension(*dimension)?;
                let positions = (0..n).map(|i| {
                    i.checked_sub(*lag)
                        .map_or(f64::NAN, |source| values[source])
                });
                Series::Axis(positions.collect())
            }
            Node::AxisPrior(dimension, window, high) => {
                let values = self.dimension(*dimension)?;
                Series::Axis(prior_axis(&values, *window, *high))
            }
            Node::AxisZero => Series::Axis(vec![0.0; n]),
            Node::AxisRelate(left, cmp, right) => {
                let (a, b) = (series[left.index()].axis()?, series[right.index()].axis()?);
                self.mask(|i| {
                    tape.bars[i]?;
                    (a[i].is_finite() && b[i].is_finite()).then(|| cmp.test(a[i], b[i]))
                })
            }
            Node::AxisMultiple(dimension, window, min, max) => {
                let values = self.dimension(*dimension)?;
                let key = (*dimension, *window);
                let med = match self.axis_medians.get(&key) {
                    Some(values) => Rc::clone(values),
                    None => {
                        self.charge(n * std::mem::size_of::<f64>())?;
                        let span = |i: usize| (!values[i].is_nan()).then_some(values[i]);
                        let med = median_sums(n, *window, span, f64::NAN);
                        store(&mut self.axis_medians, key, med)
                    }
                };
                self.mask(|i| {
                    if med[i].is_nan() || med[i] <= 0.0 || values[i].is_nan() {
                        return None;
                    }
                    let twice = 2.0 * values[i];
                    Some(twice >= min * med[i] && max.map_or(true, |max| twice <= max * med[i]))
                })
            }
            Node::Relate(left, cmp, right) => {
                let (a, b) = (
                    series[left.index()].prices()?,
                    series[right.index()].prices()?,
                );
                self.mask(|i| {
                    if a[i] == 0 || b[i] == 0 {
                        return None;
                    }
                    // Exact prices are integers within the binary64 exact range.
                    Some(cmp.test(a[i] as f64, b[i] as f64))
                })
            }
            Node::Near(reference, point, ratio) => {
                let (a, b) = (
                    series[reference.index()].prices()?,
                    series[point.index()].prices()?,
                );
                self.mask(|i| {
                    if a[i] == 0 || b[i] == 0 {
                        return None;
                    }
                    Some(!ratio.compare((b[i] - a[i]).abs(), a[i]).is_gt())
                })
            }
            Node::Share(part, lag, min, max) => self.mask(|i| {
                let b = tape.bars[i.checked_sub(*lag)?]?;
                let span = b.h - b.l;
                if span == 0 {
                    return None;
                }
                let share = part.value(b);
                Some(!min.compare(share, span).is_lt() && !max.compare(share, span).is_gt())
            }),
            Node::Multiple(window, min, max) => {
                let med = match self.medians.get(window) {
                    Some(xs) => Rc::clone(xs),
                    None => {
                        self.charge(n * std::mem::size_of::<i64>())?;
                        store(&mut self.medians, *window, prior_medians(tape, *window))
                    }
                };
                self.mask(|i| {
                    let b = tape.bars[i]?;
                    let value = 2 * (b.h - b.l);
                    if med[i] == 0 {
                        return None;
                    }
                    Some(
                        !min.compare(value, med[i]).is_lt()
                            && max
                                .as_ref()
                                .map_or(true, |r| !r.compare(value, med[i]).is_gt()),
                    )
                })
            }
            Node::Window(inner, bars) => {
                let input = series[inner.index()].mask()?;
                self.mask(|i| {
                    if i + 1 < *bars || !tape.complete(i + 1 - bars, i + 1) {
                        return None;
                    }
                    let (value, known) = input.at(i);
                    known.then_some(value)
                })
            }
            Node::Reclaim(reference, min, max, high) => {
                let (mask, breaches) =
                    reclaims(tape, series[reference.index()].prices()?, *min, *max, *high);
                Series::Reclaim(mask, breaches, reference.index())
            }
            Node::Wick(body, wick) => self.mask(|i| {
                let b = tape.bars[i]?;
                let span = b.h - b.l;
                Some(
                    span > 0
                        && !body.compare(b.body(), span).is_gt()
                        && !wick.compare(b.o.min(b.c) - b.l, span).is_lt(),
                )
            }),
            Node::Breakout(w) => {
                let extrema = self.envelope(*w)?;
                self.mask(|i| {
                    let close = tape.bars[i]?.c;
                    let (_, high) = extrema[i.checked_sub(1)?]?;
                    if close <= high {
                        Some(false)
                    } else if i >= *w && tape.complete(i - *w, i) {
                        Some(true)
                    } else {
                        None
                    }
                })
            }
            Node::Range(w, ratio) => {
                let extrema = self.envelope(*w)?;
                self.mask(|i| {
                    let close = tape.bars[i]?.c;
                    let (low, high) = extrema[i]?;
                    if ratio.compare(high - low, close).is_gt() {
                        Some(false)
                    } else if i + 1 >= *w && tape.complete(i + 1 - *w, i + 1) {
                        Some(true)
                    } else {
                        None
                    }
                })
            }
            Node::Held(child, steps) => {
                let m = series[child.index()].mask()?;
                let (mut last_false, mut last_unknown) = (0, 0);
                self.mask(|i| {
                    let (value, valid) = m.at(i);
                    if !valid {
                        last_unknown = i + 1;
                    } else if !value {
                        last_false = i + 1;
                    }
                    let first = (i + 2).saturating_sub(*steps);
                    if last_false >= first.max(1) {
                        Some(false)
                    } else if first == 0 || last_unknown >= first {
                        None
                    } else {
                        Some(true)
                    }
                })
            }
            Node::Weekday => Series::Category(
                (0..n)
                    .map(|i| self.calendar.weekday(tape.close(i)).unwrap_or(255))
                    .collect(),
            ),
            Node::Tail(d) => self.mask(|i| self.calendar.tail(tape.close(i), *d)),
            Node::Trend(frame) => Series::Category(
                (0..n)
                    .map(|i| trend(tape, i, *frame).unwrap_or(255))
                    .collect(),
            ),
            Node::Category(v) => Series::Category(vec![*v; n]),
            Node::Equal(a, b, eq) => {
                let a = series[a.index()].category()?;
                let b = series[b.index()].category()?;
                self.mask(|i| (a[i] != 255 && b[i] != 255).then(|| (a[i] == b[i]) == *eq))
            }
            Node::Not(id) => Series::Bool(series[id.index()].mask()?.not()),
            Node::Logic(items, and) => {
                let mut out = series[items[0].index()].mask()?.clone();
                for &ref_id in &items[1..] {
                    join(&mut out, series[ref_id.index()].mask()?, *and);
                }
                Series::Bool(out)
            }
        })
    }

    fn envelope(&mut self, window: usize) -> Result<Rc<Vec<Envelope>>> {
        if let Some(cached) = self.windows.get(&window) {
            return Ok(Rc::clone(cached));
        }
        self.charge(self.tape.bars.len() * std::mem::size_of::<Envelope>())?;
        let (mut high, mut low) = (VecDeque::new(), VecDeque::new());
        let out = self
            .tape
            .bars
            .iter()
            .enumerate()
            .map(|(i, b)| {
                let start = (i + 1).saturating_sub(window);
                push_extreme(&mut low, i, start, b.map(|b| b.l), true);
                push_extreme(&mut high, i, start, b.map(|b| b.h), false);
                Some((low.front()?.1, high.front()?.1))
            })
            .collect();
        self.rolling_windows += 1;
        Ok(store(&mut self.windows, window, out))
    }

    fn dimension(&mut self, dimension: Dimension) -> Result<Rc<Vec<f64>>> {
        if let Some(values) = self.dimensions.get(&dimension) {
            return Ok(Rc::clone(values));
        }
        let values = self
            .tape
            .dimension(dimension)
            .ok_or("this recording carries no counters, so a dimension cannot be read")?;
        self.charge(self.tape.bars.len() * std::mem::size_of::<f64>())?;
        Ok(store(&mut self.dimensions, dimension, values))
    }

    /// A code with dimensions on. Its price part is read as a code with none
    /// on is read, sharing that preparation. Then, on every complete window:
    /// a candle with no value on one of the code's dimensions makes the
    /// window unknown whatever its prices say; otherwise the window matches
    /// when its prices match and its values stand in each part's order.
    /// Reading the window as a chain changes price points only.
    fn geometry_with_dimensions(
        &mut self,
        pattern: &GeometryPattern,
        chained: bool,
    ) -> Result<Series> {
        let mut series = Vec::with_capacity(pattern.dimensions().len());
        for part in pattern.dimensions() {
            let values = self.dimension(part.dimension())?;
            series.push(values);
        }
        let price = match self.geometry(&pattern.price(), chained)? {
            Series::Bool(mask) => mask,
            _ => return Err("plan expected Boolean series".into()),
        };
        let w = pattern.len();
        let mut levels = Vec::new();
        Ok(self.mask(|i| {
            let (matched, known) = price.at(i);
            if !known {
                return None;
            }
            let window = i + 1 - w..i + 1;
            if series
                .iter()
                .any(|values| values[window.clone()].iter().any(|x| x.is_nan()))
            {
                return None;
            }
            Some(
                matched
                    && pattern
                        .dimensions()
                        .iter()
                        .zip(&series)
                        .all(|(part, values)| {
                            part.matches_values(&values[window.clone()], &mut levels)
                        }),
            )
        }))
    }

    fn geometry_within(
        &mut self,
        pattern: &GeometryPattern,
        chained: bool,
        radius: u32,
    ) -> Result<Series> {
        if self.radius_recording.is_none() {
            self.radius_recording = Some(self.tape.geometry_recording()?);
        }
        let width = pattern.len();
        let prepared = match self.radius_indexes.entry(width) {
            std::collections::hash_map::Entry::Occupied(entry) => entry.into_mut(),
            std::collections::hash_map::Entry::Vacant(entry) => {
                let recording = self.radius_recording.as_ref().expect("prepared recording");
                self.geometry_windows += 1;
                entry.insert(recording.prepare(width)?)
            }
        };
        let reading = if chained {
            Reading::Chained
        } else {
            Reading::Recorded
        };
        let (bits, valid) = prepared.within_masks(pattern, reading, radius)?;
        Ok(Series::Bool(Mask {
            bits,
            valid,
            len: self.tape.bars.len(),
        }))
    }

    fn geometry(&mut self, pattern: &GeometryPattern, chained: bool) -> Result<Series> {
        if pattern.has_dimensions() {
            return self.geometry_with_dimensions(pattern, chained);
        }
        let w = pattern.len();
        let tape = self.tape;
        if w > tape.bars.len() {
            return Ok(Series::Bool(Mask::empty(tape.bars.len())));
        }
        let oriented = pattern.mode() == GeometryMode::Oriented;
        if w <= GEOMETRY_KEY_MAX_BARS {
            let coordinate = (w, oriented, chained);
            let keys = match self.keys.get(&coordinate) {
                Some(keys) => Rc::clone(keys),
                None => {
                    self.charge(tape.bars.len() * std::mem::size_of::<Key>())?;
                    let mut enc = GeometryEncoder::new(w, pattern.mode())?;
                    let mut rows = vec![[0.0; 4]; w];
                    let mut keys = vec![None; tape.bars.len()];
                    for (end, slot) in keys.iter_mut().enumerate().skip(w - 1) {
                        if load(tape, end + 1, &mut rows, chained) {
                            *slot = Some(enc.encode_key_ohlc(&rows)?);
                        }
                    }
                    self.geometry_windows += 1;
                    store(&mut self.keys, coordinate, keys)
                }
            };
            let wanted = GeometryKey::from_pattern(pattern)?;
            Ok(self.mask(|i| keys[i].map(|k| k == wanted)))
        } else {
            let mut m = Mask::empty(tape.bars.len());
            let mut rows = vec![[0.0; 4]; w];
            let mut enc = GeometryEncoder::new(w, pattern.mode())?;
            for i in w - 1..tape.bars.len() {
                if load(tape, i + 1, &mut rows, chained) {
                    m.set(i, enc.encode_ohlc(&rows)? == pattern, true);
                }
            }
            self.geometry_windows += 1;
            Ok(Series::Bool(m))
        }
    }
}

fn store<K: Hash + Eq, T>(map: &mut HashMap<K, Rc<Vec<T>>>, key: K, data: Vec<T>) -> Rc<Vec<T>> {
    let data = Rc::new(data);
    map.insert(key, Rc::clone(&data));
    data
}

fn prior_axis(values: &[f64], width: usize, high: bool) -> Vec<f64> {
    let mut queue = VecDeque::new();
    let mut run = 0;
    values
        .iter()
        .enumerate()
        .map(|(i, &value)| {
            let result = if run >= width {
                queue.front().map_or(f64::NAN, |(_, value)| *value)
            } else {
                f64::NAN
            };
            if value.is_nan() {
                queue.clear();
                run = 0;
            } else {
                run += 1;
                let next_start = (i + 1).saturating_sub(width);
                push_extreme(&mut queue, i, next_start, Some(value), !high);
            }
            result
        })
        .collect()
}

fn push_extreme<T: Copy + PartialOrd>(
    q: &mut VecDeque<(usize, T)>,
    i: usize,
    start: usize,
    v: Option<T>,
    min: bool,
) {
    if q.front().map_or(false, |x| x.0 < start) {
        q.pop_front();
    }
    if let Some(v) = v {
        while q
            .back()
            .map_or(false, |x| if min { x.1 >= v } else { x.1 <= v })
        {
            q.pop_back();
        }
        q.push_back((i, v));
    }
}

/// Loads the window ending before `end` as open, high, low, close rows. Read as recorded, each row is the bar.
/// Read as a chain, the first bar is as recorded and every later bar opens at the close of the bar before it,
/// with its low and high widened to include that open, so its body always lies inside them.
fn load(tape: &Tape, end: usize, rows: &mut [[f64; 4]], chained: bool) -> bool {
    let start = end - rows.len();
    if !tape.complete(start, end) {
        return false;
    }
    let reading = if chained {
        Reading::Chained
    } else {
        Reading::Recorded
    };
    let mut previous = None;
    for (row, bar) in rows.iter_mut().zip(&tape.bars[start..end]) {
        let bar = bar.expect("complete window");
        *row = reading.candle(bar.prices(), previous);
        previous = Some(bar.c as f64);
    }
    true
}

fn trend(tape: &Tape, slot: usize, frame: i64) -> Option<u8> {
    let t = tape.close(slot);
    let end = t / frame * frame;
    let start = end - frame;
    if start < tape.start {
        return None;
    }
    let a = ((start - tape.start) / tape.interval) as usize;
    let b = ((end - tape.start) / tape.interval) as usize;
    if !tape.complete(a, b) {
        return None;
    }
    match tape.bars[b - 1]?.c.cmp(&tape.bars[a]?.o) {
        std::cmp::Ordering::Greater => Some(6),
        std::cmp::Ordering::Less => Some(7),
        std::cmp::Ordering::Equal => Some(8),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn study_logic_preserves_decisive_values_with_unknowns() {
        let truths = [None, Some(false), Some(true)];
        for a in truths {
            for b in truths {
                let mut left = Mask::empty(1);
                let mut right = Mask::empty(1);
                if let Some(a) = a {
                    left.set(0, a, true);
                }
                if let Some(b) = b {
                    right.set(0, b, true);
                }
                for and in [true, false] {
                    let pick = !and;
                    let expected = if a == Some(pick) || b == Some(pick) {
                        Some(pick)
                    } else if a.is_none() || b.is_none() {
                        None
                    } else {
                        Some(!pick)
                    };
                    let mut out = left.clone();
                    join(&mut out, &right, and);
                    let (value, known) = out.at(0);
                    assert_eq!(known.then_some(value), expected);
                }
            }
        }
    }
}
