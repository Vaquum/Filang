//! Strict CLI adapter for causal, feature-only geometry key export.
use crate::{
    geometry_keys::{self, Config},
    Result,
};
use std::{collections::HashMap, str::FromStr};

fn take(flags: &mut HashMap<String, String>, key: &str) -> Result<String> {
    flags.remove(key).ok_or_else(|| format!("missing {key}"))
}

fn value<T: FromStr>(flags: &mut HashMap<String, String>, key: &str, default: &str) -> Result<T> {
    flags
        .remove(key)
        .unwrap_or_else(|| default.into())
        .parse()
        .map_err(|_| format!("invalid {key}"))
}

pub fn cli(mut flags: HashMap<String, String>) -> Result<String> {
    let config = Config {
        data: take(&mut flags, "--data")?,
        out: take(&mut flags, "--out")?,
        interval_seconds: value(&mut flags, "--interval-seconds", "900")?,
        history_start: take(&mut flags, "--history-start")?,
        end: take(&mut flags, "--end")?,
        bars: value(&mut flags, "--bars", "10")?,
        memory_mib: value(&mut flags, "--memory-mib", "256")?,
        max_rows: value(&mut flags, "--max-rows", "2000000")?,
        resume: value(&mut flags, "--resume", "false")?,
    };
    if !flags.is_empty() {
        return Err(format!("unknown geometry key flags: {:?}", flags.keys()));
    }
    geometry_keys::run(config)
}
