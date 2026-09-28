# Filang

A parametric financial-program language and factorized engine for trillion-scale feature research.

**Status: specification phase. The engine, CLI, and performance claims described in the specification are not implemented or established yet.**

## Founding specification

[Issue #1 — Specification: Filang — a parametric financial-program language and factorized feature factory](https://github.com/mikkokotila/Filang/issues/1) is the authoritative product and architecture specification. It contains the semantic contracts, family evaluators, delivery milestones, acceptance matrix, and evidence requirements.

Implementation issues and pull requests should reference the relevant requirements in #1. Proposed command names and module layouts in that issue describe future interfaces, not commands available in this checkout.

## The idea

Features are typed, causal programs rather than entries in a fixed indicator catalog. Inputs, graph topology, operators, windows, lags, constants, normalization, and readouts are parameters. Opaque feature names retain reconstructible programs and provenance.

The engine compiles and evaluates **families of programs**, sharing numerical dependencies, threshold behaviors, Boolean paths, sufficient statistics, and execution summaries wherever their contracts permit it. A general native path handles supported constructions without a specialized family evaluator.

## Architectural commitments

- **Standalone Rust core.** Limen and Terasweep are references and optional integration targets, not mandatory runtime dependencies.
- **Semantics before optimization.** Availability, timelines, validity, initialization, precision, execution assumptions, and metric populations are explicit.
- **Factorization before intrinsics.** Eliminate repeated work before accelerating the work that remains.
- **Auditable research.** Exact evaluation, equivalent-region reuse, proven bounds, approximate objectives, heuristic search, and full replays are distinct outcomes.

A trillion possible addresses is not a trillion different features or a trillion completed backtests. Scale claims must state precisely what was generated, evaluated, shared, skipped, and retained.

## Repository boundary

This repository starts with the specification and bootstrap documentation only. It contains no copied Limen/Terasweep implementation, market datasets, credentials, or generated benchmark artifacts. Source references and the limits of existing evidence are recorded in issue #1.
