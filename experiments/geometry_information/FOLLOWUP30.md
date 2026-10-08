# F30-D1 — follow the 30-minute directional signal

This separately declared follow-up continues the 30-minute research lead from
[R1a](ROUND1A.md), after the original [three-family campaign](CAMPAIGN.md) was
completed. The user explicitly requested this continuation on 2026-10-08. The
earlier campaign, negative economic results, and stopping record remain evidence.
The authoritative machine-readable specification is
[followup30_protocol.json](followup30_protocol.json).

## Question and scope

Does the selected geometry pipeline retain its directional log-loss advantage
after the baseline and geometry scores receive the same small, past-only
probability adjustment, and is that advantage present in the latest pinned
2026 period?

R1a found a 30-minute B-minus-G pooled log-loss improvement of
0.0005687510773535314 nats per binary observation. Its original five-timeframe
Holm-adjusted p-value was 0.0024987506, three annual effects were positive, and
the partial 2026 effect was negative. The fixed-policy economic diagnostic lost
money. R2 and R3 subsequently failed their incremental economic criteria.

F30-D1 tests one explanation of this residue. Probability scoring gives each
nonflat event equal weight. Economic value also depends on the sizes of positive
and negative moves, exposure persistence, and execution costs. A probability
improvement may also depend on calibration or on a comparator's confidence scale.

This is retrospective diagnosis on a timeframe selected because of its earlier
outcome. All source observations and preceding campaign results were already
inspected. A new protocol, exact arithmetic, or another chronological evaluation
cannot turn them into fresh confirmation. The claim is relative to the specified
pipelines; it does not identify conditional mutual information or a causal wick
effect.

## Fixed inputs and prediction ownership

Use the exact original R1a 30-minute selected forecasts, their model coefficients,
selection records, sidecars, original full audit, and sealed producer manifest.
No B/G model is refitted and no new history, penalty, geometry feature, horizon,
or policy is selected.

The source contains 118,576 observed rows and 118,432 eligible causal ten-bar
geometry keys. The raw and prepared source identities, exact native artifacts,
original protocol, original run manifest and audit hashes are pinned in the new
protocol. The original R1a source run is read-only.

There are eight original prediction bundles: validation and outer phases for
2023, 2024, 2025, and partial 2026. Each aligns to every original CSV row.
Validation forecasts come from the selected **inner-training model**; outer
forecasts come from its later **pre-year refit**. Recomputing validation scores
with that refit would train on their own labels and is forbidden.

At the scheduled close of candle t, the direction target is

\[
y_t=\mathbf1\{O_{t+2}>O_{t+1}\},
\]

conditional on a nonzero difference. R1a's stored numerical return is the simple
return `O[t+2]/O[t+1]-1`. The new magnitude diagnostics explicitly reconstruct
`log(O[t+2]/O[t+1])` directly from the pinned opening prices.

Binary fitting and scoring exclude true flat outcomes. Payoff summaries retain
them. Classification eligibility requires all twelve original candles from
t−9 through t+2 to be consecutive and the exit opening to precede the phase end
strictly. Causal forecasts remain available when their future target is absent.
A future-label mask must never control whether a forecast is produced.

## Matched affine score adaptation

For each family M in {B,G} and each outer year, fit

\[
\widetilde p_M(z)=\operatorname{sigmoid}(a_M+b_Mz)
\]

using only the original selected inner-validation logits z and binary labels.
The fixed objective is

\[
\frac1N\sum_i
\left[\log(1+e^{a+bz_i})-y_i(a+bz_i)\right]
+\frac{10^{-4}}2\left[a^2+(b-1)^2\right].
\]

Both parameters are penalized around the identity mapping (0,1). There is no
penalty search. The positive penalty makes even a constant-score or single-class
sample's finite problem strictly convex. An empty fitting sample is invalid.

