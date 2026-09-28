# BTCUSDT 4h founding campaign — 2026-09-28

## Result

The engine runs, but this first generated shortlist did **not** discover a profitable held-out strategy. All five generated selections lost money after the primary costs. The validation-selected established-indicator comparator returned +11.82%, but fell to -0.82% under the predeclared doubled-cost stress. No post-holdout reselection or additional generated-candidate scan was performed.

This is a negative discovery result, not a reason to erase the experiment or report a validation winner as alpha. The next research need is more robust selection and diversity evaluation, not a larger same-holdout sweep.

## Frozen-before-evaluation evidence

The implementation and exact selection were committed and pushed as **69704e59a448c30f50c8bb18ddd04eabca1a2d54**, before the first final-period evaluation command. Frozen selection SHA-256: `9735b3c49b07e5919504217168abf2203508bea0ee0a6cf94be639452dc57c61`.

Training: 2021–2023. Validation: 2024 (including four equal-bar validation blocks). Final evaluation: 2025-01-01 to 2026-09-28 exclusive. Primary fee/slippage: 5 + 5 bps per side. Predeclared stress: 10 + 10 bps per side. All controls use the same next-open, cash-funded, long/flat ledger. The final period contains 3,808 complete scored open-to-open intervals.

Earlier engineering runs used the same seed/domain and selected the same 14 readout IDs in the same order. A cosmetic change replaced sequential generated display names with feature hashes; it did not change formulas, thresholds or ranking. Both final evaluations use the identical frozen file. The final period has now been observed and cannot be treated as an untouched holdout in subsequent research.

## All frozen candidates, in selection order

Positive drawdown values denote peak-to-trough loss. Returns are compounded and net of the declared fees/slippage. Validation results are selection data, not out of sample. `generated` rows are in their original validation rank; this table is **not** ordered by final performance.

| Group / program | Validation net | Final net | Final max drawdown | Trades | Final exposure | Stress net |
|---|---:|---:|---:|---:|---:|---:|
| generated / `f_802d96541c0a513a` | +243.02% | -37.80% | 56.31% | 36 | 46.59% | -42.12% |
| generated / `f_df9077813100ac0b` | +134.83% | -15.80% | 33.02% | 36 | 18.86% | -21.65% |
| generated / `f_65dbcefdbfbe5489` | +78.73% | -26.86% | 41.92% | 20 | 14.50% | -29.73% |
| generated / `f_521a26232a9352af` | +121.50% | -0.37% | 21.41% | 15 | 7.88% | -3.32% |
| generated / `f_3a33880cbaa64f2f` | +57.33% | -6.13% | 29.56% | 24 | 9.82% | -10.53% |
| tuned_indicator / `SMA_distance(128)` | +43.94% | +11.82% | 28.70% | 60 | 16.81% | -0.82% |
| fixed_indicator / `RSI(14)>50` | +79.03% | -39.52% | 59.57% | 209 | 50.50% | -60.18% |
| fixed_indicator / `RSI(14)<30` | +6.72% | -14.09% | 28.02% | 54 | 4.83% | -22.88% |
| fixed_indicator / `EMA(24)>EMA(96)` | +77.00% | +6.79% | 32.02% | 23 | 47.03% | +1.99% |
| fixed_indicator / `MACD(12,26,9)_hist>0` | +27.30% | -21.20% | 45.00% | 141 | 50.32% | -40.57% |
| fixed_indicator / `Close>SMA(200)` | +85.27% | +3.37% | 29.99% | 56 | 48.63% | -7.58% |
| fixed_indicator / `Bollinger(20)_z<-2` | +9.14% | -39.05% | 41.69% | 109 | 6.33% | -50.99% |
| control / `Buy_and_hold` | +122.01% | -9.88% | 53.45% | 1 | 100.00% | -10.06% |
| control / `Cash` | +0.00% | +0.00% | 0.00% | 0 | 0.00% | +0.00% |

## Scope and correctness

The campaign generated **4,096 unfamiliar programs**, alongside 51 tunable established-indicator definitions, six fixed indicator rules and two controls. There are 4,153 distinct numerical program roots (some fixed rules share roots), **157,594 feature/readout evaluations** and **945,564 requested block-metric evaluations**. These are not 945,564 independent features or full ledger replays. Fourteen frozen candidates received full chronological validation replays; the same fourteen received final primary and stress replays.

Direct and event-sweep scoring matched across the complete 157,594-row discovery ledger, with maximum absolute selection-score disagreement about 3.11e-15 in the initial check. Frozen selection was byte-identical across the matched direct/shared/event runs before the cosmetic name change. Independent NumPy direct-window features and explicit cash/share accounting checked all fourteen final candidates under both cost scenarios: zero signal disagreements; maximum absolute reported metric disagreement below 3.5e-11. See the JSON evidence files for exact values and environments.

The displayed results are conditional on the dataset and the documented idealized fills. Only one instrument and timeframe were studied, the generated search had a larger selection budget, no capacity model was run, and the annualized Sharpe is not serial-correlation corrected. See `docs/CONTRACT.md`. Neither a positive benchmark nor lower drawdown of a losing generated strategy proves future profitability.

## Reproduce

From the repository root, prepare the immutable dataset with `scripts/prepare_hf.py`, build with `cargo build --release --locked --offline`, and use the saved experiment config with a fresh `--out` directory. Evaluate that run's sealed `frozen.tsv` using the documented primary/stress commands. The source snapshot, native CSV hashes and date boundaries are in `data_provenance.json`.

Raw market data, trace histories and large per-readout ledgers are not committed. The local measured runs live under `runs/btc4h`, `runs/btc4h-evaluation` and `runs/btc4h-stress`. These artifacts can be regenerated; the retained frozen definitions allow replay without repeating discovery.
