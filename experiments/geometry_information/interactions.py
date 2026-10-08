"""Fixed current/previous interval interactions for the proposed R3 family.

This module contains no market vocabulary discovery, model fitting or scoring.
A is exactly the R2 additive G feature basis. I appends two complete one-hot
groups for candles 0 and 1 only: body interval weak order conditioned on both
body directions (75 columns), and full-range weak order conditioned on the
same directions (150 columns). Larger histories add only the existing additive
features. Every row activates one body column and one full-range column.

Four interval endpoints have 26 canonical weak orders: 13 with both intervals
proper, five point/proper, five proper/point and three point/point. For body
intervals, direction zero is equivalent to being a point, giving
4*13 + 4*5 + 3 = 75. A full-range point forces direction zero, but a flat body
may have a proper range; its count is 4*13 + 4*(13+5) + 26 = 150.

All reachable columns remain even if their fitting support is zero. The full
one-hot basis is deliberately redundant with the intercept and parts of A.
Positive ridge penalties make its coefficients unique, but this representation
changes shrinkage along overlapping spans. A comparison therefore evaluates
the complete declared richer pipeline, not a capacity-matched or wick-specific
effect. No extra direction-pair block or body-by-range crossing is present.
"""
from __future__ import annotations

import hashlib
import itertools
import json

import numpy as np

try:
    from . import common
except ImportError:
    import common


HISTORIES = (2, 3, 5, 10)
DIRECTIONS = (-1, 0, 1)
CATALOGUE_VERSION = "filang-interval-interactions-v1"


def _interval_orders():
    """Enumerate four-endpoint order types, not observed price configurations."""
    return tuple(ranks for ranks in itertools.product(range(4), repeat=4)
                 if ranks[0] <= ranks[1] and ranks[2] <= ranks[3]
                 and set(ranks) == set(range(max(ranks) + 1)))


INTERVAL_ORDERS = _interval_orders()
BODY_CATALOGUE = tuple((d0, d1, *ranks)
    for d0 in DIRECTIONS for d1 in DIRECTIONS for ranks in INTERVAL_ORDERS
    if (d0 == 0) == (ranks[0] == ranks[1]) and (d1 == 0) == (ranks[2] == ranks[3]))
RANGE_CATALOGUE = tuple((d0, d1, *ranks)
    for d0 in DIRECTIONS for d1 in DIRECTIONS for ranks in INTERVAL_ORDERS
    if (ranks[0] != ranks[1] or d0 == 0) and (ranks[2] != ranks[3] or d1 == 0))
common.require((len(INTERVAL_ORDERS), len(BODY_CATALOGUE), len(RANGE_CATALOGUE)) == (26, 75, 150),
               "fixed interval interaction catalogue cardinality")


def _column_name(block, key):
    d0, d1, *ranks = key
    return f"interaction.{block}[0,1].directions({d0},{d1}).ranks({','.join(map(str, ranks))})"


INTERACTION_NAMES = tuple(_column_name(block, key)
    for block, catalogue in (("body", BODY_CATALOGUE), ("range", RANGE_CATALOGUE)) for key in catalogue)


def catalogue_records():
    """Stable body-first, then range, lexicographic direction/rank records."""
    records = []
    for block, catalogue in (("body", BODY_CATALOGUE), ("range", RANGE_CATALOGUE)):
        for local_index, key in enumerate(catalogue):
            index = len(records)
            records.append({"index": index, "block": block, "local_index": local_index,
                "directions": list(key[:2]), "ranks": list(key[2:]), "name": INTERACTION_NAMES[index]})
    return records


def catalogue_bytes():
    """Canonical UTF-8 JSON bytes, sorted keys/compact separators, no newline."""
    payload = {"version": CATALOGUE_VERSION, "records": catalogue_records()}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def catalogue_sha256():
    return hashlib.sha256(catalogue_bytes()).hexdigest()


