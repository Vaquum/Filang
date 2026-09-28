use crate::{backtest::Metrics, Result};
use std::{fmt::Write as _, fs, path::Path};
/// Small JSON writer; all external strings pass through this encoder.
pub fn quote(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c < ' ' => {
                write!(&mut out, "\\u{:04x}", c as u32).unwrap();
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
pub fn num(n: f64) -> String {
    if n.is_finite() {
        format!("{n:.17}")
    } else {
        "null".into()
    }
}
pub fn write(path: impl AsRef<Path>, text: &str) -> Result<()> {
    fs::write(path.as_ref(), text).map_err(|e| format!("write {}: {e}", path.as_ref().display()))
}
pub fn create_out(path: &str) -> Result<()> {
    let p = Path::new(path);
    if p.exists() {
        return Err(format!(
            "output already exists: {path}; use a new run directory"
        ));
    }
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::create_dir(p).map_err(|e| e.to_string())
}
pub fn metrics(m: &Metrics, interval: i64) -> String {
    format!("{{\"net_return_pct\":{},\"gross_return_pct\":{},\"cagr_pct\":{},\"max_drawdown_pct\":{},\"sharpe_annualized_naive\":{},\"trades\":{},\"exposure_pct\":{},\"mean_bps_per_bar\":{},\"mean_trade_bps\":{},\"periods\":{}}}",num(m.lite.return_pct()),num(m.gross_return_pct),num(m.cagr_pct),num(m.max_drawdown_pct),num(m.lite.sharpe(interval)),m.lite.entries,num(100.0*m.lite.exposure()),num(10000.0*m.lite.sum/m.lite.periods as f64),num(m.mean_trade_bps),m.lite.periods)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn escaping() {
        assert_eq!(quote("x\n\"\\"), "\"x\\n\\\"\\\\\"");
        assert_eq!(num(f64::NAN), "null");
    }
}
