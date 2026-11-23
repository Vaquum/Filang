//! Resumable Composer search over observed windows on several loaded timeframes.
use crate::{
    engine_drawing::Drawing,
    engine_json::Value,
    geometry::{
        explore::{Reading, Recording},
        matching::{boundaries, holds, AxisDistance, Difference, Exact, Hold, Shape},
    },
    study, Result,
};
use std::{
    cmp::Ordering,
    collections::{BinaryHeap, HashMap},
    fmt::Write,
    sync::Arc,
};

pub(crate) const TIMEFRAMES: [i64; 5] = [900_000, 1_800_000, 3_600_000, 7_200_000, 14_400_000];
const MAX_BARS: usize = 20;

#[derive(Clone)]
pub(crate) struct Frame {
    start_ms: i64,
    interval_ms: i64,
    recording: Recording,
    complete: Arc<[u8]>,
}

impl Frame {
    pub fn load(csv: &str, interval_ms: i64) -> Result<Self> {
        let (start_ms, recording) = study::geometry_frame(csv, interval_ms)?;
        let mut run = 0u8;
        let complete = (0..recording.len())
            .map(|slot| {
                run = if recording.candle(slot, Reading::Recorded).is_some() {
                    run.saturating_add(1)
                } else {
                    0
                };
                run
            })
            .collect::<Vec<_>>()
            .into();
        Ok(Self {
            start_ms,
            interval_ms,
            recording,
            complete,
        })
    }

    pub fn len(&self) -> usize {
        self.recording.len()
    }

    fn time(&self, start: usize) -> i64 {
        self.start_ms + start as i64 * self.interval_ms
    }

    fn candle(&self, position: usize, in_drawing: usize) -> [f64; 4] {
        let reading = if in_drawing == 0 {
            Reading::Recorded
        } else {
            Reading::Chained
        };
        self.recording
            .candle(position, reading)
            .expect("complete window")
    }

    fn complete(&self, start: usize, span: usize) -> bool {
        self.complete
            .get(start + span - 1)
            .map_or(false, |&run| usize::from(run) >= span)
    }
}

#[derive(Clone, Copy)]
struct Window {
    start: u32,
    picks: u32,
}

impl Window {
    fn consecutive(start: usize, width: usize) -> Self {
        Self {
            start: start as u32,
            picks: (1 << width) - 1,
        }
    }

    fn span(self) -> usize {
        (u32::BITS - self.picks.leading_zeros()) as usize
    }

    fn offsets(self) -> impl Iterator<Item = usize> {
        let mut bits = self.picks;
        std::iter::from_fn(move || {
            let bit = bits.trailing_zeros();
            if bit == u32::BITS {
                return None;
            }
            bits &= bits - 1;
            Some(bit as usize)
        })
    }

    fn write(self, out: &mut String, frame: &Frame) {
        let start = self.start as usize;
        let span = self.span();
        let start_ms = frame.time(start);
        let end_ms = frame.time(start + span);
        write!(out, "{{\"start\":{start},\"span\":{span},\"start_ms\":{start_ms},\"end_ms\":{end_ms},\"picks\":[")
            .expect("write position");
        for (i, position) in self.offsets().enumerate() {
            if i != 0 {
                out.push(',');
            }
            write!(out, "{position}").expect("write pick");
        }
        out.push_str("]}");
    }
}

struct Ranked {
    score: f64,
    end_ms: i64,
    order: usize,
    frame: usize,
    window: Window,
    half_flips: usize,
    off: f64,
}

impl Ord for Ranked {
    fn cmp(&self, other: &Self) -> Ordering {
        self.score
            .total_cmp(&other.score)
            .then_with(|| self.window.span().cmp(&other.window.span()))
            .then_with(|| other.end_ms.cmp(&self.end_ms))
            .then_with(|| self.order.cmp(&other.order))
    }
}
impl PartialOrd for Ranked {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Eq for Ranked {}
impl PartialEq for Ranked {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other).is_eq()
    }
}

#[derive(Default)]
struct Bucket {
    first: usize,
    example: Option<(f64, usize, Window)>,
    positions: [Vec<Window>; 5],
}

