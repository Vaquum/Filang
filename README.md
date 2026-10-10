# Filang

A parametric financial-program language and factorized feature-discovery engine.

**Status: runnable 0.10, with complete qualitative geometry and a completed, independently audited three-family research campaign.** Candle bodies and wicks have an exact canonical language, including missing wicks, doji, ties, opening gaps and global relationships. The native direction sweep maps two through ten candles, retains every observed pattern and label, and accounts exactly for the unobserved universe with arbitrary-precision counts. The existing dense full-risk geometry executor retains its checked `u128` strategy multiplicities. Broader factory requirements remain open in issue #1.

**Optional qualitative algebra layer (Phase 1):** [Exact projection, overlap composition, one-candle extension, and oriented multiscale aggregation](docs/QUALITATIVE_GEOMETRY_ALGEBRA.md) are available as the separate `filang::geometry_algebra` Rust module. This is an opt-in layer over native geometry, not a change to the discovery or execution engine.

**Optional structural abstraction layer (Phase 2):** [Caller-selected partial qualitative descriptions, exact refinement classes, and lossless residual reconstruction](docs/QUALITATIVE_GEOMETRY_ABSTRACTION.md) are exposed separately through `filang::geometry_abstraction`. No other Filang subsystem invokes the new layer.

## Current: completed Bitcoin geometry research campaign

The [finite campaign](experiments/geometry_information/CAMPAIGN.md) has completed
its three hypothesis families on the five pinned Vaquum BTCUSDT timeframes.
The result separates information from tested tradeability: additive geometry
improved the frozen directional log-loss criterion at 30m only, while neither
economic round established the specified incremental long/cash edge after costs.
All evaluations remain retrospective because these snapshots and preceding
results had already been inspected.

| Attempt | Audited result | Complete evidence |
|---|---|---|
| R1 | Inconclusive: the original optimizer reached its frozen limit before outer prediction or account replay | [Preserved failure](benchmarks/reports/20261008-geometry-information-r1-failed/README.md) |
| R1a | Information criterion supported at 30m only; all five pooled fixed-policy geometry accounts lost at primary and reduced costs | [Report](benchmarks/reports/20261008-geometry-information-r1a/README.md) |
| R2 | Economic criterion not-supported at all five timeframes; positive returns did not establish incremental geometry or sufficient activity | [Report](benchmarks/reports/20261008-geometry-payoff-r2/README.md) |
| R3 | Fixed 225-column interaction extension not-supported at all five timeframes; no consistent net advantage over freshly fitted additive geometry and cash | [Report](benchmarks/reports/20261008-geometry-interactions-r3/README.md) |

