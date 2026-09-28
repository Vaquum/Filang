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
