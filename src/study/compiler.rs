use super::{
    extension::{Case, Definition, Param, ParamKind, BUNDLED},
    plan::{Plan, MAX_BATCH},
    syntax::{self, Argument, Comparison, Expr, Literal, Question},
    tape::{DAYS, TRENDS},
};
use crate::{
    engine_json,
    geometry::{Dimension, GeometryPattern},
    Result,
};
use std::{
    cmp::Ordering,
    collections::{HashMap, HashSet},
};

const DAY: i64 = 86_400_000;
const WEEK: i64 = 7 * DAY;
const QUARTER_HOUR: i64 = 900_000;
const CATALOGUE: &str = include_str!("../../study/catalogue/candles.json");

const FUNCTIONS: &[&str] = &[
    "exact_g1",
    "chained_g1",
    "wick_rejection",
    "channel_breakout",
    "quiet_range",
    "held",
    "range_contained",
    "weekday",
    "session_tail",
    "completed_trend",
    "close_return",
    "price",
    "prior_low",
    "prior_high",
    "breach_reclaim",
    "candle_relation",
    "candle_window",
    "candle_share",
    "range_multiple",
    "near_level",
    "dimension_multiple",
    "volume",
    "trades",
    "delta",
    "size",
    "imbalance",
    "relative_volume",
    "prior_utc_day_low",
    "value_area_reclaim",
];

#[derive(Clone, Copy)]
pub(super) struct Environment<'a> {
    pub instrument: &'a str,
    pub interval: i64,
    pub counters: bool,
    pub calendar: Option<&'a str>,
}

#[derive(Default)]
pub(super) struct Registry {
    patterns: HashMap<String, String>,
    functions: HashSet<String>,
    pattern_names: HashMap<String, String>,
    extensions: HashMap<String, Definition>,
}

impl Registry {
    pub fn new() -> Result<Self> {
        let document = engine_json::parse(CATALOGUE)?;
        let mut registry = Self::default();
        for pattern in document.field("patterns")?.array()? {
            let function = pattern.field("function")?.text()?;
            let instruction = pattern.field("instruction")?.text()?;
            registry.functions.insert(function.to_owned());
            registry
                .patterns
                .insert(function.to_owned(), instruction.to_owned());
            registry
                .pattern_names
                .insert(function.to_owned(), function.to_owned());
            for label in pattern.field("labels")?.array()? {
                let label = label_key(label.text()?);
                registry
                    .patterns
                    .insert(label.clone(), instruction.to_owned());
                registry.pattern_names.insert(label, function.to_owned());
            }
        }
        for text in BUNDLED {
            let definition = Definition::parse(text)?;
            registry.extensions.insert(definition.alias(), definition);
        }
        Ok(registry)
    }

    pub fn install(&mut self, text: &str, env: Environment<'_>) -> Result<Option<String>> {
        let definition = Definition::parse(text)?;
        let alias = definition.alias();
        if let Some(existing) = self.extensions.get(&alias) {
            if existing.digest == definition.digest {
                return Ok(None);
            }
            return Err(format!(
                "{} is already registered with different content",
                definition.key()
            ));
        }
        if FUNCTIONS.contains(&definition.id.as_str()) || self.functions.contains(&definition.id) {
            return Err(format!("{} is reserved", definition.key()));
        }
        for param in &definition.params {
            if param.name == "nyse_regular" || category(&param.name).is_some() {
                return Err(format!(
                    "parameter {} shadows a registered name",
                    param.name
                ));
            }
        }
        let mut required = HashSet::new();
        self.required_pins(&definition.body, env, &mut required);
        if let Some(missing) = required.difference(&definition.pins).min() {
            return Err(format!("missing dependency pin for {missing}"));
        }
        for pin in &definition.pins {
            let available = if let Some((name, version)) = pin.split_once('@') {
                (version == "1" && self.available_builtin(name))
                    || self.extensions.values().any(|def| def.key() == *pin)
            } else {
                env.calendar
                    .map_or(false, |id| pin == &format!("nyse_regular/{id}"))
            };
            if !available {
                return Err(format!("definition dependency {pin} is not available"));
            }
            if pin == &definition.key() {
                return Err("definition cannot depend on itself".into());
            }
        }
        let probe = syntax::question("on BTCUSDT 15m find wick_rejection()")?;
        let mut compiler = Compiler::new(env, self, &probe);
        let checked = compiler.expand(&definition, &[])?;
        compiler.finish(vec![format!("{} - -", checked.id)])?;
        self.extensions.insert(alias.clone(), definition);
        Ok(Some(alias))
    }

