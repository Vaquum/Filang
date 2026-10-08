import math
import unittest

import numpy as np

from experiments.geometry_information import common as c
from experiments.geometry_information import returns as r


class ReturnModelTests(unittest.TestCase):
    def test_gradient_finite_difference(self):
        rng = np.random.default_rng(21)
        X, y = rng.normal(size=(27, 5)), rng.normal(size=27)
        theta, penalty = rng.normal(size=6), 0.03
        _, analytic = r.ridge_objective(theta, X, y, penalty)
        numeric = []
        for column in range(len(theta)):
            step = np.zeros(len(theta)); step[column] = 1e-6
            numeric.append((r.ridge_objective(theta + step, X, y, penalty)[0]
                            - r.ridge_objective(theta - step, X, y, penalty)[0]) / 2e-6)
        np.testing.assert_allclose(analytic, numeric, atol=1e-8, rtol=1e-8)

    def test_known_optimum_and_unpenalized_intercept(self):
        X = np.array([[-1.0], [0.0], [1.0]])
        y = 3 + 2 * X[:, 0]
        fit = r.fit_ridge(X, y, 0.5, r.build_statistics(X, y), [0])
        self.assertTrue(fit["accepted"])
        self.assertAlmostEqual(fit["intercept"], 3)
        self.assertAlmostEqual(fit["coefficients"][0], (4 / 3) / (2 / 3 + 0.5))

    def test_true_zero_targets_constant_and_collinear_columns(self):
        X = np.column_stack((np.ones(12), np.arange(12) % 2, np.arange(12) % 2))
        y = np.zeros(12)
        fit = r.fit_ridge(X, y, 0.0001, r.build_statistics(X, y), [0, 1, 2])
        self.assertTrue(fit["accepted"])
        np.testing.assert_array_equal([fit["intercept"], *fit["coefficients"]], np.zeros(4))
        self.assertEqual(r.return_scores(y, r.predict(X, fit))["zero_count"], 12)

    def test_projection_matches_every_feature_and_direct_fit(self):
        rng = np.random.default_rng(9)
        ranks = np.sort(rng.integers(0, 40, size=(120, 10, 4)), axis=2).astype(np.uint8)
        up = rng.integers(0, 2, size=(120, 10)).astype(bool) & (ranks[:, :, 1] != ranks[:, :, 2])
        full = c.features(ranks, up, 10, "G").astype(float)
        y = rng.normal(0, 0.005, size=len(full)); y[::4] = 0
        stats = r.build_statistics(full, y)
        for n in (2, 3, 5, 10):
            for family in ("B", "G"):
                projection = r.feature_projection(n, family)
                X = c.features(ranks, up, n, family).astype(float)
                np.testing.assert_array_equal(full[:, projection], X)
                projected = r.fit_ridge(X, y, 0.01, stats, projection)
                direct = r.fit_ridge(X, y, 0.01, r.build_statistics(X, y), np.arange(X.shape[1]))
                self.assertTrue(projected["accepted"])
                np.testing.assert_allclose(projected["coefficients"], direct["coefficients"], atol=1e-13, rtol=1e-13)
        self.assertFalse(np.array_equal(r.feature_projection(2, "G"), np.arange(42)))

    def test_bad_statistics_fail_direct_gradient_or_factorization(self):
        X = np.array([[0.0], [1.0], [0.0], [1.0]])
        y = np.array([0.0, 0.001, 0.0, -0.001])
        stats = r.build_statistics(X, y)
        stats["xy_mean"][0] = 0.1
        fit = r.fit_ridge(X, y, 0.1, stats, [0])
        self.assertFalse(fit["accepted"])
        self.assertGreater(fit["max_abs_gradient"], 1e-10)
        stats["gram_mean"][0, 0] = -1
        fit = r.fit_ridge(X, y, 0.1, stats, [0])
        self.assertFalse(fit["accepted"])
        self.assertEqual(fit["solver"]["status"], "factorization_failure")
        self.assertIsNone(fit["solver"]["fallback"])

    def test_targets_include_zero_and_strict_cutoff_with_gap(self):
        ts = np.array([0, 60, 120, 180, 240, 420, 480, 540])
        opens = np.array([100, 100, 100, 110, 121, 80, 80, 88.0])
        source = {"timestamps": ts, "ohlc": np.column_stack([opens] * 4), "interval_seconds": 60}
        result = r.phase_targets(source, np.ones(len(ts), dtype=bool), 0, 480)
        np.testing.assert_array_equal(np.flatnonzero(result["target_valid"]), [0, 1, 2])
        self.assertEqual(result["target_log_return"][0], 0)
        self.assertEqual(result["direction"][0], 0)
        self.assertEqual(result["exit_row"][4], -1)
        self.assertTrue(np.isnan(result["target_log_return"][4]))
        self.assertTrue(result["phase_mask"][5])

    def test_model_ties_and_failed_candidate_are_exact(self):
        def row(n, penalty, score):
            return {"n": n, "lambda": penalty, "accepted": True, "validation_scores": {"mse": score}}
        candidates = [row(10, 0.1, 0.001), row(2, 0.001, 0.001 + 0.5e-12), row(2, 0.1, 0.001 + 0.8e-12)]
        selected, _ = r.select_model(candidates)
        self.assertEqual((selected["n"], selected["lambda"]), (2, 0.1))
        candidates[0]["accepted"] = False
        with self.assertRaises(ValueError):
            r.select_model(candidates)


