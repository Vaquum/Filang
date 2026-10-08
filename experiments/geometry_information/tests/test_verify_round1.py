"""Hand-derived and mutation tests for the independent audit, without fitting."""
import math
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np
from experiments.geometry_information import verify_round1 as v


def pack(ranks, up):
    output = []
    for window, flags in zip(ranks, up):
        value = sum(int(rank) << (6*i) for i, rank in enumerate(window.ravel()))
        value |= sum(int(flag) << (240+i) for i, flag in enumerate(flags))
        value |= len(window) << 250
        value |= 1 << 254
        output.append([(value >> (64*i)) & ((1 << 64)-1) for i in range(4)])
    return np.asarray(output, dtype=np.uint64)


def fixture(count=40):
    rng = np.random.default_rng(100)
    base = rng.integers(20, 25, count)
    close = base + rng.integers(-2, 3, count)
    prices = np.column_stack((base, np.maximum(base, close)+rng.integers(0, 3, count),
                              np.minimum(base, close)-rng.integers(0, 3, count), close)).astype(float)
    return {"timestamp": np.arange(count, dtype=np.int64)*60, "prices": prices, "interval_seconds": 60}


class VerifierTests(unittest.TestCase):
    def test_native_word_boundaries_and_all_raw_feature_columns(self):
        s = fixture()
        rows = np.arange(9, len(s["prices"]))
        ranks = v.raw_dense_ranks(s["prices"], rows, 10)
        up = s["prices"][rows[:, None]-np.arange(10), 3] > s["prices"][rows[:, None]-np.arange(10), 0]
        decoded, flags = v.decode_words(pack(ranks, up))
        np.testing.assert_array_equal(decoded, ranks)
        np.testing.assert_array_equal(flags, up)
        for n in (2, 3, 5, 10):
            for family, width in (("B", 4*n-2), ("G", 38*n-34)):
                raw = v.raw_features(s["prices"], rows, n, family)
                self.assertEqual(raw.shape[1], width)
                np.testing.assert_array_equal(raw, v.key_features(decoded, flags, n, family))

    def test_key_metadata_reserved_and_flat_flag_rejected(self):
        ranks = np.zeros((1, 10, 4), dtype=np.uint8)
        words = pack(ranks, np.zeros((1, 10), dtype=bool))
        for bit in (255, 240):
            mutated = words.copy()
            mutated[0, bit//64] |= np.uint64(1 << (bit%64))
            with self.assertRaises(ValueError):
                v.decode_words(mutated)
        mutated = words.copy()
        mutated[0, 3] ^= np.uint64(1 << 62)
        with self.assertRaises(ValueError):
            v.decode_words(mutated)

    def test_target_exact_two_open_lag_and_strict_exit_boundary(self):
        s = fixture(18)
        s["prices"][:, 0] = 100
        s["prices"][11, 0] = 110
        a = v.phase_oracle(s, np.arange(9, 18), 9*60, 14*60)
        np.testing.assert_array_equal(np.flatnonzero(a["classification_valid"]), [9, 10, 11])
        np.testing.assert_array_equal(a["direction"][[9, 10, 11]], [1, -1, 0])
        self.assertAlmostEqual(a["target_return"][9], .1)
        self.assertTrue(a["causal_feature_valid"][-1])
        self.assertFalse(a["classification_valid"][-1])
        self.assertEqual(a["entry_row"][12], -1)

    def test_future_gap_cannot_change_causal_validity_but_purges_label(self):
        s = fixture(25)
        s["timestamp"][12:] += 60
        rows = np.arange(9, 25)
        rows = rows[s["timestamp"][rows]-s["timestamp"][rows-9] == 540]
        a = v.phase_oracle(s, rows, 0, 10000)
        self.assertTrue(a["causal_feature_valid"][11])
        self.assertFalse(a["classification_valid"][11])
        self.assertFalse(a["classification_valid"][10])
        self.assertTrue(a["classification_valid"][9])
        self.assertFalse(a["causal_feature_valid"][20])
        self.assertTrue(a["causal_feature_valid"][21])

    def test_unpenalized_intercept_gradient_by_finite_difference(self):
        x = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype=float)
        y = np.array([1, 1, 0, 0])
        theta = np.array([.2, -.1, .3])
        _, gradient = v.objective_gradient(x, y, theta[0], theta[1:], .1)
        for k in range(3):
            upper, lower = theta.copy(), theta.copy()
            upper[k] += 1e-6
            lower[k] -= 1e-6
            a = v.objective_gradient(x, y, upper[0], upper[1:], .1)[0]
            b = v.objective_gradient(x, y, lower[0], lower[1:], .1)[0]
            self.assertAlmostEqual(gradient[k], (a-b)/2e-6, places=9)

    def test_cash_and_coin_account_fees_and_delayed_gap_sell(self):
        result = v.cash_share_oracle([0, 60, 120, 300, 360], [100, 100, 110, 55, 50],
                                    [.8, .8, .1, np.nan, .8], start=0, end=361,
                                    interval_seconds=60, fee_bps=10, slippage_bps=2)
        factor = .55*(1-.001)**2*(1-.0002)/(1+.0002)
        self.assertAlmostEqual(result["metrics"]["net_return"], factor-1)
        self.assertEqual(result["trades"][0]["exit_row"], 3)
        self.assertEqual(result["gaps"][0]["position_before"], 1)
        self.assertEqual(result["gaps"][0]["position_after"], 0)
        self.assertEqual(result["gaps"][0]["delay_seconds"], 120)
        self.assertAlmostEqual(result["gaps"][0]["gap_gross_log_return"], math.log(.5))

    def test_quantity_account_agrees_with_producer_on_random_traces(self):
        # The producer is imported only by this test, never by the audit itself.
        from experiments.geometry_information.economics import run_ledger
        rng = np.random.default_rng(33)
        for _ in range(30):
            ts = np.cumsum(rng.choice([60, 60, 60, 180], 35))
            op = np.exp(rng.normal(4, .1, len(ts)))
            p = rng.choice([.1, .5, .6, .9, np.nan], len(ts))
            opts = dict(start=int(ts[2]), end=int(ts[-1])+1, interval_seconds=60,
                        fee_bps=10, slippage_bps=2, policy=rng.choice(["threshold", "cash", "buy_hold"]))
            expected = v.cash_share_oracle(ts, op, p, **opts)
            actual = run_ledger(ts, op, p, **opts)
            v.compare(actual, expected)

    def test_global_centering_bootstrap_and_producer_replica_parity(self):
        from experiments.geometry_information import common
        folds = [{"binary_count": np.array([1, 0, 10, 2]), "paired_loss_sum": np.array([.2, 0, 1., -.3])},
                 {"binary_count": np.array([3, 8, 1]), "paired_loss_sum": np.array([-.8, .4, 0])}]
        for block in (1, 7, 28):
            summary, arrays = v.bootstrap_oracle(folds, 15, block, replicas=100)
            np.testing.assert_allclose(arrays["centered"], arrays["ordinary"]-summary["gain"], atol=1e-15)
            produced, ordinary, centered = common.bootstrap_gain(folds, 15, block, replicates=100)
            v.compare(arrays, {"ordinary": ordinary, "centered": centered})
            for field in summary:
                v.compare(produced[field], summary[field], field)

    def test_daily_units_use_target_exit_date_and_retain_zero_days(self):
        arrays = {"timestamp": np.array([86340, 86400, 86460]), "exit_row": np.array([2, -1, -1]),
                  "binary_mask": np.array([True, False, False]), "classification_valid": np.array([True, False, False]),
                  "direction": np.array([1, 0, 0], dtype=np.int8)}
        for name in ("B", "G", "unconditional", "lag1"):
            arrays[f"p_{name}"] = np.array([.5, np.nan, np.nan])
        for name in ("B", "G"):
            arrays[f"logit_{name}"] = np.array([0, np.nan, np.nan])
        daily = v.daily_oracle(arrays, 0, 3*86400)
        np.testing.assert_array_equal(daily["binary_count"], [0, 1, 0])
        self.assertAlmostEqual(daily["loss_sum_B"][1], math.log(2))

    def native_fixture(self, directory):
        s = fixture(40)
        source = directory / "ohlcv.csv"
        with source.open("w") as f:
            f.write("timestamp,open,high,low,close,volume\n")
            for ts, p in zip(s["timestamp"], s["prices"]):
                f.write(",".join(map(str, [int(ts), *p, 1]))+"\n")
        s = v.load_source(source, 60)
        protocol = {"data": {"history_start": "1970-01-01", "end_exclusive": "1970-01-02"}}
        context = {"format": "geometry-keys-v1", "source_sha256": s["sha256"], "engine_sha256": "a"*64,
                   "interval_seconds": 60, "history_start": "1970-01-01", "end": "1970-01-02", "bars": 10,
                   "mode": "oriented", "key_layout": "geometry-key-256-v1",
                   "eligibility": "all_window_rows_in_history_consecutive_past_only"}
        v.save_json(directory / "context.json", context)
        v.save_json(directory / "timings.json", {"seconds": 1})
        rows, all_ranks, all_up = np.arange(9, 40), [], []
        for t in rows:
            values, flags = [], []
            for k in range(10):
                o, h, low, c = s["prices"][t-k]
                values += [low, min(o, c), max(o, c), h]
                flags.append(c > o)
            ranks = {value: i for i, value in enumerate(sorted(set(values)))}
            all_ranks.append(np.array([ranks[x] for x in values]).reshape(10, 4))
            all_up.append(flags)
        words = pack(all_ranks, all_up)
        header = b"FGKEYS01"+v.digest(directory / "context.json").encode()+s["sha256"].encode()+struct.pack("<4Q", 40, 60, 10, 31)
        payload = header+b"".join(struct.pack("<5Q", int(row), *map(int, key)) for row, key in zip(rows, words))
        (directory / "keys.bin").write_bytes(payload+hashlib.sha256(payload).hexdigest().encode())
        manifest = {"format": "geometry-keys-v1", "status": "COMPLETE", "context_sha256": v.digest(directory / "context.json"),
                    "source_sha256": s["sha256"], "source_bytes": s["bytes"], "source_rows": 40,
                    "selected_first_index": 0, "selected_end_index_exclusive": 40, "selected_rows": 40,
                    "initial_warmup_rows": 9, "gap_window_skips": 0, "source_gap_count": 0, "source_missing_grid_bars": 0,
                    "bars": 10, "mode": "oriented", "records": 31, "header_bytes": 168, "record_bytes": 40,
                    "keys_file": "keys.bin", "keys_payload_bytes": len(payload),
                    "keys_payload_sha256": hashlib.sha256(payload).hexdigest(), "keys_file_bytes": len(payload)+64,
                    "keys_file_sha256": v.digest(directory / "keys.bin"), "timings_sha256": v.digest(directory / "timings.json")}
        v.save_json(directory / "manifest.json", manifest)
        (directory / "manifest.sha256").write_text(v.digest(directory / "manifest.json")+"\n")
        return s, protocol

    def test_all_record_native_serialization_and_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source, protocol = self.native_fixture(folder)
            receipt, rows = v.audit_native_keys(folder, source, protocol)
            self.assertEqual(receipt["records_checked"], 31)
            self.assertEqual(rows[-1], 39)  # Final causal row retained despite no target.
            data = bytearray((folder / "keys.bin").read_bytes())
            data[180] ^= 1
            (folder / "keys.bin").write_bytes(data)
            with self.assertRaisesRegex(ValueError, "seal"):
                v.audit_native_keys(folder, source, protocol)

    def test_resealed_semantic_native_mutation_still_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source, protocol = self.native_fixture(folder)
            data = bytearray((folder / "keys.bin").read_bytes())
            # Change original row index while preserving all cryptographic seals.
            data[168] = 10
            data[-64:] = hashlib.sha256(data[:-64]).hexdigest().encode()
            (folder / "keys.bin").write_bytes(data)
            manifest = json.loads((folder / "manifest.json").read_text())
            manifest["keys_file_sha256"] = v.digest(folder / "keys.bin")
            manifest["keys_payload_sha256"] = data[-64:].decode()
            v.save_json(folder / "manifest.json", manifest)
            (folder / "manifest.sha256").write_text(v.digest(folder / "manifest.json")+"\n")
            with self.assertRaisesRegex(ValueError, "original-row"):
                v.audit_native_keys(folder, source, protocol)

    def test_prediction_sidecars_full_rows_and_final_causal_signal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, _ = self.native_fixture(root)
            rows = np.arange(9, 40)
            fold = {"year": 1970, "outer_start": "1970-01-01", "outer_end_exclusive": "1970-01-02"}
            arrays = v.phase_oracle(source, rows, 0, 86400)
            fit_labels = dict(arrays)
            mask = arrays["causal_feature_valid"] & arrays["phase_mask"]
            models = {}
            for family in ("B", "G"):
                model = {"n": 2, "intercept": 0., "coefficients": [0.]*len(v.feature_names(2, family)),
                         "fit_id": family*64, "coefficient_sha256": family.lower()*64, "path": family+".json"}
                v.save_json(root / model["path"], model)
                models[family] = model
                arrays[f"p_{family}"] = np.where(mask, .5, np.nan)
                arrays[f"logit_{family}"] = np.where(mask, 0., np.nan)
            baseline, arrays["p_unconditional"], arrays["p_lag1"] = v.baseline_oracle(source, fit_labels, mask)
            path = root / "outer.npz"
            np.savez(path, **arrays)
            sidecar = {"schema": "filang-information-predictions-v1", "minutes": 1, "outer_year": 1970,
                       "phase": "outer", "phase_start": 0, "phase_end_exclusive": 86400,
                       "source_sha256": source["sha256"], "protocol_sha256": "a"*64, "native_keys_sha256": "b"*64,
                       "models": {family: {"fit_id": model["fit_id"], "coefficient_sha256": model["coefficient_sha256"],
                                  "path": model["path"], "file_sha256": v.digest(root / model["path"])} for family, model in models.items()},
                       "baseline_fit": baseline, "baseline_fit_rows_sha256": v.array_digest(np.flatnonzero(fit_labels["binary_mask"]), "<i8"),
                       "baseline_fit_labels_sha256": v.array_digest(fit_labels["direction"][fit_labels["binary_mask"]] == 1, np.uint8),
                       "scores": v.phase_scores(arrays), "npz_sha256": v.digest(path), "npz_bytes": path.stat().st_size,
                       "arrays": {name: {"dtype": value.dtype.str, "shape": list(value.shape), "sha256": v.array_digest(value)}
                                  for name, value in arrays.items()}}
            v.save_json(path.with_suffix(".json"), sidecar)
            receipt = {"minutes": 1, "keys_file_sha256": "b"*64}
            verified, _, _ = v.audit_predictions(root, root, "outer", source, rows, fold, models, fit_labels, "a"*64, receipt)
            self.assertTrue(np.isfinite(verified["p_B"][-1]))
            self.assertFalse(verified["classification_valid"][-1])
            arrays["p_B"][-1] = np.nan
            np.savez(path, **arrays)
            with self.assertRaisesRegex(ValueError, "NaN placement"):
                v.audit_predictions(root, root, "outer", source, rows, fold, models, fit_labels, "a"*64, receipt)

    def test_exact_flat_trade_never_becomes_roundoff_win(self):
        p = [.6]*100
        opens = [107.3]+[103.7]*98+[103.7]
        result = v.cash_share_oracle(np.arange(100)*60, opens, p, start=0, end=6000,
                                    interval_seconds=60, fee_bps=0, slippage_bps=0)
        self.assertEqual(result["trades"][0]["net_return"], 0)
        self.assertEqual(result["metrics"]["trade_win_rate"], 0)

    def test_forensic_acceptance_keeps_maxiter_failure_with_small_gradient(self):
        source = fixture()
        source["sha256"] = "a"*64
        labels = {"binary_mask": np.array([False]*10+[True]*4+[False]*26),
                  "direction": np.array([0]*10+[-1, 1, -1, 1]+[0]*26, dtype=np.int8)}
        rows, y = np.arange(10, 14), np.array([0, 1, 0, 1], dtype=np.uint8)
        feature = np.zeros((4, 6))
        fold = {"year": 2023, "inner_train_start": "1970-01-01", "inner_train_end_exclusive": "1970-01-02"}
        receipt = {"minutes": 15, "keys_file_sha256": "b"*64,
                   "features": {"B2": {"sha256": "c"*64}}}
        model = {"schema": "filang-information-fit-v1", "minutes": 15, "outer_year": 2023, "family": "B", "n": 2,
                 "lambda": .1, "stage": "inner", "fit_start": 0, "fit_end_exclusive": 86400,
                 "fit_count": 4, "fit_up_count": 2, "fit_down_count": 2,
                 "fit_rows_sha256": v.array_digest(rows, "<i8"), "fit_labels_sha256": v.array_digest(y),
                 "feature_sha256": "c"*64, "feature_columns_sha256": v.json_digest(v.feature_names(2, "B")),
                 "source_sha256": "a"*64, "native_keys_sha256": "b"*64, "protocol_sha256": v.R1_PROTOCOL_SHA256,
                 "implementation_sha256": "e"*64, "initializer": {"kind": "beta11_zero", "parent_fit_id": None,
                 "parent_coefficient_sha256": None}, "cache_hit": False}
        model["fit_id"] = v.json_digest(model)
        model.update(intercept=0., coefficients=[0.]*6, objective=math.log(2), gradient=[0.]*7,
                     max_abs_gradient=0., coefficient_sha256=v.array_digest(np.zeros(7), "<f8"),
                     initializer_sha256=v.array_digest(np.zeros(7), "<f8"), accepted=False,
                     optimizer={"success": False, "status": 1, "iterations": 1000, "function_evaluations": 1001,
                                "gradient_evaluations": 1001, "reported_objective": math.log(2)})
        arguments = (model, source, receipt, feature, labels, fold, "B", 2, .1, "inner", v.R1_PROTOCOL_SHA256, "e"*64, None)
        v.audit_fit(*arguments, require_accepted=False)
        with self.assertRaisesRegex(ValueError, "unaccepted"):
            v.audit_fit(*arguments)
        model["accepted"] = True
        with self.assertRaisesRegex(ValueError, "acceptance"):
            v.audit_fit(*arguments, require_accepted=False)
        model["accepted"] = False
        model["gradient"][2] = .1
        with self.assertRaisesRegex(ValueError, "gradient"):
            v.audit_fit(*arguments, require_accepted=False)


if __name__ == "__main__":
    unittest.main()
