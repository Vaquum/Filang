"""Exhaustive qualitative-state tests; no market rows or model fits."""
import itertools
import hashlib
import json
from pathlib import Path
import unittest
from collections import Counter

import numpy as np

from experiments.geometry_information import common, interactions as i


def independent_states():
    """Every pair of ordered four-endpoint chains on their occupied levels.

    Any valid pair has at most eight distinct prices. Relabelling its sorted
    distinct prices 0..q-1 gives exactly one generated state. Conversely every
    generated pair is realizable by positive prices rank+1. Body directions
    have two choices for each positive-width body and exactly one when flat.
    This is independent of the production four-endpoint interval catalogue.
    """
    states = []
    for q in range(1, 9):
        chains = list(itertools.combinations_with_replacement(range(q), 4))
        for current in chains:
            for previous in chains:
                if set(current + previous) != set(range(q)):
                    continue
                current_directions = (0,) if current[1] == current[2] else (-1, 1)
                previous_directions = (0,) if previous[1] == previous[2] else (-1, 1)
                for d0 in current_directions:
                    for d1 in previous_directions:
                        states.append((current, previous, d0, d1))
    return states


def independent_key(state, endpoints):
    current, previous, d0, d1 = state
    values = tuple(current[e] for e in endpoints) + tuple(previous[e] for e in endpoints)
    order = sorted(set(values))
    return (d0, d1, *(order.index(value) for value in values))


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = independent_states()
        cls.ranks = np.asarray([(a, b) for a, b, _, _ in cls.states], dtype=np.uint8)
        cls.up = np.asarray([(da > 0, db > 0) for _, _, da, db in cls.states], dtype=bool)

    def test_exact_reachable_catalogues_from_all_7452_oriented_states(self):
        self.assertEqual(len(self.states), 7452)
        self.assertEqual(len(set(self.states)), 7452)
        body = sorted({independent_key(state, (1, 2)) for state in self.states})
        ranges = sorted({independent_key(state, (0, 3)) for state in self.states})
        self.assertEqual(tuple(body), i.BODY_CATALOGUE)
        self.assertEqual(tuple(ranges), i.RANGE_CATALOGUE)
        self.assertEqual((len(body), len(ranges)), (75, 150))
        self.assertEqual(len({key[2:] for key in body}), 26)
        self.assertEqual(len({key[2:] for key in ranges}), 26)
        body_counts, range_counts = Counter(k[:2] for k in body), Counter(k[:2] for k in ranges)
        for directions in itertools.product((-1, 0, 1), repeat=2):
            flats = directions.count(0)
            self.assertEqual(body_counts[directions], (13, 5, 3)[flats])
            self.assertEqual(range_counts[directions], (13, 18, 26)[flats])
        # An unfiltered 26x9 catalogue would contain these impossible entries.
        self.assertEqual((26 * 9 - len(body), 26 * 9 - len(ranges)), (159, 84))

    def test_every_state_has_exactly_two_correct_active_columns(self):
        body = sorted({independent_key(state, (1, 2)) for state in self.states})
        ranges = sorted({independent_key(state, (0, 3)) for state in self.states})
        body_ids = {key: position for position, key in enumerate(body)}
        range_ids = {key: position + len(body) for position, key in enumerate(ranges)}
        expected = np.asarray([(body_ids[independent_key(state, (1, 2))],
                                range_ids[independent_key(state, (0, 3))]) for state in self.states], dtype=np.int16)
        indices = i.interaction_indices(self.ranks, self.up)
        np.testing.assert_array_equal(indices, expected)
        features = i.interaction_features(self.ranks, self.up)
        self.assertEqual(features.dtype, np.uint8)
        self.assertEqual(features.shape, (7452, 225))
        self.assertTrue(features.flags.c_contiguous)
        np.testing.assert_array_equal(features.sum(axis=1), np.full(7452, 2))
        np.testing.assert_array_equal(features[:, :75].sum(axis=1), np.ones(7452))
        np.testing.assert_array_equal(features[:, 75:].sum(axis=1), np.ones(7452))
        self.assertTrue(np.all(features.sum(axis=0) > 0))  # No vacuous catalogue column.
        self.assertTrue(np.all(features[np.arange(7452)[:, None], expected] == 1))

    def test_global_rank_gaps_are_locally_canonicalized_without_thresholds(self):
        remapping = np.array([0, 3, 7, 12, 18, 25, 31, 39], dtype=np.uint8)
        mapped = remapping[self.ranks]
        np.testing.assert_array_equal(i.interaction_indices(mapped, self.up), i.interaction_indices(self.ranks, self.up))
        # Same-body directions can coexist with either flat or nonflat ranges.
        flat_body = np.array([[[0, 1, 1, 3], [0, 2, 2, 3]], [[1, 1, 1, 1], [2, 2, 2, 2]]], dtype=np.uint8)
        zero_up = np.zeros((2, 2), dtype=bool)
        indices = i.interaction_indices(flat_body, zero_up)
        self.assertNotEqual(indices[0, 1], indices[1, 1])

    def test_additive_basis_unchanged_and_exact_name_projection_for_all_histories(self):
        ranks = np.repeat(self.ranks[:32, :1], 10, axis=1)
        up = np.repeat(self.up[:32, :1], 10, axis=1)
        ranks[:, :2], up[:, :2] = self.ranks[:32], self.up[:32]
        # Include maximal distinct native ranks, so projection has skipped
        # global levels and distinct longer-history endpoint relations.
        ranks = np.concatenate((ranks, np.arange(40, dtype=np.uint8).reshape(1, 10, 4)))
        up = np.concatenate((up, (np.arange(10) % 2 == 0)[None, :]))
        full = i.features(ranks, up, 10, "I")
        expected_dims = {2: (42, 267), 3: (80, 305), 5: (156, 381), 10: (346, 571)}
        for n, (a_width, i_width) in expected_dims.items():
            for family, width in (("A", a_width), ("I", i_width)):
                with self.subTest(n=n, family=family):
                    direct = i.features(ranks, up, n, family)
                    self.assertEqual(direct.shape[1], width)
                    self.assertEqual(len(i.feature_names(n, family)), width)
                    np.testing.assert_array_equal(full[:, i.feature_projection(n, family)], direct)
            np.testing.assert_array_equal(i.features(ranks, up, n, "A"), common.features(ranks, up, n, "G"))
            self.assertEqual(i.feature_names(n, "A"), common.feature_names(n, "G"))
        self.assertEqual(len(set(i.feature_names(10, "I"))), 571)

    def test_interaction_block_never_uses_older_lags_and_keeps_all_unseen_columns(self):
        ranks = np.repeat(self.ranks[-10:, :1], 10, axis=1)
        up = np.repeat(self.up[-10:, :1], 10, axis=1)
        ranks[:, :2], up[:, :2] = self.ranks[-10:], self.up[-10:]
        before = i.interaction_features(ranks, up)
        ranks[:, 2:] = np.array([0, 5, 10, 20], dtype=np.uint8)
        up[:, 2:] = True
        np.testing.assert_array_equal(before, i.interaction_features(ranks, up))
        self.assertEqual(i.features(ranks[:1], up[:1], 2, "I").shape, (1, 267))
        self.assertEqual(len(i.INTERACTION_NAMES), 225)
        self.assertGreater(np.count_nonzero(before.sum(axis=0) == 0), 0)
        empty = i.interaction_features(np.empty((0, 10, 4), np.uint8), np.empty((0, 10), bool))
        self.assertEqual(empty.shape, (0, 225))

    def test_stable_catalogue_records_and_shared_direction_spans_are_explicit(self):
        records = i.catalogue_records()
        retained = Path(i.__file__).with_name("round3_catalogue.json").read_bytes()
        self.assertEqual(retained, i.catalogue_bytes())
        self.assertEqual(hashlib.sha256(retained).hexdigest(), i.catalogue_sha256())
        self.assertEqual(json.loads(retained), {"version": i.CATALOGUE_VERSION, "records": records})
        self.assertEqual([r["index"] for r in records], list(range(225)))
        self.assertEqual([r["name"] for r in records], list(i.INTERACTION_NAMES))
        self.assertEqual(records[0]["block"], "body")
        self.assertEqual(records[75]["block"], "range")
        self.assertEqual(i.BODY_CATALOGUE, tuple(sorted(i.BODY_CATALOGUE)))
        self.assertEqual(i.RANGE_CATALOGUE, tuple(sorted(i.RANGE_CATALOGUE)))
        self.assertEqual(len(i.catalogue_sha256()), 64)
        features = i.interaction_features(self.ranks, self.up)
        for directions in itertools.product((-1, 0, 1), repeat=2):
            body_columns = [r["index"] for r in records if r["block"] == "body" and tuple(r["directions"]) == directions]
            range_columns = [r["index"] for r in records if r["block"] == "range" and tuple(r["directions"]) == directions]
            expected = np.array([(da, db) == directions for _, _, da, db in self.states], dtype=np.uint8)
            np.testing.assert_array_equal(features[:, body_columns].sum(axis=1), expected)
            np.testing.assert_array_equal(features[:, range_columns].sum(axis=1), expected)

    def test_invalid_native_states_are_rejected(self):
        valid = np.array([[[0, 1, 2, 3], [1, 2, 3, 4]]], dtype=np.uint8)
        up = np.array([[True, False]])
        for bad in (valid.astype(float), valid[:, :1], valid[:, :, :3], valid[:, :, ::-1]):
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                i.interaction_indices(bad, up)
        with self.assertRaises(ValueError):
            i.interaction_indices(valid, up.astype(np.uint8))
        flat = valid.copy(); flat[0, 0, 2] = flat[0, 0, 1]
        with self.assertRaisesRegex(ValueError, "flat body"):
            i.interaction_indices(flat, up)
        with self.assertRaises(ValueError):
            i.feature_names(4, "I")
        with self.assertRaises(ValueError):
            i.feature_names(2, "B")


if __name__ == "__main__":
    unittest.main()
