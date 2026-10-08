# R3: fixed qualitative interactions beyond additive geometry

The frozen R3 criterion is **not-supported in all five timeframes**. These outcomes follow a full independent audit of the complete attempt. They are retrospective evidence under the declared OHLC execution proxy, not a live trading-edge claim or proof of outperformance against passive Bitcoin ownership. **R3 completes the campaign's third and final hypothesis family.**

The unchanged producer [analysis](analysis.json) remains `COMPLETE_PENDING_INDEPENDENT_AUDIT` with conditional outcomes. This report joins it to the later [full independent audit](verification.json); the collector does not refit models, select policies or mutate producer files. Every timeframe, annual fold, cash choice and cost/control result is retained.

## Controlled feature change

A is exactly the additive geometry feature basis called G in R2, fitted freshly in R3. I contains A and one fixed 225-column block for the **current and immediately prior candle only**. The block contains 75 body-interval weak orders and 150 full low-to-high range weak orders, each conditioned on both body directions. It uses only native endpoint ranks and orientation. Each row activates exactly one body entry and one range entry.

| History | A columns | I columns |
| --- | --- | --- |
| 2 | 42 | 267 |
| 3 | 80 | 305 |
| 5 | 156 | 381 |
| 10 | 346 | 571 |

Two intervals allowing points have 26 possible weak orders: 13 proper/proper, five point/proper, five proper/point and three point/point. Body intervals are points exactly when their direction is flat, giving `4×13 + 4×5 + 3 = 75` conditioned entries. Flat bodies may still have proper full ranges, giving `4×13 + 4×18 + 26 = 150` range entries. The exact [catalogue](catalogue.json), SHA-256 `dca090d73c32419bc525b71101f6cf0b584b1c8b91cf79808d4ed2f5d710bcdb`, is fixed by mathematical admissibility. Exhaustive synthetic enumeration covers all 7,452 oriented two-bar states and reaches every declared column. Market-zero-support columns remain present.

There is no learned vocabulary, arbitrary reference-column removal, extra direction-pair block, body-by-range crossing or added interaction with older lags. Longer histories enlarge only A. The complete one-hot groups share direction-pair spans and overlap with A and the intercept. Positive ridge penalties make the fitted solution unique, but this declared redundant basis changes effective shrinkage. The hypothesis concerns the **entire richer pipeline**; it does not isolate wick information or compare equal parameter capacity.

## Frozen model, policy and execution contract

The five pinned source series span January 2020 through October 7, 2026. Four outer folds cover 2023, 2024, 2025 and partial 2026. Each uses the prior calendar year for inner validation and earlier history for inner training, then refits the selected model on all admissible pre-outer data. An earlier outer year may enter a later fold's fitting history under that frozen schedule. Nothing from R2's coefficients, policies, scores, predictions or return statistics substitutes for a fresh R3 fit.

The target is `log(O[t+2]/O[t+1])`, retaining exact zero returns. All candidates share causal ten-bar eligibility. Scored candle t must open in its phase, have two consecutive subsequent bars, and exit strictly before the phase cutoff. Causal predictions also cover valid final and pre-gap feature rows without future labels. The ridge objective is mean squared error divided by two plus `λ·sum(beta²)/2`, with unpenalized intercept, unscaled fixed binary features, n∈{2,3,5,10} and λ∈{0.1,0.01,0.001,0.0001}. Inner MSE selects each A/I model; the predeclared tie order and direct-gradient acceptance rule apply to every fit. U is the contemporaneous fitting-sample mean return.

Inner validation chooses one of seven policies independently for A, I and U: cash, or entry multiples {0,0.5,1} crossed with exit multiples {−0.5,0} of the primary round-trip log-cost hurdle. It maximizes validation net log return with the frozen cash/turnover/threshold/id tie order. While cash, enter when the signed forecast is at least the entry threshold; while long, remain long when it is at least the exit threshold. When exit < entry, equality at exit preserves current state. NaN requests cash. These are conditional return forecasts, not probabilities, and positions may span multiple forecast horizons.

Primary fees/slippage are **10+2 bps per side**; zero (0+0), reduced (5+1) and stress (20+4) scenarios reuse the same selected model, primary-cost thresholds and request path. They are declared scenarios, not account-specific fee evidence. A completed candle's request executes only at the next observed opening. Existing positions are marked through source gaps; no future gap triggers an anticipatory exit. Every annual phase starts in cash, imports no earlier pending request, and liquidates at its prescribed terminal opening. Cash and buy-and-hold use the same administrative boundaries.

## Primary paired results

