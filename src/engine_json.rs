//! JSON string decoding used by study text and portable engine artifacts.

use crate::Result;

/// Takes one JSON string, including its quotes, and returns the remaining text.
pub(crate) fn string(text: &str) -> Result<(String, &str)> {
    let mut rest = text.strip_prefix('"').ok_or("expected a JSON string")?;
    let mut out = String::new();
    while let Some(ch) = rest.chars().next() {
        rest = &rest[ch.len_utf8()..];
        match ch {
            '"' => return Ok((out, rest)),
            '\\' => {
                let escape = rest
                    .as_bytes()
                    .first()
                    .copied()
                    .ok_or("unterminated escape")?;
                if !escape.is_ascii() {
                    return Err("invalid JSON escape".into());
                }
                rest = &rest[1..];
                out.push(match escape {
                    b'"' => '"',
                    b'\\' => '\\',
                    b'/' => '/',
                    b'b' => '\u{8}',
                    b'f' => '\u{c}',
                    b'n' => '\n',
                    b'r' => '\r',
                    b't' => '\t',
                    b'u' => {
                        let (first, tail) = hex_quad(rest)?;
                        rest = tail;
                        let mut scalar = u32::from(first);
                        if (0xd800..=0xdbff).contains(&first) {
                            let (second, tail) =
                                hex_quad(rest.strip_prefix("\\u").ok_or("missing low surrogate")?)?;
                            if !(0xdc00..=0xdfff).contains(&second) {
                                return Err("invalid low surrogate".into());
                            }
                            rest = tail;
                            scalar = 0x1_0000
                                + (u32::from(first - 0xd800) << 10)
                                + u32::from(second - 0xdc00);
                        }
                        char::from_u32(scalar).ok_or("invalid Unicode escape")?
                    }
                    _ => return Err("invalid JSON escape".into()),
                });
            }
            ch if ch < ' ' => return Err("raw control character in JSON string".into()),
            ch => out.push(ch),
        }
    }
    Err("unterminated JSON string".into())
}

fn hex_quad(rest: &str) -> Result<(u16, &str)> {
    let prefix = rest.get(..4).ok_or("short Unicode escape")?;
    if !prefix.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid Unicode escape".into());
    }
    Ok((
        u16::from_str_radix(prefix, 16).expect("four hex digits"),
        &rest[4..],
    ))
}

#[derive(Debug)]
pub(crate) enum Value {
    Null,
    Bool(bool),
    Number(String),
    Text(String),
    Array(Vec<Value>),
    Object(std::collections::BTreeMap<String, Value>),
}

impl Value {
    pub fn array(&self) -> Result<&[Self]> {
        match self {
            Self::Array(values) => Ok(values),
            _ => Err("expected a JSON array".into()),
        }
    }

    pub fn object(&self) -> Result<&std::collections::BTreeMap<String, Self>> {
        match self {
            Self::Object(values) => Ok(values),
            _ => Err("expected a JSON object".into()),
        }
    }

    pub fn text(&self) -> Result<&str> {
        match self {
            Self::Text(text) => Ok(text),
            _ => Err("expected a JSON string".into()),
        }
    }

    pub fn field(&self, key: &str) -> Result<&Self> {
        self.object()?
            .get(key)
            .ok_or_else(|| format!("missing JSON field {key}"))
    }

    pub fn bool(&self) -> Result<bool> {
        match self {
            Self::Bool(value) => Ok(*value),
            _ => Err("expected a JSON Boolean".into()),
        }
    }

    pub fn number<T: std::str::FromStr>(&self) -> Result<T> {
        match self {
            Self::Number(value) => value.parse().map_err(|_| "invalid JSON number".into()),
            _ => Err("expected a JSON number".into()),
        }
    }
}

pub(crate) fn parse(text: &str) -> Result<Value> {
    let (value, rest) = parse_value(text, 0)?;
    if whitespace(rest).is_empty() {
        Ok(value)
    } else {
        Err("trailing JSON content".into())
    }
}

fn whitespace(text: &str) -> &str {
    text.trim_start_matches([' ', '\r', '\n', '\t'])
}

fn parse_value(text: &str, depth: usize) -> Result<(Value, &str)> {
    if depth > 48 {
        return Err("JSON artifact is nested too deeply".into());
    }
    let text = whitespace(text);
    match text.as_bytes().first() {
        Some(b'"') => string(text).map(|(text, rest)| (Value::Text(text), rest)),
        Some(b'[') => {
            let mut values = Vec::new();
            let mut rest = whitespace(&text[1..]);
            if let Some(tail) = rest.strip_prefix(']') {
                return Ok((Value::Array(values), tail));
            }
            loop {
                let (value, tail) = parse_value(rest, depth + 1)?;
                values.push(value);
                let tail = whitespace(tail);
                if let Some(tail) = tail.strip_prefix(']') {
                    return Ok((Value::Array(values), tail));
                }
                rest = tail.strip_prefix(',').ok_or("expected ',' or ']'")?;
            }
        }
        Some(b'{') => {
            let mut values = std::collections::BTreeMap::new();
            let mut rest = whitespace(&text[1..]);
            if let Some(tail) = rest.strip_prefix('}') {
                return Ok((Value::Object(values), tail));
            }
            loop {
                let (key, tail) = string(whitespace(rest))?;
                let tail = whitespace(tail).strip_prefix(':').ok_or("expected ':'")?;
                let (value, tail) = parse_value(tail, depth + 1)?;
                if values.insert(key, value).is_some() {
                    return Err("duplicate JSON object field".into());
                }
                let tail = whitespace(tail);
                if let Some(tail) = tail.strip_prefix('}') {
                    return Ok((Value::Object(values), tail));
                }
                rest = tail.strip_prefix(',').ok_or("expected ',' or '}'")?;
            }
        }
        Some(b't') => text
            .strip_prefix("true")
            .map(|rest| (Value::Bool(true), rest))
            .ok_or_else(|| "invalid JSON value".into()),
        Some(b'f') => text
            .strip_prefix("false")
            .map(|rest| (Value::Bool(false), rest))
            .ok_or_else(|| "invalid JSON value".into()),
        Some(b'n') => text
            .strip_prefix("null")
            .map(|rest| (Value::Null, rest))
            .ok_or_else(|| "invalid JSON value".into()),
        Some(b'-' | b'0'..=b'9') => {
            let rest = number(text)?;
            Ok((
                Value::Number(text[..text.len() - rest.len()].to_owned()),
                rest,
            ))
        }
        _ => Err("invalid JSON value".into()),
    }
}

fn number(input: &str) -> Result<&str> {
    let digits = |text: &str| text.bytes().take_while(u8::is_ascii_digit).count();
    let input = input.strip_prefix('-').unwrap_or(input);
    let whole = digits(input);
    if whole == 0 || (whole > 1 && input.starts_with('0')) {
        return Err("invalid JSON integer".into());
    }
    let mut rest = &input[whole..];
    if let Some(fraction) = rest.strip_prefix('.') {
        let n = digits(fraction);
        if n == 0 {
            return Err("invalid JSON fraction".into());
        }
        rest = &fraction[n..];
    }
    if let Some(exponent) = rest.strip_prefix(['e', 'E']) {
        let exponent = exponent.strip_prefix(['+', '-']).unwrap_or(exponent);
        let n = digits(exponent);
        if n == 0 {
            return Err("invalid JSON exponent".into());
        }
        rest = &exponent[n..];
    }
    Ok(rest)
}
