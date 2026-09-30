# Fine SMA atom-neighborhood sweep — 2026-09-30

## Result and scope

The native factory resolved **10,091,043 parameter combinations** through **433,405 exact result regions**, using **5,043 upstream constructions**. This is not ten million independent indicators: the final subtraction constant is explicitly readout-equivalent. Every declared combination is represented; none was heuristically pruned.

Small parameter changes improved discovery-period returns, but **none met the predeclared 40% stress-drawdown ceiling**. The minimum stress drawdown anywhere in the grid was 46.56048287%. The ceiling was not relaxed, no variant was promoted, and only the unchanged anchor was frozen for later replay. Descriptive maxima and the complete response surface are retained, not presented as newly validated alpha.

## The exact family

```text
P = close + a * (open - close)
M = mean_sum(n, P)
D = M + b * (mean_sum(n+1, P) - M)
F = P / D - c
long when F > 0
```

At a=0 the source is the unchanged close node. At b=0 the denominator is exactly M, without adding the adjacent window's warmup. Thus n=200,a=b=0,c=1 has the exact existing SMA-anchor expression identity. No rolling mean is commuted through the source mixture; operation order and the raw-total numerical profile are preserved. Execution uses the original market prices, not the modified signal source.

| Parameter | Values | Step | Count |
|---|---|---|---:|
| Integer mean period n | 199, 200, 201 | 1 bar | 3 |
| Source weight a | -0.01 to +0.01 | 0.0005 | 41 |
| Adjacent-mean weight b | 0 to 0.1 | 0.0025 | 41 |
| Subtraction constant c | 0.999 to 1.001 | 0.000001 | 2,001 |

The c increment is 0.01 basis point relative to the baseline ratio. a multiplies the candle's open-close difference, not the full price. b is an interpolation weight between two integer-window means, not a fractional argument passed to Mean. Zero settings are genuine anchors, not constant all-flat shortcuts. Parameters, bounds and the selection policy were fixed in issue #10 before outcomes.

## What changed in the backtest

Discovery is 2021-01-01 through 2024-12-31, on pinned BTCUSDT 4h data: 8,764 complete execution intervals with no intermediate fold resets. Primary costs are 5 bps fee plus 5 bps slippage per side; stress doubles both. Prices, costs, execution timing and all ten metrics are identical across candidates. These single-interval results must not be compared directly with the older eight-fold-reset report.

| Discovery comparison | n | a | b | c | Primary net | Stress net | Stress max drawdown | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Unchanged anchor | 200 | 0 | 0 | 1 | +262.7108% | +181.9150% | 46.5605% | 126 |
| Best source/mean weights, period and cutoff unchanged | 200 | -0.0005 | 0.0625 | 1 | +269.1402% | +187.4866% | 46.5605% | 125 |
| Best upstream changes, cutoff fixed at one | 199 | 0.0085 | 0 | 1 | +280.6206% | +199.4067% | 46.5605% | 120 |
| Best cutoff only | 200 | 0 | 0 | 1.000987–1.001 | +313.2540% | +227.0334% | 46.5605% | 117 |
| Best unrestricted descriptive grid point | 201 | 0.008 | 0 | 1.000561 | +321.7134% | +235.7363% | 47.0685% | 114 |

Each restricted comparison is a descriptive maximum within that slice, not a separately selected validation winner. Most of the largest observed gain is already attainable through cutoff changes; the weights-only comparison isolates an actual atom-composition change from that effect. This is not a causal attribution or evidence of generalization.

Across the full discovery grid, primary net returns range from +207.3210% to +321.7134%; stressed net returns range from +133.6660% to +235.7363%. 5,580,645 addresses exceed the anchor's stressed return. Counts of neighboring, dependent parameter settings are not statistical confidence levels or independent trials.

## Frozen selection and later replay

Eligibility required >=12 primary trades, 2–98% primary exposure, and stress drawdown <=40%. Ranking was stressed log return, with predeclared score resolution and nearest-anchor tie breaking. Eligible addresses: **zero**. The unrestricted maximum above did not pass and was not tested as a promoted strategy.