    pub fn cases(&self, alias: &str) -> &[Case] {
        &self.extensions[alias].cases
    }

    pub fn remove(&mut self, alias: &str) {
        self.extensions.remove(alias);
    }

    pub fn compile_case(&self, expression: &str, env: Environment<'_>) -> Result<Plan> {
        let question = syntax::question("on BTCUSDT 15m find wick_rejection()")?;
        let expr = syntax::expression(expression)?;
        let mut compiler = Compiler::new(env, self, &question);
        let id = compiler.boolean(&expr, false)?;
        compiler.finish(vec![format!("{id} - -")])
    }

    fn available_builtin(&self, name: &str) -> bool {
        self.functions.contains(name)
            || (FUNCTIONS.contains(&name)
                && !matches!(
                    name,
                    "relative_volume" | "prior_utc_day_low" | "value_area_reclaim"
                ))
    }

    fn required_pins(&self, expr: &Expr, env: Environment<'_>, pins: &mut HashSet<String>) {
        match expr {
            Expr::Call(name, args) => {
                if let Some(dep) = self.extensions.get(name) {
                    pins.insert(dep.key());
                } else if self.available_builtin(name) {
                    pins.insert(format!("{name}@1"));
                }
                if matches!(name.as_str(), "weekday" | "session_tail") {
                    if let Some(table) = env.calendar {
                        pins.insert(format!("nyse_regular/{table}"));
                    }
                }
                for arg in args {
                    self.required_pins(&arg.value, env, pins);
                }
            }
            Expr::Logic(_, items) | Expr::Vector(items) => {
                for item in items {
                    self.required_pins(item, env, pins);
                }
            }
            Expr::Not(item) => self.required_pins(item, env, pins),
            Expr::Compare(_, left, right) => {
                self.required_pins(left, env, pins);
                self.required_pins(right, env, pins);
            }
            Expr::Scalar(Literal::Text(text)) | Expr::Scalar(Literal::Name(text)) => {
                let name = label_key(text);
                if let Some(pattern) = self.pattern_names.get(&name) {
                    pins.insert(format!("{pattern}@1"));
                } else if name == "wick rejection" {
                    pins.insert("wick_rejection@1".into());
                } else if name == "quiet range" {
                    pins.insert("quiet_range@1".into());
                }
            }
            _ => {}
        }
    }

    pub fn catalogue() -> &'static str {
        CATALOGUE
    }
}

fn label_key(text: &str) -> String {
    text.trim()
        .chars()
        .flat_map(|ch| {
            match ch {
                '\u{ff01}'..='\u{ff5e}' => char::from_u32(ch as u32 - 0xfee0).unwrap(),
                _ => ch,
            }
            .to_lowercase()
        })
        .collect()
}

pub(super) fn compile(
    text: &str,
    environment: Environment<'_>,
    registry: &Registry,
    candidate: Option<usize>,
) -> Result<Plan> {
    let question = syntax::question(text)?;
    if question.instrument != environment.instrument || question.interval != environment.interval {
        return Err("study instrument or interval differs from the loaded recording".into());
    }
    for name in question.bindings.keys() {
        if name == "nyse_regular" || category(name).is_some() || FUNCTIONS.contains(&name.as_str())
        {
            return Err(format!("binding {name} shadows a registered name"));
        }
    }
    let count = question.choices.iter().try_fold(1usize, |n, choices| {
        n.checked_mul(choices.len())
            .filter(|&total| total <= MAX_BATCH)
            .ok_or("study expands to more than 64 candidates")
    })?;
    if candidate.map_or(false, |index| index >= count) {
        return Err("candidate is outside the checked study".into());
    }
    let mut compiler = Compiler::new(environment, registry, &question);
    let mut requests = Vec::with_capacity(count);
    let mut selected_filters = Vec::with_capacity(count);
    for index in 0..count {
        let mut remainder = index;
        for (slot, choices) in compiler.indices.iter_mut().zip(&question.choices).rev() {
            *slot = remainder % choices.len();
            remainder /= choices.len();
        }
        let (request, filters) = compiler.query()?;
        if candidate.map_or(true, |i| i == index) {
            requests.push(request);
            selected_filters.push(filters);
        }
    }
    if let Some(unused) = question
        .bindings
        .keys()
        .filter(|name| !compiler.used.contains(*name))
        .min()
    {
        return Err(format!("binding {unused} is never used"));
    }
    let mut plan = compiler.finish(requests)?;
    for (query, filters) in plan.queries.iter_mut().zip(selected_filters) {
        query.filters = filters;
    }
    Ok(plan)
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Event,
    Condition,
    State,
    Day,
    Trend,
    Price,
    Prior,
    Axis(Dimension),
}

