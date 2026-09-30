//! Ten established constructions are authoring macros over general atoms.
//! Neither family names nor anchor outcomes enter numerical/execution kernels.
use crate::{
    lang::{Graph, Id, Op},
    regions::Grid,
    Result,
};
pub const KINDS: [&str; 10] = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger",
    "stochastic",
    "atr",
    "roc",
    "cci",
    "vwap",
];
pub fn defaults(kind: &str) -> Result<(usize, f64, Grid)> {
    let (n, cutoff, grid) = match kind {
        "sma" => (200, 1., "999000:1:2001:1000000"),
        "ema" => (24, 1., "999000:1:2001:1000000"),
        "rsi" => (14, 1., "998000:2:2001:1000000"),
        "macd" => (12, 0., "-1000:1:2001:10000000"),
        "bollinger" => (20, 2., "198000:2:2001:100000"),
        "stochastic" => (14, 0., "-1000:1:2001:1000000"),
        "atr" => (14, 0.01, "99000:1:2001:10000000"),
        "roc" => (14, 1., "999000:1:2001:1000000"),
        "cci" => (20, 1., "99000:1:2001:100000"),
        "vwap" => (20, 1., "999000:1:2001:1000000"),
        _ => return Err(format!("unknown cohort family {kind}")),
    };
    Ok((n, cutoff, Grid::parse(grid)?))
}
fn scale(g: &mut Graph, x: Id, k: f64) -> Id {
    let c = g.constant(k);
    g.binary(Op::Mul, x, c)
}
fn divide(g: &mut Graph, x: Id, k: f64) -> Id {
    let c = g.constant(k);
    g.binary(Op::Div, x, c)
}
fn mix(g: &mut Graph, x: Id, y: Id, b: f64) -> Id {
    if b == 0. {
        return x;
    }
    let delta = g.binary(Op::Sub, y, x);
    let k = g.constant(b);
    let adj = g.binary(Op::Mul, k, delta);
    g.binary(Op::Add, x, adj)
}
pub fn stripe(kind: &str, n: usize, a: f64) -> Result<(Graph, [Id; 4])> {
    defaults(kind)?;
    if !(2..100000).contains(&n) || !a.is_finite() || a.abs() > 0.25 {
        return Err("invalid cohort source/window".into());
    }
    if kind == "sma" {
        let (g, v) = crate::micro::stripe(n, a)?;
        return Ok((g, [v[0], v[1], v[2], v[0]]));
    }
    let mut g = Graph::new();
    let c = g.source(3);
    let p = if a == 0. {
        c
    } else {
        let o = g.source(0);
        let d = g.binary(Op::Sub, o, c);
        let k = g.constant(a);
        let z = g.binary(Op::Mul, k, d);
        g.binary(Op::Add, c, z)
    };
    let h = g.source(1);
    let l = g.source(2);
    let ids = match kind {
        "ema" => {
            let m = g.unary(Op::Ema(n), p);
            let q = g.unary(Op::Ema(n + 1), p);
            [p, m, q, p]
        }
        "rsi" => {
            let d = g.unary(Op::Diff(1), p);
            let z = g.unary(Op::Abs, d);
            let u = g.binary(Op::Add, z, d);
            let un = g.unary(Op::Wilder(n), u);
            let an = g.unary(Op::Wilder(n), z);
            let uq = g.unary(Op::Wilder(n + 1), u);
            let aq = g.unary(Op::Wilder(n + 1), z);
            [un, an, uq, aq]
        }
        "macd" => {
            if n >= 26 {
                return Err("MACD fast period must be below fixed slow26".into());
            }
            let input = g.unary(Op::Skip(26 - n), p);
            let fast = g.unary(Op::Ema(n), input);
            let slow = g.unary(Op::Ema(26), p);
            let line = g.binary(Op::Sub, fast, slow);
            let s = g.unary(Op::Ema(9), line);
            let q = g.unary(Op::Ema(10), line);
            [p, line, s, q]
        }
        "bollinger" => {
            let m = g.unary(Op::MeanSum(n), p);
            let s = g.unary(Op::StdSum(n), p);
            let q = g.unary(Op::StdSum(n + 1), p);
            [p, m, s, q]
        }
        "stochastic" => {
            let lo = g.unary(Op::Min(n), l);
            let hi = g.unary(Op::Max(n), h);
            let z = g.binary(Op::Sub, p, lo);
            let span = g.binary(Op::Sub, hi, lo);
            let span = divide(&mut g, span, 100.);
            let fast = g.binary(Op::Div0, z, span);
            let k = g.unary(Op::MeanSum(3), fast);
            let d = g.unary(Op::MeanSum(3), k);
            let q = g.unary(Op::MeanSum(4), k);
            [k, d, q, p]
        }
        "atr" => {
            let prev = g.unary(Op::Lag(1), p);
            let range = g.binary(Op::Sub, h, l);
            let x = g.binary(Op::Sub, h, prev);
            let x = g.unary(Op::Abs, x);
            let y = g.binary(Op::Sub, l, prev);
            let y = g.unary(Op::Abs, y);
            let z = g.binary(Op::Max2, x, y);
            let tr = g.binary(Op::Max2, range, z);
            let m = g.unary(Op::Wilder(n), tr);
            let q = g.unary(Op::Wilder(n + 1), tr);
            [p, m, q, p]
        }
        "roc" => {
            let x = g.unary(Op::Lag(n), p);
            let y = g.unary(Op::Lag(n + 1), p);
            [p, x, y, p]
        }
        "cci" => {
            let hl = g.binary(Op::Add, h, l);
            let tp = g.binary(Op::Add, hl, p);
            let tp = divide(&mut g, tp, 3.);
            let m = g.unary(Op::MeanSum(n), tp);
            let dev = g.unary(Op::MeanAbsDev(n), tp);
            let q = g.unary(Op::MeanAbsDev(n + 1), tp);
            [tp, m, dev, q]
        }
        "vwap" => {
            let hl = g.binary(Op::Add, h, l);
            let tp = g.binary(Op::Add, hl, p);
            let tp = divide(&mut g, tp, 3.);
            let v = g.source(4);
            let pv = g.binary(Op::Mul, tp, v);
            let z = g.unary(Op::MeanSum(n), pv);
            let w = g.unary(Op::MeanSum(n), v);
            let x = g.binary(Op::Div, z, w);
            let z = g.unary(Op::MeanSum(n + 1), pv);
            let w = g.unary(Op::MeanSum(n + 1), v);
            let y = g.binary(Op::Div, z, w);
            [p, x, y, p]
        }
        _ => unreachable!(),
    };
    Ok((g, ids))
}
pub fn output(g: &mut Graph, kind: &str, ids: [Id; 4], b: f64, c: f64) -> Result<Id> {
    if !b.is_finite() || !(0.0..=1.0).contains(&b) || !c.is_finite() {
        return Err("invalid mixture/cutoff".into());
    }
    if kind == "sma" {
        return crate::micro::output(g, [ids[0], ids[1], ids[2]], b, c);
    }
    let value = match kind {
        "ema" | "roc" | "vwap" => {
            let den = mix(g, ids[1], ids[2], b);
            g.binary(Op::Div, ids[0], den)
        }
        "rsi" => {
            let u = mix(g, ids[0], ids[2], b);
            let z = mix(g, ids[1], ids[3], b);
            g.binary(Op::Div0, u, z)
        }
        "macd" => {
            let sig = mix(g, ids[2], ids[3], b);
            let hist = g.binary(Op::Sub, ids[1], sig);
            g.binary(Op::Div, hist, ids[0])
        }
        "bollinger" => {
            let dev = mix(g, ids[2], ids[3], b);
            let gap = g.binary(Op::Sub, ids[1], ids[0]);
            g.binary(Op::Div, gap, dev)
        }
        "stochastic" => {
            let sig = mix(g, ids[1], ids[2], b);
            let gap = g.binary(Op::Sub, ids[0], sig);
            divide(g, gap, 100.)
        }
        "atr" => {
            let tr = mix(g, ids[1], ids[2], b);
            g.binary(Op::Div, tr, ids[0])
        }
        "cci" => {
            let dev = mix(g, ids[2], ids[3], b);
            let den = scale(g, dev, 0.015);
            let gap = g.binary(Op::Sub, ids[0], ids[1]);
            let value = g.binary(Op::Div0, gap, den);
            divide(g, value, 100.)
        }
        _ => return Err("unknown cohort family".into()),
    };
    let offset = g.constant(c);
    Ok(g.binary(Op::Sub, value, offset))
}
pub fn catalog_id() -> Result<String> {
    let mut text = String::from("filang-ten-cohort-v1|strict-gt|spot_open_v1|mad-chronological-v1");
    for kind in KINDS {
        let (n, c, _) = defaults(kind)?;
        let (mut g, ids) = stripe(kind, n, 0.)?;
        let root = output(&mut g, kind, ids, 0., c)?;
        text += kind;
        text += &g.identity(root);
    }
    Ok(crate::hash::sha256(text.as_bytes()))
}

