# R2: qualitative geometry and cost-aware conditional payoffs

The frozen R2 economic criterion is **not-supported at all five timeframes** after a complete independent audit. This is retrospective evidence under the specified OHLC execution proxy; it does not establish a live trading edge or superiority to passive Bitcoin ownership.

This report joins the unchanged producer [analysis](analysis.json) to the later [full independent audit](verification.json). The producer remains `COMPLETE_PENDING_INDEPENDENT_AUDIT`, with conditional outcomes, by design. The collector does not fit models, select policies, replay accounts or overwrite the source run. All five timeframes, including cash selections and unfavorable results, are retained.

## Frozen claim and method

R2 asks whether additive bar geometry beyond sign history provides both a positive net payoff and an incremental payoff over the sign-history baseline after declared transaction costs. B uses body and close-return direction indicators. G adds current-to-prior endpoint comparisons and wick presence. Both use the same native ten-bar causal geometry keys; n∈{2,3,5,10} selects a projection of those keys. U predicts the fitting-sample mean log return. No volume, absolute price or numeric return magnitude enters B or G as a feature.

The target is `log(O[t+2]/O[t+1])`, including exact zero returns. The forecast horizon runs from the next opening to the following opening. A policy uses candle t only after its close and executes its requested exposure at the next observed opening; stateful policies may remain long across multiple forecast horizons. Model scoring requires contiguous n10 history and two subsequent bars, candle t opening in its phase, and the exit opening strictly before the phase cutoff. Causal forecasts also cover valid final and pre-gap feature rows lacking future labels; future label availability never suppresses a trading request.

The four outer periods are 2023, 2024, 2025 and 2026 through October 7. Each has the previous calendar year for inner validation and earlier history starting January 2020 for inner training. For B and G independently, validation MSE selects n and λ∈{0.1,0.01,0.001,0.0001} for an unscaled ridge regression with an unpenalized intercept. The selected model is then refit on all data strictly before the outer year. Positive penalties make the centered normal equations well-defined; every fit must pass the frozen direct-gradient acceptance check.

Each selected inner B/G/U model evaluates seven validation policies at primary costs: cash, or entry multiples {0,0.5,1} crossed with exit multiples {−0.5,0} of the primary round-trip log-cost hurdle. A cash account enters when score ≥ entry; a long account stays long when score ≥ exit. Otherwise it requests cash. NaN requests cash. When exit < entry, a score equal to exit preserves the current position; scores at or above entry request long. There is no sigmoid and these are signed return forecasts, not probabilities. Policy selection uses validation total net log return, with the frozen cash/turnover/threshold/id tie order. All selected refits are retained even when cash wins.

Primary fees and slippage are **10+2 bps per side**. Zero (0+0), reduced (5+1), and stress (20+4) scenarios reuse the same primary-selected model, thresholds and position requests. These are declared scenarios, not a claim about an account's actual fees. Buy-and-hold and cash use the same administrative annual reset and terminal liquidation rules. All accounting retains observed gaps, applies pending requests at the next observed opening, and never exits in anticipation of a future gap.

## Primary paired results

Effects are **mean daily net-log-return differences**, with all calendar days including inactive days and equal daily weight. Brackets show each comparison's individual seven-day circular moving-block-bootstrap 95% interval. These two intervals are **not** a joint simultaneous 95% confidence region. The composite one-sided p is the larger of the two component p-values; Holm correction applies to those five timeframe composites. Summary results for all three block lengths are preserved in [primary-and-sensitivity.csv](primary-and-sensitivity.csv). All 2,000 ordinary and centered replicas per setting remain in the indexed external bootstrap bundles.

