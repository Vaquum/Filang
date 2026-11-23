# g1 radius exact-path proof

The baseline is `1efbb8652f8136cb3c38a7400ebb59ad8455ecd8`, with
adaptive postings. Both WASM builds used the same toolchain and
66,000-slot Cube recording. Its SHA-256 is
`4602501f922cc699cbac4d602c81cbc8e5b737d2c0e7648086923d7cb708baf4`.
Five alternating fresh-process pairs on Node 23.10.0 ran five samples
of 8,000 calls for each prepared key.

| Prepared key | Baseline median, µs | Radius-zero median, µs |
| --- | ---: | ---: |
| One bar | 2.289 | 1.864 |
| Two chained bars | 1.869 | 1.863 |
| Two recorded bars, all axes | 3.750 | 3.585 |
| Eleven chained bars, delta | 3.773 | 3.763 |

The fingerprints of the canonical codes, counts, positions, ternary
classifications and serialized Study replies match across all ten runs.
The explicit zero path uses the same exact geometry operation. All four
timings are within the planned 5% non-regression band. The one-bar
difference is measured variation on a microsecond workload.

For a positive radius of two, the warm observed-neighbourhood summaries
took 1.112 ms (one bar), 0.147 ms (two chained bars), 0.734 ms (two bars
with all axes) and 9.504 ms (eleven chained bars with delta). The
[raw samples](zero-a1.jsonl) also contain radii one and eight. The direct
WASM timings include binding work and exclude recording load and
preparation.

Use the [protocol](protocol.md) and
[radius-zero-bench.mjs](../../../bindings/verify/radius-zero-bench.mjs)
with the baseline and candidate browser build directories, the pinned
CSV, and the corresponding `base` or `candidate` mode.

## Integrated replications

A2 and A3 retained all exact fingerprints. Relative to the original
baseline, the one-bar median was 5.11% higher in A2 and 5.21% higher in
A3, above the 5% limit. The other keys remained in band. The
[A2](zero-a2.jsonl) and [A3](zero-a3.jsonl) samples retain those misses.

A4 uses the same Query, Composer and adaptive-postings source as the
radius build, with radius absent from baseline commit
`9f82b48b0bb3244ccf9c5b3bedb6eac46549930b`. This isolates the change.
All fingerprints agreed and all four medians met the planned band.

| Prepared key | Baseline median, µs | Radius-zero median, µs | Change |
| --- | ---: | ---: | ---: |
| One bar | 1.541 | 1.614 | +4.75% |
| Two chained bars | 1.571 | 1.618 | +2.97% |
| Two recorded bars, all axes | 3.193 | 3.234 | +1.26% |
| Eleven chained bars, delta | 3.270 | 3.325 | +1.67% |

See the retained [A4 samples](zero-a4.jsonl). The real-browser [Query
receipt](query-chromium.json) widened a pinned two-bar pattern from 1,463
to 2,666 occurrences at radius two and showed the distance bins.
[Composer's existing worker workload](composer-chromium.json) also
passed with radius available. Its longest search took 1.298 s, its
largest progress gap was 9.8 ms, and both replacements cancelled in
under 11 ms. The shared vectors check dimension-aware Composer and
the native CLI, browser and Python bindings. Limen's offline wheel
reproduced 126 features across 14,496 real bars on Python 3.10–3.13.
