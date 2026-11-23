# Shared Filang engine verification

[Protocol](protocol.md) records the criteria fixed before the runs. This
report concerns geometry, study and binding behavior. Market prediction
was outside the workload.

## Inputs and host

- Apple silicon, 10 logical CPU cores, macOS 26.6.2. Rust 1.100.0 release
  binaries for both sides of the measured trials. Rust 1.63.0 for the
  repository's compatibility tests and lint.
- Baseline `d01a251f9746b368efa42b66f5615ea182a93404`.
- Pinned Query CSV SHA-256
  `21df2ed15f787479b3e871be0048b5721cd18e7e085881e4175975c8d056889a`.
  The 400-query corpus emitted by `corpus.mjs` had SHA-256
  `f29b74c06c07b2236f478e27b6dc21ec03b034b189cfc4b91597789e236de56e`.
- Recorded BTCUSDT 4h discovery CSV SHA-256
  `6dece8e4d91e98c83d80a0217907e024db656781cf3f0ffd61941e87c942aa98`.
  Geometry scoring was restricted to calendar year 2024, with its
  original causal prefix and one worker.
- Limen's 14,496-row fixture
  `tests/fixtures/spot_15m_20250101_20250531.parquet` had SHA-256
  `eb3392d7b4ccbd17a45ad9996e1c51d0f1b004c908a4a0264ff7efa959f1999a`.
  Its nine-column adapter output had SHA-256
  `b706a6d42c9845524e1355aacc133894aea18825fbaaba974b5a1d0b1aee2d2f`.

## Service contract evidence

- Query's WASM evaluator agreed with the pinned JavaScript evaluator on
  54 candidates, including recorded and chained geometry, named events,
  condition logic, sweeps, groups, exact ratios, outcomes and a newly
  installed pinned definition.
- Chromium ran the Composer handoff through the packaged module worker.
  The v1 packet retained its bytes. The pinned sample returned 772
  recorded matches, 1,463 chained matches and 4,828 pinned-relation
  matches. A dimensioned packet round-tripped and produced the same 204
  matches through Composer's count and Query's study text, with one
  unknown.
- Mac arm64 wheels installed offline in freshly created Python 3.10.16,
  3.11.6, 3.12.3 and 3.13.2 environments. Each ran the 720 engine vectors
  and compared 126 complete feature columns against an independent Python
  rank scan of all 14,496 real Limen slots. The runtime path used the
  packaged library and the Python standard library.
- The CLI and the browser bindings each ran the same 720 recorded and
  dimensions vector cases. Rust also covered all 32 dimension selections
  against direct scans with recording gaps and missing values.

## A1. Native price-only baseline

The first runnable comparison used candidate `767d313`. Two preceding
setup attempts stopped during key-probe linking and produced no timings.
The third used the same compiler and release panic and LTO settings for
both sides. Five adjacent rounds alternated order on a Mac with concurrent
desktop activity. [Raw native A1 trials](native-a1.json) retain every sample.

Observed compact-key digests, study response digests and frozen geometry
winners agreed across all runs. Native cold study load and geometry
preparation each took about 5% longer than the base median on this run.
Geometry sweep peak RSS was 10.7 MB against a 9.1 MB baseline median.
Two- and four-bar key metrics also missed the paired baseline p75. The
A1 universal native non-regression claim was **not supported**. The A4
protocol retains this result and changes the candidate to address it.

## A2. Live Cube workload

The initial public endpoint probe returned HTTP 401. After the owner
identified the host, the read-only SSH session captured the exact data
from the production loopback bridge backed by ClickHouse. Seventeen
archived level-4 MSCB blocks yielded 66,000 rows from 2025-01-04 12:00 UTC
through 2026-11-23 00:00 UTC. Query's existing MSCB decoder preserved the
delivered binary64 counters. [Capture and CSV digests](cube-source.json)

## A3. Retained klines with frame-aligned edits

The retained BTCUSDT parquet through 2026-11-21 had SHA-256
`844e1ac4be5221c4c80aa51a242427e44d22bac1ff7ab789304a206ebcb6a1c9`.
The last 66,000 rows adapted to the study's nine-column form had SHA-256
`58cd8c11a3966434a03d4f523cf5c33db662e8c2ba69f4a8d2091d23d44eb2d7`.
The same browser binary ran five fresh profiles on `34b6d26`. An earlier
setup stopped on a module MIME error before it reported a timing.