Use exact two-parameter Newton updates with the analytic Hessian, Cholesky
factorization, and Armijo backtracking. Start at (0,1), allow at most 100 accepted
updates, and try step sizes 2^−j for j=0,...,49. Success requires finite parameters,
objective and gradient with maximum absolute gradient at most 1e−10, including
the check after update 100. There is no jitter, alternate optimizer, clipping,
changed penalty, or small-step success condition. Retain a failed required fit
and classify the incomplete attempt as inconclusive.

The slope is unconstrained. A negative slope reverses ranking; a zero slope
collapses it. Record these cases explicitly. This is therefore an affine score
adaptation experiment, without an assumed monotonicity guarantee.

Apply the fixed parameters to every available original outer logit, including
causal predictions without an available future label. There are eight fits in
total. Store complete parameters, sample and model bindings, objective, gradient,
accepted steps, convergence status, and all transformed prediction arrays.

The original validation labels already selected the base model's hyperparameters.
They are reused for adaptation. This is disclosed past-stage selection reuse;
the outer labels still do not fit their own pipeline. The inner model's validation
score distribution may differ from the refit's outer score distribution. The
experiment tests that transported mapping, not an oracle decomposition of
calibration and discrimination.

## One primary decision

The primary observation is adapted B log loss minus adapted G log loss, on the
same original nonflat mask. Aggregate paired sums and binary counts by target-exit
UTC date. Retain all 1,376 calendar days, including zero-count days.

The complete claim is supported only if all six conditions hold:

1. The pooled per-observation adapted gain is positive.
2. Its individual primary 95% confidence interval has a positive lower endpoint.
3. Its primary one-sided p-value is below 0.05.
4. At least three of the four annual point estimates are positive.
5. The partial 2026 point estimate is positive.
6. Every required fit and the full independent audit pass.

The latest-year condition is a deliberately conservative stability requirement,
motivated by the already known deterioration. Pooled support with a negative
2026 result remains visible and fails the complete stability claim. A valid
completed failure is `not-supported`; a missing fit or failed audit is
`inconclusive`. Neither means that all geometry information has been disproved.

There is one new primary comparison. The selected-timeframe and earlier adaptive
research exposure remain explicit; its nominal p-value does not establish a
campaign-wide error guarantee. No diagnostic or sensitivity offers another route
to `supported`.

### Exact inference with varying observation counts

Use 2,000 paired, year-stratified circular block-bootstrap replicas. Seven-day
blocks are primary; one- and 28-day blocks are sensitivities. The seed and draw
order follow the frozen protocol. Resample each day's paired sum and binary count
together, and estimate each replicate as total sum divided by total count.

The number of observations changes under resampling even though the number of
calendar days does not. R3's fixed-denominator predicate therefore cannot be
reused unchanged.

Represent the executed daily paired sums as exact binary rationals over a common
positive power-of-two denominator. Write S for their original integer sum,
N for the original binary count, T for a resampled integer sum, and N* for its
resampled binary count. The globally centered one-sided tail event is

\[
\frac{T}{N^*}-\frac{S}{N}\ge\frac{S}{N}
\quad\Longleftrightarrow\quad NT\ge2SN^*.
\]

The common power-of-two denominator cancels. Count equality exactly, without a
floating comparison or epsilon. Retain all integer encodings, resampled counts,
6,000 boolean tail decisions, and ordinary and centered float replicas. Means
and percentile intervals remain float64 calculations. A zero required count
makes inference inconclusive; it does not cause a redraw or omitted replicate.

The independent audit first reconstructs continuous daily values within the
declared numerical tolerance, then verifies exact tail arithmetic on the retained
and independently validated executed values. Exact discrete arithmetic does not
make approximate account or score reconstruction bit-identical.

## Fixed explanatory diagnostics

Every diagnostic is descriptive. The implementation retains raw and adapted B/G
results, all annual periods, all UTC months, every leave-one-year-out aggregate,
complete support counts, and score distributions in both validation and outer
phases. AUC gives exact ties half credit and is unavailable without both classes.
No exact binned calibration/discrimination decomposition is asserted.

Three complete partitions are recorded:

