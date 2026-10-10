# Fixed qualitative-abstraction information study (Phase 3)

This is the **first empirical layer** over Filang's exact qualitative
representation (Phase 1) and its caller-chosen structural abstractions
(Phase 2). All feature generation calls the real `geometry_abstraction::Schema`
API. The existing search, backtest, dense-sweep, direction, geometry, and
accounting engines are untouched.

- [Original R0 frozen protocol](protocol.json), committed before any fit:
  `c6e1add2995e30eb7499e09f03ab6265a5755662`.
- [R0 preflight failure](PRECHECK_FAILURE.json): source-path correction, followed
  by detection of a transcription error in the 120-minute CSV checksum.
  **No real-data label was fitted or scored** under the defective protocol.
- [R0a checksum-only amended frozen protocol](protocol_r0a.json), committed
  before fitting at `c2eecc24103b049866de2881ca8141ac194a0927`,
  SHA-256 `3f84a6331f1f6c07f3924dfefa9ede739efaa597c98448e382accc45cb2e56ea`.
- [Audited empirical result and complete scientific interpretation](../../benchmarks/reports/20261010-qualitative-information-r0a/README.md).

## Program boundaries

| Component | Purpose | Inputs inspected |
|---|---|---|
| `src/bin/geometry_abstraction_features.rs` | Native, entirely causal two-candle feature export via Phase 2 schema | Current candle and immediately previous candle only |
| `run.py` | Hash-check every source, fit fixed count models, score chronological held-out labels, retain all predictions, run bootstrap and placebos | Frozen protocol, source prices, native feature stream |
| `verify.py` | Independent source reconstruction, every feature, label, prediction, statistic, placebo and frozen decision | Source prices, protocol and sealed outputs; **never imports run.py** |
| `test_synthetic.py` | Independent synthetic native-signature oracle, append invariance, gaps, invalid inputs and final unlabelled candle | Generated synthetic OHLC only |
| `collect.py` | Check full-artifact hashes and publish original producer/audit/result bytes plus SHA-bound compact manifest | Successfully audited local run |

All input source digests and row counts, the frozen target and forecast
definition, baseline and alternative estimators, `alpha=100`, sample and
bootstrap windows, 16 null rotations, and a single 30-minute primary decision
were frozen **before** the outcome run.

The time-shift null is a *diagnostic alignment placebo*. Synthetic OHLC is a
*software correctness control*. Neither is a realistic validated generator
for market prices or a substitute for prospective evidence.

## Reproduce

Requires Rust 1.63, Python 3.13 and exact previously verified source CSVs in
the connected `Filang-direction` worktree. Sources are intentionally not
committed. Use a **new** run directory; both producer and native exporter
refuse to overwrite evidence.

~~~sh
cargo +1.63.0 build --release --locked --offline --bin geometry_abstraction_features

python3 experiments/qualitative_information/test_synthetic.py \
  --binary target/release/geometry_abstraction_features

python3 experiments/qualitative_information/run.py \
  --protocol experiments/qualitative_information/protocol_r0a.json \
  --data-dir ../Filang-direction/data/geometry-direction \
  --binary target/release/geometry_abstraction_features \
  --out runs/qinf-r0a-reproduction

python3 experiments/qualitative_information/verify.py \
  --protocol experiments/qualitative_information/protocol_r0a.json \
  --data-dir ../Filang-direction/data/geometry-direction \
  --run-dir runs/qinf-r0a-reproduction
~~~

The existing audited run is preserved in
`runs/qualitative-information-r0a/`. The compact report includes every
retained file's size and SHA-256. Repeat this on a different output path to
avoid rewriting the original artifacts.

## Scientific boundary

The R0a 30-minute fixed joint-abstraction model meets the frozen
**retrospective** next-bar coding criterion, but its +0.000441878 nats per
prediction gain is small and not superior to either simpler fixed component
model in the same dataset. Other timeframes are descriptive only.

Most importantly, all dates and the 30-minute prior lead were inspected in
earlier Filang research. Neither the current freeze nor its independent audit
undoes that exposure. Real-world utility, economic return, independent
confirmation, causal mechanism, and market-generative null remain **open**.

Do not relabel a new fit over the same historical data as a prospective test.
A separate prospective protocol needs data after that protocol's freeze.