Effects are mean daily net-log-return differences, equally weighted across every calendar day including inactive days. Brackets are individual seven-day moving-block-bootstrap 95% intervals, **not a joint simultaneous 95% region**. Both positive effects, both positive interval lower endpoints, composite Holm p<.05 across five timeframes, at least three of the same four positive years, and twenty completed I trades are mandatory. The activity count is not an effective sample size or proof of independent trades.

| Minutes | I−A/day [95% CI] | I−cash/day [95% CI] | Exact p I−A | Exact p I−cash | Composite p Holm | Audited outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 0.00000000 [0.00000000, 0.00000000] | 0.00052126 [-0.00037617, 0.00139019] | 1.000000000 | 0.126436782 | 1.000000000 | not-supported |
| 30 | 0.00000000 [0.00000000, 0.00000000] | 0.00052010 [-0.00038954, 0.00139923] | 1.000000000 | 0.131934033 | 1.000000000 | not-supported |
| 60 | -0.00000006 [-0.00001304, 0.00001287] | 0.00051906 [-0.00039047, 0.00139436] | 0.637681159 | 0.122938531 | 1.000000000 | not-supported |
| 120 | 0.00002624 [-0.00003237, 0.00007947] | 0.00052719 [-0.00037407, 0.00143195] | 0.182908546 | 0.124437781 | 0.914542729 | not-supported |
| 240 | -0.00010857 [-0.00018870, -0.00004507] | 0.00041854 [-0.00043926, 0.00129504] | 0.993503248 | 0.169415292 | 1.000000000 | not-supported |

| Minutes | Both gains >0 | Both CI lower >0 | Holm <.05 | Same ≥3 years | ≥20 I trades | Same positive years | I trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | no | no | no | no | no | 0 | 2 |
| 30 | no | no | no | no | no | 0 | 2 |
| 60 | no | no | no | no | no | 1 | 2 |
| 120 | yes | no | no | no | no | 1 | 2 |
| 240 | no | no | no | no | yes | 0 | 26 |

## Exact bootstrap tail arithmetic

All thirty cases use 2,000 shared-draw replicas: five timeframes × three block lengths × two comparisons. For each executed binary64 daily contrast, its exact binary-rational value is encoded with a common power-of-two denominator. Let S be the exact original numerator sum and T the sum under a replica's integer sampling multiplicities. Every replicate contains the same total number N of calendar days, so the centered one-sided event `(T−S)/N >= S/N` is exactly **T≥2S**. Signed integer arithmetic decides the event, includes equality, and uses no epsilon, padding or float-tail substitution. The recorded p is `(1 + exact true events) / 2001`; the timeframe composite takes the maximum of its two p-values before Holm adjustment.

Each timeframe's `bootstrap-exact.json` retains all decimal numerators, denominator exponents, fold lengths, pooled sums and canonical hashes. Its external `bootstrap.npz` retains ordinary and centered float64 arrays and all boolean exact-hit arrays. The full audit independently checks all five encodings and **60,000 exact tail bits**, then every exact count, p, composite, adjusted p and success condition. The collector also binds the compact integer sums/hashes and retained hit counts directly to the unchanged analysis and audit receipt. This is the separately declared R3 definition, not the R2 floating-tail audit workaround.

Observed means and percentile confidence intervals remain the declared binary64 calculations; centered float replicas are diagnostic. Exact integer tails remove summation ambiguity only for the executed binary64 daily contrasts. They do not make the economic account exact real arithmetic, require an approximately replayed account to have identical discontinuous decisions, or turn previously inspected history into fresh evidence. [primary-and-sensitivity.csv](primary-and-sensitivity.csv) contains aggregate summaries for 7-, 1- and 28-day blocks. Complete replica arrays remain in the sealed external bundles indexed by each `arrays.json`. Sensitivity blocks add no alternative route to success.

## Annual outcomes and all frozen choices

Annual effects are total net log returns at primary costs. Policy ids encode the entry/exit multiples (`xm05` means −0.5); full numeric thresholds, all seven trials and selected model identities remain in `selections.jsonl` and `ledgers.jsonl`. [model-policy-choices.csv](model-policy-choices.csv) lists all sixty choices. [prediction-scores.csv](prediction-scores.csv) includes both phases' A/I/U MSE and zero-target counts.

