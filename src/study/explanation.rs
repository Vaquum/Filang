//! Close-local explanations of the shared evaluator's observations.
use super::{
    compute::{Eval, Series},
    plan::Node,
    predicate::Field,
    tape::Tape,
};
use crate::{
    geometry::{
        explore::{distance, Reading},
        GeometryPattern,
    },
    rules::Cmp,
    Result,
};

pub(super) struct Explain<'a> {
    pub eval: &'a Eval<'a>,
    pub nodes: &'a [Node],
    pub series: &'a [Series],
}

impl Explain<'_> {
    pub fn at(&self, id: usize, slot: usize) -> Result<String> {
        self.explain(id, slot, &mut 128)
    }

    fn explain(&self, id: usize, i: usize, remaining: &mut usize) -> Result<String> {
        let state = self.series[id].group(i);
        if *remaining == 0 {
            return Ok(format!("Result at this close: {state}."));
        }
        *remaining -= 1;
        let tape = self.eval.tape;
        let t = tape.close(i);
        let bar = tape.bars[i];
        let reason = match &self.nodes[id] {
            Node::Wick(body_max, wick_min) => match bar {
                None => "bar absent from the recording".into(),
                Some(bar) if bar.h == bar.l => "zero range (high = low)".into(),
                Some(bar) => {
                    let range = bar.h - bar.l;
                    let body = bar.body();
                    let wick = bar.o.min(bar.c) - bar.l;
                    let body_cmp = if body_max.compare(body, range).is_gt() {
                        ">"
                    } else {
                        "≤"
                    };
                    let wick_cmp = if wick_min.compare(wick, range).is_lt() {
                        "<"
                    } else {
                        "≥"
                    };
                    format!(
                        "range {}; body {} = {:.1}% ({body_cmp} maximum); lower wick {} = {:.1}% ({wick_cmp} minimum)",
                        cents(range), cents(body), percentage(body, range), cents(wick), percentage(wick, range)
                    )
                }
            },
            Node::Breakout(width) => self.breakout(i, *width, state),
            Node::Geometry(wanted, chained) => self.geometry(i, wanted, *chained, 0, state)?,
            Node::GeometryWithin(wanted, chained, radius) => {
                self.geometry(i, wanted, *chained, *radius, state)?
            }
            Node::Pattern(rule) => {
                let width = rule.width();
                if state == "unknown" || i + 1 < width {
                    format!("This pattern requires {width} consecutive completed candles.")
                } else {
                    let mut observed = Vec::with_capacity(width);
                    for bar in tape.bars[i + 1 - width..=i].iter().flatten() {
                        observed.push([bar.o, bar.h, bar.l, bar.c].map(cents).join(" / "));
                    }
                    format!(
                        "Observed OHLC, oldest first: {}. Pattern result: {state}.",
                        observed.join(" → ")
                    )
                }
            }
            Node::Reclaim(..) => match self.series[id].reclaim(i, self.series)? {
                Some((breach, level)) => format!(
                    "Breach candle {}. First reclaim {}. Frozen level {}.",
                    utc(tape.close(breach)),
                    utc(t),
                    cents(level)
                ),
                None if bar.is_none() => "Candle absent from the recording.".into(),
                None if state == "unknown" => {
                    "Missing candles or lookback coverage prevent deciding the first reclaim."
                        .into()
                }
                None => "No first reclaim of a pierced level in the selected candle window.".into(),
            },
            Node::Relate(left, cmp, right) => {
                let a = self.series[*left].prices()?[i];
                let b = self.series[*right].prices()?[i];
                if a == 0 || b == 0 {
                    "One or both price operands are unavailable.".into()
                } else {
                    format!(
                        "{} {} and {} {}. The test was {}.",
                        price_label(&self.nodes[*left], tape.interval),
                        cents(a),
                        price_label(&self.nodes[*right], tape.interval),
                        cents(b),
                        comparison(*cmp)
                    )
                }
            }
            Node::Near(reference, point, limit) => {
                let a = self.series[*point].prices()?[i];
                let b = self.series[*reference].prices()?[i];
                if a == 0 || b == 0 {
                    "One or both price operands are unavailable.".into()
                } else {
                    let relation = if limit.compare((a - b).abs(), b).is_gt() {
                        "outside"
                    } else {
                        "inside"
                    };
                    format!(
                        "{} is {:.3}% from {}. It is {relation} the limit.",
                        cents(a),
                        percentage((a - b).abs(), b),
                        cents(b)
                    )
                }
            }
            Node::Share(part, lag, ..) => {
                let candle = i.checked_sub(*lag).and_then(|j| tape.bars[j]);
                match candle.filter(|b| b.h > b.l) {
                    Some(b) => format!(
                        "{} was {:.2}% of the candle range.",
                        field_label(*part),
                        percentage(part.value(b), b.h - b.l)
                    ),
                    None => "The selected candle is absent or has zero range.".into(),
                }
            }
            Node::Multiple(window, ..) => {
                let median = self.eval.median_at(*window, i);
                match bar.filter(|_| median > 0) {
                    Some(bar) => format!(
                        "This range was {:.3} × the preceding {} median.",
                        2.0 * (bar.h - bar.l) as f64 / median as f64,
                        duration(*window as i64 * tape.interval)
                    ),
                    None => "The previous window is incomplete or its median range is zero.".into(),
                }
            }
            Node::Range(window, _) => match (bar, self.eval.envelope_at(*window, i)) {
                (Some(bar), Some((low, high))) => format!(
                    "The {} range is {} to {} ({:.3}% of the close). State at t: {state}.",
                    duration(*window as i64 * tape.interval),
                    cents(low),
                    cents(high),
                    percentage(high - low, bar.c)
                ),
                _ => "The range is unavailable because the recording has no candle at this close."
                    .into(),
            },
            Node::Held(child, steps) => {
                let first = (i + 1).saturating_sub(*steps);
                let mask = self.series[*child].mask()?;
                let witness = (first..=i).rev().find(|&j| mask.at(j) == (false, true));
                if let Some(slot) = witness {
                    format!(
                        "state false at {} ({}), inside the required window",
                        utc(tape.close(slot)),
                        self.explain(*child, slot, remaining)?
                    )
                } else if i + 1 < *steps {
                    format!("needs {steps} samples; the first recorded close is {} (warmup: absent samples are unknown)", utc(tape.close(0)))
                } else if let Some(slot) = (first..=i).rev().find(|&j| !mask.at(j).1) {
                    format!(
                        "state unknown at {} ({}); no known false in the window",
                        utc(tape.close(slot)),
                        self.explain(*child, slot, remaining)?
                    )
                } else {
                    format!(
                        "true at all {steps} samples {} … {}",
                        utc(tape.close(first)),
                        utc(t)
                    )
                }
            }
            Node::Weekday => match state {
                "unknown" => format!("anchor {} is outside nyse_regular coverage", utc(t)),
                "closed" => format!("{} has no nyse_regular session", utc(t)),
                day => format!("The New York date of {} is a {} session.", utc(t), day),
            },
            Node::Tail(last) => format!(
                "{} is {} the last {} of the New York session.",
                utc(t),
                match state {
                    "true" => "in",
                    "false" => "outside",
                    _ => "of unknown membership in",
                },
                duration(*last)
            ),
            Node::Trend(frame) => {
                let end = t / frame * frame;
                let start = end - frame;
                let first = (start - tape.start) / tape.interval;
                let last = (end - tape.start) / tape.interval - 1;
                let head = format!("{} bar {} … {}", duration(*frame), utc(start), utc(end));
                if state == "unknown" || first < 0 || last < 0 {
                    format!("{head} incomplete (no fallback to an older bar)")
                } else {
                    let open = tape.bars[first as usize].expect("complete frame").o;
                    let close = tape.bars[last as usize].expect("complete frame").c;
                    format!(
                        "{head}: open {} → close {} ({state})",
                        cents(open),
                        cents(close)
                    )
                }
            }
            Node::Window(inner, _) => {
                if state == "unknown" {
                    "The window or a required comparison is unknown.".into()
                } else {
                    self.explain(*inner, i, remaining)?
                }
            }
            Node::Equal(left, right, _) => {
                let side = if matches!(&self.nodes[*left], Node::Category(_)) {
                    *right
                } else {
                    *left
                };
                format!(
                    "{}: {}",
                    self.series[side].group(i),
                    self.explain(side, i, remaining)?
                )
            }
            Node::Not(inner) => format!(
                "The condition is {}: {}",
                self.series[*inner].group(i),
                self.explain(*inner, i, remaining)?
            ),
            Node::Logic(items, and) => {
                let decisive = if *and { "false" } else { "true" };
                let selected = items
                    .iter()
                    .find(|&&item| self.series[item].group(i) == decisive)
                    .or_else(|| {
                        items
                            .iter()
                            .find(|&&item| self.series[item].group(i) == "unknown")
                    });
                if let Some(&item) = selected {
                    format!(
                        "A condition is {}: {}",
                        self.series[item].group(i),
                        self.explain(item, i, remaining)?
                    )
                } else {
                    format!("All {} conditions are {state}.", items.len())
                }
            }
            Node::Category(_) => "value".into(),
            Node::AxisRelate(left, cmp, right) => {
                let a = self.series[*left].axis()?[i];
                let b = self.series[*right].axis()?[i];
                if !a.is_finite() || !b.is_finite() {
                    "One or both dimension values are unavailable.".into()
                } else {
                    format!(
                        "The comparison was {a} {} {b}. Result: {state}.",
                        comparison(*cmp)
                    )
                }
            }
            Node::AxisMultiple(dimension, window, _, _) => {
                let median = self.eval.axis_median_at(*dimension, *window, i);
                format!("{dimension} relative to its prior median. Median sum: {median}. Result: {state}.")
            }
            Node::Price(..) | Node::Prior(..) => {
                format!("Price: {}.", cents(self.series[id].prices()?[i]))
            }
            Node::Axis(..) | Node::AxisPrior(..) | Node::AxisZero => {
                format!("Dimension value: {}.", self.series[id].axis()?[i])
            }
        };
        Ok(reason)
    }

    fn geometry(
        &self,
        slot: usize,
        wanted: &GeometryPattern,
        chained: bool,
        radius: u32,
        state: &str,
    ) -> Result<String> {
        let width = wanted.len();
        let reading = if chained {
            Reading::Chained
        } else {
            Reading::Recorded
        };
        if state == "unknown" || slot + 1 < width {
            let required = if wanted.has_dimensions() {
                " and all selected dimension readings"
            } else {
                ""
            };
            return Ok(format!(
                "geometry requires {width} consecutive recorded bars through this close{required}"
            ));
        }
        let recording = self.eval.tape.geometry_window(slot + 1 - width, slot + 1)?;
        let observed = recording
            .pattern_at(
                width - 1,
                width,
                wanted.mode(),
                reading,
                wanted.dimension_set(),
            )?
            .ok_or("geometry unavailable at close")?;
        let note = if chained {
            " (later opens read as the previous close)"
        } else {
            ""
        };
        if radius > 0 {
            let cost = distance(wanted, &observed)?;
            return Ok(format!(
                "{observed}{note} differs by {cost} half-flips from {wanted} (radius {radius})."
            ));
        }
        let relation = if state == "true" {
            "matches"
        } else {
            "differs from"
        };
        Ok(format!("{observed}{note} {relation} {wanted}"))
    }

    fn breakout(&self, i: usize, width: usize, state: &str) -> String {
        let tape = self.eval.tape;
        let bar = match tape.bars[i] {
            Some(bar) => bar,
            None => return "bar absent from the recording".into(),
        };
        let first = i.saturating_sub(width);
        let high = i
            .checked_sub(1)
            .and_then(|j| self.eval.envelope_at(width, j))
            .map(|(_, high)| high);
        if state == "unknown" {
            let missing = width
                - tape.bars[first..i]
                    .iter()
                    .filter(|bar| bar.is_some())
                    .count();
            return format!("channel incomplete: {missing} of {width} prior bars absent or before the recording start");
        }
        let high = high.expect("known breakout has prior high");
        let slot = (first..i)
            .find(|&j| tape.bars[j].map_or(false, |b| b.h == high))
            .expect("present prior high");
        let relation = if state == "true" { ">" } else { "≤" };
        format!(
            "close {} {relation} prior {} high {} (bar closing {})",
            cents(bar.c),
            duration(width as i64 * tape.interval),
            cents(high),
            utc(tape.close(slot))
        )
    }
}

