"""Synthetic R1a audit contracts; no market input or optimizer execution."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from experiments.geometry_information import verify_round1 as v


HERE = Path(v.__file__).resolve().parent


def telemetry(backtracks=(), status=0):
    reasons = {0: "gradient_tolerance", 1: "maximum_iterations", 2: "nonfinite_evaluation",
               3: "nonfinite_hessian", 4: "factorization_failure", 5: "nonfinite_direction",
               6: "non_descent_direction", 7: "line_search_failure", 8: "terminal_recomputation_failure"}
    trials = [b+1 for b in backtracks] + ([50] if status == 7 else [])
    return {"method": "Newton-Cholesky-Armijo", "success": status == 0, "status": status,
            "stop_reason": reasons[status], "message": "synthetic audit fixture", "iterations": len(backtracks),
            "function_evaluations": 1+sum(trials), "gradient_evaluations": 1+sum(trials),
            "hessian_evaluations": len(backtracks)+int(status in (3, 4, 5, 6, 7)),
            "reported_objective": math.log(2), "step_sizes": [2.**(-b) for b in backtracks],
            "backtrack_counts": list(backtracks), "line_search_trial_counts": trials,
            "nonfinite_line_search_trials": 0}


class R1aAuditTests(unittest.TestCase):
    def test_exact_protocol_registry_and_unfrozen_or_unknown_rejection(self):
        original = v.protocol_contract(HERE / "round1_protocol.json")
        amended = v.protocol_contract(HERE / "round1a_protocol.json")
        self.assertEqual(original["optimizer_method"], "L-BFGS-B")
        self.assertEqual(original["freeze_commit"], "b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd")
        self.assertEqual(amended["freeze_commit"], "3df6416a2de59ac396617be49326a834c94aca92")
        with patch.dict(v.SUPPORTED_PROTOCOLS, {v.R1A_PROTOCOL_SHA256: {**amended, "freeze_commit": None}}):
            with self.assertRaisesRegex(ValueError, "no admitted freeze"):
                v.protocol_contract(HERE / "round1a_protocol.json")
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            v.admitted_protocol("0"*64)

    def test_only_declared_numerical_amendment_changes_allowed(self):
        original = v.json_file(HERE / "round1_protocol.json")
        amended = v.json_file(HERE / "round1a_protocol.json")
        v.unchanged_scientific_contract(original, amended)
        changed = copy.deepcopy(amended)
        changed["data"]["history_start"] = "2021-01-01"
        with self.assertRaisesRegex(ValueError, "scientific fields"):
            v.unchanged_scientific_contract(original, changed)
        changed = copy.deepcopy(amended)
        changed["estimation"]["lambda_grid_descending"][0] = .2
        with self.assertRaisesRegex(ValueError, "scientific estimation"):
            v.unchanged_scientific_contract(original, changed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            changed = copy.deepcopy(amended)
            changed["estimation"]["optimizer"]["maxiter"] = 101
            v.save_json(path, changed)
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                v.protocol_contract(path)

    def test_amendment_and_deviation_receipts_are_exact(self):
        amended = v.json_file(HERE / "round1a_protocol.json")
        run = {"protocol_sha256": v.R1A_PROTOCOL_SHA256, "freeze_commit": v.SUPPORTED_PROTOCOLS[v.R1A_PROTOCOL_SHA256]["freeze_commit"],
               "amendments": [copy.deepcopy(amended["amendment"])], "deviations": []}
        v.run_protocol_binding(run, amended, v.R1A_PROTOCOL_SHA256)
        for update in ({"amendments": []}, {"deviations": ["silent change"]}, {"freeze_commit": "0"*40}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                v.run_protocol_binding({**run, **update}, amended, v.R1A_PROTOCOL_SHA256)
        changed = copy.deepcopy(run)
        changed["amendments"][0]["reason"] = "different numerical justification"
        with self.assertRaisesRegex(ValueError, "amendment"):
            v.run_protocol_binding(changed, amended, v.R1A_PROTOCOL_SHA256)

    def test_newton_success_at_initialization_and_update100(self):
        for backtracks in ([], [0, 3, 49], [0]*100):
            v.optimizer_record(telemetry(backtracks), np.array([0., 1e-8]), v.R1A_PROTOCOL_SHA256)
        with self.assertRaisesRegex(ValueError, "gradient tolerance"):
            v.optimizer_record(telemetry([0]), np.array([1e-6]), v.R1A_PROTOCOL_SHA256)
        with self.assertRaisesRegex(ValueError, "update budget"):
            v.optimizer_record(telemetry([0]*101), np.array([0.]), v.R1A_PROTOCOL_SHA256)

    def test_newton_counters_steps_and_stop_reason_reject_mutations(self):
        valid = telemetry([0, 2])
        mutations = ({"function_evaluations": 6}, {"gradient_evaluations": 6}, {"hessian_evaluations": 3},
                     {"step_sizes": [1., .3]}, {"backtrack_counts": [0, 50]}, {"line_search_trial_counts": [1, 2]},
                     {"stop_reason": "objective_change"}, {"nonfinite_line_search_trials": 3}, {"iterations": True},
                     {"method": "L-BFGS-B"})
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                v.optimizer_record({**valid, **mutation}, np.array([0.]), v.R1A_PROTOCOL_SHA256)
        with self.assertRaisesRegex(ValueError, "R1 optimizer method"):
            v.optimizer_record(valid, np.array([0.]), v.R1_PROTOCOL_SHA256)

    def test_newton_failure_telemetry_is_bounded_without_becoming_success(self):
        for status in (3, 4, 5, 6, 7, 8):
            v.optimizer_record(telemetry([0, 1], status=status), np.array([1e-6]), v.R1A_PROTOCOL_SHA256)
        v.optimizer_record(telemetry([0]*100, status=1), np.array([1e-6]), v.R1A_PROTOCOL_SHA256)
        invalid = telemetry([0], status=7)
        invalid["line_search_trial_counts"][-1] = 51
        with self.assertRaisesRegex(ValueError, "trial budget"):
            v.optimizer_record(invalid, np.array([1e-6]), v.R1A_PROTOCOL_SHA256)
        with self.assertRaisesRegex(ValueError, "iteration-limit"):
            v.optimizer_record(telemetry([0]*100, status=1), np.array([1e-8]), v.R1A_PROTOCOL_SHA256)

    def test_complete_fit_identity_objective_gradient_and_newton_dispatch(self):
        # Balanced labels and all-zero columns make the zero point exactly
        # stationary. This is evaluation of fixed parameters, not fitting.
        labels = {"binary_mask": np.array([False]*10+[True]*4+[False]*26),
                  "direction": np.array([0]*10+[-1, 1, -1, 1]+[0]*26, dtype=np.int8)}
        x, y, rows = np.zeros((4, 6)), np.array([0, 1, 0, 1], dtype=np.uint8), np.arange(10, 14)
        source = {"sha256": "a"*64}
        receipt = {"minutes": 15, "keys_file_sha256": "b"*64, "features": {"B2": {"sha256": "c"*64}}}
        fold = {"year": 2023, "inner_train_start": "1970-01-01", "inner_train_end_exclusive": "1970-01-02"}
        model = {"schema": "filang-information-fit-v1", "minutes": 15, "outer_year": 2023, "family": "B", "n": 2,
                 "lambda": .1, "stage": "inner", "fit_start": 0, "fit_end_exclusive": 86400, "fit_count": 4,
                 "fit_up_count": 2, "fit_down_count": 2, "fit_rows_sha256": v.array_digest(rows, "<i8"),
                 "fit_labels_sha256": v.array_digest(y), "feature_sha256": "c"*64,
                 "feature_columns_sha256": v.json_digest(v.feature_names(2, "B")), "source_sha256": "a"*64,
                 "native_keys_sha256": "b"*64, "protocol_sha256": v.R1A_PROTOCOL_SHA256,
                 "implementation_sha256": "e"*64, "initializer": {"kind": "beta11_zero", "parent_fit_id": None,
                 "parent_coefficient_sha256": None}, "cache_hit": False}
        model["fit_id"] = v.json_digest(model)
        model.update(intercept=0., coefficients=[0.]*6, objective=math.log(2), gradient=[0.]*7,
                     max_abs_gradient=0., coefficient_sha256=v.array_digest(np.zeros(7), "<f8"),
                     initializer_sha256=v.array_digest(np.zeros(7), "<f8"), accepted=True, optimizer=telemetry())
        args = (model, source, receipt, x, labels, fold, "B", 2, .1, "inner", v.R1A_PROTOCOL_SHA256, "e"*64, None)
        self.assertLess(v.audit_fit(*args), 1e-12)
        model["optimizer"]["method"] = "L-BFGS-B"
        with self.assertRaisesRegex(ValueError, "R1a optimizer method"):
            v.audit_fit(*args)
        model["optimizer"] = telemetry()
        model["gradient"][3] = .01
        with self.assertRaisesRegex(ValueError, "gradient"):
            v.audit_fit(*args)


if __name__ == "__main__":
    unittest.main()