#[derive(Default)]
struct FrameMatches {
    exact: Vec<Window>,
    held: Vec<Window>,
    qualified_exact: Vec<Window>,
    qualified_held: Vec<Window>,
    within: Vec<Window>,
}

struct Placement {
    depth: usize,
    offsets: [usize; MAX_BARS],
    choices: [usize; MAX_BARS],
    colours: [usize; MAX_BARS],
    best: Option<(f64, Window, usize, f64)>,
    first: Option<Window>,
}

impl Placement {
    fn new() -> Self {
        Self {
            depth: 0,
            offsets: [0; MAX_BARS],
            choices: [0; MAX_BARS],
            colours: [0; MAX_BARS],
            best: None,
            first: None,
        }
    }
}

// A byte holds the minimum future colour cost in half-flips. At most
// twenty candles contribute, leaving 255 available for an impossible suffix.
const UNREACHABLE: u8 = u8::MAX;
struct ColourCosts {
    slots: usize,
    stride: usize,
    costs: Vec<u8>,
    own: Vec<u8>,
    tails: [Vec<u8>; 2],
    depth: usize,
    column: usize,
    slot: usize,
    ready: bool,
}

impl ColourCosts {
    fn new(slots: usize, width: usize, stretch: usize) -> Self {
        let stride = stretch + 1;
        Self {
            slots,
            stride,
            costs: vec![UNREACHABLE; slots * width * stride],
            own: vec![UNREACHABLE; slots],
            tails: std::array::from_fn(|_| vec![UNREACHABLE; slots + 1]),
            depth: width - 1,
            column: 0,
            slot: 0,
            ready: false,
        }
    }

    fn index(&self, depth: usize, spare: usize) -> usize {
        (depth * self.stride + spare) * self.slots
    }

    fn at(&self, depth: usize, spare: usize, slot: usize) -> u8 {
        self.costs[self.index(depth, spare) + slot]
    }

    fn step(
        &mut self,
        frame: &Frame,
        shape: &Shape,
        local: &[Vec<Hold>],
        mut units: usize,
    ) -> bool {
        let width = local.len();
        let mut row = [[0.0; 4]; MAX_BARS];
        while units > 0 && !self.ready {
            if self.column == 0 {
                let end = self.slot.saturating_add(units).min(self.slots);
                let reading = if self.depth == 0 {
                    Reading::Recorded
                } else {
                    Reading::Chained
                };
                for slot in self.slot..end {
                    self.own[slot] =
                        frame
                            .recording
                            .candle(slot, reading)
                            .map_or(UNREACHABLE, |value| {
                                row[self.depth] = value;
                                if local[self.depth].iter().all(|rule| rule.matches(&row)) {
                                    shape.colour_at(self.depth, value) as u8
                                } else {
                                    UNREACHABLE
                                }
                            });
                }
                units -= end - self.slot;
                self.slot = end;
                if end == self.slots {
                    self.column = 1;
                    self.slot = 0;
                }
                continue;
            }
            let spare = self.column - 1;
            let valid = if self.depth + 1 == width && spare > 0 {
                0
            } else {
                self.slots.saturating_sub(width - 1 - self.depth + spare)
            };
            let end = (self.slot + units).min(valid);
            let target = self.index(self.depth, spare);
            for slot in self.slot..end {
                let rest = if self.depth + 1 == width {
                    0
                } else {
                    let direct = self.at(self.depth + 1, spare, slot + 1);
                    if spare == 0 {
                        direct
                    } else {
                        direct.min(self.tails[(spare - 1) % 2][slot + 1])
                    }
                };
                self.tails[spare % 2][slot] = rest;
                self.costs[target + slot] = rest.saturating_add(self.own[slot]);
            }
            units -= end - self.slot;
            self.slot = end;
            if end == valid {
                // The next spare column may read the sentinel immediately after this one.
                self.tails[spare % 2][end] = UNREACHABLE;
                self.slot = 0;
                if self.column == self.stride {
                    self.column = 0;
                    if self.depth == 0 {
                        self.ready = true;
                    } else {
                        self.depth -= 1;
                    }
                } else {
                    self.column += 1;
                }
            }
        }
        self.ready
    }
}

