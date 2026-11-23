//! The portable Composer/Query drawing packet. Shape identity uses the
//! ordinary geometry encoder and canonical parser.

use crate::{
    engine_json::{self, Value},
    geometry::{
        explore::{encode_drawing, Reading},
        matching::{Pin, Price},
        GeometryMode, GeometryPattern,
    },
    Result,
};

const PLAIN_REVISION: &str = "133e3017ba9143f7dc255df7218ff7bfe46d9d06";
const DIMENSIONS_REVISION: &str = "bd6a0ba32e18548b641267418491bfb5f011a274";

pub(crate) fn protocol() -> String {
    format!(r#"{{"version":1,"plain":"{PLAIN_REVISION}","dimensioned":"{DIMENSIONS_REVISION}"}}"#)
}

pub(crate) struct Drawing {
    pub pattern: GeometryPattern,
    pub rows: Vec<[f64; 4]>,
    pub pins: Vec<Pin>,
    pub skeleton: usize,
    pub stretch: usize,
    pub limit: usize,
    expression: Option<String>,
}

pub(crate) fn read(
    text: &str,
    expected: Option<&str>,
) -> Result<(GeometryPattern, Option<String>)> {
    let drawing = parse(text, expected)?;
    Ok((drawing.pattern, drawing.expression))
}

pub(crate) fn parse(text: &str, expected: Option<&str>) -> Result<Drawing> {
    if text.is_empty() || text.encode_utf16().count() > 96_000 {
        return Err("drawing packet has an invalid size".into());
    }
    let value = engine_json::parse(text)?;
    let packet = value.object()?;
    let revision = value.field("revision")?.text()?;
    if value.field("version")?.number::<f64>()? != 1.0
        || !matches!(revision, PLAIN_REVISION | DIMENSIONS_REVISION)
    {
        return Err("unsupported Composer drawing version".into());
    }
    if let Some(source) = packet.get("coordinates") {
        if source.text()? != "ordinal" {
            return Err("invalid drawing coordinate source".into());
        }
    }
    let mode = if value.field("oriented")?.bool()? {
        GeometryMode::Oriented
    } else {
        GeometryMode::Unoriented
    };
    let bars = value.field("bars")?.array()?;
    let width = bars.len();
    if !(1..=20).contains(&width) {
        return Err("drawing needs 1–20 bars".into());
    }
    let mut rows = Vec::with_capacity(width);
    let mut last = None;
    for bar in bars {
        let v = bar.field("v")?.array()?;
        if v.len() != 4 {
            return Err("invalid drawing price".into());
        }
        let (low, body_low, body_high, high) = (
            finite(&v[0])?,
            finite(&v[1])?,
            finite(&v[2])?,
            finite(&v[3])?,
        );
        if ![low, body_low, body_high, high]
            .iter()
            .all(|p| p.abs() <= 1e12)
            || body_low > body_high
        {
            return Err("invalid drawing price".into());
        }
        let (open, close) = match bar.field("d")?.text()? {
            "u" => (body_low, body_high),
            "d" => (body_high, body_low),
            _ => return Err("invalid drawing direction".into()),
        };
        if last.map_or(false, |previous| open != previous) {
            return Err("the next drawn bar must open at the previous close".into());
        }
        rows.push([open, high, low, close]);
        last = Some(close);
    }
    let skeleton = integer(value.field("skeleton")?, 0, width)?;
    let stretch = integer(value.field("stretch")?, 0, if width == 1 { 0 } else { 4 })?;
    let pins = value.field("pins")?.array()?;
    if pins.len() > width * (4 * width + 1) * 2 {
        return Err("too many drawing pins".into());
    }
    let mut rules = Vec::new();
    let mut search_pins = Vec::with_capacity(pins.len());
    for pin in pins {
        if matches!(pin.object()?.get("color"), Some(Value::Bool(true))) {
            let bar = integer(pin.field("bar")?, 0, width - 1)?;
            search_pins.push(Pin::Colour(bar));
            if mode == GeometryMode::Oriented {
                let [open, _, _, close] = rows[bar];
                let op = relation(close, open);
                let lag = width - 1 - bar;
                push_rule(&mut rules, compare(("close", lag), op, ("open", lag)));
            }
        } else {
            let a = point(pin.field("a")?, width)?;
            let b = point(pin.field("b")?, width)?;
            if a != b {
                let ap = Price::endpoint(a.1, rows[a.0], mode);
                let bp = Price::endpoint(b.1, rows[b.0], mode);
                search_pins.push(Pin::Relation((a.0, ap), (b.0, bp)));
                let op = relation(ap.value(rows[a.0]), bp.value(rows[b.0]));
                let lags = (width - 1 - a.0, width - 1 - b.0);
                push_rule(
                    &mut rules,
                    compare((ap.name(), lags.0), op, (bp.name(), lags.1)),
                );
            }
        }
    }
    let next = value.field("next")?;
    let dir = finite(next.field("dir")?)?;
    if ![-1.0, 0.0, 1.0].contains(&dir)
        || !matches!(next.field("measure")?.text()?, "any" | "bps" | "atr")
        || finite(next.field("bps")?)? <= 0.0
        || finite(next.field("atr")?)? <= 0.0
    {
        return Err("invalid continuation settings".into());
    }
    let limit = finite(value.field("limit")?)?;
    if ![12.0, 24.0, 48.0].contains(&limit) {
        return Err("invalid number of closest windows".into());
    }
    let price = encode_drawing(&rows, mode, Reading::Recorded, &[])?;
    let mut code = price.to_string();
    if let Some(parts) = packet.get("dimensions") {
        let parts = parts.array()?;
        if revision != DIMENSIONS_REVISION || parts.len() > 5 {
            return Err("invalid drawing dimensions".into());
        }
        for part in parts {
            let part = part.text()?;
            if part.contains('|') || part.len() > 200 {
                return Err("invalid drawing dimension part".into());
            }
            code.push('|');
            code.push_str(part);
        }
    }
    let pattern = code.parse()?;
    if expected.map_or(false, |expected| expected != code) {
        return Err("the drawing and exact g1 disagree".into());
    }
    let expression = if rules.is_empty() {
        None
    } else {
        let rules = rules.join(" and ");
        Some(if width == 1 {
            rules
        } else {
            format!("candle_window({rules}, bars: {width})")
        })
    };
    Ok(Drawing {
        pattern,
        rows,
        pins: search_pins,
        skeleton,
        stretch,
        limit: limit as usize,
        expression,
    })
}

fn point(value: &Value, width: usize) -> Result<(usize, &str)> {
    let bar = integer(value.field("bar")?, 0, width - 1)?;
    let part = value.field("part")?.text()?;
    if !matches!(part, "L" | "B" | "T" | "H") {
        return Err("invalid drawing pin point".into());
    }
    Ok((bar, part))
}

fn relation(left: f64, right: f64) -> &'static str {
    if left < right {
        "below"
    } else if left > right {
        "above"
    } else {
        "equal"
    }
}

fn compare((left, left_lag): (&str, usize), op: &str, (right, right_lag): (&str, usize)) -> String {
    format!("candle_relation(price({left}, bars_ago: {left_lag}), is: {op}, right: price({right}, bars_ago: {right_lag}))")
}

fn push_rule(rules: &mut Vec<String>, rule: String) {
    if !rules.contains(&rule) {
        rules.push(rule);
    }
}

fn finite(value: &Value) -> Result<f64> {
    let value: f64 = value.number()?;
    if value.is_finite() {
        Ok(value)
    } else {
        Err("drawing number must be finite".into())
    }
}

fn integer(value: &Value, min: usize, max: usize) -> Result<usize> {
    let value = finite(value)?;
    if value.fract() == 0.0 && (min as f64..=max as f64).contains(&value) {
        Ok(value as usize)
    } else {
        Err("drawing integer is outside its range".into())
    }
}
