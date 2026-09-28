# Filang

A parametric financial-program language and factorized feature-discovery engine.

**Status: runnable 0.1 research vertical slice.** It generates unfamiliar typed expressions, shares their numerical dependencies, searches threshold readouts, freezes selected programs and evaluates them on a later period. The broader factory specification and trillion-feature scale target remain open in [issue #1](https://github.com/mikkokotila/Filang/issues/1). Delivery of this slice is tracked in [issue #2](https://github.com/mikkokotila/Filang/issues/2).

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
