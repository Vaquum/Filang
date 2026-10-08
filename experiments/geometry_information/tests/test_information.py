"""Synthetic tests only: no market fits or outcome inspection."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as c
import run_round1 as runner

OPTIMIZER = {"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-7, "maxls": 50}
DAY = 86400


def source(rows=90, gap=None):
    t = np.arange(rows)
    times = c.timestamp("2020-01-01")+t*DAY
    if gap is not None: times[gap:] += 2*DAY
    opens = 100+2*np.sin(0.7*t)+0.03*t
    closes = opens + (t % 3-1)*0.3
    lows, highs = np.minimum(opens, closes)-0.2*(t % 2), np.maximum(opens, closes)+0.1*(t % 4)
    ohlc = np.column_stack([opens, highs, lows, closes])
    return {"timestamps": times, "ohlc": ohlc, "interval_seconds": DAY,
            "rows": rows, "sha256": "1"*64}


def independent_ranks(data):
    valid = c.causal_mask(data["timestamps"], DAY, data["timestamps"][0], data["timestamps"][-1]+DAY)
    indices = np.flatnonzero(valid)
    ranks, ups, words = [], [], []
    for t in indices:
        rows = data["ohlc"][np.arange(t, t-10, -1)]
        endpoints = [[float(l), min(o, close), max(o, close), float(h)] for o, h, l, close in rows]
        levels = sorted(set(v for row in endpoints for v in row))
        r = [[levels.index(v) for v in row] for row in endpoints]
        u = [close > o for o, _, _, close in rows]
        integer = sum(value << (6*(4*lag+endpoint)) for lag, row in enumerate(r) for endpoint, value in enumerate(row))
        integer |= sum(int(up) << (240+lag) for lag, up in enumerate(u))
        integer |= 10 << 250 | 1 << 254
        ranks.append(r); ups.append(u)
        words.append([(integer >> (64*k)) & (2**64-1) for k in range(4)])
    return indices, np.array(ranks, dtype=np.uint8), np.array(ups, dtype=bool), words


def raw_features(data, indices, n, family):
    result = []
    for t in indices:
        rows = data["ohlc"][np.arange(t, t-n, -1)]
        values = []
        for o, h, l, close in rows: values.extend([close > o, close < o])
        for k in range(n-1): values.extend([rows[k, 3] > rows[k+1, 3], rows[k, 3] < rows[k+1, 3]])
        endpoints = [[l, min(o, close), max(o, close), h] for o, h, l, close in rows]
        if family == "G":
            for k in range(1, n):
                for a in endpoints[0]:
                    for b in endpoints[k]: values.extend([a < b, a == b])
            for l, bottom, top, h in endpoints: values.extend([l < bottom, top < h])
        result.append(values)
    return np.array(result, dtype=np.uint8)


def native_fixture(root, data):
    indices, ranks, up, words = independent_ranks(data)
    context = {"source_sha256": data["sha256"], "engine_sha256": "2"*64,
               "history_start": "2020-01-01", "end": "2020-03-31", "bars": 10, "mode": "oriented",
               "key_layout": "geometry-key-256-v1", "interval_seconds": DAY,
               "eligibility": "all_window_rows_in_history_consecutive_past_only"}
    c.write_json(root / "context.json", context)
    c.write_json(root / "timings.json", {"operational": True})
    payload = b"FGKEYS01"+c.digest(root / "context.json").encode()+data["sha256"].encode()
    payload += struct.pack("<4Q", len(data["timestamps"]), DAY, 10, len(indices))
    payload += b"".join(struct.pack("<5Q", int(t), *w) for t, w in zip(indices, words))
    payload_sha = hashlib.sha256(payload).hexdigest()
    (root / "keys.bin").write_bytes(payload+payload_sha.encode())
    manifest = {"format": "geometry-keys-v1", "status": "COMPLETE", "source_sha256": data["sha256"],
                "context_sha256": c.digest(root / "context.json"), "timings_sha256": c.digest(root / "timings.json"),
                "keys_file_sha256": c.digest(root / "keys.bin"), "keys_payload_sha256": payload_sha,
                "keys_payload_bytes": len(payload), "keys_file_bytes": len(payload)+64,
                "source_rows": len(data["timestamps"]), "records": len(indices)}
    c.write_json(root / "manifest.json", manifest)
    (root / "manifest.sha256").write_text(c.digest(root / "manifest.json")+"\n")
    return ranks, up


class InformationTests(unittest.TestCase):
    def test_all_feature_columns_and_native_seals(self):
        data = source()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            native_fixture(root, data)
            decoded = c.decode_keys(root, data, c.timestamp("2020-01-01"), c.timestamp("2020-03-31"))
            for n in (2, 3, 5, 10):
                for family in ("B", "G"):
                    got = c.features(decoded["ranks"], decoded["up"], n, family)
                    np.testing.assert_array_equal(got, raw_features(data, decoded["indices"], n, family))
                    self.assertEqual(got.shape[1], 4*n-2 if family == "B" else 38*n-34)
                    self.assertEqual(len(c.feature_names(n, family)), got.shape[1])
            original = (root / "keys.bin").read_bytes()
            (root / "keys.bin").write_bytes(original[:-1]+b"!")
            with self.assertRaisesRegex(ValueError, "seal"):
                c.decode_keys(root, data, c.timestamp("2020-01-01"), c.timestamp("2020-03-31"))

    def test_phase_boundaries_gaps_flats_and_final_causal_rows(self):
        data = source(35, gap=17)
        data["ohlc"][13, 0] = data["ohlc"][12, 0]  # t=11 is a genuine flat label.
        start, end = int(data["timestamps"][10]), int(data["timestamps"][30])
        valid = c.causal_mask(data["timestamps"], DAY, data["timestamps"][0], data["timestamps"][-1]+DAY)
        labels = c.phase_labels(data, valid, start, end)
        self.assertFalse(labels["classification_valid"][9])
        self.assertTrue(labels["classification_valid"][10])
        self.assertTrue(labels["classification_valid"][11])
        self.assertEqual(labels["direction"][11], 0)
        self.assertFalse(labels["binary_mask"][11])
        self.assertFalse(labels["classification_valid"][15])  # future gap
        self.assertTrue(valid[15])  # must still receive a causal forecast
        self.assertFalse(labels["classification_valid"][28])  # exit exactly at end
        self.assertTrue(labels["classification_valid"][27])
        self.assertTrue(valid[-1])
        self.assertFalse(labels["classification_valid"][-1])
        self.assertEqual(labels["entry_row"][-1], -1)
        self.assertTrue(np.isnan(labels["target_return"][-1]))

    def test_analytic_gradient_and_optimizer_acceptance(self):
        rng = np.random.default_rng(21)
        X = rng.integers(0, 2, (83, 7)).astype(float)
        y = rng.integers(0, 2, len(X)).astype(float)
        theta = rng.normal(0, 0.3, 8)
        value, gradient = c.objective(theta, X, y, 0.07)
        estimate = []
        for i in range(len(theta)):
            delta = np.zeros_like(theta); delta[i] = 1e-6
            estimate.append((c.objective(theta+delta, X, y, 0.07)[0]-c.objective(theta-delta, X, y, 0.07)[0])/2e-6)
        np.testing.assert_allclose(gradient, estimate, atol=2e-9, rtol=2e-9)
        fitted = c.fit_model(X, y, 0.07, OPTIMIZER)
        self.assertTrue(fitted["accepted"])
        self.assertLessEqual(fitted["max_abs_gradient"], 5e-6)
        self.assertLess(fitted["objective"], value)
        with self.assertRaises(ValueError): c.fit_model(X, np.ones(len(X)), 0.07, OPTIMIZER)
        sanitized = runner.nullable_failure({"objective": float("inf"), "coefficients": [float("nan"), 0.2]})
        self.assertEqual(sanitized, {"objective": None, "coefficients": [None, 0.2]})
        json.dumps(sanitized, allow_nan=False)

    def test_future_changes_do_not_select_or_refit_on_outer_labels(self):
        original = source(100)
        changed = {**original, "ohlc": original["ohlc"].copy()}
        changed["ohlc"][65:] *= np.linspace(0.1, 4, 35)[:, None]
        def procedure(data):
            indices, ranks, up, _ = independent_ranks(data)
            valid = np.zeros(100, bool); valid[indices] = True
            train = c.phase_labels(data, valid, data["timestamps"][0], data["timestamps"][40])
            validation = c.phase_labels(data, valid, data["timestamps"][40], data["timestamps"][65])
            candidates = []
            for n in (2, 3):
                X = c.features(ranks, up, n, "G")
                for penalty in (0.1, 0.01):
                    fit = c.fit_model(X[train["binary_mask"][indices]].astype(float),
                                      (train["direction"][train["binary_mask"]] == 1).astype(float), penalty, OPTIMIZER)
                    p, z = c.predict(X[validation["binary_mask"][indices]], fit)
                    fit.update(n=n, **{"lambda": penalty}, validation_scores=c.scores(validation["direction"][validation["binary_mask"]], p, z))
                    candidates.append(fit)
            best, _ = c.select_candidate(candidates)
            refit_labels = c.phase_labels(data, valid, data["timestamps"][0], data["timestamps"][65])
            X = c.features(ranks, up, best["n"], "G")
            refitted = c.fit_model(X[refit_labels["binary_mask"][indices]],
                (refit_labels["direction"][refit_labels["binary_mask"]] == 1).astype(float), best["lambda"], OPTIMIZER)
            return best["n"], best["lambda"], c.theta(refitted), X[indices < 65]
        a, b = procedure(original), procedure(changed)
        self.assertEqual(a[:2], b[:2])
        np.testing.assert_array_equal(a[2], b[2])
        np.testing.assert_array_equal(a[3], b[3])

    def test_ties_baseline_fallback_and_pooled_null_bootstrap(self):
        candidates = [{"n": n, "lambda": lam, "accepted": True,
                       "validation_scores": {"binary_log_loss": loss}}
                      for n, lam, loss in [(3, .1, .7), (2, .01, .7+5e-13), (2, .1, .7+8e-13)]]
        self.assertEqual(c.select_candidate(candidates)[0]["lambda"], .1)
        signs, direction = np.array([-1, -1, 1]), np.array([1, -1, 1])
        baseline = c.baseline_fit(signs, direction, np.ones(3, bool))
        self.assertEqual(baseline["lag1"]["0"]["probability"], baseline["unconditional"])
        folds = [{"paired_loss_sum": np.array([.8, -.2, 0., .3]), "binary_count": np.array([4, 1, 0, 2])},
                 {"paired_loss_sum": np.array([-.5, .1, .4]), "binary_count": np.array([5, 2, 1])}]
        summary, ordinary, centered = c.bootstrap_gain(folds, 15, 2, 50, 123)
        rng = np.random.default_rng(123+15000+2)
        reference = []
        observed = sum(f["paired_loss_sum"].sum() for f in folds)/sum(f["binary_count"].sum() for f in folds)
        for _ in range(50):
            total, count = 0., 0
            for fold in folds:
                length = len(fold["binary_count"])
                starts = rng.integers(length, size=math.ceil(length/2), dtype=np.int64)
                days = [int((start+j) % length) for start in starts for j in range(2)][:length]
                total += sum(fold["paired_loss_sum"][d] for d in days)
                count += sum(fold["binary_count"][d] for d in days)
            reference.append(total/count)
        np.testing.assert_allclose(ordinary, reference, atol=1e-16)
        np.testing.assert_allclose(centered, ordinary-observed, atol=1e-16)
        self.assertEqual(summary["p_one_sided"], (1+np.count_nonzero(centered >= observed))/51)
        self.assertEqual(c.holm({"15": .01, "30": .01, "60": .03, "120": .8, "240": .9}),
                         {"15": .05, "30": .05, "60": .09, "120": 1., "240": 1.})


if __name__ == "__main__":
    unittest.main()
