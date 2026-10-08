import unittest

import numpy as np
from threadpoolctl import threadpool_limits

from experiments.geometry_information import interactions as i
from experiments.geometry_information import interaction_returns as ir
from experiments.geometry_information import returns as r


class InteractionStatisticsTests(unittest.TestCase):
    def fixture(self, count=113):
        rng = np.random.default_rng(314)
        ranks = np.sort(rng.integers(0, 40, (count, 10, 4)), axis=2).astype(np.uint8)
        up = rng.integers(0, 2, (count, 10)).astype(bool) & (ranks[:, :, 1] != ranks[:, :, 2])
        y = rng.normal(0, .003, count)
        y[::7] = 0
        return ranks, up, y

    def test_sparse_statistics_equal_direct_complete_binary_matrix(self):
        ranks, up, y = self.fixture()
        additive, full = i.features(ranks, up, 10, "A"), i.features(ranks, up, 10, "I")
        with threadpool_limits(limits=1):
            sparse = ir.build_statistics(additive, i.interaction_indices(ranks, up), y)
            dense = r.build_statistics(full, y)
        self.assertEqual(sparse["count"], len(y))
        self.assertEqual(sparse["gram_mean"].shape, (571, 571))
        for name in ("x_mean", "gram_mean", "xy_mean", "y_mean", "y2_mean"):
            np.testing.assert_allclose(sparse[name], dense[name], atol=2e-17, rtol=2e-14)
        np.testing.assert_array_equal(sparse["gram_mean"], sparse["gram_mean"].T)
        self.assertTrue(np.any(np.diag(sparse["gram_mean"])[346:] == 0))
        self.assertTrue(np.any(y == 0))

    def test_named_projection_matches_direct_ridge_for_all_histories_and_families(self):
        ranks, up, y = self.fixture(79)
        full = i.features(ranks, up, 10, "I")
        with threadpool_limits(limits=1):
            statistics = ir.build_statistics(i.features(ranks, up, 10, "A"), i.interaction_indices(ranks, up), y)
            for history in (2, 3, 5, 10):
                for family in ("A", "I"):
                    projection = i.feature_projection(history, family)
                    matrix = i.features(ranks, up, history, family).astype(np.float64)
                    np.testing.assert_array_equal(full[:, projection], matrix)
                    for penalty in (.1, .0001):
                        projected = r.fit_ridge(matrix, y, penalty, statistics, projection)
                        dense = r.fit_ridge(matrix, y, penalty, r.build_statistics(matrix, y), np.arange(matrix.shape[1]))
                        self.assertTrue(projected["accepted"])
                        self.assertTrue(dense["accepted"])
                        self.assertLessEqual(projected["max_abs_gradient"], 1e-10)
                        np.testing.assert_allclose([projected["intercept"], *projected["coefficients"]],
                                                   [dense["intercept"], *dense["coefficients"]],
                                                   atol=2e-13, rtol=2e-11)
        self.assertFalse(np.array_equal(i.feature_projection(2, "A"), np.arange(42)))
        self.assertEqual(len(i.feature_projection(10, "I")), 571)

    def test_repeated_binary_counts_do_not_overflow_uint8_and_zero_targets_are_retained(self):
        count = 1025
        additive = np.column_stack((np.ones(count, dtype=np.uint8), np.arange(count, dtype=np.int64) % 2)).astype(np.uint8)
        ids = np.tile([74, 224], (count, 1)).astype(np.int16)
        statistics = ir.build_statistics(additive, ids, np.zeros(count))
        self.assertEqual(statistics["count"], count)
        for column in (0, 2 + 74, 2 + 224):
            self.assertEqual(statistics["x_mean"][column], 1)
            self.assertEqual(statistics["gram_mean"][column, column], 1)
        self.assertEqual(statistics["gram_mean"][2 + 74, 2 + 224], 1)
        np.testing.assert_array_equal(statistics["xy_mean"], np.zeros(227))

    def test_wrong_statistics_still_fail_direct_candidate_acceptance(self):
        ranks, up, y = self.fixture(67)
        with threadpool_limits(limits=1):
            statistics = ir.build_statistics(i.features(ranks, up, 10, "A"), i.interaction_indices(ranks, up), y)
            matrix = i.features(ranks, up, 2, "I").astype(np.float64)
            projection = i.feature_projection(2, "I")
            statistics["xy_mean"][projection[-1]] += .1
            fit = r.fit_ridge(matrix, y, .1, statistics, projection)
        self.assertFalse(fit["accepted"])
        self.assertGreater(fit["max_abs_gradient"], 1e-10)
        self.assertIsNone(fit["solver"]["fallback"])
        self.assertEqual(fit["solver"]["jitter"], 0)

    def test_malformed_sparse_samples_fail_closed(self):
        additive = np.ones((3, 2), dtype=np.uint8)
        ids = np.array([[0, 75], [1, 76], [2, 77]], dtype=np.int16)
        y = np.zeros(3)
        malformed = [
            (additive, ids[:, :1], y),
            (additive, ids.astype(float), y),
            (additive, np.array([[0, 74], [1, 76], [2, 77]]), y),
            (additive, np.array([[75, 75], [1, 76], [2, 77]]), y),
            (additive, np.array([[0, 225], [1, 76], [2, 77]]), y),
            (additive, np.array([[-1, 75], [1, 76], [2, 77]]), y),
            (additive * 2, ids, y),
            (additive, ids, np.array([0, np.nan, 0])),
            (additive[:0], ids[:0], y[:0]),
            (additive, ids, y[:2]),
            (additive.astype(complex), ids, y),
        ]
        for args in malformed:
            with self.subTest(shapes=[np.shape(arg) for arg in args]):
                with self.assertRaises(ValueError):
                    ir.build_statistics(*args)


if __name__ == "__main__":
    unittest.main()
