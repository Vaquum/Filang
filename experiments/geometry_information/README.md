# Geometry information campaign — Round 1

[round1_protocol.json](round1_protocol.json) is the executable scientific specification. It must be reviewed and committed before any real-data model fitting or outcome evaluation. The run must record that freeze commit and the exact protocol SHA-256. This document explains the contract; it does not report an experiment outcome.

**Execution status:** the original R1 attempt stopped at its frozen optimizer limit and is scientifically inconclusive. Its [complete failure record](../../benchmarks/reports/20261008-geometry-information-r1-failed/README.md) preserves all retained fits and the independent forensic audit. The specification below remains the original contract; a numerical retry requires a separately frozen amendment.

[R1a](ROUND1A.md) is the separately published exact Newton amendment in merged PR #25. Its full audit passed; only 30m supported the frozen information criterion, and the selected fixed-threshold geometry policies lost at primary and reduced costs. The scientific contract below remains the original R1 reference.

[R2](ROUND2.md), separately frozen in PR #26, completed the conditional log-return and cost-aware policy experiment. Its full audit passed, with an explicit floating-tail arithmetic qualification; the economic criterion is not-supported at all five timeframes. The [complete report](../../benchmarks/reports/20261008-geometry-payoff-r2/README.md) retains all controls and outcomes. Its economic criterion is separate from this original information test.

The user subsequently reopened the 30-minute research lead after the completed
three-family campaign. [F30-D1](FOLLOWUP30.md) is that separately frozen diagnostic
in PR #28. Its full audit passed: matched past-only affine score adaptation
retains a pooled gain of 0.0004321659 nats, but only two annual effects are
positive, 2025 and partial 2026 are negative, and magnitude-weighted gain is
negative in every year. The complete stability claim is **not-supported**, and
the declared economic-continuation gate fails. Its
[complete report](../../benchmarks/reports/20261008-30m-signal-followup-d1/README.md)
preserves the positive pooled result, all diagnostic cells, the first failed
audit and the successful re-audit of the same producer output. The original R1
specification below remains unchanged.

## Claim and prior exposure

**Round 1 asks whether additive pooled endpoint geometry improves next executable-bar direction log loss beyond additive body and close-return sign history.** It tests information gain. Its fixed-policy trading outputs are diagnostics, with no model, timeframe, threshold or cost selection based on those outputs.