The independent recorded scans and the unobserved-key control agreed
with the engine in every profile. Across 1,500 input events, the time
to the frame containing the updated count was 16.6 ms p50, 18.2 ms p95
and 18.6 ms p99. Worker response with drawing and the DOM update was
1.9 ms p95. Peak retained WASM memory with eight prepared price readings
and five axes for each width was 266,272,768 bytes. The declared 16.7 ms
frame target was **not supported** for this dispatch cadence. A5 keeps
this cadence as a visible control.

The 400 price-only counts matched the original JS matcher for every
trial. The paired median was 11.7 ms for indexed worker calls and
224.3 ms for the original JS scan. The warm price-only browser latency
criterion from A1 was supported on this build.
[Raw browser A3 trials](browser-a3.json)

## A4. Price parsing and rank work

Measured candidate `34b6d26` against the same base. The two-bar compact-key
probe took 45.5 ms against 64.5 ms, and the ten-bar probe took 424 ms
against 852 ms. Geometry preparation and sweep elapsed time passed their
paired thresholds. Compact-key digests, full native study replies,
frozen geometry winners, observed catalogues and captured scored regions
were byte-identical across the paired runs.

Cold study startup missed the gate by 0.48 ms. Geometry preparation and
sweep resident memory also missed their thresholds. The joint claim was
**not supported**. A6 isolates the binding command before rerunning the
same native gates.
[Raw native A4 trials](native-a4.json)

## A5. Compact wide keys with varied pointer arrival

The same five-profile workload ran on the compact keys in `508c2e2`
with input dispatches spread across the frame. The independent scans and
the absent-pattern control agreed. Frame latency was 7.2 ms p50,
16.2 ms p95 and 17.4 ms p99. The worker-plus-DOM p95 was 1.5 ms.
Retained WASM memory fell 39%, from 266,272,768 to 162,529,280 bytes.
Both preregistered criteria were **supported** for this arrival pattern.
The separately measured A3 frame-aligned result remains above 16.7 ms.

Cold load took 38.9 ms at the median. First preparation for the eight
width and reading settings ranged from 4.9 to 376 ms at the median.
That work ran in the browser worker. Across the legacy 400-question
price control, all 29,812 matches agreed. Median elapsed time was
11.2 ms for the binding versus 226.5 ms for the JS scan.
[Raw browser A5 trials](browser-a5.json)

## A6. Native startup isolation

Candidate `508c2e2` retained byte-identical study, key and native geometry
outputs using the fresh-spawn measurement path. Cold study medians
were 5.59 ms on both sides. Warm study was 730 ms against 846 ms,
and sweep latency was about 1,328 ms on both sides. All paired latency
thresholds passed. Every RSS threshold passed except geometry
preparation, which used 9,060,352 bytes against a base p75 of
8,650,752 bytes. The joint claim was **not supported**.
[Raw native A6 trials](native-a6.json)

## Recording parity

The wheel compared four-bar chained g1 identities at the 14,493 complete
common windows in the pinned Query and Limen fixture recordings. All
matched on price. The Query fixture has no counters. A separate comparison
of optional dimensions requires both files to contain their delivered
counters, including the Cube export for live-source parity.
[Source comparison](source-parity.json)

## A7. Streamed market CSV and compact bank preparation

This attempt preserved every captured count and result digest and reduced
key probe RSS from roughly 3.5 MB to 2.8 MB. Geometry preparation still
missed latency and peak RSS. The candidate was 8.49 MB against a base
p75 of 7.09 MB in that stage. Native study peak RSS also missed by
81,920 bytes. The joint claim was **not supported** and the broader
parser and bank changes were removed. A8 addresses the repeated
whole-executable buffer in the native preparation path.
[Raw native A7 trials](native-a7.json)

## A8. Bounded native executable fingerprint

Candidate `def7f2f` reused the fingerprint computed with the fixed-size
file hasher. Native geometry preparation fell from a paired baseline
median of 165.5 ms and 8.01 MB to 137.3 ms and 5.64 MB. Byte parity still
held across every artifact. Sweep wall time, study RSS and four-bar
probe RSS missed their respective gates. The overall claim was
**not supported** in this five-pair run.
[Raw native A8 trials](native-a8.json)

The live Cube and retained Limen recordings agreed on all 65,901
complete common four-bar chained windows in a direct source
comparison. This held for price and for the combined key with all
five axes. [Price keys](cube-limen-price.json) · [All axes](cube-limen-dimensions.json)
