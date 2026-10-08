# Complete bar geometry: measured execution and verification

On BTCUSDT four-hour candles for **2024**, the final ten-worker geometry sweep
completed in **14.702466 seconds median over three runs**, with **60.00 MiB maximum
peak RSS**. The matched scalar leaf-pair run took **107.247424 seconds**, measured
once. Their **7.295× elapsed-time ratio is descriptive: one scalar observation
versus a three-run parallel median**. Both cover **55,851,217,669,989,216 declared
strategy addresses**. Certificates compute **45,134,484 native metric regions**
covering **87,925,122 physical state-pair products**; the declared addresses retain
exact multiplicities, rather than requiring that many independent backtests.
[Ten-worker measurements](year-workers10.json), [scalar measurement](year-leaf.json).

Independent verification checks every year-bank membership, full weighted task
domains, and all **192 retained task winners per run**. It does **not** independently
replay every year-region metric. A separate captured January control does check
every region, including all **786,210 scalar leaf results** and **420,236 certificate
results** per run. The frozen winning program reproduces its ten metrics on 2024;
on the later retrospective replay it returns **−3.491658% net**. This report is
systems evidence, not evidence of a validated trading edge.
[Year audit](year-verification.json), [captured audit](control-verification.json),
[later replay](later-replay.json).

## Environment and measurement policy

Measurements were made on an **Apple M1 Max, 10 logical CPUs, 64 GiB RAM**, running
macOS 26.6.2 arm64. Native `auto` selected NEON. The before-scheduler source was
`eef9553`; the final Rust source was
`be90fb50522ef782bf875541098094ff65d9c246`. Binary SHA-256 identities are:

| Build | Binary SHA-256 |
|---|---|
| Before scheduler | `55fd8c72c77fcad7a240de818b29422316c0a7bc07ceb58fa6c98df7b7640952` |
| Final | `4dded390c5ea711408452a0e705333dd2dd9f181b20d2caa38085b01fae9e717` |

