# Ten-family atom micro-sweeps (0.6)

Issue #12 fixes the cohort, grids, readouts and research protocol before outcomes.
This is a practical cohort of ten established indicators/features, NOT a measured
worldwide top-ten popularity ranking or a claim that every readout is profitable.

## Exact baselines and interior perturbations

Every family uses P = close + a*(open-close), retaining the unchanged close node
when a=0. Actual market execution prices are never modified. High, low and volume
remain the original inputs. Negative a extrapolates slightly and can put the proxy
outside its bar range; it is an explicit signal proxy, not a replacement market bar.

| Family | Baseline Q; long while Q exceeds cutoff | Interior component mixed by b |
|---|---|---|
| SMA200 | P / SMA200(P); cutoff 1 | SMA(n) toward SMA(n+1), denominator |
| EMA24 | P / EMA24(P); cutoff 1 | EMA(n) toward EMA(n+1), denominator |
| RSI14 | RSI(P)/50; cutoff 1 | Both Wilder gain and absolute-change averages n toward n+1 |
| MACD12/26/9 | Histogram / P; cutoff 0 | Signal EMA9 toward EMA10; fast period n varies |
| Bollinger20 | (SMA20(P)-P)/STD20(P); cutoff 2 | STD(n) toward STD(n+1); mean period is n |
| Stochastic14/3/3 | (slowK-slowD)/100; cutoff 0 | Signal mean3 toward mean4; high/low period n varies |
| ATR14 | ATR(H,L,P)/P; cutoff .01 | Wilder true-range average n toward n+1 |
| ROC14 | P / lag14(P); cutoff 1 | Lag(n) toward lag(n+1) |
| CCI20 | CCI(H,L,P)/100; cutoff 1 | Mean absolute deviation n toward n+1; mean period is n |
| Rolling VWAP20 | P / rolling volume-weighted typical price; cutoff 1 | Weighted baseline n toward n+1 |

Mix(x,y,b)=x+b*(y-x), with b=0 retaining x and its original validity. This is an
interpolation of an indicator's internal numerical component, not of returns.
RSI uses the existing gain/absolute-change ratio. MACD retains the pinned aligned
EMA initialization. Bollinger uses the raw-total population-variance profile.
The stochastic rule is a hold-while comparison, not a one-bar crossover event.
ATR is a volatility-regime feature, not a directional predictor. VWAP uses bar
TP=(H+L+P)/3 over the declared rolling window; it is NOT session-anchored,
transaction-level VWAP, or a TA-Lib VWAP API-parity claim.

## Grids

Each principal period is baseline-1, baseline, baseline+1. MACD's slow26 stays
fixed; its signal mixture covers EMA9 and EMA10. Stochastic smoothing is explicitly
3 with the signal mixture 3 to 4. This study does not claim to sweep every available
parameter of these indicators.

Source a: -0.01..0.01 by .0005, 41 values. Internal b: 0...1 by .0025, 41 values.
Each terminal cutoff has 2,001 rational-grid values:

- SMA, EMA, ROC, rolling VWAP: 1 +/- .001, step .000001.
- RSI: 1 +/- .002, step .000002 (ordinary RSI 49.9..50.1).
- MACD: 0 +/- .0001, step .0000001 (histogram/price).
- Bollinger: 2 +/- .02, step .00002.
- Stochastic: 0 +/- .001, step .000001 (%K-%D divided by100).
- ATR: .01 +/- .0001, step .0000001 (ATR/price).
- CCI: 1 +/- .01, step .00001 (ordinary CCI99..101).

There are 5,043 upstream parameter constructions and 10,091,043 full parameter
addresses per family, 100,910,430 total. The final subtraction constant is readout-
equivalent, not that many independently informative features. The exact SMA family
from 0.5 is repeated, not silently replaced. Configurations live in examples/micro10/.

## General numerical/execution machinery

No indicator names occur in execution kernels. Family authoring expands to typed
atoms; prepared banks reuse exact subexpressions across descendants. The only new
numerical opcode is `mad_mean n x`: population mean absolute deviation about each
window's own arithmetic mean, finite full window, chronological f64 reductions,
integer n in1..100000. This general atom currently costs O(T*n); shared preparation
avoids recomputing it for each b/c descendant. It is not a CCI kernel or TA-Lib call.

The same constant-region planner now supports signed operands whose magnitudes
are <= f64::MAX/2. Subtraction then cannot overflow; distinct binary64 operands
cannot round their difference across zero with gradual underflow. Signed zeros
and exact ties remain false under strict >. Invalid inputs remain flat. Larger
magnitudes fail the certificate instead of quietly changing the predicate. No
FMA, fast math, reduced precision, epsilon-adjusted signals or relaxed tolerances.

