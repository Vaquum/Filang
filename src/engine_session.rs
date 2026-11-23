//! Versioned in-process interface for the browser, Python and CLI adapters.

use crate::{
    engine_drawing, engine_json,
    geometry::{
        explore::{self, Bar, DeclaredDomain, PreparedGeometry, Reading, Recording, MAX_SLOTS},
        BodyDirection, Counters, Dimension, DimensionSet, GeometryDimensionKey, GeometryMode,
        GeometryPattern, GEOMETRY_KEY_MAX_BARS,
    },
    study, Result,
};
use std::{collections::HashMap, str};

pub const ABI_VERSION: u32 = 1;
pub const MAX_PAYLOAD: usize = 256 * 1024 * 1024;
const MAX_PAGE: usize = 4096;
const MAX_STUDY_BATCH: usize = 64;
const BAR_SIZE: usize = 57;

#[derive(Default)]
pub struct Session {
    recording: Option<Recording>,
    study: Option<study::Study>,
    prepared: HashMap<usize, PreparedGeometry>,
    domains: HashMap<(usize, GeometryMode), DeclaredDomain>,
}

impl Session {
    /// An ASCII operation and LF, followed by that operation's payload.
    /// Responses are UTF-8 JSON. Errors are reported out of band by the binding.
    pub fn call(&mut self, request: &[u8]) -> Result<String> {
        if request.len() > MAX_PAYLOAD {
            return Err("Filang engine request exceeds 256 MiB".into());
        }
        let delimiter = request.iter().position(|&b| b == b'\n');
        let (operation, payload) = match delimiter {
            Some(i) => (&request[..i], &request[i + 1..]),
            None => (request, &[][..]),
        };
        match operation {
            b"load" => return self.set_recording(decode_bars(payload)?),
            b"load-csv" => {
                let (interval, csv) = utf8(payload)?
                    .split_once('\n')
                    .ok_or("expected interval in milliseconds followed by CSV")?;
                let (interval, instrument) =
                    interval.split_once('\t').unwrap_or((interval, "BTCUSDT"));
                let study = study::Study::new(csv, number(interval)?, instrument)?;
                let slots = study.slots();
                self.prepared.clear();
                self.recording = None;
                self.study = Some(study);
                return Ok(format!("{{\"slots\":{slots}}}"));
            }
            _ => {}
        }
        let text = utf8(payload)?;
        match operation {
            b"version" if text.is_empty() => Ok(format!(
                "{{\"abi\":{ABI_VERSION},\"version\":\"{}\"}}",
                option_env!("FILANG_RELEASE_VERSION").unwrap_or(env!("CARGO_PKG_VERSION"))
            )),
            b"catalogue" if text.is_empty() => Ok(study::Study::catalogue().into()),
            b"calendar" => {
                let study = self
                    .study
                    .as_mut()
                    .ok_or("load a study recording from CSV first")?;
                if text.is_empty() {
                    study.set_pinned_calendar()?;
                } else {
                    study.set_calendar(text)?;
                }
                Ok("null".into())
            }
            b"calendar-named" => {
                let (table, tsv) = text
                    .split_once('\n')
                    .ok_or("missing named calendar table")?;
                self.study
                    .as_mut()
                    .ok_or("load a study recording from CSV first")?
                    .set_calendar_named(table, tsv)?;
                Ok("null".into())
            }
            b"install-definition" => {
                let (sha, definition) =
                    text.split_once('\n').ok_or("missing definition SHA-256")?;
                self.study
                    .as_mut()
                    .ok_or("load a study recording from CSV first")?
                    .install_definition(definition, sha)?;
                Ok("null".into())
            }
            b"check" => {
                let candidates = self.study()?.check(text)?;
                Ok(format!("{{\"candidates\":{candidates}}}"))
            }
            b"study" => {
                let (candidate, query) = text.split_once('\n').ok_or("missing study text")?;
                let candidate = if candidate == "-" {
                    None
                } else {
                    Some(number(candidate)?)
                };
                self.study()?.query(query, candidate)
            }
            b"study-counts" => {
                let questions = engine_json::parse(text)?;
                let questions = questions.array()?;
                if questions.len() > MAX_STUDY_BATCH {
                    return Err(format!(
                        "study count batch exceeds {MAX_STUDY_BATCH} questions"
                    ));
                }
                let study = self.study()?;
                let mut entries = Vec::with_capacity(questions.len());
                for query in questions {
                    entries.push(match study.first_count(query.text()?) {
                        Ok(count) => format!("{{\"count\":{count},\"error\":null}}"),
                        Err(error) => {
                            format!("{{\"count\":null,\"error\":{}}}", study::quote(&error))
                        }
                    });
                }
                Ok(format!("[{}]", entries.join(",")))
            }
            b"study-rows" => {
                let (page, query) = text.split_once('\n').ok_or("missing study text")?;
                let [candidate, start, limit] = fields(page)?;
                self.study()?.occurrence_page(
                    query,
                    number(candidate)?,
                    number(start)?,
                    number(limit)?,
                )
            }
            b"study-close" => {
                let (close, query) = text.split_once('\n').ok_or("missing study text")?;
                let [candidate, t] = fields(close)?;
                self.study()?
                    .close_facts(query, number(candidate)?, number(t)?)
            }
            b"session-clock" => Ok(self.study()?.session_clock(number(text)?)),
            b"inspect" => inspect(&text.parse()?),
            b"geometry-shape" => Ok(geometry_shape(&text.parse()?)),
            b"distance" => {
                let [left, right] = fields(text)?;
                let half_flips = explore::distance(&left.parse()?, &right.parse()?)?;
                Ok(format!("{{\"half_flips\":{half_flips}}}"))
            }
            b"domain" => {
                let [width, mode, dimensions] = fields(text)?;
                let width = number(width)?;
                let dimensions = DimensionSet::parse(dimensions)?;
                let mode = GeometryMode::parse(mode)?;
                use std::collections::hash_map::Entry;
                let domain = match self.domains.entry((width, mode)) {
                    Entry::Occupied(entry) => entry.into_mut(),
                    Entry::Vacant(entry) => entry.insert(DeclaredDomain::new(width, mode)?),
                };
                let count = domain.count(dimensions);
                Ok(format!(
                    "{{\"declared\":\"{count}\",\"includes_unrealizable\":{}}}",
                    dimensions.includes_patterns_that_cannot_occur(width),
                ))
            }
            b"drawing-protocol" if text.is_empty() => Ok(engine_drawing::protocol()),
            b"read-drawing" => {
                let (expected, packet) = text.split_once('\n').ok_or("missing drawing packet")?;
                let expected = (!expected.is_empty()).then_some(expected);
                let (shape, pins) = engine_drawing::read(packet, expected)?;
                let shape = inspect(&shape)?;
                let pinned = pins
                    .as_ref()
                    .map_or_else(|| "null".into(), |s| study::quote(s));
                Ok(format!(
                    "{{\"shape\":{shape},\"packet\":{packet},\"pinned_expression\":{pinned}}}"
                ))
            }
            b"draw" => inspect(&draw(text)?.0),
            b"draw-counts" => {
                let (pattern, reading) = draw(text)?;
                let counts = self.count(&pattern, reading)?;
                let shape = inspect(&pattern)?;
                Ok(format!("{{\"shape\":{shape},\"counts\":{counts}}}"))
            }
            b"at" => {
                let [end, width, mode, reading, dimensions] = fields(text)?;
                let result = self.recording()?.pattern_at(
                    number(end)?,
                    number(width)?,
                    GeometryMode::parse(mode)?,
                    Reading::parse(reading)?,
                    DimensionSet::parse(dimensions)?,
                )?;
                result.as_ref().map_or_else(|| Ok("null".into()), inspect)
            }
            b"prepare" => {
                let [width, mode, reading, dimensions] = fields(text)?;
                self.window(number(width)?)?.prepare(
                    GeometryMode::parse(mode)?,
                    Reading::parse(reading)?,
                    DimensionSet::parse(dimensions)?,
                )?;
                Ok("null".into())
            }
            b"counts" => {
                let [reading, code] = fields(text)?;
                let pattern: GeometryPattern = code.parse()?;
                self.count(&pattern, Reading::parse(reading)?)
            }
            b"positions" => {
                let [reading, start, limit, code] = fields(text)?;
                let limit = number(limit)?;
                if limit > MAX_PAGE {
                    return Err(format!("geometry page exceeds {MAX_PAGE} positions"));
                }
                let pattern: GeometryPattern = code.parse()?;
                let positions = self.window(pattern.len())?.positions(
                    &pattern,
                    Reading::parse(reading)?,
                    number(start)?,
                    limit,
                )?;
                Ok(format!("{positions:?}"))
            }
            b"classify" => {
                let [reading, start, limit, code] = fields(text)?;
                let limit = number(limit)?;
                if limit > MAX_PAGE {
                    return Err(format!("geometry page exceeds {MAX_PAGE} positions"));
                }
                let pattern: GeometryPattern = code.parse()?;
                let values = self.window(pattern.len())?.classify(
                    &pattern,
                    Reading::parse(reading)?,
                    number(start)?,
                    limit,
                )?;
                let mut out = String::from("[");
                for (i, value) in values.into_iter().enumerate() {
                    if i != 0 {
                        out.push(',');
                    }
                    out.push_str(match value {
                        Some(true) => "true",
                        Some(false) => "false",
                        None => "null",
                    });
                }
                out.push(']');
                Ok(out)
            }
            b"release" => {
                self.prepared.remove(&number(text)?);
                Ok("null".into())
            }
            _ => Err("unknown Filang engine operation".into()),
        }
    }