pub(crate) struct Search {
    frames: [Option<Frame>; 5],
    selected: u8,
    end_masks: [Option<Box<[u8]>>; 5],
    radius: usize,
    shape: Shape,
    holds: Vec<Hold>,
    by_bar: Vec<Vec<Hold>>,
    local: Vec<Vec<Hold>>,
    ending_at: Vec<Vec<Hold>>,
    has_ending_rules: bool,
    first_only: bool,
    colour_costs: Option<ColourCosts>,
    span: usize,
    stretch: usize,
    limit: usize,
    best: BinaryHeap<Ranked>,
    away: HashMap<Difference, Bucket>,
    positions: [FrameMatches; 5],
    scratch: [[f64; 4]; MAX_BARS],
    endpoints: [f64; MAX_BARS * 4],
    frame: usize,
    start: usize,
    extra: usize,
    placement: Option<Placement>,
    scanned: usize,
    total: usize,
    seen: usize,
    fallback: bool,
}

impl Search {
    pub fn new(drawing: Drawing, frames: &[Option<Frame>; 5], options: &Value) -> Result<Self> {
        let selected = options.field("timeframes")?.number::<u8>()?;
        if selected == 0 || selected > 31 {
            return Err("select one or more of Composer's five timeframes".into());
        }
        for (i, frame) in frames.iter().enumerate() {
            if selected & (1 << i) != 0 && frame.is_none() {
                return Err("load every selected timeframe before searching".into());
            }
        }
        let radius = options
            .object()?
            .get("radius")
            .map_or(Ok(0), |value| value.number::<u32>())? as usize;
        let mut end_masks: [Option<Box<[u8]>>; 5] = Default::default();
        if let Some(masks) = options.object()?.get("end_masks") {
            let masks = masks.array()?;
            if masks.len() != 5 {
                return Err("provide one optional end mask per Composer timeframe".into());
            }
            for ((target, input), frame) in end_masks.iter_mut().zip(masks).zip(frames) {
                if matches!(input, Value::Null) {
                    continue;
                }
                let text = input.text()?.as_bytes();
                if frame.as_ref().map(Frame::len) != Some(text.len())
                    || text.iter().any(|&b| !matches!(b, b'0' | b'1'))
                {
                    return Err("Composer end mask must mark every slot with 0 or 1".into());
                }
                *target = Some(text.into());
            }
        }
        let span = drawing.rows.len();
        let mode = drawing.pattern.mode();
        let shape = Shape::new(&drawing.rows, &drawing.pattern)?;
        let holds = holds(&drawing.rows, &drawing.pins, drawing.skeleton, mode);
        let mut by_bar = vec![Vec::new(); span];
        let mut local = vec![Vec::new(); span];
        let mut ending_at = vec![Vec::new(); span];
        for &hold in &holds {
            by_bar[hold.last()].push(hold);
            if hold.is_local() {
                local[hold.last()].push(hold);
            } else if hold.last() + 1 == span {
                ending_at[hold.first()].push(hold);
            }
        }
        let has_ending_rules = ending_at.iter().any(|rules| !rules.is_empty());
        let first_only = !shape.has_axes() && holds.iter().all(|hold| hold.last() == 0);
        let stretch = if holds.is_empty() { 0 } else { drawing.stretch };
        let total = frames
            .iter()
            .flatten()
            .map(|frame| (frame.len() + 1).saturating_sub(span))
            .sum();
        Ok(Self {
            frames: frames.clone(),
            selected,
            end_masks,
            radius,
            shape,
            holds,
            by_bar,
            local,
            ending_at,
            has_ending_rules,
            first_only,
            colour_costs: None,
            span,
            stretch,
            limit: drawing.limit,
            best: BinaryHeap::new(),
            away: HashMap::new(),
            positions: Default::default(),
            scratch: [[0.0; 4]; MAX_BARS],
            endpoints: [0.0; MAX_BARS * 4],
            frame: 0,
            start: 0,
            extra: 0,
            placement: None,
            scanned: 0,
            total,
            seen: 0,
            fallback: false,
        })
    }

