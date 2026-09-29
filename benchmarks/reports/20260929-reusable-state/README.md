# Reusable full-risk state and shared paged runtime — 2026-09-29

## What changed

One bounded native page executor now accepts known-indicator catalogs and parameter
families, streamed ordinary expressions, and the actual versioned open generator.
It retains full backtest state across program/page changes, shares event discovery
across fee scenarios, supports reversible sparse updates, and falls back to full
chronological replay for dense changes. It requests all ten original metrics.

This is a systems/parity delivery, not new financial winner selection, universal
TA-Lib coverage, or a trillion completed evaluations. The old `walk-search`
selection-policy orchestration remains versioned and unchanged; its actual program
generator now also feeds the common evaluation interface. Known and open programs
are not routed to separate special-purpose numerical kernels.

Measured native source: `a314e8decb6f403d99371245d29898fc1bed752c`. Executable SHA-256:
`cf4c1b0cb18265e4ccf885a558f9f553f8e370ee5eb2316949e7b0ea15c545eb`. All recorded benchmark runs used a clean worktree.
Data SHA-256: `7844ae10462b6ddd6b17ea21a0626153b6786cbb0fd828bf2593e574a7578625`. Source and stored strategy results are unchanged.

## Matched measurements: three distinct questions

**Distinct programs:** SMA-distance periods 2 through 2,048, one fixed greater-than-zero
readout per period, two fee/slippage scenarios: **2,047 different numerical period
programs and 4,094 full metric sets**. Increasing threshold count is not used to
inflate the feature count.

**Weak reuse:** 1,023 known SMA-period programs with alternating direction. This
makes consecutive positions deliberately dissimilar. It is a systems control, not
a search for a new topology or market winner.

**Threshold families:** the unchanged radius-four neighborhood with **252 requests,
239 distinct numerical roots and 120,832 full metric sets**. Original anchors are
retained. These are readout/scenario metric sets, not 120,832 different features.

Three fresh-process repetitions per execution path, with rotated path order.
Apple M1 Max, 64 GiB host, Rust 1.63.0, f64, **one native worker**. No CPU pinning;
OS caches were not flushed. Times include startup, data loading, planning,
generation, feature calculation, full metrics and all-result writes. Every timed
metric output matches its native reference within the pre-existing envelope;
trade and sample counts match exactly. Verification runs are outside the timing.

| Axis | Path | Median whole-process time | Min–max | Maximum RSS |
|---|---|---:|---:|---:|
| programs | `replay` | 0.355082 s | 0.326974–0.370692 s | 29.2 MiB |
| programs | `rebuild` | 0.769212 s | 0.739670–0.773406 s | 33.2 MiB |
| programs | `events` | 0.851661 s | 0.850382–0.854998 s | 32.1 MiB |
| programs | `delta` | 0.238579 s | 0.204865–0.241690 s | 29.8 MiB |
| programs | `auto` | 0.199683 s | 0.198800–0.202044 s | 29.3 MiB |
| low_similarity | `replay` | 0.208599 s | 0.207306–0.211278 s | 31.1 MiB |
| low_similarity | `rebuild` | 0.453221 s | 0.445908–0.454864 s | 29.8 MiB |
| low_similarity | `delta` | 0.403317 s | 0.398464–0.420804 s | 30.1 MiB |
| low_similarity | `auto` | 0.168635 s | 0.161973–0.171913 s | 29.4 MiB |
| thresholds | `family` | 2.273233 s | 2.251717–2.317479 s | 57.4 MiB |
| thresholds | `state-legacy` | 2.427106 s | 2.372925–2.542298 s | 56.2 MiB |
| thresholds | `state-events` | 1.163623 s | 1.062429–1.189827 s | 57.6 MiB |
| thresholds | `state` | 1.017575 s | 1.003634–1.056966 s | 57.0 MiB |

The most useful comparisons are:

- **Distinct program axis:** native replay 0.355082s to adaptive
  state 0.199683s, **1.778x**.
