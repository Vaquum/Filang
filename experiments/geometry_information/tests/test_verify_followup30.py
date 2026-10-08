"""Independent F30-D1 oracle checks; synthetic data only."""
from __future__ import annotations

from fractions import Fraction
import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_followup30 as audit


def fixture():
    direction = np.array([-1, 1, 0, 1, -1, 0], dtype=np.int8)
    valid = np.array([True, True, True, True, True, False])
    result = {"classification_valid": valid, "binary_mask": valid & (direction != 0),
              "direction": direction, "target_log_return": np.array([-.001, .002, 0, .004, -.003, np.nan]),
              "timestamp": np.arange(6, dtype=np.int64) * 1800 + audit.epoch("2023-01-01"),
              "exit_row": np.array([2, 3, 4, 5, 5, -1], dtype=np.int64)}
    for family, z in [("B", [-.2, .1, .0, .3, -.1, .2]), ("G", [-.3, .2, .1, .15, -.2, .1])]:
        z = np.asarray(z, dtype=np.float64)
        result[f"logit_{family}"] = z
        result[f"p_{family}"] = audit.original.stable_sigmoid(z)
        result[f"adapted_logit_{family}"] = .03 + .8 * z
        result[f"adapted_p_{family}"] = audit.original.stable_sigmoid(.03 + .8 * z)
    return result


class AdapterOracleTests(unittest.TestCase):
    def test_direct_gradient_and_hessian_finite_difference(self):
        z = np.array([-4., -1.2, -.1, .0, .7, 3.])
        y = np.array([0., 1., 0., 1., 1., 0.])
        parameters = np.array([.1, -.4])
        f, gradient, hessian = audit.adapter_objective_gradient_hessian(z, y, parameters)
        numerical_g = np.empty(2)
        numerical_h = np.empty((2, 2))
        step = 1e-5
        for k in range(2):
            delta = np.eye(2)[k] * step
            plus = audit.adapter_objective_gradient_hessian(z, y, parameters + delta)
            minus = audit.adapter_objective_gradient_hessian(z, y, parameters - delta)
            numerical_g[k] = (plus[0] - minus[0]) / (2 * step)
            numerical_h[:, k] = (plus[1] - minus[1]) / (2 * step)
        np.testing.assert_allclose(gradient, numerical_g, atol=1e-10, rtol=1e-8)
        np.testing.assert_allclose(hessian, numerical_h, atol=1e-10, rtol=1e-8)
        self.assertGreater(np.linalg.eigvalsh(hessian).min(), 0)
        self.assertTrue(math.isfinite(f))

    def test_constant_logits_single_class_and_identity_penalty(self):
        z = np.zeros(7)
        y = np.ones(7)
        f, g, h = audit.adapter_objective_gradient_hessian(z, y, [0., 1.])
        self.assertAlmostEqual(f, math.log(2))
        np.testing.assert_array_equal(g, [-.5, 0])
        np.testing.assert_array_equal(h, [[.2501, 0], [0, .0001]])
        f2, g2, _ = audit.adapter_objective_gradient_hessian(z, y, [0., 0.])
        self.assertAlmostEqual(f2 - f, .00005)
        self.assertEqual(g2[1], -.0001)

    def test_no_false_float_or_discrete_equivalence(self):
        with self.assertRaisesRegex(ValueError, "boolean"):
            audit.compare(1, True)
        with self.assertRaisesRegex(ValueError, "integer"):
            audit.compare(1., 1)
        with self.assertRaisesRegex(ValueError, "dtype"):
            audit.compare(np.array([1], dtype=np.int32), np.array([1], dtype=np.int64))