    pub fn step(&mut self, work: usize) -> bool {
        let mut remaining = work;
        let frames = self.frames.clone();
        while remaining > 0 {
            if self.frame == self.frames.len() {
                if self.fallback || self.holds.is_empty() || self.held_count() != 0 {
                    return true;
                }
                self.frame = 0;
                self.start = 0;
                self.fallback = true;
            }
            let frame = match frames[self.frame].as_ref() {
                Some(frame) if self.start + self.span <= frame.len() => frame,
                _ => {
                    self.frame += 1;
                    self.colour_costs = None;
                    self.start = 0;
                    continue;
                }
            };
            let selected = self.selected & (1 << self.frame) != 0;
            if !self.fallback && selected && self.stretch > 0 && self.span > 2 {
                let costs = self
                    .colour_costs
                    .get_or_insert_with(|| ColourCosts::new(frame.len(), self.span, self.stretch));
                if !costs.ready {
                    costs.step(frame, &self.shape, &self.local, remaining * 8);
                    return false;
                }
            }
            if !frame.complete(self.start, self.span + self.extra) {
                self.next_start();
            } else if self.fallback {
                if selected && self.qualifies(self.frame, self.start + self.span - 1) {
                    self.contiguous(frame);
                    let window = Window::consecutive(self.start, self.span);
                    if let Some(axes) = self.axes(frame, window) {
                        let colours = self.values();
                        let ends = &self.endpoints[..4 * self.span];
                        if let Some((score, flips, off)) =
                            self.shape.rank(ends, colours, axes, self.bound())
                        {
                            self.record_rank(score, flips, off, window);
                        }
                    }
                }
                self.next_start();
            } else {
                if self.extra == 0 && self.placement.is_none() {
                    self.contiguous(frame);
                    self.observe_consecutive(frame, selected);
                    if self.holds.is_empty()
                        || self.first_only
                            && self.by_bar[0]
                                .iter()
                                .any(|hold| !hold.matches(&self.scratch))
                    {
                        self.next_start();
                        remaining -= 1;
                        continue;
                    }
                }
                let mut placement = self.placement.take().unwrap_or_else(|| {
                    let mut placement = Placement::new();
                    if self.first_only {
                        let mut first = Window::consecutive(self.start, self.span);
                        first.picks &= !(1 << (self.span - 1));
                        first.picks |= 1 << (self.span + self.extra - 1);
                        placement.first = Some(first);
                    }
                    placement
                });
                let qualified = self.qualifies(self.frame, self.start + self.span + self.extra - 1);
                let rank = selected && qualified;
                if (rank || placement.first.is_none()) && self.place(frame, &mut placement, rank) {
                    self.placement = Some(placement);
                } else {
                    if let Some(window) = placement.first {
                        let matches = &mut self.positions[self.frame];
                        matches.held.push(window);
                        if qualified && self.end_masks[self.frame].is_some() {
                            matches.qualified_held.push(window);
                        }
                    }
                    if let Some((score, window, flips, off)) = placement.best {
                        self.record_rank(score, flips, off, window);
                    }
                    self.extra += 1;
                    if self.extra > self.stretch {
                        self.next_start();
                    }
                }
            }
            remaining -= 1;
        }
        false
    }

    fn next_start(&mut self) {
        self.start += 1;
        self.extra = 0;
        self.scanned += usize::from(!self.fallback);
    }

    fn contiguous(&mut self, frame: &Frame) {
        for i in 0..self.span {
            self.scratch[i] = frame.candle(self.start + i, i);
        }
    }

    fn values(&mut self) -> usize {
        for (i, &row) in self.scratch[..self.span].iter().enumerate() {
            self.endpoints[4 * i..4 * i + 4].copy_from_slice(&boundaries(row));
        }
        self.shape.colour_flips(&self.scratch[..self.span])
    }

    fn axes(&self, frame: &Frame, window: Window) -> Option<AxisDistance> {
        if !self.shape.has_axes() {
            return Some(AxisDistance::ZERO);
        }
        let mut slots = [0; MAX_BARS];
        for (i, offset) in window.offsets().enumerate() {
            slots[i] = window.start as usize + offset;
        }
        self.shape
            .axis_distance(|i, axis| frame.recording.dimension_at(slots[i], axis))
    }

