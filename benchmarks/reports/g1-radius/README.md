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
