import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

from experiments.geometry_information import common as c
from experiments.geometry_information import interactions as i
from experiments.geometry_information import run_round3 as runner


def synthetic_source(change_final_outer=False):
    """A generated daily-grid fixture; no market source is read or computed."""
    ts = np.arange(c.timestamp("2020-01-01"), c.timestamp("2026-10-08"), 86400, dtype=np.int64)
    sequence = np.arange(len(ts))
    opens = 100 * np.exp(sequence * 1e-6 + .0005 * np.sin(sequence / 3))
    opens[1::11] = opens[::11][:len(opens[1::11])]
    if change_final_outer:
        changed = ts >= c.timestamp("2026-01-01")
        opens[changed] *= np.exp(.0002 * np.sin(sequence[changed]))
    close = opens * (1 + .0001 * np.cos(sequence / 5))
    low = np.minimum(opens, close) * .9999
    high = np.maximum(opens, close) * 1.0001
    ohlc = np.column_stack((opens, high, low, close))
    valid = c.causal_mask(ts, 86400, int(ts[0]), c.timestamp("2026-10-08"))
    indices = np.flatnonzero(valid)
    ranks = np.empty((len(indices), 10, 4), dtype=np.uint8)
    up = np.empty((len(indices), 10), dtype=bool)
    endpoints = np.column_stack((low, np.minimum(opens, close), np.maximum(opens, close), high))
    for k, row in enumerate(indices):
        rows = row - np.arange(10)
        ranks[k] = np.unique(endpoints[rows], return_inverse=True)[1].reshape(10, 4)
        up[k] = close[rows] > opens[rows]
    source = {"timestamps": ts, "ohlc": ohlc, "interval_seconds": 86400, "rows": len(ts),
              "sha256": c.array_sha(ohlc), "raw_sha256": "a" * 64, "path": "synthetic-only", "missing_grid_bars": 0}
    keys = {"indices": indices, "ranks": ranks, "up": up, "valid": valid,
            "context_sha256": "b" * 64, "manifest_sha256": "c" * 64,
            "keys_sha256": c.array_sha(ranks), "context": {"engine_sha256": "d" * 64}}
    return source, keys


class RoundThreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runner.numerical()

    def run_fixture(self, destination, changed=False):
        protocol_path = Path(__file__).parents[1] / "round3_protocol.json"
        protocol = json.loads(protocol_path.read_bytes())
        protocol["inference"]["bootstrap"]["replicates"] = 7
        protocol["features"]["catalogue"]["catalogue_sha256"] = i.catalogue_sha256()
        destination.mkdir()
        c.write_json(destination / "protocol.json", protocol)
        c.write_json(destination / "provenance.json", {"synthetic_fixture": True})
        (destination / "catalogue.json").write_bytes(i.catalogue_bytes())
        source, keys = synthetic_source(changed)
        options = {"out": str(destination), "data_dir": "synthetic-only", "keys_dir": "synthetic-only",
                   "protocol_sha256": c.digest(destination / "protocol.json"), "implementation_sha256": "e" * 64}
        with patch.object(c, "load_source", return_value=source), patch.object(c, "decode_keys", return_value=keys), \
                threadpool_limits(limits=1), contextlib.redirect_stdout(io.StringIO()):
            result = runner.timeframe_job(options, 15)
        return result

    def test_complete_compact_worker_and_outer_label_invariance(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"
            result, receipt, _ = self.run_fixture(first)
            changed, changed_receipt, _ = self.run_fixture(second, changed=True)
            self.assertEqual(receipt["inner_fits"], 128)
            self.assertEqual(receipt["refits"], 8)
            self.assertEqual(receipt["statistics_built"], 5)
            self.assertEqual(receipt["policy_choices"], 12)
            self.assertEqual(receipt["validation_ledgers"], 84)
            self.assertEqual(receipt["outer_ledgers"], 80)
            self.assertEqual(receipt["prediction_phases"], 8)
            root = first / "15m"
            records = {name: [json.loads(line) for line in (root / f"{name}.jsonl").read_text().splitlines()]
                       for name in ("fits", "statistics", "selections", "ledgers")}
            self.assertEqual([len(records[name]) for name in ("fits", "statistics", "selections", "ledgers")], [136, 5, 12, 164])
            self.assertEqual(len({row["fit_id"] for row in records["fits"]}), 136)
            self.assertEqual(len({row["ledger_id"] for row in records["ledgers"]}), 164)
            self.assertEqual(len(list(root.glob("*.npz"))), 5)
            self.assertLess(len(list(root.rglob("*"))), 20)
            encoding = json.loads((root / "bootstrap-exact.json").read_bytes())
            self.assertEqual(encoding["comparison_order"], ["I_minus_A", "I_minus_cash"])
            self.assertEqual(encoding["fold_lengths"], [365, 366, 365, 280])
            with np.load(root / "bootstrap.npz", allow_pickle=False) as bootstraps:
                self.assertEqual(len(bootstraps.files), 9)
                for block in (7, 1, 28):
                    hits = bootstraps[f"block{block}__exact_hits"]
                    self.assertEqual(hits.dtype, np.dtype(bool))
                    self.assertEqual(hits.shape, (7, 2))
                    for column, name in enumerate(encoding["comparison_order"]):
                        record = result["bootstrap"][str(block)]["comparisons"][name]
                        self.assertEqual(record["p_one_sided"], (1 + np.count_nonzero(hits[:, column])) / 8)
            for row in records["statistics"]:
                self.assertEqual(row["construction_method"], runner.ir.STATISTICS_METHOD)
                self.assertEqual(row["array_identities"]["gram_mean"]["shape"], [571, 571])
            with np.load(root / "year2026.npz", allow_pickle=False) as data:
                phase = data["outer__phase_mask"]
                causal = data["outer__causal_feature_valid"]
                target = data["outer__target_valid"]
                for family in ("A", "I", "U"):
                    np.testing.assert_array_equal(np.isfinite(data[f"outer__mu_{family}"]), phase & causal)
                self.assertTrue(np.any(phase & causal & ~target))
                self.assertTrue(np.any(data["outer__target_log_return"][target] == 0))
                self.assertFalse(any(data[name].dtype.kind == "O" for name in data.files))
            other_fits = [json.loads(line) for line in (second / "15m" / "fits.jsonl").read_text().splitlines()]
            for old, new in zip(records["fits"], other_fits):
                # All fit samples end before changed 2026 outer observations.
                self.assertEqual(old["fit_rows_sha256"], new["fit_rows_sha256"])
                self.assertEqual(old["fit_targets_sha256"], new["fit_targets_sha256"])
                np.testing.assert_array_equal(old["coefficients"], new["coefficients"])
                self.assertEqual(old["intercept"], new["intercept"])
            for old, new in zip(result["folds"], changed["folds"]):
                for family in ("A", "I", "U"):
                    a, b = old["selected"][family], new["selected"][family]
                    self.assertEqual((a["n"], a["lambda"], a["policy"]), (b["n"], b["lambda"], b["policy"]))
            # The first three outer years precede every modified source row.
            # Every available past forecast must remain unchanged too.
            for year in (2023, 2024, 2025):
                with np.load(root / f"year{year}.npz", allow_pickle=False) as old, \
                     np.load(second / "15m" / f"year{year}.npz", allow_pickle=False) as new:
                    for family in ("A", "I", "U"):
                        np.testing.assert_array_equal(old[f"outer__mu_{family}"], new[f"outer__mu_{family}"])
            self.assertEqual(receipt["inner_fits"], changed_receipt["inner_fits"])

    def test_failed_fit_payload_is_retained_before_worker_raises(self):
        original = runner.r.fit_ridge
        def reject(*args, **kwargs):
            model = original(*args, **kwargs)
            model["accepted"] = False
            model["solver"]["success"] = False
            model["solver"]["message"] = "synthetic deliberate rejection"
            model["objective"] = np.nan
            model["normal_residual"][0] = np.inf
            model["max_abs_normal_residual"] = np.inf
            return model
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.r, "fit_ridge", side_effect=reject):
            out = Path(tmp) / "failed"
            with self.assertRaisesRegex(RuntimeError, "required ridge fit rejected"):
                self.run_fixture(out)
            records = [json.loads(line) for line in (out / "15m" / "fits.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["accepted"])
            self.assertIsNone(records[0]["objective"])
            self.assertIsNone(records[0]["normal_residual"][0])
            with np.load(out / "15m" / "year2023.npz", allow_pickle=False) as arrays:
                prefix = records[0]["nonfinite_payload_prefix"]
                for diagnostic in ("theta", "gradient", "objective", "normal_residual",
                                   "max_abs_gradient", "max_abs_normal_residual"):
                    self.assertIn(prefix + "__" + diagnostic, arrays.files)
                self.assertTrue(np.isnan(arrays[prefix + "__objective"]))
                self.assertTrue(np.isposinf(arrays[prefix + "__normal_residual"][0]))
                self.assertTrue(np.isposinf(arrays[prefix + "__max_abs_normal_residual"]))
            runner.seal_run(out)
            self.assertEqual((out / "manifest.sha256").read_text(), c.digest(out / "manifest.json") + "\n")

    def test_same_year_activity_and_strict_significance_boundaries(self):
        result = {"bootstrap": {"7": {"comparisons": {
            name: {"mean_daily_net_log_gain": .01, "ci95_low": .001}
            for name in ("I_minus_A", "I_minus_cash")}}}, "joint_positive_years": 3, "completed_I_trades": 20}
        self.assertTrue(all(runner.outcome_conditions(result, .049).values()))
        self.assertFalse(runner.outcome_conditions(result, .05)["holm_below_005"])
        result["joint_positive_years"] = 2
        self.assertFalse(runner.outcome_conditions(result, .01)["three_same_positive_years"])
        result["completed_I_trades"] = 19
        self.assertFalse(runner.outcome_conditions(result, .01)["twenty_I_completed_trades"])
        result["bootstrap"]["7"]["comparisons"]["I_minus_cash"]["ci95_low"] = 0
        self.assertFalse(runner.outcome_conditions(result, .01)["both_ci_above_zero"])

    def test_nonfinite_json_and_numeric_payload_rules(self):
        original = {"accepted": False, "values": [np.nan, np.inf, -np.inf, 1.]}
        self.assertEqual(runner.nullable_failure(original), {"accepted": False, "values": [None, None, None, 1.]})
        with tempfile.TemporaryDirectory() as tmp:
            for array in (np.array([object()], dtype=object), np.array(["not numeric"]),
                          np.array([b"bytes"]), np.array([1+2j]), np.array(["2026-01-01"], dtype="datetime64[D]")):
                with self.assertRaisesRegex(ValueError, "only real numeric and boolean arrays permitted"):
                    runner.save_npz(Path(tmp) / "bad.npz", {"bad": array})

    def test_unpublished_or_malformed_freeze_identities_are_rejected(self):
        runner.require_frozen_identifiers("a" * 64, "b" * 40)
        for protocol, commit in (("PENDING", "b" * 40), ("a" * 64, "PENDING"),
                                 ("A" * 64, "b" * 40), ("a" * 63, "b" * 40),
                                 ("a" * 64, "b" * 41)):
            with self.assertRaisesRegex(ValueError, "published, fixed protocol and freeze identities"):
                runner.require_frozen_identifiers(protocol, commit)


if __name__ == "__main__":
    unittest.main()
