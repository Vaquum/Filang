use crate::{backtest::Costs, config::Config, data::date, kernels::Backend, Result};
use std::{collections::BTreeMap, fs};
#[derive(Clone, Debug)]
pub struct WalkConfig {
    pub base: Config,
    pub edges: Vec<i64>,
    pub outer: Vec<i64>,
    pub inner: usize,
    pub addresses: u64,
    pub address_start: u64,
    pub page_size: usize,
    pub threads: usize,
    pub archive: usize,
    pub min_positive: usize,
    pub min_trades: usize,
    pub max_corr: f64,
    pub neighbor_radius: usize,
    pub stress: Costs,
    pub backend: Backend,
    pub prepared: bool,
    pub prefix_reuse: bool,
    pub scenario_reuse: bool,
    pub window_reuse: bool,
}
impl WalkConfig {
    pub fn load(path: &str) -> Result<Self> {
        Self::parse(&fs::read_to_string(path).map_err(|e| e.to_string())?)
    }
    pub fn parse(text: &str) -> Result<Self> {
        let names = [
            "walk_edges",
            "walk_outer",
            "walk_inner",
            "feature_addresses",
            "address_start",
            "generation_page_size",
            "threads",
            "archive_size",
            "min_positive_windows",
            "min_window_trades",
            "max_abs_correlation",
            "neighbor_radius",
            "stress_fee_bps",
            "stress_slip_bps",
            "kernel_backend",
            "reuse_basis",
            "reuse_prefix_quantiles",
            "reuse_cost_scenarios",
            "reuse_windows",
        ];
        let mut extra = BTreeMap::new();
        let mut base = String::new();
        for line in text.lines() {
            let t = line.trim();
            if t.is_empty() || t.starts_with('#') {
                continue;
            }
            let (k, v) = t.split_once('=').ok_or("expected key=value")?;
            if names.contains(&k.trim()) {
                if extra
                    .insert(k.trim().to_string(), v.trim().to_string())
                    .is_some()
                {
                    return Err(format!("duplicate {k}"));
                }
            } else {
                base.push_str(line);
                base.push('\n');
            }
        }
        fn take(m: &mut BTreeMap<String, String>, key: &str, default: &str) -> String {
            m.remove(key).unwrap_or_else(|| default.into())
        }
        fn number<T: std::str::FromStr>(
            m: &mut BTreeMap<String, String>,
            key: &str,
            default: &str,
        ) -> Result<T> {
            take(m, key, default)
                .parse()
                .map_err(|_| format!("bad {key}"))
        }
        fn dates(s: String) -> Result<Vec<i64>> {
            s.split(',').map(|v| date(v.trim())).collect()
        }
        let c = Self {
            base: Config::parse(&base)?,
            edges: dates(take(&mut extra, "walk_edges", ""))?,
            outer: dates(take(&mut extra, "walk_outer", ""))?,
            inner: number(&mut extra, "walk_inner", "4")?,
            addresses: number(&mut extra, "feature_addresses", "4096")?,
            address_start: number(&mut extra, "address_start", "0")?,
            page_size: number(&mut extra, "generation_page_size", "256")?,
            threads: number(&mut extra, "threads", "1")?,
            archive: number(&mut extra, "archive_size", "128")?,
            min_positive: number(&mut extra, "min_positive_windows", "3")?,
            min_trades: number(&mut extra, "min_window_trades", "2")?,
            max_corr: number(&mut extra, "max_abs_correlation", "0.8")?,
            neighbor_radius: number(&mut extra, "neighbor_radius", "1")?,
            stress: Costs {
                fee_bps: number(&mut extra, "stress_fee_bps", "10")?,
                slip_bps: number(&mut extra, "stress_slip_bps", "10")?,
            }
            .validate()?,
            backend: Backend::resolve(&take(&mut extra, "kernel_backend", "auto"))?,
            prepared: number(&mut extra, "reuse_basis", "true")?,
            prefix_reuse: number(&mut extra, "reuse_prefix_quantiles", "true")?,
            scenario_reuse: number(&mut extra, "reuse_cost_scenarios", "true")?,
            window_reuse: number(&mut extra, "reuse_windows", "true")?,
        };
        if c.addresses == 0
            || c.address_start.checked_add(c.addresses).is_none()
            || !(1..=4096).contains(&c.page_size)
            || c.address_start % c.page_size as u64 != 0
            || !(1..=16).contains(&c.threads)
            || c.archive < c.base.top_k
            || c.archive > 1024
            || c.base.top_k > 31
            || !(1..=12).contains(&c.inner)
            || c.min_positive > c.inner
            || c.neighbor_radius > 2
            || !c.max_corr.is_finite()
            || c.max_corr < 0.0
            || c.max_corr > 1.0
            || c.outer.len() < 2
            || c.outer.len() > 65
            || c.edges.len() < c.inner + 1
            || c.edges.len() > 128
        {
            return Err("invalid walk-forward/resource parameters".into());
        }
        if c.edges.windows(2).any(|w| w[0] >= w[1])
            || c.outer.windows(2).any(|w| w[0] >= w[1])
            || c.edges[0] <= c.base.train_start
            || *c.edges.last().unwrap() != c.base.validation_end
            || c.outer[c.outer.len() - 2] != c.base.validation_end
            || *c.outer.last().unwrap() != c.base.evaluation_end
        {
            return Err("inconsistent walk-forward chronology".into());
        }
        for t in &c.outer[..c.outer.len() - 1] {
            if c.edges
                .iter()
                .position(|x| x == t)
                .map_or(true, |i| i < c.inner)
            {
                return Err("outer start must end the requested preceding inner windows".into());
            }
        }
        if c.base.quantiles.windows(2).any(|q| q[0] >= q[1]) {
            return Err("walk quantiles must be strictly increasing".into());
        }
        if c.stress.fee_bps < c.base.costs.fee_bps || c.stress.slip_bps < c.base.costs.slip_bps {
            return Err("stress costs must not be lower than primary".into());
        }
        c.addresses
            .checked_mul((c.edges.len() * c.base.quantiles.len() * 4) as u64)
            .ok_or("requested counters would overflow")?;
        Ok(c)
    }
    pub fn page_count(&self) -> u64 {
        (self.addresses - 1) / self.page_size as u64 + 1
    }
}
