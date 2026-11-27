//! Stable descriptions for a checked question and its sweep candidates.
use super::{
    compiler, quote,
    syntax::{self, Comparison, Duration, Expr, Literal, Question},
    Study,
};
use crate::{engine_json, Result};
use std::{
    collections::{BTreeSet, HashSet},
    fmt::Write,
    ops::Range,
};

const TERMS: &str = include_str!("../../study/catalogue/terms.json");

impl Study {
    pub fn terms() -> &'static str {
        TERMS
    }

    pub fn resolve_candle(&self, name: &str) -> Option<&str> {
        self.registry.resolve_candle(name)
    }

    pub fn diagnostics(&self, source: &str) -> String {
        let header = 0..source.find('\n').unwrap_or(source.len());
        let parsed = syntax::question(source);
        let errors = match &parsed {
            Err(error) => vec![(error_span(source, error, header), error.clone())],
            Ok(question) => {
                match compiler::compile_question(question, self.environment(), &self.registry, None)
                {
                    Ok(_) => Vec::new(),
                    Err(error) => {
                        let mut errors =
                            compiler::clause_errors(question, self.environment(), &self.registry);
                        if errors.is_empty() {
                            errors.push((header, error));
                        }
                        errors
                    }
                }
            }
        };
        let ok = errors.is_empty();
        let syntax = match parsed {
            Ok(question) if !ok && errors.iter().all(|(_, e)| e.contains("counters")) => {
                let (canonical, ast) = render_question(&question, None);
                format!(",\"canonical\":{},\"ast\":{ast}", quote(&canonical))
            }
            _ => String::new(),
        };
        let errors = errors
            .into_iter()
            .map(|(span, error)| diagnostic(source, span, &error))
            .collect::<Vec<_>>()
            .join(",");
        format!("{{\"ok\":{ok},\"errors\":[{errors}]{syntax}}}")
    }

    pub fn describe(&self, source: &str) -> Result<String> {
        let question = syntax::question(source)?;
        let plan = compiler::compile_question(&question, self.environment(), &self.registry, None)?;
        let terms = engine_json::parse(TERMS)?;
        let defs = terms.field("terms")?.array()?;
        let (canonical, ast) = render_question(&question, None);
        let axes = sweep_axes(&question, defs);
        let mut candidates = Vec::with_capacity(plan.queries().len());
        let mut candidate_manifest = Vec::with_capacity(plan.queries().len());
        let mut pins = HashSet::new();
        for index in 0..plan.queries().len() {
            let mut choices = vec![0usize; axes.len()];
            question.select(index, &mut choices);
            let (resolved, _) = render_question(&question, Some(&choices));
            let selected = syntax::question(&resolved)?;
            for expr in std::iter::once(&selected.find)
                .chain(&selected.filters)
                .chain(selected.group.iter())
                .chain(&selected.measures)
            {
                self.registry
                    .required_pins(expr, self.environment(), &mut pins);
            }
            let assignments: Vec<_> = choices
                .iter()
                .enumerate()
                .map(|(i, &value)| {
                    let label = &axes[i];
                    let text = literal(&question.choices[i][value]).text;
                    (label, text, value)
                })
                .collect();
            let label = if assignments.is_empty() {
                "single run".to_string()
            } else {
                assignments
                    .iter()
                    .map(|(name, value, _)| format!("{name}={value}"))
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            let assignments = assignments
                .iter()
                .enumerate()
                .map(|(i, (name, value, at))| {
                    format!(
                        "{{\"axis\":{},\"axisIndex\":{i},\"value\":{},\"valueIndex\":{at}}}",
                        quote(name),
                        quote(value)
                    )
                })
                .collect::<Vec<_>>()
                .join(",");
            candidates.push(format!(
                "{{\"index\":{index},\"label\":{},\"assignment\":[{assignments}],\"resolvedText\":{}}}",
                quote(&label), quote(&resolved)
            ));
            candidate_manifest.push(format!(
                "{{\"label\":{},\"resolved\":{}}}",
                quote(&label),
                quote(&resolved)
            ));
        }
        let axes = axes
            .iter()
            .zip(&question.choices)
            .enumerate()
            .map(|(index, (label, values))| {
                let values = values
                    .iter()
                    .map(|v| literal(v).ast)
                    .collect::<Vec<_>>()
                    .join(",");
                format!(
                    "{{\"index\":{index},\"label\":{},\"values\":[{values}]}}",
                    quote(label)
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        self.registry.expand_pins(&mut pins);
        let manifest = self.manifest(
            &canonical,
            &question.interval_text,
            &candidate_manifest,
            &pins,
            defs,
        );
        Ok(format!(
            "{{\"canonical\":{},\"ast\":{ast},\"axes\":[{axes}],\"candidates\":[{}],\"manifest\":{manifest}}}",
            quote(&canonical), candidates.join(",")
        ))
    }

    fn manifest(
        &self,
        canonical: &str,
        interval: &str,
        candidates: &[String],
        pins: &HashSet<String>,
        terms: &[engine_json::Value],
    ) -> String {
        let mut definitions = BTreeSet::new();
        let mut candles = BTreeSet::new();
        let mut extensions = Vec::new();
        for pin in pins.iter().collect::<BTreeSet<_>>() {
            if let Some(definition) = self.registry.extension_pin(pin) {
                definitions.insert(pin.clone());
                extensions.push(format!(
                    "{{\"id\":{},\"sha256\":{}}}",
                    quote(pin),
                    quote(definition)
                ));
            } else if let Some((name, version)) = pin.rsplit_once('@') {
                let term = term(terms, name);
                let id = term.and_then(|value| field(value, "id")).unwrap_or(name);
                definitions.insert(format!("{id}@{version}"));
                if let Some(value) = term
                    .and_then(|value| value.field("candle").ok())
                    .and_then(|value| value.object().ok().map(|_| value))
                {
                    let id = field(value, "id").expect("catalogue id");
                    let sha = field(value, "sha256").expect("catalogue digest");
                    candles.insert(format!(
                        "{{\"id\":{},\"version\":{version},\"sha256\":{}}}",
                        quote(id),
                        quote(sha)
                    ));
                }
            }
        }
        let definitions = definitions
            .iter()
            .map(|pin| quote(pin))
            .collect::<Vec<_>>()
            .join(",");
        let candles = candles.into_iter().collect::<Vec<_>>().join(",");
        let calendars = self
            .calendar
            .as_ref()
            .zip(self.calendar_sha256.as_ref())
            .map(|((table, _), sha)| {
                format!("{{\"id\":{},\"sha256\":{}}}", quote(table), quote(sha))
            })
            .unwrap_or_default();
        format!(
            "{{\"engine\":{{\"name\":\"Filang\",\"version\":\"{}\"}},\"query\":{},\"candidates\":[{}],\"pins\":{{\"source\":{{\"csv_sha256\":{},\"rows\":{},\"instrument\":{},\"bar\":{}}},\"calendars\":[{calendars}],\"definitions\":[{definitions}],\"candlePatterns\":[{candles}],\"extensions\":[{}]}},\"arithmetic\":\"integer cents + exact rational thresholds; float64 returns\"}}",
            crate::engine_session::VERSION, quote(canonical), candidates.join(","), quote(&self.source_sha256),
            self.slots() - self.tape.absent(), quote(&self.instrument), quote(interval), extensions.join(",")
        )
    }
}

fn error_span(source: &str, error: &str, fallback: Range<usize>) -> Range<usize> {
    let start = error
        .rsplit_once(" at byte ")
        .and_then(|(_, position)| position.parse::<usize>().ok())
        .filter(|&position| source.is_char_boundary(position));
    match start {
        Some(start) => {
            let end = source[start..]
                .chars()
                .next()
                .map_or(start, |c| start + c.len_utf8());
            start..end
        }
        None => fallback,
    }
}

fn diagnostic(source: &str, span: Range<usize>, error: &str) -> String {
    let (kind, hint) = if error.contains(" at byte ") {
        ("parse", "Check the syntax and the order of the clauses.")
    } else if error.contains("binding") {
        (
            "binding",
            "Declare each value once and reference it by name.",
        )
    } else if error.contains("choice") || error.contains("candidate") {
        (
            "sweep",
            "Choose distinct scalar values and stay within 64 candidates.",
        )
    } else if error.contains("counters") || error.contains("calendar") {
        (
            "capability",
            "Load the recording or calendar required by this term.",
        )
    } else if error.contains("unavailable") || error.contains("unknown") {
        (
            "name",
            "Use a term or candle name available in this engine.",
        )
    } else {
        (
            "type",
            "Check the argument types, ranges and the recording interval.",
        )
    };
    let message = error
        .rsplit_once(" at byte ")
        .map_or(error, |(message, _)| message);
    let start = source[..span.start].encode_utf16().count();
    let end = start + source[span].encode_utf16().count();
    format!(
        "{{\"kind\":\"{kind}\",\"message\":{},\"start\":{start},\"end\":{end},\"hint\":{}}}",
        quote(message),
        quote(hint)
    )
}

fn field<'a>(row: &'a engine_json::Value, key: &str) -> Option<&'a str> {
    row.field(key).ok()?.text().ok()
}

fn term<'a>(terms: &'a [engine_json::Value], name: &str) -> Option<&'a engine_json::Value> {
    terms.iter().find(|term| field(term, "name") == Some(name))
}

