//! Bounded, close-anchored research studies over a checked Filang plan.
//! This path shares the native geometry and packed mask representations.
mod bench;
mod candles;
mod compiler;
mod compute;
mod description;
mod explanation;
mod extension;
mod plan;
mod predicate;
mod syntax;
mod tape;

pub(crate) use compiler::DrawingCatalogue;
pub(crate) use tape::{recording_slot, valid_open_time, MAX_EXACT_INTEGER};

pub(crate) fn geometry_frame(
    csv: &str,
    interval: i64,
) -> crate::Result<(i64, crate::geometry::explore::Recording)> {
    let tape = tape::Tape::parse(csv, interval)?;
    Ok((tape.start, tape.geometry_recording()?))
}

use self::{
    compute::{Eval, Series},
    plan::{Plan, Query},
    tape::{Calendar, Tape},
};
use crate::Result;
use std::{
    io::{self, BufRead, BufReader, BufWriter, Write},
    path::Path,
};

const PLAN_LIMIT: u64 = 1_048_576;
const OUTPUT_CELLS: usize = 1_000_000;

pub fn serve(bars: impl AsRef<Path>, calendar: impl AsRef<Path>, interval_ms: i64) -> Result<()> {
    let tape = Tape::read(bars, interval_ms)?;
    let calendar = Calendar::read(calendar)?;
    let mut input = BufReader::new(io::stdin().lock());
    let mut out = BufWriter::new(io::stdout().lock());
    writeln!(out, "{{\"ready\":\"filang-study-v1\"}}").map_err(io_error)?;
    out.flush().map_err(io_error)?;
    loop {
        let mut line = String::new();
        let len = std::io::Read::take(&mut input, PLAN_LIMIT + 1)
            .read_line(&mut line)
            .map_err(io_error)?;
        if len == 0 {
            return Ok(());
        }
        if len as u64 > PLAN_LIMIT {
            return Err("study request exceeds 1 MiB".into());
        }
        match evaluate(&line, &tape, &calendar) {
            Ok(value) => writeln!(out, "{value}").map_err(io_error)?,
            Err(error) => writeln!(out, "{{\"error\":{}}}", quote(&error)).map_err(io_error)?,
        }
        out.flush().map_err(io_error)?;
    }
}

/// An in-memory study, independent of the legacy process protocol.
pub struct Study {
    tape: Tape,
    calendar: Option<(String, Calendar)>,
    calendar_sha256: Option<String>,
    instrument: String,
    source_sha256: String,
    registry: compiler::Registry,
}

impl Study {
    pub fn new(csv: &str, interval: i64, instrument: &str) -> Result<Self> {
        if instrument.is_empty()
            || !instrument
                .bytes()
                .all(|x| x.is_ascii_alphanumeric() || x == b'_')
        {
            return Err("invalid recording instrument".into());
        }
        Ok(Self {
            tape: Tape::parse(csv, interval)?,
            calendar: None,
            calendar_sha256: None,
            instrument: instrument.to_owned(),
            source_sha256: crate::hash::sha256(csv.as_bytes()),
            registry: compiler::Registry::new()?,
        })
    }

    pub fn set_calendar(&mut self, tsv: &str) -> Result<()> {
        self.set_calendar_named(extension::PINNED_CALENDAR, tsv)
    }

    pub fn set_pinned_calendar(&mut self) -> Result<()> {
        self.set_calendar(include_str!("../../study/catalogue/nyse.tsv"))?;
        self.calendar_sha256 = Some(crate::hash::sha256(include_bytes!(
            "../../study/nyse-sessions.json"
        )));
        Ok(())
    }

    pub fn set_calendar_named(&mut self, table: &str, tsv: &str) -> Result<()> {
        if table.is_empty() || table.chars().any(|ch| ch.is_whitespace() || ch == '/') {
            return Err("invalid calendar table id".into());
        }
        self.calendar = Some((table.to_owned(), Calendar::parse(tsv)?));
        self.calendar_sha256 = Some(crate::hash::sha256(tsv.as_bytes()));
        Ok(())
    }

