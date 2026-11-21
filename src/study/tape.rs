use crate::Result;
use std::{fs, path::Path};

const MAX_PRICE: i64 = 9_007_199_254_740_991;
const MAX_SLOTS: usize = 1_000_000;

#[derive(Clone, Copy)]
pub(super) struct Bar {
    pub o: i64,
    pub h: i64,
    pub l: i64,
    pub c: i64,
}

impl Bar {
    pub fn body(self) -> i64 {
        (self.c - self.o).abs()
    }

    pub fn prices(self) -> [f64; 4] {
        [self.o as f64, self.h as f64, self.l as f64, self.c as f64]
    }
}

pub(super) struct Tape {
    pub start: i64,
    pub interval: i64,
    pub bars: Vec<Option<Bar>>,
    absent: Vec<usize>,
}

pub(super) fn number<T: std::str::FromStr>(text: Option<&str>, label: &str) -> Result<T> {
    text.and_then(|s| s.parse().ok())
        .ok_or_else(|| format!("invalid or missing {label}"))
}

fn price(text: Option<&str>) -> Result<i64> {
    let text = text.ok_or("missing price")?;
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    if whole.is_empty()
        || fraction.len() > 2
        || text.ends_with('.')
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|b| b.is_ascii_digit())
    {
        return Err("price must be a positive integer-cent decimal".into());
    }
    let whole: i64 = number(Some(whole), "price")?;
    let cents = fraction
        .bytes()
        .zip([10, 1])
        .map(|(b, place)| i64::from(b - b'0') * place)
        .sum::<i64>();
    whole
        .checked_mul(100)
        .and_then(|p| p.checked_add(cents))
        .filter(|p| (1..=MAX_PRICE).contains(p))
        .ok_or_else(|| "price is outside the exact tick range".into())
}

impl Tape {
    pub fn read(path: impl AsRef<Path>, interval: i64) -> Result<Self> {
        Self::parse(
            &fs::read_to_string(path).map_err(|err| err.to_string())?,
            interval,
        )
    }

    fn parse(csv: &str, interval: i64) -> Result<Self> {
        if !(60_000..=86_400_000).contains(&interval) {
            return Err("unsupported study interval".into());
        }
        let mut lines = csv.lines();
        if lines.next() != Some("open_ms,open,high,low,close,volume") {
            return Err("expected the study recording CSV header".into());
        }
        let mut bars = Vec::new();
        let mut start = 0;
        for (row, line) in lines.enumerate() {
            let mut cells = line.split(',');
            let t: i64 = number(cells.next(), "bar open timestamp")?;
            let o = price(cells.next())?;
            let h = price(cells.next())?;
            let l = price(cells.next())?;
            let c = price(cells.next())?;
            let volume: f64 = number(cells.next(), "volume")?;
            let valid_timestamp = (0..=MAX_PRICE - interval).contains(&t) && t % interval == 0;
            let valid_bar = l <= o.min(c) && o.max(c) <= h && volume.is_finite() && volume >= 0.0;
            if !(valid_timestamp && valid_bar && cells.next().is_none()) {
                return Err(format!("invalid recording row {}", row + 2));
            }
            if row == 0 {
                start = t;
            }
            let slot = usize::try_from((t - start) / interval).map_err(|_| "reordered bars")?;
            if slot < bars.len() || slot >= MAX_SLOTS {
                return Err(
                    "reordered or duplicate bar, or study grid exceeds 1,000,000 slots".into(),
                );
            }
            bars.resize(slot, None);
            bars.push(Some(Bar { o, h, l, c }));
        }
        if bars.is_empty() {
            return Err("study recording is empty".into());
        }
        let mut absent = vec![0];
        for bar in &bars {
            absent.push(absent[absent.len() - 1] + usize::from(bar.is_none()));
        }
        Ok(Self {
            start,
            interval,
            bars,
            absent,
        })
    }

    pub fn close(&self, slot: usize) -> i64 {
        self.start + (slot as i64 + 1) * self.interval
    }

    pub fn complete(&self, start: usize, end: usize) -> bool {
        self.absent[end] == self.absent[start]
    }

    pub fn absent(&self) -> usize {
        self.absent[self.bars.len()]
    }
}

pub(super) const DAYS: [&str; 6] = ["mon", "tue", "wed", "thu", "fri", "closed"];
pub(super) const TRENDS: [&str; 3] = ["up", "down", "flat"];

pub(super) struct Calendar {
    start: i64,
    end: i64,
    sessions: Vec<(i64, i64, u8)>,
}

impl Calendar {
    pub fn read(path: impl AsRef<Path>) -> Result<Self> {
        let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
        let mut lines = text.lines();
        let mut header = lines.next().ok_or("empty calendar")?.split_whitespace();
        let start = number(header.next(), "calendar coverage start")?;
        let end = number(header.next(), "calendar coverage end")?;
        if !(0..end).contains(&start) || end > MAX_PRICE || header.next().is_some() {
            return Err("invalid calendar coverage".into());
        }
        let mut sessions = Vec::new();
        let mut next_day = start;
        for line in lines {
            let mut fields = line.split_whitespace();
            let day: i64 = number(fields.next(), "session day start")?;
            let close: i64 = number(fields.next(), "session close")?;
            let index = fields
                .next()
                .and_then(|s| DAYS[..5].iter().position(|x| *x == s))
                .ok_or("invalid session weekday")?;
            if day < next_day
                || day > end - 86_400_000
                || !(day..day + 86_400_000).contains(&close)
                || fields.next().is_some()
            {
                return Err("invalid or overlapping session rows".into());
            }
            next_day = day + 86_400_000;
            sessions.push((day, close, index as u8));
        }
        Ok(Self {
            start,
            end,
            sessions,
        })
    }

    pub fn weekday(&self, t: i64) -> Option<u8> {
        if t < self.start || t >= self.end {
            return None;
        }
        let i = self.sessions.partition_point(|s| s.0 <= t);
        Some(match self.sessions[..i].last() {
            Some((day, _, wd)) if t < day + 86_400_000 => *wd,
            _ => 5,
        })
    }

    pub fn tail(&self, t: i64, last: i64) -> Option<bool> {
        let i = self.sessions.partition_point(|s| s.1 < t);
        if self.sessions.get(i).map_or(false, |s| s.1 - last < t) {
            Some(true)
        } else if t >= self.start && t + last <= self.end {
            Some(false)
        } else {
            None
        }
    }
}
