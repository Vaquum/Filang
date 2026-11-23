use super::tape::Bar;
use crate::Result;
use std::cmp::Ordering;

pub(super) struct Ratio {
    num: Decimal,
    den: Decimal,
}

struct Decimal {
    small: Option<u128>,
    digits: Vec<u8>,
}

impl Decimal {
    fn parse(text: &str) -> Result<Self> {
        if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
            return Err("ratio expects unsigned decimal integers".into());
        }
        let text = text.trim_start_matches('0');
        Ok(Self {
            small: if text.is_empty() {
                Some(0)
            } else {
                text.parse().ok()
            },
            digits: text.bytes().rev().map(|b| b - b'0').collect(),
        })
    }

    fn multiply(&self, scale: u64) -> Vec<u8> {
        if scale == 0 {
            return Vec::new();
        }
        let mut carry = 0;
        let mut digits = Vec::with_capacity(self.digits.len() + 16);
        for &d in &self.digits {
            let x = u64::from(d) * scale + carry;
            digits.push((x % 10) as u8);
            carry = x / 10;
        }
        while carry > 0 {
            digits.push((carry % 10) as u8);
            carry /= 10;
        }
        digits
    }
}

impl Ratio {
    pub fn parse(text: &str) -> Result<Self> {
        let ratio = Self::magnitude(text)?;
        if ratio.compare(1, 1) == Ordering::Less {
            return Err("expected a ratio between zero and one".into());
        }
        Ok(ratio)
    }

    pub fn magnitude(text: &str) -> Result<Self> {
        let (num, den) = text
            .split_once('/')
            .ok_or("expected numerator/denominator")?;
        let ratio = Self {
            num: Decimal::parse(num)?,
            den: Decimal::parse(den)?,
        };
        if ratio.den.digits.is_empty() {
            return Err("expected a nonzero denominator".into());
        }
        Ok(ratio)
    }

    /// Compare lhs to rhs * ratio in exact ticks, including long decimal thresholds.
    pub fn compare(&self, lhs: i64, rhs: i64) -> Ordering {
        let lhs = lhs as u64;
        let rhs = rhs as u64;
        if let (Some(a), Some(b)) = (
            self.den.small.and_then(|x| x.checked_mul(u128::from(lhs))),
            self.num.small.and_then(|x| x.checked_mul(u128::from(rhs))),
        ) {
            return a.cmp(&b);
        }
        let a = self.den.multiply(lhs);
        let b = self.num.multiply(rhs);
        a.len()
            .cmp(&b.len())
            .then_with(|| a.iter().rev().cmp(b.iter().rev()))
    }
}

type Words<'a> = std::str::SplitWhitespace<'a>;

#[derive(Clone, Copy)]
pub(super) enum Field {
    Open,
    High,
    Low,
    Close,
    BodyLow,
    BodyHigh,
    Body,
    Range,
    Lower,
    Upper,
    Direction,
}

impl Field {
    pub fn parse(s: &str) -> Result<Self> {
        Ok(match s {
            "open" => Self::Open,
            "high" => Self::High,
            "low" => Self::Low,
            "close" => Self::Close,
            "bodyLow" | "body_low" => Self::BodyLow,
            "bodyHigh" | "body_high" => Self::BodyHigh,
            "body" => Self::Body,
            "range" => Self::Range,
            "lower" => Self::Lower,
            "upper" => Self::Upper,
            "dir" => Self::Direction,
            _ => return Err("unknown named-pattern field".into()),
        })
    }

    pub fn value(self, b: Bar) -> i64 {
        match self {
            Self::Open => b.o,
            Self::High => b.h,
            Self::Low => b.l,
            Self::Close => b.c,
            Self::BodyLow => b.o.min(b.c),
            Self::BodyHigh => b.o.max(b.c),
            Self::Body => b.body(),
            Self::Range => b.h - b.l,
            Self::Lower => b.o.min(b.c) - b.l,
            Self::Upper => b.h - b.o.max(b.c),
            Self::Direction => (b.c - b.o).signum(),
        }
    }

    fn drawing_value(self, [o, h, l, c]: [f64; 4]) -> f64 {
        match self {
            Self::Open => o,
            Self::High => h,
            Self::Low => l,
            Self::Close => c,
            Self::BodyLow => o.min(c),
            Self::BodyHigh => o.max(c),
            Self::Body => (c - o).abs(),
            Self::Range => h - l,
            Self::Lower => o.min(c) - l,
            Self::Upper => h - o.max(c),
            Self::Direction => f64::from(u8::from(c > o)) - f64::from(u8::from(c < o)),
        }
    }
}

