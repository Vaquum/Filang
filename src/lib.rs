//! Filang's first independently specified, dependency-free research engine.
pub mod backtest;
pub mod config;
pub mod data;
pub mod engine;
pub mod hash;
pub mod lang;
pub mod report;
pub mod search;
pub type Result<T> = std::result::Result<T, String>;

pub mod kernels;
pub mod packed;
pub mod quantiles;
pub mod walk;
pub mod walk_config;
pub mod walk_evaluate;

pub mod anchor_run;
pub mod anchors;
pub mod family;
pub mod family_kernels;

pub mod paged;

pub mod paged_anchors;

pub mod program_run;