    fn count(&mut self, pattern: &GeometryPattern, reading: Reading) -> Result<String> {
        let result = self.window(pattern.len())?.counts(pattern, reading)?;
        Ok(format!(
            "{{\"matched\":{},\"false_count\":{},\"unknown\":{}}}",
            result.matched, result.false_count, result.unknown
        ))
    }

    fn set_recording(&mut self, recording: Recording) -> Result<String> {
        let length = recording.len();
        self.recording = Some(recording);
        self.study = None;
        self.prepared.clear();
        Ok(format!("{{\"slots\":{length}}}"))
    }

    fn study(&self) -> Result<&study::Study> {
        self.study
            .as_ref()
            .ok_or_else(|| "load a study recording from CSV first".into())
    }

    fn recording(&mut self) -> Result<&Recording> {
        if self.recording.is_none() {
            self.recording = Some(self.study()?.geometry_recording()?);
        }
        Ok(self.recording.as_ref().expect("loaded recording"))
    }

    fn window(&mut self, width: usize) -> Result<&mut PreparedGeometry> {
        if self.recording.is_none() {
            self.recording()?;
        }
        let recording = self.recording.as_ref().expect("loaded recording");
        use std::collections::hash_map::Entry;
        Ok(match self.prepared.entry(width) {
            Entry::Occupied(entry) => entry.into_mut(),
            Entry::Vacant(entry) => entry.insert(recording.prepare(width)?),
        })
    }
}

