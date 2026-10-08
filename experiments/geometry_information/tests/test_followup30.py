"""Synthetic F30-D1 contracts; these tests never open market artifacts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import common
import followup30 as d
import run_followup30 as producer


def fixture():
    protocol = json.loads((HERE / "followup30_protocol.json").read_text())
    folds = protocol["target_and_phases"]["outer_folds"]
    times = np.concatenate([d.epoch(f"{year}-01-01")+np.arange(40, dtype=np.int64)*1800
                            for year in range(2021, 2027)])
    rows = np.arange(len(times))
    opens = 10000*np.exp(0.002*np.sin(rows*0.8)+rows*0.00001)
    opens[rows % 11 == 2] = opens[np.maximum(rows[rows % 11 == 2]-1, 0)]
    source = {"timestamps": times, "ohlc": np.column_stack([opens, opens*1.01, opens*.99, opens]),
              "interval_seconds": 1800, "rows": len(times), "sha256": "synthetic"}
    causal = common.causal_mask(times, 1800, d.epoch("2020-01-01"), d.epoch("2026-10-08"))
    phases, fitted = {}, {}
    for fold in folds:
        year = fold["year"]
        originals = {}
        for phase in ("validation", "outer"):
            arrays = common.phase_labels(source, causal, d.epoch(fold[f"{phase}_start"]), d.epoch(fold[f"{phase}_end_exclusive"]))
            available = arrays["phase_mask"] & arrays["causal_feature_valid"]
            for family in ("B", "G"):
                z = .2*np.sin(rows*.8) + (0.1*np.cos(rows*.5) if family == "G" else 0)
                arrays[f"logit_{family}"] = np.where(available, z, np.nan)
                arrays[f"p_{family}"] = np.where(available, d.sigmoid(z), np.nan)
            arrays["p_unconditional"] = np.where(available, .51, np.nan)
            arrays["p_lag1"] = np.where(available, .49, np.nan)
            originals[phase] = arrays
        validation = originals["validation"]
        selected = validation["binary_mask"]
        models = {family: d.fit_adapter(validation[f"logit_{family}"][selected], (validation["direction"][selected] == 1).astype(np.uint8))
                  for family in d.FAMILIES}
        if not all(model["accepted"] for model in models.values()):
            raise AssertionError("synthetic calibration failed")
        fitted[year] = models
        for phase, arrays in originals.items():
            phases[year, phase] = d.transformed_arrays(arrays, models, opens)
    return protocol, folds, source, causal, phases, fitted


class AdapterTests(unittest.TestCase):
    def test_analytic_derivatives(self):
        theta = np.array([.2, -.7])
        z, y = np.array([-2., -.1, .4, 1.5]), np.array([0., 1., 1., 0.])
        objective, gradient, hessian = d.adapter_objective(theta, z, y)
        epsilon = 1e-5
        numeric_gradient = []
        numeric_hessian = np.empty((2, 2))
        for j in range(2):
            step = np.zeros(2); step[j] = epsilon
            plus = d.adapter_objective(theta+step, z, y)
            minus = d.adapter_objective(theta-step, z, y)
            numeric_gradient.append((plus[0]-minus[0])/(2*epsilon))
            numeric_hessian[:, j] = (plus[1]-minus[1])/(2*epsilon)
        np.testing.assert_allclose(gradient, numeric_gradient, atol=1e-9, rtol=1e-8)
        np.testing.assert_allclose(hessian, numeric_hessian, atol=1e-9, rtol=1e-8)
        self.assertGreater(np.linalg.eigvalsh(hessian).min(), 0)

    def test_constant_logits_single_class_and_negative_slope(self):
        constant = d.fit_adapter(np.zeros(50), np.r_[np.zeros(25), np.ones(25)])
        self.assertTrue(constant["accepted"])
        self.assertEqual(constant["parameters"], [0., 1.])
        self.assertEqual(constant["optimizer"]["iterations"], 0)
        self.assertEqual(constant["optimizer"]["hessian_evaluations"], 0)
        single = d.fit_adapter(np.zeros(50), np.ones(50))
        self.assertTrue(single["accepted"])
        self.assertGreater(single["a"], 0)
        self.assertEqual(single["b"], 1)
        z = np.linspace(-2, 2, 101)
        reversed_ = d.fit_adapter(z, (z < 0).astype(float))
        self.assertTrue(reversed_["accepted"])
        self.assertTrue(reversed_["slope_negative"])

    def test_gradient_is_required_and_failure_retained(self):
        failed = d.fit_adapter(np.zeros(10), np.ones(10), max_updates=1)
        self.assertFalse(failed["accepted"])
        self.assertEqual(failed["optimizer"]["stop_reason"], "maximum_updates")
        self.assertEqual(failed["optimizer"]["iterations"], 1)
        self.assertGreater(failed["max_abs_gradient"], 1e-10)
        self.assertTrue(all(np.isfinite(failed["parameters"])))
        self.assertEqual(len(failed["optimizer"]["accepted_path"]), 1)
        self.assertEqual(failed["optimizer"]["hessian_evaluations"], 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"failed.json"
            d.write_json(path, failed)
            self.assertEqual(d.read_json(path), failed)

    def test_no_small_step_success_shortcut(self):
        with patch.object(d, "adapter_objective_gradient", return_value=(1.0, np.array([1e-5, 0.]))), \
             patch.object(d, "adapter_hessian", return_value=np.eye(2)):
            result = d.fit_adapter(np.zeros(10), np.ones(10), max_updates=1)
        self.assertFalse(result["accepted"])
        self.assertGreater(result["max_abs_gradient"], 1e-10)

    def test_loss_is_stable_and_nonfinite_input_rejected(self):
        objective, gradient, hessian = d.adapter_objective([0, 1], np.array([-1000., 1000.]), np.array([0., 1.]))
        self.assertTrue(np.isfinite(objective))
        self.assertTrue(np.isfinite(gradient).all())
        self.assertTrue(np.isfinite(hessian).all())
        with self.assertRaisesRegex(ValueError, "finite/binary"):
            d.fit_adapter([np.nan], [0])


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol, cls.folds, cls.source, cls.causal, cls.phases, cls.fitted = fixture()

    def test_all_declared_partitions_and_calendar(self):
        result, daily, memberships = d.build_diagnostics(self.phases, self.folds)
        expected = {"periods": 55, "magnitude_cells": 30, "decision_cells": 40, "score_boundaries": 16,
                    "distribution": 32, "corrections": 16, "sample_census": 8, "weighted_gains": 10, "past_means": 4}
        for key, count in expected.items():
            self.assertEqual(len(result[key]), count)
        self.assertEqual(len(daily["day"]), 1376)
        self.assertTrue(np.any(daily["binary_count"] == 0))
        for row in result["periods"]:
            if row["kind"] in ("month", "leave_one_year_out"):
                self.assertEqual(set(row["cell"]), {"counts", "variants"})
                self.assertEqual(set(row["cell"]["variants"]["raw"]["paired"]),
                                 {"loss_sum", "log_loss_gain", "brier_sum", "brier_gain"})
        annual = {row["period"]: row["cell"] for row in result["periods"] if row["kind"] in ("year", "pooled")}
        for period, total in annual.items():
            magnitude = [row["cell"] for row in result["magnitude_cells"] if row["period"] == period]
            self.assertEqual(sum(row["counts"]["target_valid"] for row in magnitude), total["counts"]["target_valid"])
            for variant in d.VARIANTS:
                decision = [row["cell"] for row in result["decision_cells"] if row["period"] == period and row["variant"] == variant]
                for cells in (magnitude, decision):
                    self.assertAlmostEqual(sum(row["variants"][variant]["paired"]["loss_sum"] for row in cells),
                                           total["variants"][variant]["paired"]["loss_sum"], places=12)
        for year, values in memberships.items():
            self.assertEqual(len(values), 7)
            invalid = ~self.phases[year, "outer"]["classification_valid"]
            self.assertTrue(all(np.all(array[invalid] == -1) for array in values.values()))

    def test_future_label_invalid_forecasts_stay_available(self):
        for arrays in self.phases.values():
            unavailable_target = arrays["phase_mask"] & arrays["causal_feature_valid"] & ~arrays["classification_valid"]
            self.assertTrue(unavailable_target.any())
            self.assertTrue(np.isnan(arrays["target_log_return"][unavailable_target]).all())
            for family in d.FAMILIES:
                self.assertTrue(np.isfinite(arrays[f"adapted_p_{family}"][unavailable_target]).all())

    def test_outer_outcomes_do_not_fit_adapters_or_boundaries(self):
        changed = {key: {name: a.copy() for name, a in arrays.items()} for key, arrays in self.phases.items()}
        for (year, phase), arrays in changed.items():
            if phase == "outer":
                arrays["direction"] *= -1
                arrays["target_log_return"] *= -5
        for year in (2023, 2024, 2025, 2026):
            original = self.phases[year, "validation"]
            other = changed[year, "validation"]
            for family in d.FAMILIES:
                mask = original["binary_mask"]
                refit = d.fit_adapter(other[f"logit_{family}"][mask], (other["direction"][mask] == 1).astype(float))
                self.assertEqual(refit, self.fitted[year][family])
                for variant in d.VARIANTS:
                    self.assertEqual(d.score_boundaries(original, variant, family), d.score_boundaries(other, variant, family))

    def test_magnitude_equalities_and_duplicate_score_cuts(self):
        magnitude = np.array([0., 0., 0.0001, 0.0005, np.nextafter(.0012, np.inf), np.nextafter(.0024, np.inf)])
        self.assertEqual(d.magnitude_membership(np.array([0, 1, 1, 1, 1, 1]), magnitude).tolist(), [0, 1, 2, 3, 4, 5])
        arrays = {"phase_mask": np.ones(10, bool), "causal_feature_valid": np.ones(10, bool), "p_B": np.full(10, .5)}
        cuts = d.score_boundaries(arrays, "raw", "B")
        self.assertEqual(cuts["raw_cuts"], [.5]*4)
        self.assertEqual(cuts["cuts"], [.5])
        self.assertEqual(np.searchsorted(cuts["cuts"], [.4, .5, .6], side="right").tolist(), [0, 1, 1])
        self.assertEqual(d.decision_membership([.49, .49, .5, .5], [.49, .5, .49, .5]).tolist(), [0, 1, 2, 3])

    def test_auc_ties_and_affine_ranking(self):
        y = np.array([0, 1, 1, 0], bool)
        self.assertEqual(d.auc(y, [.2, .5, .5, .8]), .5)
        self.assertEqual(d.auc(y, [.5]*4), .5)
        self.assertIsNone(d.auc(np.ones(4, bool), [.1, .2, .3, .4]))
        z = np.array([-.7, -.1, .4, 1.2])
        expected = d.auc(y, d.sigmoid(z))
        self.assertEqual(d.auc(y, d.sigmoid(2+3*z)), expected)
        self.assertEqual(d.auc(y, d.sigmoid(-z)), 1-expected)

    def test_flats_payoff_identity_and_missing_signs(self):
        direction = np.array([1, 1, -1, 0], dtype=np.int8)
        data = {"direction": direction, "binary_mask": direction != 0,
                "target_log_return": np.array([.01, .03, -.02, 0.]), "past_mean": np.full(4, .001)}
        for family, z in (("B", np.array([.2, .3, -.4, .1])), ("G", np.array([.3, .4, -.5, .2]))):
            for variant in d.VARIANTS:
                pname, zname = d.prediction_names(variant, family)
                data[pname], data[zname] = d.sigmoid(z), z
        cell = d.cell(data)
        self.assertEqual(cell["counts"], {"target_valid": 4, "binary": 3, "up": 2, "down": 1, "flat": 1})
        self.assertAlmostEqual(cell["payoff"]["mean_log_return"], .005)
        self.assertLess(cell["payoff"]["conditional_reconstruction_error"], 1e-15)
        self.assertIsNotNone(cell["payoff"]["break_even_up_probability"])
        empty = d.cell(data, np.zeros(4, bool))
        self.assertEqual(empty["counts"]["target_valid"], 0)
        self.assertIsNone(empty["payoff"]["mean_log_return"])
        self.assertEqual(empty["variants"]["raw"]["paired"]["loss_sum"], 0)
        positive = d.cell(data, direction == 1)
        self.assertIsNone(positive["payoff"]["negative_mean_magnitude"])
        self.assertIsNone(positive["payoff"]["break_even_up_probability"])
        data["target_log_return"][:] = 0
        rounded_zero = d.cell(data)
        self.assertIsNone(rounded_zero["payoff"]["break_even_up_probability"])

    def test_primary_latest_year_and_alignment_veto(self):
        diagnostics, _, _ = d.build_diagnostics(self.phases, self.folds)
        for row in diagnostics["periods"]:
            if row["kind"] in ("year", "pooled"):
                row["cell"]["variants"]["adapted"]["paired"].update(log_loss_gain=.01, centered_alignment=.001)
        bootstrap = {"7": {"gain": .01, "ci95_low": .001, "p_one_sided": .01}}
        result = d.decisions(diagnostics, bootstrap)
        self.assertTrue(result["primary"]["criterion_met"])
        self.assertTrue(result["continuation"]["gate_if_verified"])
        latest = next(row for row in diagnostics["periods"] if row["period"] == "2026" and row["kind"] == "year")
        latest["cell"]["variants"]["adapted"]["paired"]["centered_alignment"] = -0.001
        result = d.decisions(diagnostics, bootstrap)
        self.assertTrue(result["primary"]["criterion_met"])
        self.assertFalse(result["continuation"]["gate_if_verified"])
        latest["cell"]["variants"]["adapted"]["paired"]["log_loss_gain"] = -.01
        result = d.decisions(diagnostics, bootstrap)
        self.assertFalse(result["primary"]["criterion_met"])
        self.assertEqual(result["primary"]["outcome"], "inconclusive")
        self.assertEqual(result["primary"]["outcome_if_verified"], "not-supported")


class IntegrityAndBootstrapTests(unittest.TestCase):
    def test_relocated_sources_use_archived_provenance_without_rewriting_fresh_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/"new-machine-data"
            (data/"raw").mkdir(parents=True)
            (data/"30m").mkdir()
            raw = data/"raw/synthetic.parquet"
            raw.write_bytes(b"opaque synthetic pinned source bytes")
            csv_path = data/"30m/ohlcv.csv"
            csv_path.write_text("timestamp,open,high,low,close,volume\n0,10,12,9,11,1\n1800,11,13,10,12,2\n3600,12,14,11,13,3\n")
            specification = {"minutes": 30, "repo": "synthetic/source", "revision": "synthetic-revision",
                "filename": raw.name, "sha256": d.digest(raw), "expected_source_rows": 3,
                "expected_source_bytes": raw.stat().st_size, "prepared_csv_sha256": d.digest(csv_path), "missing_grid_bars": 0}
            record = {"minutes": 30, "source": specification, "source_sha256": d.digest(raw),
                "csv_sha256": d.digest(csv_path), "csv_bytes": csv_path.stat().st_size,
                "missing_grid_bars": 0, "csv_path": "/original/machine/data/30m/ohlcv.csv"}
            archived = root/"archived-provenance.json"
            d.write_json(archived, {"sources": [record]})
            fresh = data/"provenance.json"
            d.write_json(fresh, {"sources": [{**record, "csv_path": str(csv_path)}]})
            archived_sha, fresh_before = d.digest(archived), fresh.read_bytes()
            self.assertNotEqual(archived_sha, d.digest(fresh))
            result = producer.load_archived_source(archived, archived_sha, data, specification)
            self.assertEqual(result["rows"], 3)
            self.assertEqual(result["path"], str(csv_path.resolve()))
            self.assertEqual(fresh.read_bytes(), fresh_before)
            self.assertEqual(d.digest(archived), archived_sha)
            csv_before = csv_path.read_bytes()
            csv_path.write_bytes(csv_before.replace(b"12,14", b"12,15"))
            with self.assertRaisesRegex(ValueError, "prepared source bytes/checksum"):
                producer.load_archived_source(archived, archived_sha, data, specification)
            csv_path.write_bytes(csv_before)
            archived.write_bytes(archived.read_bytes()+b" ")
            with self.assertRaisesRegex(ValueError, "archived source provenance binding"):
                producer.load_archived_source(archived, archived_sha, data, specification)

    def test_output_cannot_modify_or_contain_immutable_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = [root/name for name in ("original", "data", "keys")]
            for source in inputs:
                source.mkdir()
                for output in (source, source/"new-run", root):
                    with self.assertRaisesRegex(ValueError, "overlap an immutable input"):
                        producer.validate_output_destination(output, inputs)
            (root/"alias").symlink_to(inputs[0], target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "overlap an immutable input"):
                producer.validate_output_destination(root/"alias/new-run", inputs)
            allowed = root/"new-output"
            self.assertEqual(producer.validate_output_destination(allowed, inputs), allowed.resolve())
            self.assertFalse(allowed.exists())

    def test_raw_phase_corruption_and_full_row_mask_rejected(self):
        protocol, folds, source, causal, phases, _ = fixture()
        arrays = {k: v.copy() for k, v in phases[2023, "validation"].items() if k in d.SOURCE_ARRAYS}
        sidecar = {"schema": "filang-information-predictions-v1", "minutes": 30, "outer_year": 2023,
            "phase": "validation", "phase_start": d.epoch("2022-01-01"), "phase_end_exclusive": d.epoch("2023-01-01"),
            "source_sha256": "synthetic", "protocol_sha256": "original", "native_keys_sha256": "native",
            "arrays": {k: d.array_record(v) for k, v in arrays.items()}}
        producer.validate_phase(arrays, sidecar, folds[0], "validation", source,
                                {"valid": causal, "keys_sha256": "native"}, "original")
        with self.assertRaisesRegex(ValueError, "sidecar phase"):
            producer.validate_phase(arrays, {**sidecar, "phase": "outer"}, folds[0], "validation", source,
                                    {"valid": causal, "keys_sha256": "native"}, "original")
        altered = {k: v.copy() for k, v in arrays.items()}
        row = np.flatnonzero(altered["binary_mask"])[0]
        altered["direction"][row] *= -1
        with self.assertRaisesRegex(ValueError, "array identity direction"):
            producer.validate_phase(altered, sidecar, folds[0], "validation", source,
                                    {"valid": causal, "keys_sha256": "native"}, "original")
        # Even a self-consistent rewritten sidecar cannot hide a target shift.
        amended = {**sidecar, "arrays": {k: d.array_record(v) for k, v in altered.items()}}
        with self.assertRaisesRegex(ValueError, "original phase direction"):
            producer.validate_phase(altered, amended, folds[0], "validation", source,
                                    {"valid": causal, "keys_sha256": "native"}, "original")
        future_invalid = arrays["phase_mask"] & arrays["causal_feature_valid"] & ~arrays["classification_valid"]
        masked = {k: v.copy() for k, v in arrays.items()}
        masked["p_B"][future_invalid] = np.nan
        amended = {**sidecar, "arrays": {k: d.array_record(v) for k, v in masked.items()}}
        with self.assertRaisesRegex(ValueError, "full-row availability p_B"):
            producer.validate_phase(masked, amended, folds[0], "validation", source,
                                    {"valid": causal, "keys_sha256": "native"}, "original")

    def test_refit_model_cannot_replace_validation_vintage(self):
        model = {"stage": "inner", "fit_id": "inner-id", "coefficient_sha256": "coefficients", "path": "inner.json"}
        binding = {"fit_id": "inner-id", "coefficient_sha256": "coefficients", "path": "inner.json", "file_sha256": "file"}
        producer.validate_prediction_model(binding, model, "validation", "file")
        with self.assertRaisesRegex(ValueError, "vintage"):
            producer.validate_prediction_model(binding, {**model, "stage": "refit"}, "validation", "file")
        with self.assertRaisesRegex(ValueError, "binding"):
            producer.validate_prediction_model({**binding, "path": "refit.json"}, model, "validation", "file")

    def test_producer_retains_rejected_adapter_before_raising(self):
        protocol, _, source, _, phases, _ = fixture()
        inputs = {"phases": [{"year": year, "phase": phase, "prediction_path": f"30m/{year}/{phase}.npz",
                    "prediction_sha256": "synthetic", "models": {family: {"fit_id": "synthetic"} for family in d.FAMILIES}}
                  for year in (2023, 2024, 2025, 2026) for phase in ("validation", "outer")]}
        rejected = d.fit_adapter(np.zeros(10), np.ones(10), max_updates=0)
        with tempfile.TemporaryDirectory() as folder, patch.object(d, "fit_adapter", return_value=rejected):
            out = Path(folder)
            with self.assertRaisesRegex(ValueError, "adapter rejected"):
                producer.produce(protocol, out, phases, source, inputs, {"sha256": "synthetic"}, {})
            retained = d.read_json(out/"2023/adapters/B.json")
            self.assertFalse(retained["accepted"])
            self.assertEqual(retained["parameters"], rejected["parameters"])
            self.assertEqual(retained["gradient"], rejected["gradient"])
            lines = (out/"fits.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0]), retained)
            self.assertFalse((out/"2023/outer.npz").exists())

    def test_exact_ratio_tails_variable_counts_and_zero_ties(self):
        daily = {"adapted_paired_loss_sum": np.array([1.5, -.5]), "binary_count": np.array([100, 1], dtype=np.int64),
                 "outer_year": np.array([2023, 2023], dtype=np.int64), "day": np.array([1, 2], dtype=np.int64)}
        summary, arrays, encoding = d.ratio_bootstrap(daily, 1, replicates=100)
        rng = np.random.default_rng(20261008+30000+1)
        different_old_predicate = False
        for i in range(100):
            selected = rng.integers(0, 2, size=2, dtype=np.int64)
            total = sum(float(daily["adapted_paired_loss_sum"][j]) for j in selected)
            count = sum(int(daily["binary_count"][j]) for j in selected)
            expected = 101*total >= 2*count
            self.assertEqual(bool(arrays["exact_tail_hits"][i]), expected)
            self.assertEqual(arrays["resampled_count"][i], count)
            different_old_predicate |= (total >= 2) != expected
        self.assertTrue(different_old_predicate)
        self.assertEqual(summary["p_one_sided"], (1+int(arrays["exact_tail_hits"].sum()))/101)
        self.assertEqual(encoding["count_sum"], 101)
        daily["adapted_paired_loss_sum"] *= -1
        _, negative, _ = d.ratio_bootstrap(daily, 1, replicates=100)
        self.assertTrue(negative["exact_tail_hits"].any())
        daily["adapted_paired_loss_sum"][:] = 0
        tied, bits, _ = d.ratio_bootstrap(daily, 1, replicates=100)
        self.assertTrue(bits["exact_tail_hits"].all())
        self.assertEqual(tied["p_one_sided"], 1)

    def test_empty_bootstrap_denominators_fail_without_redraw(self):
        daily = {"adapted_paired_loss_sum": np.array([0., 0.]), "binary_count": np.array([0, 0], dtype=np.int64),
                 "outer_year": np.array([2023, 2023], dtype=np.int64), "day": np.array([1, 2], dtype=np.int64)}
        with self.assertRaisesRegex(ValueError, "original bootstrap denominator"):
            d.ratio_bootstrap(daily, 1, replicates=100)
        daily["binary_count"][0] = 1
        with self.assertRaisesRegex(ValueError, "resampled bootstrap denominator"):
            d.ratio_bootstrap(daily, 1, replicates=100)

    def test_exact_encoding_roundtrips_and_npz_forbids_objects(self):
        values = np.array([0., np.nextafter(0., 1.), -.1, 1.5])
        counts, years, days = np.ones(4, dtype=np.int64), np.full(4, 2023, np.int64), np.arange(4, dtype=np.int64)
        record, integers = d.integer_encoding(values, counts, years, days)
        denominator = 1 << record["denominator_power_of_two"]
        for value, numerator in zip(values, integers):
            n, den = float(value).as_integer_ratio()
            self.assertEqual(numerator*den, n*denominator)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "object arrays forbidden"):
                d.write_npz(Path(folder)/"unsafe.npz", {"a": np.array([None], dtype=object)})

    def test_nested_seals_retained_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"predecessor").mkdir()
            (root/"predecessor/manifest.json").write_text("{}\n")
            (root/"predecessor/manifest.sha256").write_text("original\n")
            d.write_json(root/"run.json", {"status": "FAILED"})
            producer.seal_run(root)
            manifest = d.read_json(root/"manifest.json")
            self.assertIn("predecessor/manifest.json", manifest["files"])
            self.assertIn("predecessor/manifest.sha256", manifest["files"])
            self.assertNotIn("manifest.json", manifest["files"])
            self.assertEqual((root/"manifest.sha256").read_text(), d.digest(root/"manifest.json")+"\n")
            with self.assertRaisesRegex(ValueError, "contained"):
                producer.bounded(root, "../elsewhere")

    def test_frozen_protocol_identity_and_corrupt_root_rejection(self):
        path = HERE/"followup30_protocol.json"
        self.assertEqual(d.digest(path), producer.PROTOCOL_SHA256)
        protocol = d.read_json(path)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/"analysis.json").write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "pinned original root identity"):
                producer.admit_inputs(root, root, root, protocol, root/"out")


if __name__ == "__main__":
    unittest.main()
