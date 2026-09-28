# Filang 0.2: factorized walk-forward factory

This delivery implements issue #4 under the independent language specification #1.
Limen remains a capability prototype; Terasweep remains a performance prototype.
The design objective is trillion-address research without a trillion-row task queue,
feature matrix, result ledger, or global deduplication set. This is not a claim that
one trillion different numerical programs have been evaluated.

## Commands

```sh
cargo test --locked --offline
cargo build --release --locked --offline
# First prepare the pinned source using the README's prepare_hf.py instructions.
python3 scripts/prepare_walk.py
./target/release/filang walk-inspect --config examples/trillion-plan.cfg
./target/release/filang walk-search --config examples/btc4h-walk.cfg --out runs/my-walk
./target/release/filang walk-evaluate --data data/btc4h/evaluation.csv \
  --selection runs/my-walk/walk.tsv --out runs/my-walk-primary
./target/release/filang walk-evaluate --data data/btc4h/evaluation.csv \
  --selection runs/my-walk/walk.tsv --out runs/my-walk-stress --scenario stress
```

All output directories must be new. `walk-inspect` does not read market data or
score features. An actual trillion-address search is NOT an interactive smoke test.

## Work elimination and bounded state

The generator maps `(seed, page index, slot)` to programs. Each page resets its
bounded grammar pool, permits nested generated subprograms inside that page, and
interns shared expressions. `generation_page_size` changes this versioned domain;
it is not an execution-only parameter. `address_start` supports direct access to an
aligned page without enumerating preceding pages. Tests generate the last page of
a one-trillion-address plan directly. Only that page is generated in the test.

Numerical history is computed once per required node/batch, not separately for
each readout, scenario or outer fold. A read-only source/basis bank is shared across
pages and native workers. Its data identity and full structural node identities
are checked before reuse. Worker numerical payloads and per-fold ranked archives
are bounded; no per-readout records are written by default. Peak process RSS is
measured separately from the numerical-vector budget. Generation metadata is
bounded by page size, not by the campaign address count.

Overlapping outer folds reuse identical historical validation windows. The example
needs 11 distinct windows rather than 32 fold-window requests. Training-prefix
quantiles use a single sorted coordinate map and incremental Fenwick counts per
feature. Coordinate compression may contain later observations, but counts and
order statistics at each as-of depend only on its historical prefix; direct-sort
and future-perturbation tests check this property.

Threshold activation updates cost-independent category counts, return moments and
log growth. Primary/stress costs apply to those statistics without sorting or
scanning the feature again. Summation uses compensated updates; this is a matched
mathematical calculation, not guaranteed bit-identical floating-point reductions.
The direct scanner remains available for differential tests and benchmarks.

ARM NEON and x86 AVX2 intrinsics implement pointwise f64 arithmetic and threshold
packing. Packed intersection/popcount supports behavior comparisons; bit-sliced
counters implement strict-majority votes over up to 31 members. Runtime dispatch
checks hardware features; forced unsupported backends fail. Scalar and SIMD retain
precision, strict comparisons, finite-value checks, division-domain behavior and
tail handling. No FMA or fast-math reassociation is introduced. Stateful rolling
kernels retain their sequential reference order.

Pages may run concurrently with immutable shared inputs and private working state.
Results merge in page order; ranked ties use a 1e-9 fitness resolution and a stable
policy identity. Thread/backend changes do not change the intended search domain.

## Research protocol

**All results are retrospective walk-forward, not a fresh untouched holdout.** The
founding campaign already exposed later BTC outcomes. This procedure is evaluated
chronologically, but its design follows that experience. Do not relabel it as
independent confirmation of newly discovered alpha.

The fixed example has eight outer periods from 2023-01-01 to 2026-09-28, changing
policy every six months except the last partial period. At each start, consider
only the preceding four six-month validation windows. In each historical window,
fit the declared quantile cutoffs using earlier data beginning 2020-07-01; never fit
that window's thresholds using its own or later observations. Refit the selected
quantile at the outer start using all permitted earlier history. Full fold-specific
programs and thresholds are sealed before any outer-result replay.