pub(super) fn outcome(tape: &Tape, slot: usize, horizon: usize) -> String {
    let later = slot + horizon;
    let elapsed = duration(horizon as i64 * tape.interval);
    match tape.bars.get(later) {
        None => format!(
            "t + {elapsed} = {} is after the recording end {}",
            utc(tape.close(later)),
            utc(tape.close(tape.bars.len() - 1))
        ),
        Some(None) => format!(
            "bar closing at t + {elapsed} ({}) is absent",
            utc(tape.close(later))
        ),
        Some(Some(bar)) => format!(
            "C(t+{elapsed}) {} / C(t) {} − 1",
            cents(bar.c),
            cents(tape.bars[slot].expect("present anchor").c)
        ),
    }
}

fn duration(ms: i64) -> String {
    let minutes = ms / 60_000;
    if minutes % 1440 == 0 {
        format!("{}d", minutes / 1440)
    } else if minutes % 60 == 0 {
        format!("{}h", minutes / 60)
    } else {
        format!("{minutes}m")
    }
}

fn cents(value: i64) -> String {
    let magnitude = value.unsigned_abs();
    let sign = if value < 0 { "-" } else { "" };
    format!("{sign}{}.{:02}", magnitude / 100, magnitude % 100)
}

fn percentage(part: i64, whole: i64) -> f64 {
    100.0 * part as f64 / whole as f64
}