| Partition | Frozen construction | Interpretation |
|---|---|---|
| Realized magnitude | True flat separately; nonflat absolute log returns below 1, 1–5, 5–12, 12–24, and at least 24 bps | Ex-post outcome strata, unavailable as entry filters |
| Shared direction decision | The four B/G combinations at probability >=0.5, separately for raw and adapted scores | Paired contribution decomposition; not a trade ledger |
| Score buckets | Four 20/40/60/80% cuts from preceding validation causal probabilities, separately per family, variant and year | Past-defined reliability/payoff views with distinct B/G memberships |

Quantile cuts use linear interpolation, sorted unique boundaries, and equality
assigned to the upper bucket. Retain empty outer buckets. Never merge bins based
on outcomes. Year-specific score buckets are not pooled by ordinal bucket number.

For each cell, retain target-valid, binary, up, down and flat counts, probabilities,
paired score contributions, and positive and negative return magnitudes. Missing
conditional quantities are null; contribution sums still reconcile to the full
sample. No tail trimming or favorable-period exclusion is permitted.

### Probability and payoff

For a cell with both nonflat sign classes, let z be its flat frequency, q its up
frequency conditional on a nonflat return, m+ its mean positive log return, and
m− the magnitude of its mean negative log return. The empirical identity is

\[
\overline r=(1-z)\left[qm_+-(1-q)m_-\right].
\]

Positive and negative contribution sums provide the corresponding identity when
a conditional mean is undefined. Retain the reconciliation error.

For an isolated one-bar round trip at the existing primary cost assumption,

\[
k=-\log\left((1-f)^2\frac{1-s}{1+s}\right),
\qquad f=0.001,\quad s=0.0002,
\]

the descriptive break-even frequency is

\[
q^*=\frac{m_-+k/(1-z)}{m_++m_-}.
\]

Do not clip q* to [0,1]. This uses realized cell outcomes and is not a deployable
threshold for a persistent position policy.

Also retain absolute-return-weighted paired log-loss gain and score-to-payoff
alignment, including

\[
E[(p_G-p_B)(r-\mu_{\rm past})].
\]

The past mean comes only from that fold's original target-valid validation sample,
including flat returns, and is shared by B and G. No outer mean is used to fit
this centering. These are associations and reweighted scoring diagnostics, not
realized strategy P&L or additional primary tests.

## Bounded continuation

This follow-up permits F30-D1 and at most one subsequent, separately frozen
F30-M1 probability-to-payoff experiment. Its gate requires the complete D1 primary
claim to pass, plus positive adapted drift-centered payoff alignment pooled,
in partial 2026, and in at least three annual periods. Alignment is a descriptive
feasibility veto, not a second inferential success claim.

If that gate passes, the permitted next object preserves the same directional
heads and adapters and maps probability through common past-only flat frequency
and signed return magnitudes. It must include the mapped baseline, unconditional
mean, cash and buy-and-hold controls, with fully frozen chronology, policy,
execution and cost rules. Attractive diagnostic buckets cannot choose its
magnitude-conditioning scheme.

If the gate fails, retain the diagnostic findings and close this bounded
follow-up. Do not enlarge the architecture or historical search to obtain a
favorable result. Any later live tradeability claim still needs a separately
frozen future-data evaluation and execution evidence.

## Audit and reproducible evidence

The verifier independently reconstructs all 118,432 native keys and all consumed
original selected predictions from raw OHLC and retained coefficients. The
original pinned full audit remains the evidence for unconsumed original candidate
fits and timeframes. The new audit checks every adapter's objective and gradient,
all transformations, masks, diagnostic cells, partitions, daily arrays, exact
tails, decision criteria, and continuation gate.

The new producer's fitting, scoring, partitioning and bootstrap helpers are not
imported by the new verifier. Established independent raw-OHLC oracle primitives
may be reused with their source identities recorded. Floating comparisons use
absolute 1e−10 plus relative 1e−10 tolerance; integer identities, masks, membership,
counts, exact encodings and decisions agree exactly.

