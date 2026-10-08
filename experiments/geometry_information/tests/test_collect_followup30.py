"""F30-D1 report admission and scientific-label consistency checks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_followup30 as c


def cell(gain=0.001, alignment=0.01):
    return {"counts": {"target_valid": 2, "binary": 2, "up": 1, "down": 1, "flat": 0},
            "payoff": {"mean_log_return": 0.0, "break_even_up_probability": 0.62},
            "variants": {variant: {"families": {}, "paired": {
                "log_loss_gain": gain, "loss_sum": 2 * gain,
                "centered_alignment": alignment}}
                for variant in ("raw", "adapted")}}


def fixture():
    scopes = {str(y): cell(-0.001 if y == 2026 else 0.001) for y in c.YEARS}
    scopes["pooled"] = cell(0.0005)
    rows = [{"kind": "year", "period": str(y), "cell": scopes[str(y)]} for y in c.YEARS]
    rows += [{"kind": "pooled", "period": "pooled", "cell": scopes["pooled"]}]
    rows += [{"kind": "month", "period": f"{y}-{m:02}", "cell": cell()}
             for y in c.YEARS for m in range(1, 13 if y < 2026 else 11)]
    rows += [{"kind": "leave_one_year_out", "period": "without-" + str(y), "cell": cell()} for y in c.YEARS]
    boundaries = [{"year": y, "variant": v, "family": f, "bin_count": 1, "cuts": []}
                  for y in c.YEARS for v in ("raw", "adapted") for f in ("B", "G")]
    diagnostics = {"schema": "filang-followup30-diagnostics-v1", "periods": rows,
                   "magnitude_cells": [{"period": p, "bin": b, "label": "bin-" + str(b), "cell": cell()}
                                       for p in scopes for b in range(6)],
                   "decision_cells": [{"period": p, "variant": v, "state": s, "cell": cell()}
                                      for p in scopes for v in ("raw", "adapted") for s in range(4)],
                   "score_boundaries": boundaries,
                   "score_cells": [{"year": b["year"], "variant": b["variant"], "family": b["family"],
                                    "bin": 0, "cell": cell()} for b in boundaries],
                   "distribution": [{} for _ in range(32)], "corrections": [{} for _ in range(16)],
                   "sample_census": [{} for _ in range(8)], "past_means": [{} for _ in range(4)],
                   "weighted_gains": [{"period": p, "variant": v, "gain": 0.0003}
                                      for p in scopes for v in ("raw", "adapted")]}
    bootstrap = {str(b): {"block_days": b, "replicates": 2000, "seed": 20261008 + 30000 + b,
                         "exact_tail_hit_count": 10, "p_one_sided": 11 / 2001,
                         "ci95_low": 0.0001, "ci95_high": 0.0009, "gain": 0.0005, "original_count": 8}
                 for b in (1, 7, 28)}
    conditions = {"positive_pooled_gain": True, "ci_above_zero": True, "p_below_005": True,
                  "three_positive_years": True, "latest_2026_positive": False}
    analysis = {"schema": "filang-followup30-analysis-v1", "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "protocol_sha256": c.PROTOCOL_SHA256, "freeze_commit": c.FREEZE_COMMIT,
                "bootstrap": bootstrap, "outcome": "inconclusive", "outcome_if_verified": "not-supported",
                "primary": {"conditions": conditions, "annual_gains": {str(y): (-0.001 if y == 2026 else 0.001) for y in c.YEARS},
                            "positive_years": 3, "criterion_met": False,
                            "outcome": "inconclusive", "outcome_if_verified": "not-supported"},
                "continuation": {"conditions": {"primary_supported_if_verified": False,
                                                  "pooled_alignment_positive": True,
                                                  "latest_2026_alignment_positive": True,
                                                  "three_positive_alignment_years": True},
                                 "gate_if_verified": False,
                                 "annual_centered_alignment": {str(y): 0.01 for y in c.YEARS},
                                 "pooled_centered_alignment": 0.01, "status": "PENDING_INDEPENDENT_AUDIT"}}
    identity = {"status": "COMPLETE_PENDING_INDEPENDENT_AUDIT", "protocol_sha256": c.PROTOCOL_SHA256,
                "freeze_commit": c.FREEZE_COMMIT, "attempt_id": "F30-D1", "deviations": [],
                "implementation": {"git_commit": "a" * 40}}
    return diagnostics, analysis, identity


class CriterionTests(unittest.TestCase):
    def test_pooled_support_does_not_override_latest_year(self):
        diagnostics, analysis, identity = fixture()
        outcome, scopes = c.check_analysis(analysis, diagnostics, identity)
        self.assertEqual(outcome, "not-supported")
        self.assertGreater(scopes["pooled"]["variants"]["adapted"]["paired"]["log_loss_gain"], 0)
        self.assertFalse(analysis["continuation"]["gate_if_verified"])
        forged = copy.deepcopy(analysis)
        forged["primary"]["conditions"]["latest_2026_positive"] = True
        with self.assertRaisesRegex(ValueError, "primary criterion"):
            c.check_analysis(forged, diagnostics, identity)

    def test_wrong_exact_tail_p_is_rejected(self):
        diagnostics, analysis, identity = fixture()
        analysis["bootstrap"]["7"]["p_one_sided"] = 0.001
        with self.assertRaisesRegex(ValueError, "p-value/count"):
            c.check_analysis(analysis, diagnostics, identity)

    def test_duplicate_period_cannot_replace_negative_year(self):
        diagnostics, _, _ = fixture()
        diagnostics["periods"][3] = copy.deepcopy(diagnostics["periods"][2])
        with self.assertRaisesRegex(ValueError, "period"):
            c.check_tables(diagnostics)

    def test_score_bins_include_empty_declared_bins(self):
        diagnostics, _, _ = fixture()
        diagnostics["score_boundaries"][0]["bin_count"] = 2
        with self.assertRaisesRegex(ValueError, "score cell coverage"):
            c.check_tables(diagnostics)

    def test_descriptive_alignment_cannot_rescue_primary(self):
        diagnostics, analysis, identity = fixture()
        analysis["continuation"]["gate_if_verified"] = True
        with self.assertRaisesRegex(ValueError, "continuation gate"):
            c.check_analysis(analysis, diagnostics, identity)


class AdmissionTests(unittest.TestCase):
    def test_stale_and_partial_audit_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            run = Path(folder)
            (run / "manifest.json").write_text("{}\n")
            (run / "analysis.json").write_text("{}\n")
            _, _, identity = fixture()
            audit = {"schema": "filang-30m-signal-followup-verification-v1", "stage": "full", "status": "PASS",
                     "protocol_sha256": c.PROTOCOL_SHA256, "freeze_commit": c.FREEZE_COMMIT,
                     "producer_manifest_sha256": c.digest(run / "manifest.json"),
                     "analysis_sha256": c.digest(run / "analysis.json"), "coverage": dict(c.COVERAGE),
                     "checks": {name: True for name in c.CHECKS}, "all_array_members_checked": True,
                     "implementation_commit": "a" * 40, "no_model_fitting_by_verifier": True,
                     "audited_array_members": 1, "max_adapter_gradient": 1e-12, "max_numeric_error": 1e-15}
            c.check_audit(run, audit, identity)
            partial = copy.deepcopy(audit)
            partial["coverage"]["exact_tail_bits"] = 5999
            with self.assertRaisesRegex(ValueError, "coverage"):
                c.check_audit(run, partial, identity)
            (run / "analysis.json").write_text('{"changed":true}\n')
            with self.assertRaisesRegex(ValueError, "stale"):
                c.check_audit(run, audit, identity)

    def test_confined_paths_and_fresh_output(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            run = Path(folder)
            with self.assertRaisesRegex(ValueError, "confined"):
                c.bounded(run, "../outside")
            with self.assertRaisesRegex(ValueError, "confined"):
                c.bounded(run, str(run / "absolute"))
            with self.assertRaisesRegex(ValueError, "fresh"):
                c.collect(run, run)

    def test_csv_retains_zero_and_undefined_fields(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "table.csv"
            c.write_csv(path, [{"bin": 0, "cell": {"count": 0, "mean": None}},
                               {"bin": 1, "cell": {"count": 2, "mean": -0.1}}])
            import csv
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0], {"bin": "0", "cell.count": "0", "cell.mean": ""})
            self.assertEqual(rows[1]["cell.mean"], "-0.1")


if __name__ == "__main__":
    unittest.main()