    pub fn install_definition(&mut self, text: &str, sha256: &str) -> Result<()> {
        if crate::hash::sha256(text.as_bytes()) != sha256 {
            return Err("definition bytes do not match the pinned SHA-256".into());
        }
        let environment = compiler::Environment {
            instrument: &self.instrument,
            interval: self.tape.interval,
            counters: self.tape.has_counters(),
            calendar: self.calendar.as_ref().map(|(table, _)| table.as_str()),
        };
        if let Some(alias) = self.registry.install(text, environment)? {
            let result = self.validate_definition(&alias);
            if result.is_err() {
                self.registry.remove(&alias);
            }
            result?;
        }
        Ok(())
    }

    fn validate_definition(&self, alias: &str) -> Result<()> {
        let empty_calendar = Calendar::empty();
        let calendar = self
            .calendar
            .as_ref()
            .map_or(&empty_calendar, |(_, calendar)| calendar);
        for case in self.registry.cases(alias) {
            let timestamp = utc_millis(&case.anchor)?;
            let relative = timestamp - self.tape.start;
            if relative <= 0 || relative % self.tape.interval != 0 {
                return Err(format!(
                    "conformance anchor {} is off the recording grid",
                    case.anchor
                ));
            }
            let slot = usize::try_from(relative / self.tape.interval - 1)
                .ok()
                .filter(|&slot| slot < self.slots())
                .ok_or_else(|| {
                    format!(
                        "conformance anchor {} is outside the recording",
                        case.anchor
                    )
                })?;
            let plan = self
                .registry
                .compile_case(&format!("{alias}({})", case.arguments), self.environment())?;
            let mut evaluator = Eval::new(&self.tape, calendar);
            let series = evaluator.series(&plan.nodes)?;
            let (truth, known) = series[plan.queries[0].find].mask()?.at(slot);
            let observed = known.then_some(truth);
            if observed != case.expected {
                return Err(format!(
                    "definition conformance failed at {}: expected {:?}, got {:?}",
                    case.anchor, case.expected, observed
                ));
            }
        }
        Ok(())
    }

    pub fn slots(&self) -> usize {
        self.tape.bars.len()
    }

    pub fn geometry_recording(&self) -> Result<crate::geometry::explore::Recording> {
        self.tape.geometry_recording()
    }

    pub fn catalogue() -> &'static str {
        compiler::Registry::catalogue()
    }

    fn environment(&self) -> compiler::Environment<'_> {
        compiler::Environment {
            instrument: &self.instrument,
            interval: self.tape.interval,
            counters: self.tape.has_counters(),
            calendar: self.calendar.as_ref().map(|(table, _)| table.as_str()),
        }
    }

    fn compile(&self, text: &str, candidate: Option<usize>) -> Result<Plan> {
        compiler::compile(text, self.environment(), &self.registry, candidate)
    }

    pub fn check(&self, text: &str) -> Result<usize> {
        Ok(self.compile(text, None)?.queries.len())
    }

    /// Evaluate checked Filang text and return the existing study result shape.
    pub fn query(&self, text: &str, candidate: Option<usize>) -> Result<String> {
        let plan = self.compile(text, candidate)?;
        let empty = Calendar::empty();
        evaluate_plan(
            plan,
            &self.tape,
            self.calendar
                .as_ref()
                .map_or(&empty, |(_, calendar)| calendar),
        )
    }

    /// Count the first candidate without materializing closes or outcomes.
    /// A batch consumer can return an error for one query and keep the others.
    pub fn first_count(&self, text: &str) -> Result<usize> {
        let plan = self.compile(text, Some(0))?;
        let empty = Calendar::empty();
        let calendar = self
            .calendar
            .as_ref()
            .map_or(&empty, |(_, calendar)| calendar);
        let mut eval = Eval::new(&self.tape, calendar);
        let series = eval.series(&plan.nodes)?;
        let query = &plan.queries[0];
        let event = series[query.find].mask()?;
        let context = query.context.map(|id| series[id].mask()).transpose()?;
        Ok(self
            .tape
            .bars
            .iter()
            .enumerate()
            .filter(|&(i, bar)| {
                bar.is_some() && event.at(i).0 && context.map_or(true, |mask| mask.at(i).0)
            })
            .count())
    }
}

