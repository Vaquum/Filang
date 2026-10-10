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

pub mod micro;
pub mod regions;

pub mod cohort;

pub mod cohort_parity;

pub mod rule_kernels;
pub mod rules;

pub mod joint;

pub mod joint_run;

pub mod dense_cells;

pub mod dense_bank;

pub mod dense_tree;

pub mod dense_io;

pub mod dense_run;

pub mod geometry;

pub mod geometry_run;

pub mod geometry_cli;

pub mod direction;

pub mod direction_cli;

pub mod geometry_keys;

pub mod geometry_keys_cli;

pub mod geometry_algebra;

pub mod geometry_abstraction;