| Minutes | G−B/day [95% CI] | G−cash/day [95% CI] | p G−B | p G−cash | Composite p Holm | Audited outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 0.00000000 [0.00000000, 0.00000000] | 0.00052126 [-0.00037617, 0.00139019] | 1.000000 | 0.126437 | 1.000000 | not-supported |
| 30 | -0.00000115 [-0.00000346, 0.00000000] | 0.00052010 [-0.00038954, 0.00139923] | 0.902049 | 0.131934 | 1.000000 | not-supported |
| 60 | 0.00000000 [0.00000000, 0.00000000] | 0.00051912 [-0.00039044, 0.00139443] | 1.000000 | 0.122439 | 1.000000 | not-supported |
| 120 | -0.00002802 [-0.00008203, 0.00003090] | 0.00050095 [-0.00040375, 0.00140747] | 0.831084 | 0.137431 | 1.000000 | not-supported |
| 240 | 0.00000752 [-0.00007689, 0.00008232] | 0.00052711 [-0.00033719, 0.00140961] | 0.449775 | 0.122439 | 1.000000 | not-supported |

Every success condition must hold. The annual condition requires the **same** three or more outer years to have both positive effects; twenty completed G round trips is an activity requirement, not an effective sample size or proof of independent trades.

| Minutes | Both gains >0 | Both CI lower >0 | Holm <.05 | Same ≥3 years | ≥20 G trades | Same positive years | G trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | no | no | no | no | no | 0 | 2 |
| 30 | no | no | no | no | no | 0 | 2 |
| 60 | no | no | no | no | no | 0 | 2 |
| 120 | no | no | no | no | no | 0 | 17 |
| 240 | yes | no | no | no | no | 1 | 2 |

## Bootstrap arithmetic audit

The first audit attempt stopped at a bootstrap tail-count discrepancy. That failed audit is preserved as audit-development history; it is not erased or treated as another market-model attempt. The preserved audit-development attachments are archived byte-for-byte in this package: [geometry-payoff-r2-audit-v2.json](operational/audit/geometry-payoff-r2-audit-v2.json), [geometry-payoff-r2-verification-v2.log](operational/audit/geometry-payoff-r2-verification-v2.log), [geometry-payoff-r2-verification.log](operational/audit/geometry-payoff-r2-verification.log), [receipt.json](operational/audit/receipt.json), [test_verify_round2.py](operational/audit/test_verify_round2.py), [verify_round2.py](operational/audit/verify_round2.py).

The final audit uses the same two-stage method for **all thirty cases** (five timeframes × three block lengths × two contrasts). First, it independently reconstructs raw cash/share daily effects and checks every ordinary and centered bootstrap replica with the unchanged absolute-plus-relative numerical tolerance of `1e-10`. Second, it reconstructs the committed two-column reduction from the already-audited retained daily values, then applies the frozen **literal `>=`** predicate to the sealed centered float64 replicas. The retained integer tail count must give exactly the p-value in `analysis.json` through `(1 + count) / 2001`.

Numerically close continuous replicas need not give identical discrete tail decisions at an equality boundary. There is **no generic claim of raw-account oracle p-value agreement**. No predicate epsilon was introduced, no existing numeric tolerance was changed, and no producer, protocol, observations, bootstrap draws or model/policy selections were changed. The following table includes only cases with differing tail decisions or p-values; all thirty diagnostics, observed effects, signed nearest margins and retained-arithmetic errors are in [verification.json](verification.json).

| Minutes | Block days | Comparison | Raw-account oracle p (diagnostic) | Retained literal p | Predicate disagreements / exact margins | Min absolute margin / max centered error | Algebraic atom p (diagnostic) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 1 | G_minus_B | 0.745127436 | 0.902548726 | 315 / 0 | 2.117582e-22 / 4.794206e-19 | 0.920539730 (1 nonzero days) |
| 30 | 7 | G_minus_B | 0.737631184 | 0.902048976 | 329 / 0 | 2.117582e-22 / 3.930233e-19 | 0.927036482 (1 nonzero days) |
| 30 | 28 | G_minus_B | 0.773613193 | 0.912543728 | 278 / 0 | 2.117582e-22 / 4.743385e-19 | 0.934532734 (1 nonzero days) |