    fn observe_consecutive(&mut self, frame: &Frame, selected: bool) {
        let window = Window::consecutive(self.start, self.span);
        let axes = match self.axes(frame, window) {
            Some(axes) => axes,
            None => return,
        };
        let qualified = self.qualifies(self.frame, self.start + self.span - 1);
        let colours = self.values();
        let ends = &self.endpoints[..4 * self.span];
        if self.radius > 0 && self.shape.within(ends, colours, axes, self.radius) {
            self.positions[self.frame].within.push(window);
        }
        match self.shape.exact_or_one_away(ends, colours, axes) {
            Exact::Match => {
                let matches = &mut self.positions[self.frame];
                matches.exact.push(window);
                if qualified && self.end_masks[self.frame].is_some() {
                    matches.qualified_exact.push(window);
                }
            }
            Exact::OneAway(change) if selected => {
                let (_, look) = self.shape.look(ends);
                let order = self.away.len();
                let bucket = self.away.entry(change).or_insert_with(|| Bucket {
                    first: order,
                    ..Bucket::default()
                });
                bucket.positions[self.frame].push(window);
                if bucket
                    .example
                    .map_or(true, |(previous, ..)| look < previous)
                {
                    bucket.example = Some((look, self.frame, window));
                }
            }
            _ => {}
        }
        if self.holds.is_empty() && selected && qualified {
            if let Some((score, flips, off)) = self.shape.rank(ends, colours, axes, self.bound()) {
                self.record_rank(score, flips, off, window);
            }
        }
    }

    /// Advance one placement node. The first and last pick are fixed, and
    /// later candles always read the actual previous close, even across a skip.
    fn place(&mut self, frame: &Frame, placement: &mut Placement, rank: bool) -> bool {
        let depth = placement.depth;
        let end = self.span + self.extra - 1;
        let offset = placement.choices[depth];
        let last = if depth == 0 { 0 } else { depth + self.extra };
        if offset > last {
            if depth == 0 {
                return false;
            }
            placement.depth -= 1;
            return true;
        }
        placement.choices[depth] += 1;
        let mut bound = f64::INFINITY;
        let prefix = placement.colours[depth];
        if placement.first.is_some() {
            bound = placement
                .best
                .map_or(self.bound(), |(score, ..)| score.min(self.bound()));
        }
        if let Some(costs) = &self.colour_costs {
            let spare = self.extra - (offset - depth);
            let lower = costs.at(depth, spare, self.start + offset);
            if lower == UNREACHABLE || (prefix + usize::from(lower)) as f64 / 2.0 > bound {
                return true;
            }
        }
        placement.offsets[depth] = offset;
        if depth == 0 && self.has_ending_rules {
            self.scratch[self.span - 1] = frame.candle(self.start + end, self.span - 1);
        }
        self.scratch[depth] = frame.candle(self.start + offset, depth);
        if self.by_bar[depth]
            .iter()
            .chain(&self.ending_at[depth])
            .any(|hold| !hold.matches(&self.scratch))
        {
            return true;
        }
        if depth + 1 < self.span {
            let child = depth + 1;
            placement.depth = child;
            placement.colours[child] = prefix + self.shape.colour_at(depth, self.scratch[depth]);
            placement.choices[child] = if child == self.span - 1 {
                end
            } else {
                offset + 1
            };
            return true;
        }
        let picks = placement.offsets[..self.span]
            .iter()
            .fold(0, |bits, &slot| bits | 1 << slot);
        let window = Window {
            start: self.start as u32,
            picks,
        };
        let axes = match self.axes(frame, window) {
            Some(axes) => axes,
            None => return true,
        };
        placement.first.get_or_insert(window);
        if !rank {
            return false;
        }
        let bound = placement
            .best
            .map_or(self.bound(), |(score, ..)| score.min(self.bound()));
        let colours = self.values();
        let ends = &self.endpoints[..4 * self.span];
        if let Some((score, flips, off)) = self.shape.rank(ends, colours, axes, bound) {
            if placement.best.map_or(true, |(current, ..)| score < current) {
                placement.best = Some((score, window, flips, off));
            }
        }
        true
    }

    fn bound(&self) -> f64 {
        if self.best.len() < self.rank_capacity() {
            f64::INFINITY
        } else {
            self.best.peek().expect("full rank heap").score
        }
    }

    fn rank_capacity(&self) -> usize {
        (self.limit * 40).max(400)
    }

