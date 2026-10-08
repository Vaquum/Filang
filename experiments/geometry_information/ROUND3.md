# R3 — fixed qualitative interactions beyond additive geometry

This is the final hypothesis family in the [geometry information campaign](CAMPAIGN.md).
It follows the complete R2 record, including its unsupported economic criterion,
controls and numerical audit-development history. The exact [protocol](round3_protocol.json)
and [catalogue](round3_catalogue.json) were published in [PR #27](https://github.com/mikkokotila/Filang/pull/27)
at freeze commit `bcc49b113c59f2a2c72524605d26b2dedca98353`, after verified R2
merge `9fd79511541845c435e39fc25fb1d75ad42d1174` and before any R3 market fitting.
The protocol SHA-256 is
`486fd2b2f1bfa0e4e2ce19b77485386cef833c8b6341d5eca2403556dcdf67a7`.
The catalogue SHA-256 is
`dca090d73c32419bc525b71101f6cf0b584b1c8b91cf79808d4ed2f5d710bcdb`.
Each execution retains its own clean implementation commit and imported code hashes.

## Question and controlled change

Does a small, fully specified nonlinear composition of bar geometry add useful
conditional payoff information beyond the additive geometry model?

A is exactly the additive geometry feature family called G in R2. I contains A
and one fixed 225-column interaction block for the current and immediately prior
candle. A and I are fitted afresh under the same chronological selection procedure.
There is no reuse of R2 coefficients, policies, scores or return statistics.
The previous sign-history comparison remains in R2's record; it is not an
additional model search in R3.

This is a test of the entire specified interaction pipeline. Body orientation
is part of qualitative geometry, so a positive result would not isolate wick
information from orientation interactions. I has more columns and a different
penalty geometry than A; this is not a comparison with equal parameter capacity.

## Complete fixed interaction catalogue

For each adjacent pair, write the current candle first and the prior candle
second. Project its exact native ranks to either of these four-tuples:

- Body: `(current.body_bottom, current.body_top, prior.body_bottom, prior.body_top)`.
- Range: `(current.low, current.high, prior.low, prior.high)`.

Replace the projected values by their own dense weak-order ranks. Equal values
receive the same rank. Only relative order is used; neither distances, ratios,
volatility, price scale nor volume becomes a feature. The joint body direction
is `(current_direction, prior_direction)`, with down=-1, flat=0 and up=1.
A native flat body has no up flag.

Two intervals, each permitting a point interval, have 26 possible weak orders.
This can be partitioned without numerical measurements:

| First interval | Second interval | Weak orders |
|---|---|---:|
| Proper | Proper | 13 |
| Point | Proper | 5 |
| Proper | Point | 5 |
| Point | Point | 3 |
| **All cases** | | **26** |

Body intervals are points exactly when body direction is flat. A flat-body
candle may still have a proper low-to-high range, because it may have wicks.
That gives the following complete conditioned catalogues:

| Direction-pair class | Number of direction pairs | Body entries per pair | Range entries per pair |
|---|---:|---:|---:|
| Both nonflat | 4 | 13 | 13 |
| Exactly one flat | 4 | 5 | 18 |
| Both flat | 1 | 3 | 26 |
| **Total columns** | | **75** | **150** |

The additional block therefore contains 225 columns. Each row activates exactly
one body entry and one range entry. Catalogue entries are generated from
mathematical OHLC admissibility and placed in a stable canonical order before
any market fitting. Exhaustive synthetic enumeration covers all 7,452 valid
oriented two-bar qualitative states. The implementation and its independent
oracle must agree on every state, and every declared catalogue entry must be
reachable in that enumeration.

Only mathematically impossible entries are excluded. A reachable entry remains
a defined, penalized column even if no market fitting row activates it. There
is no empirical support filter, learned vocabulary, extra direction-pair block,
full body-by-range crossing or interaction at another lag. Longer histories
only enlarge the unchanged additive part.

| Candidate history n | Additive A columns | Interaction I columns |
|---:|---:|---:|
| 2 | 42 | 267 |
| 3 | 80 | 305 |
| 5 | 156 | 381 |
| 10 | 346 | 571 |

Each complete onehot group sums to one. The groups share direction-pair spans
and overlap with additive features. R3 deliberately keeps this redundant basis;
it does not drop an arbitrary reference category. Positive ridge penalties and
an unpenalized intercept give a unique fitted objective solution, while the
basis determines effective shrinkage. No invariance to another encoding is
claimed.

## Unchanged forecast and selection contract

After candle t closes, predict the following executable reference interval:

\[
y_t=\log(O_{t+2}/O_{t+1}),\qquad\widehat\mu_t=a+X_t\beta.
\]

Use the same five pinned Vaquum BTCUSDT snapshots, exact ten-candle causal
eligibility, strict exit-before-phase-boundary rule and all valid targets,
including exact zeros. An unavailable future label never suppresses an
otherwise available causal forecast in the economic ledger.

A and I independently choose n=2,3,5,10 and lambda=0.1,0.01,0.001,0.0001 by
preceding-year validation MSE. Ties within 1e-12 prefer shorter history and
then stronger regularization. Each selected model is refitted on all permitted
past data. The four outer folds remain 2023, 2024, 2025 and partial 2026.
The fitting objective, unscaled binary features, Cholesky solve, absence of
jitter/fallback and direct maximum-gradient acceptance at 1e-10 remain unchanged.

The implementation builds full I10 sufficient statistics once for each exact
fitting sample, binds their source/rows/targets/columns/bounds, and projects each
smaller A/I system by feature names. No fitted model substitutes for any required
fit. There are 640 inner candidates, 40 selected refits and 25 unique full-statistic
samples across the five timeframes.

## Same economic policy opportunity

A, I and unconditional mean-return control U each receive the same seven
validation candidates: cash, and entry {0,0.5,1}k crossed with exit {-0.5,0}k,
where the primary round-trip log cost is

\[
k=-\log\!\left((1-f)^2\frac{1-s}{1+s}\right),\quad f=0.001,\quad s=0.0002.
\]

Model selection uses the inner model's validation forecasts. Policy selection
maximizes primary-cost validation net log return, retaining the declared tie
order. The selected model and policy remain fixed through their own outer year.
No outer outcome or alternative cost scenario reselects either one.

The instrument remains long/cash spot Bitcoin under the same opening-price
proxy: next observed opening fills, delayed gap fills, actual gap exposure,
annual cash resets and terminal liquidation. Every validation trial and outer
ledger is retained. The 420 validation and 400 outer ledgers cover A/I/U, cash,
buy-and-hold and the unchanged zero/reduced/primary/stress cost scenarios.
The one-bar prediction target does not limit a selected holding to one bar.

## Exact bootstrap tails

R2 exposed a numerical issue in a sparse daily contrast: many globally centered
bootstrap replicas landed on the mathematical comparison boundary, and tiny
float summation differences changed literal tail counts. R3 specifies exact
arithmetic for this predicate before observing any R3 outcomes.

For either daily contrast, interpret each executed binary64 daily value as its
exact binary rational. Convert the values to signed integer numerators over a
common power-of-two denominator. Let S be the sum of original numerators, T the
sum with a replica's resampling multiplicities, and N the fixed number of days.
Then the one-sided globally centered event is

\[
\frac{T-S}{N}\ge\frac{S}{N}\quad\Longleftrightarrow\quad T\ge2S.
\]

The positive common denominator cancels as well. Integer summation and comparison
therefore count equality exactly. There is no epsilon, padding or float-derived
tail decision. The ordinary and centered float replicas are still retained,
and the observed means and percentile confidence intervals remain binary64
calculations. Only the tail predicate uses exact integers.

The same year-stratified circular block indices drive both effects, float
replicas and integer multiplicities. Seven-day blocks and 2,000 replicas remain
primary, with one- and 28-day sensitivity records. The original seed and draw
order remain fixed. Complete integer encodings and every boolean tail event are
retained and independently reconstructed; NPZ files contain only numeric or
boolean arrays, never Python object arrays or pickle.

This removes ambiguity for the executed binary64 daily inputs. It does not make
the independently reconstructed cash/share account bit-identical, remove the
specified account comparison tolerance or change historical data exposure.
The audit reports continuous numerical errors separately from exact retained-input
tail agreement.

## Primary criterion and stop

I must improve on both freshly selected additive A and cash. Use all calendar
days with equal weight, including inactive days. Take the maximum of the two
one-sided p-values for each timeframe, then apply Holm across all five.
All of the following must hold:

1. Both pooled daily effects are positive.
2. Both individual primary 95% interval lower endpoints exceed zero.
3. The Holm-adjusted composite p-value is below 0.05.
4. At least three of the same four years have both positive effects.
5. I completes at least 20 outer round trips.
6. All required fits, predictions, selections, ledgers, inference and artifact
   checks pass the full independent audit.

Twenty trades is an activity condition, not an independent sample-size claim.
U and buy-and-hold remain mandatory descriptive controls; the primary criterion
does not establish outperformance against either. All historical observations
and preceding rounds are already exposed. A supported result would be
retrospective evidence under this declared proxy, requiring fresh confirmation
and execution evidence before a live tradeability claim.

This is the third and final family in the frozen campaign budget. Retain its
full supported/not-supported/inconclusive result and stop the campaign, without
expanding architecture, thresholds, costs or horizons until a favorable result
appears.

## Reproduction and retained evidence

Use the completed PR #27 implementation tree. The freeze commit contains the
scientific specification and catalogue; it is not the full executable tree.
The recorded environment uses Python 3.13.2 and the repository's pinned
`requirements-direction.txt` and `requirements-information.txt`. Choose unused
output directories. Existing pinned data and native keys can be reused without
rebuilding them; every run verifies their complete source and artifact identities.

For a fresh checkout with no prepared inputs, use the existing preparation and
native export commands. They preserve actual timestamps and missing grid bars:

```sh
FILANG_DATA_DIR="$PWD/data/geometry-direction"
FILANG_KEYS_DIR="$PWD/runs/geometry-interaction-replay-keys"
.venv/bin/python scripts/prepare_direction.py --out "$FILANG_DATA_DIR"
cargo +1.63.0 build --release --locked --offline
for minutes in 15 30 60 120 240
do
  target/release/filang geometry-key-export \
    --data "$FILANG_DATA_DIR/${minutes}m/ohlcv.csv" \
    --interval-seconds "$((minutes * 60))" \
    --history-start 2020-01-01 --end 2026-10-08 --bars 10 \
    --out "$FILANG_KEYS_DIR/${minutes}m"
done
```

The data preparer uses the original immutable direction protocol and rejects
changed downloads or invalid source data. The native export includes every
causal ten-bar row, including rows without an available next-bar label. Native
context and executable hashes may differ when rebuilding on another platform;
each fresh export and replay records its actual identities. Replaying the
original retained byte identities requires the original sealed artifacts.

Run the producer and full independent audit from a clean committed worktree:

```sh
.venv/bin/python experiments/geometry_information/run_round3.py \
  --data-dir "$FILANG_DATA_DIR" --keys-dir "$FILANG_KEYS_DIR" \
  --out runs/geometry-interactions-r3-replay \
  --protocol experiments/geometry_information/round3_protocol.json \
  --freeze-commit bcc49b113c59f2a2c72524605d26b2dedca98353 \
  --workers 5 --blas-threads 2
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 \
.venv/bin/python experiments/geometry_information/verify_round3.py \
  --stage full --run runs/geometry-interactions-r3-replay \
  --data-dir "$FILANG_DATA_DIR" --keys-root "$FILANG_KEYS_DIR" \
  --protocol experiments/geometry_information/round3_protocol.json \
  --out runs/geometry-interactions-r3-replay/verification.json
.venv/bin/python experiments/geometry_information/collect_round3.py \
  --run runs/geometry-interactions-r3-replay --keys-dir "$FILANG_KEYS_DIR" \
  --out runs/geometry-interactions-r3-replay-report
```

The executable rejects unrecognized protocol bytes, the wrong freeze, a dirty
worktree, changed input bindings or an existing run directory. The collector
requires a full accepted audit and preserves the producer's original pending-audit
status. It joins that immutable record to the audit without rewriting the run.
A separately supplied `--launcher` receipt and repeated `--audit-receipt` arguments
can retain external command, exit, timing and log evidence alongside the report.

Every timeframe retains all coefficients, fitting statistics, model and policy
choices, ledger metrics and array-member identities. Four annual NPZ bundles
contain complete predictions and all ledger traces, trades, gaps and calendar-day
returns. A fifth NPZ contains all ordinary, centered and exact-hit bootstrap
arrays; `bootstrap-exact.json` retains the complete signed integer encodings.
NPZ loads forbid pickle. The compact report copies all compact records and binds
the external bundles by exact bytes, hashes and member counts. No losing trial,
cash choice, outer year or timeframe is removed.

Runtime receipts include package and BLAS details, process/thread settings,
sufficient-statistics construction, fit/selection/policy/inference/serialization
stage timings and peak memory. Some phase timings explicitly encompass nested
work; they must not be added as if every interval were disjoint. The measured
producer and independent audit wall times are operational evidence, without a
matched speedup or compute-ceiling claim.