This follows [PR #22](https://github.com/mikkokotila/Filang/pull/22), the [complete-pattern protocol](../geometry_direction/protocol.json), and its [measured report](../../benchmarks/reports/20261008-bitcoin-direction/README.md). That experiment selected two-candle models and found severe sparsity at longer exact configurations. It did not establish primary incremental information beyond lag one.

All snapshots through **2026-10-07** and their earlier reported outcomes have already been inspected. Every fold here is retrospective. A new model, split or nested procedure cannot make those observations fresh. Positive historical results would justify further research, not a demonstrated tradeable edge.

The campaign is finite: R1 tests additive pooling; a separately frozen R2 may test a small economic-selection family; a separately frozen R3 may test limited interpretable interactions only when the recorded residue warrants it. Stop when the budget is exhausted or no declared next hypothesis is justified. Follow [Law 1](../../CLAUDE.md) for every named results or performance attempt, retaining failures and explicit supported/not-supported/inconclusive conclusions.

## Data and native feature boundary

Reuse the five immutable Vaquum BTCUSDT snapshots at 15, 30, 60, 120 and 240 minutes, from 2020-01-01 through the exclusive end 2026-10-08. The protocol pins both raw Parquet and prepared CSV hashes and links the predecessor provenance. There are 459,503 actual source candles. Preserve their timestamps and missing grid bars; never fill prices or compress gaps.

All predictive features come from the same **native oriented ten-candle global geometry key**. `geometry-key-export` emits every valid causal window `t-9,...,t`, including final rows with no future label. It does not consult targets or splits. All fitting candidates share this ten-candle validity even when their model uses fewer candles.

The `FGKEYS01` ABI is fixed in the JSON: a 168-byte header, 40-byte records containing the original source-row index and four little-endian key words, and a trailing 64-byte ASCII SHA-256 seal. The header binds context and source; records preserve original row indices. Key bits encode forty six-bit ranks, ten up flags, literal width ten, and orientation. Validate the native context, manifests and seals before decoding. Equality remains exact; no tick guess or price tolerance enters geometry.

## Two nested feature families

Use histories **2, 3, 5 and 10**. A separate orientation search would duplicate information already present in the baseline, so there is none.

| Family | Features | Columns at n=2 / 3 / 5 / 10 |
|---|---|---|
| **B** | Up/down body indicators at lags `0..n-1`; up/down close-return indicators at lags `0..n-2`; flat categories omitted | 6 / 10 / 18 / 38 |
| **G** | B, followed by current-to-prior endpoint comparison indicators and each candle's lower/upper wick presence | 42 / 80 / 156 / 346 |

For G, compare each current `[L,bottom,top,H]` endpoint with all four endpoints of each prior candle. Record `<` and `=` indicators; `>` is the reference. Append two wick-presence indicators per candle. The protocol fixes the complete column order. Every feature is an unscaled binary indicator decoded from native ranks and direction flags. Do not add interactions, scaling, feature screening, or drop constant columns. Volume, price levels, numeric returns and ratios are absent from the model inputs.

G contains B as a feature family but has more capacity. The comparison uses the same fitting and selection procedure; it is not an equal-parameter-count comparison or a fixed-model likelihood-ratio test.

## Target, folds and fitting

At the close of source candle `t`, predict:

\[
r_{t+1}=O_{t+2}/O_{t+1}-1,
\qquad y_{t+1}=\operatorname{sign}(O_{t+2}-O_{t+1}).
\]

Classification requires twelve consecutive actual candles `t-9,...,t+2`. The decision candle's **opening** must be at or after the phase start, and its exit opening `t+2` must be **strictly before** phase end. Apply this rule independently to training, validation, refit and outer evaluation. Earlier feature history is allowed when already known. Retain flat counts, but exclude exactly flat labels from binary fitting and scores.

| Outer fold | Inner training | Inner validation | Selected-model refit |
|---|---|---|---|
| 2023 | 2020–2021 | 2022 | All eligible data before 2023 |
| 2024 | 2020–2022 | 2023 | All eligible data before 2024 |
| 2025 | 2020–2023 | 2024 | All eligible data before 2025 |
| 2026 through Oct 7 | 2020–2024 | 2025 | All eligible data before 2026 |

Fit logistic regression in float64 with objective `mean(logaddexp(0,z)-y*z) + lambda*sum(beta²)/2`; the intercept is unpenalized. The fixed lambda grid is **0.1, 0.01, 0.001, 0.0001**. SciPy L-BFGS-B uses `maxiter=1000`, `ftol=1e-12`, `gtol=1e-7`, `maxls=50` and the analytic gradient. Require optimizer success, finite outputs, and maximum absolute gradient at most `5e-6`.

Initialize coefficients at zero and the intercept at the logit of the fitting sample's Beta(1,1) up probability. A recorded stronger-to-weaker lambda warm start within the same exact sample/family/history is permitted. Cache reuse requires matching data, fitting rows/labels/boundaries, features, lambda, initializer and implementation identities. Failed or nonconverged candidates remain in the record; silently discarding them is prohibited.

There are **640 inner candidates** and **40 selected refit pipelines**. Select B and G separately for each timeframe/year using validation log loss only. Scores within `1e-12` of the minimum tie; prefer shorter history, then stronger lambda. Freeze each selected refit through its outer year. Outer outcomes cannot select models or solver settings.

That restriction is relative to each outer fold. The explicit rolling schedule allows an earlier outer year to become past training or validation data in a later fold. It never permits a fold's own outer outcomes to select or fit that fold's pipeline.

Descriptive unconditional and lag-one models use Beta(1,1) smoothing on the corresponding allowed fitting sample. Lag one conditions on `sign(C[t]-C[t-1])` and falls back to unconditional when a stratum is absent. The predecessor exact-pattern model has a different target and is not imported as an R1 comparator.

## Primary criterion and uncertainty

Improvement is **B log loss minus G log loss**. Pool outer binary observations with equal observation weight and also report all four years separately. The daily unit is the UTC date of the target exit opening. Retain full calendar days, including zero-count days.

Use a paired circular moving-block bootstrap within each outer year: seven-day primary blocks, 2,000 resamples, and one-/28-day sensitivity blocks. Each year retains its original calendar length. The JSON fixes the generator seed as `20261008 + 1000*timeframe_minutes + block_days`, replicate/year draw order, circular truncation, and shared indices across paired statistics.

The confidence interval uses ordinary bootstrapped gains. For the one-sided null distribution, center each day's sum by **the pooled observed gain multiplied by that day's count**, then resample the same sum/count pairs. Do not subtract separate annual means. The p-value is `(exceedances+1)/2001`. Apply Holm correction to the five primary timeframe p-values.

A timeframe supports the claim only if:

1. Its pooled gain is positive.
2. Its primary 95% interval lies entirely above zero.
3. Its Holm-adjusted one-sided p-value is below 0.05.
4. At least three of four annual point estimates are positive.

The complete required fits and independent audit must also pass. A completed test failing the criterion is `not-supported`; incomplete or invalid evidence is `inconclusive`. Sensitivities, accuracy, other baselines and economics provide no alternative success route. This remains retrospective uncertainty, not fresh confirmation.

## Causal economic diagnostic

Evaluate selected B, selected G, unconditional and lag-one probabilities using a fixed **p≥0.5 long, otherwise cash** policy. Cash and buy-and-hold are administrative benchmarks. Positions are unleveraged BTCUSDT spot with zero cash yield.

The ledger consumes the full original observed-open timeline, not the classification subset. Predict on every causally valid ten-candle row even if its future label is unavailable. Missing causal history produces NaN and requests cash only after that candle closes. A future gap must never erase a return or cause an anticipatory exit.

Execute only the immediately preceding observed candle's signal, at the next observed open. If data are missing, carry existing holdings across the price gap and report the queued signal's delayed assumed fill. Missing dataset bars do not establish exchange closure; this is an explicit execution proxy. Report 2023's gap episode separately from continuous 2024+ data.

Each year starts in cash with no pending prior-fold signal. A signal's source candle must open inside the year. Force cash at the last observed opening strictly before fold end and prohibit a new entry there. Buy-and-hold requests long after the first in-fold candle and, unlike forecast policies, does not depend on feature-history availability. It shares reset, mark, delayed-fill and terminal-cost conventions. A combined 2024+ summary concatenates independently reset annual ledgers.

| Scenario | Fee per side | Slippage per side |
|---|---:|---:|
| Zero | 0 bps | 0 bps |
| Reduced | 5 bps | 1 bp |
| **Primary diagnostic** | **10 bps** | **2 bps** |
| Stress | 20 bps | 4 bps |

These are fixed scenarios, not claims about actual account or historical fees. With fee fraction `f` and slippage `s`, a buy has mid-mark equity factor `(1-f)/(1+s)`; a sale has factor `(1-s)*(1-f)`. While long, mark by the ratio of consecutive observed opens. Charge exposure changes, including terminal liquidation. Allocate marks and costs to the UTC day of the receiving opening and retain all calendar days.

Retain full positions/signals/fills/costs, trades, gaps, daily returns, exposure, turnover, drawdown and break-even costs. Open-based draws and fills do not reconstruct intrabar paths, spread, depth, capacity or sub-bar latency. No threshold or cost scenario is optimized in R1.

## Reproducible artifacts and audit

The JSON fixes the run contract: exact protocol copy; run/source/code/runtime identities; native feature artifacts and dictionaries; every candidate's coefficients, fitting identity and convergence record; all candidate scores; selected models; and daily/aggregate outputs. Persist both the selected **inner-validation** full-row predictions from the inner-training model and the **outer** predictions from the pre-year refit. Future R2 must not recreate validation predictions using a model trained on those labels.

Prediction NPZ files align to original CSV rows, distinguish causal-feature validity from future-label validity, retain invalid predictions as NaN, and use explicit masks to distinguish invalid labels from true flat labels. JSON sidecars bind models, phases, source and array/file hashes. A complete manifest seals retained artifacts. Large row-level files may remain in sealed reproducible run directories; commit compact results, model parameters, receipts and the independent audit.

The independent verifier may not import producer feature, target, estimator or ledger computational helpers. It must reconstruct all native keys and B/G features from raw OHLC, every phase and label, saved-coefficient predictions, candidate scores, selected parameters, daily sums, bootstrap/Holm results, and the complete ledger using a separate shares/cash oracle. Sampling is insufficient for the final audit. Report numerical discrepancies and keep integer identities, masks, labels, positions and selections exact.

Intended runtime versions are Python 3.13.2, NumPy 2.5.1, SciPy 1.18.1, Polars 1.42.1 and threadpoolctl 3.7.0. Set thread limits before imports, including `VECLIB_MAXIMUM_THREADS` for Apple Accelerate, and record NumPy/BLAS configuration even if threadpoolctl reports no library. Bound process concurrency and record it before execution. Runtime controls are not scientific search axes. Separate native export, fitting, economics and audit timings; any performance claim requires its own recorded attempt.