def _lookup(catalogue, offset):
    table = np.full((9, 256), -1, dtype=np.int16)
    for index, (d0, d1, a, b, c, d) in enumerate(catalogue):
        table[(d0 + 1) * 3 + d1 + 1, 64 * a + 16 * b + 4 * c + d] = index + offset
    table.flags.writeable = False
    return table


_BODY_LOOKUP = _lookup(BODY_CATALOGUE, 0)
_RANGE_LOOKUP = _lookup(RANGE_CATALOGUE, len(BODY_CATALOGUE))


def _canonical_codes(endpoints):
    """Compress four global ranks to dense local ranks, preserving exact ties."""
    ordered = np.sort(endpoints, axis=1)
    first = np.ones_like(ordered, dtype=bool)
    first[:, 1:] = ordered[:, 1:] != ordered[:, :-1]
    ranks = np.sum((ordered[:, None, :] < endpoints[:, :, None]) & first[:, None, :], axis=2, dtype=np.int16)
    return ranks @ np.array([64, 16, 4, 1], dtype=np.int16)


def interaction_indices(ranks, up):
    """Return N×2 int16 global one-hot column indices, using only lags 0/1.

    Inputs are already decoded native rank/up arrays. Unused price levels may
    occur between selected endpoints; their removal is local canonicalization,
    never numerical normalization learned from fitting or future data.
    """
    r, u = np.asarray(ranks), np.asarray(up)
    common.require(r.ndim == 3 and r.shape[1] >= 2 and r.shape[2] == 4 and r.dtype.kind in "iu",
                   "interval interactions require integer endpoint rank arrays")
    common.require(u.shape == r.shape[:2] and u.dtype.kind == "b", "interval interactions require matching boolean up flags")
    r, u = r[:, :2], u[:, :2]
    common.require(np.all((r >= 0) & (r < 40)) and np.all(r[:, :, 1:] >= r[:, :, :-1]),
                   "interval interactions require valid native candle rank order")
    flat = r[:, :, 1] == r[:, :, 2]
    common.require(not np.any(flat & u), "flat body cannot carry an up flag")
    directions = np.where(flat, 0, np.where(u, 1, -1)).astype(np.int16)
    direction_index = (directions[:, 0] + 1) * 3 + directions[:, 1] + 1
    body = r[:, :, 1:3].reshape(-1, 4)
    ranges = r[:, :, (0, 3)].reshape(-1, 4)
    body_indices = _BODY_LOOKUP[direction_index, _canonical_codes(body)]
    range_indices = _RANGE_LOOKUP[direction_index, _canonical_codes(ranges)]
    common.require(np.all(body_indices >= 0) and np.all(range_indices >= 0), "unreachable interval interaction key")
    return np.ascontiguousarray(np.column_stack((body_indices, range_indices)), dtype=np.int16)


def interaction_features(ranks, up):
    """Dense uint8 block for Gram construction; two nonzero entries per row."""
    indices = interaction_indices(ranks, up)
    result = np.zeros((len(indices), len(INTERACTION_NAMES)), dtype=np.uint8)
    result[np.arange(len(indices))[:, None], indices] = 1
    return result


def feature_names(n, family):
    common.require(n in HISTORIES and family in ("A", "I"), "R3 history/family")
    names = common.feature_names(n, "G")
    return names if family == "A" else names + list(INTERACTION_NAMES)


def features(ranks, up, n, family):
    """A is byte-for-byte the existing additive basis; I appends the fixed block."""
    names = feature_names(n, family)
    common.require(ranks.shape[1] >= n, "R3 history exceeds supplied native ranks")
    additive = common.features(ranks, up, n, "G")
    result = additive if family == "A" else np.column_stack((additive, interaction_features(ranks, up)))
    common.require(result.shape[1] == len(names), "R3 feature dimension")
    return np.ascontiguousarray(result, dtype=np.uint8)


def feature_projection(n, family):
    """Project a declared candidate from I10 by exact column name, not prefix."""
    lookup = {name: i for i, name in enumerate(feature_names(10, "I"))}
    return np.array([lookup[name] for name in feature_names(n, family)], dtype=np.int64)