class DiagnosticOracleTests(unittest.TestCase):
    def test_auc_half_ties_and_slope_behavior(self):
        y = np.array([-1, 1, -1, 1])
        score = np.array([0., 0., 1., 2.])
        value = audit.auc_oracle(y, score)
        brute = np.mean([float(a > b) + .5 * float(a == b) for a in score[y == 1] for b in score[y == -1]])
        self.assertEqual(value, brute)
        self.assertEqual(audit.auc_oracle(y, -score), 1 - value)
        self.assertEqual(audit.auc_oracle(y, np.zeros(4)), .5)
        self.assertIsNone(audit.auc_oracle(np.array([1, 1]), np.array([0., 1.])))
        self.assertIsNone(audit.auc_oracle(np.array([], dtype=int), np.array([])))

    def test_bins_include_equalities_and_preserve_empty_cells(self):
        direction = np.array([0, 1, -1, 1, -1, 1])
        # The protocol compares executed binary64 |return|*10000. Decimal
        # .0012 and .0024 multiply to values immediately below 12 and 24;
        # do not insert an epsilon or silently reinterpret those literals.
        returns = np.array([0., 0., .0001, -.0005, np.nextafter(.0012, np.inf), -np.nextafter(.0024, np.inf)])
        np.testing.assert_array_equal(audit.magnitude_membership(direction, returns), [0, 1, 2, 3, 4, 5])
        np.testing.assert_array_equal(audit.magnitude_membership(np.array([1, 1]), np.array([.0012, .0024])), [3, 4])
        np.testing.assert_array_equal(audit.decision_membership([.4, .4, .5, .5], [.4, .5, .4, .5]), [0, 1, 2, 3])
        cuts = np.unique(audit.linear_quantiles([.2, .2, .2, .2], [.2, .4, .6, .8]))
        np.testing.assert_array_equal(cuts, [.2])
        np.testing.assert_array_equal(np.searchsorted(cuts, [.1, .2, .3], side="right"), [0, 1, 1])

    def test_linear_quantiles_match_declared_interpolation(self):
        for values in ([1.], [4., 2., 1., 7., 9.], [0., 0., .5, .5, 1.]):
            q = [.05, .2, .25, .4, .5, .6, .75, .8, .95]
            np.testing.assert_allclose(audit.linear_quantiles(values, q), np.quantile(values, q, method="linear"), atol=1e-15)

    def test_flat_preservation_payoff_and_partition_reconciliation(self):
        arrays = fixture()
        mask = arrays["classification_valid"]
        cell = audit.cell_oracle(arrays, mask, .0002)
        self.assertEqual(cell["counts"], {"target_valid": 5, "binary": 4, "up": 2, "down": 2, "flat": 1})
        payoff = cell["payoff"]
        self.assertAlmostEqual(payoff["mean_log_return"], .0004)
        self.assertAlmostEqual(payoff["contribution_reconstruction_error"], 0)
        self.assertAlmostEqual(payoff["conditional_reconstruction_error"], 0)
        self.assertEqual(payoff["flat_fraction"], .2)
        empty = audit.cell_oracle(arrays, np.zeros(len(mask), dtype=bool), .0002)
        self.assertEqual(empty["counts"]["target_valid"], 0)
        self.assertIsNone(empty["payoff"]["mean_log_return"])
        self.assertEqual(empty["variants"]["raw"]["paired"]["loss_sum"], 0)
        membership = audit.decision_membership(arrays["p_B"], arrays["p_G"])
        parts = [audit.cell_oracle(arrays, mask & (membership == k), .0002) for k in range(4)]
        self.assertEqual(sum(p["counts"]["target_valid"] for p in parts), 5)
        for variant in audit.VARIANTS:
            self.assertAlmostEqual(sum(p["variants"][variant]["paired"]["loss_sum"] for p in parts),
                                   cell["variants"][variant]["paired"]["loss_sum"])

    def test_one_class_and_flat_only_defined_statistics(self):
        arrays = fixture()
        up = arrays["direction"] == 1
        cell = audit.cell_oracle(arrays, up, .0001)
        self.assertIsNone(cell["payoff"]["negative_mean_magnitude"])
        self.assertIsNone(cell["payoff"]["break_even_up_probability"])
        self.assertIsNone(cell["variants"]["raw"]["families"]["G"]["balanced_accuracy"])
        flat = audit.cell_oracle(arrays, arrays["direction"] == 0, .0001)
        self.assertEqual(flat["counts"]["flat"], 1)
        self.assertEqual(flat["payoff"]["mean_log_return"], 0)
        self.assertIsNone(flat["variants"]["raw"]["families"]["G"]["log_loss"])


