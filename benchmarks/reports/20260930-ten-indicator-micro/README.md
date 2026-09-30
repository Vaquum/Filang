# Ten known-feature atom micro-sweeps — 2026-09-30

## Outcome and scope

All ten declared families were implemented and run through the common native
micro-sweep engine. Each found a discovery-period improvement, including changes
to source/component weights while keeping the original period and cutoff fixed.
This is a result of searching a neighborhood that includes the baseline, not an
estimate of the effect of a random tweak or proof of improvement on unseen data.
Some improved strategies still lost money; eight of ten full-grid descriptive
maxima remained negative under doubled transaction-cost assumptions.

The total domain is **100,910,430 parameter addresses**, from **50,430 upstream
parameter constructions**. It was resolved through **7,427,701 exact sample-scoped
behavior regions**, supplying **14,855,402 physical ten-metric scenario results**
for **201,820,860 logical scenario requests**. Offset values are readout-equivalent;
these counts do not represent that many independent indicators, trials or signals.
All addresses are covered; none was heuristically pruned. Regions are counted per
upstream construction, not asserted globally unique behavior masks.

The cohort is SMA, EMA, RSI, MACD, Bollinger Bands, slow stochastic, ATR, ROC, CCI,
and rolling VWAP. It is a practical selection of mainstream constructions, not a
measured worldwide top-ten popularity ranking. All individual output/readout
variants are explicit below and in docs/TEN_INDICATOR_SWEEP.md.

## Predeclared experiment

Issue #12 fixed definitions, parameter grids, data boundaries, costs, ranking and
promotion rules before the full searches. Data are the existing pinned BTCUSDT
four-hour source. Discovery is 2021-01-01 through 2025-01-01 exclusive; earlier data
supply causal warmup. Later replay is 2025-01-01 through 2026-09-28 exclusive. Both
periods were already observed in preceding research: this is retrospective
exploration, not untouched out-of-sample confirmation.

All variants use original market prices for cash-funded long/flat execution at
the next open, continuous periods with a terminal exit and no intermediate fold
resets. Primary costs:5bps fees+5bps slippage per side; stress:10+10. No leverage,
market-impact, live-fill, latency or capacity claim is made.

Source/engine computation is committed as
`7be7d5917f07922c17b3009adc2a600518bda8b1`, executable SHA-256
`194dce74012b586a4994a5a8e0d834e649af42abe8f51f1cee733f1a07de34c6`.
All ten discoveries and exact anchor-only frozen selections were committed and
pushed as `4d726459033d8db7b405c59091db37a4472ca839` before any later replay.
Subsequent helper/report commits do not change the native executable.

## What was varied

For every family, `P=close+a*(open-close)`. At a=0, the original close node is used
directly. High, low and volume remain unchanged. A slightly negative a extrapolates
away from the open; this is an explicit signal proxy and can lie outside the bar's
range. It never changes execution prices.

For an internal pair x,y, `mix(x,y,b)=x+b*(y-x)`. At b=0 the original node and its
warmup are retained directly. No arithmetic identity moves rolling calculations
through source transformations; no backtest returns are interpolated.

| Family | Baseline and strict long/flat rule | Internal component varied by b |
|---|---|---|
| SMA200 | P/SMA200(P)>1 | Denominator SMA(n) toward SMA(n+1) |
| EMA24 | P/EMA24(P)>1 | Denominator EMA(n) toward EMA(n+1) |
| RSI14 | RSI(P)/50>1 | Gain and absolute-change Wilder averages n toward n+1 |
| MACD12/26/9 | Histogram/P>0 | Signal EMA9 toward EMA10 |
| Bollinger20 | (SMA20(P)-P)/STD20(P)>2 | Standard deviation n toward n+1 |
| Stochastic14/3/3 | (slowK-slowD)/100>0 | Signal mean3 toward mean4 |
| ATR14 | ATR(H,L,P)/P>.01 | True-range Wilder average n toward n+1 |
| ROC14 | P/lag14(P)>1 | Lag n toward lag n+1 |
| CCI20 | CCI(H,L,P)/100>1 | Mean absolute deviation n toward n+1 |
| Rolling VWAP20 | P/rolling-volume-weighted-TP>1 | Weighted baseline n toward n+1 |

ATR is explicitly a volatility-regime feature, not a directional forecast.
Stochastic uses a hold-while K>D rule, not a single-bar crossover event. Rolling
VWAP uses bar TP=(H+L+P)/3; it is not session-anchored or transaction-level VWAP.
MACD's aligned initialization matches the pinned reference. Its fast period varies
by +/-1; slow26 remains fixed. Other principal periods likewise vary by +/-1.