/// Local parity evidence tied to the executable, expanded catalog and dataset.
pub fn validate_gate(path: &str, digest: &str) -> Result<()> {
    use std::{collections::HashMap, fs, path::Path};
    let text = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let seal = fs::read_to_string(format!("{path}.sha256")).map_err(|e| e.to_string())?;
    if crate::hash::sha256(text.as_bytes()) != seal.trim() {
        return Err("cohort gate checksum".into());
    }
    let mut m = HashMap::new();
    for l in text.lines() {
        let (k, v) = l.split_once('=').ok_or("bad cohort gate")?;
        if m.insert(k, v).is_some() {
            return Err("duplicate cohort gate field".into());
        }
    }
    for (k, v) in [
        ("version", "cohort-v1".to_owned()),
        ("status", "PASS".into()),
        ("data_sha256", digest.into()),
        ("engine_sha256", crate::anchor_run::engine_id()?),
        ("catalog_sha256", catalog_id()?),
    ] {
        if m.get(k).copied() != Some(v.as_str()) {
            return Err(format!("cohort gate {k} mismatch"));
        }
    }
    let base = Path::new(path).parent().ok_or("gate parent")?;
    for file in [
        "manifest.json",
        "verification.json",
        "metrics.bin",
        "features.bin",
        "traces.bin",
    ] {
        let key = format!("{file}_sha256");
        let hash = crate::hash::sha256(&fs::read(base.join(file)).map_err(|e| e.to_string())?);
        if m.get(key.as_str()).copied() != Some(hash.as_str()) {
            return Err(format!("cohort evidence changed: {file}"));
        }
    }
    Ok(())
}
