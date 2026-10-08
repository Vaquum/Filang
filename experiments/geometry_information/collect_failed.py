#!/usr/bin/env python3
"""Preserve the audited R1 numerical failure; never promote it to science PASS."""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import shlex
import sys

try:
    from . import collect_round1 as report
except ImportError:
    import collect_round1 as report

IMPLEMENTATION_COMMIT = "17457a99ce3d5b25cd6ff33deefd6ed3fec60bca"
COVERAGE = {"native_keys": 458972, "fits": 161, "candidate_fits": 156,
            "accepted_candidate_fits": 151, "candidate_validation_scores": 151,
            "refit_fits": 5, "rejected_fits": 5, "selections": 5,
            "outer_predictions": 0, "validation_predictions": 0, "ledger_replays": 0,
            "all_retained_records": True, "sampled": False}
CHECKS = ("raw_source_provenance", "all_native_keys_and_projections",
          "all_retained_fit_rows_labels_objectives_gradients", "all_retained_acceptance_flags",
          "all_retained_candidate_validation_scores", "all_retained_complete_family_selections",
          "all_worker_failure_records", "no_post_failure_predictions_or_economics",
          "all_retained_artifact_identities", "no_optimizer_run_by_verifier", "all_failed_parameter_arrays")


def checked_artifacts(run):
    manifest = report.load_json(run / "manifest.json")
    report.require(report.digest(run / "manifest.json") == (run / "manifest.sha256").read_text().strip(),
                   "failed producer manifest seal differs")
    files = {}
    for relative, expected in manifest["files"].items():
        source = report.bounded(run, relative)
        report.require(source.is_file() and report.file_record(source) ==
                       {"bytes": expected["bytes"], "sha256": expected["sha256"]},
                       "failed-run artifact identity differs: " + relative)
        report.require("/economics/" not in relative and not relative.endswith(("/outer.npz", "/validation.npz",
                       "/outer.json", "/validation.json", "/summary.json")) and
                       relative not in ("analysis.json", "classification_daily.csv", "selected.json", "candidates.csv"),
                       "failure package contains predictive/economic outputs")
        report.require(not relative.endswith(".npz") or relative.endswith("-failed-parameters.npz"),
                       "unexpected binary artifact in numerical-failure run")
        files[relative] = source
    required = {"protocol.json", "provenance.json", "run.json"}
    for m in report.TIMEFRAMES:
        required.update({f"{m}m/features.json", f"{m}m/fits.jsonl", f"{m}m/2023/B/selected.json",
                         f"{m}m/2023/B/refit.json", f"failure-{m}m.json"})
    report.require(required <= set(files), "failure artifact coverage is incomplete")
    report.require(sum(p.endswith("-failed-parameters.npz") for p in files) == 5,
                   "five rejected parameter attachments must remain retained")
    return manifest, files


def check_audit(run, audit):
    report.require(audit["schema"] == "filang-geometry-information-verification-v1" and
                   audit["stage"] == "failed" and audit["status"] == "PASS", "full failed-stage forensic audit required")
    report.require(audit["experiment_status"] == "FAILED" and audit["outcome"] == "inconclusive" and
                   audit["criterion_evaluable"] is False, "forensic PASS must not imply scientific success")
    report.require(audit["scientific_models_checked"] is False and audit["retained_model_parameters_checked"] is True,
                   "forensic scope differs")
    report.require(audit["protocol_sha256"] == report.PROTOCOL_SHA256 and
                   audit["producer_manifest_sha256"] == report.digest(run / "manifest.json") and
                   audit["analysis_sha256"] is None, "forensic audit identity differs")
    report.require(audit["audited_timeframes"] == list(report.TIMEFRAMES) and audit["audited_outer_years"] == [2023],
                   "forensic timeframe/year coverage differs")
    report.require(all(audit["coverage"].get(k) == v for k, v in COVERAGE.items()), "forensic retained-record coverage differs")
    report.require(all(audit["checks"].get(k) is True for k in CHECKS), "forensic check missing or failed")
    report.require(len(audit["failures"]) == 5, "five rejected fits must be audited")