    fn record_rank(&mut self, score: f64, half_flips: usize, off: f64, window: Window) {
        let frame = self.frames[self.frame].as_ref().expect("ranked frame");
        let ranked = Ranked {
            score,
            end_ms: frame.time(window.start as usize + window.span()),
            order: self.seen,
            frame: self.frame,
            window,
            half_flips,
            off,
        };
        if self.best.len() >= self.rank_capacity() {
            if self.best.peek().map_or(false, |worst| &ranked >= worst) {
                return;
            }
            self.best.pop();
        }
        self.best.push(ranked);
        self.seen += 1;
    }

    fn within(&self, frame: usize) -> &[Window] {
        if self.radius == 0 {
            &self.positions[frame].exact
        } else {
            &self.positions[frame].within
        }
    }

    fn qualifies(&self, frame: usize, end: usize) -> bool {
        self.end_masks[frame]
            .as_ref()
            .map_or(true, |mask| mask[end] == b'1')
    }

    fn qualified(&self, frame: usize, held: bool) -> &[Window] {
        let matches = &self.positions[frame];
        match (self.end_masks[frame].is_some(), held) {
            (true, true) => &matches.qualified_held,
            (true, false) => &matches.qualified_exact,
            (false, true) => &matches.held,
            (false, false) => &matches.exact,
        }
    }

    fn held_count(&self) -> usize {
        (0..5)
            .filter(|&frame| self.selected & (1 << frame) != 0)
            .map(|frame| self.qualified(frame, true).len())
            .sum()
    }

    fn top_near(&self) -> Vec<(&Difference, &Bucket, usize)> {
        let mut buckets: Vec<_> = self
            .away
            .iter()
            .map(|(diff, bucket)| (diff, bucket, bucket.positions.iter().map(Vec::len).sum()))
            .collect();
        buckets.sort_unstable_by_key(|(_, bucket, n)| (std::cmp::Reverse(*n), bucket.first));
        buckets.truncate(6);
        buckets
    }

    pub fn positions(&self, frame: usize, kind: &str, from: usize, limit: usize) -> Result<String> {
        if from > u32::MAX as usize || limit > 4096 {
            return Err("invalid Composer position page".into());
        }
        let tape = self.frames[frame]
            .as_ref()
            .ok_or("load the requested timeframe first")?;
        let positions = match kind {
            "exact" => &self.positions[frame].exact,
            "held" => &self.positions[frame].held,
            "within" => self.within(frame),
            "qualified-exact" => self.qualified(frame, false),
            "qualified-held" => self.qualified(frame, true),
            _ => {
                let index: usize = kind
                    .strip_prefix("near:")
                    .and_then(|n| n.parse().ok())
                    .ok_or("invalid Composer position kind")?;
                &self
                    .top_near()
                    .get(index)
                    .ok_or("no such one-away result")?
                    .1
                    .positions[frame]
            }
        };
        let first = from.min(positions.len());
        let end = (first + limit).min(positions.len());
        let mut out = String::from("{\"positions\":[");
        for (i, window) in positions[first..end].iter().enumerate() {
            if i != 0 {
                out.push(',');
            }
            window.write(&mut out, tape);
        }
        let next = if end < positions.len() {
            end.to_string()
        } else {
            "null".into()
        };
        write!(out, "],\"next\":{next},\"total\":{}}}", positions.len())
            .expect("write position page");
        Ok(out)
    }