| Minutes | Year | I−A log | I−cash log | A model; policy | I model; policy | U; policy |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 2023 | 0.000000 | 0.000000 | n=10, λ=0.1; cash | n=10, λ=0.1; cash | mean; cash |
| 15 | 2024 | 0.000000 | 0.787340 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 15 | 2025 | 0.000000 | -0.070087 | n=3, λ=0.1; e0_xm05 | n=3, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 15 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 30 | 2023 | 0.000000 | 0.000000 | n=5, λ=0.1; cash | n=5, λ=0.1; cash | mean; cash |
| 30 | 2024 | 0.000000 | 0.785856 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 30 | 2025 | 0.000000 | -0.070200 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 30 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 60 | 2023 | 0.000000 | 0.000000 | n=3, λ=0.1; cash | n=3, λ=0.1; cash | mean; cash |
| 60 | 2024 | 0.005902 | 0.789933 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 60 | 2025 | -0.005983 | -0.075710 | n=2, λ=0.01; e0_xm05 | n=3, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 60 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 120 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 120 | 2024 | 0.036104 | 0.794318 | n=10, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 120 | 2025 | 0.000000 | -0.068910 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 120 | 2026 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.1; cash | mean; cash |
| 240 | 2023 | 0.000000 | 0.000000 | n=2, λ=0.1; cash | n=2, λ=0.01; cash | mean; cash |
| 240 | 2024 | -0.149784 | 0.647375 | n=2, λ=0.1; e0_xm05 | n=3, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 240 | 2025 | 0.004201 | -0.067653 | n=2, λ=0.1; e0_xm05 | n=2, λ=0.1; e0_xm05 | mean; e0_xm05 |
| 240 | 2026 | -0.003813 | -0.003813 | n=2, λ=0.1; e05_x0 | n=2, λ=0.1; e05_x0 | mean; cash |

## Primary costs and descriptive controls

The aggregate concatenates separately reset annual accounts. Turnover is one-way full-account exposure changes; completed trades include terminal liquidations. The break-even cost is implied by the realized gross path and turnover and is undefined without turnover. It is not a promised executable allowance. Return, drawdown and other risk measures are descriptive. U and buy-and-hold remain controls; the primary success rule does not test superiority against either.

| Minutes | Family | Net return | Net log | Gross return | Max drawdown | Exposure | Turnover | Trades | Break-even bps/side |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | A | 104.88% | 0.717253 | 105.87% | 35.76% | 53.12% | 4 | 2 | 1651.588 |
| 15 | I | 104.88% | 0.717253 | 105.87% | 35.76% | 53.12% | 4 | 2 | 1651.588 |
| 15 | U | 105.03% | 0.717964 | 106.01% | 35.76% | 53.12% | 4 | 2 | 1653.071 |
| 15 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 15 | buy_hold | 395.51% | 1.600415 | 400.29% | 53.98% | 100.00% | 8 | 4 | 1822.939 |
| 30 | A | 104.55% | 0.715656 | 105.54% | 35.76% | 53.11% | 4 | 2 | 1648.255 |
| 30 | I | 104.55% | 0.715656 | 105.54% | 35.76% | 53.11% | 4 | 2 | 1648.255 |
| 30 | U | 105.63% | 0.720897 | 106.62% | 35.76% | 53.12% | 4 | 2 | 1659.190 |
| 30 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 30 | buy_hold | 395.56% | 1.600512 | 400.34% | 53.90% | 99.99% | 8 | 4 | 1823.039 |
| 60 | A | 104.28% | 0.714304 | 105.26% | 34.76% | 53.10% | 4 | 2 | 1645.431 |
| 60 | I | 104.26% | 0.714224 | 105.24% | 34.76% | 53.11% | 4 | 2 | 1645.263 |
| 60 | U | 103.56% | 0.710810 | 104.54% | 34.76% | 53.12% | 4 | 2 | 1638.131 |
| 60 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 60 | buy_hold | 390.88% | 1.591039 | 395.62% | 53.89% | 99.99% | 8 | 4 | 1813.351 |
| 120 | A | 99.23% | 0.689303 | 107.53% | 34.45% | 52.89% | 34 | 17 | 212.452 |
| 120 | I | 106.56% | 0.725408 | 107.55% | 34.45% | 53.10% | 4 | 2 | 1668.591 |
| 120 | U | 105.69% | 0.721200 | 106.68% | 34.45% | 53.11% | 4 | 2 | 1659.822 |
| 120 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 120 | buy_hold | 397.18% | 1.603790 | 401.98% | 53.72% | 99.98% | 8 | 4 | 1826.388 |
| 240 | A | 106.54% | 0.725305 | 107.53% | 34.37% | 53.10% | 4 | 2 | 1668.377 |
| 240 | I | 77.87% | 0.575909 | 89.33% | 34.37% | 52.70% | 52 | 26 | 122.006 |
| 240 | U | 106.54% | 0.725305 | 107.53% | 34.37% | 53.10% | 4 | 2 | 1668.377 |
| 240 | cash | 0.00% | 0.000000 | 0.00% | -0.00% | 0.00% | 0 | 0 | — |
| 240 | buy_hold | 403.25% | 1.615922 | 408.11% | 53.72% | 99.95% | 8 | 4 | 1838.775 |

