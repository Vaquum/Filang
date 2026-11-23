//! Paged occurrence receipts for the Query workbench.
use super::{
    compiler,
    compute::{Eval, Series},
    description,
    explanation::{self, Explain},
    plan::{Node, Query},
    quote, syntax,
    tape::{Calendar, DAYS, TRENDS},
    write_outcomes, write_reclaim, Study, OUTPUT_CELLS,
};
use crate::{rules::Mask, Result};
use std::fmt::Write;

pub(super) const MAX_RECEIPT_PAGE: usize = 4096;

impl Study {
    pub fn occurrence_page(
        &self,
        text: &str,
        candidate: usize,
        start: usize,
        limit: usize,
    ) -> Result<String> {
        if limit > MAX_RECEIPT_PAGE {
            return Err(format!("occurrence page exceeds {MAX_RECEIPT_PAGE} rows"));
        }
        let question = syntax::question(text)?;
        let plan = compiler::compile_question(
            &question,
            self.environment(),
            &self.registry,
            Some(candidate),
        )?;
        let empty = Calendar::empty();
        let calendar = self.calendar.as_ref().map_or(&empty, |(_, cal)| cal);
        let series = Eval::new(&self.tape, calendar).series(&plan.nodes)?;
        let query = &plan.queries[0];
        let filters = query
            .filters
            .iter()
            .map(|&id| series[id].mask())
            .collect::<Result<Vec<_>>>()?;
        let event = series[query.find].mask()?;
        let mut present_events = event.bits.clone();
        let mut event_unknown = 0;
        for (i, bar) in self.tape.bars.iter().enumerate() {
            if bar.is_none() {
                present_events[i / 64] &= !(1 << (i % 64));
            } else {
                event_unknown += usize::from(!event.at(i).1);
            }
        }
        let occurrences = popcount(&present_events);
        let (clause_stats, survivors) = filter_totals(&present_events, occurrences, &filters);
        let columns = query
            .column_labels
            .iter()
            .map(|label| quote(label))
            .collect::<Vec<_>>()
            .join(",");
        let lines = description::receipt_lines(&question, candidate);
        let mut out = format!(
            "{{\"event_count\":{occurrences},\"event_unknown\":{event_unknown},\"columns\":[{columns}],\"lines\":{lines},\"clause_stats\":{clause_stats:?},\"survivors\":{survivors:?},\"group_labels\":{},\"rows\":[",
            format_group_labels(query, &plan.nodes)
        );
        let mut next = None;
        let mut wrote = 0;
        let mut budget = OUTPUT_CELLS;
        for i in start..self.slots() {
            if present_events[i / 64] & (1 << (i % 64)) == 0 {
                continue;
            }
            if wrote == limit {
                next = Some(i);
                break;
            }
            budget = budget
                .checked_sub(4 + query.horizons.len() + filters.len())
                .ok_or("occurrence page exceeds materialization budget")?;
            if wrote > 0 {
                out.push(',');
            }
            write!(
                out,
                "{{\"slot\":{i},\"t\":{},\"group\":{},\"where\":[",
                self.tape.close(i),
                group_at(query, &series, i)
            )
            .expect("format string");
            let mut fail_at = -1;
            for (j, mask) in filters.iter().enumerate() {
                if j > 0 {
                    out.push(',');
                }
                let value = truth(mask, i);
                if value != "true" && fail_at == -1 {
                    fail_at = j as isize;
                }
                out.push_str(value);
            }
            write!(out, "],\"fail_at\":{fail_at}").expect("format string");
            write_outcomes(&mut out, &self.tape, i, &query.horizons);
            write_reclaim(&mut out, &self.tape, &series, query, i)?;
            out.push('}');
            wrote += 1;
        }
        let next = next.map_or_else(|| "null".to_owned(), |i| i.to_string());
        write!(out, "],\"next\":{next}}}").expect("format string");
        Ok(out)
    }

