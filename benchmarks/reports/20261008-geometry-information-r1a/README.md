# Bitcoin geometry information — Round 1a — numerical amendment measured report

**The frozen information criterion is supported retrospectively at 30-minute resolution.** The full independent audit passed before this report was generated.
This is an informational comparison of two finite, selected logistic model
families on previously examined historical data. It is not a demonstrated
tradeability result or an estimate of the true conditional mutual information.

The primary quantity is selected sign-history baseline **B log loss minus
selected geometry model G log loss**, measured in nats per eligible binary bar.
Positive values favor geometry. These labels concern the subsequent executable
reference interval, `O[t+2]/O[t+1]-1`, after information from candle `t` closes.
Exactly flat targets are retained in counts and excluded from binary scoring.

This is the separately frozen R1a numerical amendment. The [original R1 failure](../20261008-geometry-information-r1-failed/README.md) remains scientifically inconclusive. R1a changes the frozen numerical solver only; its objective, candidate grid, selection, inference and economic criteria remain unchanged. All R1 partial inner scores were already exposed. The complete amendment and exact solver are preserved in [protocol.json](protocol.json).

## Primary results and every success condition

| Minutes | Gain (nats/bar) | 7-day 95% CI | Raw p | Holm p | Gain >0 | CI >0 | Holm <.05 | Positive years | Audited outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | 0.00029303 | [0.00002463, 0.00057005] | 0.01549 | 0.05797 | yes | yes | no | 3/4 | not-supported |
| 30 | 0.00056875 | [0.00025086, 0.00089354] | 0.00050 | 0.00250 | yes | yes | yes | 3/4 | supported |
| 60 | 0.00069940 | [0.00004600, 0.00132770] | 0.01449 | 0.05797 | yes | yes | no | 3/4 | not-supported |
| 120 | 0.00036610 | [-0.00034217, 0.00107868] | 0.16192 | 0.32384 | yes | no | no | 1/4 | not-supported |
| 240 | 0.00024207 | [-0.00074234, 0.00128313] | 0.32384 | 0.32384 | yes | no | no | 3/4 | not-supported |

A timeframe requires all four conditions: positive pooled gain, positive lower
endpoint of the seven-day 95% interval, Holm-adjusted one-sided p below .05
across all five timeframes, and at least three positive annual effects. Complete
fit and independent-audit coverage are prerequisites. The producer's exact
[analysis.json](analysis.json) deliberately retains
`COMPLETE_PENDING_INDEPENDENT_AUDIT` and conditional outcomes; this report joins
that unchanged artifact with the subsequent [verification.json](verification.json).
No candidate, timeframe, year or unfavorable cost scenario is removed.

## Design, selection and annual effects

The five pinned Vaquum BTCUSDT sources contain 459,503 actual candles at 15, 30,
60, 120 and 240 minutes, spanning 2020-01-01 to the exclusive end 2026-10-08.
Their exact Hub revisions, raw and prepared hashes are in
[protocol.json](protocol.json) and [provenance.json](provenance.json).
Missing grid bars remain missing. Classification shares ten-candle causal
history plus two consecutive subsequent bars for every candidate, and requires
the target exit opening strictly before the relevant phase cutoff.

For outer years 2023–2026, the immediately preceding calendar year is inner
validation and earlier years from 2020 are training. B and G independently
select n in {2,3,5,10} and lambda in {.1,.01,.001,.0001} by validation log
loss, then refit all allowed earlier labels. A loss tie within 1e-12 prefers
shorter history, then stronger regularization. The partial 2026 fold ends on
October 7. There are 640 inner candidate records and 40 selected refits.