enum Operand {
    Constant(i64),
    Price(bool, Field, i64),
}

impl Operand {
    fn parse(text: &str, bars: usize) -> Result<Self> {
        if let Ok(value) = text.parse::<i64>() {
            return Ok(Self::Constant(value));
        }
        let (mul, field) = match text.split_once('*') {
            Some((scale, field)) => {
                let mul = scale
                    .parse::<i64>()
                    .map_err(|_| "invalid pattern multiplier")?;
                if !(1..=64).contains(&mul) {
                    return Err("pattern multiplier outside bounds".into());
                }
                (mul, field)
            }
            None => (1, text),
        };
        let (previous, field) = field
            .strip_prefix("prev.")
            .map_or((false, field), |s| (true, s));
        if previous && bars != 2 {
            return Err("one-bar rule references previous candle".into());
        }
        Ok(Self::Price(previous, Field::parse(field)?, mul))
    }

    fn value(&self, current: Bar, previous: Bar) -> i64 {
        match self {
            Self::Constant(n) => *n,
            Self::Price(prior, field, mul) => {
                field.value(if *prior { previous } else { current }) * mul
            }
        }
    }
}

pub(super) struct CandleRule {
    bars: usize,
    expr: Expression,
}

enum Expression {
    Compare(crate::rules::Cmp, Operand, Operand),
    Compound(bool, Vec<Expression>),
}

impl CandleRule {
    pub(super) fn width(&self) -> usize {
        self.bars
    }

    pub fn parse(bars: usize, words: &mut Words<'_>) -> Result<Self> {
        if !(1..=2).contains(&bars) {
            return Err("named rule requires one or two bars".into());
        }
        Ok(Self {
            bars,
            expr: Expression::parse(words, bars, 0)?,
        })
    }

    pub fn eval(&self, current: Bar, previous: Option<Bar>) -> Option<bool> {
        let previous = if self.bars == 2 { previous? } else { current };
        Some(self.expr.eval(|operand| operand.value(current, previous)))
    }

    pub fn matches_drawing(&self, rows: &[[f64; 4]]) -> bool {
        let current = rows[rows.len() - 1];
        let previous = rows[rows.len() - self.bars];
        self.expr.eval(|operand| match *operand {
            Operand::Constant(n) => n as f64,
            Operand::Price(prior, field, mul) => {
                field.drawing_value(if prior { previous } else { current }) * mul as f64
            }
        })
    }
}

impl Expression {
    fn parse(input: &mut Words<'_>, bars: usize, depth: usize) -> Result<Self> {
        if depth == 32 {
            return Err("candle rule nesting limit".into());
        }
        let op = input.next().ok_or("missing candle rule operator")?;
        if let Some((logic, n)) = op.split_once(':') {
            let and = match logic {
                "all" => true,
                "any" => false,
                _ => return Err("unknown candle logic".into()),
            };
            let n = n.parse::<usize>().map_err(|_| "bad candle rule arity")?;
            if !(1..=64).contains(&n) {
                return Err("candle rule arity outside bounds".into());
            }
            let items = (0..n)
                .map(|_| Self::parse(input, bars, depth + 1))
                .collect::<Result<_>>()?;
            Ok(Self::Compound(and, items))
        } else {
            let op = crate::rules::Cmp::parse(op)?;
            let mut next = || Operand::parse(input.next().ok_or("missing candle operand")?, bars);
            Ok(Self::Compare(op, next()?, next()?))
        }
    }

    fn eval<T: PartialOrd>(&self, value: impl Fn(&Operand) -> T + Copy) -> bool {
        match self {
            Self::Compound(true, items) => items.iter().all(|x| x.eval(value)),
            Self::Compound(false, items) => items.iter().any(|x| x.eval(value)),
            Self::Compare(op, a, b) => {
                use crate::rules::Cmp::*;
                let a = value(a);
                let b = value(b);
                match op {
                    Lt => a < b,
                    Le => a <= b,
                    Gt => a > b,
                    Ge => a >= b,
                    Eq => a == b,
                    Ne => a != b,
                }
            }
        }
    }
}