fn utc_millis(text: &str) -> Result<i64> {
    let invalid = || format!("invalid UTC conformance anchor {text}");
    let (day, clock) = text
        .strip_suffix('Z')
        .and_then(|iso| iso.split_once('T'))
        .ok_or_else(invalid)?;
    let mut clock = clock.split(':');
    let read = |cell: Option<&str>, limit: i64| -> Result<i64> {
        cell.filter(|cell| cell.len() == 2 && cell.bytes().all(|b| b.is_ascii_digit()))
            .and_then(|cell| cell.parse().ok())
            .filter(|&n| n < limit)
            .ok_or_else(invalid)
    };
    let hour = read(clock.next(), 24)?;
    let minute = read(clock.next(), 60)?;
    let seconds = clock.next().ok_or_else(invalid)?;
    if clock.next().is_some() {
        return Err(invalid());
    }
    let (seconds, fraction) = seconds.split_once('.').unwrap_or((seconds, ""));
    if fraction.len() > 3 || !fraction.bytes().all(|b| b.is_ascii_digit()) {
        return Err(invalid());
    }
    let fraction = fraction
        .bytes()
        .zip([100, 10, 1])
        .map(|(b, scale)| i64::from(b - b'0') * scale)
        .sum::<i64>();
    Ok(crate::data::date(day)? * 1000
        + hour * 3_600_000
        + minute * 60_000
        + read(Some(seconds), 60)? * 1000
        + fraction)
}

fn io_error(e: io::Error) -> String {
    e.to_string()
}

pub(crate) fn quote(text: &str) -> String {
    use std::fmt::Write;
    let mut value = String::with_capacity(text.len() + 2);
    value.push('"');
    for c in text.chars() {
        match c {
            '"' => value.push_str("\\\""),
            '\\' => value.push_str("\\\\"),
            c if c.is_control() => write!(value, "\\u{:04x}", c as u32).expect("format string"),
            c => value.push(c),
        }
    }
    value.push('"');
    value
}

fn evaluate(text: &str, tape: &Tape, calendar: &Calendar) -> Result<String> {
    evaluate_plan(Plan::parse(text, tape.interval)?, tape, calendar)
}

fn evaluate_plan(plan: Plan, tape: &Tape, calendar: &Calendar) -> Result<String> {
    use std::fmt::Write;
    let mut eval = Eval::new(tape, calendar);
    let series = eval.series(&plan.nodes)?;
    let mut out = String::new();
    write!(out, "{{\"engine\":\"Filang {} · study v1\",\"work\":{{\"candidates\":{},\"nodes\":{},\"rollingWindows\":{},\"geometryWindows\":{},\"medianWindows\":{}}},\"results\":[",
        env!("CARGO_PKG_VERSION"), plan.queries.len(), plan.nodes.len(), eval.rolling_windows, eval.geometry_windows, eval.median_windows())
        .expect("format string");
    let mut cells_left = OUTPUT_CELLS;
    for (i, query) in plan.queries.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        write_result(&mut out, tape, &series, query, &mut cells_left)?;
    }
    out.push_str("]}");
    Ok(out)
}