The report includes every consumed original prediction bundle and compact model
record, preserving original relative paths in a scoped input bundle, plus the
exact native artifacts. Original raw Parquet and prepared CSV identities remain
externally pinned. Fresh output directories, an admitted published freeze, and a
clean committed implementation are required. Runtime and memory measurements are
operational receipts, with no matched speedup claim.

The producer seals its original `COMPLETE_PENDING_INDEPENDENT_AUDIT` record.
Verification and report collection add their own evidence without rewriting that
record. No failed fit, unfavorable cell, outer period, or missing support may
disappear from the final report.

## Reproduction

Use the completed PR #28 implementation tree. The published freeze
`ed7e0b9bccedebc6bda75d7ab701829a6a708c5f` contains the specification and reference;
it does not contain the later executable implementation. The protocol SHA-256 is
`4099e7a6620387d0fbe2267819ca0d37dff0f52da3e6bf8689705e979adf497b`.

The original run uses the existing pinned source preparation. The complete D1
report also retains the scoped original forecasts and native artifacts, so a
new checkout can replay this diagnosis without regenerating the earlier model
search. Set up the pinned environment and prepare the immutable raw/CSV inputs
only when they are not already available:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-direction.txt -r requirements-information.txt
FILANG_DATA_DIR="$PWD/data/geometry-direction-replay"
.venv/bin/python scripts/prepare_direction.py --out "$FILANG_DATA_DIR"
FILANG_D1_SOURCE="$PWD/benchmarks/reports/20261008-30m-signal-followup-d1/run"
```

Fresh preparation may have different absolute paths in its provenance metadata.
The exact archived predecessor provenance is preserved in the source bundle;
the loader independently verifies the relocated raw and CSV bytes against its
immutable pins. It neither overwrites new metadata with old paths nor requires
different locations' metadata files to be byte-identical.

Run from a clean published checkout, using unused output directories outside
every immutable input tree:

```sh
.venv/bin/python experiments/geometry_information/run_followup30.py \
  --r1a-run "$FILANG_D1_SOURCE/predecessor" \
  --data-dir "$FILANG_DATA_DIR" \
  --keys-dir "$FILANG_D1_SOURCE/native" \
  --protocol experiments/geometry_information/followup30_protocol.json \
  --freeze-commit ed7e0b9bccedebc6bda75d7ab701829a6a708c5f \
  --blas-threads 2 --out runs/geometry-followup30-d1-replay
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 \
.venv/bin/python experiments/geometry_information/verify_followup30.py \
  --stage full --run runs/geometry-followup30-d1-replay \
  --data-dir "$FILANG_DATA_DIR" \
  --protocol experiments/geometry_information/followup30_protocol.json \
  --out runs/geometry-followup30-d1-replay/verification.json
.venv/bin/python experiments/geometry_information/collect_followup30.py \
  --run runs/geometry-followup30-d1-replay \
  --out runs/geometry-followup30-d1-replay-report
```

On the original machine, the producer may instead read
`/Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1a` as
`--r1a-run` and
`/Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1` as
`--keys-dir`, with prepared data at
`/Users/mikkokotila/dev/Filang-direction/data/geometry-direction`.
Both routes admit the same original selected forecast and native bytes.

The collector's repeated `--receipt` option can include external launch, audit,
test and log files. Operational receipts remain outside the immutable producer
directory; within that directory the later full audit occupies only the fresh
canonical `verification.json`. A failed audit is preserved before any separate
retry is considered.

## Conceptual references

- Gneiting and Raftery (2007), [Strictly Proper Scoring Rules, Prediction, and
  Estimation](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf),
  provides the scoring-rule context. The experiment distinguishes a probability
  score from an economic decision utility.
- Niculescu-Mizil and Caruana (2005), [Predicting Good Probabilities With Supervised
  Learning](https://icml.cc/Conferences/2005/proceedings/papers/079_GoodProbabilities_NiculescuMizilCaruana.pdf),
  motivates examining probability adaptation alongside ranking and accuracy.
  The exact penalty, solver, and scientific criterion here are this protocol's
  choices, not a result supplied by that paper.
