# Factorized walk-forward campaign — 2026-09-28

## Outcome

The diverse generated voting policy returned **+14.19%** at primary costs and **+1.48%** at doubled costs over this retrospective multi-fold replay. Its maximum drawdown was **38.61%**. This is positive realized backtest performance, but it is far behind the fixed SMA/EMA trend comparators and continuous buy-and-hold. It does not establish a robust generated edge comparable to the strongest fixed controls. The generated top-one and equal-feature-budget selections lost money; those outcomes are retained.

All results are **retrospective walk-forward, not a fresh untouched holdout**. The prior campaign already exposed later BTC outcomes, and the selector design followed that experience. No outer-results-driven reselection was performed in this campaign.

## Freeze and research protocol

Source and all fold-specific selections were committed and pushed as `edb186e41ad142cc7a161e74f56e26c7e1470750` before the first explicit outer replay. The selection seal is `0f329672f5a9c0d3950ec6b7feaade56578811a58764d6916753fc0c2ccf63a5`. The pinned source and native CSV hashes are in the provenance JSON.

Eight outer periods cover 2023-01-01 through 2026-09-28 exclusive. Each uses the preceding four six-month validation windows; each historical window fits quantile thresholds only on earlier data beginning 2020-07-01. Selected quantiles refit at the outer start. Primary fees/slippage are 5+5 bps per side, stress 10+10. Both scenarios use exactly the same selections. Full rules and the objective are in `docs/WALKFORWARD.md`.

Generated-full uses 4,096 addresses. The matched group uses the first 51 generated addresses versus 51 tunable indicator definitions. Feature-count matching does not equalize all structural priors or complexity. Each page has exact structural uniqueness; cross-page/global uniqueness is deliberately not asserted.

## All predeclared portfolios

Portfolios are listed in stable identifier order, not ordered by final return. Drawdown is a positive peak-to-trough loss.

| Portfolio | Net return | Stress net | Max drawdown | Trades | Exposure | Positive folds |
|---|---:|---:|---:|---:|---:|---:|
| buy_hold | +395.50% | +387.63% | 53.90% | 8 | 99.83% | 6 |
| buy_hold_continuous | +411.50% | +410.48% | 53.45% | 1 | 100.00% | N/A |
| cash | +0.00% | +0.00% | 0.00% | 0 | 0.00% | 0 |
| RSI(14)>50 | +62.47% | -29.01% | 59.34% | 414 | 53.01% | 5 |
| RSI(14)<30 | -22.02% | -36.79% | 28.02% | 105 | 4.20% | 5 |
| EMA(24)>EMA(96) | +257.95% | +225.19% | 33.22% | 48 | 54.58% | 7 |
| MACD(12,26,9) histogram>0 | +71.21% | -6.79% | 45.45% | 304 | 49.61% | 4 |
| Close>SMA(200) | +286.26% | +205.06% | 30.96% | 118 | 55.82% | 5 |
| Bollinger(20) z<-2 | -48.51% | -67.95% | 49.70% | 237 | 6.32% | 1 |
| generated_diverse | +14.19% | +1.48% | 38.61% | 59 | 24.90% | 4 |
| generated_top1 | -22.52% | -31.01% | 53.25% | 58 | 23.49% | 3 |
| indicator_diverse | -15.89% | -23.74% | 56.86% | 49 | 32.96% | 1 |
| indicator_top1 | -1.00% | -6.58% | 43.13% | 29 | 29.24% | 2 |
| matched_generated_diverse | -22.91% | -28.98% | 54.21% | 41 | 41.55% | 1 |
| matched_generated_top1 | -17.30% | -21.02% | 48.53% | 23 | 42.80% | 1 |

`buy_hold` closes/restarts at the same fold boundaries as adaptive policies; `buy_hold_continuous` has one uninterrupted trade. Concatenation includes **14 explicit flat inter-fold intervals**, not compressed time. Each policy sees the same signal-to-next-open ledger and costs. The next-open fill is idealized; capacity, market impact and real order latency are not modeled.

## Selection and verification

- `generated`: member counts by fold [5, 5, 5, 5, 5, 5, 5, 2]; cash fallback in 0 folds; maximum retained historical absolute behavior correlation 0.758056.
- `matched_generated`: member counts by fold [0, 0, 0, 5, 5, 5, 5, 0]; cash fallback in 4 folds; maximum retained historical absolute behavior correlation 0.791085.
- `indicator`: member counts by fold [0, 0, 0, 5, 5, 5, 5, 0]; cash fallback in 4 folds; maximum retained historical absolute behavior correlation 0.797082.

Independent NumPy direct-window arithmetic, strict-vote reconstruction and explicit cash/share accounting checked all **112 fold-portfolios and 15 aggregate portfolios per cost scenario**, with **zero position disagreements**. Maximum absolute metric discrepancy was below **6e-10**. Full primary and stress JSON reports are retained.

Native tests cover direct/shared/SIMD/parallel frozen-selection equality, future-price perturbation, later-fold addition, prefix order statistics against direct sorting, multi-cost moments against direct ledgers, bitmap tails/invalids/votes, prepared-bank identity and bounded random access to the last trillion-domain page.

## Runtime evidence

The repeated matched-ablation results will be added after their execution. The first recorded discovery completed in about 3.27 internal seconds on four M1 Max workers with NEON; this is one measurement, not the comparative benchmark. No trillion feature evaluation has occurred.

## Reproduce

See `docs/WALKFORWARD.md` for commands. The full local runs are `runs/btc4h-walk-v02`, `runs/btc4h-walk-primary` and `runs/btc4h-walk-stress`. Raw market data and full portfolio CSVs are not committed; they are regenerated from the immutable source, frozen definitions and recorded contracts.