- **Threshold axis:** previous already-factorized family engine
  2.273233s to new shared paged state
  1.017575s, **2.234x**.
- **Weak-reuse axis:** native replay 0.208599s versus
  adaptive state 0.168635s,
  **1.237x**. Forced delta
  is slower (0.403317s); this negative result is retained.

`state-legacy` uses the same new paged numerical/output infrastructure with the old
per-series/per-scenario full-risk scorer. `rebuild` rebuilds tree state explicitly;
`replay` is ordinary chronological scoring. All paths use actual native work, not
a deliberately uncached Python indicator for every threshold. There is no new
end-to-end TA-Lib timing claim in this report; the external tool is used for
independent parity verification. Do not multiply these ratios by older results.
Short runtimes and three repetitions remain limited measurements, not universal
latency bounds or a trillion-scale extrapolation.

## Actual execution work across different programs

A representative adaptive distinct-period run processes 2,047 requests
across 64 numerical pages. **98.53%** of transitions change at most 1% of
8,194 positions. This is measured for this family, data and traversal order, not
an assumption imposed on arbitrary neighboring programs.

| Physical work | Count |
|---|---:|
| Exact nonconstant behavior reuse | 236 |
| Sparse state updates | 1,808 |
| Tree rebuilds | 1 |
| Shared chronological fallbacks | 2 |
| Changed bits detected | 21,877 |
| Sparse changed bits decoded | 16,268 |
| Bitmap words compared | 264,063 |
| Incremental interval joins / splits | 2,658 / 1,364 |
| Cost-scenario leaf updates | 104,488 |
| Cost-scenario tree merges | 320,340 |
| Shared-mask full-replay periods | 16,388 |
| All-off / all-on requests | 0 / 0 |

The replay control visits 33,546,236 interval/scenario combinations. A tree
merge, a leaf update, a mask comparison and a sequential visit have different
costs; their count ratio is not presented as a speedup.

In this representative adaptive run, numerical work takes
0.128335s and scoring
0.024326s. Detection
(0.018130s) is already included in scoring.
The optimized distinct-period axis is now primarily limited by numerical work;
the threshold-heavy axis has a different bottleneck. Counters are retained for
every measured run rather than generalized from one workload.

Every weak-reuse transition chooses chronological fallback. It does not wastefully
perform per-bit interval edits or rebuild a large tree. An initial uncommitted
engineering probe exposed that dense tree rebuilding regressed against replay;
the published algorithm includes a generic replay fallback. Final slow variants
remain in the benchmark, rather than being removed from the reported comparison.

## Full-risk correctness and independent reference coverage

The unchanged pinned input contains 14,412 four-hour bars. Evaluation is
2023-01-01 through 2026-09-28 exclusive, with the same eight fold boundaries and
14 explicitly flat inter-fold intervals, for 8,194 scored intervals. Primary costs
are 5 bps fees plus 5 bps slippage per side; stress is 10+10. The cash-funded
next-open execution model is still idealized: no new capacity or latency claim.

The anchor gate passes all **88 primary/stress cases** over 18 construction
requests. Validity, threshold masks and trade events agree exactly. All 16 stored
legacy fixed-control metric sets reproduce. Maximum feature discrepancy is
3.6432190597679437e-10; metric discrepancy
3.922195901395753e-12; complete equity/trade-trace discrepancy
7.9047879353311146e-14. All 88 traces are checked with independent
explicit cash/share accounting. These checks are not based on stored answers in
native kernels.

The wider SMA proof checks every captured value and mask for **2,047
programs** against pinned TA-Lib wrapper 0.6.8 / C 0.6.4: measured value discrepancy
**0.0**, mask disagreements **0**.
All **4,094 full metric sets** match the independent NumPy
chronological backtester, with maximum discrepancy
1.1795009413617663e-12. An additional
32 explicit cash/share replays check
every 128th period program under both scenarios. These systematic subset checks
are not described as a separate cash/share replay for every metric set.