Here the margin is `retained_centered_replica − retained_observed_effect`; exact margins count literal zero differences. The error column is the largest absolute difference between independently replayed and retained centered replicas. With one nonzero daily effect `a`, the extra algebraic diagnostic counts `m*a >= 2*a` using the sampled multiplicity `m`; with no nonzero days its algebraic tail probability is one. These diagnostic p-values expose the equality mass and arithmetic sensitivity. They are **not replacement or corrected mathematical p-values** for the frozen retained-array result, and they are never used for promotion. All five timeframes independently fail the minimum-twenty-completed-G-trades condition. Changing which diagnostic p-value is displayed cannot make the frozen joint criterion pass.


## Annual effects and frozen choices

Annual effects below are total net log returns at primary costs. Policy ids encode entry/exit multiples (`xm05` means −0.5); full numeric thresholds and every losing or cash validation trial remain in each timeframe's `selections.jsonl` and `ledgers.jsonl`. [model-policy-choices.csv](model-policy-choices.csv) provides all sixty choices; [prediction-scores.csv](prediction-scores.csv) includes validation and outer B/G/U MSE, true zero counts and the remaining recorded score summaries.

| Minutes | Outer year | G−B log | G−cash log | B model; policy | G model; policy | U; policy |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=10, λ=0.1; cash | mean; cash |
| 15 | 2024 | 0.000000 | 0.787340 | n=10, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 15 | 2025 | 0.000000 | -0.070087 | n=2, λ=0.1; e0_xm05 | n=3, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 15 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 30 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=5, λ=0.1; cash | mean; cash |
| 30 | 2024 | -0.001587 | 0.785856 | n=5, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 30 | 2025 | 0.000000 | -0.070200 | n=10, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 30 | 2026 | 0.000000 | 0.000000 | n=3, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 60 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=3, λ=0.1; cash | mean; cash |
| 60 | 2024 | 0.000000 | 0.784031 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 60 | 2025 | 0.000000 | -0.069727 | n=10, λ=0.01; e0_xm05 | n=2, λ=0.01; e0_xm05 | mean; e0_xm05 |
| 60 | 2026 | 0.000000 | 0.000000 | n=3, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 120 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 120 | 2024 | -0.036104 | 0.758214 | n=10, λ=0.1; e0_xm05 | n=10, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 120 | 2025 | -0.002457 | -0.068910 | n=10, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 120 | 2026 | 0.000000 | 0.000000 | n=3, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 240 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 240 | 2024 | 0.003819 | 0.797160 | n=5, λ=0.0001; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 240 | 2025 | 0.006535 | -0.071854 | n=10, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 240 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; e05_x0 | mean; cash |

## Primary-cost account outcomes and controls

All-outer figures compound the separately reset annual accounts. Turnover counts one-way changes of full account exposure; completed trades include prescribed terminal liquidations. Break-even is the symmetric per-side cost implied by the realized gross path and turnover, and is undefined when there is no turnover. It is not a predicted executable allowance. Drawdown and all return/risk metrics are descriptive.