class SignedPolicyTests(unittest.TestCase):
    def test_signed_threshold_equality_neutral_state_nan_and_reset(self):
        policy = {"id": "test", "kind": "threshold", "entry_threshold": 0.2, "exit_threshold": -0.1}
        scores = [1, 0, 0.2, -0.1, -0.10001, -0.1, 0.3, np.nan, 0.1]
        result = r.score_requests(np.arange(9), scores, start=1, end=9, policy=policy)
        np.testing.assert_array_equal(result[1:], [0, 1, 1, 0, 0, 1, 0, 0])
        self.assertTrue(np.isnan(result[0]))
        changed = scores[:6] + [-500, 800, 900]
        later = r.score_requests(np.arange(9), changed, start=1, end=9, policy=policy)
        np.testing.assert_array_equal(result[1:6], later[1:6])

    def test_policy_hurdle_and_cash_ties(self):
        grid = r.policy_grid()
        self.assertEqual(len(grid), 7)
        self.assertEqual(grid[0]["roundtrip_log_cost"], -math.log((1-.001)**2 * (1-.0002) / (1+.0002)))
        trials = [{"policy": policy, "metrics": {"net_log_return": 0, "one_way_turnover": 0}} for policy in grid]
        selected, _ = r.select_policy(trials)
        self.assertEqual(selected["policy"]["id"], "cash")
        trials[0]["metrics"]["net_log_return"] = -1
        selected, _ = r.select_policy(trials)
        self.assertEqual(selected["policy"]["id"], "e1_xm05")
        trials[1]["metrics"].update(net_log_return=0, one_way_turnover=-1)
        selected, _ = r.select_policy(trials)
        self.assertEqual(selected["policy"]["id"], "e0_xm05")

    def test_signed_ledger_matches_direct_cash_shares_with_gap_and_terminal(self):
        ts = np.array([0, 60, 120, 300, 360, 420, 480, 540, 600])
        prices = np.array([100, 105, 99, 80, 84, 82, 86, 92, 90.0])
        scores = np.array([1, -.05, .3, np.nan, .4, -.1, -.2, 1, 1])
        policy = {"id": "test", "kind": "threshold", "entry_threshold": .2, "exit_threshold": -.1}
        for fee, slip in ((0, 0), (10, 2), (20, 4)):
            ledger = r.run_score_ledger(ts, prices, scores, start=60, end=601,
                interval_seconds=60, fee_bps=fee, slippage_bps=slip, score_policy=policy)
            f, s = fee / 10000, slip / 10000
            cash, shares, prior_equity, position = 1., 0., 1., 0
            expected_positions, expected_returns = [], []
            for k, row in enumerate(range(1, len(ts))):
                desired = 0
                if k and np.isfinite(scores[row-1]):
                    desired = int(scores[row-1] >= (policy["exit_threshold"] if position else policy["entry_threshold"]))
                if row == len(ts)-1:
                    desired = 0
                if desired != position:
                    if desired:
                        shares, cash = cash * (1-f) / (prices[row] * (1+s)), 0.
                    else:
                        cash, shares = shares * prices[row] * (1-s) * (1-f), 0.
                position = desired
                equity = cash + shares * prices[row]
                expected_positions.append(position)
                expected_returns.append(math.log(equity / prior_equity))
                prior_equity = equity
            np.testing.assert_array_equal(ledger["trace"]["position_after"], expected_positions)
            np.testing.assert_allclose(ledger["trace"]["net_log_return"], expected_returns, atol=1e-14, rtol=1e-14)
            self.assertIn("signal_request", ledger["trace"])
            self.assertNotIn("signal_probability", ledger["trace"])
            self.assertIn("signal_score", ledger["trace"])
            self.assertEqual(ledger["trace"]["position_after"][0], 0)
            self.assertEqual(ledger["trace"]["position_after"][-1], 0)
            self.assertEqual(ledger["gaps"][0]["delay_seconds"], 120)

    def test_pending_gap_buy_and_nan_exit_are_delayed(self):
        ts = np.array([0, 60, 240, 300, 360])
        score = np.array([-1, 1, np.nan, np.nan, 1])
        ledger = r.run_score_ledger(ts, [100, 100, 80, 88, 88], score,
            start=0, end=361, interval_seconds=60, fee_bps=0, slippage_bps=0,
            score_policy={"id": "test", "kind": "threshold", "entry_threshold": .1, "exit_threshold": -.1})
        self.assertAlmostEqual(ledger["metrics"]["net_return"], .1)
        self.assertEqual(ledger["trades"][0]["entry_delay_seconds"], 120)
        self.assertEqual(ledger["trades"][0]["exit_row"], 3)

    def test_bootstrap_same_draws_equal_zero_day_weight_and_global_centering(self):
        folds = [{"daily_G": np.array([.1, 0, .2, 0]), "daily_B": np.array([0, 0, .1, 0])},
                 {"daily_G": np.array([0, -.1, 0]), "daily_B": np.array([0, .2, 0])}]
        summary, ordinary, centered = r.bootstrap_economics(folds, 30, 2, 23, 99)
        rng = np.random.default_rng(99 + 1000*30 + 2)
        pieces = [np.column_stack((fold["daily_G"] - fold["daily_B"], fold["daily_G"])) for fold in folds]
        observed = np.concatenate(pieces).mean(axis=0)
        expected = []
        expected_null = []
        for _ in range(23):
            values, null = [], []
            for part in pieces:
                indices = []
                for first in rng.integers(0, len(part), size=(len(part)+1)//2, dtype=np.int64):
                    indices.extend((int(first)+k) % len(part) for k in range(2))
                values.extend(part[indices[:len(part)]])
                null.extend((part-observed)[indices[:len(part)]])
            expected.append(np.asarray(values).sum(axis=0)/7)
            expected_null.append(np.asarray(null).sum(axis=0)/7)
        np.testing.assert_allclose(ordinary, expected, atol=1e-16, rtol=1e-16)
        np.testing.assert_allclose(centered, expected_null, atol=1e-16, rtol=1e-16)
        self.assertEqual(summary["comparisons"]["G_minus_cash"]["calendar_days"], 7)
        self.assertEqual(summary["intersection_union_p"], max(row["p_one_sided"] for row in summary["comparisons"].values()))


if __name__ == "__main__":
    unittest.main()