impl Kind {
    fn boolean(self) -> bool {
        matches!(self, Self::Event | Self::Condition | Self::State)
    }

    fn category(self) -> bool {
        matches!(self, Self::Day | Self::Trend)
    }

    fn price(self) -> bool {
        matches!(self, Self::Price | Self::Prior)
    }
}

#[derive(Clone, Copy)]
struct Node {
    kind: Kind,
    id: usize,
}

fn category(name: &str) -> Option<Kind> {
    if DAYS.contains(&name) {
        Some(Kind::Day)
    } else if TRENDS.contains(&name) {
        Some(Kind::Trend)
    } else {
        None
    }
}

struct Compiler<'a> {
    environment: Environment<'a>,
    registry: &'a Registry,
    question: &'a Question,
    indices: Vec<usize>,
    nodes: Vec<String>,
    ids: HashMap<String, usize>,
    used: HashSet<String>,
    locals: Option<HashMap<&'a str, &'a Literal>>,
    depth: usize,
}

impl<'a> Compiler<'a> {
    fn new(environment: Environment<'a>, registry: &'a Registry, question: &'a Question) -> Self {
        Self {
            environment,
            registry,
            question,
            indices: vec![0; question.choices.len()],
            nodes: Vec::new(),
            ids: HashMap::new(),
            used: HashSet::new(),
            locals: None,
            depth: 0,
        }
    }

    fn finish(self, requests: Vec<String>) -> Result<Plan> {
        let mut wire = format!("filang-study-v1\t{}", self.nodes.len());
        for node in self.nodes.into_iter().chain(requests) {
            wire.push('\t');
            wire.push_str(&node);
        }
        if wire.len() >= 1_048_576 {
            return Err("compiled study exceeds 1 MiB".into());
        }
        Plan::parse(&wire, self.environment.interval)
    }

    fn intern(&mut self, kind: Kind, text: String) -> Result<Node> {
        if let Some(&id) = self.ids.get(&text) {
            return Ok(Node { kind, id });
        }
        let id = self.nodes.len();
        if id >= 2048 {
            return Err("study plan exceeds 2,048 nodes".into());
        }
        self.ids.insert(text.clone(), id);
        self.nodes.push(text);
        Ok(Node { kind, id })
    }

    fn query(&mut self) -> Result<(String, Vec<usize>)> {
        let q = self.question;
        let event = self.emit(&q.find, true)?;
        if event.kind != Kind::Event {
            return Err("find needs an event".into());
        }
        let mut filters = Vec::with_capacity(q.filters.len());
        for filter in &q.filters {
            filters.push(self.boolean(filter, false)?);
        }
        let context = match filters.len() {
            0 => "-".into(),
            1 => filters[0].to_string(),
            _ => self.logic(Kind::Condition, true, &filters)?.id.to_string(),
        };
        let group = match &q.group {
            Some(expr) => {
                let node = self.emit(expr, false)?;
                if !node.kind.boolean() && !node.kind.category() {
                    return Err("group by needs a Boolean or categorical value".into());
                }
                node.id.to_string()
            }
            None => "-".into(),
        };
        let mut horizons = Vec::new();
        for measure in &q.measures {
            let args = match measure {
                Expr::Call(name, args) if name == "close_return" => args,
                _ => return Err("measure needs close_return".into()),
            };
            let mut args = Args::new("close_return", args, None)?;
            let after = args.required("after")?;
            let expressions = match after {
                Expr::Vector(items) => items.as_slice(),
                scalar => std::slice::from_ref(scalar),
            };
            for expr in expressions {
                let ms = self.duration(expr, QUARTER_HOUR, WEEK, true)?;
                if horizons.contains(&ms) {
                    return Err("outcome horizon appears more than once".into());
                }
                horizons.push(ms);
            }
            args.finish()?;
        }
        let mut request = format!("{} {context} {group}", event.id);
        for horizon in horizons {
            use std::fmt::Write;
            write!(request, " {horizon}").expect("write to String");
        }
        Ok((request, filters))
    }

