"""Failed-run packaging tests use synthetic artifacts, never market fits."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from experiments.geometry_information import collect_failed as failed
from experiments.geometry_information import collect_round1 as report
from experiments.geometry_information.tests.test_collect_round1 import fixture as full_fixture, save


def fixture(root):
    run = root / "run"
    full_fixture(run)
    identity = report.load_json(run / "run.json")
    features = report.load_json(run / "features.json")["timeframes"]
    protocol = (run / "protocol.json").read_bytes()
    provenance = (run / "provenance.json").read_bytes()
    shutil.rmtree(run)
    run.mkdir()
    (run / "protocol.json").write_bytes(protocol)
    (run / "provenance.json").write_bytes(provenance)
    identity.update(status="FAILED", implementation={"git_head": failed.IMPLEMENTATION_COMMIT,
                    "worktree_status_porcelain": ""}, settings={"workers": 5, "blas_threads": 2})
    identity["input_paths"]["data_dir"] = "/synthetic data/pinned-csv"
    save(run / "run.json", identity)
    rejected = []
    for feature in features:
        minutes = feature["minutes"]
        save(run / f"{minutes}m/features.json", feature)
        save(run / f"failure-{minutes}m.json", {"minutes": minutes, "traceback": "synthetic failure"})
        fits = []
        for i in range(29 if minutes == 240 else 33):
            refit = i == 16
            reject = i == (28 if minutes == 240 else 32)
            family = "B" if i <= 16 else "G"
            path = f"{minutes}m/2023/{family}/refit.json" if refit else f"{minutes}m/2023/{family}/candidates/fit-{i}.json"
            fit = {"minutes": minutes, "outer_year": 2023, "stage": "refit" if refit else "inner",
                   "family": family, "n": 5 if minutes == 240 else 10, "lambda": .0001,
                   "fit_id": f"synthetic-{minutes}-{i}", "path": path, "accepted": not reject,
                   "objective": .69, "max_abs_gradient": 2e-6,
                   "optimizer": {"success": not reject, "iterations": 1000 if reject else 2,
                                 "message": "STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT" if reject else "CONVERGED"}}
            if not refit and not reject:
                fit["validation_scores"] = {"binary_log_loss": .69, "binary_count": 10}
            if reject:
                rejected.append(fit)
                attachment = run / path.replace(".json", "-failed-parameters.npz")
                attachment.parent.mkdir(parents=True, exist_ok=True)
                attachment.write_bytes(b"SYNTHETIC REJECTED PARAMETERS")
            save(run / path, fit)
            fits.append(fit)
        (run / f"{minutes}m/fits.jsonl").write_text("".join(json.dumps(f, sort_keys=True) + "\n" for f in fits))
        save(run / f"{minutes}m/2023/B/selected.json", {"minutes": minutes, "family": "B"})
    manifest = {"files": {p.relative_to(run).as_posix(): report.file_record(p) for p in run.rglob("*") if p.is_file()}}
    save(run / "manifest.json", manifest)
    (run / "manifest.sha256").write_text(report.digest(run / "manifest.json") + "\n")
    audit = {"schema": "filang-geometry-information-verification-v1", "stage": "failed", "status": "PASS",
             "experiment_status": "FAILED", "outcome": "inconclusive", "criterion_evaluable": False,
             "scientific_models_checked": False, "retained_model_parameters_checked": True,
             "protocol_sha256": report.PROTOCOL_SHA256, "producer_manifest_sha256": report.digest(run / "manifest.json"),
             "analysis_sha256": None, "audited_timeframes": list(report.TIMEFRAMES), "audited_outer_years": [2023],
             "coverage": dict(failed.COVERAGE), "checks": dict.fromkeys(failed.CHECKS, True), "failures": rejected}
    audit_path = root / "run-failed-verification.json"
    save(audit_path, audit)
    save(root / "run-launch.json", {"command": identity["command"], "exit_code": 1, "elapsed_seconds": 77.7})
    return run, audit


class FailureCollectorTests(unittest.TestCase):
    def test_full_failure_package_preserves_all_models_and_never_supports_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = fixture(root)
            result = failed.collect(run, root / "report")
            self.assertEqual(result["outcome"], "inconclusive")
            self.assertEqual(len((root / "report/retained-fits.jsonl").read_text().splitlines()), 161)
            self.assertEqual(len(list((root / "report").rglob("*-failed-parameters.npz"))), 5)
            self.assertEqual((run / "15m/fits.jsonl").read_bytes(), (root / "report/15m/fits.jsonl").read_bytes())
            readme = (root / "report/README.md").read_text()
            self.assertIn("--data-dir '/synthetic data/pinned-csv'", readme)
            self.assertIn("completed PR #24 tree", readme)
            self.assertIn("predates that final", readme)
            failed.collect(run, root / "report")

    def test_forensic_gate_rejects_unsupported_scientific_or_incomplete_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            run, audit = fixture(Path(directory))
            changes = [("stage", "full"), ("outcome", "supported"), ("criterion_evaluable", True),
                       ("analysis_sha256", "0" * 64), ("producer_manifest_sha256", "0" * 64)]
            for key, value in changes:
                bad = copy.deepcopy(audit); bad[key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    failed.check_audit(run, bad)
            for key in ("all_failed_parameter_arrays", "no_post_failure_predictions_or_economics"):
                bad = copy.deepcopy(audit); bad["checks"][key] = False
                with self.subTest(key=key), self.assertRaises(ValueError):
                    failed.check_audit(run, bad)

    def test_tampered_parameter_attachment_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = fixture(root)
            next(run.rglob("*-failed-parameters.npz")).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "artifact identity differs"):
                failed.collect(run, root / "report")
            self.assertFalse((root / "report").exists())


if __name__ == "__main__":
    unittest.main()
