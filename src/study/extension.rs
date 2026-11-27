use super::{
    plan::Role,
    syntax::{self, Expr, Literal},
};
use crate::{
    engine_json::{self, Value},
    Result,
};
use std::collections::HashSet;

pub(super) const PINNED_CALENDAR: &str = "nyse-core-2025-01-05-v1";
pub(super) const BUNDLED: &[&str] = &[
    include_str!("../../study/extensions/quiet_friday_close.v1.json"),
    include_str!("../../study/extensions/quiet_friday_close.v2.json"),
];

pub(super) struct Definition {
    pub id: String,
    pub version: u32,
    pub role: Role,
    pub body: Expr,
    pub params: Vec<Param>,
    pub pins: HashSet<String>,
    pub digest: String,
    pub cases: Vec<Case>,
}

pub(super) struct Case {
    pub anchor: String,
    pub arguments: String,
    pub expected: Option<bool>,
}

pub(super) struct Param {
    pub name: String,
    pub default: Literal,
    pub domain: Domain,
}

pub(super) enum Domain {
    Duration {
        min_ms: Option<i64>,
        max_ms: Option<i64>,
        grid: bool,
    },
    Ratio {
        min: Option<String>,
        max: Option<String>,
        min_exclusive: bool,
        max_exclusive: bool,
    },
    Number {
        whole_min: Option<usize>,
        whole_max: Option<usize>,
    },
}

impl Definition {
    pub fn parse(text: &str) -> Result<Self> {
        if text.len() > 262_144 {
            return Err("definition artifact exceeds 256 KiB".into());
        }
        let json = engine_json::parse(text)?;
        if json.field("artifact")?.text()? != "limen.sfd.definition" {
            return Err("invalid Filang definition artifact".into());
        }
        let id = json.field("id")?.text()?;
        let version = json.field("version")?.number()?;
        if !identifier(id) || version == 0 || version_suffix(id) {
            return Err("invalid definition id or version".into());
        }
        let role = match json.field("kind")?.text()? {
            "condition" => Role::Condition,
            "event" => Role::Event,
            _ => return Err("definition kind must be condition or event".into()),
        };
        let mut seen = HashSet::new();
        let mut params = Vec::new();
        if let Some(values) = json.object()?.get("params") {
            for value in values.array()? {
                let name = value.field("name")?.text()?;
                if !identifier(name) || !seen.insert(name) || params.len() >= 64 {
                    return Err(format!("invalid or duplicate parameter {name}"));
                }
                let default = match syntax::expression(value.field("default")?.text()?)? {
                    Expr::Scalar(default) => default,
                    _ => return Err(format!("parameter {name} needs a literal default")),
                };
                let domain = domain(
                    value.field("type")?.text()?,
                    value.object()?.get("domain"),
                    name,
                )?;
                params.push(Param {
                    name: name.to_owned(),
                    default,
                    domain,
                });
            }
        }
        let mut pins = HashSet::new();
        if let Some(values) = json.object()?.get("depends") {
            for value in values.array()? {
                let pin = if let Some(calendar) = value.object()?.get("calendar") {
                    format!("{}/{}", calendar.text()?, value.field("table")?.text()?)
                } else {
                    let version: u32 = value.field("version")?.number()?;
                    format!("{}@{version}", value.field("name")?.text()?)
                };
                if !pins.insert(pin) {
                    return Err("duplicate definition dependency".into());
                }
            }
        }
        let mut cases = Vec::new();
        if let Some(values) = json.object()?.get("conformance") {
            for value in values.array()? {
                if cases.len() >= 64 {
                    return Err("definition exceeds 64 conformance cases".into());
                }
                let mut arguments = Vec::new();
                if let Some(args) = value.object()?.get("args") {
                    for (key, literal) in args.object()? {
                        let literal = match literal {
                            Value::Text(text) | Value::Number(text) => text,
                            _ => return Err("conformance arguments must be literal values".into()),
                        };
                        if !identifier(key)
                            || !matches!(syntax::expression(literal)?, Expr::Scalar(_))
                        {
                            return Err("invalid conformance argument".into());
                        }
                        arguments.push(format!("{key}: {literal}"));
                    }
                }
                let expected = match value.field("expect")?.text()? {
                    "true" => Some(true),
                    "false" => Some(false),
                    "unknown" => None,
                    _ => return Err("invalid conformance expectation".into()),
                };
                cases.push(Case {
                    anchor: value.field("anchor")?.text()?.into(),
                    arguments: arguments.join(", "),
                    expected,
                });
            }
        }
        Ok(Self {
            id: id.to_owned(),
            version,
            role,
            params,
            pins,
            digest: crate::hash::sha256(text.as_bytes()),
            cases,
            body: syntax::expression(json.field("body")?.text()?)?,
        })
    }

    pub fn alias(&self) -> String {
        if self.version == 1 {
            self.id.clone()
        } else {
            format!("{}_v{}", self.id, self.version)
        }
    }

    pub fn key(&self) -> String {
        format!("{}@{}", self.id, self.version)
    }
}

fn identifier(name: &str) -> bool {
    let mut bytes = name.bytes();
    matches!(bytes.next(), Some(b'a'..=b'z' | b'_'))
        && bytes.all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

fn version_suffix(name: &str) -> bool {
    name.rsplit_once("_v").map_or(false, |(_, v)| {
        !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit())
    })
}

fn domain(kind: &str, value: Option<&Value>, name: &str) -> Result<Domain> {
    let empty = Default::default();
    let fields = value.map(Value::object).transpose()?.unwrap_or(&empty);
    let allowed: &[&str] = match kind {
        "Duration" => &["minMs", "maxMs", "barMultiple"],
        "Ratio" => &[
            "ratioMin",
            "ratioMax",
            "ratioMinExclusive",
            "ratioMaxExclusive",
        ],
        "Number" => &["wholeMin", "wholeMax"],
        _ => return Err(format!("parameter {name} has an unsupported type")),
    };
    if let Some(key) = fields.keys().find(|key| !allowed.contains(&key.as_str())) {
        return Err(format!(
            "parameter {name}: {key} is outside its {kind} domain"
        ));
    }
    let ms = |key| fields.get(key).map(Value::number::<i64>).transpose();
    let count = |key| fields.get(key).map(Value::number::<usize>).transpose();
    let flag = |key| fields.get(key).map_or(Ok(false), Value::bool);
    let ratio = |key| {
        fields
            .get(key)
            .map(|number| {
                let text = match number {
                    Value::Text(text) | Value::Number(text) => text,
                    _ => return Err("invalid ratio limit".into()),
                };
                match syntax::expression(text)? {
                    Expr::Scalar(literal) => literal.wire_ratio(),
                    _ => Err("invalid ratio limit".into()),
                }
            })
            .transpose()
    };
    Ok(match kind {
        "Duration" => Domain::Duration {
            min_ms: ms("minMs")?,
            max_ms: ms("maxMs")?,
            grid: flag("barMultiple")?,
        },
        "Ratio" => Domain::Ratio {
            min: ratio("ratioMin")?,
            max: ratio("ratioMax")?,
            min_exclusive: flag("ratioMinExclusive")?,
            max_exclusive: flag("ratioMaxExclusive")?,
        },
        "Number" => Domain::Number {
            whole_min: count("wholeMin")?,
            whole_max: count("wholeMax")?,
        },
        _ => unreachable!("parameter type was checked"),
    })
}
