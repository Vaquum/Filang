# QINF-R0a: predictive information in fixed qualitative abstractions

**Scientific result: supported within the predeclared retrospective criterion, not new prospective confirmation.** The independently verified 30-minute fixed *joint* endpoint-relationship model has positive paired held-out next-candle close-direction log-loss improvement over the learned lag-one direction model, including partial 2026. The magnitude is small. This is not evidence of an economically tradable signal, novel causal mechanism or uninspected market-data confirmation.

**Audit: PASS.** All five pinned BTCUSDT timeframes were checked against independent source-OHLC calculations. The experiment was executed after the frozen checksum-only amendment; the original frozen preflight failure remains preserved.

## Scope and scientific chronology

1. The original [R0 protocol](../../../experiments/qualitative_information/protocol.json) was frozen at commit `c6e1add2995e30eb7499e09f03ab6265a5755662`, SHA-256 `0ea24346e24eb33acb670125d0e6f212f77955dcf713d3fe061f96dea4937b66`.
2. The first preflight used a wrong directory convention (`15/` versus existing `15m/`); no data were analyzed. The next preflight correctly rejected a miscopied 120-minute CSV SHA. The original protocol remains unmodified, with the [failed input-integrity receipt](../../../experiments/qualitative_information/PRECHECK_FAILURE.json). Scientific status of original R0: **inconclusive**.
3. The separately [frozen R0a amendment](../../../experiments/qualitative_information/protocol_r0a.json) corrected **only** the 120m CSV checksum; it did not change the data, hypothesis, models, splits, target, priors, criteria, or null. Commit `c2eecc24103b049866de2881ca8141ac194a0927`, protocol SHA-256 `3f84a6331f1f6c07f3924dfefa9ede739efaa597c98448e382accc45cb2e56ea`.
4. One R0a producer run then exported the native causal two-candle signatures, fitted the fixed statistical models, scored all held-out eligible events, generated the 16 time-shift placebos, and retained the full prediction rows.
5. An independently coded Python auditor **did not import the producer**. It reconstructed every observed native signature from CSV price endpoints, labels, chronological folds, fit tables, scores, bootstrap distribution, and placebo measurements, retaining a full [PASS receipt](verification.json). The final [result.json](result.json) is bound by hash to both producer and audit.

Prior research had already inspected the whole 2020–October 7, 2026 BTC source period, and the **30-minute timeframe was selected because of earlier signals**. A future observation is not fresh merely because its labels were held out from a particular fit. A nominal p-value here does not adjust for previous timeframe selection or previous experiments.

## Exact primary comparison

For each candle `t`, use the **current-first** oriented native two-candle geometry from `t,t-1`, available at the close of `t`. The binary target is the sign of `close[t+1]-close[t]`; true flats are excluded from fitting/scoring and retained in counts. Gaps are never filled; all three relevant candles must be contiguous.

The baseline learns `P(next up | sign(close[t]-close[t-1]))` with Jeffreys smoothing. The fixed joint qualitative abstraction contains the four current/prior body endpoint-pair comparisons, four current/prior full-range comparisons, and two body directions. The alternative learns `P(next up | lag direction, signature)`, shrunk toward the lag-direction baseline with frozen strength `alpha=100`. There is **no selection** among models, priors, thresholds or timeframes on this test; body-only and range-only models are reported descriptively.

Fit separately for each outer year using **only completed target labels from 2020 onward strictly before that year**. Evaluate 2023, 2024, 2025 and partial 2026 ending before 2026-10-08 UTC. Purge boundary-crossing labels. Four years' sums are observation-weighted for the pooled result.

| Primary 30m measure | Audited result |
|---|---:|
| Scored binary next-bar events | **66,005** |
| Improvement (baseline minus joint natural-log loss) | **+0.000441877772745 nats/event** |
| Aggregate predictive description length saved | **+42.077848985 bits** |
| Paired circular 7-day moving-block bootstrap 95% interval | **[+0.000131555677, +0.000766198276] nats/event** |
| Centered-null one-sided bootstrap p (2,000 replicates) | **0.003498250875** |
| Positive outer years | **3 of 4**, including partial 2026 |
| Independent audit | **PASS** |
| Complete frozen retrospective criterion | **supported** |

The bootstrap resamples within each annual segment, retains days without scored events, and scores the pooled observation-weighted difference. This is a **nominal conditional uncertainty calculation**, not a correction for the sequence of previous Filang hypotheses.

## Annual 30-minute behavior

| Outer year | Binary events | Joint minus baseline coding advantage, nats/event | Total bits saved |
|---|---:|---:|---:|
| 2023 | 17,504 | +0.000937804230 | +23.6823 |
| 2024 | 17,559 | +0.000850323951 | +21.5406 |
| 2025 | 17,512 | **−0.000446851768** | −11.2895 |
| Partial 2026 | 13,430 | +0.000420346021 | +8.1444 |

The negative 2025 result is retained. The full per-year class counts, unmatched-signature counts, source hashes, complete conditional probability record and all original test definitions are in [producer.json](producer.json) and [result.json](result.json).