fn decode_bars(data: &[u8]) -> Result<Recording> {
    if data.len() % BAR_SIZE != 0 || data.len() / BAR_SIZE > MAX_SLOTS {
        return Err("invalid binary recording length".into());
    }
    let mut bars = Vec::with_capacity(data.len() / BAR_SIZE);
    for (slot, row) in data.chunks_exact(BAR_SIZE).enumerate() {
        let bar = (|| {
            if row[0] == 0 {
                return Ok(None);
            }
            if row[0] > 2 {
                return Err("invalid bar flag".to_string());
            }
            let read = |i: usize| {
                let bytes = &row[1 + 8 * i..1 + 8 * (i + 1)];
                f64::from_le_bytes(bytes.try_into().unwrap())
            };
            let ohlc = [read(0), read(1), read(2), read(3)];
            let counters = if row[0] == 2 {
                Some(Counters::new(read(4), read(5), read(6))?)
            } else {
                None
            };
            Ok(Some(Bar::new(ohlc, counters)?))
        })()
        .map_err(|error| format!("slot {slot}: {error}"))?;
        bars.push(bar);
    }
    Recording::new(bars)
}

fn inspect(pattern: &GeometryPattern) -> Result<String> {
    let words = if pattern.len() <= GEOMETRY_KEY_MAX_BARS {
        let key = GeometryDimensionKey::from_pattern(pattern)?;
        let price = key.price().words();
        let mut words = String::new();
        for word in price.iter().chain(key.dimension_words()) {
            use std::fmt::Write;
            if !words.is_empty() {
                words.push(',');
            }
            write!(words, "\"{word}\"").expect("write to String");
        }
        format!("[{words}]")
    } else {
        "null".into()
    };
    Ok(format!(
        "{{\"code\":{},\"width\":{},\"oriented\":{},\"dimensions\":{},\"words\":{words}}}",
        study::quote(&pattern.to_string()),
        pattern.len(),
        pattern.mode() == GeometryMode::Oriented,
        pattern.dimension_set().json(),
    ))
}

