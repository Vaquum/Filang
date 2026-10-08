# Bitcoin next-bar direction from complete candle geometry

This repeatable classification experiment asks whether the qualitative arrangement of candle bodies and wicks helps predict Bitcoin's immediately subsequent bar direction, beyond unconditional direction frequency and ordinary lag-one direction autocorrelation.

The executable specification is [protocol.json](protocol.json). The [measured results and verification report](../../benchmarks/reports/20261008-bitcoin-direction/README.md) records the resulting evidence. Performance and outcome numbers belong to that report; this document defines what is run, how it is scored, and how to reproduce it.

## 1. Declared experiment

The design crosses nine consecutive window lengths, five independently sourced timeframes, and both supported geometry modes:

| Dimension | Values |
|---|---|
| Candles in the feature window | 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| Bar duration | 15, 30, 60, 120, 240 minutes |
| Geometry mode | Unoriented; oriented |
| Prediction horizon | The immediately subsequent bar, lag one |
| Primary outcome, `cc` | `sign(close[t+1] - close[t])` |
| Secondary outcome, `body` | `sign(close[t+1] - open[t+1])` |
| Probability smoothing, `alpha` | 1, 10, 100, 1000 |

There are **90 complete geometry mappings**: 9 lengths × 5 timeframes × 2 modes. Each mapping supplies two outcome tables. Four smoothing choices produce **720 candidate forecasters**, comprising 360 primary and 360 secondary candidates. The two outcomes share the same geometry and eligible observations; they are not independent experiments.

No volume, indicators, wick ratios, body lengths, elapsed-time features, or numeric price thresholds enter a geometry key. The bar duration selects a dataset and the window length selects its consecutive candles. The body direction is retained only in oriented mode. Baseline direction variables are recorded separately for the declared controls.

## 2. Complete qualitative identity

For each candle the four boundaries are:

$$
L\le b=\min(O,C)\le t=\max(O,C)\le H.
$$

One canonical pattern preserves the global order and equality of all boundaries in its window. Rows appear current-first: candle `t`, then `t-1`, through `t-n+1`. Global ranking retains comparisons between nonadjacent candles as well as neighboring candles. Equal boundaries express missing wicks, zero bodies, flat candles, and shared price levels. Opening gaps remain legal geometry.

The versioned text format is `g1:u:` for unoriented and `g1:o:` for oriented geometry. For example, `g1:o:0,1,2,3,u;4,5,6,7,d` contains two ordered candle rows, each with `[low, body_low, body_high, high]` ranks and an optional direction token. The tokens are `d`, `z`, and `u`. Equality is exact on the validated numeric input; there is no fitted equality tolerance. A strictly increasing price transformation preserves these qualitative identities.

The implementation uses a lossless **32-byte key** containing up to forty six-bit ranks, body directions, window length, and mode. Hash collisions are resolved by full-key equality. The catalogue writes canonical text directly from the key without allocating an intermediate pattern. See the [bar-geometry reference](../../docs/BAR_GEOMETRY.md) for the language, counting derivation, degeneracies, and key layout.

### What “every possible combination” means

The native sweep records every identity observed on an eligible labelled window. It also records the exact size of the legal complement, both relative to all observed windows and relative to training windows alone. Ten-bar cardinalities exceed `u128`; the direction experiment uses checked arbitrary-precision decimal counting through ten bars.

Every unobserved identity has zero empirical counts. Its empirical conditional rate is **undefined**, rather than an estimated edge. For prediction, an identity without any fitting binary outcomes receives the fitted unconditional probability. The symbolic complement accounts for the entire legal universe without inventing examples or sampling identities.

These counts describe geometry identities. They do not mean that an astronomical number of independent historical observations or backtests were performed.

## 3. Data and chronology

All timestamps are UTC candle opening timestamps. The intervals are half-open:

| Phase | Opening timestamps | Use |
|---|---|---|
| Training | 2020-01-01 to 2024-01-01 | Fit probabilities evaluated on validation |
| Validation | 2024-01-01 to 2025-01-01 | Select length, orientation, and smoothing |
| Test | 2025-01-01 to 2026-10-08 | Evaluate frozen selected models |