| Minutes | Outer year | Gain (nats/bar) | B n / lambda | G n / lambda |
| --- | --- | --- | --- | --- |
| 15 | 2023 | 0.00142121 | 10 / 0.1 | 10 / 0.1 |
| 15 | 2024 | 0.00028036 | 10 / 0.0001 | 10 / 0.01 |
| 15 | 2025 | -0.00059891 | 10 / 0.1 | 5 / 0.01 |
| 15 | 2026 | 0.00000261 | 10 / 0.1 | 3 / 0.1 |
| 30 | 2023 | 0.00158666 | 10 / 0.001 | 10 / 0.1 |
| 30 | 2024 | 0.00076880 | 10 / 0.0001 | 10 / 0.1 |
| 30 | 2025 | 0.00020310 | 5 / 0.01 | 3 / 0.1 |
| 30 | 2026 | -0.00054199 | 10 / 0.1 | 2 / 0.1 |
| 60 | 2023 | 0.00153899 | 5 / 0.0001 | 10 / 0.01 |
| 60 | 2024 | 0.00037168 | 10 / 0.001 | 10 / 0.1 |
| 60 | 2025 | 0.00084492 | 10 / 0.01 | 5 / 0.01 |
| 60 | 2026 | -0.00015448 | 5 / 0.1 | 3 / 0.1 |
| 120 | 2023 | 0.00262253 | 10 / 0.01 | 3 / 0.01 |
| 120 | 2024 | -0.00025220 | 10 / 0.001 | 5 / 0.01 |
| 120 | 2025 | -0.00096453 | 3 / 0.1 | 3 / 0.1 |
| 120 | 2026 | -0.00002506 | 3 / 0.1 | 2 / 0.1 |
| 240 | 2023 | -0.00053542 | 10 / 0.1 | 2 / 0.01 |
| 240 | 2024 | 0.00014277 | 2 / 0.0001 | 2 / 0.1 |
| 240 | 2025 | 0.00061381 | 10 / 0.1 | 10 / 0.1 |
| 240 | 2026 | 0.00090094 | 5 / 0.1 | 5 / 0.1 |

B contains body and close-return sign indicators. G adds additive
current-to-prior endpoint comparisons and wick-presence indicators, all decoded
from the native oriented ten-candle geometry key. G has more columns; this is
not an equal-capacity comparison. Full coefficients, fitting identities,
convergence receipts and scores are retained in [fits.jsonl](fits.jsonl),
[candidates.csv](candidates.csv), [selected.json](selected.json) and the individual
model records listed in the package manifest.

The unconditional and lag-one models are descriptive controls with the frozen
Beta(1,1) smoothing. Accuracy above 50% alone is not incremental evidence beyond
these controls, and an accuracy difference is not the primary success test.

| Minutes | Policy | Binary bars | Flat bars | Log loss | Brier | Accuracy | Balanced accuracy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | B | 131986 | 81 | 0.69115038 | 0.249003 | 52.50% | 52.49% |
| 15 | G | 131986 | 81 | 0.69085735 | 0.248856 | 52.92% | 52.92% |
| 15 | unconditional | 131986 | 81 | 0.69315260 | 0.250003 | 50.12% | 50.00% |
| 15 | lag1 | 131986 | 81 | 0.69218934 | 0.249521 | 52.24% | 52.24% |
| 30 | B | 66002 | 22 | 0.69095238 | 0.248904 | 52.90% | 52.85% |
| 30 | G | 66002 | 22 | 0.69038363 | 0.248621 | 53.21% | 53.17% |
| 30 | unconditional | 66002 | 22 | 0.69307213 | 0.249962 | 50.62% | 50.00% |
| 30 | lag1 | 66002 | 22 | 0.69170896 | 0.249280 | 52.75% | 52.76% |
| 60 | B | 32997 | 6 | 0.69034376 | 0.248600 | 53.33% | 53.20% |
| 60 | G | 32997 | 6 | 0.68964436 | 0.248248 | 53.70% | 53.63% |
| 60 | unconditional | 32997 | 6 | 0.69305503 | 0.249954 | 50.73% | 50.00% |
| 60 | lag1 | 32997 | 6 | 0.69161885 | 0.249236 | 52.75% | 52.76% |
| 120 | B | 16489 | 3 | 0.69032377 | 0.248593 | 52.79% | 52.78% |
| 120 | G | 16489 | 3 | 0.68995767 | 0.248410 | 53.32% | 53.12% |
| 120 | unconditional | 16489 | 3 | 0.69290206 | 0.249877 | 51.14% | 50.00% |
| 120 | lag1 | 16489 | 3 | 0.69147998 | 0.249166 | 52.97% | 53.00% |
| 240 | B | 8248 | 0 | 0.68950715 | 0.248183 | 54.10% | 53.90% |
| 240 | G | 8248 | 0 | 0.68926508 | 0.248061 | 54.22% | 53.91% |
| 240 | unconditional | 8248 | 0 | 0.69273716 | 0.249795 | 51.53% | 50.00% |
| 240 | lag1 | 8248 | 0 | 0.68958698 | 0.248222 | 54.00% | 54.05% |

