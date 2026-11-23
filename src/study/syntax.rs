use crate::{engine_json, Result};
use std::{
    collections::{HashMap, HashSet},
    ops::Range,
};

pub(super) const MAX_DEPTH: usize = 64;
const MAX_TOKENS: usize = 12_288;
const MAX_TEXT: usize = 1_048_576;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(super) enum Literal {
    Name(String),
    Text(String),
    Number(String, bool),
    Duration(Duration),
}

#[derive(Clone, Debug, Eq)]
pub(super) struct Duration {
    pub ms: i64,
    pub text: String,
}

impl PartialEq for Duration {
    fn eq(&self, other: &Self) -> bool {
        self.ms == other.ms
    }
}

impl std::hash::Hash for Duration {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        std::hash::Hash::hash(&self.ms, state);
    }
}

impl Literal {
    pub fn wire_ratio(&self) -> Result<String> {
        let (decimal, pct) = match self {
            Self::Number(decimal, pct) => (decimal, *pct),
            _ => return Err("expected a decimal number or percentage".into()),
        };
        let (whole, fraction) = decimal.split_once('.').unwrap_or((decimal, ""));
        let fraction = fraction.trim_end_matches('0');
        let digits = format!("{whole}{fraction}");
        let numerator = digits.trim_start_matches('0');
        if numerator.is_empty() {
            return Ok("0/1".into());
        }
        let shift = fraction.len() + if pct { 2 } else { 0 };
        let trailing = numerator.len() - numerator.trim_end_matches('0').len();
        let cancel = shift.min(trailing);
        Ok(format!(
            "{}/1{}",
            &numerator[..numerator.len() - cancel],
            "0".repeat(shift - cancel)
        ))
    }
}