## Information in simpler abstractions

All three models were fixed before outcome fitting. These are **descriptive** comparisons; secondary models cannot replace the predeclared primary.

| BTC candle interval | Binary events | Body-only gain | Range-only gain | Joint gain |
|---:|---:|---:|---:|---:|
| 15m | 131,998 | +0.000780526 | +0.000247966 | +0.000623314 |
| **30m** | **66,005** | **+0.000447891** | **+0.000449200** | **+0.000441878** |
| 60m | 33,011 | +0.000524801 | +0.000421571 | +0.000054887 |
| 120m | 16,500 | +0.000478967 | +0.000563287 | +0.000005705 |
| 240m | 8,248 | −0.000749381 | −0.000030616 | −0.000070626 |

Gains are natural-log-loss reduction per binary prediction over the *same* fitted lag-one baseline. At 30m, **both simpler abstractions slightly outperform the joint representation**. At 60m and 120m, the joint model loses much of the simpler models' descriptive gain. These observations do **not** establish that adding more qualitative distinctions improves prediction. No trading score or cost-adjusted payoff was computed.

## Placebo and synthetic controls

Sixteen **predeclared** nominal shifts from 14 through 119 days (step seven days) were applied to the joint signature sequence within each fold's fitting events and within each fold's scored events, separately. Labels, lag-direction baseline, fold boundaries and event counts remained fixed. Each shifted conditional model was refitted to its own surrogate alignment. All sixteen placebo gains were negative, ranging approximately **−0.000735 to −0.000338 nats/event**.

These shifts preserve the observed signature sequence and some local autocorrelation, but disrupt feature-outcome alignment. They are **noncausal alignment placebos, not samples from an established market generative null**. They were predeclared as descriptive only, not used to compute the bootstrap p-value or open a success route.

The native exporter also passed an independent synthetic-OHLC contract test: gaps, ties, wicks and doji; exact signature parity; past-feature invariance when future candles are appended; feature availability on the final unlabelled candle; fail-closed invalid data and output protection. Those tests are correctness controls, not an empirical market null.

## Verifiability and source boundaries

Source data: the exact five previously published immutable Vaquum BTCUSDT snapshots, using the previously prepared and SHA-256 pinned OHLCV CSVs under `data/geometry-direction/{minutes}m/ohlcv.csv` in the local direction worktree. Each CSV's SHA, source row count and original raw Parquet identity are fixed in the R0a protocol. The native binary uses the **real Phase 2 Schema API**; it does not maintain a second implementation of its geometry semantics. The verifier *does* implement independent comparison and direction decoding from raw prices.

The auditor verified **255,762** held-out binary predictions across five timeframes and every native feature row (including rows with no future target), with maximum absolute numerical comparison discrepancy **2.099 × 10⁻¹¹**, within the fixed numerical tolerances. All model and score outputs are retained as source-index-aligned TSVs in the ignored run directory; the compact result, producer, audit and [manifest.json](manifest.json) are committed unchanged. The manifest includes full-row artifact SHA-256 hashes so their integrity can be checked without adding large datasets or response arrays to Git.

### Reproduce in a fresh output directory

~~~sh
cargo +1.63.0 build --release --locked --offline --bin geometry_abstraction_features

python3 experiments/qualitative_information/test_synthetic.py \
  --binary target/release/geometry_abstraction_features

python3 experiments/qualitative_information/run.py \
  --protocol experiments/qualitative_information/protocol_r0a.json \
  --data-dir ../Filang-direction/data/geometry-direction \
  --binary target/release/geometry_abstraction_features \
  --out runs/qualitative-information-r0a-reproduction

python3 experiments/qualitative_information/verify.py \
  --protocol experiments/qualitative_information/protocol_r0a.json \
  --data-dir ../Filang-direction/data/geometry-direction \
  --run-dir runs/qualitative-information-r0a-reproduction
~~~

The old verified run is in `runs/qualitative-information-r0a/`; the command above writes only to a fresh directory. Use Python 3.13 for matching generator semantics and exact seeded bootstrap; the producer and independent verifier use only the standard library. The `run.py` module refuses altered frozen protocol bytes or source hashes. The native writer refuses overwriting an existing feature output.

## Residue and next decision

**QINF-R0a supported its own historical coding criterion, but it did not establish additional tradable geometry or independently confirmed predictive information.** The improvement is about 0.00064 bits per prediction, occurs in a timeframe previously selected for apparent signal, is negative in 2025, and is not better than either simpler abstraction in 30m. Secondary descriptive gains vary by timeframe.

The justified next stage is a **separately frozen prospective, externally recorded evaluation** on data not previously examined when the model and data policy are locked. Do not retune this result against the same BTC snapshots and call it fresh. A future study should explicitly compare body-only/range-only and joint models against a lag-direction baseline, incorporate a better market null where possible, and keep prediction and economic utility separate. No future data are claimed to exist in this record.