    pub fn reply(&self, done: bool) -> String {
        if !done {
            return format!(
                "{{\"done\":false,\"scanned\":{},\"total\":{}}}",
                self.scanned, self.total
            );
        }
        let mode = if self.fallback {
            "fallback"
        } else if self.holds.is_empty() {
            "nearest"
        } else {
            "held"
        };
        let exact: [usize; 5] = std::array::from_fn(|i| self.positions[i].exact.len());
        let held: [usize; 5] = std::array::from_fn(|i| self.positions[i].held.len());
        let qualified_exact: [usize; 5] = std::array::from_fn(|i| self.qualified(i, false).len());
        let qualified_held: [usize; 5] = std::array::from_fn(|i| self.qualified(i, true).len());
        let band = if self.radius > 0 {
            let within: [usize; 5] = std::array::from_fn(|i| self.within(i).len());
            format!(",\"within\":{within:?}")
        } else {
            String::new()
        };
        let mut out = format!(
            "{{\"done\":true,\"mode\":\"{mode}\",\"exact\":{exact:?},\"held\":{held:?},\"qualified_exact\":{qualified_exact:?},\"qualified_held\":{qualified_held:?}{band},\"results\":["
        );
        let mut ranked: Vec<_> = self.best.iter().collect();
        ranked.sort_unstable();
        let mut times = Vec::<(i64, i64)>::new();
        for r in ranked {
            let frame = self.frames[r.frame].as_ref().expect("ranked frame");
            let first = r.window.start as usize;
            let a = frame.time(first);
            let b = frame.time(first + r.window.span());
            if times.iter().any(|&(x, y)| a < y && b > x) {
                continue;
            }
            if !times.is_empty() {
                out.push(',');
            }
            times.push((a, b));
            let mut broken = Vec::new();
            if self.fallback {
                let rows: Vec<_> = r
                    .window
                    .offsets()
                    .enumerate()
                    .map(|(i, p)| frame.candle(first + p, i))
                    .collect();
                broken.extend(
                    self.holds
                        .iter()
                        .enumerate()
                        .filter_map(|(i, h)| (!h.matches(&rows)).then_some(i)),
                );
            }
            write!(out, "{{\"timeframe\":{},\"score\":{},\"half_flips\":{},\"off\":{},\"broken\":{broken:?},\"window\":",
                frame.interval_ms, r.score, r.half_flips, r.off).expect("write ranked window");
            r.window.write(&mut out, frame);
            out.push('}');
            if times.len() == self.limit {
                break;
            }
        }
        out.push_str("],\"near\":[");
        for (index, (diff, bucket, n)) in self.top_near().into_iter().enumerate() {
            if index != 0 {
                out.push(',');
            }
            let (_, k, w) = bucket.example.expect("populated near bucket");
            let frame = self.frames[k].as_ref().expect("example frame");
            let axis = diff
                .axis
                .map_or_else(String::new, |name| format!("\"axis\":\"{name}\","));
            write!(out, "{{{axis}\"a\":{},\"b\":{},\"was\":{},\"relation\":{},\"count\":{n},\"timeframe\":{},\"example\":",
                diff.left, diff.right, diff.expected, diff.observed, frame.interval_ms).expect("write neighbour");
            w.write(&mut out, frame);
            out.push('}');
        }
        out.push_str("]}");
        out
    }
}

#[cfg(test)]
mod tests {
    use crate::{engine_json, engine_session::Session};

    #[test]
    fn equal_scores_retain_the_latest_distinct_windows_beyond_heap_capacity() {
        use std::fmt::Write;

        let interval = 900_000;
        let mut session = Session::default();
        let mut csv = format!("composer-load\n{interval}\nopen_ms,open,high,low,close,volume\n");
        for i in 0..800 {
            writeln!(
                csv,
                "{},100.00,120.00,75.00,100.00,1",
                i64::from(i) * interval
            )
            .unwrap();
        }
        session.call(csv.as_bytes()).unwrap();
        let packet = r#"{"version":1,"revision":"133e3017ba9143f7dc255df7218ff7bfe46d9d06","oriented":true,
            "bars":[{"v":[75,100,100,120],"d":"u"},{"v":[75,100,100,120],"d":"u"}],
            "pins":[],"skeleton":0,"stretch":0,"limit":12,"next":{"dir":0,"measure":"any","bps":10,"atr":1}}"#;
        session
            .call(format!("composer-start\n{{\"timeframes\":1}}\n{packet}").as_bytes())
            .unwrap();
        let reply = session.call(b"composer-step\n1024").unwrap();
        let result = engine_json::parse(&reply).unwrap();
        let rows = result.field("results").unwrap().array().unwrap();
        let starts: Vec<usize> = rows
            .iter()
            .map(|r| {
                r.field("window")
                    .unwrap()
                    .field("start")
                    .unwrap()
                    .number()
                    .unwrap()
            })
            .collect();
        assert_eq!(starts, (0..12).map(|i| 798 - i * 2).collect::<Vec<_>>());
    }
}