Every family uses 3 principal periods, 41 source coefficients a=-.01..+.01 in
.0005 steps, and 41 component coefficients b=0.0 to 0.1 in .0025 steps. Each upstream
construction has 2,001 terminal constants. Grids use exact integer ticks followed
by one f64 division, not accumulated floating-point additions. Thus each family
has 5,043 upstream constructions and 10,091,043 full parameter addresses.

| Terminal quantity | Cutoff grid | Step |
|---|---|---|
| SMA, EMA, ROC, rolling VWAP ratio | 0.999..1.001 | 0.000001 |
| RSI/50 | 0.998..1.002 | 0.000002 |
| MACD histogram/price | -0.0001..0.0001 | 0.0000001 |
| Negative Bollinger z | 1.98..2.02 | 0.00002 |
| (stochastic K-D)/100 | -0.001..0.001 | 0.000001 |
| ATR/price | 0.0099..0.0101 | 0.0000001 |
| CCI/100 | 0.99..1.01 | 0.00001 |

## Discovery results: full cohort, including losses

Every best-in-slice value below is selected by **stressed log return**, then the
predeclared near-anchor tie break. Primary return is reported at that same point;
it is not separately maximized. Consequently a broader-slice choice can have a
slightly lower primary return while a higher stress return. All values are
cumulative net percentages over the four-year discovery interval.

| Feature | Unmodified primary | Weights-only primary | Atom-only primary | Cutoff-only primary | Full-grid primary | Full-grid stress |
|---|---:|---:|---:|---:|---:|---:|
| SMA(200) | +262.7108% | +269.1402% | +280.6206% | +313.2540% | +321.7134% | +235.7363% |
| EMA(24) | +87.1251% | +103.9526% | +103.9526% | +120.7293% | +122.4968% | -4.1377% |
| RSI(14) | +76.0616% | +77.5922% | +89.1283% | +83.1960% | +101.8391% | -15.9451% |
| MACD(12,26,9) | -30.2195% | -27.4260% | -6.4960% | -12.2921% | +10.2674% | -45.2428% |
| Bollinger(20) | -41.7588% | -41.0999% | -33.1588% | -34.5133% | -34.0568% | -61.4177% |
| Stochastic(14,3,3) | -73.3031% | -68.6762% | -64.8364% | -72.1947% | -64.7429% | -95.6652% |
| ATR(14) / price | +134.9912% | +135.3866% | +136.1533% | +138.2778% | +138.6530% | +110.4000% |
| ROC(14) | -31.5466% | -19.9755% | +40.7014% | -22.3628% | +65.1900% | -40.1946% |
| CCI(20) | -3.1116% | +2.0863% | +28.4067% | -0.1796% | +28.7772% | -39.5339% |
| Rolling VWAP(20) | +47.0594% | +54.7947% | +54.6126% | +81.8772% | +99.9013% | -26.0179% |

Weights-only keeps both period and cutoff fixed. Atom-only allows the principal
period and source/component weights to vary, but fixes the cutoff. Cutoff-only
keeps the original feature. Full-grid varies all declared coordinates. The complete
coordinate choices and all ten metrics are retained in each comparisons/summary
JSON, discovery_comparison.csv, and the 50,430-row collection of response surfaces.
These are descriptive search maxima, not separately validated or promoted strategies.

All ten weights-only slices improved the corresponding baseline return on this
history. In the full grid, MACD, ROC and CCI crossed from negative to positive
primary returns. This does not make them cost-robust: their stressed results remain
negative. Only the SMA and ATR families have positive stressed returns in this
specific grid. The number of neighboring winning addresses is not a confidence
level, an independent-trial count, or evidence about future performance.

## Eligibility and later replay

The unchanged promotion rule requires at least12 primary trades, primary exposure
2–98%, and stress maximum drawdown<=40%. Ranking uses stressed log return, with
1e-9 resolution, then normalized distance and address. This eligibility screen
does not itself require a positive return.

**No parameter address in any family passed.** The minimum stressed drawdown ranges
from46.56% for SMA to97.46% for stochastic. No gate was relaxed. Only each unchanged
anchor was frozen; no descriptive variant was selected for later validation.

| Unchanged anchor | Later primary net | Later stress net |
|---|---:|---:|
| SMA(200) | +3.3690% | -7.5835% |
| EMA(24) | -39.8444% | -61.4894% |
| RSI(14) | -39.5176% | -60.1807% |
| MACD(12,26,9) | -21.2028% | -40.5653% |
| Bollinger(20) | -39.0535% | -50.9914% |
| Stochastic(14,3,3) | -39.0523% | -75.1212% |
| ATR(14) / price | -39.8018% | -48.1870% |
| ROC(14) | -39.7631% | -63.2446% |
| CCI(20) | -34.8421% | -54.7224% |
| Rolling VWAP(20) | -38.6053% | -60.2217% |