    fn literal(&mut self, expr: &'a Expr) -> Result<&'a Literal> {
        if let Expr::Scalar(Literal::Name(name)) = expr {
            if let Some(locals) = &self.locals {
                return Ok(locals
                    .get(name.as_str())
                    .copied()
                    .unwrap_or_else(|| match expr {
                        Expr::Scalar(literal) => literal,
                        _ => unreachable!(),
                    }));
            }
        }
        match expr {
            Expr::Scalar(Literal::Name(name)) if self.question.bindings.contains_key(name) => {
                self.used.insert(name.to_owned());
                self.literal(&self.question.bindings[name])
            }
            Expr::Scalar(scalar) => Ok(scalar),
            Expr::Choice(index) => Ok(&self.question.choices[*index][self.indices[*index]]),
            _ => Err("expected a scalar argument".into()),
        }
    }

    fn choice_name(&mut self, expr: &'a Expr) -> Result<&'a str> {
        match self.literal(expr)? {
            Literal::Name(name) => Ok(name),
            _ => Err("expected an unquoted name".into()),
        }
    }

    fn arg_name(&mut self, arg: Option<&'a Expr>, default: &'a str) -> Result<&'a str> {
        arg.map_or(Ok(default), |expr| self.choice_name(expr))
    }

    fn whole(&mut self, arg: Option<&'a Expr>, default: usize) -> Result<usize> {
        match arg {
            None => Ok(default),
            Some(expr) => match self.literal(expr)? {
                lit @ Literal::Number(_, false) => {
                    let ratio = lit.wire_ratio()?;
                    ratio
                        .strip_suffix("/1")
                        .and_then(|n| n.parse::<usize>().ok())
                        .filter(|&n| n <= 64)
                        .ok_or_else(|| "expected a whole number in 0..=64".into())
                }
                _ => Err("expected a whole number".into()),
            },
        }
    }

    fn duration(&mut self, expr: &'a Expr, min: i64, max: i64, grid: bool) -> Result<i64> {
        match self.literal(expr)? {
            Literal::Duration(ms)
                if (min..=max).contains(ms) && (!grid || ms % self.environment.interval == 0) =>
            {
                Ok(*ms)
            }
            _ => Err("duration is outside its range or off the recording grid".into()),
        }
    }

    fn duration_arg(
        &mut self,
        arg: Option<&'a Expr>,
        default: i64,
        min: i64,
        max: i64,
    ) -> Result<i64> {
        match arg {
            Some(expr) => self.duration(expr, min, max, true),
            None if default % self.environment.interval == 0 => Ok(default),
            None => Err("default duration is off the recording grid".into()),
        }
    }

    fn ratio(
        &mut self,
        arg: Option<&'a Expr>,
        default: &str,
        unit: bool,
        positive: bool,
    ) -> Result<String> {
        let ratio = match arg {
            Some(expr) => self.literal(expr)?.wire_ratio()?,
            None => default.to_owned(),
        };
        if (unit && compare_ratios(&ratio, "1/1") == Ordering::Greater)
            || (positive && ratio.starts_with("0/"))
        {
            return Err("ratio is outside its permitted range".into());
        }
        Ok(ratio)
    }

    fn boolean(&mut self, expr: &'a Expr, event: bool) -> Result<usize> {
        let node = self.emit(expr, event)?;
        if (event && node.kind == Kind::Event) || (!event && node.kind.boolean()) {
            Ok(node.id)
        } else {
            Err("Boolean operator needs a compatible event, state or condition".into())
        }
    }

    fn logic(&mut self, kind: Kind, and: bool, terms: &[usize]) -> Result<Node> {
        use std::fmt::Write;
        let mut instruction = String::from(if and { "and" } else { "or" });
        for term in terms {
            write!(instruction, " {term}").expect("write to String");
        }
        self.intern(kind, instruction)
    }

    fn emit(&mut self, expr: &'a Expr, event: bool) -> Result<Node> {
        match expr {
            Expr::Logic(and, terms) => {
                let ids = terms
                    .iter()
                    .map(|term| self.boolean(term, event))
                    .collect::<Result<Vec<_>>>()?;
                self.logic(
                    if event { Kind::Event } else { Kind::Condition },
                    *and,
                    &ids,
                )
            }
            Expr::Not(term) => {
                let id = self.boolean(term, false)?;
                self.intern(Kind::Condition, format!("not {id}"))
            }
            Expr::Compare(op, left, right) => {
                let a = self.category_operand(left)?;
                let b = self.category_operand(right)?;
                if a.kind != b.kind
                    || !a.kind.category()
                    || !matches!(op, Comparison::Eq | Comparison::Ne)
                {
                    return Err("comparison needs matching categorical values and = or !=".into());
                }
                self.intern(Kind::Condition, format!("{} {} {}", op.wire(), a.id, b.id))
            }
            Expr::Call(name, args) => self.call(name, args),
            Expr::Scalar(_) | Expr::Choice(_) => match self.literal(expr)? {
                Literal::Name(name) => self.named(name, false),
                Literal::Text(name) => self.named(name, true),
                _ => Err("expected a study call or named definition".into()),
            },
            Expr::Vector(_) => Err("vector is only allowed as an outcome argument".into()),
        }
    }

    fn named(&mut self, name: &str, quoted: bool) -> Result<Node> {
        let normalized = label_key(name);
        if let Some(instruction) = self.registry.patterns.get(&normalized) {
            if quoted || self.registry.functions.contains(name) || !name.is_ascii() {
                return self.intern(Kind::Event, instruction.clone());
            }
        }
        match (normalized.as_str(), quoted) {
            ("wick rejection", true) => self.call("wick_rejection", &[]),
            ("quiet range", true) => self.call("quiet_range", &[]),
            _ => Err(format!("unknown study definition {name:?}")),
        }
    }

    fn category_operand(&mut self, expr: &'a Expr) -> Result<Node> {
        if let Ok(Literal::Name(name)) = self.literal(expr) {
            if let Some(kind) = category(name) {
                return self.intern(kind, format!("category {name}"));
            }
        }
        self.emit(expr, false)
    }

    fn price(&mut self, expr: &'a Expr, prior: bool) -> Result<Node> {
        let node = self.emit(expr, false)?;
        if (prior && node.kind == Kind::Prior) || (!prior && node.kind.price()) {
            Ok(node)
        } else {
            Err("expected a candle price or a compatible prior price level".into())
        }
    }

    fn relation(&mut self, left: &'a Expr, op: &str, right: &'a Expr) -> Result<String> {
        let mut operand = |expr| match self.literal(expr) {
            Ok(value @ Literal::Number(_, _)) if value.wire_ratio()? == "0/1" => Ok(None),
            _ => self.emit(expr, false).map(Some),
        };
        let a = operand(left)?;
        let b = operand(right)?;
        let (left, right, axis) = match (a, b) {
            (Some(a), Some(b)) if a.kind.price() && b.kind.price() => (a.id, b.id, false),
            (Some(a), Some(b)) if a.kind == b.kind && matches!(a.kind, Kind::Axis(_)) => {
                (a.id, b.id, true)
            }
            (Some(value), None) | (None, Some(value)) => match value.kind {
                Kind::Axis(axis) if axis.has_reference() => {
                    let zero = self.intern(Kind::Axis(axis), format!("axis-zero {axis}"))?;
                    if a.is_some() {
                        (value.id, zero.id, true)
                    } else {
                        (zero.id, value.id, true)
                    }
                }
                _ => return Err("zero reference requires delta or imbalance".into()),
            },
            _ => return Err("candle_relation needs two values on the same axis".into()),
        };
        let name = if axis { "axis-relate" } else { "relate" };
        Ok(format!("{name} {left} {op} {right}"))
    }

    fn calendar(&mut self, expr: &'a Expr) -> Result<()> {
        if self.choice_name(expr)? == "nyse_regular" && self.environment.calendar.is_some() {
            Ok(())
        } else {
            Err("load the pinned nyse_regular calendar before using this call".into())
        }
    }

    fn counters(&self) -> Result<()> {
        if self.environment.counters {
            Ok(())
        } else {
            Err("this recording carries no counters".into())
        }
    }

    fn expand(&mut self, definition: &'a Definition, args: &'a [Argument]) -> Result<Node> {
        if self.depth >= syntax::MAX_DEPTH {
            return Err("study definition expansion is nested too deeply".into());
        }
        let mut args = Args::new(&definition.id, args, None)?;
        let mut locals = HashMap::new();
        for param in &definition.params {
            let value = match args.take(&param.name) {
                Some(expr) => self.literal(expr)?,
                None => &param.default,
            };
            validate_param(param, value, self.environment.interval)?;
            locals.insert(param.name.as_str(), value);
        }
        args.finish()?;
        for pin in &definition.pins {
            if let Some((_, table)) = pin.split_once('/') {
                if self.environment.calendar != Some(table) {
                    return Err(format!("definition needs pinned calendar {pin}"));
                }
            }
        }
        let saved = self.locals.replace(locals);
        self.depth += 1;
        let body = self.emit(&definition.body, false);
        self.depth -= 1;
        self.locals = saved;
        let body = body?;
        if !body.kind.boolean() {
            return Err("definition body must be Boolean".into());
        }
        let kind = if definition.event {
            Kind::Event
        } else {
            Kind::Condition
        };
        Ok(Node { kind, id: body.id })
    }

    fn call(&mut self, name: &'a str, arguments: &'a [Argument]) -> Result<Node> {
        if let Some(definition) = self.registry.extensions.get(name) {
            return self.expand(definition, arguments);
        }
        if self.registry.functions.contains(name) {
            let args = Args::new(name, arguments, None)?;
            args.finish()?;
            return self.intern(Kind::Event, self.registry.patterns[name].clone());
        }
        let positional = match name {
            "exact_g1" | "chained_g1" => Some("pattern"),
            "held" => Some("state"),
            "weekday" | "session_tail" => Some("calendar"),
            "price" => Some("point"),
            "breach_reclaim" | "near_level" => Some("reference"),
            "candle_relation" => Some("left"),
            "candle_window" => Some("event"),
            "candle_share" => Some("part"),
            "dimension_multiple" => Some("dimension"),
            _ => None,
        };
        let mut a = Args::new(name, arguments, positional)?;
        let (kind, op) = match name {
            "exact_g1" | "chained_g1" => {
                let source = match self.literal(a.required("pattern")?)? {
                    Literal::Text(text) => text,
                    _ => return Err("g1 pattern must be a string".into()),
                };
                let pattern: GeometryPattern = source.parse()?;
                if pattern.is_empty() {
                    return Err("g1 event needs at least one candle".into());
                }
                if pattern.has_dimensions() {
                    self.counters()?;
                }
                let op = if name == "exact_g1" { "g1" } else { "g1c" };
                (Kind::Event, format!("{op} {pattern}"))
            }
            "wick_rejection" => {
                let body = self.ratio(a.take("body_max"), "35/100", true, false)?;
                let wick = self.ratio(a.take("wick_min"), "45/100", true, true)?;
                (Kind::Event, format!("wick {body} {wick}"))
            }
            "channel_breakout" => {
                let over = self.duration(a.required("over")?, QUARTER_HOUR, WEEK, true)?;
                (Kind::Event, format!("breakout {over}"))
            }
            "quiet_range" | "range_contained" => {
                let quiet = name == "quiet_range";
                let (over, width) = if quiet {
                    (
                        self.duration_arg(a.take("window"), 4 * 3_600_000, 1_800_000, 2 * DAY)?,
                        self.ratio(a.take("width_max"), "25/1000", true, true)?,
                    )
                } else {
                    (
                        self.duration(a.required("over")?, 1_800_000, WEEK, true)?,
                        self.ratio(Some(a.required("width_max")?), "", true, true)?,
                    )
                };
                (
                    if quiet { Kind::State } else { Kind::Condition },
                    format!("range {over} {width}"),
                )
            }
            "held" => {
                let state = self.emit(a.required("state")?, false)?;
                if state.kind != Kind::State {
                    return Err("held needs a State".into());
                }
                let time = self.duration(a.required("for")?, QUARTER_HOUR, WEEK, true)?;
                (Kind::Condition, format!("held {} {time}", state.id))
            }
            "weekday" => {
                self.calendar(a.required("calendar")?)?;
                (Kind::Day, "weekday".into())
            }
            "session_tail" => {
                self.calendar(a.required("calendar")?)?;
                let last = self.duration(a.required("last")?, 60_000, 390 * 60_000, false)?;
                (Kind::Condition, format!("tail {last}"))
            }
            "completed_trend" => {
                let frame = self.duration(a.required("frame")?, QUARTER_HOUR, DAY, true)?;
                if DAY % frame != 0 {
                    return Err("trend frame must divide 24h".into());
                }
                (Kind::Trend, format!("trend {frame}"))
            }
            "price" => {
                let point = self.arg_name(a.take("point"), "close")?;
                let lag = self.whole(a.take("bars_ago"), 0)?;
                (Kind::Price, format!("price {point} {lag}"))
            }
            "prior_low" | "prior_high" => {
                let over = self.duration_arg(a.take("over"), 4 * 3_600_000, QUARTER_HOUR, WEEK)?;
                let side = if name == "prior_low" { "low" } else { "high" };
                match a.take("of") {
                    Some(expr) => {
                        self.counters()?;
                        let axis: Dimension = self.choice_name(expr)?.parse()?;
                        (Kind::Axis(axis), format!("axis-prior-{side} {axis} {over}"))
                    }
                    None => (Kind::Prior, format!("prior-{side} {over}")),
                }
            }
            "volume" | "trades" | "delta" | "size" | "imbalance" => {
                self.counters()?;
                let axis: Dimension = name.parse()?;
                let lag = self.whole(a.take("bars_ago"), 0)?;
                (Kind::Axis(axis), format!("axis {axis} {lag}"))
            }
            "breach_reclaim" => {
                let reference = self.price(a.required("reference")?, true)?.id;
                let min = self.whole(a.take("within_min"), 0)?;
                let max = self.whole(a.take("within_max"), 0)?;
                (Kind::Event, format!("reclaim {reference} {min} {max}"))
            }
            "candle_relation" => {
                let left = a.required("left")?;
                let right = a.required("right")?;
                let op = match self.arg_name(a.take("is"), "above")? {
                    "above" => "gt",
                    "below" => "lt",
                    "at_or_above" => "ge",
                    "at_or_below" => "le",
                    "equal" => "eq",
                    "unequal" => "ne",
                    _ => return Err("unknown candle relation".into()),
                };
                (Kind::Event, self.relation(left, op, right)?)
            }
            "candle_window" => {
                let event = self.boolean(a.required("event")?, true)?;
                let bars = self.whole(a.take("bars"), 2)?;
                (Kind::Event, format!("window {event} {bars}"))
            }
            "candle_share" => {
                let part = self.arg_name(a.take("part"), "lower_wick")?;
                let lag = self.whole(a.take("bars_ago"), 0)?;
                let min = self.ratio(a.take("min"), "1/2", true, false)?;
                let max = self.ratio(a.take("max"), "1/1", true, false)?;
                ordered(&min, &max)?;
                (Kind::Condition, format!("share {part} {lag} {min} {max}"))
            }
            "range_multiple" | "dimension_multiple" => {
                let over = self.duration_arg(a.take("over"), 4 * 3_600_000, QUARTER_HOUR, WEEK)?;
                let min = self.ratio(a.take("min"), "15/10", false, false)?;
                let max = match a.take("max") {
                    Some(expr) => {
                        let max = self.ratio(Some(expr), "", false, false)?;
                        ordered(&min, &max)?;
                        max
                    }
                    None => "-".into(),
                };
                let op = if name == "dimension_multiple" {
                    self.counters()?;
                    let axis: Dimension = self.arg_name(a.take("dimension"), "volume")?.parse()?;
                    if axis.has_reference() {
                        return Err("signed dimensions have no median multiple".into());
                    }
                    format!("axis-multiple {axis} {over} {min} {max}")
                } else {
                    format!("multiple {over} {min} {max}")
                };
                (Kind::Condition, op)
            }
            "near_level" => {
                let reference = self.price(a.required("reference")?, false)?.id;
                let point = self.price(a.required("point")?, false)?.id;
                let within = self.ratio(a.take("within"), "25/10000", true, false)?;
                (
                    Kind::Condition,
                    format!("near {reference} {point} {within}"),
                )
            }
            _ => return Err(format!("unknown or unavailable study call {name}")),
        };
        a.finish()?;
        self.intern(kind, op)
    }
}

fn validate_param(param: &Param, value: &Literal, interval: i64) -> Result<()> {
    let domain = &param.domain;
    let valid = match (&param.kind, value) {
        (ParamKind::Duration, Literal::Duration(ms)) => {
            domain.min_ms.map_or(true, |min| *ms >= min)
                && domain.max_ms.map_or(true, |max| *ms <= max)
                && (!domain.grid || ms % interval == 0)
        }
        (ParamKind::Number, Literal::Number(_, false)) => {
            if domain.whole_min.is_none() && domain.whole_max.is_none() {
                true
            } else {
                value
                    .wire_ratio()?
                    .strip_suffix("/1")
                    .and_then(|n| n.parse::<usize>().ok())
                    .map_or(false, |n| {
                        domain.whole_min.map_or(true, |min| n >= min)
                            && domain.whole_max.map_or(true, |max| n <= max)
                    })
            }
        }
        (ParamKind::Ratio, Literal::Number(_, _)) => {
            let ratio = value.wire_ratio()?;
            domain.ratio_min.as_ref().map_or(true, |min| {
                let comparison = compare_ratios(&ratio, min);
                comparison.is_gt() || (comparison.is_eq() && !domain.ratio_min_exclusive)
            }) && domain.ratio_max.as_ref().map_or(true, |max| {
                let comparison = compare_ratios(&ratio, max);
                comparison.is_lt() || (comparison.is_eq() && !domain.ratio_max_exclusive)
            })
        }
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(format!(
            "parameter {} is outside its type or domain",
            param.name
        ))
    }
}

struct Args<'a> {
    name: &'a str,
    values: HashMap<&'a str, &'a Expr>,
}

