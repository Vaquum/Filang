# Annual indicator micro-sweeps: 10+10 costs

BTCUSDT four-hour bars. 10 bps fees + 10 bps slippage per side.
Each year is independently tuned on that same year (in-sample).
Tuned = unrestricted descriptive maximum by same-year stressed log return.
Difference = tuned minus reference in percentage points (pp).

## 2024

| Indicator | Reference return | Tuned return | Difference (pp) |
|---|---:|---:|---:|
| SMA(200) | +75.18% | +86.56% | +11.38 |
| EMA(24) | +63.27% | +69.76% | +6.49 |
| RSI(14) | +48.05% | +60.86% | +12.82 |
| MACD(12,26,9) | +6.54% | +30.98% | +24.44 |
| Bollinger(20) | -4.93% | -4.51% | +0.42 |
| Stochastic(14,3,3) | -54.76% | -48.64% | +6.12 |
| ATR(14) / price | +103.04% | +107.98% | +4.94 |
| ROC(14) | +37.72% | +65.66% | +27.93 |
| CCI(20) | -6.94% | +20.73% | +27.67 |
| Rolling VWAP(20) | +19.55% | +26.03% | +6.48 |

## 2025

| Indicator | Reference return | Tuned return | Difference (pp) |
|---|---:|---:|---:|
| SMA(200) | -18.14% | -12.89% | +5.25 |
| EMA(24) | -56.97% | -51.20% | +5.77 |
| RSI(14) | -56.78% | -50.20% | +6.58 |
| MACD(12,26,9) | -40.25% | -34.32% | +5.93 |
| Bollinger(20) | -29.85% | -22.30% | +7.55 |
| Stochastic(14,3,3) | -62.17% | -56.12% | +6.06 |
| ATR(14) / price | -39.25% | -35.87% | +3.38 |
| ROC(14) | -54.65% | -46.22% | +8.43 |
| CCI(20) | -42.26% | -36.19% | +6.07 |
| Rolling VWAP(20) | -56.03% | -52.35% | +3.69 |

## 2026 — January 1–September 27 (partial year)

| Indicator | Reference return | Tuned return | Difference (pp) |
|---|---:|---:|---:|
| SMA(200) | +12.90% | +17.33% | +4.43 |
| EMA(24) | -10.50% | -3.13% | +7.37 |
| RSI(14) | -7.87% | -1.41% | +6.46 |
| MACD(12,26,9) | -0.53% | +6.48% | +7.01 |
| Bollinger(20) | -30.14% | -27.00% | +3.14 |
| Stochastic(14,3,3) | -34.23% | -23.95% | +10.28 |
| ATR(14) / price | -14.71% | -11.53% | +3.18 |
| ROC(14) | -18.95% | -10.80% | +8.16 |
| CCI(20) | -21.58% | -17.69% | +3.89 |
| Rolling VWAP(20) | -9.52% | -6.71% | +2.81 |


## Method and reproducibility

Same fixed ten-family grids as issue #12, independently rerun within each calendar year. All historical input rows before the year remain available solely for causal feature warmup. Equity starts at one and the final position is closed in each year. The existing next-open execution contract excludes the last two decision bars without a complete execution interval; 2026 is partial through the stored September 28 exclusive cutoff, not annualized.

The displayed tuned return is the unrestricted same-year maximum, selected by stressed log return with the existing nearest-anchor tie break. It is not the promotion-eligible selection or evidence of out-of-sample improvement. Original grids, numerical profiles, signal/execution prices and costing are unchanged. Both standard scenarios remain in underlying parity artifacts; these tables expose only fees10bps plus slippage10bps per side.

Run `.venv/bin/python scripts/run_annual_cohort.py discover --out runs/my-annual` then `.venv/bin/python scripts/run_annual_cohort.py verify --out runs/my-annual --workers 4`. New output directory required. Three data-specific annual cohort gates and the legacy gate are independently verified; no gate is bypassed.

All 302,731,290 parameter addresses are covered by 6,065,720 exact per-construction result regions. Verification checks all 12,131,440 physical scenario metric sets and every represented decision path; no mask disagreement. Detailed maximum numeric discrepancies, exact source/data/engine identities and table-to-region maximum checks are retained in JSON. Forty-nine native tests, format and Clippy pass; the range test confirms identical full warmup feature histories and rejects future rows. Native computation source: `2bd5951fcd841eec8ab16fbdb1b9f30a565d5458`.