## Dependence and block sensitivity

The paired bootstrap resamples complete UTC target-exit dates, including
zero-count days, within each outer year. It pools observations with equal
per-bar weight, uses 2,000 replicas, and centers the null by the global observed
gain times each day's count. The frozen seed and draw order are in the protocol.
Only the seven-day test and its five-way Holm adjustment determine success.

| Minutes | Block days | 95% CI (nats/bar) | Raw one-sided p |
| --- | --- | --- | --- |
| 15 | 1 | [0.00003720, 0.00057580] | 0.02099 |
| 15 | 7 | [0.00002463, 0.00057005] | 0.01549 |
| 15 | 28 | [0.00003224, 0.00057237] | 0.02149 |
| 30 | 1 | [0.00020425, 0.00092472] | 0.00200 |
| 30 | 7 | [0.00025086, 0.00089354] | 0.00050 |
| 30 | 28 | [0.00020584, 0.00090312] | 0.00100 |
| 60 | 1 | [0.00003968, 0.00133015] | 0.01699 |
| 60 | 7 | [0.00004600, 0.00132770] | 0.01449 |
| 60 | 28 | [0.00011727, 0.00128245] | 0.01349 |
| 120 | 1 | [-0.00042251, 0.00118565] | 0.19140 |
| 120 | 7 | [-0.00034217, 0.00107868] | 0.16192 |
| 120 | 28 | [-0.00033586, 0.00113463] | 0.16692 |
| 240 | 1 | [-0.00087124, 0.00138674] | 0.32984 |
| 240 | 7 | [-0.00074234, 0.00128313] | 0.32384 |
| 240 | 28 | [-0.00065750, 0.00122881] | 0.29885 |

The one- and 28-day rows are sensitivity descriptions, not alternative paths to
success. These intervals describe the frozen pipelines conditionally on the
retrospective research design; they do not erase prior exposure or repeated
research selection. [classification_daily.csv](classification_daily.csv)
contains the paired daily receipts.

## Fixed-policy economic diagnostic

Selected B and G, unconditional and lag-one probabilities use the frozen
`p>=0.5` long/cash policy, without economic model or threshold selection.
The primary cost scenario is **10 bps fee plus 2 bps slippage per side**.
Cash and buy-and-hold follow the same annual reset and terminal liquidation
conventions; buy-and-hold does not stop for unavailable geometry history.

The table separates gap-affected 2023 from continuous 2024+ and also reports all
outer years. Aggregates compound independently reset annual ledgers; they do
not imply positions were carried across year boundaries. Exposure is elapsed
time spent long; one-way turnover counts position changes. Break-even is the
equivalent symmetric wealth haircut per side on the fixed gross trading path,
not a newly selected fee assumption or a guarantee about actual execution.

