//! Opt-in Phase 3 causal two-candle feature export using Phase 2 Schema.
//! Outputs features for every source row without reading future outcomes.
use filang::{
    geometry::{BodyDirection, Boundary, GeometryMode, GeometryPattern},
    geometry_abstraction::{Endpoint, EndpointPair, Schema, Signature},
    Result,
};
use std::{
    cmp::Ordering,
    env,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, BufWriter, Write},
    path::PathBuf,
};

#[derive(Clone, Copy)]
struct Bar {
    timestamp: i64,
    open: f64,
    high: f64,
    low: f64,
    close: f64,
}

impl Bar {
    fn parse(line: &str, minutes: i64) -> Result<Self> {
        let fields = line.split(',').collect::<Vec<_>>();
        if fields.len() != 6 {
            return Err("QINF: expected 6 CSV columns".into());
        }
        let timestamp = fields[0]
            .parse::<i64>()
            .map_err(|_| "QINF: bad timestamp")?;
        let mut v = [0.0; 5];
        for (i, field) in fields[1..].iter().enumerate() {
            v[i] = field.parse::<f64>().map_err(|_| "QINF: bad float")?;
            if !v[i].is_finite() {
                return Err("QINF: nonfinite float".into());
            }
        }
        if timestamp.rem_euclid(minutes * 60) != 0
            || v[0] <= 0.0
            || v[1] <= 0.0
            || v[2] <= 0.0
            || v[3] <= 0.0
            || v[1] < v[0].max(v[3])
            || v[2] > v[0].min(v[3])
            || v[4] < 0.0
        {
            return Err("QINF: misaligned or invalid OHLCV".into());
        }
        Ok(Self {
            timestamp,
            open: v[0],
            high: v[1],
            low: v[2],
            close: v[3],
        })
    }
    fn ohlc(self) -> [f64; 4] {
        [self.open, self.high, self.low, self.close]
    }
}

fn schema_pair(a: Boundary, b: Boundary) -> Result<EndpointPair> {
    EndpointPair::new(Endpoint::new(0, a), Endpoint::new(1, b))
}

fn schemas() -> Result<[Schema; 3]> {
    let mut body = Vec::with_capacity(4);
    let mut range = Vec::with_capacity(4);
    for a in [Boundary::BodyLow, Boundary::BodyHigh] {
        for b in [Boundary::BodyLow, Boundary::BodyHigh] {
            body.push(schema_pair(a, b)?);
        }
    }
    for a in [Boundary::Low, Boundary::High] {
        for b in [Boundary::Low, Boundary::High] {
            range.push(schema_pair(a, b)?);
        }
    }
    let body = Schema::new(2, GeometryMode::Oriented, body, vec![0, 1])?;
    let range = Schema::new(2, GeometryMode::Oriented, range, vec![])?;
    let joint = body.join(&range)?;
    Ok([body, range, joint])
}

fn code(sig: &Signature) -> u32 {
    let mut number = 0u32;
    for value in sig.relations() {
        number = number * 3
            + match value {
                Ordering::Less => 0,
                Ordering::Equal => 1,
                Ordering::Greater => 2,
            };
    }
    for value in sig.directions() {
        number = number * 3
            + match value {
                BodyDirection::Down => 0,
                BodyDirection::Flat => 1,
                BodyDirection::Up => 2,
            };
    }
    number
}

fn sign(a: f64, b: f64) -> i8 {
    if a > b {
        1
    } else if a < b {
        -1
    } else {
        0
    }
}

fn export(input: PathBuf, output: PathBuf, minutes: i64) -> Result<String> {
    if minutes <= 0 {
        return Err("QINF: minutes must be positive".into());
    }
    let mut source = BufReader::new(fs::File::open(input).map_err(|e| e.to_string())?);
    let mut header = String::new();
    source.read_line(&mut header).map_err(|e| e.to_string())?;
    if header.trim_end_matches(&['\r', '\n'][..]) != "timestamp,open,high,low,close,volume" {
        return Err("QINF: unexpected CSV header".into());
    }
    if !output.parent().ok_or("QINF: output lacks parent")?.is_dir() {
        return Err("QINF: output directory absent".into());
    }
    let temp = output.with_extension("pending");
    if output.exists() || temp.exists() {
        return Err("QINF: output already exists; use a fresh run path".into());
    }
    let mut writer = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)
            .map_err(|e| e.to_string())?,
    );
    let outcome = (|| -> Result<(usize, usize)> {
        writer
            .write_all(b"index\ttimestamp\tvalid\tlag\tbody\trange\tjoint\n")
            .map_err(|e| e.to_string())?;
        let bases = schemas()?;
        let mut prior: Option<Bar> = None;
        let mut rows = 0usize;
        let mut valid = 0usize;
        for line in source.lines() {
            let line = line.map_err(|e| e.to_string())?;
            if line.trim().is_empty() {
                return Err("QINF: empty CSV row".into());
            }
            let bar = Bar::parse(&line, minutes)?;
            if let Some(past) = prior {
                if bar.timestamp <= past.timestamp {
                    return Err("QINF: unordered source rows".into());
                }
                if bar.timestamp - past.timestamp == minutes * 60 {
                    let geometry = GeometryPattern::from_ohlc(
                        &[bar.ohlc(), past.ohlc()],
                        GeometryMode::Oriented,
                    )?;
                    let codes = [
                        code(&bases[0].signature(&geometry)?),
                        code(&bases[1].signature(&geometry)?),
                        code(&bases[2].signature(&geometry)?),
                    ];
                    writeln!(
                        writer,
                        "{rows}\t{}\t1\t{}\t{}\t{}\t{}",
                        bar.timestamp,
                        sign(bar.close, past.close),
                        codes[0],
                        codes[1],
                        codes[2]
                    )
                    .map_err(|e| e.to_string())?;
                    valid += 1;
                } else {
                    writeln!(writer, "{rows}\t{}\t0\t-\t-\t-\t-", bar.timestamp)
                        .map_err(|e| e.to_string())?;
                }
            } else {
                writeln!(writer, "{rows}\t{}\t0\t-\t-\t-\t-", bar.timestamp)
                    .map_err(|e| e.to_string())?;
            }
            prior = Some(bar);
            rows += 1;
        }
        if rows < 4 {
            return Err("QINF: too few rows".into());
        }
        writer.flush().map_err(|e| e.to_string())?;
        writer.get_ref().sync_all().map_err(|e| e.to_string())?;
        Ok((rows, valid))
    })();
    drop(writer);
    match outcome {
        Ok((rows, valid)) => {
            fs::rename(&temp, &output).map_err(|e| e.to_string())?;
            Ok(format!(
                "{{\"status\":\"ok\",\"rows\":{rows},\"valid\":{valid}}}"
            ))
        }
        Err(e) => {
            let _ = fs::remove_file(&temp);
            Err(e)
        }
    }
}

fn main() {
    let args = env::args().skip(1).collect::<Vec<_>>();
    let result =
        if args.len() != 6 || args[0] != "--data" || args[2] != "--out" || args[4] != "--minutes" {
            Err("usage: geometry_abstraction_features --data CSV --out TSV --minutes N".to_string())
        } else {
            match args[5].parse::<i64>() {
                Ok(minutes) => export(args[1].clone().into(), args[3].clone().into(), minutes),
                Err(_) => Err("QINF: invalid minutes".into()),
            }
        };
    match result {
        Ok(value) => println!("{value}"),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    }
}