For each readout, require positive primary-cost returns in at least three of four
windows; at least two trades and 2–98% exposure in every window; and positive
aggregate stress log return. Rank by median stress-window annualized Sharpe minus
0.5 times its population standard deviation, minus 0.25 times the magnitude of a
negative worst window, minus 0.002 times the unique dependency-node count. Individual
window Sharpes are clipped to [-5,5] for selection only. Require positive resulting
fitness. Rank each quantile by the worst fitness among itself and its adjacent
configured quantiles (same direction); an ineligible neighbor rejects the center.
This is an explicit heuristic, not a statistical significance test.

Keep the best readout per feature in bounded top-128 archives. Greedily select up
to five candidates whose absolute Pearson correlation of concatenated historical
binary behavior is at most 0.8. Each history segment uses its separately fitted
cutoff. Packed counts/intersections compute the correlation. This removes strongly
similar and opposite behavior, not every possible economic dependence. Only the
bounded archive is searched for diversity; no globally optimal portfolio is claimed.

Evaluate top-one and strict-majority-vote portfolios for (a) all generated addresses,
(b) the first 51 generated addresses, matching the 51 indicator definitions in the
example, and (c) the indicator bank. This controls one feature-budget dimension, not
all complexity/prior differences. Abstain in cash when no candidate qualifies. Fixed
indicator rules, cash and buy-and-hold bypass the selector as explicit controls.

## Execution and population

The cash-funded long/flat `spot_open_v1` ledger is unchanged. The signal at bar t's
close executes at the following open and earns the next open-to-open return. Primary
costs are 5+5 bps fee/slippage per side; stress is 10+10, using the same sealed
members. These are assumptions, not verified venue costs or attainable-fill claims.
No leverage, impact/capacity, borrowing or interest on cash is modeled.

Each outer period closes its position before switching policies and omits the last
two signals that lack a complete execution interval inside that period. In the
concatenated report those two inter-fold intervals are explicitly flat. Compounded
returns, drawdown, exposure and Sharpe include these gaps rather than silently
compressing time. A separate `buy_hold_continuous` control has no inter-fold
liquidations/gaps. Fold reports and aggregate portfolio CSV ledgers are retained.
Annualized Sharpe remains the naive square-root-of-time estimate; no multiple-test
or serial-correlation correction is claimed.

## Artifacts and evidence

`walk.tsv` and its checksum contain exact fold-specific programs/rules, date ranges,
per-fold history-prefix hashes, generation metadata and research role. `lineage.jsonl`
adds selected generator addresses and quantile values. `selection.json` records
archive counts, selected member counts, maximum behavior overlap and cash fallbacks.
`summary.json` counts actual numerical work, contexts, metrics and SIMD dispatch.
`evaluation.json` and portfolio CSVs retain every outer and aggregate result.

A checksum detects alteration; it is not an authenticated signature or OS-level
information barrier. Future-price and added-fold tests verify earlier selections;
independent NumPy arithmetic and explicit cash/share accounting verify portfolio
signals and metrics. Separate source and evaluation files make access auditable.

```sh
.venv/bin/python scripts/verify_walk.py --data data/btc4h/evaluation.csv \
  --selection runs/my-walk/walk.tsv --report runs/my-walk-primary/evaluation.json
python3 scripts/benchmark_walk.py --out runs/my-walk-benchmark --repeats 3
```

Benchmarks compare the same programs, folds, costs and frozen outputs across direct
scalar, factorized scalar, factorized SIMD and factorized parallel execution. They
include process startup, preparation, selection and artifact writes. Thread/core
use and RSS must accompany speedup claims. These are not benchmarked financial gains.

## Remaining scale work

The address domain is lazy and memory bounded, but genuinely different program
pages still incur work proportional to the visited pages. This delivery does not
implement universal symbolic region scoring, global unique-feature counting,
checkpoint/resume, distributed execution, or a trillion completed evaluations.
Within-page structural uniqueness is exact; global uniqueness is intentionally
reported as unknown instead of allocating an unbounded seen-set. Trillion-scale
throughput still needs measured reductions in distinct program work, not a linear
extrapolation of this campaign or merely more threads. The legacy `search` command
retains its earlier eager generator; use `walk-search` for the new bounded runtime.
