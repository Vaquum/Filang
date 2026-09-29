# Filang 0.4: reusable state in one bounded page executor

Issue #8 follows the known-indicator parity-first direction in #1. This delivery
changes physical execution, not the numerical indicators, input history, trading
rules, fee assumptions, or requested metrics. It performs no winner selection.

## One evaluation interface

`paged::Executor` accepts a stream of `Page { graph, requests }` through
`PageSource`. `Request` contains an address, graph root and explicit readouts;
there is no indicator-name field. Known-indicator catalog/neighborhood pages,
period domains, expression streams and the actual `walk::page` open generator
all feed this executor. Anonymous open-generator coverage runs on synthetic data
in tests. Existing `walk-search` selection-policy orchestration is retained;
this delivery does not silently change its statistical objective or claim every
legacy command was replaced. `program-sweep` is the shared paged evaluation entry.

`anchor-parity` and `anchor-sweep` now default to this same runtime. Their finite
old direct/shared/family modes remain explicit regression oracles. The paged
anchor source reproduces the preceding finite catalog and candidate ordering,
including clamped periods, without holding a growing global deduplication set.

## Reversible full-risk state

`ReusableExecution` owns immutable market contexts and one packed position path.
The context includes the exact row range and each fee/slippage scenario. A changed
dataset, timeline or scenario set constructs a new context; cross-context state
reuse is not permitted through this API.

An XOR comparison detects exact changed positions. Identical words authorize reuse
without a hash-only inference. Position changes update their preceding/current/
following return classifications. Dirty leaves and their common ancestors are
collected once, then reused by all cost-specific trees. Adjacent programs need not
have identical numerical outputs or positions to benefit from this path.

Each tree node carries net-return moments, ordered log-equity extrema/drawdown,
activity and entry counts, gross growth and active-run return summaries. If two
active run fragments with net returns a and b touch, their compounded return is
`a + b + a*b`. The merge adds `a.tail * b.head` to the sum of run net returns.
Prefix/suffix run summaries make both trade joins and splits work without an
insertion-only union-find or per-candidate equity history. At the root, the sum
of complete run returns and exact entry count yield mean completed-trade return.
This is a real-arithmetic identity with floating-point tolerances, not a promise
of bit-identical regrouping versus a chronological reference.

All ten original metrics remain requested. No drawdown proxy or partial score
replaces full risk. Counts and masks are exact; feature and metric tolerances
remain those in ANCHOR_PARITY.md. Nonfinite summaries fail explicitly.

## Plans, dense fallback and costs

Small-readout pages use coordinate-major traversal with alternating program
traversal direction. This keeps nearby parameter programs near each other and
restores original request/readout/scenario order before output. Numerical history
is still computed where required; comparing packed positions is not free.

Large-readout pages sort a feature once and advance its exact threshold events.
That one event plan drives every scenario, rather than sorting and traversing
again per fee pair. Ties and both strict directions retain their original rules.

`auto` chooses a small-readout cross-program plan or a per-series event plan. Its
reversible state uses sparse dirty updates where appropriate. Dense changes use
one chronological mask traversal shared across scenarios instead of constructing
expensive tree state; a later sparse transition rebuilds tree state before using
it. The default density heuristic is explicit and data-value independent, not a
claim of optimal scheduling. `delta`, `rebuild`, `events`, `legacy` and `replay`
allow matched ablations. Forced delta can be slower on dissimilar programs.

Interval joins/splits count incremental operations; dense replay has separate
counters instead of pretending to execute each interval edit. Flips, decoded
changes, bitmap words, sparse updates, full replays, dirty leaves, tree merges,
scenario-specific work, all-off/all-on paths and change-density histograms are
reported. The histogram bins are zero, (0,0.1%], (0.1%,1%], (1%,5%], (5%,10%],
(10%,25%], (25%,50%], and (50%,100%]. Scoring time includes event/mask discovery;
its detection sub-timer must not be added to scoring time again.

## Bounded state and results

Generation and numerical/result pages are bounded, and execution state survives
page boundaries. The numerical/result budget and execution-state payload are
separate accounting categories; neither claims to cap total process RSS. Oversized
pages split deterministically; one request that cannot fit fails rather than
silently losing readouts. Fixed state still scales with history length and cost
scenario count. Program generation/dependency metadata, input data and interpreter
or process overhead remain visible in measured RSS.

`--output all` streams all ten metrics per requested scenario in canonical order.
`--output summary` computes and hashes those same records, discarding each instead
of retaining it. SHA-256 is incremental: no complete result-file reread or buffer
is needed. Summary mode is not sublinear evaluation or proof-based pruning. A
compact domain contract replaces per-program manifests for open/period sources;
optional proof capture writes numerical outputs and program/readout definitions.
Full-output benchmarks use identical output contracts for all compared paths.

Known sources preserve the existing numerical profiles and no new TA-Lib API is
claimed covered by this delivery. The parity gate binds code, data, catalog and
independent evidence. Source config/expression file digests and domain parameters
are retained. Checksums are audit aids, not authenticated security boundaries.

## Commands

```sh
cargo test --locked --offline
cargo build --release --locked --offline
./target/release/filang anchor-parity --data data/btc4h/evaluation.csv --out runs/parity-v04
.venv/bin/python scripts/anchor_reference.py --data data/btc4h/evaluation.csv \
  --manifest runs/parity-v04/manifest.json --native runs/parity-v04 \
  --out runs/parity-v04-reference --gate

./target/release/filang program-sweep --data data/btc4h/evaluation.csv \
  --gate runs/parity-v04/gate.txt --source periods --kind sma --profile talib \
  --period-start 2 --period-end 2048 --rules gt:0 \
  --start 2023-01-01 --end 2026-09-28 \
  --gaps 2023-07-01,2024-01-01,2024-07-01,2025-01-01,2025-07-01,2026-01-01,2026-07-01 \
  --scorer auto --page-size 32 --output all --out runs/period-regression

.venv/bin/python scripts/benchmark_state.py --gate runs/parity-v04/gate.txt \
  --out runs/state-benchmark --repeats 3 --period-end 2048
```

Use fresh output directories. `program-sweep --capture true` additionally emits
`features.bin` and `requests.jsonl`. For a captured period-source run:

```sh
.venv/bin/python scripts/verify_state_programs.py --data data/btc4h/evaluation.csv \
  --run runs/period-regression-captured --out runs/period-regression-verification.json
```

The generic sources also include `--source expressions --expressions FILE` (one
ordinary prefix expression per line) and `--source open --generator-config CFG
--addresses N --address-start A` (page-aligned random access). These are evaluation
interfaces, not a recommendation to resume novel-feature financial discovery.
`--diagnostic true` permits explicitly labeled synthetic/systems tests without a
market parity gate; it does not imply a passing external reference certificate.

## Evidence standard and limits

Benchmarks separately increase threshold count, genuinely different numerical
program count, and behavior dissimilarity. Record all ten metrics, exact counts,
detection/update/rebuild work, phase and whole-process time, output and RSS.
Retain negative performance findings. Parity tests include both directions/ties,
invalids, tails, arbitrary splits/joins, page boundaries, future perturbation and
actual open-generator programs near a trillion-address boundary. That last test
executes only its bounded page; it is not a trillion-feature measurement.

A trillion-sized domain still contains physical generation, numerical, comparison
and output work. No new compression theorem, universal near-zero marginal cost,
global independent-feature count or completed trillion sweep is claimed here.
The important new capability is reusing full execution state across genuinely
different programs in the same runtime used to verify established constructions.
