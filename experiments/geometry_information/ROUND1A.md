# R1a — exact Newton numerical amendment

[PR #25](https://github.com/mikkokotila/Filang/pull/25) continues the
[audited R1 numerical failure](../../benchmarks/reports/20261008-geometry-information-r1-failed/README.md).
The original attempt remains scientifically inconclusive. R1a uses a separately
published solver specification and starts every required fit afresh.

The authoritative [protocol](round1a_protocol.json) was published in commit
`3df6416a2de59ac396617be49326a834c94aca92`, with SHA-256
`cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34`.
An independent comparison found that only the attempt identifiers, protocol
status, optimizer specification and amendment record differ from R1.

## Recorded outcome

The [complete measured report](../../benchmarks/reports/20261008-geometry-information-r1a/README.md)
records a full execution and independent audit. All 680 fits passed the frozen
acceptance test. The information claim is **supported at 30m only**: pooled
B-minus-G gain 0.0005687511 nats per binary observation, 95% interval
[0.0002508591, 0.0008935404], Holm-adjusted p=0.00249875, and three of four
positive annual effects. The 2026 effect was negative. The other four primary
timeframes are not supported by the complete criterion.

No selected G fixed-threshold policy is profitable at primary or reduced costs
when aggregating its four annual folds. Every one of the 20 G annual primary-cost
net log returns is negative. Buy-and-hold and unconditional controls are positive;
these observations do not establish that every possible geometry policy loses.
The economic residue motivates a separately frozen test of conditional payoff
and cost-aware policy selection.

The original launcher measured 106.97062174999155 seconds for the complete
producer. Independent full audit took 172.01818441599607 seconds, covering all
458,972 native keys, 640 candidate fits, 40 refits, 40 full-row prediction
artifacts, inference replicas and 960 ledger replays. Maximum checked numerical
discrepancy was 2.128217602148652e-10, within the prescribed absolute-plus-relative
tolerance. These are operational timings, without a matched speedup claim.

## Scientific contract

The five source snapshots, exact geometry features, common ten-candle validity,
open-to-open target, four chronological folds, n=2/3/5/10 candidate histories,
four L2 penalties, validation selection, baselines, bootstrap, costs and economic
ledger remain unchanged. The complete procedure still requires 640 inner fits
and 40 selected refits. See the [R1 reference](README.md) for that contract.

R1a tests whether pooled endpoint geometry improves direction log loss beyond
body and close-return sign history. The original four-part predictive criterion
and complete independent audit remain necessary. Its fixed-threshold economic
outputs remain descriptive. All historical data and R1's retained partial inner
validation scores are exposed; neither a new solver nor chronological nesting
makes these observations fresh.

## Numerical method

For A=[ones,X], theta=[intercept,beta], and z=A*theta, minimize the unchanged
float64 objective:

\[
f(\theta)=N^{-1}\sum_i[\log(1+e^{z_i})-y_i z_i]
             +\lambda\lVert\beta\rVert_2^2/2.
\]

The implementation evaluates the first term with `logaddexp`. Its analytic
gradient is the original R1 gradient. With q=exp(-abs(z)), compute stable weights
w=q/(1+q)^2 and the full Hessian:

\[
H=A^\top\operatorname{diag}(w/N)A+
  \operatorname{diag}(0,\lambda,\ldots,\lambda).
\]

The block implementation avoids making an augmented copy of the full design
matrix. At the largest declared dimension, the Hessian has 347 squared float64
entries: 963,272 bytes, about 0.92 MiB. That figure describes the Hessian only;
design matrices and temporary arrays use additional memory. Correlated and
constant columns remain present and penalized as specified.

Solve H*d=-gradient using SciPy
[cho_factor](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_factor.html)
and [cho_solve](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_solve.html),
with lower-triangle factorization and finite checks. Require a finite descent
direction. There is no jitter, pseudoinverse, substitute solver or additional
regularization.

Try alpha=2^-j for j=0,...,49, accepting the first finite trial satisfying
f(theta+alpha*d) <= f(theta)+1e-4*alpha*(gradient dot d). Permit at most 100
accepted updates. Optimizer success requires max(abs(gradient)) <=1e-7, checked
at initialization and after every accepted update, including update 100.
Small steps or objective changes alone cannot produce success. The existing
final acceptance conjunction remains: success, finite parameters/objective/
gradient, and independently checked maximum absolute gradient <=5e-6.

Each fit retains accepted step sizes, backtracking counts, evaluation counters,
termination reason, full parameters and gradient. Initialization and every
Armijo trial evaluate objective and gradient together; each attempted Newton
update evaluates one Hessian. Terminal independent recomputation is outside
those optimizer counters. All failure statuses remain recorded.

## Execution and audit

Use the completed PR #25 implementation tree for replay. The freeze commit
contains the specification; the subsequent implementation commit is recorded in
the run. The final verifier checks the exact producer source hashes, so restore
the recorded experiment tree when replaying after later code changes.

From the research checkout on the recorded execution machine:

```sh
FILANG_DATA_DIR=/Users/mikkokotila/dev/Filang-direction/data/geometry-direction
FILANG_KEYS_DIR=/Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1
.venv/bin/python experiments/geometry_information/run_round1.py \
  --data-dir "$FILANG_DATA_DIR" --keys-dir "$FILANG_KEYS_DIR" \
  --out runs/geometry-information-r1a \
  --protocol experiments/geometry_information/round1a_protocol.json \
  --freeze-commit 3df6416a2de59ac396617be49326a834c94aca92 \
  --workers 5 --blas-threads 2
.venv/bin/python experiments/geometry_information/verify_round1.py \
  --stage full --run runs/geometry-information-r1a \
  --data-dir "$FILANG_DATA_DIR" --keys-root "$FILANG_KEYS_DIR" \
  --protocol experiments/geometry_information/round1a_protocol.json \
  --out runs/geometry-information-r1a/verification.json
.venv/bin/python experiments/geometry_information/collect_round1.py \
  --run runs/geometry-information-r1a \
  --out benchmarks/reports/20261008-geometry-information-r1a
```

The output directory must be fresh. Relocate source/key roots explicitly when
reproducing elsewhere, preserving their pinned bytes. Reuse of original R1 fits
or failed coefficients is forbidden. The existing audited source and geometry
key artifacts can be reused; within-attempt stronger-to-weaker warm starts
follow the unchanged exact-sample rule.

The independent audit reconstructs all geometry keys and feature projections,
every fitting sample, terminal objective and gradient, candidate validation
score and selection, all full-row causal predictions, paired inference and
economic ledgers. A complete report requires all five timeframes and every
required pipeline. Operational timings are retained, with no matched speedup
claim from this numerical amendment.
