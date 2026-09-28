# Filang 0.1 execution and research contract

This is a runnable first vertical slice of issue #1, not implementation of the complete specification. Limen is a capability prototype and Terasweep a performance prototype; neither is imported or treated as a compatibility oracle.

## Program language

The native engine accepts a typed numerical DAG. Canonical expressions use prefix syntax, for example:

```text
(div (sub close (mean 32 close)) (std 32 close))
```

Sources are `open`, `high`, `low`, `close`, `volume`. Constants use `(constant <16 hexadecimal IEEE-754 bits>)`. Unary operators are `abs`, `neg`; binary operators are `add`, `sub`, `mul`, `div`, `min2`, `max2`. Window/lag operators are `(lag n x)`, `(diff n x)`, `(mean n x)`, `(std n x)`, `(min n x)`, `(max n x)`, `(ema n x)` and `(wilder n x)`.

Price and base-volume dimensions are checked. Addition/minimum/maximum require matching dimensions; multiplication/division compose units. Search/readout roots must be dimensionless. Dependencies point backward; depth, node count and windows have limits. No arbitrary code evaluation or source compilation occurs per candidate.

Rolling windows include the current bar and require all `n` finite observations. Standard deviation is the population version. Sliding moments periodically rebase at absolute row indexes divisible by 512. EMA uses `2/(n+1)` and Wilder smoothing `1/n`; both initialize from the arithmetic mean of the first `n` consecutive finite values and reset after invalid input. Lag is in raw, fixed-duration bars. There is no row dropping, forward filling, fitted scaling or cross-sectional ranking in this version.

Division by a denominator with magnitude <= `1e-12` returns invalid, not an epsilon-shifted ratio. Nonfinite intermediate results become invalid; invalid roots imply flat signals. This policy is part of the formula, not a claim of universal numerical correctness. Seeds reconstruct RSI in [-1,1] (ordinary RSI/50 minus one), EMA differences, MACD histogram, Bollinger z-score, channel position, momentum and ATR-normalized distances. Completely flat RSI windows are invalid under the general division contract.

The generator starts from these numerical constructions plus volume surprise, volatility-normalized return and candle geometry. Eight parameterized composition motifs generate new trees, including selected previously generated subprograms. Windows, lags, motif choices, reuse cadence, seed, depth and size bounds are exposed in the configuration. This is bounded structural search, not yet an exhaustive arbitrary-grammar enumerator.

## Data and availability

CSV schema: `timestamp,open,high,low,close,volume`. Timestamps are integer Unix seconds interpreted as UTC bar opening times. Prices must be finite and positive, volume finite and nonnegative, OHLC geometry valid, and timestamps exactly contiguous at `interval_seconds`. Gaps, duplicates and invalid source bars fail; they are never silently compressed.

The pinned 4-hour source has one missing bar in February 2020. The declared view starts 2020-03-01 based on that data-quality inspection, before any performance analysis. Training starts 2021-01-01. Older history is causal warm-up only.

`discovery.csv` ends exactly at `validation_end` (exclusive). Search rejects any later rows rather than silently reading them as additional fitting data. `evaluation.csv` is used only by the separate evaluation command and contains the identical warm-up/discovery prefix. Its prefix hash must match the frozen selection. Input separation is an auditable research protocol, **not an operating-system security boundary**.

## Spot ledger v1

At the close of bar `t`, evaluate the strictly greater-than or strictly less-than rule on the completed feature. The desired long/flat position executes at `open[t+1]` and earns the change through `open[t+2]`. Hold while the condition remains true. A continuous position is not liquidated/re-entered every bar. The first evaluation interval starts at the next open after the first scored signal. The last two possible decisions lack a complete execution interval and are excluded. The final held position is liquidated at the last available open inside the evaluation range.

The next-open fill is an idealized bar-level assumption, not an assertion that a real order can always receive that quote. Computation/venue latency, spread variation, queueing, market impact, order minimums and capacity are not simulated. Results cannot establish live tradability.

Let `f=fee_bps/10000`, `s=slip_bps/10000`. Entry fully funds shares and fees from available cash:

```text
shares = starting_cash / (entry_open * (1+s) * (1+f))
exit_cash = shares * exit_open * (1-s) * (1-f)
```

