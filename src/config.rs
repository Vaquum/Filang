use crate::{backtest::Costs, data::date, Result};
use std::{collections::BTreeMap, fs};

#[derive(Clone, Debug)]
pub struct Config {
    pub data: String,
    pub out: String,
    pub train_start: i64,
    pub validation_start: i64,
    pub validation_end: i64,
    pub evaluation_start: i64,
    pub evaluation_end: i64,
    pub interval: i64,
    pub generated: usize,
    pub seed: u64,
    pub windows: Vec<usize>,
    pub quantiles: Vec<f64>,
    pub batch_size: usize,
    pub memory_bytes: usize,
    pub top_k: usize,
    pub costs: Costs,
    pub blocks: usize,
    pub min_train_trades: usize,
    pub min_validation_trades: usize,
    pub min_exposure: f64,
    pub max_exposure: f64,
    pub stability_penalty: f64,
    pub complexity_penalty: f64,
    pub max_depth: usize,
    pub max_nodes: usize,
    pub scorer: String,
    pub lags: Vec<usize>,
    pub templates: Vec<usize>,
    pub injection_stride: usize,
}
impl Config {
    pub fn load(path: &str) -> Result<Self> {
        Self::parse(&fs::read_to_string(path).map_err(|e| format!("read config: {e}"))?)
    }
    pub fn parse(text: &str) -> Result<Self> {
        let mut m = BTreeMap::new();
        for (i, line) in text.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let (k, v) = line
                .split_once('=')
                .ok_or_else(|| format!("config line {}: expected key=value", i + 1))?;
            if m.insert(k.trim().to_string(), v.trim().to_string())
                .is_some()
            {
                return Err(format!("duplicate config key {k}"));
            }
        }
        fn take(m: &mut BTreeMap<String, String>, k: &str) -> Result<String> {
            m.remove(k).ok_or_else(|| format!("missing config key {k}"))
        }
        fn number<T: std::str::FromStr>(m: &mut BTreeMap<String, String>, k: &str) -> Result<T> {
            take(m, k)?
                .parse()
                .map_err(|_| format!("invalid config key {k}"))
        }
        if take(&mut m, "version")? != "1" {
            return Err("unsupported config version".into());
        }
        let data = take(&mut m, "data")?;
        let out = take(&mut m, "out")?;
        let train_start = date(&take(&mut m, "train_start")?)?;
        let validation_start = date(&take(&mut m, "validation_start")?)?;
        let validation_end = date(&take(&mut m, "validation_end")?)?;
        let evaluation_start = date(&take(&mut m, "evaluation_start")?)?;
        let evaluation_end = date(&take(&mut m, "evaluation_end")?)?;
        let windows = take(&mut m, "windows")?
            .split(',')
            .map(|x| {
                x.trim()
                    .parse::<usize>()
                    .map_err(|_| "bad window list".to_string())
            })
            .collect::<Result<Vec<_>>>()?;
        let quantiles = take(&mut m, "quantiles")?
            .split(',')
            .map(|x| {
                x.trim()
                    .parse::<f64>()
                    .map_err(|_| "bad quantile list".to_string())
            })
            .collect::<Result<Vec<_>>>()?;
        let lags = m
            .remove("lags")
            .unwrap_or_else(|| "1,2,3,4,5,6,7,8".into())
            .split(',')
            .map(|s| {
                s.trim()
                    .parse::<usize>()
                    .map_err(|_| "invalid lag list".to_string())
            })
            .collect::<Result<Vec<_>>>()?;
        let names = [
            "interact",
            "contrast",
            "delta",
            "zscore",
            "minmax",
            "attenuate",
            "smooth",
            "lag_interact",
        ];
        let templates = m
            .remove("templates")
            .unwrap_or_else(|| names.join(","))
            .split(',')
            .map(|s| {
                names
                    .iter()
                    .position(|n| *n == s.trim())
                    .ok_or_else(|| format!("unknown generation template {s}"))
            })
            .collect::<Result<Vec<_>>>()?;
        let injection_stride = m
            .remove("pool_injection_stride")
            .unwrap_or_else(|| "8".into())
            .parse::<usize>()
            .map_err(|_| "invalid pool_injection_stride")?;
        let c = Self {
            lags,
            templates,
            injection_stride,
            data,
            out,
            train_start,
            validation_start,
            validation_end,
            evaluation_start,
            evaluation_end,
            windows,
            quantiles,
            interval: number(&mut m, "interval_seconds")?,
            generated: number(&mut m, "generated_features")?,
            seed: number(&mut m, "seed")?,
            batch_size: number(&mut m, "batch_size")?,
            memory_bytes: number::<usize>(&mut m, "memory_mib")?
                .checked_mul(1024 * 1024)
                .ok_or("memory overflow")?,
            top_k: number(&mut m, "top_k")?,
            costs: Costs {
                fee_bps: number(&mut m, "fee_bps")?,
                slip_bps: number(&mut m, "slip_bps")?,
            }
            .validate()?,
            blocks: number(&mut m, "validation_blocks")?,
            min_train_trades: number(&mut m, "min_train_trades")?,
            min_validation_trades: number(&mut m, "min_validation_trades")?,
            min_exposure: number(&mut m, "min_exposure")?,
            max_exposure: number(&mut m, "max_exposure")?,
            stability_penalty: number(&mut m, "stability_penalty")?,
            complexity_penalty: number(&mut m, "complexity_penalty")?,
            max_depth: number(&mut m, "max_depth")?,
            max_nodes: number(&mut m, "max_nodes")?,
            scorer: take(&mut m, "scorer")?,
        };
        if !m.is_empty() {
            return Err(format!(
                "unknown config keys: {:?}",
                m.keys().collect::<Vec<_>>()
            ));
        }
        if !(c.train_start < c.validation_start
            && c.validation_start < c.validation_end
            && c.validation_end <= c.evaluation_start
            && c.evaluation_start < c.evaluation_end)
        {
            return Err("invalid chronological split boundaries".into());
        }
        if c.interval <= 0
            || c.generated > 1_000_000
            || c.batch_size == 0
            || c.batch_size > 4096
            || c.memory_bytes < 1024 * 1024
            || c.top_k == 0
            || c.top_k > 100
            || !(1..=12).contains(&c.blocks)
            || !(2..=64).contains(&c.max_depth)
            || !(4..=256).contains(&c.max_nodes)
        {
            return Err("invalid resource/generation limits".into());
        }
        if c.windows.is_empty()
            || c.windows.len() > 64
            || c.windows.iter().any(|w| !(2..=10000).contains(w))
        {
            return Err("windows must contain 1..64 integers in 2..10000".into());
        }
        if c.quantiles.is_empty()
            || c.quantiles.len() > 1024
            || c.quantiles
                .iter()
                .any(|q| !q.is_finite() || *q <= 0.0 || *q >= 1.0)
        {
            return Err("quantiles must be finite and strictly in (0,1)".into());
        }
        if !c.min_exposure.is_finite()
            || !c.max_exposure.is_finite()
            || c.min_exposure < 0.0
            || c.max_exposure > 1.0
            || c.min_exposure >= c.max_exposure
            || !c.stability_penalty.is_finite()
            || !c.complexity_penalty.is_finite()
            || c.stability_penalty < 0.0
            || c.complexity_penalty < 0.0
        {
            return Err("invalid fitness parameters".into());
        }
        if c.lags.is_empty()
            || c.lags.iter().any(|k| *k == 0 || *k > 10000)
            || c.templates.is_empty()
            || c.injection_stride == 0
        {
            return Err("invalid structural generation parameters".into());
        }
        if c.scorer != "events" && c.scorer != "scan" {
            return Err("scorer must be events or scan".into());
        }
        Ok(c)
    }
}