#[derive(Debug)]
pub(super) enum Expr {
    Scalar(Literal),
    Choice(usize),
    Vector(Vec<Expr>),
    Call(String, Vec<Argument>),
    Logic(bool, Vec<Expr>),
    Not(Box<Expr>),
    Compare(Comparison, Box<Expr>, Box<Expr>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Comparison {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl Comparison {
    pub fn wire(self) -> &'static str {
        match self {
            Self::Eq => "eq",
            Self::Ne => "ne",
            Self::Lt => "lt",
            Self::Le => "le",
            Self::Gt => "gt",
            Self::Ge => "ge",
        }
    }
}

#[derive(Debug)]
pub(super) struct Argument {
    pub name: Option<String>,
    pub value: Expr,
}

#[derive(Debug)]
pub(super) struct Question {
    pub instrument: String,
    pub interval: i64,
    pub interval_text: String,
    pub bindings: HashMap<String, Expr>,
    pub binding_order: Vec<String>,
    pub choices: Vec<Vec<Literal>>,
    pub find: Expr,
    pub find_span: Range<usize>,
    pub filters: Vec<Expr>,
    pub filter_spans: Vec<Range<usize>>,
    pub group: Option<Expr>,
    pub group_span: Option<Range<usize>>,
    pub measures: Vec<Expr>,
    pub measure_spans: Vec<Range<usize>>,
}

#[derive(Debug)]
enum Kind {
    Keyword(&'static str),
    Scalar(Literal),
    Punct(char),
    Compare(Comparison),
    End,
}

struct Token {
    kind: Kind,
    offset: usize,
}

pub(super) fn question(source: &str) -> Result<Question> {
    let mut parser = Parser::new(source)?;
    parser.require_keyword("on")?;
    let instrument = parser.name()?;
    let duration = match parser.advance() {
        Kind::Scalar(Literal::Duration(duration)) => duration,
        _ => return parser.fail("expected bar duration after instrument"),
    };
    let mut bindings = HashMap::new();
    let mut binding_order = Vec::new();
    while parser.keyword("let") {
        let name = parser.name()?;
        if !matches!(parser.advance(), Kind::Compare(Comparison::Eq)) {
            return parser.fail("expected '=' after the binding name");
        }
        let value = parser.expr(0)?;
        if !matches!(value, Expr::Scalar(_) | Expr::Choice(_)) {
            return Err(format!(
                "binding {name} must be a scalar or choices of scalars"
            ));
        }
        if bindings.insert(name.clone(), value).is_some() {
            return Err(format!("duplicate binding {name}"));
        }
        binding_order.push(name);
    }
    parser.require_keyword("find")?;
    let (find, find_span) = parser.clause(source)?;
    let mut filters = Vec::new();
    let mut filter_spans = Vec::new();
    while parser.keyword("where") {
        let (filter, span) = parser.clause(source)?;
        filters.push(filter);
        filter_spans.push(span);
    }
    let (group, group_span) = if parser.keyword("group") {
        parser.require_keyword("by")?;
        let (group, span) = parser.clause(source)?;
        (Some(group), Some(span))
    } else {
        (None, None)
    };
    let mut measures = Vec::new();
    let mut measure_spans = Vec::new();
    while parser.keyword("measure") {
        match parser.clause(source)? {
            (measure @ Expr::Call(..), span) => {
                measures.push(measure);
                measure_spans.push(span);
            }
            _ => return parser.fail("expected an outcome call after measure"),
        }
    }
    if !matches!(parser.current(), Kind::End) {
        return parser.fail("expected clauses in on, let, find, where, group by, measure order");
    }
    for (name, value) in &bindings {
        let values = match value {
            Expr::Scalar(literal) => std::slice::from_ref(literal),
            Expr::Choice(i) => &parser.choices[*i],
            _ => unreachable!("checked binding"),
        };
        if values
            .iter()
            .any(|lit| matches!(lit, Literal::Name(id) if bindings.contains_key(id)))
        {
            return Err(format!("binding {name} cannot refer to another binding"));
        }
    }
    if parser
        .choices
        .iter()
        .flatten()
        .any(|lit| matches!(lit, Literal::Name(id) if bindings.contains_key(id)))
    {
        return Err("choices cannot refer to a binding".into());
    }
    Ok(Question {
        instrument,
        interval: duration.ms,
        interval_text: duration.text,
        bindings,
        binding_order,
        choices: parser.choices,
        find,
        find_span,
        filters,
        filter_spans,
        group,
        group_span,
        measures,
        measure_spans,
    })
}

pub(super) fn expression(source: &str) -> Result<Expr> {
    let mut parser = Parser::new(source)?;
    let result = parser.expr(0)?;
    if !matches!(parser.current(), Kind::End) || !parser.choices.is_empty() {
        return parser.fail("expected one expression without choices");
    }
    Ok(result)
}

fn keyword(word: &str) -> Option<&'static str> {
    [
        "on", "let", "find", "where", "group", "by", "measure", "and", "or", "not",
    ]
    .into_iter()
    .find(|&keyword| keyword == word)
}

fn id_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn id_next(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || ('\u{300}'..='\u{36f}').contains(&c)
}

fn tokenize(source: &str) -> Result<Vec<Token>> {
    if source.len() > MAX_TEXT {
        return Err("study text exceeds 1 MiB".into());
    }
    let mut tokens = Vec::new();
    let mut rest = source;
    while let Some(ch) = rest.chars().next() {
        let offset = source.len() - rest.len();
        if matches!(ch, ' ' | '\r' | '\n' | '\t') {
            rest = &rest[1..];
            continue;
        }
        if rest.starts_with("--") {
            rest = rest.split_once('\n').map_or("", |(_, after)| after);
            continue;
        }
        if tokens.len() >= MAX_TOKENS {
            return Err("study exceeds the token limit".into());
        }
        let kind = if id_start(ch) {
            let end = rest.find(|c| !id_next(c)).unwrap_or(rest.len());
            let name = &rest[..end];
            rest = &rest[end..];
            match keyword(name) {
                Some(keyword) => Kind::Keyword(keyword),
                None => Kind::Scalar(Literal::Name(name.to_owned())),
            }
        } else if ch.is_ascii_digit() {
            let (kind, remaining) =
                number(rest).map_err(|error| format!("{error} at byte {offset}"))?;
            rest = remaining;
            kind
        } else if ch == '"' {
            let (value, remaining) =
                engine_json::string(rest).map_err(|error| format!("{error} at byte {offset}"))?;
            rest = remaining;
            Kind::Scalar(Literal::Text(value))
        } else {
            rest = &rest[ch.len_utf8()..];
            match ch {
                '(' | ')' | '[' | ']' | '{' | '}' | ':' | ',' | '|' | '%' => Kind::Punct(ch),
                '=' => Kind::Compare(Comparison::Eq),
                '!' | '<' | '>' => {
                    let equal = rest.starts_with('=');
                    if equal {
                        rest = &rest[1..];
                    }
                    Kind::Compare(match (ch, equal) {
                        ('!', true) => Comparison::Ne,
                        ('<', false) => Comparison::Lt,
                        ('<', true) => Comparison::Le,
                        ('>', false) => Comparison::Gt,
                        ('>', true) => Comparison::Ge,
                        _ => return Err(format!("expected != at byte {offset}")),
                    })
                }
                _ => return Err(format!("unexpected {ch:?} at byte {offset}")),
            }
        };
        tokens.push(Token { kind, offset });
    }
    tokens.push(Token {
        kind: Kind::End,
        offset: source.len(),
    });
    Ok(tokens)
}

fn number(input: &str) -> Result<(Kind, &str)> {
    let digits = |text: &str| text.bytes().take_while(u8::is_ascii_digit).count();
    let whole = digits(input);
    if whole > 1 && input.starts_with('0') {
        return Err("leading zeros are not allowed".into());
    }
    let mut end = whole;
    if let Some(fraction) = input[whole..].strip_prefix('.') {
        let n = digits(fraction);
        if n == 0 {
            return Err("a number needs digits after its decimal point".into());
        }
        end += 1 + n;
    }
    let rest = &input[end..];
    if rest.chars().next().map_or(false, id_start) {
        if end != whole {
            return Err("a duration must be whole".into());
        }
        let units_end = rest.find(|c| !id_next(c)).unwrap_or(rest.len());
        let unit = match &rest[..units_end] {
            "m" => 60_000,
            "h" => 3_600_000,
            "d" => 86_400_000,
            _ => return Err("duration unit must be m, h or d".into()),
        };
        let ms = input[..whole]
            .parse::<i64>()
            .ok()
            .and_then(|a| a.checked_mul(unit))
            .filter(|&a| (1..=9_007_199_254_740_991).contains(&a))
            .ok_or("invalid duration")?;
        let duration = Duration {
            ms,
            text: input[..end + units_end].to_owned(),
        };
        Ok((
            Kind::Scalar(Literal::Duration(duration)),
            &rest[units_end..],
        ))
    } else {
        let pct = rest.starts_with('%');
        Ok((
            Kind::Scalar(Literal::Number(input[..end].to_owned(), pct)),
            if pct { &rest[1..] } else { rest },
        ))
    }
}

struct Parser {
    tokens: Vec<Token>,
    index: usize,
    choices: Vec<Vec<Literal>>,
    vector_depth: usize,
}

impl Parser {
    fn new(source: &str) -> Result<Self> {
        Ok(Self {
            tokens: tokenize(source)?,
            index: 0,
            choices: Vec::new(),
            vector_depth: 0,
        })
    }

    fn current(&self) -> &Kind {
        &self.tokens[self.index].kind
    }

    fn clause(&mut self, source: &str) -> Result<(Expr, Range<usize>)> {
        let start = self.tokens[self.index].offset;
        let expr = self.expr(0)?;
        let end = self.tokens[self.index].offset;
        Ok((expr, start..start + source[start..end].trim_end().len()))
    }

    fn advance(&mut self) -> Kind {
        if matches!(self.current(), Kind::End) {
            return Kind::End;
        }
        let kind = std::mem::replace(&mut self.tokens[self.index].kind, Kind::End);
        self.index += 1;
        kind
    }

    fn fail<T>(&self, message: &str) -> Result<T> {
        Err(format!(
            "{message} at byte {}",
            self.tokens[self.index].offset
        ))
    }

    fn name(&mut self) -> Result<String> {
        match self.advance() {
            Kind::Scalar(Literal::Name(name)) => Ok(name),
            _ => self.fail("expected a name"),
        }
    }

    fn keyword(&mut self, want: &str) -> bool {
        if matches!(self.current(), Kind::Keyword(got) if *got == want) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn require_keyword(&mut self, want: &str) -> Result<()> {
        if self.keyword(want) {
            Ok(())
        } else {
            self.fail(&format!("expected {want}"))
        }
    }

    fn punct(&mut self, want: char) -> bool {
        if matches!(self.current(), Kind::Punct(got) if *got == want) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn require_punct(&mut self, want: char) -> Result<()> {
        if self.punct(want) {
            Ok(())
        } else {
            self.fail(&format!("expected {want}"))
        }
    }

    fn expr(&mut self, depth: usize) -> Result<Expr> {
        let mut result = self.and(depth)?;
        if self.keyword("or") {
            let mut items = vec![result, self.and(depth)?];
            while self.keyword("or") {
                items.push(self.and(depth)?);
            }
            result = Expr::Logic(false, items);
        }
        Ok(result)
    }

    fn and(&mut self, depth: usize) -> Result<Expr> {
        let mut result = self.unary(depth)?;
        if self.keyword("and") {
            let mut items = vec![result, self.unary(depth)?];
            while self.keyword("and") {
                items.push(self.unary(depth)?);
            }
            result = Expr::Logic(true, items);
        }
        Ok(result)
    }

    fn unary(&mut self, depth: usize) -> Result<Expr> {
        if depth > MAX_DEPTH {
            return self.fail("study expression is nested too deeply");
        }
        if self.keyword("not") {
            return Ok(Expr::Not(Box::new(self.unary(depth + 1)?)));
        }
        let left = self.atom(depth)?;
        if let Kind::Compare(op) = *self.current() {
            self.advance();
            return Ok(Expr::Compare(
                op,
                Box::new(left),
                Box::new(self.atom(depth)?),
            ));
        }
        Ok(left)
    }

    fn atom(&mut self, depth: usize) -> Result<Expr> {
        match self.advance() {
            Kind::Scalar(Literal::Name(name)) if self.punct('(') => self.call(name, depth),
            Kind::Scalar(Literal::Number(text, false)) if self.punct('%') => {
                Ok(Expr::Scalar(Literal::Number(text, true)))
            }
            Kind::Scalar(scalar) => Ok(Expr::Scalar(scalar)),
            Kind::Punct('(') => {
                let result = self.expr(depth + 1)?;
                self.require_punct(')')?;
                Ok(result)
            }
            Kind::Punct('[') => {
                self.vector_depth += 1;
                let mut items = vec![self.expr(depth + 1)?];
                while self.punct(',') {
                    items.push(self.expr(depth + 1)?);
                }
                self.require_punct(']')?;
                self.vector_depth -= 1;
                Ok(Expr::Vector(items))
            }
            Kind::Punct('{') if self.vector_depth == 0 => {
                let mut items = vec![self.choice_literal()?];
                self.require_punct('|')?;
                items.push(self.choice_literal()?);
                while self.punct('|') {
                    items.push(self.choice_literal()?);
                }
                self.require_punct('}')?;
                let mut seen = HashSet::new();
                for item in &items {
                    let key = match item {
                        Literal::Number(_, _) => Literal::Number(item.wire_ratio()?, false),
                        other => other.clone(),
                    };
                    if !seen.insert(key) {
                        return self.fail("duplicate candidate choice");
                    }
                }
                let index = self.choices.len();
                self.choices.push(items);
                Ok(Expr::Choice(index))
            }
            _ => self.fail("expected a scalar, call, vector, choice or parenthesized expression"),
        }
    }

    fn choice_literal(&mut self) -> Result<Literal> {
        match self.advance() {
            Kind::Scalar(Literal::Number(text, false)) if self.punct('%') => {
                Ok(Literal::Number(text, true))
            }
            Kind::Scalar(value) => Ok(value),
            _ => self.fail("choice values must be scalar literals"),
        }
    }

    fn call(&mut self, name: String, depth: usize) -> Result<Expr> {
        let mut args = Vec::new();
        if self.punct(')') {
            return Ok(Expr::Call(name, args));
        }
        loop {
            let named = matches!(self.current(), Kind::Scalar(Literal::Name(_)))
                && matches!(
                    self.tokens.get(self.index + 1).map(|t| &t.kind),
                    Some(Kind::Punct(':'))
                );
            let key = if named {
                let name = self.name()?;
                self.require_punct(':')?;
                Some(name)
            } else if args.is_empty() {
                None
            } else {
                return self.fail("only the first argument may be positional");
            };
            args.push(Argument {
                name: key,
                value: self.expr(depth + 1)?,
            });
            if !self.punct(',') {
                self.require_punct(')')?;
                break;
            }
        }
        Ok(Expr::Call(name, args))
    }
}