fn write_result(
    out: &mut String,
    tape: &Tape,
    series: &[Series],
    query: &Query,
    budget: &mut usize,
) -> Result<()> {
    use std::fmt::Write;
    let event = series[query.find].mask()?;
    let context = query.context.map(|id| series[id].mask()).transpose()?;
    let mut eligible = Vec::new();
    let mut event_unknown = Vec::new();
    let mut context_unknown = Vec::new();
    let mut eligible_unknown = Vec::new();
    let mut matches = Vec::new();
    let (mut occurrences, mut nonmatching) = (0, 0);
    for (i, bar) in tape.bars.iter().enumerate() {
        if bar.is_none() {
            continue;
        }
        let t = tape.close(i);
        let (exists, known) = event.at(i);
        occurrences += usize::from(exists);
        if !known {
            event_unknown.push(t);
        }
        match context.map_or((true, true), |m| m.at(i)) {
            (_, false) => context_unknown.push(t),
            (true, true) => {
                eligible.push(t);
                match (exists, known) {
                    (_, false) => eligible_unknown.push(t),
                    (false, true) => nonmatching += 1,
                    (true, true) => matches.push(i),
                }
            }
            (false, true) => {}
        }
    }
    let materialized = eligible.len()
        + event_unknown.len()
        + context_unknown.len()
        + eligible_unknown.len()
        + matches.len() * (2 + query.horizons.len());
    *budget = budget.checked_sub(materialized).ok_or(
        "study response exceeds materialization budget; request one candidate or narrow the query",
    )?;
    write!(out, "{{\"eligible\":{eligible:?},\"unknown\":{{\"event\":{event_unknown:?},\"eligibility\":{context_unknown:?},\"detectorWithinContext\":{eligible_unknown:?}}},\"counts\":{{\"event\":{occurrences},\"eligible\":{},\"matches\":{},\"nonmatching\":{nonmatching},\"absent\":{}}},\"anchors\":[",
        eligible.len(), matches.len(), tape.absent()).expect("format string");
    for (j, &i) in matches.iter().enumerate() {
        if j > 0 {
            out.push(',');
        }
        write!(out, "{}", tape.close(i)).expect("format string");
    }
    out.push_str("],\"rows\":[");
    for (j, &i) in matches.iter().enumerate() {
        if j > 0 {
            out.push(',');
        }
        write!(out, "{{\"t\":{},\"group\":", tape.close(i)).expect("format string");
        if let Some(id) = query.group {
            write!(out, "\"{}\"", series[id].group(i)).expect("format string");
        } else {
            out.push_str("null");
        }
        write_outcomes(out, tape, i, &query.horizons);
        write_reclaim(out, tape, series, query, i)?;
        out.push('}');
    }
    out.push_str("]}");
    Ok(())
}

fn write_outcomes(out: &mut String, tape: &Tape, i: usize, horizons: &[usize]) {
    use std::fmt::Write;
    out.push_str(",\"out\":[");
    let start = tape.bars[i].expect("present occurrence").c;
    for (k, &h) in horizons.iter().enumerate() {
        if k > 0 {
            out.push(',');
        }
        match tape.bars.get(i + h) {
            None => out.push_str("{\"status\":\"censored\",\"value\":null}"),
            Some(None) => out.push_str("{\"status\":\"unknown\",\"value\":null}"),
            Some(Some(bar)) => write!(
                out,
                "{{\"status\":\"observed\",\"value\":{}}}",
                (bar.c - start) as f64 / start as f64
            )
            .expect("format string"),
        }
    }
    out.push(']');
}

