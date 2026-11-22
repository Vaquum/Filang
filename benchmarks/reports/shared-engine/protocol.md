# Shared Filang engine performance protocol

## A1. Compatibility on existing price-only workloads

**Hypothesis.** Price-only geometry key encoding, native study evaluation and
the native geometry preparation and pair scorer retain parity, latency and
peak resident memory compared with `d01a251f9746b368efa42b66f5615ea182a93404`.
The browser binding also retains or improves the current JavaScript study
latency for equivalent warm, exact price-only questions.

**Method.** Build the base and candidate in release mode with one compiler on
one quiet Apple-silicon machine. Use the pinned Query recording and replay
the same two-, three- and four-bar question corpus from #73. Use the native
geometry smoke configuration on the same pinned native recording for the
existing prepare and pair workload. Compare timestamp-level truth and
validity, canonical text and compact words, and native coverage and scored
outputs. When output includes engine identity or timing, compare all
semantic fields. Time cold preparation and warm queries separately. Collect
at least five alternated rounds per side. Keep all rounds and peak RSS from
fresh processes. Run in Chromium for the browser comparison with the same
recording and equivalent count output. Support requires parity and the
candidate median for every declared latency and peak-RSS metric at or
below the 75th percentile of its corresponding baseline. Retain all
failures and measurements.

## A2. Exact interactive exploration

**Hypothesis.** With the relevant window and dimensions prepared, changing
a mark across a rank boundary or toggling an axis delivers the exact count
to the browser in one 60 Hz frame at p95. Work on the edit depends on
observed positions in the recording.

**Method.** Replay warmed edits on the real Cube recording spanning at least
60,000 15-minute bars and report the recording digest. Exercise both
readings, width changes, ties and all five dimensions, retaining undefined
axis values. Use a large separate synthetic fixture to exercise wide
windows and sparse, dense and unobserved exact patterns. Compare answers to
a direct per-window reference scan, including unknown counts. Measure from
dispatch of the input action, through WASM to completion of the browser
frame containing the updated count. Record p50/p95/p99 and maximum from at
least 300 edits over five fresh page runs on Chromium, including binding
overhead. Report cold load and newly prepared width/axis latency separately
and report resident memory. The decision criterion is parity and warm p95
at or below 16.7 ms on the real recording. A synthetic run cannot establish
the real-recording criterion.

## A3. Interactive exploration on retained spot klines

**Hypothesis.** The engine returns exact matches on 66,000 original 15-minute
BTCUSDT klines with all five counter-derived axes enabled. Warm edits on a
prepared recording complete by the next browser frame at p95 (16.7 ms).
This is a separate performance attempt because the live Cube bridge requires
authenticated export and the retained Limen counters have different precision.

**Method.** Use the last 66,000 rows of the retained 15m kline parquet through
2026-11-21. Record the parquet and normalized CSV SHA-256. Exercise widths
2, 4, 12 and 24, alternating recorded and chained reads, price-only edits,
and changes to axis selections. Run 300 sequential edits per page across
five fresh Chromium processes. Time edit dispatch, WASM worker response
and the first animation frame after updating the visible count. Check
sampled indexed answers against a direct comparison oracle on the same
rows, including unobserved keys. Report cold setup separately, p50/p95/p99
and maximum, and the worker's final WASM linear-memory size. The performance
criterion is p95 at or below 16.7 ms with exact parity. This gives no
verdict on the real-Cube criterion in A2.

## A4. Restore the native price-only budget

**Hypothesis.** Parsing recording fields in place, hashing each source once
and merging the sorted endpoints for one- and two-bar windows restore the
price-only runtime and resident-memory budget. Removing index tie-breaking
from the general encoder preserves each tie class and its exact output.

**Method.** Repeat the same paired native control from A1 with the updated
code on the same host and Rust version. Retain the A1 measurements. Compare
canonical compact-key digests, every worker response and the scored geometry
winner. Record the actual workload and host load. The decision criterion is
parity and each candidate median at or below its paired base p75.