[R3's protocol and replay guide](experiments/geometry_information/ROUND3.md),
[frozen specification](experiments/geometry_information/round3_protocol.json)
and [PR #27](https://github.com/mikkokotila/Filang/pull/27) define the final test.
It retains all 680 fits, 60 policy selections, 820 ledgers, the exact interaction
catalogue, and independently checked integer bootstrap tail decisions. At 15m
and 30m the interaction and additive policies have the same primary net results;
the 120m advantage is almost entirely lower turnover, and the 240m extension
loses relative to its additive baseline. No timeframe passes every frozen gate.

The campaign budget is exhausted. Its complete outcomes and original failure
remain reproducible; no robust live trading edge is claimed. The existing
qualitative language and native sweeps below remain available for explicitly
specified research.

## Earlier: Bitcoin next-bar direction (0.10)

[The experiment protocol and guide](experiments/geometry_direction/README.md)
define a pinned Vaquum BTCUSDT study at 15, 30, 60, 120 and 240 minutes,
crossed with every consecutive window length from two through ten and both
orientation modes. A grouped native sweep writes exact per-pattern direction
counts and chronological events. It uses the shared geometry kernel and avoids
materializing a pattern-by-timeline matrix.

Training, validation selection and frozen test periods are explicit. The study
compares geometry with unconditional and lag-one direction baselines, preserves
missing bars, reports unseen-pattern support, and independently reconstructs
every output. [The measured report](benchmarks/reports/20261008-bitcoin-direction/README.md)
contains outcomes, uncertainty, throughput and verification receipts.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-direction.txt
.venv/bin/python scripts/run_direction_experiment.py \
  --out runs/geometry-direction-v1 --workers 10
```

The runner builds pinned Rust 1.63, downloads immutable checked source snapshots,
maps all 90 configurations, selects on validation, and runs the independent audit.
Use `--stage prepare|map|analyze|verify` to run a stage explicitly. The native
`geometry-direction-sweep` also exposes a strict standalone CLI and sealed resume.

## Earlier: qualitative bar geometry (0.9)

[The complete technical reference](docs/BAR_GEOMETRY.md) defines the atoms,
canonical format, completeness boundary, exact counts, sweep domain, memory
budgets, durable artifacts and independent verification. A pattern preserves the
global order and equality of every low, body bottom, body top and high. Optional
body direction is part of the candle; indicators and volume are not geometry
atoms. Lengths and ratios are outside this ordinal language.

For a fixed lag window, every valid historical decision matches exactly one
complete pattern. Unobserved patterns share an all-false raw mask on that causal
input. The engine retains their exact count, then applies temporal qualifiers,
interns identical truth/validity masks, certifies Boolean products and scores the
remaining regions. A frozen winner always names explicit patterns; it is encoded
and evaluated afresh on another dataset.

```sh
cargo build --release --locked --offline
./target/release/filang geometry-count --bars 2 --mode oriented
./target/release/filang geometry-inspect --config examples/geometry-trillion.cfg

# Requires the prepared discovery CSV; scoring is 2024, with causal warm-up.
./target/release/filang geometry-sweep \
  --config examples/geometry-trillion.cfg --out runs/geometry --workers 10
python3 scripts/verify_geometry.py --run runs/geometry

# Resume after interruption; worker count may change.
./target/release/filang geometry-sweep \
  --config examples/geometry-trillion.cfg --out runs/geometry \
  --resume true --workers 4
```

`geometry-example` creates a custom config, `geometry-prepare` commits only the
predicate banks, and `geometry-evaluate` replays a checksummed frozen selection
through the separate chronological scorer. `--capture true` retains every result
region for exhaustive independent metric replay; summary output verifies all
bank memberships, domain coverage and retained task winners. The verifier reports
its scope explicitly. `scripts/benchmark_geometry.py` measures matched scalar,
certificate, native and parallel runs with verification outside the timer.

The `smoke` example has 333,193,824 logical addresses. The `trillion` example uses
two three-bar lag windows, three qualifiers and three two-slot rules. These are
complete searches of their declared domains; physical work depends on the data
and may still be substantial. Bank and tree budgets fail explicitly instead of
pruning the domain. Native execution has no third-party dependencies and retains
the Rust 1.63 minimum.

[The measured geometry report](benchmarks/reports/20261008-bar-geometry/README.md)
records exhaustive captured-control verification, full-year domain coverage,
matched timings, worker scaling, peak memory and frozen replay.

## Earlier: dense atom pairs (0.8)

`dense-sweep` independently varies both numerical neighborhoods, shares exact
truth/validity signatures across atom coordinates, and evaluates certified products
through the same full-risk engine. Bounded banks, checked u128 coverage, restartable
task commits and worker-count-independent reduction are explicit. See
[the contracts and commands](docs/DENSE_ATOM_PAIRS.md). Large summary output is
not mislabeled as exhaustive independent replay of every metric record.

## Earlier: joint indicator and rule sweeps (0.7)

`strategy-sweep` jointly varies predicate alternatives, their feature/threshold/
temporal parameters, and compound AND/OR/NOT/temporal rules. It uses packed validity
and truth planes, shared numerical/predicate plans, Boolean cofactors, exact result
boxes and the existing full-risk execution engine. No single-feature shortlist is
required. See [the language, commands and limitations](docs/JOINT_STRATEGY_SWEEP.md).

## Earlier: ten-family atom micro-sweeps (0.6)

Ten declared known-feature families now use the same fine-grid engine, with signed
result-region support, an independent cohort parity gate and full response surfaces.
See [the exact cohort, configurations and experiment commands](docs/TEN_INDICATOR_SWEEP.md).
The selection is a practical mainstream cohort, not a measured global usage ranking.

## Earlier: fine atom-neighborhood sweeps (0.5)

The new `micro-sweep` keeps the exact SMA anchor, varies ordinary source/mixture/
subtraction constants on explicit rational grids, shares input/mean dependencies,
and returns exact parameter regions rather than independently replaying every
constant. It uses the common paged executor and full-risk state, with independent
reference checks and a separately sealed later replay. See
[the family, research protocol and commands](docs/ATOM_MICRO_SWEEP.md).

## Earlier: paged full-risk state (0.4)

Known-indicator parity and parameter neighborhoods now use the shared page executor.
It accepts the same ordinary programs as the paged open generator, retains full
backtest state across program changes, shares event plans across cost scenarios,
and falls back to chronological replay when changes are dense. All ten metrics
remain intact. See [the state contract and commands](docs/REUSABLE_STATE.md).

[The measured shared-state report](benchmarks/reports/20260929-reusable-state/README.md)
separates distinct-period-program gains, threshold-family gains, weak-reuse fallback,
full reference parity, and bounded output.

The earlier commands and benchmark reports below are retained as versioned evidence;
no historical winning result or external reference kernel is embedded in this path.

## Earlier delivery: factorized walk-forward discovery

The 0.2 native path adds paged generation, a shared numerical basis across workers,
reused fold and cost statistics, prefix-quantile factorization, NEON/AVX2 kernels,
packed behavior diversity, and sealed top-one/voting policies. It is designed to
avoid allocations and per-readout logging proportional to a trillion-address domain.
An address-space plan is not a completed trillion-feature backtest.

See [the runnable walk-forward/performance contract](docs/WALKFORWARD.md).
`examples/btc4h-walk.cfg` runs the measured-scale campaign;
`examples/trillion-plan.cfg` is for **planning**, not a completed scale result.
[The 0.2 walk-forward and performance report](benchmarks/reports/20260928-walkforward/README.md)
records all portfolio outcomes, matched execution ablations, and bounded-memory probes.
The diverse generated policy was positive under both cost scenarios in this retrospective
study, but remained far behind the strongest fixed trend controls. This is not fresh
untouched evidence or a claim of a robust generated edge.
The original 0.1 campaign below is retained unchanged as historical evidence.

## Indicator workflow: known-indicator parity first

[The measured parity report](benchmarks/reports/20260928-anchor-parity/README.md)
records the passing anchor checks, complete-result comparisons, and matched
single-threaded performance: 120,832 metric sets in a three-repeat experiment and
1,050,704 metric sets in a separate large pair. Coverage is explicitly eight
reference APIs, not all indicators or one million numerical features.

The next research step is not novel-topology generation. Filang reconstructs
established indicator definitions using ordinary atoms, verifies values, signals,
trade events, complete equity paths and PnL/risk against pinned TA-Lib plus
independent cash/share accounting, then unlocks bounded period/threshold
neighborhoods. See [the parity and benchmark contract](docs/ANCHOR_PARITY.md).

```sh
cargo build --release --locked --offline
.venv/bin/python -m pip install -r requirements-parity.txt
./target/release/filang anchor-parity --data data/btc4h/evaluation.csv --out runs/parity
.venv/bin/python scripts/anchor_reference.py --data data/btc4h/evaluation.csv \
  --manifest runs/parity/manifest.json --native runs/parity --out runs/parity-ref --gate
./target/release/filang anchor-sweep --data data/btc4h/evaluation.csv \
  --gate runs/parity/gate.txt --radius 4 --thresholds 129 --out runs/neighbors
```

This is an explicitly listed first coverage cohort, not all TA-Lib functions or
proof that every indicator is profitable. The compiler has no indicator-name
shortcuts: grouped statistics, coefficient-lane SIMD, tiled atom execution and
full-risk threshold sweeps also accept anonymous atom programs. Stored market
outcomes are regression evidence, never answers embedded in the native engine.

## Run without market data

Rust 1.63 or later. The native package has **no third-party dependencies**; the committed Cargo.lock builds offline.

```sh
cargo test --locked --offline
cargo build --release --locked --offline
./target/release/filang demo --out runs/demo
```

The synthetic demo generates data, searches programs, freezes candidates, and replays a separate period. Synthetic performance is a functionality test, not financial evidence. Use a fresh output directory for each run.

## Run the Binance spot campaign

The data adapter is optional Python/Polars; the engine does not import Python, Limen or Terasweep. The source is an immutable revision of Vaquum's BTCUSDT 4-hour spot snapshot, with a required SHA-256.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-data.txt
.venv/bin/python scripts/prepare_hf.py
cargo build --release --locked --offline

# This command can only select on the discovery CSV, ending before 2025.
./target/release/filang search --config examples/btc4h.cfg

# Read the validation results and inspect the frozen programs before this step.
./target/release/filang evaluate \
  --data data/btc4h/evaluation.csv \
  --selection runs/btc4h/frozen.tsv \
  --out runs/btc4h-evaluation

# Same frozen programs; do not select again using the final-period results.
./target/release/filang evaluate \
  --data data/btc4h/evaluation.csv \
  --selection runs/btc4h/frozen.tsv \
  --out runs/btc4h-stress --fee-bps 10 --slip-bps 10
```

For another discovery run, use `search --config examples/btc4h.cfg --out runs/another-run` and point evaluation at that run's frozen file. Merely rerunning on the same final period does not create new out-of-sample evidence.

## First measured result

[The full frozen campaign report](benchmarks/reports/20260928-btc4h/README.md) records the first real-data run. All five generated selections lost money in the later period; the tuned SMA-distance comparator was positive at primary costs but negative under doubled costs. The implementation is runnable; a robust generated trading edge has **not** been established. All frozen candidates and failed outcomes are retained.

## What the factory searches

Inputs, source combinations, rolling windows, lags, smoothing, arithmetic interactions, normalization and expression topology vary through parameters. Eight composition motifs can reuse unfamiliar subprograms. For example, a feature can combine normalized trend distance with changing activity and then smooth or difference their interaction. Programs get opaque, reconstructible SHA-256 identities rather than becoming separate source files.

The example searches 4,096 generated feature programs alongside 51 tunable indicator definitions, six fixed indicator rules and cash/buy-and-hold. Thresholds and direction are readouts, not extra numerical features. The data split is training 2021–2023, selection-validation 2024, and final evaluation 2025–September 2026. Costs and execution are identical for generated and established-indicator comparisons.

See [the execution, language and selection contract](docs/CONTRACT.md) before interpreting any return. Next-open execution is idealized, fees are assumptions, Sharpe is not serial-correlation adjusted, and the larger generated search receives a larger selection budget. This is not a trading recommendation or proof of future alpha.

## Artifacts and inspection

`runs/<run>/programs.tsv` retains formulas. `discovery.jsonl` records all scored readouts. `selected_validation.json` reports the frozen selections on validation. `frozen.tsv` plus its checksum can be replayed without rerunning search. `summary.json` distinguishes numerical programs, readouts, actual numerical work and full replays. Final evaluation writes `evaluation.json` and a trace CSV for each frozen program.

```sh
./target/release/filang inspect --config examples/btc4h.cfg
make test
```

Optional independent checks:

```sh
# NumPy is required only by this verification script.
.venv/bin/python -m pip install -r requirements-verify.txt
.venv/bin/python scripts/verify_reference.py --data data/btc4h/evaluation.csv \
  --report runs/btc4h-evaluation/evaluation.json --trace-dir runs/btc4h-evaluation
python3 scripts/compare_discovery.py runs/one-matched-run runs/another-matched-run
python3 scripts/benchmark.py --out runs/benchmark --repeats 3
```

## Reference prototypes, not blueprints

**Limen is the capability prototype:** understand what a financial construction computes and why it is useful, then independently generalize and redesign its computation at scale.

**Terasweep is the performance prototype:** a starting point for eliminating repeated work, not a prescribed kernel stack or performance ceiling. Filang combines shared numerical DAGs with parameter-event scoring in this slice; broader algorithms remain open.

Neither prototype is a runtime dependency or compatibility obligation. Correctness is defined here and checked with independent reference calculations. This repository contains no copied prototype implementation or market dataset.

## Joint strategy sweep evidence

The joint rule layer and its first complete **8.748-trillion-address** parameter
campaign are documented in [the measured report](benchmarks/reports/20261005-joint-strategies/README.md).
This is exact result-box coverage of a declared two-condition family, not trillions
of independent indicators or a general arbitrary trillion-program throughput claim.
All combined positions and full backtest metrics were independently verified.
[Rule syntax, contracts and commands](docs/JOINT_STRATEGY_SWEEP.md) include a
summary-output mode that avoids retaining the large result-box file.
