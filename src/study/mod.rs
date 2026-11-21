//! Bounded, close-anchored research studies over a checked Filang plan.
//! This path shares the native geometry and packed mask representations.
mod compute;
mod plan;
mod predicate;
mod tape;

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

fn io_error(e: io::Error) -> String {
    e.to_string()
}

fn quote(text: &str) -> String {
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
    use std::fmt::Write;
    let plan = Plan::parse(text, tape.interval)?;
    let mut eval = Eval::new(tape, calendar);
    let series = eval.series(&plan.nodes)?;
    let mut out = String::new();
    write!(out, "{{\"engine\":\"Filang {} · study v1\",\"work\":{{\"candidates\":{},\"nodes\":{},\"rollingWindows\":{},\"geometryWindows\":{}}},\"results\":[",
        env!("CARGO_PKG_VERSION"), plan.queries.len(), plan.nodes.len(), eval.rolling_windows, eval.geometry_windows)
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
        out.push_str(",\"out\":[");
        let start = tape.bars[i].expect("present occurrence").c;
        for (k, &h) in query.horizons.iter().enumerate() {
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
        out.push_str("]}");
    }
    out.push_str("]}");
    Ok(())
}