    pub fn close_facts(&self, text: &str, candidate: usize, t: i64) -> Result<String> {
        let relative = t
            .checked_sub(self.tape.start)
            .filter(|n| *n > 0 && *n % self.tape.interval == 0)
            .ok_or("close is off the recording grid")?;
        let i = usize::try_from(relative / self.tape.interval - 1)
            .ok()
            .filter(|&i| i < self.slots())
            .ok_or("close is outside the recording grid")?;
        let plan = self.compile(text, Some(candidate))?;
        let empty = Calendar::empty();
        let calendar = self.calendar.as_ref().map_or(&empty, |(_, cal)| cal);
        let mut eval = Eval::new(&self.tape, calendar);
        let series = eval.series(&plan.nodes)?;
        let explain = Explain {
            eval: &eval,
            nodes: &plan.nodes,
            series: &series,
            notes: &plan.notes,
            calendar,
        };
        let query = &plan.queries[0];
        let answers = query
            .filters
            .iter()
            .map(|&id| Ok(truth(series[id].mask()?, i)))
            .collect::<Result<Vec<_>>>()?;
        let mut out = format!(
            "{{\"slot\":{i},\"t\":{t},\"present\":{},\"event\":{},\"where\":[{}],\"group\":{}",
            self.tape.bars[i].is_some(),
            truth(series[query.find].mask()?, i),
            answers.join(","),
            group_at(query, &series, i)
        );
        write!(
            out,
            ",\"event_why\":{},\"where_why\":[",
            quote(&explain.at(query.find, i)?)
        )
        .expect("format string");
        for (position, &filter) in query.filters.iter().enumerate() {
            if position > 0 {
                out.push(',');
            }
            out.push_str(&quote(&explain.at(filter, i)?));
        }
        out.push(']');
        if let Some(group) = query.group {
            write!(out, ",\"group_why\":{}", quote(&explain.at(group, i)?)).expect("format string");
        }
        if self.tape.bars[i].is_some() {
            write_outcomes(&mut out, &self.tape, i, &query.horizons);
            write_reclaim(&mut out, &self.tape, &series, query, i)?;
            out.push_str(",\"outcome_why\":[");
            for (position, &horizon) in query.horizons.iter().enumerate() {
                if position > 0 {
                    out.push(',');
                }
                out.push_str(&quote(&explanation::outcome(&self.tape, i, horizon)));
            }
            out.push(']');
        } else {
            out.push_str(",\"out\":null,\"outcome_why\":null");
        }
        out.push('}');
        Ok(out)
    }

    pub fn session_clock(&self, t: i64) -> String {
        match self
            .calendar
            .as_ref()
            .and_then(|(_, cal)| cal.session_clock(t))
        {
            None => "{\"kind\":\"outside\",\"text\":\"outside calendar\"}".into(),
            Some(None) => "{\"kind\":\"closed\",\"text\":\"no session\"}".into(),
            Some(Some((weekday, minutes, offset))) => {
                let day = DAYS[weekday as usize];
                let zone = match offset {
                    14_400_000 => "EDT".into(),
                    18_000_000 => "EST".into(),
                    0 => "UTC+0".into(),
                    ms => format!("UTC−{}", ms as f64 / 3_600_000.0),
                };
                let clock = format!("{:02}:{:02} {zone}", minutes / 60, minutes % 60);
                format!(
                    "{{\"kind\":\"session\",\"weekday\":\"{day}\",\"local\":\"{clock}\",\"text\":\"{} {clock}\"}}",
                    day.to_ascii_uppercase()
                )
            }
        }
    }
}

fn truth(mask: &Mask, slot: usize) -> &'static str {
    match mask.at(slot) {
        (true, true) => "true",
        (false, true) => "false",
        (_, false) => "null",
    }
}

fn popcount(words: &[u64]) -> usize {
    words.iter().map(|word| word.count_ones() as usize).sum()
}

fn filter_totals(
    events: &[u64],
    occurrences: usize,
    filters: &[&Mask],
) -> (Vec<[usize; 3]>, Vec<usize>) {
    let mut survivors = events.to_vec();
    let mut remaining = Vec::with_capacity(filters.len());
    let mut stats = Vec::with_capacity(filters.len());
    for filter in filters {
        let mut known = 0;
        let mut matching = 0;
        for (i, (&event, left)) in events.iter().zip(&mut survivors).enumerate() {
            known += (event & filter.valid[i]).count_ones() as usize;
            matching += (event & filter.bits[i]).count_ones() as usize;
            *left &= filter.bits[i];
        }
        stats.push([matching, known - matching, occurrences - known]);
        remaining.push(popcount(&survivors));
    }
    (stats, remaining)
}

fn group_at(query: &Query, series: &[Series], i: usize) -> String {
    query
        .group
        .map_or_else(|| "null".into(), |id| quote(series[id].group(i)))
}

fn group_labels(query: &Query, nodes: &[Node]) -> Vec<(&'static str, &'static str)> {
    let id = match query.group {
        Some(id) => id,
        None => return Vec::new(),
    };
    let mut labels = match &nodes[id] {
        Node::Weekday | Node::Category(0..=5) => DAYS
            .into_iter()
            .zip([
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "closed (no session that New York date)",
            ])
            .collect(),
        Node::Trend(_) | Node::Category(6..=8) => TRENDS
            .into_iter()
            .zip([
                "up (close > open)",
                "down (close < open)",
                "flat (close = open)",
            ])
            .collect(),
        _ => vec![("true", "true"), ("false", "false")],
    };
    labels.push(("unknown", "unknown"));
    labels
}

fn format_group_labels(query: &Query, nodes: &[Node]) -> String {
    let entries = group_labels(query, nodes)
        .into_iter()
        .map(|(key, label)| format!("{{\"key\":{},\"label\":{}}}", quote(key), quote(label)))
        .collect::<Vec<_>>();
    format!("[{}]", entries.join(","))
}
