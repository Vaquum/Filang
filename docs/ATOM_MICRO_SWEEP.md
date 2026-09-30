# Fine atom-neighborhood research, version 1

This is a parameterized neighborhood of a known construction, not unrestricted
novel-topology search. It uses the existing scalar/NEON/AVX2 atoms, numerical
profiles, common paged executor and reversible full-risk execution state.

## Construction and allowed parameters

```
P = close + a * (open - close)
M = mean_sum(n, P)
D = M + b * (mean_sum(n+1, P) - M)
F = P / D - c
position = F > 0
```

At `a=0`, P is exactly the original close node. At `b=0`, D is exactly M.
These are authoring-time inactive-parameter branches, not floating-point rewrites.
`n=200,a=0,b=0,c=1` has exactly the existing SMA-distance anchor expression ID.
Negative a slightly extrapolates away from the opening price; positive a moves
slightly toward it. The same modified source feeds both means. Mean arithmetic
is NOT moved through the affine source transformation. For nonzero b the next
integer mean participates and the output therefore has its declared additional
warmup. b is an adjacent-window mixture weight, NOT a fractional Mean period.
The only new continuous degrees of freedom are constants in ordinary atoms.
No internal tolerances, minimum periods, seeds or economic assumptions are tuned.

The example uses n=199,200,201; a=-0.01..0.01 in 0.0005 steps; b=0..0.1 in
0.0025 steps; c=0.999..1.001 in 0.000001 steps (0.01 basis point increments).
It defines 5,043 upstream constructions and 10,091,043 full parameter addresses.
The final constant is mathematically readout-equivalent, not an additional source
of independent signal innovation. Configurable grids use
`start_tick:step_tick:count:denominator`, with exact integer construction followed
by one f64 division. Grids must contain the original anchor settings.
The authoring limits are a in [-.25,.25], b in [0,1], positive c, and integer
windows 2..99999. Experiment domains and declared assumptions remain finite.

## Generic work elimination

`Executor::prepare_shared` stores a bounded graph/data-scoped bank once per source
and window stripe. All b/c descendants reuse exactly those node values. The graph
prefix and data context must match; incompatible state is rejected.
`Executor::constant_regions` recognizes an ordinary `sub(series,constant)` root
read out strictly above zero. It does not recognize an indicator name. For the
supported finite bounded operands (signed support extended in 0.6), `(x-c)>0` and `x>c` have identical decisions:
subtraction cannot overflow or reverse a nonzero difference's sign. Nonfinite x
remains invalid/flat. An unsupported domain fails this plan; the expanded reference
remains available. No approximate margin or epsilon licenses a changed trade.

For each observed base series, grid-index events determine every position change.
The evaluator emits contiguous half-open offset-index ranges with identical
positions and all ten scenario-specific metrics. It never visits individual
constant addresses inside an unchanged range. This is exact sample-scoped result
coverage, not proof of feature equivalence on future data. Base definitions and
all offset addresses remain reconstructible. Numerical variation in a/b is still
real work; region compression is not a universal constant-time program evaluator.

`regions.bin`: records contain base ID, offset lo, offset hi as three little-endian
u64 values, then two ten-f64 metric sets, 184 bytes per region. `transitions.bin`
contains exact initial packed masks and ordered (grid index, row index) changes
for independent verification of every represented mask. `surface.csv` has one
row per upstream construction, including the c=1 response and best/worst offset
responses. `summary.json` separates logical addresses from physical regions,
state changes, source banks, numerical work and written bytes.
Summary mode discards binary evidence records after hashing. It is not pruning.
No arrays scale with the constant-grid count. The simple native grid test resolves
a trillion offset addresses over a bounded synthetic series, but this is NOT a
trillion genuinely distinct feature-program sweep.

## Research and selection protocol

Discovery uses 2021-01-01 through 2024-12-31. Input must end exactly at 2025-01-01
exclusive; future rows are rejected. Earlier rows provide causal warmup. Selection
uses stress log return, subject to >=12 primary trades, primary exposure 2–98%,
and stress max drawdown <=40%. Ties at 1e-9 log-return resolution prefer the
smallest normalized parameter distance to the anchor, then address. Inside an
identical-behavior region choose the offset closest to one. The anchor is retained
regardless of eligibility; absence of an eligible variant is a valid result.

Only the anchor and at most one discovery-selected candidate are frozen for later
replay, 2025-01-01 to 2026-09-28 exclusive. Both periods are already-observed
history, so this is retrospective exploration rather than untouched confirmation.
The protocol, domain and objective are fixed in issue #10 before outcomes.
There are no intermediate fold-reset gaps in this explicitly single-interval
study. Do not compare its numbers directly with the older eight-fold-reset report.
Primary fee/slippage are 5+5 basis points per side; stress is 10+10. All variants
use the identical cash-funded next-open long/flat contract and terminal close.
No market impact, capacity, real order latency or live profitability is inferred.

## Run

```
cargo test --locked --offline
cargo build --release --locked --offline
# Fresh executable requires a fresh full reference gate.
./target/release/filang anchor-parity --data data/btc4h/evaluation.csv --out runs/micro-parity
.venv/bin/python scripts/anchor_reference.py --data data/btc4h/evaluation.csv --manifest runs/micro-parity/manifest.json --native runs/micro-parity --out runs/micro-parity-reference --gate
.venv/bin/python scripts/prepare_micro_gate.py --gate runs/micro-parity/gate.txt --full data/btc4h/evaluation.csv --discovery data/btc4h/discovery.csv
./target/release/filang micro-inspect --config examples/sma-micro.cfg
./target/release/filang micro-sweep --config examples/sma-micro.cfg --gate runs/micro-parity/micro_gate.txt --out runs/my-micro
.venv/bin/python scripts/verify_micro.py --run runs/my-micro --out runs/my-micro/verification.json --all-metrics
# Inspect and retain the frozen selection before separate later replay.
./target/release/filang evaluate --data data/btc4h/evaluation.csv --selection runs/my-micro/frozen.tsv --out runs/my-micro-later
./target/release/filang evaluate --data data/btc4h/evaluation.csv --selection runs/my-micro/frozen.tsv --out runs/my-micro-later-stress --fee-bps 10 --slip-bps 10
```

The prefix authorization verifies bytes, not performance, and does not expose
later prices to micro-sweep. Checksums are integrity evidence, not authenticated
security. Every output directory must be new. Gate binds executable/catalog,
external parity evidence, full data and the authorized discovery prefix.

## Benchmark and verification

```
.venv/bin/python scripts/benchmark_micro.py --gate runs/micro-parity/micro_gate.txt --out runs/my-micro-benchmark --repeats 3
```

The small grid compares every logical ten-metric output between expanded direct
replay, unshared regions, and shared regions. Direct replay caches the upstream
features; it does not recompute an indicator for every constant. Timed modes all
use summary output; their physical result encodings differ by design, so hashes
of expanded vs region records are not expected to match. Independent verification
checks every compressed mask via exact event records and optionally every region's
full metrics using TA-Lib on each actual modified source plus separate NumPy
chronological accounting. Systematic cash/share checks are labeled as a subset.
Performance evidence must report count definitions, actual region compression,
source/compiled hashes, repetition counts, whole-process memory and time. No
throughput is extrapolated to unrelated open-program spaces.