Discovery and its exact anchor-only frozen file were committed/pushed in `bc8dd26` before the first later replay. The later interval, 2025-01-01 to 2026-09-28 exclusive, produced +3.37% primary / -7.58% stress for the unchanged anchor, with 56 trades. These outcomes are retained in the later-anchor JSON files. Both historical periods had been observed in earlier research; neither is claimed as a fresh untouched holdout. No new variant was selected after seeing later results.

## General factorization, not an SMA-specific kernel

The authoring layer supplies ordinary source, add/subtract, multiply/divide, mean_sum and constant nodes. The generic paged Executor prepares one bounded bank per source/window stripe, then reuses those exact values across its descendants. The default run builds 123 banks: 969 prepared nodes and 39,606 recorded prepared-node hits. The numerical atoms themselves are unchanged.

The generic constant-region API recognizes `sub(series,constant)` read out above zero. It certifies its finite nonnegative domain, then determines the grid indices at which positions change. Contiguous index ranges retain all original parameter identities and share full metric results only on this data/context. No hash-only match, epsilon-shifted predicate, omitted metric or approximate pruning is used.

The 433,405 regions supply 866,810 physical ten-metric sets, representing 20,182,086 logical scenario-metric sets. The average region covers 23.283 parameter addresses. This is exact compressed result coverage, not 10,091,043 independent chronological replays or a claim of ten million independently informative signals.

The state engine recorded one full chronological fallback, one tree rebuild, 433,403 incremental updates, 91,453 interval joins and 109,803 splits. All-on/all-off region requests: zero. Detection and state work are counted separately in summary.json. Unsupported constant-region domains fail explicitly; ordinary expanded evaluation remains a reference path.

## Independent verification

`verify_micro.py --all-metrics` used pinned TA-Lib wrapper 0.6.8 / C 0.6.4 to compute each actual modified source's means. For every upstream construction it compared the complete initial packed mask and ordered (grid index, row index) transition records as arrays, not just hashes. This verifies every represented position path, including strict thresholds and ties.

Every one of the **866,810 physical scenario metric sets** was checked against independent NumPy chronological accounting. Maximum absolute metric difference: **1.1368683772161603e-12**. Counts match exactly; no mask mismatch occurred. Twenty additional systematic explicit cash/share replays are labeled a subset. The unchanged full anchor gate separately passed all 88 cash/share/trace cases and all stored fixed-control regressions. Numerical tolerances were not widened.

The fully verified computational source was `3bbe54810393e85c2e32d1a6cbce398c7f355fe9`. The final source `f9f4d5620ce89fecd387489535cd18e20e0bcb16` changes only native help text. Every byte of its complete regions.bin, transitions.bin, surface.csv and frozen.tsv was compared with the fully verified run; all agree. Final anchor parity was also rerun. See final_build_equivalence.json, verification.json, and anchor_parity/.

Final executable SHA-256: `c2ce0e260c3b97990ed90f263482cbc12ccf1e0f43cabae32ce289165c3b757b`. Discovery CSV SHA-256: `6dece8e4d91e98c83d80a0217907e024db656781cf3f0ffd61941e87c942aa98`.

The independent full-grid verification took about 221 seconds. That is verification cost, including comparisons and reference reconstruction, **not a matched reference-performance denominator** and not used to claim a speedup.

## Measured performance

Hardware: Apple M1 Max, one native worker, f64 with the existing NEON path. CPU affinity was not pinned and OS caches were not flushed. No concurrent reference verification was run during the timing comparisons. All final timing runs used the final executable above. Short measurements and three repetitions do not establish universal latency or throughput bounds.

The complete 10,091,043-address run took **1.31 seconds whole-process**, including discovery calculations, full scenario metrics, surface/selection output, 79,746,520 bytes of region records and 12,722,432 bytes of exact transition evidence. Maximum measured RSS was **16,465,920 bytes (15.70 MiB)**. This is one captured run, not a median or a trillion-program extrapolation.