| Minutes | Period | Policy | Net return | Net log return | Exposure | One-way turns | Break-even bps/side |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | 2023 | B | -99.99% | -9.8420 | 56.95% | 8910 | 0.959 |
| 15 | 2023 | G | -99.99% | -9.5471 | 52.40% | 8764 | 1.111 |
| 15 | 2023 | unconditional | 156.46% | 0.9418 | 99.97% | 4 | 2107.322 |
| 15 | 2023 | lag1 | -100.00% | -21.7268 | 49.52% | 18510 | 0.267 |
| 15 | 2023 | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 15 | 2023 | buy_hold | 155.06% | 0.9363 | 100.00% | 2 | 3746.055 |
| 15 | 2024+ | B | -100.00% | -29.3464 | 55.74% | 25740 | 0.604 |
| 15 | 2024+ | G | -100.00% | -29.9165 | 52.16% | 26102 | 0.544 |
| 15 | 2024+ | unconditional | 94.27% | 0.6641 | 100.00% | 6 | 1058.475 |
| 15 | 2024+ | lag1 | -100.00% | -59.1396 | 49.96% | 50492 | 0.292 |
| 15 | 2024+ | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 15 | 2024+ | buy_hold | 94.27% | 0.6641 | 100.00% | 6 | 1058.475 |
| 15 | all outer | B | -100.00% | -39.1885 | 56.06% | 34650 | 0.695 |
| 15 | all outer | G | -100.00% | -39.4636 | 52.22% | 34866 | 0.686 |
| 15 | all outer | unconditional | 398.22% | 1.6059 | 99.99% | 10 | 1493.778 |
| 15 | all outer | lag1 | -100.00% | -80.8663 | 49.85% | 69002 | 0.286 |
| 15 | all outer | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 15 | all outer | buy_hold | 395.51% | 1.6004 | 100.00% | 8 | 1822.939 |
| 30 | 2023 | B | -99.99% | -9.6817 | 52.28% | 8698 | 0.874 |
| 30 | 2023 | G | -99.76% | -6.0491 | 52.90% | 5588 | 1.180 |
| 30 | 2023 | unconditional | 157.00% | 0.9439 | 99.94% | 4 | 2111.465 |
| 30 | 2023 | lag1 | -100.00% | -10.5674 | 49.51% | 9478 | 0.856 |
| 30 | 2023 | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 30 | 2023 | buy_hold | 154.35% | 0.9336 | 99.99% | 2 | 3737.321 |
| 30 | 2024+ | B | -100.00% | -25.9143 | 53.85% | 22850 | 0.664 |
| 30 | 2024+ | G | -100.00% | -20.4376 | 53.64% | 17976 | 0.636 |
| 30 | 2024+ | unconditional | 94.83% | 0.6670 | 99.99% | 6 | 1062.778 |
| 30 | 2024+ | lag1 | -100.00% | -29.0171 | 49.32% | 25350 | 0.558 |
| 30 | 2024+ | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 30 | 2024+ | buy_hold | 94.83% | 0.6670 | 99.99% | 6 | 1062.778 |
| 30 | all outer | B | -100.00% | -35.5960 | 53.43% | 31548 | 0.722 |
| 30 | all outer | G | -100.00% | -26.4867 | 53.44% | 23564 | 0.765 |
| 30 | all outer | unconditional | 400.71% | 1.6109 | 99.98% | 10 | 1498.020 |
| 30 | all outer | lag1 | -100.00% | -39.5845 | 49.37% | 34828 | 0.639 |
| 30 | all outer | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 30 | all outer | buy_hold | 395.56% | 1.6005 | 99.99% | 8 | 1823.039 |
| 60 | 2023 | B | -93.17% | -2.6842 | 58.60% | 2772 | 2.322 |
| 60 | 2023 | G | -93.68% | -2.7611 | 54.18% | 2754 | 1.979 |
| 60 | 2023 | unconditional | 159.38% | 0.9531 | 99.89% | 4 | 2129.639 |
| 60 | 2023 | lag1 | -99.43% | -5.1591 | 48.59% | 4734 | 1.107 |
| 60 | 2023 | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 60 | 2023 | buy_hold | 155.04% | 0.9362 | 99.99% | 2 | 3745.723 |
| 60 | 2024+ | B | -99.99% | -8.8961 | 58.98% | 8372 | 1.379 |
| 60 | 2024+ | G | -99.94% | -7.4538 | 55.44% | 6954 | 1.286 |
| 60 | 2024+ | unconditional | 92.48% | 0.6548 | 99.99% | 6 | 1044.651 |
| 60 | 2024+ | lag1 | -100.00% | -14.1369 | 49.48% | 12676 | 0.852 |
| 60 | 2024+ | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 60 | 2024+ | buy_hold | 92.48% | 0.6548 | 99.99% | 6 | 1044.651 |
| 60 | all outer | B | -100.00% | -11.5803 | 58.88% | 11144 | 1.613 |
| 60 | all outer | G | -100.00% | -10.2149 | 55.11% | 9708 | 1.483 |
| 60 | all outer | unconditional | 399.24% | 1.6079 | 99.96% | 10 | 1495.527 |
| 60 | all outer | lag1 | -100.00% | -19.2960 | 49.25% | 17410 | 0.922 |
| 60 | all outer | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 60 | all outer | buy_hold | 390.88% | 1.5910 | 99.99% | 8 | 1813.351 |
| 120 | 2023 | B | -92.07% | -2.5349 | 49.33% | 2318 | 1.069 |
| 120 | 2023 | G | -86.16% | -1.9777 | 57.23% | 2026 | 2.243 |
| 120 | 2023 | unconditional | 160.66% | 0.9580 | 99.77% | 4 | 2139.296 |
| 120 | 2023 | lag1 | -92.67% | -2.6128 | 48.09% | 2370 | 0.980 |
| 120 | 2023 | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 120 | 2023 | buy_hold | 156.28% | 0.9411 | 99.98% | 2 | 3760.958 |
| 120 | 2024+ | B | -99.86% | -6.5622 | 50.79% | 6130 | 1.300 |
| 120 | 2024+ | G | -99.34% | -5.0249 | 59.41% | 4812 | 1.562 |
| 120 | 2024+ | unconditional | 94.00% | 0.6627 | 99.98% | 6 | 1056.393 |
| 120 | 2024+ | lag1 | -99.87% | -6.6532 | 49.05% | 6364 | 1.550 |
| 120 | 2024+ | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 120 | 2024+ | buy_hold | 94.00% | 0.6627 | 99.98% | 6 | 1056.393 |
| 120 | all outer | B | -99.99% | -9.0971 | 50.40% | 8448 | 1.237 |
| 120 | all outer | G | -99.91% | -7.0026 | 58.83% | 6838 | 1.764 |
| 120 | all outer | unconditional | 405.67% | 1.6207 | 99.92% | 10 | 1506.392 |
| 120 | all outer | lag1 | -99.99% | -9.2661 | 48.79% | 8734 | 1.396 |
| 120 | all outer | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 120 | all outer | buy_hold | 397.18% | 1.6038 | 99.98% | 8 | 1826.388 |
| 240 | 2023 | B | -47.01% | -0.6350 | 59.71% | 1028 | 5.826 |
| 240 | 2023 | G | -33.28% | -0.4046 | 59.75% | 982 | 7.881 |
| 240 | 2023 | unconditional | 157.16% | 0.9445 | 99.95% | 2 | 3771.628 |
| 240 | 2023 | lag1 | -57.36% | -0.8523 | 47.42% | 1226 | 5.052 |
| 240 | 2023 | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 240 | 2023 | buy_hold | 157.16% | 0.9445 | 99.95% | 2 | 3771.628 |
| 240 | 2024+ | B | -90.35% | -2.3383 | 55.63% | 2892 | 3.919 |
| 240 | 2024+ | G | -87.01% | -2.0410 | 60.47% | 2492 | 3.814 |
| 240 | 2024+ | unconditional | 95.69% | 0.6714 | 99.95% | 6 | 1069.365 |
| 240 | 2024+ | lag1 | -95.29% | -3.0555 | 48.79% | 3230 | 2.545 |
| 240 | 2024+ | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 240 | 2024+ | buy_hold | 95.69% | 0.6714 | 99.95% | 6 | 1069.365 |
| 240 | all outer | B | -94.89% | -2.9734 | 56.71% | 3920 | 4.419 |
| 240 | all outer | G | -91.33% | -2.4456 | 60.28% | 3474 | 4.964 |
| 240 | all outer | unconditional | 403.25% | 1.6159 | 99.95% | 8 | 1838.775 |
| 240 | all outer | lag1 | -97.99% | -3.9078 | 48.42% | 4456 | 3.235 |
| 240 | all outer | cash | 0.00% | 0.0000 | 0.00% | 0 | — |
| 240 | all outer | buy_hold | 403.25% | 1.6159 | 99.95% | 8 | 1838.775 |