| Minutes | Family | Net return | Net log | Gross return | Max drawdown | Exposure | One-way turnover | Trades | Break-even bps/side |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | B | 104.88% | 0.717253 | 105.87% | 35.76% | 53.12% | 4 | 2 | 1651.588 |
| 15 | G | 104.88% | 0.717253 | 105.87% | 35.76% | 53.12% | 4 | 2 | 1651.588 |
| 15 | U | 105.03% | 0.717964 | 106.01% | 35.76% | 53.12% | 4 | 2 | 1653.071 |
| 15 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 15 | buy_hold | 395.51% | 1.600415 | 400.29% | 53.98% | 100.00% | 8 | 4 | 1822.939 |
| 30 | B | 104.88% | 0.717243 | 105.86% | 35.76% | 53.11% | 4 | 2 | 1651.567 |
| 30 | G | 104.55% | 0.715656 | 105.54% | 35.76% | 53.11% | 4 | 2 | 1648.255 |
| 30 | U | 105.63% | 0.720897 | 106.62% | 35.76% | 53.12% | 4 | 2 | 1659.190 |
| 30 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 30 | buy_hold | 395.56% | 1.600512 | 400.34% | 53.90% | 99.99% | 8 | 4 | 1823.039 |
| 60 | B | 104.28% | 0.714304 | 105.26% | 34.76% | 53.10% | 4 | 2 | 1645.431 |
| 60 | G | 104.28% | 0.714304 | 105.26% | 34.76% | 53.10% | 4 | 2 | 1645.431 |
| 60 | U | 103.56% | 0.710810 | 104.54% | 34.76% | 53.12% | 4 | 2 | 1638.131 |
| 60 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 60 | buy_hold | 390.88% | 1.591039 | 395.62% | 53.89% | 99.99% | 8 | 4 | 1813.351 |
| 120 | B | 107.07% | 0.727865 | 108.06% | 34.45% | 53.11% | 4 | 2 | 1673.707 |
| 120 | G | 99.23% | 0.689303 | 107.53% | 34.45% | 52.89% | 34 | 17 | 212.452 |
| 120 | U | 105.69% | 0.721200 | 106.68% | 34.45% | 53.11% | 4 | 2 | 1659.822 |
| 120 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 120 | buy_hold | 397.18% | 1.603790 | 401.98% | 53.72% | 99.98% | 8 | 4 | 1826.388 |
| 240 | B | 104.41% | 0.714952 | 121.80% | 33.58% | 52.46% | 68 | 34 | 116.462 |
| 240 | G | 106.54% | 0.725305 | 107.53% | 34.37% | 53.10% | 4 | 2 | 1668.377 |
| 240 | U | 106.54% | 0.725305 | 107.53% | 34.37% | 53.10% | 4 | 2 | 1668.377 |
| 240 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 240 | buy_hold | 403.25% | 1.615922 | 408.11% | 53.72% | 99.95% | 8 | 4 | 1838.775 |

The 2023 source gap is reported separately. The 2024+ column concatenates independently reset 2024, 2025 and partial-2026 accounts; it does not carry positions across annual boundaries. Gap mark and delayed-exposure counts expose the next-observed-open fill assumption.

| Minutes | Family | 2023 net return | 2023 gaps | Gap gross log | Delayed changes | 2024+ net return |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | G | 0.00% | 1 | 0.000000 | 0 | 104.88% |
| 15 | B | 0.00% | 1 | 0.000000 | 0 | 104.88% |
| 15 | U | 0.00% | 1 | 0.000000 | 0 | 105.03% |
| 15 | buy_hold | 155.06% | 1 | 0.001176 | 0 | 94.27% |
| 30 | G | 0.00% | 1 | 0.000000 | 0 | 104.55% |
| 30 | B | 0.00% | 1 | 0.000000 | 0 | 104.88% |
| 30 | U | 0.00% | 1 | 0.000000 | 0 | 105.63% |
| 30 | buy_hold | 154.35% | 1 | 0.001436 | 0 | 94.83% |
| 60 | G | 0.00% | 1 | 0.000000 | 0 | 104.28% |
| 60 | B | 0.00% | 1 | 0.000000 | 0 | 104.28% |
| 60 | U | 0.00% | 1 | 0.000000 | 0 | 103.56% |
| 60 | buy_hold | 155.04% | 1 | 0.001436 | 0 | 92.48% |
| 120 | G | 0.00% | 1 | 0.000000 | 0 | 99.23% |
| 120 | B | 0.00% | 1 | 0.000000 | 0 | 107.07% |
| 120 | U | 0.00% | 1 | 0.000000 | 0 | 105.69% |
| 120 | buy_hold | 156.28% | 1 | 0.001386 | 0 | 94.00% |
| 240 | G | 0.00% | 0 | 0.000000 | 0 | 106.54% |
| 240 | B | 0.00% | 0 | 0.000000 | 0 | 104.41% |
| 240 | U | 0.00% | 0 | 0.000000 | 0 | 106.54% |
| 240 | buy_hold | 157.16% | 0 | 0.000000 | 0 | 95.69% |

