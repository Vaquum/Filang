use super::syntax::{self, Expr, Literal};
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
    pub event: bool,
    pub body: Expr,
    pub params: Vec<Param>,
    pub pins: HashSet<String>,
}

pub(super) struct Param {
    pub name: String,
    pub default: Literal,
    pub kind: ParamKind,
    pub domain: Domain,
}

pub(super) enum ParamKind {
    Duration,
    Ratio,
    Number,
}

#[derive(Default)]
pub(super) struct Domain {
    pub min_ms: Option<i64>,
    pub max_ms: Option<i64>,
    pub grid: bool,
    pub whole_min: Option<usize>,
    pub whole_max: Option<usize>,
    pub ratio_min: Option<String>,
    pub ratio_max: Option<String>,
    pub ratio_min_exclusive: bool,
    pub ratio_max_exclusive: bool,
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
        let event = match json.field("kind")?.text()? {
            "condition" => false,
            "event" => true,
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
                let kind = match value.field("type")?.text()? {
                    "Duration" => ParamKind::Duration,
                    "Ratio" => ParamKind::Ratio,
                    "Number" => ParamKind::Number,
                    _ => return Err(format!("parameter {name} has an unsupported type")),
                };
                let domain = value
                    .object()?
                    .get("domain")
                    .map_or(Ok(Domain::default()), domain)?;
                params.push(Param {
                    name: name.to_owned(),
                    default,
                    kind,
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
        Ok(Self {
            id: id.to_owned(),
            version,
            event,
            params,
            pins,
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

fn domain(value: &Value) -> Result<Domain> {
    let fields = value.object()?;
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
    Ok(Domain {
        min_ms: ms("minMs")?,
        max_ms: ms("maxMs")?,
        grid: flag("barMultiple")?,
        whole_min: count("wholeMin")?,
        whole_max: count("wholeMax")?,
        ratio_min: ratio("ratioMin")?,
        ratio_max: ratio("ratioMax")?,
        ratio_min_exclusive: flag("ratioMinExclusive")?,
        ratio_max_exclusive: flag("ratioMaxExclusive")?,
    })
}