The captured threshold proof compares every numerical output and requested mask
for 252 construction requests / 120,832 full metric sets. Mask disagreements:
**0**. Maximum metric discrepancy:
4.8885340220294893e-12. All ten metric columns are checked, not a
winning subset or a cheap moment proxy. The proof source and binary are the same
as the measured source; verification artifacts and captured-file checksums remain
separate from timing.

The numerical envelopes are unchanged: feature atol=1e-8/rtol=1e-9, metric
atol=1e-7/rtol=1e-9, trace atol=1e-8/rtol=1e-9. Decisions and counts must agree
exactly. Floating-point reduction regrouping is not claimed bit-identical in
general. No new TA-Lib API is universally certified; coverage expands to the
explicitly tested SMA period range and general execution-state fixtures.

## Generic mechanism, not indicator-specific code

The executor sees ordinary typed graphs, addresses and rules, not indicator names.
Paired moments and recurrence lanes remain general numerical operations. Exact
packed positions drive shared transition plans across every cost scenario.

A segment stores prefix/suffix active-run returns and the sum of active-run net
returns. Touching fragments combine through a+b+a*b. Together with the ordered
log-equity summary, this permits both trade joins and splits while retaining
mean completed-trade return and maximum drawdown. No insertion-only union-find,
per-program complete equity materialization, or different risk metric is required.

Sparse masks reuse dirty tree structure; dense masks use chronological replay.
The state survives numerical page boundaries. Every cost scenario retains its
own return/path-risk values; shared scheduling does not pretend all scenarios
have identical drawdown. Numerical profiles, original sample validity and source
history are not relaxed for speed.

## Bounded output and memory

Summary mode computes and incrementally hashes the same metric records as exhaustive
mode, then discards them. Its digest matches the 2,047-program exhaustive output;
it writes no metrics.bin and retains a fixed domain contract. It is not a bound,
pruning result or unvisited region masquerading as completed evaluations.

These separate probes are **one fresh run per size**, not the repeated main timing:

| Period programs | Whole-process time | Maximum RSS | Metric bytes written |
|---|---:|---:|---:|
| 127 | 0.055819 s | 20.9 MiB | 0 |
| 511 | 0.081387 s | 28.2 MiB | 0 |
| 2,047 | 0.189530 s | 29.4 MiB | 0 |

Page size and budgets remain fixed. The execution-state payload for this context
is 9,765,456 bytes. Numerical, result-block and state
budgets are distinct from process RSS. Generation is bounded by page size;
unknown global uniqueness is not replaced by an unbounded hash set.

## Build, integration and reproduction

A clean clone passed **37 Rust tests**, locked/offline release build, formatting
and warning-free Clippy on Rust 1.63.0. Source-head Ubuntu and macOS CI passed;
the retained CI JSON identifies exact source/check URLs. Later evidence-only
commits require their own final-head CI before merge. No native third-party
runtime dependency was added.

Tests include arbitrary flips/splits/joins, multiple costs, dense/sparse transitions,
bitmap tails, both directions, page-size changes, future-data perturbation,
summary/exhaustive digest equality, and actual open-generator programs passed
through this same Executor. The near-trillion-endpoint test executes only its
bounded page, not a trillion programs.

Contracts and commands: `docs/REUSABLE_STATE.md`. Current local gate:
`runs/state-v04-parity/gate.txt`. Benchmarks: `runs/state-v04-benchmark`.
Wider captured proof: `runs/state-v04-program-proof`; threshold proof:
`runs/state-v04-threshold-proof`.

Raw data and large captured histories stay in ignored runs/. This report retains
manifests, source/data/executable identities, verification results, complete work
counters and timing logs. `artifact_checksums.json` identifies larger proof files.

The delivery demonstrates less full-backtest work across genuinely different
period programs, while keeping one common execution path available to arbitrary
atom sources. Numerical calculations, comparisons, distinct-program traversal and
output still have real costs. It does not establish a trillion completed feature
sweep, universal constant marginal cost, universal reference coverage, or a new
profitable trading strategy.