fn write_reclaim(
    out: &mut String,
    tape: &Tape,
    series: &[Series],
    query: &Query,
    i: usize,
) -> Result<()> {
    use std::fmt::Write;
    if let Some((breach, level)) = series[query.find].reclaim(i, series)? {
        write!(
            out,
            ",\"reclaim\":{{\"breach\":{},\"reclaim\":{},\"level\":{level}}}",
            tape.close(breach),
            tape.close(i)
        )
        .expect("format string");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geometry::COUNTER_COLUMNS;
    use std::fmt::Write as _;

    const BAR: i64 = 900_000;

    fn calendar() -> Calendar {
        let path = std::env::temp_dir().join(format!(
            "filang-study-calendar-{}-{:?}.tsv",
            std::process::id(),
            std::thread::current().id()
        ));
        std::fs::write(&path, "0\t86400000\n").unwrap();
        let calendar = Calendar::read(&path).unwrap();
        std::fs::remove_file(path).unwrap();
        calendar
    }

    /// Six slots: two up bars, a flat bar without trades, a missing bar and
    /// two more up bars. Counters are USDT traded, taker-buy USDT, trades.
    fn recording(counters: bool) -> String {
        let bars = [
            (0, "100.00,105.00,99.00,104.00", "1000,600,10"),
            (1, "104.00,110.00,103.00,109.00", "2000,1200,40"),
            (2, "109.00,109.00,109.00,109.00", "0,0,0"),
            (4, "109.00,112.00,108.00,111.00", "5e2,100,5"),
            (5, "111.00,115.00,110.00,114.00", "700,500,7"),
        ];
        let mut csv = if counters {
            format!("{COUNTER_COLUMNS}\n")
        } else {
            "open_ms,open,high,low,close,volume\n".to_owned()
        };
        for (slot, prices, counts) in bars {
            write!(csv, "{},{prices},1.5", slot * BAR).unwrap();
            if counters {
                write!(csv, ",{counts}").unwrap();
            }
            csv.push('\n');
        }
        csv
    }

    /// The closes at which the code matches, and those at which it is unknown.
    fn read(tape: &Tape, node: &str) -> Result<(Vec<i64>, Vec<i64>)> {
        let plan = format!("filang-study-v1\t1\t{node}\t0 - -");
        let answer = evaluate(&plan, tape, &calendar())?;
        let list = |key: &str| -> Vec<i64> {
            let marker = format!("\"{key}\":[");
            let at = answer.find(&marker).unwrap() + marker.len();
            let end = at + answer[at..].find(']').unwrap();
            answer[at..end]
                .split(',')
                .filter(|item| !item.is_empty())
                .map(|item| item.trim().parse().unwrap())
                .collect()
        };
        Ok((list("anchors"), list("event")))
    }

    #[test]
    fn text_compiler_keeps_dimension_validity_and_type_rules() {
        use crate::engine_json;

        let study = Study::new(&recording(true), BAR, "BTCUSDT").unwrap();
        let query = |find: &str| format!("on BTCUSDT 15m\nfind {find}");
        let result = |find: &str| {
            let raw = study.query(&query(find), None).unwrap();
            let json = engine_json::parse(&raw).unwrap();
            let result = &json.field("results").unwrap().array().unwrap()[0];
            let timestamps = |values: &engine_json::Value| {
                values
                    .array()
                    .unwrap()
                    .iter()
                    .map(|value| value.number::<i64>().unwrap())
                    .collect::<Vec<_>>()
            };
            (
                timestamps(result.field("anchors").unwrap()),
                timestamps(result.field("unknown").unwrap().field("event").unwrap()),
            )
        };
        let close = |slots: &[i64]| slots.iter().map(|i| (i + 1) * BAR).collect::<Vec<_>>();
        let v = "candle_relation(volume(), is: above, right: volume(bars_ago: 1))";
        let d = "candle_relation(delta(), is: above, right: 0)";
        assert_eq!(result(v), (close(&[1, 5]), close(&[0, 4])));
        assert_eq!(result(d), (close(&[0, 1, 5]), vec![]));
        assert_eq!(
            result(&format!("{v} and {d}")),
            (close(&[1, 5]), close(&[0]))
        );
        assert_eq!(
            result("candle_relation(volume(), is: below, right: prior_low(over: 30m, of: volume))"),
            (close(&[2]), close(&[0, 1, 4, 5])),
        );
        assert!(study
            .check(&query("candle_relation(size(), right: volume())"))
            .is_err());
        assert!(study
            .check(&query("candle_relation(volume(), right: 0)"))
            .is_err());
        assert!(study
            .check(&query("wick_rejection() where dimension_multiple(delta)"))
            .is_err());
        assert!(study
            .check(&query(
                "wick_rejection() where dimension_multiple(volume, over: 30m, min: 200 %, max: 3)"
            ))
            .is_ok());
    }

    #[test]
    fn dimension_codes_are_three_valued_and_need_counters() {
        let tape = Tape::parse(&recording(true), BAR).unwrap();
        let close = |slots: &[i64]| slots.iter().map(|s| (s + 1) * BAR).collect::<Vec<_>>();
        // One up candle with net buying: the flat bar and the net seller are
        // known not to match, and no present bar is unknown.
        assert_eq!(
            read(&tape, "g1 g1:o:0,1,2,3,u|delta:1/0").unwrap(),
            (close(&[0, 1, 5]), vec![])
        );
        assert_eq!(
            read(&tape, "g1 g1:o:0,1,2,3,u").unwrap(),
            (close(&[0, 1, 4, 5]), vec![])
        );
        // The bar without trades has no size: unknown, whatever its prices.
        assert_eq!(
            read(&tape, "g1 g1:o:0,0,0,0,z|size:0").unwrap(),
            (vec![], close(&[2]))
        );
        assert_eq!(
            read(&tape, "g1 g1:o:0,0,0,0,z|volume:0|delta:0/0").unwrap(),
            (close(&[2]), vec![])
        );
        // Two bars: unknown for want of a bar at slots 0 and 4, and also for
        // want of a value where the window reads the bar without trades.
        let pair = "g1:o:0,1,3,4,u;2,3,5,6,u";
        for op in ["g1", "g1c"] {
            assert_eq!(
                read(&tape, &format!("{op} {pair}")).unwrap(),
                (close(&[1, 5]), close(&[0, 4]))
            );
            assert_eq!(
                read(&tape, &format!("{op} {pair}|volume:0,1")).unwrap(),
                (close(&[1, 5]), close(&[0, 4]))
            );
            assert_eq!(
                read(&tape, &format!("{op} {pair}|volume:1,0")).unwrap(),
                (vec![], close(&[0, 4]))
            );
            assert_eq!(
                read(&tape, &format!("{op} {pair}|imbalance:0,2/1")).unwrap(),
                (close(&[5]), close(&[0, 2, 4]))
            );
            assert_eq!(
                read(&tape, &format!("{op} {pair}|volume:0,1|imbalance:1,1/0")).unwrap(),
                (close(&[1]), close(&[0, 2, 4]))
            );
        }
        // Malformed parts are rejected with the plan, and a recording without
        // counters refuses the code rather than reading its price part.
        assert!(read(&tape, &format!("g1 {pair}|volume:0")).is_err());
        assert!(read(&tape, &format!("g1 {pair}|delta:0,1")).is_err());
        let plain = Tape::parse(&recording(false), BAR).unwrap();
        assert_eq!(
            read(&plain, &format!("g1 {pair}")).unwrap(),
            (close(&[1, 5]), close(&[0, 4]))
        );
        assert!(read(&plain, &format!("g1 {pair}|volume:0,1"))
            .unwrap_err()
            .contains("no counters"));
        // A recording whose counters cannot be right is refused.
        let good = recording(true);
        for (from, to) in [
            ("1000,600,10", "1000,1001,10"),
            ("1000,600,10", "1000,600,10.5"),
            ("1000,600,10", "-1000,600,10"),
            ("1000,600,10", "inf,600,10"),
            ("1000,600,10", "1000,600"),
            ("1000,600,10", "1000,600,10,1"),
        ] {
            assert!(good.contains(from));
            assert!(Tape::parse(&good.replace(from, to), BAR).is_err(), "{to}");
        }
    }
}