The source gap period is separated below. Continuous 2024+ means separately reset 2024, 2025 and partial-2026 accounts; positions are not carried across fold boundaries.

| Minutes | Family | 2023 net return | 2023 gaps | Gap gross log | Delayed changes | 2024+ net return |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | A | 0.00% | 1 | 0.000000 | 0 | 104.88% |
| 15 | I | 0.00% | 1 | 0.000000 | 0 | 104.88% |
| 15 | U | 0.00% | 1 | 0.000000 | 0 | 105.03% |
| 15 | buy_hold | 155.06% | 1 | 0.001176 | 0 | 94.27% |
| 30 | A | 0.00% | 1 | 0.000000 | 0 | 104.55% |
| 30 | I | 0.00% | 1 | 0.000000 | 0 | 104.55% |
| 30 | U | 0.00% | 1 | 0.000000 | 0 | 105.63% |
| 30 | buy_hold | 154.35% | 1 | 0.001436 | 0 | 94.83% |
| 60 | A | 0.00% | 1 | 0.000000 | 0 | 104.28% |
| 60 | I | 0.00% | 1 | 0.000000 | 0 | 104.26% |
| 60 | U | 0.00% | 1 | 0.000000 | 0 | 103.56% |
| 60 | buy_hold | 155.04% | 1 | 0.001436 | 0 | 92.48% |
| 120 | A | 0.00% | 1 | 0.000000 | 0 | 99.23% |
| 120 | I | 0.00% | 1 | 0.000000 | 0 | 106.56% |
| 120 | U | 0.00% | 1 | 0.000000 | 0 | 105.69% |
| 120 | buy_hold | 156.28% | 1 | 0.001386 | 0 | 94.00% |
| 240 | A | 0.00% | 0 | 0.000000 | 0 | 106.54% |
| 240 | I | 0.00% | 0 | 0.000000 | 0 | 77.87% |
| 240 | U | 0.00% | 0 | 0.000000 | 0 | 106.54% |
| 240 | buy_hold | 157.16% | 0 | 0.000000 | 0 | 95.69% |

All cost sensitivities use the same primary-selected policies without reselection:

| Minutes | Scenario | A net return | I net return | U net return | Cash net return | Buy-hold net return |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | zero | 105.87% | 105.87% | 106.01% | 0.00% | 400.29% |
| 15 | reduced | 105.37% | 105.37% | 105.52% | 0.00% | 397.89% |
| 15 | primary | 104.88% | 104.88% | 105.03% | 0.00% | 395.51% |
| 15 | stress | 103.90% | 103.90% | 104.04% | 0.00% | 390.77% |
| 30 | zero | 105.54% | 105.54% | 106.62% | 0.00% | 400.34% |
| 30 | reduced | 105.04% | 105.04% | 106.12% | 0.00% | 397.94% |
| 30 | primary | 104.55% | 104.55% | 105.63% | 0.00% | 395.56% |
| 30 | stress | 103.57% | 103.57% | 104.64% | 0.00% | 390.82% |
| 60 | zero | 105.26% | 105.24% | 104.54% | 0.00% | 395.62% |
| 60 | reduced | 104.77% | 104.75% | 104.05% | 0.00% | 393.25% |
| 60 | primary | 104.28% | 104.26% | 103.56% | 0.00% | 390.88% |
| 60 | stress | 103.30% | 103.28% | 102.59% | 0.00% | 386.19% |
| 120 | zero | 107.53% | 107.55% | 106.68% | 0.00% | 401.98% |
| 120 | reduced | 103.34% | 107.05% | 106.18% | 0.00% | 399.58% |
| 120 | primary | 99.23% | 106.56% | 105.69% | 0.00% | 397.18% |
| 120 | stress | 91.26% | 105.57% | 104.70% | 0.00% | 392.43% |
| 240 | zero | 107.53% | 89.33% | 107.53% | 0.00% | 408.11% |
| 240 | reduced | 107.03% | 83.52% | 107.03% | 0.00% | 405.68% |
| 240 | primary | 106.54% | 77.87% | 106.54% | 0.00% | 403.25% |
| 240 | stress | 105.55% | 67.10% | 105.55% | 0.00% | 398.44% |

[economics.csv](economics.csv) preserves all annual and aggregate cost/control metrics, including cost drag, turnover, exposure, completed trades, gaps, drawdown and annualized descriptive measures.