No leverage, borrowing, shorting, interest on cash, or fee rebates. Thus a held interval's wealth multiplier is `exit_open/entry_open * (1-f)*(1-s)/((1+f)*(1+s))`. Fees are assumptions, not the user's verified Binance fee schedule. Primary: 5 bps fee plus 5 bps slippage per side. Predeclared stress: 10 plus 10 per side. Signal selection does not optimize the fee assumption.

Returns are mark-to-market equity returns, with entry and exit costs applied at their fills. All complete evaluation intervals, including flat zero-return intervals, enter mean and variance. Total net return compounds; drawdown includes initial equity 1.0; CAGR uses actual elapsed interval length. Per-trade return averages complete compounded trades. The displayed annualized Sharpe uses sample standard deviation and sqrt(31557600/interval_seconds), assumes zero cash return, and is **not serial-correlation adjusted**. Undefined Sharpe/mean-trade metrics are JSON null. Cash is a separate zero-return control.

## Family evaluator

Numerical dependencies are interned and evaluated once per bounded batch, not once per readout. Batch size shrinks to fit the configured numerical-vector payload budget. This budget includes a small scratch reserve; it is **not a cap on total process RSS** (data, program metadata, sorting and output buffers also exist).

For a fixed feature and evaluation block, sort feature values. Move through thresholds monotonically, activating positions. One activation changes only the return categories at its preceding, current and following intervals. Maintain entry count, exposure, sum of returns, squared returns and log wealth. Both strict directions and tied values are covered. This supplies the declared selection metrics without constructing an equity history for every threshold. It does not compute drawdown or general path-dependent execution. Selected programs receive full chronological replays.

`scorer=scan` is the direct per-rule oracle. `scorer=events` uses incremental statistics and compensated summation. They are mathematically matched but not promised bit-identical. Differential tests and campaign checks record discrepancies; ranking uses a declared 1e-9 score resolution, then the stable full candidate ID. Independent Python/NumPy verification uses direct windows and explicit cash/shares, not the category algorithm.

## Selection protocol

Training: 2021-01-01 through 2023-12-31. Validation: 2024, also divided into four contiguous equal-bar blocks. Threshold quantiles (linear interpolation) are fitted only to finite training feature values. Candidate rules vary direction and those frozen cutoffs.

For searched candidates, require positive training and whole-validation net returns, at least 12 training trades and 8 validation trades, and exposure between 2% and 98% on both. Rank by mean validation-block annualized Sharpe minus `0.5 * block-Sharpe standard deviation` minus `0.001 * unique dependency-node count`. Undefined block Sharpe contributes zero **to this selection objective only**. These constants, exposure/trade gates and block count are configurable. Sub-block evaluation resets capital/positions and incurs its own boundary costs; it is not silently equated with uninterrupted yearly performance.

Freeze the best readout per feature, then the top five generated features and top one tuned established-indicator feature. Also freeze six predeclared fixed indicator controls and buy-and-hold/cash. Fixed controls bypass search eligibility gates so weak/inactive controls are not hidden. The final period is 2025-01-01 through 2026-09-27; both primary and stress scenarios use the unchanged frozen list and order. Later results are not used to choose a new winner.

Generated features have a much larger search budget than the known-indicator comparator bank. This is an exploratory comparison, not a controlled claim of algorithmic superiority. One asset, one timeframe and one chronological selection/holdout split cannot establish generalization. The engine does not yet rerun full discovery in outer walk-forward folds or provide a multiple-testing correction. Inspecting final results consumes that holdout for future research.

## Identity and artifacts

Feature IDs are SHA-256 of versioned canonical expressions; readout IDs additionally cover strict direction and exact threshold bits. The expression is always retained; hashes are not inverted and collision-prone hash-only reuse is not used (the graph map compares full structural keys).

`programs.tsv`: definitions, groups and structural sizes. `discovery.jsonl`: every evaluated readout and eligibility/selection result. `selected_validation.json`: full validation replays. `frozen.tsv` and its checksum: exact programs/rules, execution assumptions, final boundaries and discovery-prefix identity. `summary.json`: real work, counts and timing. `evaluation.json`: all frozen results in selection order, not re-ranked; per-candidate CSVs expose feature values, signals and execution timestamps.

The checksum detects accidental edits; it is not an authenticated signature. Run directories refuse overwriting. The engine does not yet implement checkpoint/resume, packed multi-predicate Boolean programs, distributed workers, GPU/ISA-specific kernels, automatic family planning, or trillion-scale completion. Issue #1 remains open.
