# Anchor parity before neighborhood research

This delivery follows issue #6. The active research path starts from known
indicator constructions, not random new topologies. A feature that has a positive
historical example is not thereby universally profitable. The first coverage
cohort is deliberately explicit and remains smaller than TA-Lib's full catalog.

## Coverage

The first cohort contains the six recorded fixed indicator rules, cash and
buy-and-hold, plus ten external-reference constructions using eight TA-Lib APIs:
SMA, EMA (also paired as an EMA crossover), RSI, BBANDS, MACD, ROC, WILLR
(re-expressed as channel position), and ATR. Every construction is expanded into
ordinary Filang atoms. No opcode calls TA-Lib or dispatches on an indicator label.
Unsupported reference functions are not claimed covered. The complete installed
TA-Lib function inventory is retained with the verification evidence.

Native legacy profiles reproduce the existing recorded 0.2 formulas and results.
External profiles deliberately encode reference initialization and arithmetic:

* `skip n x` invalidates exactly the first n source rows. It is used to express
  MACD's aligned fast-EMA seed with ordinary EMA nodes. It is not dropped data.
* `div0 x y` returns zero for finite operands when |y| <= 1e-12; otherwise it
  divides. It is explicit in the RSI reference macro. Normal `div` is unchanged.
* `mean_sum` and `std_sum` use add/output/subtract raw rolling totals; standard
  deviation floors raw variance below 1e-14. They are separate numerical
  contracts from the unchanged Welford `mean` and `std` atoms. Raw moments can
  be less stable; the compiler does not silently substitute them for Welford.

All profiles retain the source timeline. Pinned finite OHLCV data and the tested
fixtures define external parity scope; different TA-Lib global compatibility or
unstable-period settings, invalid-source propagation and extreme numerical
regimes are not universally certified by the real-data comparison. Threshold
masks are required to match exactly; a numerical tolerance never excuses a
changed trading decision.

## Shared family execution

`family::prepare` recognizes the operator graph, not the anchor name. A Mean/Std
pair with the same input, window and numerical profile advances one shared state
machine. Recurrence banks load a common input and advance independent period/
coefficient lanes using NEON or AVX2 while keeping time order within each lane.
There is no FMA, reassociation or reduced precision. Different initialization
nodes are different graph dependencies and cannot share incompatible state.

`family::Program` compiles terminal pointwise operations into 256-row tiles,
using existing SIMD arithmetic, and can emit packed predicates without full
intermediate arrays. Capturing a numerical root is required by threshold-order
sweeps, not by every possible consumer. Anonymous, nested atom-program and actual open-generator corpus tests
exercise this compiler without consulting the anchor catalog.

Price log-prefixes and category terms are prepared once per market context and
reused across all feature programs and thresholds.

Full threshold-family scoring uses local position activations, an associative
path-summary tree for maximum drawdown, and interval-component merges for mean
completed-trade return. It supplies the same ten metrics as chronological replay,
not only a cheaper moment score. Requested thresholds are real parameters, not
post-hoc aliases of recorded winning results. Exact packed-behavior comparison
allows complete metric reuse in bounded batches; a hash alone is never proof.

The generic compiler and `Market::full_thresholds` are ordinary native library
APIs available to arbitrary atom programs and the open-sweep runtime. The anchor
runner is a small finite authoring/benchmark front end, not a substitute for a
trillion-address enumerator. Its default batch is 32, scratch tiles are fixed,
and its cache is resource-budgeted. The prior paged open-sweep remains available;
this delivery does not pretend that its newly finite neighborhood front end has
already executed a trillion candidates.

## Parity and gating

`anchor-parity` emits the expanded catalog, numerical outputs, chronological
trade/equity traces and all metric results on the same pinned data and fold-gap
contract as the stored fixed controls. `scripts/anchor_reference.py --gate`
checks every value's validity, every requested threshold mask, each trade event,
net/gross returns, every equity point and completed-trade return against separate
TA-Lib formulas and cash/share accounting. It also compares the legacy fixed
control results against the previously committed primary/stress reports.

The initial tolerances are feature `atol=1e-8, rtol=1e-9`, metric
`atol=1e-7, rtol=1e-9`, chronological trace `atol=1e-8, rtol=1e-9`.
Validity, masks, events, trade counts and sample counts must agree exactly.
These are declared numerical tolerances, not a claim of bit identity to TA-Lib.
The first Bollinger comparison failed the feature-value criterion despite matching
PnL; the arithmetic profile was made explicit rather than weakening that criterion.

A passing gate binds the native executable, expanded anchor catalog, data digest,
manifest, metrics and independent verification. `anchor-sweep` rejects missing,
altered or incompatible gates. Checksums detect accidental alteration; this is
not an authenticated security barrier against a user who rewrites evidence.

## Run

```sh
cargo test --locked --offline
cargo build --release --locked --offline
.venv/bin/python -m pip install -r requirements-parity.txt
./target/release/filang anchor-parity --data data/btc4h/evaluation.csv --out runs/parity
.venv/bin/python scripts/anchor_reference.py --data data/btc4h/evaluation.csv \
  --manifest runs/parity/manifest.json --native runs/parity \
  --out runs/parity-reference --gate
./target/release/filang anchor-sweep --data data/btc4h/evaluation.csv \
  --gate runs/parity/gate.txt --radius 4 --thresholds 129 --out runs/neighbors
```

Every output directory must be new. The source data preparation is unchanged.
A changed native executable requires a fresh parity run. The neighborhood contains
unchanged anchors and declared period/threshold variations, preserving parent and
expanded program identity; no mutation invents a new topology. All outcomes are
retained in compact binary metrics plus their manifest, with no winning candidate
promoted using this already-observed history.

## Benchmark contract

Compare identical manifests/data, numerical profiles, costs, thresholds, all ten
metrics and output layout. Include process startup, data reading, feature work,
full backtests and result writes. Report the TA-Lib+NumPy application baseline
separately from independent native chronological replay and the shared family
backend. The Python reference caches reused TA-Lib function calls; it does not
recompute an indicator for every threshold. A combined speedup is not a claim
that each TA-Lib indicator kernel is individually slower.

Large-run verification checks every metric and every mask when numerical outputs
are captured. Repeated timing runs can disable capture symmetrically after this
verification; output differences and verification time are never smuggled into a
speedup denominator. No GPU, extra threads, shortened history or cheaper risk
metric is used to manufacture the family speedup. A logical threshold grid is
not counted as that many distinct numerical features.