fn geometry_shape(pattern: &GeometryPattern) -> String {
    let ranks = pattern.ranks();
    let rank_count = ranks.iter().flatten().copied().max().expect("nonempty g1") + 1;
    let detail = match pattern.directions() {
        Some(directions) => {
            let labels: Vec<_> = directions
                .iter()
                .map(|direction| match direction {
                    BodyDirection::Up => "u",
                    BodyDirection::Down => "d",
                    BodyDirection::Flat => "z",
                })
                .collect();
            let rows: Vec<_> = ranks
                .iter()
                .zip(directions)
                .map(
                    |(&[low, body_low, body_high, high], direction)| match direction {
                        BodyDirection::Down => [body_high, high, low, body_low],
                        _ => [body_low, high, low, body_high],
                    },
                )
                .collect();
            let chained = rows.windows(2).all(|pair| pair[0][3] == pair[1][0]);
            format!("\"directions\":{labels:?},\"rows\":{rows:?},\"chained\":{chained}")
        }
        None => "\"directions\":null,\"rows\":null,\"chained\":null".into(),
    };
    format!("{{\"ranks\":{ranks:?},\"rank_count\":{rank_count},{detail}}}")
}

fn draw(text: &str) -> Result<(GeometryPattern, Reading)> {
    let mut lines = text.split('\n');
    let [mode, reading, n] = fields(lines.next().ok_or("missing drawing header")?)?;
    let n = number(n)?;
    if !(1..=explore::MAX_WIDTH).contains(&n) {
        return Err(format!(
            "drawing width must be in 1..={}",
            explore::MAX_WIDTH
        ));
    }
    let mut rows = Vec::with_capacity(n);
    for _ in 0..n {
        let [open, high, low, close] = fields(lines.next().ok_or("missing drawing bar")?)?;
        rows.push([number(open)?, number(high)?, number(low)?, number(close)?]);
    }
    let mut axes = Vec::new();
    for line in lines {
        let (axis, values) = line.split_once('\t').ok_or("missing drawing axis values")?;
        let axis: Dimension = axis.parse()?;
        let values = values
            .split('\t')
            .map(number)
            .collect::<Result<Vec<f64>>>()?;
        axes.push((axis, values));
    }
    let axes: Vec<_> = axes
        .iter()
        .map(|(axis, marks)| (*axis, marks.as_slice()))
        .collect();
    let reading = Reading::parse(reading)?;
    let pattern = explore::encode_drawing(&rows, GeometryMode::parse(mode)?, reading, &axes)?;
    Ok((pattern, reading))
}

fn utf8(input: &[u8]) -> Result<&str> {
    str::from_utf8(input).map_err(|_| "expected UTF-8 input".into())
}

fn fields<const N: usize>(text: &str) -> Result<[&str; N]> {
    let mut parts = text.split('\t');
    let mut values = [""; N];
    for value in &mut values {
        *value = parts.next().ok_or("missing engine argument")?;
    }
    if parts.next().is_some() {
        return Err("unexpected engine argument".into());
    }
    Ok(values)
}

fn number<T: str::FromStr>(text: &str) -> Result<T> {
    text.parse().map_err(|_| format!("invalid number {text:?}"))
}
