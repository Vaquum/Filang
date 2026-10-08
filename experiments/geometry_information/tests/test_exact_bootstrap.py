"""Synthetic-only exact bootstrap tests; no market source is read."""
from fractions import Fraction
import hashlib
import json
import unittest

import numpy as np

from experiments.geometry_information import exact_bootstrap as exact


class ExactBootstrapTests(unittest.TestCase):
    def test_fraction_oracle_shared_draws_global_centering_and_complete_encoding(self):
        folds = [
            {"daily_I": np.array([0., .1, -.07]), "daily_A": np.array([.03, 0., -.01])},
            {"daily_I": np.array([0., -.2, .04, .5]), "daily_A": np.array([0., .02, 0., .49])},
        ]
        prepared = exact.prepare_exact(folds)
        summary, ordinary, centered, hits = exact.bootstrap_economics(folds, 30, 2, 47, 17, prepared=prepared)
        parts = [np.column_stack((f["daily_I"] - f["daily_A"], f["daily_I"])) for f in folds]
        rational = [[tuple(Fraction.from_float(float(x)) for x in row) for row in part] for part in parts]
        pooled = [sum((row[column] for part in rational for row in part), Fraction()) for column in range(2)]
        rng = np.random.default_rng(17 + 30000 + 2)
        expected_hits = []
        expected_mean = []
        for _ in range(47):
            totals = [Fraction(), Fraction()]
            for part in rational:
                indices = []
                for start in rng.integers(0, len(part), size=(len(part) + 1) // 2, dtype=np.int64):
                    indices.extend([(int(start) + offset) % len(part) for offset in range(2)])
                for index in indices[:len(part)]:
                    for column in range(2):
                        totals[column] += part[index][column]
            expected_hits.append([value >= 2 * pooled[column] for column, value in enumerate(totals)])
            expected_mean.append([float(value / 7) for value in totals])
        np.testing.assert_array_equal(hits, expected_hits)
        np.testing.assert_allclose(ordinary, expected_mean, atol=2e-16, rtol=2e-16)
        np.testing.assert_allclose(centered, ordinary - np.array([float(x / 7) for x in pooled]), atol=2e-16, rtol=2e-16)
        self.assertEqual(hits.dtype, np.dtype(bool))
        self.assertEqual(ordinary.dtype, np.dtype("float64"))
        json.dumps(prepared.metadata, allow_nan=False)
        for column, name in enumerate(exact.COMPARISONS):
            meta = prepared.metadata["contrasts"][name]
            self.assertEqual(Fraction(int(meta["pooled_numerator_decimal"]), 2 ** meta["denominator_exponent"]), pooled[column])
            integers = [row[column] for part in prepared.integers for row in part]
            self.assertEqual(meta["numerators_decimal"], [str(value) for value in integers])
            self.assertEqual([Fraction(int(value), 2 ** meta["denominator_exponent"])
                              for value in meta["numerators_decimal"]],
                             [row[column] for part in rational for row in part])
            encoded = "".join(str(value) + "\n" for value in integers).encode("ascii")
            self.assertEqual(meta["numerators_sha256"], hashlib.sha256(encoded).hexdigest())
            self.assertEqual(summary["comparisons"][name]["p_one_sided"], (1 + np.count_nonzero(hits[:, column])) / 48)

    def test_one_atom_negative_ties_are_all_included(self):
        lengths = [365, 366, 365, 280]
        folds = [{"daily_I": np.zeros(n), "daily_A": np.zeros(n)} for n in lengths]
        folds[1]["daily_A"][0] = .0015869036017893655
        result, _, _, hits = exact.bootstrap_economics(folds, 30, 7, 2000)
        rng = np.random.default_rng(20261008 + 30000 + 7)
        counts = []
        for _ in range(2000):
            atoms = 0
            for fold_index, days in enumerate(lengths):
                starts = rng.integers(0, days, size=(days + 6) // 7, dtype=np.int64)
                indices = ((starts[:, None] + np.arange(7)) % days).ravel()[:days]
                if fold_index == 1:
                    atoms = int(np.count_nonzero(indices == 0))
            counts.append(atoms)
        np.testing.assert_array_equal(hits[:, 0], np.asarray(counts) <= 2)
        self.assertGreater(np.count_nonzero(np.asarray(counts) == 2), 100)
        self.assertTrue(hits[np.asarray(counts) == 2, 0].all())
        self.assertTrue(hits[:, 1].all())
        self.assertEqual(result["comparisons"]["I_minus_cash"]["p_one_sided"], 1.)

    def test_one_positive_atom_uses_opposite_tail_and_includes_equality(self):
        folds = [{"daily_I": np.array([0., .1, 0., 0.]), "daily_A": np.zeros(4)}]
        result, _, _, hits = exact.bootstrap_economics(folds, 15, 1, 100, 31)
        rng = np.random.default_rng(31 + 15000 + 1)
        counts = [int(np.count_nonzero(rng.integers(0, 4, size=4, dtype=np.int64) == 1)) for _ in range(100)]
        expected = np.asarray(counts) >= 2
        self.assertTrue(np.any(np.asarray(counts) == 2))
        np.testing.assert_array_equal(hits[:, 0], expected)
        np.testing.assert_array_equal(hits[:, 1], expected)
        self.assertEqual(result["comparisons"]["I_minus_A"]["exact_tail_count"], int(expected.sum()))

    def test_zero_inputs_subnormal_and_zero_pooled_sum(self):
        smallest = np.nextafter(np.float64(0), np.float64(1))
        folds = [{"daily_I": np.array([smallest, -smallest, 0., -0.]), "daily_A": np.zeros(4)}]
        prepared = exact.prepare_exact(folds)
        self.assertEqual(prepared.metadata["contrasts"]["I_minus_A"]["denominator_exponent"], 1074)
        self.assertEqual(prepared.metadata["contrasts"]["I_minus_A"]["pooled_numerator_decimal"], "0")
        _, _, _, hits = exact.bootstrap_economics(folds, 15, 5, 30, prepared=prepared)
        np.testing.assert_array_equal(hits[:, 0], hits[:, 1])
        zero = [{"daily_I": np.zeros(9), "daily_A": np.zeros(9)}]
        summary, ordinary, centered, hits = exact.bootstrap_economics(zero, 15, 3, 20)
        self.assertTrue(hits.all())
        self.assertFalse(ordinary.any() or centered.any())
        self.assertEqual(summary["intersection_union_p"], 1.)

    def test_cache_identity_and_input_failures(self):
        folds = [{"daily_I": np.array([.1, .2, 0.]), "daily_A": np.zeros(3)}]
        prepared = exact.prepare_exact(folds)
        uncached = exact.bootstrap_economics(folds, 60, 2, 13)
        cached = exact.bootstrap_economics(folds, 60, 2, 13, prepared=prepared)
        self.assertEqual(uncached[0], cached[0])
        for one, two in zip(uncached[1:], cached[1:]):
            np.testing.assert_array_equal(one, two)
        folds[0]["daily_I"][0] = .3
        with self.assertRaisesRegex(ValueError, "cached exact encoding"):
            exact.bootstrap_economics(folds, 60, 2, 13, prepared=prepared)
        for bad in ([], [{"daily_I": [np.nan], "daily_A": [0.]}], [{"daily_I": [], "daily_A": []}],
                    [{"daily_I": [1., 2.], "daily_A": [1.]}]):
            with self.assertRaises(ValueError):
                exact.prepare_exact(bad)
        for bad in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                exact.bootstrap_economics(folds, 60, bad, 13)
        for bad in (-1, 1.5, True, np.bool_(True)):
            with self.assertRaises(ValueError):
                exact.bootstrap_economics(folds, 60, 2, 13, bad)


if __name__ == "__main__":
    unittest.main()
