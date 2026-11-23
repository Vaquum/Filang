# Composer search protocol

## A1. Real-history matching and worker yield

Use the five BTCUSDT timeframes published for Composer, pinned by revision,
parquet SHA-256, and row count. Run the queries in Composer's
`checks/search-performance.mjs` at `bd6a0ba`, with the documented partition
between matching and downstream outcome calculations. Use the same data
and query for the JavaScript oracle and Filang. Check exact and held
counts, selections, their chained placements, half-flips, nearest scores
and the ordering of distinct results. Check the one-comparison neighbours
and their counts before outcome statistics. Run the pinned synthetic
checks for stretch, holds and the nearest formula as independent oracles.

Measure elapsed search time and the longest interval without a yield on
loaded data, including request and response encoding. Use an actual
browser worker with cold and repeated searches, and record per-run
versions, machine, input hashes and samples. Require every search to
finish in under five seconds with no interval of 100 ms between yields.
Replace the five- and twenty-bar stretched searches after 10 ms.
Require the superseded work to yield within 100 ms, with no stale result
emitted. Report source load separately.

## A2. Prune stretch placements with remaining colour cost

Retain A1's comparison and acceptance bounds. Precompute the lowest
remaining half-colour cost for each placement and spare count. Use it
only as a lower bound for score, or to prove no locally valid placement
exists. Keep the earliest held placement even when its score cannot rank.
Compare A2 with both the pinned matcher and the unpruned candidate on
the scenarios the latter completes. Repeat the same five- and twenty-bar
replacement checks through Chromium's worker.