All returns use normalized spot long/cash equity, with no leverage, shorting,
borrowing, funding or cash yield. A signal can first execute at the next observed
opening after its source candle closes. Existing positions carry across missing
bars, with delayed assumed fills and gap marks recorded; future missing data
cannot trigger an anticipatory exit. Each year starts in cash and liquidates at
its last observed opening strictly before its end. Openings are execution
reference prices, not guaranteed obtainable fills.

### Cost sensitivity for the selected models

Cells show net compounded returns. Each column is a fixed fee+slippage scenario
in basis points per side. Every model, administrative control and scenario has
its exact metrics retained in the corresponding `economics` records; the
following table is a compact B/G comparison.

| Minutes | Period | Policy | 0+0 bps | 5+1 bps | 10+2 bps | 20+4 bps |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 2023 | B | 135.00% | -98.88% | -99.99% | -100.00% |
| 15 | 2023 | G | 164.88% | -98.62% | -99.99% | -100.00% |
| 15 | 2024+ | B | 373.25% | -100.00% | -100.00% | -100.00% |
| 15 | 2024+ | G | 313.26% | -100.00% | -100.00% | -100.00% |
| 15 | all outer | B | 1012.15% | -100.00% | -100.00% | -100.00% |
| 15 | all outer | G | 994.65% | -100.00% | -100.00% | -100.00% |
| 30 | 2023 | B | 113.89% | -98.84% | -99.99% | -100.00% |
| 30 | 2023 | G | 93.34% | -93.24% | -99.76% | -100.00% |
| 30 | 2024+ | B | 355.91% | -100.00% | -100.00% | -100.00% |
| 30 | 2024+ | G | 213.50% | -99.99% | -100.00% | -100.00% |
| 30 | all outer | B | 875.14% | -100.00% | -100.00% | -100.00% |
| 30 | all outer | G | 506.10% | -100.00% | -100.00% | -100.00% |
| 60 | 2023 | B | 90.33% | -63.94% | -93.17% | -99.76% |
| 60 | 2023 | G | 72.47% | -66.97% | -93.68% | -99.77% |
| 60 | 2024+ | B | 217.25% | -97.91% | -99.99% | -100.00% |
| 60 | 2024+ | G | 144.61% | -96.23% | -99.94% | -100.00% |
| 60 | all outer | B | 503.83% | -99.25% | -100.00% | -100.00% |
| 60 | all outer | G | 321.87% | -98.76% | -100.00% | -100.00% |
| 120 | 2023 | B | 28.13% | -68.12% | -92.07% | -99.51% |
| 120 | 2023 | G | 57.55% | -53.29% | -86.16% | -98.79% |
| 120 | 2024+ | B | 121.85% | -94.40% | -99.86% | -100.00% |
| 120 | 2024+ | G | 112.10% | -88.19% | -99.34% | -100.00% |
| 120 | all outer | B | 184.25% | -98.21% | -99.99% | -100.00% |
| 120 | all outer | G | 234.15% | -94.48% | -99.91% | -100.00% |
| 240 | 2023 | B | 82.04% | -1.77% | -47.01% | -84.59% |
| 240 | 2023 | G | 116.90% | 20.31% | -33.28% | -79.50% |
| 240 | 2024+ | B | 210.65% | -45.23% | -90.35% | -99.70% |
| 240 | 2024+ | G | 158.74% | -42.01% | -87.01% | -99.35% |
| 240 | all outer | B | 465.52% | -46.20% | -94.89% | -99.95% |
| 240 | all outer | G | 461.21% | -30.23% | -91.33% | -99.87% |

