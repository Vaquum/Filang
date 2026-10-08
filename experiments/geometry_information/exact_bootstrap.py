"""Paired daily bootstrap with exact tail decisions for binary64 contrasts.

This draft R3 helper does not import R2 producer or verifier computations. Float
replicas describe the resampled effects and their percentile intervals. Tail
decisions instead interpret each supplied binary64 daily contrast as an exact
binary rational. With N fixed by stratification, the centered one-sided event
is T >= 2*S, where S is the original sum and T is the resampled sum. Thus exact
equality is included without padding, rounding, or floating-point centering.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import operator

import numpy as np


COMPARISONS = ("I_minus_A", "I_minus_cash")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _array_sha(array):
    return hashlib.sha256(np.ascontiguousarray(array, dtype="<f8").tobytes()).hexdigest()


def _json_sha(value):
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _parts(folds):
    _require(bool(folds), "at least one complete calendar fold is required")
    result = []
    for fold in folds:
        interaction = np.asarray(fold["daily_I"], dtype=np.float64)
        additive = np.asarray(fold["daily_A"], dtype=np.float64)
        _require(interaction.ndim == 1 and interaction.shape == additive.shape and len(interaction) > 0,
                 "paired nonempty one-dimensional daily folds are required")
        _require(np.isfinite(interaction).all() and np.isfinite(additive).all(), "finite daily accounts required")
        with np.errstate(over="ignore", invalid="ignore"):
            part = np.column_stack((interaction - additive, interaction)).astype(np.float64)
        _require(np.isfinite(part).all(), "finite binary64 daily contrasts required")
        part.setflags(write=False)
        result.append(part)
    return tuple(result)


@dataclass(frozen=True)
class ExactInput:
    """In-memory cache; only ``metadata`` belongs in a JSON artifact.

    ``integers`` contains Python arbitrary-precision integers in NumPy object
    arrays solely for exact dot products. Never serialize these arrays to NPZ.
    The complete integer vectors are retained as decimal strings and bound by
    decimal-line SHA-256 hashes in ``metadata``.
    """

    parts: tuple
    integers: tuple
    pooled_sums: tuple
    metadata: dict


def prepare_exact(folds):
    """Encode the two paired contrasts on common power-of-two denominators.

    Fold order and within-fold calendar-day order are retained. An encoded
    integer q with denominator exponent e denotes exactly q / 2**e. Hash input
    for a numerator vector is each signed base-10 integer followed by LF, in
    concatenated fold order; zero is spelled ``0``.
    """
    parts = _parts(folds)
    lengths = [len(part) for part in parts]
    joined = np.concatenate(parts)
    integer_columns, columns, pooled_sums = [], {}, []
    for index, name in enumerate(COMPARISONS):
        ratios = [float(value).as_integer_ratio() for value in joined[:, index]]
        exponent = max(denominator.bit_length() - 1 for _, denominator in ratios)
        integers = [numerator << (exponent - (denominator.bit_length() - 1))
                    for numerator, denominator in ratios]
        pooled = sum(integers)
        integer_columns.append(integers)
        pooled_sums.append(pooled)
        encoded = "".join(str(value) + "\n" for value in integers).encode("ascii")
        columns[name] = {
            "denominator_exponent": exponent,
            "pooled_numerator_decimal": str(pooled),
            "numerators_decimal": [str(value) for value in integers],
            "numerators_sha256": hashlib.sha256(encoded).hexdigest(),
            "binary64_contrasts_sha256": _array_sha(joined[:, index]),
            "nonzero_days": int(np.count_nonzero(joined[:, index])),
        }
    integer_matrix = np.column_stack([np.asarray(column, dtype=object) for column in integer_columns])
    integer_parts, offset = [], 0
    for length in lengths:
        part = integer_matrix[offset:offset + length]
        part.setflags(write=False)
        integer_parts.append(part)
        offset += length
    metadata = {
        "schema": "filang-exact-bootstrap-input-v1",
        "comparison_order": list(COMPARISONS),
        "fold_lengths": lengths,
        "calendar_days": sum(lengths),
        "fold_binary64_sha256": [_array_sha(part) for part in parts],
        "integer_encoding": "signed decimal integer plus LF per day; concatenated fold order",
        "value_definition": "numerator / 2**denominator_exponent; supplied binary64 contrasts interpreted exactly",
        "tail_event": "resampled_numerator_sum >= 2 * pooled_numerator_sum",
        "contrasts": columns,
    }
    metadata["encoding_sha256"] = _json_sha(metadata)
    return ExactInput(parts, tuple(integer_parts), tuple(pooled_sums), metadata)


def _positive_integer(value, name):
    _require(not isinstance(value, (bool, np.bool_)), name + " must be a positive integer")
    try:
        result = operator.index(value)
    except TypeError as error:
        raise ValueError(name + " must be a positive integer") from error
    _require(result > 0, name + " must be a positive integer")
    return result


def bootstrap_economics(folds, minutes, block_days, replicates=2000, base_seed=20261008, *, prepared=None):
    """Return summary, ordinary, centered, and exact-hit arrays.

    The first two arrays are float64[replicates, 2]; exact hits are bool with the
    same shape. Draw order is replicate, then supplied outer-fold order; each
    fold draws ceil(days/block_days) int64 circular-block starts and truncates
    to its original length. Both contrasts share all draws. ``prepared`` may
    cache the integer encoding across block sensitivities; its input binding
    is checked on every call.
    """
    minutes = _positive_integer(minutes, "minutes")
    block_days = _positive_integer(block_days, "block_days")
    replicates = _positive_integer(replicates, "replicates")
    _require(not isinstance(base_seed, (bool, np.bool_)), "base_seed must be a nonnegative integer")
    try:
        base_seed = operator.index(base_seed)
    except TypeError as error:
        raise ValueError("base_seed must be an integer") from error
    _require(base_seed >= 0, "base_seed must be a nonnegative integer")
    if prepared is None:
        prepared = prepare_exact(folds)
    else:
        _require(isinstance(prepared, ExactInput), "prepared input must be an ExactInput")
        supplied = _parts(folds)
        _require([len(part) for part in supplied] == prepared.metadata["fold_lengths"] and
                 [_array_sha(part) for part in supplied] == prepared.metadata["fold_binary64_sha256"],
                 "cached exact encoding does not match the supplied ordered daily contrasts")
    parts = prepared.parts
    count = prepared.metadata["calendar_days"]
    observed = sum((part.sum(axis=0) for part in parts), np.zeros(2)) / count
    seed = base_seed + 1000 * minutes + block_days
    rng = np.random.default_rng(seed)
    ordinary = np.empty((replicates, 2), dtype=np.float64)
    centered = np.empty_like(ordinary)
    hits = np.empty((replicates, 2), dtype=bool)
    twice_original = tuple(2 * value for value in prepared.pooled_sums)
    for replicate in range(replicates):
        total, null_total = np.zeros(2), np.zeros(2)
        exact_total = [0, 0]
        for part, integer_part in zip(parts, prepared.integers):
            days = len(part)
            starts = rng.integers(0, days, size=(days + block_days - 1) // block_days, dtype=np.int64)
            indices = ((starts[:, None] + np.arange(block_days)) % days).ravel()[:days]
            total += part[indices].sum(axis=0)
            null_total += (part - observed)[indices].sum(axis=0)
            multiplicities = np.bincount(indices, minlength=days)
            weighted = multiplicities @ integer_part
            exact_total[0] += weighted[0]
            exact_total[1] += weighted[1]
        ordinary[replicate], centered[replicate] = total / count, null_total / count
        hits[replicate] = [exact_total[index] >= twice_original[index] for index in range(2)]
    _require(np.isfinite(observed).all() and np.isfinite(ordinary).all() and np.isfinite(centered).all(),
             "finite floating bootstrap estimates required")
    ci = np.quantile(ordinary, [0.025, 0.975], axis=0, method="linear")
    comparisons = {}
    for index, name in enumerate(COMPARISONS):
        tail_count = int(np.count_nonzero(hits[:, index]))
        comparisons[name] = {
            "mean_daily_net_log_gain": float(observed[index]),
            "total_net_log_gain": float(observed[index] * count),
            "calendar_days": count,
            "ci95_low": float(ci[0, index]),
            "ci95_high": float(ci[1, index]),
            "exact_tail_count": tail_count,
            "p_one_sided": (1 + tail_count) / (replicates + 1),
        }
    return {
        "block_days": block_days, "replicates": replicates, "seed": seed,
        "comparisons": comparisons,
        "intersection_union_p": max(row["p_one_sided"] for row in comparisons.values()),
        "ordinary_sha256": _array_sha(ordinary), "centered_sha256": _array_sha(centered),
        "exact_hits_sha256": hashlib.sha256(np.ascontiguousarray(hits).tobytes()).hexdigest(),
        "exact_encoding_sha256": prepared.metadata["encoding_sha256"],
        "tail_method": "exact_binary64_rational_weighted_sum_ge_twice_original_sum",
    }, ordinary, centered, hits