class RatioBootstrapOracleTests(unittest.TestCase):
    def test_exact_variable_count_tail_matches_fraction_reference(self):
        parts = [np.array([.125, -.03125, .0625]), np.array([.0, -.0625])]
        counts = [np.array([1, 7, 2], dtype=np.int64), np.array([4, 1], dtype=np.int64)]
        block, replicas, seed = 1, 37, 91
        saved = audit.exact_ratio_bootstrap(parts, counts, block, replicas, seed)
        original_count = sum(int(c.sum()) for c in counts)
        original_sum = sum((Fraction(float(x)) for p in parts for x in p), Fraction(0))
        gain = original_sum / original_count
        rng = np.random.default_rng(seed + 30000 + block)
        expected, nstar = [], []
        for _ in range(replicas):
            total, count = Fraction(0), 0
            for p, c in zip(parts, counts):
                sample = rng.integers(0, len(p), size=len(p), dtype=np.int64)
                total += sum((Fraction(float(p[i])) for i in sample), Fraction(0))
                count += int(c[sample].sum())
            expected.append((total - gain * count) / count >= gain)
            nstar.append(count)
        np.testing.assert_array_equal(saved["exact_tail_hits"], expected)
        np.testing.assert_array_equal(saved["resampled_count"], nstar)
        self.assertTrue(np.any(saved["resampled_count"] != original_count))

    def test_exact_zero_and_negative_sums(self):
        for p in [np.array([0., 0.]), np.array([-.125, -.25])]:
            saved = audit.exact_ratio_bootstrap([p], [np.array([1, 3], dtype=np.int64)], 2, 10)
            self.assertTrue(saved["exact_tail_hits"].all())
            self.assertTrue(np.isfinite(saved["ordinary"]).all())

    def test_empty_original_or_resampled_denominator_fails(self):
        with self.assertRaisesRegex(ValueError, "original denominator"):
            audit.exact_ratio_bootstrap([np.zeros(2)], [np.zeros(2, dtype=np.int64)], 1, 5)
        with self.assertRaisesRegex(ValueError, "resampled denominator"):
            audit.exact_ratio_bootstrap([np.array([0., .1])], [np.array([0, 1], dtype=np.int64)], 1, 200)

    def test_boundaries_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(audit.bounded(temp, "a/b").name, "b")
            with self.assertRaisesRegex(ValueError, "escape"):
                audit.bounded(temp, "../outside")

    def test_audit_output_cannot_mutate_source_or_scoped_input_trees(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run, data, predecessor, keys = (root / name for name in ("run", "data", "predecessor", "keys"))
            for folder in (run, data, predecessor, keys):
                folder.mkdir()
            audit.check_audit_output(run, data, run / "verification.json", [predecessor, keys])
            audit.check_audit_output(run, data, root / "external-audit.json", [predecessor, keys])
            for output in (run / "predecessor/new-audit.json", run / "native/30m/new.json"):
                with self.assertRaisesRegex(ValueError, "canonical"):
                    audit.check_audit_output(run, data, output, [predecessor, keys])
            for output in (data / "new.json", predecessor / "new.json", keys / "new.json"):
                with self.assertRaisesRegex(ValueError, "immutable source"):
                    audit.check_audit_output(run, data, output, [predecessor, keys])


class CompleteDiagnosticParityTests(unittest.TestCase):
    @staticmethod
    def phases():
        # The producer is imported only by this cross-implementation synthetic
        # test. The verifier module itself never imports producer computations.
        import followup30 as producer
        days = [audit.epoch(f"{year}-01-01") for year in range(2022, 2027)]
        times = np.concatenate([day + np.arange(28, dtype=np.int64) * 1800 for day in days])
        prices = 100. + np.sin(np.arange(len(times)) * .7)
        prices[::7] = prices[np.maximum(np.arange(0, len(prices), 7) - 1, 0)]
        source = {"timestamp": times, "prices": np.column_stack((prices, prices + 1, prices - 1, prices)),
                  "interval_seconds": 1800}
        causal = np.arange(9, len(times), dtype=np.int64)
        causal = causal[times[causal] - times[causal - 9] == 9 * 1800]
        phases, folds = {}, []
        for year in audit.YEARS:
            fold = {"year": year, "validation_start": f"{year - 1}-01-01", "validation_end_exclusive": f"{year}-01-01",
                    "outer_start": f"{year}-01-01", "outer_end_exclusive": f"{year + 1}-01-01" if year < 2026 else "2026-10-08"}
            folds.append(fold)
            base = {}
            for phase in audit.PHASES:
                arrays = audit.original.phase_oracle(source, causal, audit.epoch(fold[f"{phase}_start"]), audit.epoch(fold[f"{phase}_end_exclusive"]))
                finite = arrays["phase_mask"] & arrays["causal_feature_valid"]
                for family, coefficient in (("B", .14), ("G", -.21)):
                    z = np.full(len(times), np.nan)
                    z[finite] = coefficient * (np.arange(len(times))[finite] % 9 - 4)
                    arrays[f"logit_{family}"] = z
                    arrays[f"p_{family}"] = audit.original.stable_sigmoid(z)
                for baseline in ("unconditional", "lag1"):
                    arrays[f"p_{baseline}"] = np.where(finite, .5, np.nan)
                base[phase] = arrays
            fitting = base["validation"]["binary_mask"]
            adapters = {family: producer.fit_adapter(base["validation"][f"logit_{family}"][fitting],
                         base["validation"]["direction"][fitting] == 1) for family in audit.FAMILIES}
            for phase in audit.PHASES:
                phases[year, phase] = producer.transformed_arrays(base[phase], adapters, prices)
        return phases, folds

    def test_every_diagnostic_cell_daily_row_and_membership(self):
        import followup30 as producer
        phases, folds = self.phases()
        actual = producer.build_diagnostics(phases, folds)
        expected = audit.diagnostics_oracle(phases, folds)
        self.assertLessEqual(audit.compare(actual[0], expected[0], "all diagnostic tables"), 1e-10)
        self.assertLessEqual(audit.compare(actual[1], expected[1], "all daily arrays"), 1e-10)
        self.assertLessEqual(audit.compare(actual[2], expected[2], "every discrete membership"), 1e-10)
        self.assertEqual(len(actual[0]["periods"]), 55)
        self.assertEqual(len(actual[0]["magnitude_cells"]), 30)
        self.assertEqual(len(actual[0]["decision_cells"]), 40)
        self.assertEqual(len(actual[1]["day"]), 1376)
        self.assertEqual(sum(p["cell"]["counts"]["target_valid"] for p in actual[0]["periods"] if p["kind"] == "month"),
                         next(p["cell"]["counts"]["target_valid"] for p in actual[0]["periods"] if p["kind"] == "pooled"))

    def test_validation_cuts_and_adapter_inputs_ignore_outer_labels(self):
        phases, folds = self.phases()
        for year in audit.YEARS:
            old = {family: audit.boundary_oracle(phases[year, "validation"], year, "adapted", family) for family in audit.FAMILIES}
            arrays = phases[year, "outer"]
            arrays["direction"][arrays["binary_mask"]] *= -1
            arrays["target_log_return"][arrays["classification_valid"]] *= -1
            for family in audit.FAMILIES:
                audit.compare(old[family], audit.boundary_oracle(phases[year, "validation"], year, "adapted", family))

    def test_all_six_thousand_ratio_tail_bits_and_exact_receipts(self):
        import followup30 as producer
        year_parts, days, counts, values = [], [], [], []
        for index, year in enumerate(audit.YEARS):
            length = index + 3
            year_parts.extend([year] * length)
            days.extend((audit.epoch(f"{year}-01-01") // 86400 + np.arange(length)).tolist())
            counts.extend((np.arange(length) % 3 + 1).tolist())
            values.extend([float(((-1) ** (i + index)) * (i + 1) / 128) for i in range(length)])
        daily = {"outer_year": np.array(year_parts, dtype=np.int64), "day": np.array(days, dtype=np.int64),
                 "binary_count": np.array(counts, dtype=np.int64), "adapted_paired_loss_sum": np.array(values, dtype=np.float64)}
        bits = 0
        for block in (1, 7, 28):
            summary, arrays, encoding = producer.ratio_bootstrap(daily, block)
            expected, error = audit.bootstrap_summary_oracle(daily, block, arrays)
            audit.compare(summary, expected, "complete exact bootstrap summary")
            self.assertEqual(encoding, audit.exact_encoding_oracle(daily))
            self.assertEqual(summary["p_one_sided"], expected["p_one_sided"])
            self.assertLessEqual(error, 1e-10)
            bits += len(arrays["exact_tail_hits"])
        self.assertEqual(bits, 6000)

    def test_selected_inner_vintage_and_adapter_optimum_corruptions_rejected(self):
        import followup30 as producer
        phases, folds = self.phases()
        arrays, fold = phases[2023, "validation"], folds[0]
        rows = np.flatnonzero(arrays["binary_mask"])
        labels = (arrays["direction"][rows] == 1).astype(np.uint8)
        z = arrays["logit_B"][rows]
        binding = {"prediction_path": "30m/2023/validation.npz", "prediction_sha256": "a" * 64,
                   "models": {"B": {"fit_id": "selected-inner", "path": "30m/2023/B/candidates/n02-l0.1.json",
                                     "coefficient_sha256": "b" * 64, "file_sha256": "c" * 64}}}
        metadata = {"schema": "filang-followup30-adapter-v1", "year": 2023, "family": "B", "lambda": .0001,
            "initial_parameters": [0., 1.], "protocol_sha256": audit.PROTOCOL_SHA256, "implementation_sha256": "d" * 64,
            "source_prediction_path": binding["prediction_path"], "source_prediction_sha256": binding["prediction_sha256"],
            "source_model": binding["models"]["B"], "training_start": audit.epoch(fold["validation_start"]),
            "training_end_exclusive": audit.epoch(fold["validation_end_exclusive"]), "sample_count": len(rows),
            "sample_up_count": int(labels.sum()), "sample_down_count": int(len(rows) - labels.sum()),
            "sample_rows_sha256": audit.array_digest(rows), "sample_logits_sha256": audit.array_digest(z),
            "sample_labels_sha256": audit.array_digest(labels)}
        metadata["fit_id"] = audit.json_digest(metadata)
        record = {**metadata, **producer.fit_adapter(z, labels)}
        error, gradient = audit.adapter_oracle(record, arrays, fold, "B", binding, "d" * 64)
        self.assertLessEqual(error, 1e-10)
        self.assertLessEqual(gradient, 1e-10)
        wrong_vintage = copy.deepcopy(record)
        wrong_vintage["source_model"]["path"] = "30m/2023/B/refit.json"
        with self.assertRaisesRegex(ValueError, "source_model"):
            audit.adapter_oracle(wrong_vintage, arrays, fold, "B", binding, "d" * 64)
        wrong_optimum = copy.deepcopy(record)
        wrong_optimum["parameters"][0] += .1
        wrong_optimum["a"] = wrong_optimum["parameters"][0]
        wrong_optimum["parameters_sha256"] = audit.array_digest(np.array(wrong_optimum["parameters"]))
        with self.assertRaisesRegex(ValueError, "optimum acceptance"):
            audit.adapter_oracle(wrong_optimum, arrays, fold, "B", binding, "d" * 64)


if __name__ == "__main__":
    unittest.main()