## Cost sensitivity without re-selection

| Minutes | Scenario | B net return | G net return | U net return | Cash net return | Buy-hold net return |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | zero | 105.87% | 105.87% | 106.01% | 0.00% | 400.29% |
| 15 | reduced | 105.37% | 105.37% | 105.52% | 0.00% | 397.89% |
| 15 | primary | 104.88% | 104.88% | 105.03% | 0.00% | 395.51% |
| 15 | stress | 103.90% | 103.90% | 104.04% | 0.00% | 390.77% |
| 30 | zero | 105.86% | 105.54% | 106.62% | 0.00% | 400.34% |
| 30 | reduced | 105.37% | 105.04% | 106.12% | 0.00% | 397.94% |
| 30 | primary | 104.88% | 104.55% | 105.63% | 0.00% | 395.56% |
| 30 | stress | 103.90% | 103.57% | 104.64% | 0.00% | 390.82% |
| 60 | zero | 105.26% | 105.26% | 104.54% | 0.00% | 395.62% |
| 60 | reduced | 104.77% | 104.77% | 104.05% | 0.00% | 393.25% |
| 60 | primary | 104.28% | 104.28% | 103.56% | 0.00% | 390.88% |
| 60 | stress | 103.30% | 103.30% | 102.59% | 0.00% | 386.19% |
| 120 | zero | 108.06% | 107.53% | 106.68% | 0.00% | 401.98% |
| 120 | reduced | 107.56% | 103.34% | 106.18% | 0.00% | 399.58% |
| 120 | primary | 107.07% | 99.23% | 105.69% | 0.00% | 397.18% |
| 120 | stress | 106.07% | 91.26% | 104.70% | 0.00% | 392.43% |
| 240 | zero | 121.80% | 107.53% | 107.53% | 0.00% | 408.11% |
| 240 | reduced | 112.93% | 107.03% | 107.03% | 0.00% | 405.68% |
| 240 | primary | 104.41% | 106.54% | 106.54% | 0.00% | 403.25% |
| 240 | stress | 88.37% | 105.55% | 105.55% | 0.00% | 398.44% |

[economics.csv](economics.csv) retains every annual and aggregate cost/control result, including gross and net returns, cost drag, exposure, turnover, drawdown, trade counts, gaps, and annualized descriptive metrics. The 1- and 28-day block checks do not add another route to success or alter the primary criterion.

## Evidence, execution and reproduction

The exact [protocol](protocol.json) was published at freeze commit `9489c22556898603268fbad9124e0268f0d99852` with SHA-256 `40162d6e1a6ced930bb8c8cfb578f6d9eb4935b7f2ef4ae37a363dc75e52d11d`. The five immutable source snapshots and prepared CSV identities are in [provenance.json](provenance.json) and the protocol: 459,503 source rows, January 2020 through October 7, 2026. The common native export contains 458,972 causal ten-bar keys. The source and feature hashes, all runtime/package/thread settings, and implementation identity are retained in [run.json](run.json), [features.json](features.json), and the native preparation receipts.

The [full audit](verification.json) covers 640 candidate fits, 40 refits, 60 policy choices, all 40 prediction phases, 420 validation ledgers and 400 outer ledgers. Its largest recorded numeric comparison error is `2.128217602148652e-10`. All coefficient, objective, direct-gradient, validation-MSE and model/threshold choice records remain in five `fits.jsonl`/`selections.jsonl` groups. No optimizer is run by the collector. The audit independently reconstructs targets, forecasts and signed-score cash/share accounting and verifies the complete array census.

The external launcher records exit 0 and 67.952530 seconds. These are operational receipts, not a matched performance benchmark or a compute-ceiling claim. External launcher and audit logs, if supplied, live under `operational/` in this report and remain outside the sealed producer run.

