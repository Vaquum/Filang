use crate::{hash::sha256, Result};
use std::{fmt::Write as _, fs};

#[derive(Clone, Debug)]
pub struct Data {
    pub timestamps: Vec<i64>,
    /// open, high, low, close, base-asset volume. UTC opening timestamps.
    pub columns: [Vec<f64>; 5],
    pub interval: i64,
    pub digest: String,
}
impl Data {
    pub fn len(&self) -> usize {
        self.timestamps.len()
    }
    pub fn is_empty(&self) -> bool {
        self.timestamps.is_empty()
    }
    pub fn read(path: &str, interval: i64) -> Result<Self> {
        let bytes = fs::read(path).map_err(|e| format!("read {path}: {e}"))?;
        let text = std::str::from_utf8(&bytes).map_err(|e| e.to_string())?;
        let mut data = Self::parse(text, interval)?;
        data.digest = sha256(&bytes);
        Ok(data)
    }
    pub fn parse(text: &str, interval: i64) -> Result<Self> {
        if interval <= 0 {
            return Err("interval must be positive".into());
        }
        let mut rows = text.lines();
        if rows.next() != Some("timestamp,open,high,low,close,volume") {
            return Err("CSV header must be timestamp,open,high,low,close,volume".into());
        }
        let mut out = Self {
            timestamps: vec![],
            columns: std::array::from_fn(|_| Vec::new()),
            interval,
            digest: sha256(text.as_bytes()),
        };
        for (index, row) in rows.enumerate() {
            let fields: Vec<_> = row.split(',').collect();
            if fields.len() != 6 {
                return Err(format!("CSV line {}: expected 6 fields", index + 2));
            }
            let t = fields[0]
                .parse::<i64>()
                .map_err(|_| format!("invalid timestamp line {}", index + 2))?;
            if let Some(last) = out.timestamps.last() {
                if t - *last != interval {
                    return Err(format!("non-contiguous/duplicate timestamp at {t}; gaps must be resolved explicitly, never compressed"));
                }
            }
            let mut v = [0.0f64; 5];
            for j in 0..5 {
                v[j] = fields[j + 1]
                    .parse()
                    .map_err(|_| format!("invalid numeric field line {}", index + 2))?;
            }
            if v.iter().any(|x| !x.is_finite())
                || v[..4].iter().any(|x| *x <= 0.0)
                || v[4] < 0.0
                || v[1] < v[0].max(v[3])
                || v[2] > v[0].min(v[3])
                || v[1] < v[2]
            {
                return Err(format!("invalid OHLCV line {}", index + 2));
            }
            out.timestamps.push(t);
            for (col, value) in out.columns.iter_mut().zip(v) {
                col.push(value);
            }
        }
        if out.len() < 4 {
            return Err("at least four bars required".into());
        }
        Ok(out)
    }
    pub fn index(&self, time: i64) -> usize {
        self.timestamps.partition_point(|x| *x < time)
    }
    pub fn prefix(&self, n: usize) -> Self {
        Self {
            timestamps: self.timestamps[..n].to_vec(),
            columns: std::array::from_fn(|j| self.columns[j][..n].to_vec()),
            interval: self.interval,
            digest: format!("{}:prefix:{n}", self.digest),
        }
    }
}
/// Strict Gregorian YYYY-MM-DD, UTC midnight.
pub fn date(s: &str) -> Result<i64> {
    let p: Vec<_> = s.split('-').collect();
    if p.len() != 3 || p[0].len() != 4 || p[1].len() != 2 || p[2].len() != 2 {
        return Err(format!("invalid date {s}"));
    }
    let y = p[0]
        .parse::<i64>()
        .map_err(|_| format!("invalid date {s}"))?;
    let m = p[1]
        .parse::<i64>()
        .map_err(|_| format!("invalid date {s}"))?;
    let d = p[2]
        .parse::<i64>()
        .map_err(|_| format!("invalid date {s}"))?;
    let leap = y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let lengths = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if !(1970..=2200).contains(&y)
        || !(1..=12).contains(&m)
        || d < 1
        || d > lengths[(m - 1) as usize]
    {
        return Err(format!("invalid date {s}"));
    }
    let yy = y - if m <= 2 { 1 } else { 0 };
    let era = yy / 400;
    let yoe = yy - era * 400;
    let mp = m + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    Ok((era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468) * 86400)
}
pub fn write_synthetic(path: &str, n: usize) -> Result<()> {
    let mut state = 173u64;
    let mut close = 100.0;
    let mut out = String::from("timestamp,open,high,low,close,volume\n");
    let start = date("2020-01-01")?;
    for i in 0..n {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        let noise = (state as f64 / u64::MAX as f64 - 0.5) * 0.012;
        let open = close;
        close = open * (1.0 + noise + 0.001 * (i as f64 / 70.0).sin());
        writeln!(
            &mut out,
            "{},{:.12},{:.12},{:.12},{:.12},{:.12}",
            start + i as i64 * 14400,
            open,
            open.max(close) * 1.002,
            open.min(close) * 0.998,
            close,
            100.0 + 20.0 * (i as f64 / 9.0).sin()
        )
        .expect("String writes are infallible");
    }
    fs::write(path, out).map_err(|e| e.to_string())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dates() {
        assert_eq!(date("1970-01-01").unwrap(), 0);
        assert_eq!(date("2024-01-01").unwrap(), 1704067200);
        assert!(date("2023-02-29").is_err());
    }
    #[test]
    fn reject_gaps_and_bad_prices() {
        let good="timestamp,open,high,low,close,volume\n0,1,2,1,2,4\n1,2,3,1,2,4\n2,2,3,1,2,4\n3,2,3,1,2,4\n";
        assert!(Data::parse(good, 1).is_ok());
        assert!(Data::parse(&good.replace("\n2,", "\n5,"), 1).is_err());
        assert!(Data::parse(&good.replace("0,1,2,1,2,4", "0,0,2,1,2,4"), 1).is_err());
    }
}