### Matched small-grid ablation

The small grid contains 27 upstream constructions and 201 offsets each: 5,427 parameter addresses / 10,854 logical full-metric sets. Every logical result was reconstructed and compared between all three paths. The expanded reference caches upstream values and independently subtracts each constant and replays the original full metric contract; it does not recompute an indicator for each constant.

| Path | Median wall time, 3 runs |
|---|---:|
| Expanded native replay, shared upstream calculation | 0.463111 s |
| Exact regions, unshared upstream calculation | 0.049336 s |
| Exact regions, shared upstream calculation | 0.051129 s |

The expanded/shared-region ratio is **9.058x** on this small workload. Both timed modes use summary output; their physical encodings differ because one represents individual addresses and the other exact result regions. This is the intended algorithmic compression, not a byte-identical-output comparison. On the small grid, shared-bank setup does not independently improve the measured median; that negative detail is retained.

### Full-grid dependency-sharing ablation

Six separate summary-output runs covered the same full 10,091,043-address domain, with rotated shared/unshared order. Both paths computed and hashed identical complete region records and produced the same frozen selection. Median shared time was **1.22 s**; unshared was **1.59 s**, a measured **1.303x** ratio. Timings come from /usr/bin/time's printed hundredth-second resolution. All raw logs and per-run numerical/state counters are retained in full_benchmark/.

These are native application comparisons, not standalone TA-Lib kernel speedups. They must not be multiplied by ratios from previous releases. The user-facing response surface and metrics are not replaced with a cheap proxy. Result compression reduces per-offset work; changing source/window settings still requires actual numerical calculations.

## Reproduction and retained artifacts

Commands and numerical/research contracts are in `docs/ATOM_MICRO_SWEEP.md`. The current reusable local gate is `runs/micro-v05-final-parity/micro_gate.txt`. A changed executable requires fresh anchor parity and authorized-prefix evidence. Core runtime has no third-party dependencies; TA-Lib/NumPy are optional verification tools.

```sh
./target/release/filang micro-sweep --config examples/sma-micro.cfg \
  --gate runs/micro-v05-final-parity/micro_gate.txt --out runs/my-micro
.venv/bin/python scripts/verify_micro.py --run runs/my-micro \
  --out runs/my-micro/verification.json --all-metrics
.venv/bin/python scripts/benchmark_micro.py \
  --gate runs/micro-v05-final-parity/micro_gate.txt --out runs/my-benchmark --repeats 3
```

For the full-grid sharing ablation, run micro-sweep three times each with `--output summary --shared true` and `--output summary --shared false`, using fresh output paths and alternating order; collect `/usr/bin/time -l` resource logs. Compare every summary's region_sha256 and frozen.tsv with the independently verified run, not only runtime. Those are the exact commands/conditions used for the retained full-grid measurements.

The report retains the complete 5,043-row surface, discovery metrics, original freeze checkpoint, later anchor outcomes, reference verification, final-build equivalence, parity gate evidence, timing/resource logs and file checksums. Larger region/event binaries remain in ignored local run directories and can be regenerated. `artifact_checksums.json` binds their bytes.

Forty-two native tests passed, including exact anchor identity, anonymous supported graphs through the same region API, exhaustive small grids, both cost scenarios, ties/invalids, immutable future outputs, prepared-bank context guards, earlier paged runtime regressions and a bounded synthetic trillion-offset grid. That synthetic test resolves only constant-grid addresses on a small fixture, not a trillion genuinely different programs. Linux/macOS source CI and a clean-clone offline build also passed; exact source/log details are retained separately.

## What remains open

This is a working fine-grid atom-neighborhood study with measured factorization and full backtest parity. It does not certify all possible indicators, arbitrary signed-domain rewrites, all numerical regimes, a new profitable strategy, or trillion-feature program throughput. Data-specific behavioral equality does not erase parameter identities or prove future equality. Numerical work, event detection, actual changed behaviors, and output still have costs. No eligibility gate or financial assumption was changed to manufacture the outcome.