struct Printed {
    text: String,
    ast: String,
}

impl Printed {
    fn with_text(mut self) -> Self {
        self.ast.pop();
        write!(self.ast, ",\"text\":{}}}", quote(&self.text)).expect("format expression text");
        self
    }
}

fn literal(value: &Literal) -> Printed {
    match value {
        Literal::Name(name) => Printed {
            text: name.clone(),
            ast: format!("{{\"k\":\"id\",\"name\":{}}}", quote(name)),
        }
        .with_text(),
        Literal::Text(value) => {
            let text = quote(value);
            let ast = format!("{{\"k\":\"str\",\"value\":{text}}}");
            Printed { text, ast }.with_text()
        }
        Literal::Number(value, pct) => {
            let kind = if *pct { "pct" } else { "num" };
            let suffix = if *pct { "%" } else { "" };
            Printed {
                text: format!("{value}{suffix}"),
                ast: if *pct {
                    format!(
                        "{{\"k\":\"pct\",\"text\":{},\"canonical_text\":{}}}",
                        quote(value),
                        quote(&format!("{value}%"))
                    )
                } else {
                    format!("{{\"k\":\"{kind}\",\"text\":{}}}", quote(value))
                },
            }
        }
        Literal::Duration(d) => {
            let (amount, unit) = d.text.split_at(d.text.len() - 1);
            Printed {
                text: d.text.clone(),
                ast: format!(
                    "{{\"k\":\"dur\",\"text\":{},\"amount\":{amount},\"unit\":{},\"ms\":{}}}",
                    quote(&d.text),
                    quote(unit),
                    d.ms
                ),
            }
        }
    }
}