Full risk states, both cost scenarios, data/graph identity checks and result-region
format are unchanged. Numerical profiles and operation order are explicit; linear
identities are not used to commute moving averages through source modifications.

## Research protocol

Same immutable BTCUSDT4h input. Discovery2021-01-01..2025-01-01 exclusive and later
2025-01-01..2026-09-28 exclusive, with causal warmup and no intermediate fold resets.
Both histories were previously observed. These are retrospective studies, not
fresh untouched confirmation. Every baseline and variant uses the same next-open
cash-funded long/flat accounting, primary5+5bps and stress10+10bps per side.

For each family: report unchanged anchor; best source/component weights with n
and cutoff fixed; best upstream change with cutoff fixed; cutoff-only maximum;
and unrestricted descriptive maximum. Keep the complete surface and region coverage.
Those descriptive slices are not independent market-validation winners.

The eligibility rule is unchanged: >=12 primary trades, primary exposure2–98%,
stress drawdown<=40%. Rank by stress log return with1e-9 score resolution, then
nearest normalized anchor distance and address. This gate does NOT guarantee
positive returns. At most one eligible variant per family is frozen with its anchor.
Empty eligibility is valid; no relaxation after outcomes. Freeze/push all ten
selection artifacts before any later replay. Keep all later results, including losses.

## Reproduce

Build and obtain fresh baseline gates after any executable change:

```sh
cargo test --locked --offline
cargo build --release --locked --offline
./target/release/filang anchor-parity --data data/btc4h/evaluation.csv --out runs/ten-legacy-parity
.venv/bin/python scripts/anchor_reference.py --data data/btc4h/evaluation.csv --manifest runs/ten-legacy-parity/manifest.json --native runs/ten-legacy-parity --out runs/ten-legacy-reference --gate
.venv/bin/python scripts/prepare_micro_gate.py --gate runs/ten-legacy-parity/gate.txt --full data/btc4h/evaluation.csv --discovery data/btc4h/discovery.csv
./target/release/filang cohort-parity --data data/btc4h/discovery.csv --out runs/cohort-v06-parity
.venv/bin/python scripts/cohort_reference.py --data data/btc4h/discovery.csv --run runs/cohort-v06-parity
.venv/bin/python scripts/run_cohort.py discover --gate runs/ten-legacy-parity/micro_gate.txt --cohort-gate runs/cohort-v06-parity/gate.txt --out runs/ten-experiment
.venv/bin/python scripts/run_cohort.py verify --out runs/ten-experiment
```

Then preserve the complete discoveries and exact frozen.tsv files before separate
`filang evaluate` calls, primary and stress, for each family. Use fresh output dirs.
`comparisons.json` gives the three restricted descriptive comparisons. Non-SMA
surface columns use `at_anchor_cutoff`; legacy `mean_weight` means the family's
explicit interior-component mixture. Generic region records retain all parameters.

## Reference scope and timing

The legacy88-case gate remains. The new cohort gate checks ten baselines and twenty
predeclared endpoint perturbations, every value/validity/mask/trade/equity point,
60 full scenario metric sets, and direct TA-Lib APIs for raw baselines where available.
Rolling VWAP is verified with independent weighted sums. Full-grid verification
compares exact initial masks and all grid/row event records, then every physical
region's ten metrics against separate explicit cash/share C accounting (not the
Filang tree formulas). The C oracle is cross-checked with independent NumPy ledgers
and Python cash/share traces; full-grid NumPy subset checks are labeled separately.
C is an optional verification accelerator, NOT a native runtime dependency or
an optimized-code timing denominator. The C compiler disables FMA contraction.

Feature tolerance remains atol1e-8/rtol1e-9, metrics atol1e-7/rtol1e-9, traces
atol1e-8/rtol1e-9. Masks/events/counts exact. Independent raw-reference fixtures are
retained for native scalar and SIMD CI tests. Full-grid checks are dataset/domain
specific, not universal numerical certification.

Small matched ablations use scripts/benchmark_micro.py --config FAMILY.cfg,
expanded/unshared/shared paths with all full logical results compared. Full-grid
ablation uses --output summary --shared true/false and verifies identical region
hashes/selections. Report entire processes, repetition counts, source/engine hashes,
RSS and exact workload counters. Verification and timing runs must not be concurrent.

Sources for terminology (not usage ranking): official TA-Lib function catalog and
v0.6.4 C source; Fidelity CCI/stochastic indicator guides; TradingView VWAP documentation.
No assertion of universal profitability or trillion distinct-program completion.