## Audit, retained artifacts and reproduction

The [protocol](protocol.json) is bound to freeze `bcc49b113c59f2a2c72524605d26b2dedca98353` and SHA-256 `486fd2b2f1bfa0e4e2ce19b77485386cef833c8b6341d5eca2403556dcdf67a7`. [provenance.json](provenance.json) binds all 459,503 source rows and the same five immutable snapshots. [features.json](features.json) binds all 458,972 native keys, the fixed catalogue and every N×2 interaction-index digest. [run.json](run.json) retains code, command, runtime, package, thread and settings identities. Native preparation receipts are archived separately.

The [full audit](verification.json) checks 640 candidates, 40 refits, 60 policy choices, 420 inner-validation and 400 outer ledgers, all 40 prediction phases, every array member and every exact tail event. Its largest recorded numeric comparison error is `2.128217602148652e-10` and maximum independent direct fit gradient is `2.5062222601597052e-17`. Neither collector nor verifier runs an optimizer. All coefficients, fitting identities, direct objectives/gradients, validation scores and choices remain in compact JSONL records.

The external launcher records exit 0 and 167.068887 seconds. These are operational receipts, not a matched speedup benchmark or a compute-ceiling claim. The original [producer manifest](producer-manifest.json) and seal are copied unchanged. The independent [report manifest](manifest.json) seals this 90-file package, including any supplied external launcher/execution/audit receipts. The twenty annual plus five bootstrap NPZ files (271,070,486 bytes) and native key payloads (18,360,040 bytes) remain externally retained through [exact identities](retained-artifacts.json). All integer metadata is copied into the report. Large bundles are required for complete replay; compact packaging does not reduce audit scope.

Use the completed R3 publication tree containing the final verifier and exactly the producer file hashes recorded in `run.json`. Later edits to computational files will fail original-run identity checks. Reuse the recorded sealed native-key directory. The original producer invocation was:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/run_round3.py --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --out /Users/mikkokotila/dev/Filang-research/runs/geometry-interactions-r3 --protocol /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/round3_protocol.json --freeze-commit bcc49b113c59f2a2c72524605d26b2dedca98353 --workers 5 --blas-threads 2
```

Re-execution requires a new unused `--out` directory, identical pinned inputs, and the recorded implementation and freeze pair. To audit and collect the retained run:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python -m pip install -r requirements-information.txt
/Users/mikkokotila/dev/Filang-research/.venv/bin/python experiments/geometry_information/verify_round3.py --stage full --run /Users/mikkokotila/dev/Filang-research/runs/geometry-interactions-r3 --keys-root /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --protocol experiments/geometry_information/round3_protocol.json --out /Users/mikkokotila/dev/Filang-research/runs/geometry-interactions-r3/verification.json
/Users/mikkokotila/dev/Filang-research/.venv/bin/python experiments/geometry_information/collect_round3.py --run /Users/mikkokotila/dev/Filang-research/runs/geometry-interactions-r3 --out benchmarks/reports/20261008-geometry-interactions-r3
```

Optional `--launcher` and repeatable `--audit-receipt` archive external operational evidence. Keep those files outside the sealed run. Different existing report evidence is never overwritten.

## Residue and campaign stop

I has positive pooled primary-cost net log return in 5 of five timeframes and selects cash in 9 of twenty timeframe/year cases. The complete joint criterion is supported in 0 of five timeframes. These are complete outcomes for the fixed family; no outer winner is used to change the vocabulary, penalty grid, policies, horizon or cost assumptions.

The record preserves the [exact-pattern predecessor](../20261008-bitcoin-direction/README.md), [R1 numerical failure](../20261008-geometry-information-r1-failed/README.md), [R1a information experiment](../20261008-geometry-information-r1a/README.md), and [R2 payoff experiment with audit-development history](../20261008-geometry-payoff-r2/README.md). All historical data and preceding outcomes were exposed before R3. Nested fitting controls row availability within each fold but does not erase adaptive research exposure; the five-timeframe Holm family does not account away the whole campaign.

A not-supported result does not prove all geometric functions useless; a supported result does not establish live tradeability or excess return over passive Bitcoin. This finite current/previous interaction projection omits many possible functions. The execution proxy lacks quotes, depth, latency, market impact and actual fills; no real orders were placed. **The finite campaign ends with R3's retained result.** Any eventual trading-edge claim needs separately frozen future-data and execution evidence, rather than extending the historical search until a favorable outcome appears.

Bibliography: [declared fee-scenario reference](https://www.binance.com/en/fee/trading); [backtest-overfitting research](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). These are contextual links rather than substitutes for this protocol and its measured evidence.