def retained_fits(run, files):
    fits, selections = [], []
    for m in report.TIMEFRAMES:
        rows = [json.loads(s) for s in (run / f"{m}m/fits.jsonl").read_text().splitlines() if s.strip()]
        report.require(len(rows) == (29 if m == 240 else 33), "per-timeframe retained fit count differs")
        for fit in rows:
            report.require(fit["minutes"] == m and fit["outer_year"] == 2023 and fit["path"] in files,
                           "retained fit identity/scope differs")
            report.require(report.load_json(files[fit["path"]]) == fit, "journal differs from individual model record")
        fits.extend(rows)
        selections.append(report.load_json(run / f"{m}m/2023/B/selected.json"))
    counts = {"fits": len(fits), "candidate_fits": sum(f["stage"] == "inner" for f in fits),
              "accepted_candidate_fits": sum(f["stage"] == "inner" and f["accepted"] for f in fits),
              "candidate_validation_scores": sum("validation_scores" in f for f in fits),
              "refit_fits": sum(f["stage"] == "refit" for f in fits),
              "rejected_fits": sum(not f["accepted"] for f in fits), "selections": len(selections)}
    report.require(all(v == COVERAGE[k] for k, v in counts.items()), "retained model census differs")
    report.require(all(f["accepted"] and f["family"] == "B" for f in fits if f["stage"] == "refit"),
                   "unexpected completed refit")
    fit_paths = {f["path"] for f in fits}
    report.require(fit_paths == {p for p in files if "/candidates/" in p and p.endswith(".json") or p.endswith("/refit.json")},
                   "unaccounted retained model")
    rejected = [f for f in fits if not f["accepted"]]
    report.require(all(f["optimizer"]["success"] is False and f["optimizer"]["iterations"] == 1000 and
                       f["family"] == "G" and f["lambda"] == .0001 for f in rejected),
                   "this collector describes the recorded R1 iteration-limit failure only")
    return fits, selections, rejected


def readme(identity, audit, launcher, rejected):
    rows = [[f["minutes"], f["n"], f["lambda"], f["optimizer"]["iterations"],
             f'{f["max_abs_gradient"]:.10g}', "yes" if f["max_abs_gradient"] <= 5e-6 else "no",
             f["optimizer"]["message"]] for f in rejected]
    table = report.table(["Minutes", "G history", "Lambda", "Iterations", "Max absolute gradient",
                          "Gradient ≤5e-6", "Optimizer termination"], rows)
    command = shlex.join(identity["command"])
    elapsed = launcher["elapsed_seconds"]
    return f"""# Round 1 — numerical failure, scientifically inconclusive

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

{table}

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

The frozen protocol commit is `{report.FREEZE_COMMIT}`; exact SHA-256 is
`{report.PROTOCOL_SHA256}`. Execution used clean implementation commit
`{IMPLEMENTATION_COMMIT}`, with exact source-file hashes and numerical-library
configuration in [run.json](run.json). Native causal feature preparation occurred
before the protocol freeze; fitting used the subsequently frozen specification.

The launcher measured **{elapsed:.9f} seconds** wall time and exit code
{launcher["exit_code"]}, with {identity["settings"]["workers"]} timeframe workers
and configured BLAS thread limit {identity["settings"]["blas_threads"]} per process.
[launcher.json](launcher.json) is an operational receipt for this failed run,
not a completed experiment runtime benchmark or a speedup result. Native context,
manifest and timing receipts are retained under `native/`.

## Reproduction and next attempt

Reproduce the attempted computation using Python 3.13.2, the pinned
`requirements-information.txt`, retained implementation commit and exact inputs.
The recorded producer command is:

```sh
{command}
```

Use a fresh output directory; the failed run remains immutable. Audit and collect
that original run without refitting:

```sh
python experiments/geometry_information/verify_round1.py \\
  --stage failed --run runs/geometry-information-r1 \\
  --keys-root runs/geometry-information-keys-v1 \\
  --data-dir data/geometry-direction \\
  --protocol experiments/geometry_information/round1_protocol.json \\
  --out runs/geometry-information-r1-failed-verification.json
python experiments/geometry_information/collect_failed.py \\
  --run runs/geometry-information-r1 \\
  --launcher runs/geometry-information-r1-launch.json \\
  --verification runs/geometry-information-r1-failed-verification.json \\
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
"""


