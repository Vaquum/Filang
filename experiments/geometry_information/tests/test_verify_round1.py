"""Hand-derived and mutation tests for the independent audit, without fitting."""
import math
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


if __name__ == "__main__":
    unittest.main()
