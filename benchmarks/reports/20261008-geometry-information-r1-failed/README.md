# Round 1 — numerical failure, scientifically inconclusive

**The frozen R1 attempt is inconclusive.** All five timeframe workers stopped
at a required geometry-model fit after L-BFGS-B reached its frozen 1,000-iteration
limit. The retained record contains no outer predictions, primary inference or
economic ledgers. This is a failure to complete the prescribed estimator, not
evidence that geometry lacks predictive information or that any policy is
tradeable or untradeable.

The subsequent independent **forensic audit passed**. That means the retained
source, feature, model, score, selection and failure records reconcile. It does
not mean that the incomplete scientific hypothesis passed. The audit explicitly
states `experiment_status=FAILED`, `outcome=inconclusive`,
`criterion_evaluable=false` and `scientific_models_checked=false`.

## Where the attempt stopped

| Minutes | G history | Lambda | Iterations | Max absolute gradient | Gradient ≤5e-6 | Optimizer termination |
| --- | --- | --- | --- | --- | --- | --- |
| 15 | 10 | 0.0001 | 1000 | 2.344195862e-06 | yes | STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT |
| 30 | 10 | 0.0001 | 1000 | 6.4626746e-06 | no | STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT |
| 60 | 10 | 0.0001 | 1000 | 1.836918705e-06 | yes | STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT |
| 120 | 10 | 0.0001 | 1000 | 2.568179173e-06 | yes | STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT |
| 240 | 5 | 0.0001 | 1000 | 2.949754857e-07 | yes | STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT |

Every rejected fit is in the first outer-year pipeline, 2023, using its declared
2020–2021 inner training period. At four resolutions the failed candidate has
history ten; the 240-minute worker stops earlier at history five. All use lambda
0.0001. The frozen acceptance rule requires **both** optimizer success and a
finite maximum absolute analytic gradient at most 5e-6. Four rejected fits meet
the gradient bound but fail optimizer success; the 30-minute fit also exceeds
the gradient bound. The run correctly did not waive either requirement, silently
drop a required candidate, extend the budget after inspecting scores, or continue
to outer evaluation.

There are **161 retained fits**: 151 accepted and validation-scored inner
candidates, five rejected inner candidates, and five accepted B refits. Five B
choices were completed before the corresponding G search stopped. The planned
complete design requires 640 inner candidates and 40 selected refits, so the
retained prefixes cannot substitute for that design or establish B versus G
outcomes. Partial inner validation scores are preserved for accountability,
not promoted as primary results.

## Exact evidence and audit scope

The package preserves every producer artifact byte for byte, including each
timeframe's complete `fits.jsonl`, all 161 individual model records, five B
selections, the five small rejected-parameter NPZ attachments, worker failures,
all five source/feature identities, and runtime/provenance receipts.
[retained-fits.jsonl](retained-fits.jsonl) concatenates the five original journals
in ascending timeframe order; [retained-validation-scores.csv](retained-validation-scores.csv)
provides the 151 recorded candidate scores. These are derived indexes; the
original journals and individual files remain separately sealed.

[verification.json](verification.json) records independent reconstruction of
458,972 native keys and all retained projections, fit rows and labels, objectives
and analytic gradients, acceptance flags, candidate validation scores, completed
family selections and worker failures. It performs no new optimizer run. It also
checks that no post-failure prediction or economic output was retained. Its
coverage and maximum numerical discrepancies are the authoritative audit receipt.
The run's [original manifest](producer-manifest.json) remains unchanged; this
package has a separate [manifest](manifest.json) binding the producer copies,
later audit and this report without a self-hash cycle.

Any retained initial forensic-adapter rejection/log is an audit-development
receipt, not a second market experiment. The adapter initially disallowed NPZ
files too broadly; the five rejected-fit parameter attachments require separate
parameter comparison, rather than being mistaken for predictions. Only the
final failed-stage PASS authorizes this collection.

The five immutable Vaquum sources span 2020-01-01 through 2026-10-07 and contain
459,503 observed candles at 15, 30, 60, 120 and 240 minutes. Source pins and hashes
are preserved in [protocol.json](protocol.json) and [provenance.json](provenance.json).
All historical data, including earlier reported results, were already exposed.
No fresh-holdout claim is made.

## Protocol interpretation and implementation identity

The protocol's `estimation.outer_use` restriction is **relative to each outer
fold**, following its explicit chronological schedule. A fold's outer labels
cannot select or fit that fold's pipeline. Once time advances, those dates may
become past training or the preceding-year validation sample for a later fold,
as the frozen schedule explicitly specifies. This clarification does not change
the protocol JSON or permit same-fold leakage. No outer-label results were
produced in this failed attempt.

The frozen protocol commit is `b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd`; exact SHA-256 is
`abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a`. Execution used clean implementation commit
`17457a99ce3d5b25cd6ff33deefd6ed3fec60bca`, with exact source-file hashes and numerical-library
configuration in [run.json](run.json). Native causal feature preparation occurred
before the protocol freeze; fitting used the subsequently frozen specification.

The launcher measured **77.744591750 seconds** wall time and exit code
1, with 5 timeframe workers
and configured BLAS thread limit 2 per process.
[launcher.json](launcher.json) is an operational receipt for this failed run,
not a completed experiment runtime benchmark or a speedup result. Native context,
manifest and timing receipts are retained under `native/`.

## Reproduction and next attempt

Reproduce the attempted computation using Python 3.13.2, the pinned
`requirements-information.txt`, retained implementation commit and exact inputs.
The recorded producer command is:

```sh
/Users/mikkokotila/dev/Filang-research/.venv/bin/python /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/run_round1.py --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 --out /Users/mikkokotila/dev/Filang-research/runs/geometry-information-r1 --protocol /Users/mikkokotila/dev/Filang-research/experiments/geometry_information/round1_protocol.json --freeze-commit b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd --workers 5 --blas-threads 2
```

Use a fresh output directory; the failed run remains immutable. Audit and collect
that original run without refitting:

```sh
python experiments/geometry_information/verify_round1.py \
  --stage failed --run runs/geometry-information-r1 \
  --keys-root runs/geometry-information-keys-v1 \
  --data-dir data/geometry-direction \
  --protocol experiments/geometry_information/round1_protocol.json \
  --out runs/geometry-information-r1-failed-verification.json
python experiments/geometry_information/collect_failed.py \
  --run runs/geometry-information-r1 \
  --launcher runs/geometry-information-r1-launch.json \
  --verification runs/geometry-information-r1-failed-verification.json \
  --out benchmarks/reports/20261008-geometry-information-r1-failed
```

The empirical residue is numerical: the initial solver budget did not complete
the required weakly penalized geometry candidates. The next proposed attempt is
a separately frozen solver amendment in a subsequent published pull request,
with its own criterion and full outcome record. It must preserve this failure
and disclose already inspected inner scores. Changes to numerical method or
iteration budget must be declared before execution; the original attempt must
not be relabeled successful retrospectively. No new economic selection or
positive-edge claim follows from this failure. See [the finite campaign](../../../experiments/geometry_information/CAMPAIGN.md)
and [PR #24](https://github.com/mikkokotila/Filang/pull/24).
