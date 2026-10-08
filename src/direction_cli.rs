//! Strict CLI adapter for the grouped complete-geometry direction sweep.
use crate::{
    direction::{self, Config},
    geometry::GeometryMode,
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
    let default_workers = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
        .min(1024)
        .to_string();
    let bars = flags
        .remove("--bars")
        .unwrap_or_else(|| "2,3,4,5,6,7,8,9,10".into())
        .split(',')
        .map(|n| n.parse::<usize>().map_err(|_| "invalid --bars".to_owned()))
        .collect::<Result<Vec<_>>>()?;
    let modes = flags
        .remove("--modes")
        .unwrap_or_else(|| "oriented,unoriented".into())
        .split(',')
        .map(GeometryMode::parse)
        .collect::<Result<Vec<_>>>()?;
    let config = Config {
        data: take(&mut flags, "--data")?,
        out: take(&mut flags, "--out")?,
        interval_seconds: value(&mut flags, "--interval-seconds", "900")?,
        history_start: take(&mut flags, "--history-start")?,
        validation_start: take(&mut flags, "--validation-start")?,
        test_start: take(&mut flags, "--test-start")?,
        end: take(&mut flags, "--end")?,
        bars,
        modes,
        workers: value(&mut flags, "--workers", &default_workers)?,
        memory_mib: value(&mut flags, "--memory-mib", "2048")?,
        max_rows: value(&mut flags, "--max-rows", "2000000")?,
        resume: value(&mut flags, "--resume", "false")?,
        max_tasks: value(&mut flags, "--max-tasks", "0")?,
    };
    if !flags.is_empty() {
        return Err(format!("unknown direction flags: {:?}", flags.keys()));
    }
    direction::run(config)
}