The [benchmark driver](../../../scripts/benchmark_geometry.py) times the entire
native subprocess, including preparation, hashing, and durable output.
Independent verification runs afterward, outside that timer. RSS comes from
`wait4` for that native child; verifier memory does not enter the next native
measurement. Tables report the **maximum** peak RSS across repeats. CPU time and
elapsed time are retained separately; ten workers do not imply continuous use
of ten CPUs. [Linux and macOS CI passed for the final Rust revision](https://github.com/Vaquum/Filang/actions/runs/37786701783);
[local tests](native-tests.txt) and [Clippy output](native-clippy.txt) are retained.

## Exact data and language scope

Both principal configurations use BTCUSDT spot OHLCV at 14,400-second intervals,
cash-funded long/flat positions, decisions at the close, execution at the next
open, terminal liquidation, and **10 bps fee plus 10 bps slippage per side**.
Dates below are UTC, with the end excluded.

| Input and scoring | Captured January | Full year |
|---|---:|---:|
| Start | `2024-01-01` | `2024-01-01` |
| End, exclusive | `2024-02-01` | `2025-01-01` |
| Input candles, including history | 8,592 | 10,602 |
| Candles before the scored start | 8,406 | 8,406 |
| Scored decisions | 184 | 2,194 |
| Region output | Captured | Summary |

The final two candles supply execution prices and are not scored decisions.
Preparation scans the complete causal prefix and applies qualifiers before
slicing the scored timeline. Input must end exactly at the configured boundary.
The [control configuration](control-config.cfg) and [year configuration](year-config.cfg)
retain all settings, including 64/128/256/128 MiB numeric/bank/tree/preparation
budgets, `task_states=128`, and `max_task_nodes=100000000`.

```ini
mode=oriented
windows=0,1,2;0,2,4
qualifiers=plain,persist:2,recent:3
rules=(and s0 s1);(or s0 s1);(and s0 (not s1))
allow_same_bank=false
```

Lags identify the current candle first. Each oriented three-candle window has
**32,160,252 legal complete patterns**, including absent wicks, zero bodies,
flat candles, exact ties, direction, and relations between nonadjacent candles.
With three qualifiers, each bank contains 96,480,756 logical conditions. The two
ordered bank pairs and three rules therefore give:

```text
2 × 3 × (32,160,252 × 3)² = 55,851,217,669,989,216
```

The domain is the complete legal geometry universe for these declared windows
and rules. It contains no numerical threshold grid. The native checked-`u128`
chain-merging counter and independent Python occupied-level inclusion/exclusion
counter agree. The [formal reference](../../../docs/BAR_GEOMETRY.md) defines the
minimal primitives, completeness boundary, canonical grammar, and counting proof.

## Logical coverage and physical work

Each valid raw window matches one complete pattern. Preparation records every
observed identity and one symbolic complement carrying the count of all
unobserved identities. Those absent identities are all false on the fixed causal
prefix. Qualified predicates with equal truth **and validity** on the scored
timeline share a dictionary state while retaining their memberships and weights.
This equivalence applies to the measured timeline; exported winners freeze one
explicit pattern per slot.

| Preparation | January `0,1,2` | January `0,2,4` | Year `0,1,2` | Year `0,2,4` |
|---|---:|---:|---:|---:|
| Causal windows encoded | 8,588 | 8,586 | 10,598 | 10,596 |
| Observed full patterns | 5,872 | 7,192 | 6,771 | 8,657 |
| Unobserved identities | 32,154,380 | 32,153,060 | 32,153,481 | 32,151,595 |
| Physical pattern representatives | 5,873 | 7,193 | 6,772 | 8,658 |
| Pattern/qualifier memberships | 17,619 | 21,579 | 20,316 | 25,974 |
| Distinct scored states | 359 | 365 | 3,621 | 4,047 |

“Observed” includes earlier causal history. The resulting physical pair domains
are `6 × 359 × 365 = 786,210` for January and
`6 × 3,621 × 4,047 = 87,925,122` for the year.
[January bank audit](control-verification.json), [year bank audit](year-verification.json).

A certificate proves that a product of dictionary-state sets has one position
path. One full-risk metric region then carries that product's exact logical
multiplicity. The native engine can also reuse execution state between paths.
Thus a metric region counts a native metric result, not necessarily a separate
chronological row-by-row replay. Disjoint weighted coverage reconciles the full
logical domain without materializing quadrillions of masks.

## Captured control and scheduler comparison

Each build ran all four modes three times with identical input, domain, costs,
and captured-output policy. Every run has 24 tasks and passed exhaustive captured
verification. Times are medians; memory is the final build's maximum across its
three repeats. [Before records](control-before.json), [final records](control.json).

| Mode | Workers | Regions | Before, s | Final, s | Final RSS, MiB |
|---|---:|---:|---:|---:|---:|
| Scalar leaf pairs | 1 | 786,210 | 2.349906 | 2.243861 | 9.14 |
| Scalar certificates | 1 | 420,236 | 1.664559 | 1.628625 | 9.20 |
| NEON certificates | 1 | 420,236 | 1.628940 | 1.707560 | 8.45 |
| NEON certificates | 10 | 420,236 | 0.915699 | 0.964602 | 10.41 |

Final parallel certificates are **2.326× faster** than the matched final scalar
leaf median. Certificates reduce native region count by **46.55%**. The final
single-worker NEON result is slower than scalar certificates on this control;
the measurement does not establish a SIMD advantage here.

The scheduler change permits worker batches to cross rule-template boundaries
while retaining template-major task IDs and the active tree pair. One matched
24-task before/after comparison found every captured boxes file byte-identical,
checkpoint payloads identical apart from the changed engine context, and
`best.json` byte-identical. The [equivalence receipt](scheduler-equivalence.json)
covers these 24 task artifacts, separately from the 24 timing invocations.

**No scheduler speed gain was observed:** its parallel median rose from 0.915699
to 0.964602 seconds, approximately **5.34%**. The evidence establishes result
preservation for that change. All 24 individual captured verification receipts
are retained under [before](verification/control-before) and
[final](verification/control).

## Full-year timings

All seven final year runs use the same configuration, binary, and summary-output
policy. Every certificate run resolves 45,134,484 regions across 192 tasks.
[Eight workers](year-workers8.json), [ten workers](year-workers10.json),
[scalar leaf pairs](year-leaf.json).

| Mode | Repeats | Elapsed seconds | Median, s | Maximum RSS, MiB |
|---|---:|---|---:|---:|
| Scalar leaf pairs, 1 worker | **1** | 107.247424 | Single observation | 39.23 |
| NEON certificates, 8 workers | 3 | 16.126447, 15.450713, 18.618734 | 16.126447 | 61.66 |
| NEON certificates, 10 workers | 3 | 14.294086, 14.702466, 16.233504 | 14.702466 | 60.00 |

The ten-worker median is **8.83% lower** than the eight-worker median in these
three-run samples. Its average CPU usage ranges from 4.50 to 5.27 CPU equivalents.
The scalar-to-ten-worker ratio of 7.295× combines certificate reduction,
execution reuse, backend differences, and parallelism; it is not an isolated
scheduler measurement or a median-to-median estimate.

The earlier [single pilot](year-pilot.json) took **16.170249 seconds**, with
**58.80 MiB RSS**. Its [native summary](year-summary.json) records 90,268,776 tree
node-pair visits, 13,639,142 certified nonleaf products and 31,495,342 leaf regions.
The 45,134,484 total regions are **48.67% fewer** than the 87,925,122 physical pairs.
These counters are stable across the repeated certificate runs.

The [seven-run equivalence receipt](year-equivalence.json) confirms equal logical
coverage, the same concrete selected patterns, agreement of all ten winning
metrics, and agreement with frozen same-period replay. It does not assert
independent metric equality for every uncaptured region. All seven verification
receipts are retained under [eight workers](verification/year-workers8),
[ten workers](verification/year-workers10), and [scalar](verification/year-leaf).

## Independent verification and values above `u64`

The verifier reconstructs endpoint ranks and occurrence-based qualifiers from
CSV, independently counts the legal domain, and checks catalogue records,
memberships, truth/validity masks, complement representatives, weights, seals,
and frozen exports. With captured output it checks each rectangle's constant
position path and complete disjoint coverage, then compares its ten metrics with
an independent sequential cash/share ledger.

| Scope, per run | January leaf | January certificates | Year certificates | `u128` control |
|---|---:|---:|---:|---:|
| Membership records checked | 39,198 | 39,198 | 46,290 | 8,591 |
| Physical pair coverage | 786,210 | 786,210 | 87,925,122 | 1,110 |
| Native metric regions | 786,210 | 420,236 | 45,134,484 | 861 |
| Captured region metrics checked | **786,210** | **420,236** | **0** | **861** |
| Task winners replayed | 24 | 24 | 192 | 3 |
| Mask disagreements | 0 | 0 | 0 | 0 |
| Maximum absolute metric error | 7.1623e−12 | 7.1623e−12 | 3.9222e−12 | 4.4480e−12 |

Receipts: [January leaf](control-leaf-verification.json),
[January certificates](control-verification.json), [year](year-verification.json),
[`u128`](u128-verification.json). Finite comparisons allow `1e-7` absolute plus
`1e-9` relative tolerance; undefined status, trade counts and period counts must
agree. The first sixteen C-ledger reference paths are crosschecked with Python.
Summary runs independently check all banks, requested task domains, committed
coverage counters and retained winners; other region metrics remain native-only
results. The year scalar receipt has the same independent scope, with 87,925,122
native leaf regions. Raw captured boxes remain in the experiment runs rather than
Git; the committed receipts record their verification and identities.

The separate [high-count configuration](u128-config.cfg) uses unoriented windows
`0,1,2,3,4,5` and `0`, qualifier `plain`, and rule `(and s0 s1)` on January.
Its six-candle bank has **43,216,321,851,028,552,968** patterns, already above `u64`.
Both ordered bank pairs cover
**691,461,149,616,456,847,488 logical addresses**. The
[native summary](u128-summary.json) and [independent audit](u128-verification.json)
reconcile every weight, all 1,110 physical pairs and all 861 captured region
metrics. This exercises nonzero high 64 bits in real preparation, certificates,
artifacts and verification, rather than only testing a counting function.

## Concrete frozen replay

The committed [selection](best-geometry.tsv) fixes two explicit oriented patterns,
with lags `0,1,2` and `0,2,4`, both qualified by `recent:3`; the
[rule](best-rule.txt) is `(or s0 s1)`. Their checksum sidecars bind the frozen
artifacts. The same selection is evaluated without another search on each period.

| Metric | `2024-01-01` → `2025-01-01` | `2025-01-01` → `2026-09-28` |
|---|---:|---:|
| Net return, % | 18.602387 | **−3.491658** |
| Gross return, % | 20.515288 | −3.104851 |
| CAGR, % | 18.579333 | −2.024590 |
| Maximum drawdown, % | 1.209259 | 3.491658 |
| Sharpe | 1.814792 | −1.103906 |
| Entries | 4 | 1 |
| Exposure, % | 0.546946 | 0.078782 |
| Mean period return, bps | 0.798056 | −0.092551 |
| Mean trade return, bps | 439.791283 | −349.165800 |
| Periods | 2,194 | 3,808 |

Both ends are exclusive. Independent replay checks every decision's truth and
validity plus all ten metrics: [2024 result](year-replay.json) and
[audit](year-replay-verification.json), [later result](later-replay.json) and
[audit](later-replay-verification.json). There are zero mask disagreements; maximum
absolute metric errors are 1.2506e−12 and 1.1369e−13 respectively. Only 12 year
decisions and three later decisions are active. The first period selected the
winner; the later period is retrospective systems evidence, not a newly untouched
holdout. Sparse trading and the later loss provide no basis for claiming a
general trading advantage.

## Reproduction

Use the final source revision and byte-identical CSV inputs. The committed
configurations contain original absolute machine paths; copy them to working
configs and change only `data=` as needed. January is the byte-preserving prefix
of the discovery CSV ending before `2024-02-01`, retaining all earlier history.
Source SHA-256 values are:

| CSV | SHA-256 |
|---|---|
| January control | `a6910aa38a3bd943a94307e405ea1782b7418ea2c1df7c31d53a13f101b8b1d3` |
| Full-year discovery | `6dece8e4d91e98c83d80a0217907e024db656781cf3f0ffd61941e87c942aa98` |
| Later evaluation | `7844ae10462b6ddd6b17ea21a0626153b6786cbb0fd828bf2593e574a7578625` |

From the repository root, with relocated `control.cfg`, `year.cfg` and `u128.cfg`:

```sh
cargo build --release --locked --offline
python3 scripts/verify_geometry.py --self-test
python3 scripts/benchmark_geometry.py --config control.cfg --out runs/control \
  --repeats 3 --workers 10 --capture --ledger c \
  --modes leaf_scalar certificates_scalar certificates_native certificates_parallel
python3 scripts/benchmark_geometry.py --config year.cfg --out runs/year8 \
  --repeats 3 --workers 8 --ledger c --modes certificates_parallel
python3 scripts/benchmark_geometry.py --config year.cfg --out runs/year10 \
  --repeats 3 --workers 10 --ledger c --modes certificates_parallel
python3 scripts/benchmark_geometry.py --config year.cfg --out runs/year-leaf \
  --repeats 1 --ledger c --modes leaf_scalar
./target/release/filang geometry-sweep --config u128.cfg --out runs/u128 \
  --workers 10 --capture true
python3 scripts/verify_geometry.py --run runs/u128 --ledger c
./target/release/filang geometry-evaluate --data data/btc4h/evaluation.csv \
  --selection benchmarks/reports/20261008-bar-geometry/best-geometry.tsv \
  --start 2025-01-01 --end 2026-09-28 --interval-seconds 14400 \
  --fee-bps 10 --slip-bps 10 --out runs/later
python3 scripts/verify_geometry.py --evaluation runs/later \
  --data data/btc4h/evaluation.csv --ledger c
```

For same-period frozen replay, use `data/btc4h/discovery.csv`, dates
`2024-01-01` and `2025-01-01`, and a fresh output directory. For the scheduler
comparison, build `eef9553` separately and repeat the captured control; its driver
runs all four modes by default, so omit `--modes` there. Changed paths or engine
bytes can change context-bound digests. Compare the declared domain, verified
coverage, concrete selection and metric values with the retained receipts.