fn comparison(cmp: Comparison) -> &'static str {
    match cmp {
        Comparison::Eq => "=",
        Comparison::Ne => "!=",
        Comparison::Lt => "<",
        Comparison::Le => "<=",
        Comparison::Gt => ">",
        Comparison::Ge => ">=",
    }
}

fn join_ast(values: &[Printed]) -> String {
    values
        .iter()
        .map(|item| item.ast.as_str())
        .collect::<Vec<_>>()
        .join(",")
}

fn render(q: &Question, expr: &Expr, selected: Option<&[usize]>, min: u8) -> Printed {
    let children = |items: &[Expr], prec| {
        items
            .iter()
            .map(|item| render(q, item, selected, prec))
            .collect::<Vec<_>>()
    };
    let (precedence, mut value) = match expr {
        Expr::Scalar(value) => {
            if selected.is_some() {
                if let Literal::Name(name) = value {
                    if let Some(bound) = q.bindings.get(name) {
                        return render(q, bound, selected, min);
                    }
                }
            }
            return literal(value);
        }
        Expr::Choice(index) => {
            let items = &q.choices[*index];
            if let Some(selected) = selected {
                return literal(&items[selected[*index]]);
            }
            let items: Vec<_> = items.iter().map(literal).collect();
            let text = items
                .iter()
                .map(|i| i.text.as_str())
                .collect::<Vec<_>>()
                .join(" | ");
            let ast = join_ast(&items);
            return Printed {
                text: format!("{{{text}}}"),
                ast: format!("{{\"k\":\"choices\",\"items\":[{ast}]}}"),
            }
            .with_text();
        }
        Expr::Vector(items) => {
            let items = children(items, 0);
            let text = items
                .iter()
                .map(|i| i.text.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            let ast = join_ast(&items);
            return Printed {
                text: format!("[{text}]"),
                ast: format!("{{\"k\":\"vec\",\"items\":[{ast}]}}"),
            }
            .with_text();
        }
        Expr::Call(name, args) => {
            let rendered = args
                .iter()
                .filter_map(|arg| {
                    let value = render(q, &arg.value, selected, 0);
                    if matches!(name.as_str(), "exact_g1" | "chained_g1")
                        && arg.name.as_deref() == Some("radius")
                        && value.text.bytes().all(|b| matches!(b, b'0' | b'.'))
                    {
                        return None;
                    }
                    let text = arg.name.as_ref().map_or_else(
                        || value.text.clone(),
                        |name| format!("{name}: {}", value.text),
                    );
                    let key = arg
                        .name
                        .as_ref()
                        .map_or_else(|| "null".into(), |name| quote(name));
                    Some(Printed {
                        text,
                        ast: format!("{{\"name\":{key},\"value\":{}}}", value.ast),
                    })
                })
                .collect::<Vec<_>>();
            let text = rendered
                .iter()
                .map(|arg| arg.text.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            let ast = join_ast(&rendered);
            return Printed {
                text: format!("{name}({text})"),
                ast: format!(
                    "{{\"k\":\"call\",\"name\":{},\"args\":[{ast}]}}",
                    quote(name)
                ),
            }
            .with_text();
        }
        Expr::Logic(and, items) => {
            let (precedence, kind) = if *and { (2, "and") } else { (1, "or") };
            let children = children(items, precedence + 1);
            let text = children
                .iter()
                .map(|i| i.text.as_str())
                .collect::<Vec<_>>()
                .join(&format!(" {kind} "));
            let ast = join_ast(&children);
            (
                precedence,
                Printed {
                    text,
                    ast: format!("{{\"k\":\"{kind}\",\"items\":[{ast}]}}"),
                },
            )
        }
        Expr::Not(inner) => {
            let inner = render(q, inner, selected, 3);
            (
                3,
                Printed {
                    text: format!("not {}", inner.text),
                    ast: format!("{{\"k\":\"not\",\"item\":{}}}", inner.ast),
                },
            )
        }
        Expr::Compare(cmp, a, b) => {
            let op = comparison(*cmp);
            let a = render(q, a, selected, 5);
            let b = render(q, b, selected, 5);
            (
                4,
                Printed {
                    text: format!("{} {op} {}", a.text, b.text),
                    ast: format!(
                        "{{\"k\":\"cmp\",\"op\":{},\"left\":{},\"right\":{}}}",
                        quote(op),
                        a.ast,
                        b.ast
                    ),
                },
            )
        }
    };
    if precedence < min {
        value.text = format!("({})", value.text);
    }
    value.with_text()
}

pub(super) fn receipt_lines(question: &Question, candidate: usize) -> String {
    let mut choices = vec![0; question.choices.len()];
    question.select(candidate, &mut choices);
    let text = |expr: &Expr| quote(&render(question, expr, Some(&choices), 0).text);
    let list = |items: &[Expr]| items.iter().map(text).collect::<Vec<_>>().join(",");
    let find = text(&question.find);
    let group = question
        .group
        .as_ref()
        .map_or_else(|| "null".to_owned(), text);
    let on = quote(&format!(
        "{} {}",
        question.instrument, question.interval_text
    ));
    format!(
        "{{\"on\":{on},\"find\":{find},\"wheres\":[{}],\"group\":{group},\"measures\":[{}]}}",
        list(&question.filters),
        list(&question.measures),
    )
}

fn render_question(q: &Question, selected: Option<&[usize]>) -> (String, String) {
    let mut text = format!("on {} {}", q.instrument, q.interval_text);
    let bar = literal(&Literal::Duration(Duration {
        ms: q.interval,
        text: q.interval_text.clone(),
    }));
    let bindings = if selected.is_none() {
        q.binding_order
            .iter()
            .map(|name| {
                let value = render(q, &q.bindings[name], None, 0);
                write!(text, "\nlet {name} = {}", value.text).expect("format string");
                format!(
                    "{{\"k\":\"let\",\"name\":{},\"value\":{}}}",
                    quote(name),
                    value.ast
                )
            })
            .collect::<Vec<_>>()
            .join(",")
    } else {
        String::new()
    };
    let mut clauses = |expr: &Expr, keyword: &str| {
        let entry = render(q, expr, selected, 0);
        write!(text, "\n{keyword} {}", entry.text).expect("format string");
        entry.ast
    };
    let find = clauses(&q.find, "find");
    let filters = q
        .filters
        .iter()
        .map(|f| clauses(f, "where"))
        .collect::<Vec<_>>()
        .join(",");
    let group = q
        .group
        .as_ref()
        .map_or_else(|| "null".into(), |g| clauses(g, "group by"));
    let measures = q
        .measures
        .iter()
        .map(|m| clauses(m, "measure"))
        .collect::<Vec<_>>()
        .join(",");
    let ast = format!(
        "{{\"k\":\"question\",\"on\":{{\"instrument\":{{\"name\":{}}},\"bar\":{}}},\"lets\":[{bindings}],\"find\":{find},\"wheres\":[{filters}],\"group\":{group},\"measures\":[{measures}]}}",
        quote(&q.instrument), bar.ast
    );
    (text, ast)
}

fn label_expr(
    q: &Question,
    expr: &Expr,
    label: &str,
    terms: &[engine_json::Value],
    labels: &mut [String],
) {
    match expr {
        Expr::Choice(index) => labels[*index] = label.to_owned(),
        Expr::Call(name, args) => {
            let position = term(terms, name)
                .and_then(|term| field(term, "positional"))
                .unwrap_or("arg");
            for arg in args {
                let name = format!("{name}.{}", arg.name.as_deref().unwrap_or(position));
                label_expr(q, &arg.value, &name, terms, labels);
            }
        }
        Expr::Not(item) => label_expr(q, item, label, terms, labels),
        Expr::Logic(_, items) | Expr::Vector(items) => {
            for item in items {
                label_expr(q, item, label, terms, labels);
            }
        }
        Expr::Compare(cmp, left, right) => {
            let operator = comparison(*cmp);
            label_expr(
                q,
                left,
                &format!("{operator} {}", render(q, right, None, 0).text),
                terms,
                labels,
            );
            label_expr(
                q,
                right,
                &format!("{} {operator}", render(q, left, None, 0).text),
                terms,
                labels,
            );
        }
        Expr::Scalar(_) => {}
    }
}

fn sweep_axes(q: &Question, terms: &[engine_json::Value]) -> Vec<String> {
    let mut labels = vec![String::new(); q.choices.len()];
    let mut bindings = vec![false; q.choices.len()];
    for name in &q.binding_order {
        if let Expr::Choice(index) = q.bindings[name] {
            labels[index] = name.clone();
            bindings[index] = true;
        }
    }
    label_expr(q, &q.find, "find", terms, &mut labels);
    for (i, filter) in q.filters.iter().enumerate() {
        label_expr(q, filter, &format!("where #{}", i + 1), terms, &mut labels);
    }
    if let Some(group) = &q.group {
        label_expr(q, group, "group by", terms, &mut labels);
    }
    for (i, measure) in q.measures.iter().enumerate() {
        label_expr(
            q,
            measure,
            &format!("measure #{}", i + 1),
            terms,
            &mut labels,
        );
    }
    let original = labels.clone();
    for (i, (name, binding)) in original.iter().zip(&bindings).enumerate() {
        if *binding {
            continue;
        }
        let indices: Vec<_> = original
            .iter()
            .zip(&bindings)
            .enumerate()
            .filter_map(|(j, (label, bound))| (!bound && label == name).then_some(j))
            .collect();
        if indices.len() > 1 {
            let duplicate = indices.iter().position(|&j| j == i).expect("present label") + 1;
            labels[i] = format!("{name} ({duplicate})");
        }
    }
    labels
}