The source snapshots are pinned by full Hub commit, filename, SHA-256, byte length, and row count in `protocol.json`:

| Minutes | Immutable Vaquum source revision |
|---:|---|
| 15 | [binance_btcusdt_15m_klines](https://huggingface.co/datasets/vaquum/binance_btcusdt_15m_klines/tree/46344429039d7b268dfadcb20bee2435cfb6cdd5) |
| 30 | [binance_btcusdt_30m_klines](https://huggingface.co/datasets/vaquum/binance_btcusdt_30m_klines/tree/9ebf9f0f26c13e2e34a5a2808082d73127f142e5) |
| 60 | [binance_btcusdt_1h_klines](https://huggingface.co/datasets/vaquum/binance_btcusdt_1h_klines/tree/0e32b55575e24c0748aad7cb9140caf0fb04913c) |
| 120 | [binance_btcusdt_2h_klines](https://huggingface.co/datasets/vaquum/binance_btcusdt_2h_klines/tree/cffd0d94bf33bcd4455d1846f13dbf3a9854b11f) |
| 240 | [binance_btcusdt_4h_klines](https://huggingface.co/datasets/vaquum/binance_btcusdt_4h_klines/tree/45183e45055b759ad803547e9fdb124033fdabfb) |

[prepare_direction.py](../../scripts/prepare_direction.py) downloads these exact files, checks their identities, and extracts OHLCV CSVs. It rejects null, nonfinite, invalid OHLCV, duplicate, unordered, or off-grid records. It retains every real bar in the declared interval and records missing grid bars. It verifies the outer coverage boundaries and the validation/test opening candles.

### When an observation becomes knowable

For interval length `Δ`, the geometry of candle `t` is available at `open_timestamp[t] + Δ`. The next outcome is available at `open_timestamp[t] + 2Δ`. An event requires:

1. All `n` feature candles and the following target candle to be consecutive on the declared grid.
2. Every feature candle to lie within the history beginning 2020-01-01.
3. Current and target opening timestamps to belong to the same phase.
4. The target candle to finish no later than that phase's end.

No missing bar is filled or compressed away. A missing grid bar invalidates every candidate whose feature or target span crosses it. The source's final candle cannot be a decision because its next outcome is absent. An otherwise valid decision immediately before a phase boundary is purged when its target would enter the next phase.

The native counters partition candidate decisions into `gap_purged`, `boundary_purged`, and emitted `events`, in that order. Down, flat, and up outcomes are retained throughout. Binary scores exclude exactly flat targets and report the excluded counts.

## 4. Fitting, selection, and inference

For a pattern with fitting counts `up` and `down`, its probability is:

$$
p(\text{up}\mid g)=\frac{\text{up}_g+\alpha p_0}{\text{up}_g+\text{down}_g+\alpha},
\qquad
p_0=\frac{\text{up}+0.5}{\text{up}+\text{down}+1}.
$$

The prior and baseline fits are shared within each timeframe/outcome and use every eligible two-bar fitting observation. Each geometry candidate uses all its own eligible fitting observations. Pattern identities discovered later may exist in the serialized catalogue, but their held-out labels never enter a fit.

### Equal comparison opportunities

Every candidate's validation and test scores use the **same valid ten-bar decision timestamps** within its timeframe. A shorter window otherwise has more eligible observations around gaps and at the history start; giving each candidate a different evaluation sample would confound the comparison. Training retains each candidate's full eligible sample.

The fitted controls are unconditional frequency, lag-one close direction, and current body direction. Conditional controls use three current states—down, flat, up—with Jeffreys-smoothed binary probabilities. Deterministic momentum and reversal accuracies are also reported, with flat-current abstentions explicit.

Selection minimizes validation binary log loss. Scores within an absolute `1e-12` of the minimum are tied; the deterministic preference is fewer bars, then unoriented geometry, then smaller `alpha`. This chooses one `(n, mode, alpha)` per timeframe and outcome. Its counts are then refitted on training plus validation and frozen throughout test. All-candidate test tables are descriptive; test scores do not choose a candidate.

Metrics include log loss, Brier score, accuracy, balanced accuracy, class counts, and fitting-support coverage at 1, 5, 20, and 100 occurrences. Support counts include flats and are labelled accordingly. Unseen-pattern coverage exposes when a long window supplies little reusable evidence.

The primary comparison is selected `cc` geometry versus learned lag-one close direction. The secondary comparison uses the current-body control. Paired circular moving-block bootstrap resamples UTC target days, retaining observation-weighted daily sums. The main block length is seven days; one- and twenty-eight-day blocks are sensitivity analyses. There are 2,000 replicates with seed `20261008`. The output contains percentile intervals and one-sided centered-null bootstrap probabilities. Holm adjustment covers the five selected primary tests; secondary results form a separate exploratory family.

The protocol was committed before analysis in [020a362](https://github.com/mikkokotila/Filang/commit/020a362). The final protocol bytes and implementation identities are saved with each run. This is a retrospective study: the test interval is held out from this experiment's fitting and selection, while portions of the same historical period appeared in earlier Filang work. It is not asserted to be previously untouched data.

## 5. Native execution and artifacts

[direction.rs](../../src/direction.rs) specializes the sweep for conditional direction counts, reusing the complete geometry kernel. Each eligible window updates one fixed-key record and emits one event. It avoids allocating a pattern-by-timeline Boolean mask for this objective.

For `N` input rows, work is `O(N × Σ n log n)` over the requested small windows; `n ≤ 10`. Memory is proportional to input rows plus distinct observed patterns in active tasks. Sorting uses reusable buffers, hash entries and counts are reserved once, and output is buffered and hashed while streaming. CPU workers process the eighteen independent length/mode tasks within one timeframe. The run records requested and effective worker counts; a conservative memory budget can reduce active workers. There is no GPU or distributed execution path in this experiment.

For each timeframe the native command creates `tasks/n02-oriented/` through the requested task set:

| File | Meaning |
|---|---|
| `patterns.tsv` | Zero-based ID, canonical pattern, and eighteen counts: phase × outcome × down/flat/up |
| `events.tsv` | Decision/target opening timestamps, phase, pattern ID, both target signs, current close sign, current body sign |
| `summary.json` | Exact universe/complement sizes, observed identities, phase totals, purges, and source/context metadata |
| `task.identity` | Semantic run identity and task width/mode |
| `timing.json` | Native task and encoding/event-output timings |
| `artifacts.tsv` and `.sha256` | Byte lengths and checksums for the task files |

IDs follow first eligible chronological occurrence and are local to their task. They are stable across worker counts but are not portable meanings; use canonical strings across runs. Count columns are ordered `train`, `validation`, `test`; within each phase, `cc` then `body`; within each outcome, `down`, `flat`, `up`. Event signs are `-1`, `0`, `1`.

Each task publishes atomically after its files are flushed and sealed. Resume verifies input, executable, semantic configuration, and completed artifacts before continuing. Worker count may change; data or executable changes require a fresh run. The top-level `manifest.json` records task status, memory estimates, and invocation timing.

## 6. Reproduce the experiment

From the repository root, use a Python interpreter compatible with the pinned requirements:

```sh
python3 -m venv .venv-direction
. .venv-direction/bin/activate
python -m pip install -r requirements-direction.txt
rustup toolchain install 1.63.0 --profile minimal
```

[requirements-direction.txt](../../requirements-direction.txt) includes the pinned Polars input adapter and NumPy analysis/verifier dependencies. The native Rust engine has no external crate dependencies.

Run preparation, release build, all ninety mappings, analysis, and exhaustive verification:

```sh
python scripts/run_direction_experiment.py \
  --out runs/geometry-direction-v1 \
  --workers 10
```

The runner uses `experiments/geometry_direction/protocol.json`, places prepared sources under `data/geometry-direction`, and invokes pinned Rust 1.63 in offline, locked mode. Release settings retain LTO and a single code-generation unit. `--memory-mib` defaults to 4096 in the runner; the native command alone defaults to 2048. Requested worker count is a ceiling, bounded by active tasks and the memory allowance.

Stages can be rerun explicitly:

```sh
python scripts/run_direction_experiment.py \
  --out runs/geometry-direction-v1 --stage map --workers 10 --resume

python scripts/run_direction_experiment.py \
  --out runs/geometry-direction-v1 --stage analyze

python scripts/run_direction_experiment.py \
  --out runs/geometry-direction-v1 --stage verify
```

Resume requires the same binary bytes; use `--skip-build` when retaining an existing release executable. A fresh timing measurement requires a new output directory. Do not pre-create an individual native timeframe directory. `--stage prepare`, `--data-dir`, `--protocol`, `--binary`, and `--cargo` support explicit staging and environment selection.

The native command is also directly usable on one prepared CSV:

```sh
./target/release/filang geometry-direction-sweep \
  --data data/geometry-direction/15m/ohlcv.csv \
  --interval-seconds 900 \
  --history-start 2020-01-01 --validation-start 2024-01-01 \
  --test-start 2025-01-01 --end 2026-10-08 \
  --bars 2,3,4,5,6,7,8,9,10 --modes oriented,unoriented \
  --workers 10 --out runs/direction-15m
```

`--max-tasks N` can stop after a bounded number of new tasks. Continue with the same arguments and `--resume true`. `--max-rows` defaults to 2,000,000 and cannot exceed `u32::MAX`; exceeding a guard fails explicitly.

## 7. Verification and performance measurement

[verify_direction.py](../../scripts/verify_direction.py) independently rebuilds geometry from sorted distinct endpoints and computes complete-domain cardinalities with Python integer inclusion/exclusion. Its default audit checks every event, phase assignment, gap exclusion, target/control sign, ID, catalogue count, universe/complement count, source hash, and artifact seal.

When supplied the analysis, it also independently checks candidate and baseline scores, validation-only selection, frozen probabilities, every selected daily sum, the primary-comparator bootstrap sensitivities, and Holm adjustment. Native tests separately exercise real-command chronology, ten-bar counts, worker/resume parity, resource guards, and tamper detection. Python synthetic tests exercise fitting and inference.

`--verify-sample-per-task N` deliberately requests a labelled sample geometry audit. The receipt then does not claim exhaustive reconstruction. Full verification is the default and is the evidence required for the complete experiment. Relocated exact-byte inputs can be supplied to the verifier with `--source-map`; paths alone never replace checksum agreement.

For fresh, matched one-versus-ten-worker measurements:

```sh
python scripts/benchmark_direction.py \
  --out runs/geometry-direction-benchmark \
  --workers 1,10 --repeats 3 --timeframes 15
```

Use `--timeframes all` for all five sources. The benchmark retains every repeat's complete outputs and checks scientific-file byte equivalence. Native timing includes CSV loading, encoding, grouping, hashing, and durable output. Download, compilation, analysis, verification, and cross-run comparison are measured separately. Per-child elapsed time, CPU time, and peak RSS are recorded; filesystem caches are not claimed to be cold.

Outcome estimates, uncertainty, coverage, measured speed, and verification receipts are published in the [experiment report](../../benchmarks/reports/20261008-bitcoin-direction/README.md). This experiment measures direction classification; fees, slippage, execution, and trading returns require a separately specified trading experiment.

## 8. Collect and render a report

After a complete audit and matched benchmark, collect the compact evidence without copying the large pattern/event tables:

```sh
python scripts/collect_direction_report.py \
  --run runs/geometry-direction-v1 \
  --benchmark runs/geometry-direction-benchmark \
  --data-dir data/geometry-direction \
  --out benchmarks/reports/my-direction-run
```

The collector requires exhaustive verification and matching protocol, executable, source, and artifact identities. It checks the benchmark's scientific-file hashes against the original audited files, then retains the analysis, selected probability tables, daily sums, native summaries and seals, timings, and verification receipts. Existing identical evidence can be collected again; differing files fail explicitly. Existing report prose and figures are preserved.

Optional figures are generated only from the completed analysis artifact:

```sh
python -m pip install -r requirements-direction-plots.txt
python scripts/plot_direction.py \
  --analysis benchmarks/reports/my-direction-run/analysis.json \
  --out benchmarks/reports/my-direction-run/figures
```

Plotting is outside the fitting and timing paths. The figure receipt records the analysis checksum, plotting-script checksum, library versions, and each image's checksum.
