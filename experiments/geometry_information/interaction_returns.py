"""Exact binary sufficient statistics for the fixed R3 interaction basis.

The full design is [A10, H]. A10 is the unchanged binary additive geometry
basis; H has one active body column and one active range column per row. Build
the A10 Gram with float64 BLAS and its H cross-product with a sparse product.
Build the H Gram from integer category counts, then evaluate every retained
normal statistic in float64. A dense N-by-225 interaction matrix is unnecessary
for this construction. Direct ridge acceptance still uses the original dense
candidate matrix through the unchanged returns.fit_ridge implementation.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix

try:
    from . import common as c
except ImportError:
    import common as c


BODY_COLUMNS = 75
RANGE_COLUMNS = 150
INTERACTION_COLUMNS = BODY_COLUMNS + RANGE_COLUMNS
STATISTICS_METHOD = "float64_additive_gram_sparse_cross_and_int64_interaction_counts"


def build_statistics(additive, interaction_indices, y):
    """Return the complete [A10,H] mean/Gram/cross-products for one exact sample.

    Inputs must have the same row order. Interaction indices use the catalogue's
    global IDs: body 0..74 and range 75..224. Each row therefore has exactly two
    ones, with no duplicate category. Integer accumulation never uses the uint8
    feature dtype. The maximum admitted row count also keeps binary counts
    exactly representable as float64 before normalization.
    """
    raw_a, raw_y = np.asarray(additive), np.asarray(y)
    indices = np.asarray(interaction_indices)
    c.require(raw_a.dtype.kind in "biuf" and raw_y.dtype.kind in "biuf",
              "real numeric additive features and targets required")
    c.require(raw_a.ndim == 2 and raw_a.shape[1] > 0 and raw_y.shape == (len(raw_a),)
              and 0 < len(raw_a) <= 2**53, "aligned nonempty interaction fitting sample")
    c.require(indices.shape == (len(raw_a), 2) and indices.dtype.kind in "iu",
              "two integer interaction indices per fitting row required")
    c.require(np.all((indices[:, 0] >= 0) & (indices[:, 0] < BODY_COLUMNS))
              and np.all((indices[:, 1] >= BODY_COLUMNS) & (indices[:, 1] < INTERACTION_COLUMNS)),
              "one body and one range interaction index required")
    a, y = np.asarray(raw_a, dtype=np.float64), np.asarray(raw_y, dtype=np.float64)
    c.require(np.isfinite(a).all() and np.isfinite(y).all(), "finite interaction fitting sample")
    c.require(np.all((a == 0) | (a == 1)), "binary additive geometry features required")
    count, dimension = a.shape
    ids = np.asarray(indices, dtype=np.int64)
    sparse = csr_matrix((np.ones(2 * count, dtype=np.float64), ids.ravel(),
                         np.arange(0, 2 * count + 1, 2, dtype=np.int64)),
                        shape=(count, INTERACTION_COLUMNS))
    category_count = np.bincount(ids.ravel(), minlength=INTERACTION_COLUMNS)
    pair_id = ids[:, 0] * RANGE_COLUMNS + ids[:, 1] - BODY_COLUMNS
    pair_count = np.bincount(pair_id, minlength=BODY_COLUMNS * RANGE_COLUMNS).reshape(BODY_COLUMNS, RANGE_COLUMNS)

    gram = np.empty((dimension + INTERACTION_COLUMNS,) * 2, dtype=np.float64)
    gram[:dimension, :dimension] = a.T @ a / count
    cross = np.asarray(sparse.T @ a) / count
    gram[dimension:, :dimension], gram[:dimension, dimension:] = cross, cross.T
    interaction_gram = gram[dimension:, dimension:]
    interaction_gram.fill(0)
    interaction_gram[np.diag_indices(INTERACTION_COLUMNS)] = category_count / count
    interaction_gram[:BODY_COLUMNS, BODY_COLUMNS:] = pair_count / count
    interaction_gram[BODY_COLUMNS:, :BODY_COLUMNS] = pair_count.T / count
    result = {"count": count,
        "x_mean": np.concatenate((a.mean(axis=0), category_count / count)),
        "gram_mean": gram,
        "xy_mean": np.concatenate((a.T @ y / count, np.asarray(sparse.T @ y) / count)),
        "y_mean": float(y.mean()), "y2_mean": float(y @ y / count)}
    c.require(all(np.isfinite(result[name]).all() for name in
                  ("x_mean", "gram_mean", "xy_mean", "y_mean", "y2_mean")),
              "finite complete interaction normal statistics required")
    return result