These twenty anchor/scenario replays were all independently verified. They are
not a test of whether the descriptive micro-tweak winners generalize. No such
claim is made. Source histories had been seen earlier, and the later reports
retain the legacy evaluator's schema metadata; the authoritative executable
identity/version is the recorded 0.6 build/hash, not the older serializer label.

## General factorization and verification

The compiler still receives ordinary atom graphs, not names such as RSI or CCI.
The only new numerical opcode is a general full-window mean absolute deviation
`mad_mean(n,x)`. It has population denominator, finite-window validity, chronological
f64 reduction, and O(T*n) arithmetic. At current n=19..22 it is shared across all
mixture/cutoff descendants; it is not a named-indicator special kernel. Existing
SMA source/expression semantics remain unchanged.

Signed constant-region certification extends to finite operand magnitudes <=
f64::MAX/2. Subtraction cannot overflow and a nonzero binary64 difference cannot
round across zero under gradual underflow; ties/signed zeros stay false. No
fast-math, epsilon-shifted trading decisions or reduced precision is used.
Other ordinary graph, SIMD, prepared-bank and full-risk execution machinery is
shared with the existing paged/open runtime.

All ten baseline-plus-endpoint families passed the new parity gate:30 numerical
programs,60 scenario metrics, every value/validity/mask and every equity/trade-trace
point. Direct pinned TA-Lib outputs are checked for raw baselines, with independent
weighted sums for rolling VWAP. The unchanged88-case prior anchor gate also passed.

Full-grid verification compares exact initial masks and all ordered grid-index/
row-index transition arrays for every upstream construction. Those comparisons
establish every represented position path. All **14,855,402 physical scenario
metric sets** were then checked against independent explicit cash/share C
accounting, rather than Filang's tree summaries. Maximum absolute metric discrepancy
was **6.59383658785373e-12**; trade/sample counts are exact and no mask mismatch
occurred. The C oracle is separately cross-checked against Python cash/share traces
and NumPy chronology at the baseline gate, plus1,200 systematic full-grid region
crosschecks. The latter are a subset; the C check covers every physical region.

The C code is an optional reference accelerator only, with FMA contraction disabled;
it is not linked into the native engine and its runtime is not a benchmark
speedup denominator. Four external reference workers were used, separately from
native timing. All proofs/source/library hashes and exact reference versions are
retained. Feature atol1e-8/rtol1e-9, metric atol1e-7/rtol1e-9, and trace atol1e-8/
rtol1e-9 remain unchanged. Decisions/events/counts cannot differ within a tolerance.

## Performance evidence

The initial complete ten-family captured campaign took **42.0977 seconds** including
sequential process startup, required gate checks, source preparation, all full-risk
region metrics and region/transition/surface output. It used one native worker per
process. Largest measured process RSS was about50.41MiB. This is one campaign
measurement, not a universal latency bound or a trillion-program extrapolation.
Timing details are per-family in discovery_index.json and resource logs.

Matched repeated measurements are documented below. They are native application
ablations, not standalone TA-Lib C-indicator speed claims. All outcomes and gates
remain unchanged across timing paths. No external verification runs concurrently.

### Matched small-grid ablation: every family

Each small grid has27 upstream constructions ×201 cutoffs=5,427 addresses and
10,854 scenario metric sets. All logical results are compared between expanded
native chronological replay, unshared regions and shared regions. All timed modes
use summary output; physical encodings differ by design. The expanded path caches
upstream values, rather than deliberately recomputing an indicator per cutoff.
Three fresh-process repetitions per path, one native worker, no CPU pinning or OS
cache flush. No independent verification ran concurrently with timing.

| Family | Expanded median | Unshared regions median | Shared regions median | Expanded/shared |
|---|---:|---:|---:|---:|
| SMA(200) | 0.8449s | 0.3847s | 0.3102s | 2.724x |
| EMA(24) | 1.0871s | 0.6145s | 0.4082s | 2.663x |
| RSI(14) | 0.9627s | 0.3528s | 0.2947s | 3.266x |
| MACD(12,26,9) | 1.0841s | 0.3026s | 0.2915s | 3.719x |
| Bollinger(20) | 0.4771s | 0.2489s | 0.2277s | 2.095x |
| Stochastic(14,3,3) | 0.7995s | 0.2542s | 0.2388s | 3.348x |
| ATR(14) / price | 0.8231s | 0.2345s | 0.2435s | 3.381x |
| ROC(14) | 0.7351s | 0.2437s | 0.2403s | 3.059x |
| CCI(20) | 0.5707s | 0.2605s | 0.2359s | 2.419x |
| Rolling VWAP(20) | 0.7023s | 0.2410s | 0.2412s | 2.911x |

### Full-grid dependency sharing: every family