The [producer manifest](producer-manifest.json) and its seal preserve the original artifact identities. The separate [report manifest](manifest.json) seals this compact package. [retained-artifacts.json](retained-artifacts.json) records all externally retained large files: twenty annual numeric bundles and five bootstrap bundles (257,163,459 bytes), plus native key payloads. Each timeframe's `arrays.json` retains every member's dtype, shape and digest. These bundles are required for a full replay; their omission from Git is a packaging choice, not reduced audit scope. The package contains 85 files including its own manifest and seal.

Use the completed PR26 tree containing the final verifier and exactly the producer file hashes in `run.json`. Later edits to producer computational files will fail identity checks when replaying this original run. Install `requirements-information.txt` with the recorded Python/package environment. Reuse the sealed native keys at the recorded key directory; preparing keys again is unnecessary. The original producer invocation, retained verbatim as arguments, was:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/run_round2.py --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --out /Users/mikkokotila/dev/Filang-research/runs/geometry-payoff-r2 --protocol /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/round2_protocol.json --freeze-commit 9489c22556898603268fbad9124e0268f0d99852 --workers 5 --blas-threads 2
```

Re-execution requires a **new unused `--out` directory**, the frozen protocol/freeze pair above, identical pinned inputs and the recorded implementation. The producer refuses to resume or overwrite a completed attempt. To audit the original retained run and collect it:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python -m pip install -r requirements-information.txt
/Users/mikkokotila/dev/Filang-research/.venv/bin/python experiments/geometry_information/verify_round2.py --stage full --run /Users/mikkokotila/dev/Filang-research/runs/geometry-payoff-r2 --keys-root /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --protocol experiments/geometry_information/round2_protocol.json --out /Users/mikkokotila/dev/Filang-research/runs/geometry-payoff-r2/verification.json
/Users/mikkokotila/dev/Filang-research/.venv/bin/python experiments/geometry_information/collect_round2.py --run /Users/mikkokotila/dev/Filang-research/runs/geometry-payoff-r2 --out benchmarks/reports/20261008-geometry-payoff-r2
```

Supply optional `--launcher /path/to/external-launch.json` and repeatable `--audit-receipt /path/to/external-audit.log` to archive operational evidence. Those files must stay outside the sealed run. A report destination already containing different evidence is rejected.

## Empirical residue and limits

At primary costs, G has a positive all-outer net log return in 5 of five timeframes; its inner selector chooses cash in 9 of twenty timeframe/year cases. The complete joint criterion is supported in 0 of five timeframes. These counts describe this audited attempt and do not authorize selecting an outer winner after inspection or changing thresholds to improve the result.

R2 follows the [exact-pattern predecessor](../20261008-bitcoin-direction/README.md), the retained [R1 numerical failure](../20261008-geometry-information-r1-failed/README.md), and the [R1a information experiment](../20261008-geometry-information-r1a/README.md). All historical observations and prior outcomes were exposed before R2. Nesting controls which rows enter each fit and selector; it does not make those historical observations fresh. An earlier outer year may enter a later fold's fitting history under the explicit frozen schedule. Bootstrap uncertainty is conditional on the declared procedure and does not erase adaptive campaign history.

This finite additive/current-to-prior geometry projection and seven-policy family cannot exhaust all geometric functions. A not-supported result is not proof that geometry contains zero information; a supported result is not a live-edge guarantee. Execution uses OHLC openings with prescribed fees, slippage and delayed gap fills; there are no quotes, order-book depth, latency, market impact, financing, custody, taxes or real orders. Buy-and-hold is a descriptive control rather than a primary superiority test. The remaining campaign budget permits only a separately justified, frozen limited-interaction round, followed by stopping if the declared evidence does not support an edge. Any eventual tradeability claim needs separately frozen future data and execution evidence.

Bibliography: [declared fee-scenario reference](https://www.binance.com/en/fee/trading); [backtest-overfitting research](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). These links provide context and do not substitute for the frozen protocol or measured artifacts.