fn field_label(field: Field) -> &'static str {
    match field {
        Field::Open => "open",
        Field::High => "high",
        Field::Low => "low",
        Field::Close => "close",
        Field::BodyLow => "body low",
        Field::BodyHigh => "body high",
        Field::Body => "body",
        Field::Range => "range",
        Field::Lower => "lower wick",
        Field::Upper => "upper wick",
        Field::Direction => "direction",
    }
}

fn price_label(node: &Node, interval: i64) -> String {
    match node {
        Node::Price(field, lag) => {
            if *lag == 0 {
                field_label(*field).into()
            } else {
                format!("{} {} bars ago", field_label(*field), lag)
            }
        }
        Node::Prior(window, high) => format!(
            "prior {} {}",
            duration(*window as i64 * interval),
            if *high { "high" } else { "low" }
        ),
        _ => "price".into(),
    }
}

fn comparison(cmp: Cmp) -> &'static str {
    match cmp {
        Cmp::Eq => "equal",
        Cmp::Ne => "unequal",
        Cmp::Lt => "below",
        Cmp::Le => "at or below",
        Cmp::Gt => "above",
        Cmp::Ge => "at or above",
    }
}

// Invert the same Gregorian century/leap-year arithmetic used by data::date.
fn utc(ms: i64) -> String {
    let minutes = ms.div_euclid(60_000);
    let day = minutes.div_euclid(1440) + 719_468;
    let clock = minutes.rem_euclid(1440);
    let era = day.div_euclid(146_097);
    let doe = day.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year}-{month:02}-{day:02} {:02}:{:02}Z",
        clock / 60,
        clock % 60
    )
}