The same 10,091,043-address grid per family is computed three times with sharing
and three times without, rotating family/path order. Every complete region-result
hash and frozen selection agrees with the independently verified discovery.
Both variants compute all region metrics and hash/discard binary records in summary
mode; they retain the same response surface. Timings include required parity-evidence
checks, process/data startup, calculations and output.

| Family | Shared median | Unshared median | Unshared/shared | Shared min–max |
|---|---:|---:|---:|---:|
| SMA(200) | 1.5019s | 1.9245s | 1.281x | 1.4671–1.5866s |
| EMA(24) | 4.2032s | 4.3658s | 1.039x | 4.0702–4.4378s |
| RSI(14) | 1.3054s | 1.9395s | 1.486x | 1.2720–1.3109s |
| MACD(12,26,9) | 3.2654s | 3.7724s | 1.155x | 3.2328–3.5338s |
| Bollinger(20) | 1.0329s | 1.4612s | 1.415x | 1.0303–1.0617s |
| Stochastic(14,3,3) | 2.1492s | 4.6691s | 2.172x | 2.1356–2.1570s |
| ATR(14) / price | 1.3810s | 2.1824s | 1.580x | 1.3804–1.7184s |
| ROC(14) | 3.2723s | 3.5921s | 1.098x | 3.2120–3.5809s |
| CCI(20) | 1.3633s | 4.8268s | 3.541x | 1.3435–1.3750s |
| Rolling VWAP(20) | 4.4620s | 5.0323s | 1.128x | 4.1145–6.1718s |

These ratios are workload-specific whole-application measurements, not standalone
SIMD or TA-Lib kernel gains. Variation is retained: for example, the final shared
VWAP repetition was slower than its unshared pair, despite a lower shared median.
Three repetitions and unpinned hardware do not establish a universal latency bound.
Ratios are not multiplied by results from previous releases. Full raw logs and work
counters for every run are retained; no reduced metric or hidden extra worker is used.

The sum of per-family shared medians is 23.9366s versus 33.7662s
without sharing. This is explicitly a sum of individual medians, NOT a measured
median of a single combined process or the captured campaign's total duration.

## Build and reproduction

Forty-eight native Rust tests pass, including independent raw TA-Lib fixtures on
scalar and detected NEON/AVX2 backends, complete tiny-grid region/expanded parity,
mean-absolute-deviation domains/validity, signed zeros/subnormals/ties, exact old
SMA identity, future append, and the preceding generic paged/open tests. Native
runtime remains dependency-free. Exact numerical-source CI passed Ubuntu and
macOS; a fresh clone passed offline tests/build, formatting and warning-free Clippy.
Fresh-clone timing was not used as a performance benchmark.

The final native executable remains the same measured/gated hash above. Later
commits add orchestration, reports and references, not new numerical behavior.
The generic numerical language now has23 opcode types, with the new mean-absolute-
deviation atom reusable outside this cohort. Broader coverage, richer parameter
exposure, signed-domain rules beyond the certified envelope and trillion distinct-
program completion remain open under issue#1.

Ready local runs:

```text
runs/ten-v06                      full ten-family discovery and complete verification
runs/ten-v06-later                twenty frozen anchor/scenario replays and checks
runs/ten-v06-benchmark            repeated small/full ablations
runs/cohort-v06-parity/gate.txt   ten-family baseline/endpoint evidence
runs/ten-v06-legacy-parity/micro_gate.txt   original gate + authorized prefix
```

```sh
cd ~/dev/Filang
.venv/bin/python scripts/run_cohort.py discover \
  --gate runs/ten-v06-legacy-parity/micro_gate.txt \
  --cohort-gate runs/cohort-v06-parity/gate.txt --out runs/my-ten
.venv/bin/python scripts/run_cohort.py verify --out runs/my-ten --workers 4
.venv/bin/python scripts/benchmark_cohort.py \
  --gate runs/ten-v06-legacy-parity/micro_gate.txt \
  --verified runs/my-ten --out runs/my-ten-benchmark --repeats 3
```

Use new output directories. A different native executable needs fresh legacy and
cohort gates; commands are in docs/TEN_INDICATOR_SWEEP.md. Individual configurations
in examples/micro10/ can be run with the existing `micro-sweep` CLI. Record the full
search protocol and freeze all selections before later replay. Ordinary `evaluate`
replays each frozen.tsv; `verify_cohort_later.py` checks all recorded outputs.

The committed report retains every response surface, coordinate comparison,
selection, later result, verification summary, exact source/data/engine identity,
repetition timing, and resource log. Large region/event binaries remain in ignored
runs/ with recorded sizes and digests. Full encoded results are reconstructible
from the committed configs and source; no parameter address is erased by behavior
compression and dataset equality does not imply future equality.
