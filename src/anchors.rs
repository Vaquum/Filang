//! Known constructions are macros over the general atom language. The compiler
//! never sees these labels. Parameters and every expanded expression are public.
use crate::{
    backtest::Rule,
    lang::{Graph, Id, Op},
    Result,
};
#[derive(Clone, Debug)]
pub struct Anchor {
    pub key: String,
    pub profile: String,
    pub kind: String,
    pub periods: [usize; 3],
    pub root: Id,
    pub rules: Vec<Rule>,
    pub reference_key: String,
}
fn ratio(g: &mut Graph, a: Id, b: Id) -> Id {
    let q = g.binary(Op::Div, a, b);
    let one = g.constant(1.0);
    g.binary(Op::Sub, q, one)
}
pub fn expand(g: &mut Graph, kind: &str, p: [usize; 3], profile: &str) -> Result<Id> {
    if p.iter().any(|w| *w < 2 || *w > 100000) {
        return Err("anchor periods require 2..100000".into());
    }
    let c = g.source(3);
    let h = g.source(1);
    let l = g.source(2);
    let one = g.constant(1.0);
    Ok(match kind {
        "sma" => {
            let m = g.unary(
                if profile == "talib" {
                    Op::MeanSum(p[0])
                } else {
                    Op::Mean(p[0])
                },
                c,
            );
            ratio(g, c, m)
        }
        "ema" => {
            let m = g.unary(Op::Ema(p[0]), c);
            ratio(g, c, m)
        }
        "ema_cross" => {
            if p[0] >= p[1] {
                return Err("fast must be below slow".into());
            }
            let a = g.unary(Op::Ema(p[0]), c);
            let b = g.unary(Op::Ema(p[1]), c);
            ratio(g, a, b)
        }
        "rsi" => {
            let delta = g.unary(Op::Diff(1), c);
            let abs = g.unary(Op::Abs, delta);
            let u = g.binary(Op::Add, abs, delta);
            let up = g.unary(Op::Wilder(p[0]), u);
            let total = g.unary(Op::Wilder(p[0]), abs);
            let q = g.binary(
                if profile == "talib" {
                    Op::Div0
                } else {
                    Op::Div
                },
                up,
                total,
            );
            g.binary(Op::Sub, q, one)
        }
        "bollinger" => {
            let m = g.unary(
                if profile == "talib" {
                    Op::MeanSum(p[0])
                } else {
                    Op::Mean(p[0])
                },
                c,
            );
            let s = g.unary(
                if profile == "talib" {
                    Op::StdSum(p[0])
                } else {
                    Op::Std(p[0])
                },
                c,
            );
            let d = g.binary(Op::Sub, c, m);
            g.binary(Op::Div, d, s)
        }
        "macd" => {
            if p[0] >= p[1] {
                return Err("fast must be below slow".into());
            }
            let input = if profile == "talib" {
                g.unary(Op::Skip(p[1] - p[0]), c)
            } else {
                c
            };
            let a = g.unary(Op::Ema(p[0]), input);
            let b = g.unary(Op::Ema(p[1]), c);
            let d = g.binary(Op::Sub, a, b);
            let sig = g.unary(Op::Ema(p[2]), d);
            let hist = g.binary(Op::Sub, d, sig);
            g.binary(Op::Div, hist, c)
        }
        "roc" => {
            let prev = g.unary(Op::Lag(p[0]), c);
            ratio(g, c, prev)
        }
        "channel" => {
            let hi = g.unary(Op::Max(p[0]), h);
            let lo = g.unary(Op::Min(p[0]), l);
            let a = g.binary(Op::Sub, c, lo);
            let b = g.binary(Op::Sub, hi, lo);
            g.binary(Op::Div, a, b)
        }
        "atr" => {
            let pc = g.unary(Op::Lag(1), c);
            let r = g.binary(Op::Sub, h, l);
            let a = g.binary(Op::Sub, h, pc);
            let a = g.unary(Op::Abs, a);
            let b = g.binary(Op::Sub, l, pc);
            let b = g.unary(Op::Abs, b);
            let ab = g.binary(Op::Max2, a, b);
            let tr = g.binary(Op::Max2, r, ab);
            let atr = g.unary(Op::Wilder(p[0]), tr);
            g.binary(Op::Div, atr, c)
        }
        "cash" | "buy_hold" => one,
        _ => return Err(format!("unknown anchor kind {kind}")),
    })
}
fn rules(kind: &str) -> Vec<Rule> {
    let vals: &[f64] = match kind {
        "rsi" => &[-0.4, 0.0, 0.4],
        "bollinger" => &[-2.0, 0.0, 2.0],
        "channel" => &[0.2, 0.5, 0.8],
        "atr" => &[0.005, 0.01, 0.02],
        "cash" => &[2.0],
        _ => &[0.0],
    };
    vals.iter()
        .flat_map(|&threshold| [false, true].map(move |greater| Rule { threshold, greater }))
        .collect()
}
pub fn catalog() -> Result<(Graph, Vec<Anchor>)> {
    let mut g = Graph::new();
    let mut rows = vec![];
    let legacy = [
        ("fixed_0", "rsi", [14, 14, 14], 0.0, true),
        ("fixed_1", "rsi", [14, 14, 14], -0.4, false),
        ("fixed_2", "ema_cross", [24, 96, 9], 0.0, true),
        ("fixed_3", "macd", [12, 26, 9], 0.0, true),
        ("fixed_4", "sma", [200, 200, 200], 0.0, true),
        ("fixed_5", "bollinger", [20, 20, 20], -2.0, false),
        ("buy_hold", "buy_hold", [2, 2, 2], 0.0, true),
        ("cash", "cash", [2, 2, 2], 2.0, true),
    ];
    for (key, kind, p, t, gt) in legacy {
        let root = expand(&mut g, kind, p, "filang_v1")?;
        rows.push(Anchor {
            key: key.into(),
            profile: "filang_v1".into(),
            kind: kind.into(),
            periods: p,
            root,
            rules: vec![Rule {
                threshold: t,
                greater: gt,
            }],
            reference_key: key.into(),
        });
    }
    for (kind, p) in [
        ("sma", [20, 20, 20]),
        ("sma", [200, 200, 200]),
        ("ema", [24, 24, 24]),
        ("ema_cross", [24, 96, 9]),
        ("rsi", [14, 14, 14]),
        ("bollinger", [20, 20, 20]),
        ("macd", [12, 26, 9]),
        ("roc", [14, 14, 14]),
        ("channel", [14, 14, 14]),
        ("atr", [14, 14, 14]),
    ] {
        let root = expand(&mut g, kind, p, "talib")?;
        rows.push(Anchor {
            key: format!("talib_{kind}_{}_{}_{}", p[0], p[1], p[2]),
            profile: "talib".into(),
            kind: kind.into(),
            periods: p,
            root,
            rules: rules(kind),
            reference_key: String::new(),
        });
    }
    Ok((g, rows))
}
/// A bounded parameter neighborhood: no root topology invention and no inactive
/// parameters counted as diversity. Every member retains its parent and offsets.
pub fn neighborhood(radius: usize, thresholds: usize) -> Result<(Graph, Vec<Anchor>)> {
    if radius > 32 || !(3..=4097).contains(&thresholds) || thresholds % 2 == 0 {
        return Err("radius <=32; odd threshold count in 3..4097".into());
    }
    let (mut g, base) = catalog()?;
    let mut out = base.clone();
    let mut seen = std::collections::HashSet::new();
    for a in base.into_iter().filter(|a| a.profile == "talib") {
        let width = if a.kind == "macd" || a.kind == "ema_cross" {
            3
        } else {
            1
        };
        for d in -(radius as isize)..=radius as isize {
            for e in if width == 3 {
                -(radius as isize)..=radius as isize
            } else {
                0..=0
            } {
                let mut p = a.periods;
                p[0] = (a.periods[0] as isize + d).max(2) as usize;
                if width == 3 {
                    p[1] = (a.periods[1] as isize + e).max(2) as usize;
                }
                if p[0] >= p[1] && width == 3 {
                    continue;
                }
                let root = expand(&mut g, &a.kind, p, "talib")?;
                if !seen.insert((a.kind.clone(), p[0], p[1], p[2])) {
                    continue;
                }
                let (center, span) = match a.kind.as_str() {
                    "rsi" => (0.0, 0.8),
                    "bollinger" => (0.0, 3.0),
                    "channel" => (0.5, 0.49),
                    "atr" => (0.02, 0.019),
                    _ => (0.0, 0.03),
                };
                let rules = (0..thresholds)
                    .flat_map(|i| {
                        let threshold =
                            center + span * (2.0 * i as f64 / (thresholds - 1) as f64 - 1.0);
                        [false, true].map(move |greater| Rule { threshold, greater })
                    })
                    .collect();
                out.push(Anchor {
                    key: format!("{}_d{d}_e{e}", a.key),
                    profile: a.profile.clone(),
                    kind: a.kind.clone(),
                    periods: p,
                    root,
                    rules,
                    reference_key: a.key.clone(),
                });
            }
        }
    }
    Ok((g, out))
}
