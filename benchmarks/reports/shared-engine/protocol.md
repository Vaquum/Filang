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

## A5. Compact wide indexes and exercise pointer arrival across a frame

**Hypothesis.** Storing wide observed ranks as exact 16-bit fields reduces
the final WASM linear memory by at least 25% on A3's workspace. The
compact engine also updates on the first animation frame at p95 within
16.7 ms when edit dispatches are spread across the frame interval.

**Method.** Use the same retained recording, widths, marks, axes, reference
checks and Chromium binary as A3. Keep A3 as the frame-aligned arrival
control. For A5 insert a deterministic 0–15 ms delay before each input
dispatch, outside the timing boundary. Run five fresh profiles with 300
edits each. Require full count parity in the sampled oracles, the memory
reduction against A3 and p95 at or below 16.7 ms. Retain both workloads.

## A6. Isolate the legacy native workloads from binding startup

**Hypothesis.** Linking the engine command separately keeps the study
compiler and binding runtime out of existing native commands. Loading
the recording's validity prefix in the row loop reduces cold study work.
Together these changes meet the existing price-only timing and RSS gates
with identical outputs.

**Method.** Repeat A4's source, work, repetitions and acceptance thresholds.
Run measured child processes with spawn file actions so the measured
executable begins with fresh process memory. Retain A4's full samples.
Compare the same stage boundaries and byte digests, including the scored
region and catalogue files.

## A7. Reduce native preparation's retained input and keys

**Hypothesis.** Stream the market CSV through one reusable line buffer and
retain compact bank keys while grouping observed positions. This brings
geometry preparation peak RSS within the A6 baseline without regressing
any price-only latency or changing any result.

**Method.** Build both sides in release and repeat A6's interleaved
fresh-process workload. Compare full native study replies, compact key
digests, observed catalogues, captured score regions and frozen winners.
Require parity and the same paired p75 gates for every measured latency and
resident-memory metric.

### A2 execution trace after authorized source access

The production bridge is read through the authorized host. Freeze the
latest fully archived 66,000 bars at level 4 before running locally. Use
Query's existing binary decoder and preserve the delivered binary64
counters. Replay the A5 varied-arrival workload with the same p95 gate,
recording width, marks, read mode, axes, independent count parity and
cold preparation. The A3 retained-recording frame-aligned control stays
in the record. Compare the Cube capture with Limen on common closes
and record source differences separately from binding parity.

## A8. Stream and reuse the native executable fingerprint

**Hypothesis.** Hashing the executable through the existing fixed-size
file hasher and reusing that fingerprint within a geometry run restores
the native preparation budget. This removes the whole executable buffer
and the second hashing pass without changing the receipt digest.

**Method.** Start from A6's market parser and bank preparation. Retain A7's
negative record and replace its broader changes with this narrower change.
Repeat A6's fresh-process baseline, inputs, five alternating rounds,
captured result and coverage parity, and unchanged p75 gates.

## A9. Independent native replication

**Hypothesis.** The A8 binary preserves native latency and RSS under
an independent, larger paired replay. The five-pair A8 trial recorded
a geometry prepare improvement alongside three missed gates.

**Method.** Reuse the exact A8 baseline and candidate executables and
inputs. Run 15 alternating fresh-spawn pairs, with the same workload,
parity checks, timer boundaries and p75 thresholds as A8. Keep A8
and A9 in the report. Treat this run as a replication of the measured
platform and inputs.