def collect(run, out, launcher_path=None, verification_path=None, keys_dir=None, receipts=()):
    run, out = run.resolve(), out.resolve()
    report.require(run != out and run not in out.parents and out not in run.parents, "source and report must be separate")
    manifest, files = checked_artifacts(run)
    identity = report.load_json(run / "run.json")
    report.require(identity["status"] == "FAILED" and identity["freeze_commit"] == report.FREEZE_COMMIT and
                   identity["protocol_sha256"] == report.PROTOCOL_SHA256 == report.digest(run / "protocol.json"),
                   "failed-run protocol/status differs")
    report.require(identity["implementation"]["git_head"] == IMPLEMENTATION_COMMIT and
                   identity["implementation"]["worktree_status_porcelain"] == "", "failed implementation identity differs")
    report.require(identity["source_provenance_sha256"] == report.digest(run / "provenance.json"), "provenance identity differs")
    verification_path = verification_path or run.parent / (run.name + "-failed-verification.json")
    audit = report.load_json(verification_path)
    check_audit(run, audit)
    fits, selections, rejected = retained_fits(run, files)
    report.require({f["fit_id"] for f in rejected} == {f["fit_id"] for f in audit["failures"]}, "audited rejected fits differ")
    launcher_path = launcher_path or run.parent / (run.name + "-launch.json")
    launcher = report.load_json(launcher_path)
    report.require(launcher["command"] == identity["command"] and launcher["exit_code"] != 0 and
                   launcher["elapsed_seconds"] > 0, "launcher does not bind the failed command")
    copies = dict(files)
    copies.update({"producer-manifest.json": run / "manifest.json", "producer-manifest.sha256": run / "manifest.sha256",
                   "verification.json": verification_path, "launcher.json": launcher_path})
    features = {"timeframes": [report.load_json(run / f"{m}m/features.json") for m in report.TIMEFRAMES]}
    native, external = report.native_receipts(identity, features, keys_dir)
    copies.update(native)
    for path in receipts:
        path = path.resolve()
        destination = "audit-development/" + path.name
        report.require(destination not in copies, "duplicate audit-development receipt basename")
        copies[destination] = path
    log = Path(launcher.get("log", ""))
    if log.is_file():
        copies["execution.log"] = log
    scores = [{"minutes": f["minutes"], "outer_year": f["outer_year"], "family": f["family"],
               "n": f["n"], "lambda": f["lambda"], "fit_id": f["fit_id"], **f["validation_scores"]}
              for f in fits if "validation_scores" in f]
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=list(scores[0]))
    writer.writeheader(); writer.writerows(scores)
    receipt = {"schema": "filang-r1-failure-collection-v1", "status": "PASS", "experiment_status": "FAILED",
               "outcome": "inconclusive", "criterion_evaluable": False, "coverage": audit["coverage"],
               "collector_sha256": report.digest(Path(__file__).resolve()),
               "producer_manifest_sha256": report.digest(run / "manifest.json"),
               "verification_sha256": report.digest(verification_path), "native_keys_retained_externally": external}
    generated = {"README.md": readme(identity, audit, launcher, rejected).encode(),
                 "retained-fits.jsonl": b"".join((run / f"{m}m/fits.jsonl").read_bytes() for m in report.TIMEFRAMES),
                 "retained-validation-scores.csv": csv_text.getvalue().encode(),
                 "retained-selections.json": report.json_bytes(selections),
                 "collection.json": report.json_bytes(receipt)}
    package = report.write_package(out, copies, generated)
    return {"status": "PASS", "outcome": "inconclusive", "out": str(out), "collected_files": len(package["files"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--keys-dir", type=Path)
    parser.add_argument("--audit-receipt", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    print(json.dumps(collect(args.run, args.out, args.launcher, args.verification, args.keys_dir, args.audit_receipt)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as error:
        print("R1 failure collection: " + str(error), file=sys.stderr)
        raise SystemExit(2)