impl<'a> Args<'a> {
    fn new(name: &'a str, args: &'a [Argument], positional: Option<&'a str>) -> Result<Self> {
        let mut values = HashMap::new();
        for argument in args {
            let key = argument
                .name
                .as_deref()
                .or(positional)
                .ok_or_else(|| format!("{name} needs named arguments"))?;
            if values.insert(key, &argument.value).is_some() {
                return Err(format!("duplicate argument {key} in {name}"));
            }
        }
        Ok(Self { name, values })
    }

    fn take(&mut self, name: &str) -> Option<&'a Expr> {
        self.values.remove(name)
    }

    fn required(&mut self, name: &str) -> Result<&'a Expr> {
        self.take(name)
            .ok_or_else(|| format!("missing argument {name} in {}", self.name))
    }

    fn finish(self) -> Result<()> {
        if let Some(key) = self.values.keys().min() {
            Err(format!("unexpected argument {key} in {}", self.name))
        } else {
            Ok(())
        }
    }
}

// Thresholds lowered from decimal literals have power-of-ten denominators.
// Defaults may use 1/2. Compare them without rounding long user decimals.
fn ratio_decimal(ratio: &str) -> (&str, usize) {
    let (num, den) = ratio.split_once('/').expect("wire ratio");
    if den == "2" {
        ("5", 1)
    } else {
        (num, den.len() - 1)
    }
}

fn compare_ratios(a: &str, b: &str) -> Ordering {
    let (a, ad) = ratio_decimal(a);
    let (b, bd) = ratio_decimal(b);
    if a == "0" || b == "0" {
        return (a != "0").cmp(&(b != "0"));
    }
    let at = a.len() as i64 - ad as i64;
    let bt = b.len() as i64 - bd as i64;
    at.cmp(&bt).then_with(|| {
        (0..a.len().max(b.len()))
            .map(|i| {
                (
                    a.as_bytes().get(i).copied().unwrap_or(b'0'),
                    b.as_bytes().get(i).copied().unwrap_or(b'0'),
                )
            })
            .find_map(|(left, right)| (left != right).then(|| left.cmp(&right)))
            .unwrap_or(Ordering::Equal)
    })
}

fn ordered(min: &str, max: &str) -> Result<()> {
    if compare_ratios(min, max) == Ordering::Greater {
        Err("minimum exceeds maximum".into())
    } else {
        Ok(())
    }
}