Annualized daily-log Sharpe, open-marked drawdown, gross return, trade summaries,
active days, cost drag, gaps and delayed changes remain in the retained metric
records. Full daily arrays, trades and observed-open traces are identified by
[retained-artifacts.json](retained-artifacts.json). Classification labels with
unavailable future rows never suppress an otherwise causal economic signal.

## Evidence, operational receipts and limitations

The collector checked all files against the producer manifest and required a
complete independent PASS before combining any outcome. The audit's own
coverage, numerical discrepancies and identities are preserved unchanged in
[verification.json](verification.json). [run.json](run.json) contains source,
code, runtime, command, process/thread and operational timing identities;
[features.json](features.json) binds the native feature input. These are
single-run operational receipts, not a matched benchmark or a speedup claim.

The producer command recorded for this run was:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/run_round1.py --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1a --protocol /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/round1a_protocol.json --freeze-commit 3df6416a2de59ac396617be49326a834c94aca92 --workers 5 --blas-threads 2
```

The five source histories and earlier results were already examined before this
round, including the predecessor [PR #22](https://github.com/mikkokotila/Filang/pull/22).
Nested temporal fitting prevents the declared inner/outer fitting leakage;
it does not create a fresh external holdout. The protocol was frozen at
`3df6416a2de59ac396617be49326a834c94aca92` before fitting or predictive evaluation. Native causal feature
preparation occurred earlier. This report follows the finite
[campaign](../../../experiments/geometry_information/CAMPAIGN.md) and retains
the frozen [protocol SHA-256](protocol.json): `cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34`.

The modeled projection uses additive current-to-prior endpoint relations. A
negative result does not rule out every possible geometry function, interaction
or conditional regime; a positive result is restricted to this finite family,
target and historical record. Predictive log-loss improvement is not a claim
about the exact information content of geometry. The p>=.5 diagnostic also
does not establish an optimal return policy: directional probabilities and
profit after transaction costs are different quantities.

The candles do not reconstruct spreads, order-book depth, market impact,
size-dependent capacity, sub-bar latency or intrabar drawdown. In particular,
2023's delayed-fill convention is a disclosed proxy for missing observations,
not evidence that trading was unavailable. Fixed costs are scenarios rather
than account-specific or historical fee claims.

## Empirical residue and next decision

The frozen information criterion is supported retrospectively at 30-minute resolution. This outcome fixes the scope of what this attempt established; it does
not authorize a revised criterion after seeing the tables. Compare the recorded
annual signs, uncertainty and primary-cost ledgers when deciding whether any
specific next hypothesis is justified. A favorable sensitivity alone cannot
promote an unsuccessful primary result.

Across all independently reset outer years, G has a positive primary-cost net log return at 0/5 timeframes, exceeds B at 4/5, and exceeds the buy-and-hold control at 0/5. At 5/5 timeframes its zero-cost net log return is positive but its primary-cost net log return is nonpositive. These are descriptive fixed-policy comparisons, without an economic selection or significance claim.

Any R2 must be separately frozen and remain inside the small economic-selection
budget recorded in the campaign. Retained inner-validation predictions allow
past-only policy selection; their own labels must never enter a model producing
those probabilities. R3 is limited to justified interpretable interactions.
Stop if no concrete residue supports a next hypothesis or the finite campaign
budget is exhausted. Fresh confirmation requires later, genuinely uninspected
observations, and a tradeability claim additionally requires execution evidence.

## Reproduction

Run from the repository root using Python 3.13.2 and the recorded implementation
identity. The freeze commit binds the scientific protocol; the run's code hashes
identify its implementation. A forensic replay of retained outputs requires the
completed PR #25 tree containing the final verifier and the
unchanged producer files whose hashes are in [run.json](run.json). A protocol
freeze commit alone may predate that implementation. A later campaign checkout
with modified producer files must not audit this run under different code.

The commands below use the recorded data and key roots, preserving paths that
may be outside this research checkout. The data themselves must match the
source and prepared-CSV hashes in [protocol.json](protocol.json). Paths can be
relocated only while retaining those exact input identities. These commands
reproduce work; do not execute them into an existing sealed run directory.
Native preparation uses `--resume true`: an existing completed key cache is
verified only when its source, context and executable identities match. The
exporter rejects mismatches instead of overwriting a sealed cache. Use the
recorded native executable for that check; if generating a new key cache,
choose an unused key root and pass that same root to the fresh runner. The
already sealed, matching key cache can also be reused directly by the runner
without executing native preparation again.

```sh
python3.13 -m venv .venv-information
.venv-information/bin/python -m pip install -r requirements-information.txt
export VECLIB_MAXIMUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
cargo build --release
target/release/filang geometry-key-export --data /Users/mikkokotila/dev/Filang-direction/data/geometry-direction/15m/ohlcv.csv --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1/15m --interval-seconds 900 --history-start 2020-01-01 --end 2026-10-08 --bars 10 --memory-mib 256 --max-rows 2000000 --resume true
target/release/filang geometry-key-export --data /Users/mikkokotila/dev/Filang-direction/data/geometry-direction/30m/ohlcv.csv --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1/30m --interval-seconds 1800 --history-start 2020-01-01 --end 2026-10-08 --bars 10 --memory-mib 256 --max-rows 2000000 --resume true
target/release/filang geometry-key-export --data /Users/mikkokotila/dev/Filang-direction/data/geometry-direction/60m/ohlcv.csv --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1/60m --interval-seconds 3600 --history-start 2020-01-01 --end 2026-10-08 --bars 10 --memory-mib 256 --max-rows 2000000 --resume true
target/release/filang geometry-key-export --data /Users/mikkokotila/dev/Filang-direction/data/geometry-direction/120m/ohlcv.csv --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1/120m --interval-seconds 7200 --history-start 2020-01-01 --end 2026-10-08 --bars 10 --memory-mib 256 --max-rows 2000000 --resume true
target/release/filang geometry-key-export --data /Users/mikkokotila/dev/Filang-direction/data/geometry-direction/240m/ohlcv.csv --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1/240m --interval-seconds 14400 --history-start 2020-01-01 --end 2026-10-08 --bars 10 --memory-mib 256 --max-rows 2000000 --resume true
.venv-information/bin/python experiments/geometry_information/run_round1.py --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --out runs/geometry-information-r1a --protocol experiments/geometry_information/round1a_protocol.json --freeze-commit 3df6416a2de59ac396617be49326a834c94aca92 --workers 5 --blas-threads 2
```

The original recorded command is preserved above and in
[reproduction.json](reproduction.json). The fresh-run example uses the registered
`geometry-information-r1a` directory; choose an unused output location when repeating
the computation. Match the recorded native engine identity when reproducing
feature artifacts. Thread/process controls are operational receipts, not
scientific selection axes.

Audit and collect the retained original run without refitting:

```sh
.venv-information/bin/python experiments/geometry_information/verify_round1.py --stage full --run /Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1a --keys-root /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --protocol experiments/geometry_information/round1a_protocol.json --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1a/verification.json
.venv-information/bin/python experiments/geometry_information/collect_round1.py --run /Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1a --out benchmarks/reports/20261008-geometry-information-r1a
```

The exact scientific identity is
`round1a_protocol.json@3df6416a2de59ac396617be49326a834c94aca92`, protocol SHA-256
`cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34`. The collector admits only its pinned registry
entry, requires its exact declared amendment record and no deviations, and
cannot promote a partial or failed-stage audit to full scientific PASS.

Large source-row predictions and complete economic traces remain in the sealed
run. [Retained-artifact identities](retained-artifacts.json) bind their relative
paths, lengths and digests. This package preserves compact files byte for byte;
its separate [manifest](manifest.json) seals the copies and generated report
without changing the original producer manifest.


## Bibliography

- [Binance official trading-fee schedule](https://www.binance.com/en/fee/trading).
  The experiment's fee/slippage values are fixed scenarios, not a claim about
  an account's effective or historical fees.
- [Bailey et al., *The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
  Background reading on repeated historical research; this report makes no new
  empirical claim from that paper.

## External operational receipts

- [operational/launcher.json](operational/launcher.json) — successful producer launcher.
- [operational/execution.log](operational/execution.log) — producer execution log.
- [operational/audit/geometry-information-r1a-verification.log](operational/audit/geometry-information-r1a-verification.log) — external audit-development or execution receipt.

These exact-byte receipts are archived only in this report package. The launcher, when supplied, matches the recorded producer command, successful exit and positive duration. They are not added to the sealed run or represented as files in its original producer manifest. Scientific audit coverage remains defined by verification.json.
