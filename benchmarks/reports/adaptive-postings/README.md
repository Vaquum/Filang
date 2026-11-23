# Adaptive postings verification

[A1 protocol](protocol.md) · [Native samples](native-a1.json)

The release candidate `72af9fd` was compared with `9ae049d` in
five alternating fresh-process pairs on Apple silicon. Both builds
used Rust 1.100.0 with release LTO. The Cube CSV SHA-256 was
`4602501f922cc699cbac4d602c81cbc8e5b737d2c0e7648086923d7cb708baf4`.
Counts, bounded position pages and ternary classifications agreed
at every tested width in every pair.

## Native results

| Workload | Preparation, base → candidate | Warm count, base → candidate | Peak RSS, base → candidate |
| --- | ---: | ---: | ---: |
| Dense, 1 million slots, 24 bars | 901 → 904 ms | 5.689 → 0.011 ms | 167.10 → 139.82 MB |
| Cube, 66,000 slots, 2 bars | 13.20 → 14.23 ms | 22.643 → 0.986 ms | 15.14 → 14.25 MB |
| Cube, 66,000 slots, 4 bars | 32.83 → 34.54 ms | 0.117 → 0.074 ms | 22.32 → 22.97 MB |
| Cube, 66,000 slots, 24 bars | 312.98 → 311.00 ms | 0.150 → 0.170 ms | 85.46 → 85.57 MB |

Numbers are medians. The dense trial times a present and an absent
query. Each Cube corpus has 256 observed keys and one absent key.
The runner records process high-water RSS and measures preparation
after loading the recording.

The native criteria passed. The 24-bar Cube corpus had a 0.020 ms
increase in its median and stayed inside the 0.182 ms gate.
Using the frequencies in the frozen Cube tape, the posting payload
at two bars falls from 1,583,976 to 374,160 bytes under the promotion
rule. At four bars it falls from 1,583,928 to 1,379,316 bytes. At
24 bars the keys remain sparse. Payload excludes hash keys, container
metadata and allocations outside the posting values.

## Chromium results

Five fresh profiles ran 1,500 varied-arrival edits on the frozen Cube
recording after preparation. All counts matched the independent oracle.
The pooled median was 7.2 ms to the displayed count, p95 was 16.3 ms,
and p99 was 17.2 ms. Worker plus DOM p95 was 1.6 ms. The 16.7 ms
criterion passed. Cold CSV load was 40.6 ms at the median and peak
retained WASM linear memory was 160,169,984 bytes.
[Readable summary](browser-a1.json) · [Complete browser samples](browser-a1.json.gz)
The archive expands to the original runner output. Its SHA-256 is in the summary.

## Reproduction

Build both checkouts with `cargo +1.100.0 build --release --locked --offline`.
The paired runner links against each release library.

```sh
python3 benchmarks/reports/adaptive-postings/native.py "$BASE" "$CANDIDATE" "$CUBE_CSV" native.json
```

Replay the varied-arrival Chromium workload with the candidate browser
package using the [existing Cube capture and replay instructions](../shared-engine/README.md#repeat-the-real-cube-trace).
Use five fresh profiles, alternate corpus execution order, and summarize
the raw profiles with `benchmarks/reports/shared-engine/browser.py`.
