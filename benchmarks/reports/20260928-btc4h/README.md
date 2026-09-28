# BTCUSDT 4h founding campaign — 2026-09-28

The selection artifacts in this directory were committed before the first final-period evaluation. `frozen.tsv.sha256` seals the exact programs/readouts, costs, split boundaries and discovery-prefix identity. The implementation and independent validation checks exist in the same commit.

Training: 2021–2023. Validation: 2024. Final evaluation (not yet run in this commit): 2025-01-01 to 2026-09-28 exclusive. Primary 5 bps fee + 5 bps slippage per side; predeclared stress 10 + 10. No later-period performance informed this selection.

The initial engineering runs used the same seed/domain and produced the same 14 selected readout IDs in the same order. A cosmetic change replaced sequential generated display names with feature hashes; this did not change selected identities, formulas, thresholds or ranking. Direct scanning and event sweeps agreed across all 157,594 readouts; the independently computed validation metrics agreed for all 14 frozen candidates.

Raw market data and large per-readout ledgers are deliberately not committed. Recreate them with the pinned adapter and saved config. See the repository contract for inference limitations and what the counts mean.
