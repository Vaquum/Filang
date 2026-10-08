#!/usr/bin/env python3
"""Independent raw-OHLC and cash/share oracle for the frozen R1 campaign.

This module does not import producer feature, target, estimator, inference or
ledger helpers. It never runs an optimizer or fits a market model. The feature
stage is usable before predictive execution and audits every native key.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import time
from datetime import datetime, timezone

for _thread_variable in ("VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                         "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_thread_variable, "1")

import numpy as np


HERE = Path(__file__).resolve().parent
TIMES = (15, 30, 60, 120, 240)
HISTORIES = (2, 3, 5, 10)
FAMILIES = ("B", "G")
YEARS = (2023, 2024, 2025, 2026)
TOLERANCE = 1e-10
HEX = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def epoch(text):
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def digest(path, limit=None):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        remaining = limit
        while remaining is None or remaining > 0:
            block = stream.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
            if not block:
                break
            value.update(block)
            if remaining is not None:
                remaining -= len(block)
        require(remaining in (None, 0), "truncated hashed input: " + str(path))
    return value.hexdigest()


def array_digest(value, dtype=None):
    return hashlib.sha256(np.ascontiguousarray(value, dtype=dtype).tobytes(order="C")).hexdigest()


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def json_digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def json_file(path):
    def reject_constant(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(Path(path).read_text(), parse_constant=reject_constant)


def compare(actual, expected, label="value", tolerance=TOLERANCE):
    """Compare complete structures and return their maximum numeric discrepancy."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), label + ": object fields")
        return max((compare(actual[key], value, label + "/" + key, tolerance)
                    for key, value in expected.items()), default=0.0)
    if isinstance(expected, (list, tuple)):
        require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + ": sequence length")
        return max((compare(a, b, label + f"/{i}", tolerance)
                    for i, (a, b) in enumerate(zip(actual, expected))), default=0.0)
    if isinstance(expected, np.ndarray):
        value = np.asarray(actual)
        require(value.shape == expected.shape, label + ": array shape")
        if expected.dtype.kind in "biu":
            require(np.array_equal(value, expected), label + ": integer/mask values")
            return 0.0
        require(np.array_equal(np.isnan(value), np.isnan(expected)), label + ": NaN placement")
        require(not np.isinf(value).any() and not np.isinf(expected).any(), label + ": infinite values")
        mask = np.isfinite(expected)
        require(np.allclose(value[mask], expected[mask], atol=tolerance, rtol=tolerance), label + ": floating values")
        return float(np.max(np.abs(value[mask] - expected[mask]))) if np.any(mask) else 0.0
    if expected is None or isinstance(expected, (str, bool, int, np.integer)):
        require(actual == expected, f"{label}: {actual!r} != {expected!r}")
        return 0.0
    require(math.isfinite(float(actual)) and math.isfinite(float(expected)), label + ": nonfinite number")
    require(math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=tolerance),
            f"{label}: {actual!r} != {expected!r}")
    return abs(float(actual) - float(expected))


def load_source(csv_path, interval_seconds, expected_sha=None):
    csv_path = Path(csv_path)
    source_sha = digest(csv_path)
    require(expected_sha is None or source_sha == expected_sha, "prepared CSV digest mismatch")
    with csv_path.open() as source:
        require(source.readline().rstrip("\r\n") == "timestamp,open,high,low,close,volume", "CSV schema")
    matrix = np.loadtxt(csv_path, delimiter=",", skiprows=1, dtype=np.float64, ndmin=2)
    require(matrix.shape[1] == 6 and len(matrix) >= 12 and np.isfinite(matrix).all(), "source shape/finite values")
    timestamps = matrix[:, 0].astype(np.int64)
    require(np.array_equal(matrix[:, 0], timestamps), "nonintegral source timestamp")
    step = int(interval_seconds)
    differences = np.diff(timestamps)
    require(step > 0 and np.all(timestamps % step == 0) and np.all(differences > 0),
            "source timestamps duplicate, unordered or off grid")
    prices = np.ascontiguousarray(matrix[:, 1:5])
    require(np.all(prices > 0) and np.all(matrix[:, 5] >= 0), "source price/volume domain")
    require(np.all(prices[:, 2] <= np.minimum(prices[:, 0], prices[:, 3])) and
            np.all(np.maximum(prices[:, 0], prices[:, 3]) <= prices[:, 1]), "source OHLC order")
    return {"timestamp": timestamps, "prices": prices, "interval_seconds": step,
            "sha256": source_sha, "bytes": csv_path.stat().st_size, "path": str(csv_path),
            "gap_count": int((differences > step).sum()),
            "missing_grid_bars": int((differences // step - 1).sum())}


def endpoints(prices):
    return np.column_stack((prices[:, 2], np.minimum(prices[:, 0], prices[:, 3]),
                            np.maximum(prices[:, 0], prices[:, 3]), prices[:, 1]))


def feature_names(n, family):
    require(n in HISTORIES and family in FAMILIES, "undeclared feature family/history")
    names = [f"body[{k}].{sign}" for k in range(n) for sign in ("up", "down")]
    names += [f"cc[{k}].{sign}" for k in range(n - 1) for sign in ("up", "down")]
    if family == "G":
        names += [f"comparison[{k},{a},{b}].{sign}" for k in range(1, n)
                  for a in range(4) for b in range(4) for sign in ("less", "equal")]
        names += [f"wick[{k}].{side}_present" for k in range(n) for side in ("lower", "upper")]
    return names


def raw_features(prices, rows, n, family):
    """Projection directly from raw prices; never decode ranks or up flags."""
    rows = np.asarray(rows, dtype=np.int64)
    values = np.empty((len(rows), len(feature_names(n, family))), dtype=np.uint8)
    column = 0
    for lag in range(n):
        indices = rows - lag
        values[:, column] = prices[indices, 3] > prices[indices, 0]
        values[:, column + 1] = prices[indices, 3] < prices[indices, 0]
        column += 2
    for lag in range(n - 1):
        a, b = prices[rows - lag, 3], prices[rows - lag - 1, 3]
        values[:, column], values[:, column + 1] = a > b, a < b
        column += 2
    if family == "G":
        bounds = endpoints(prices)
        for lag in range(1, n):
            for current in range(4):
                for previous in range(4):
                    a, b = bounds[rows, current], bounds[rows - lag, previous]
                    values[:, column], values[:, column + 1] = a < b, a == b
                    column += 2
        for lag in range(n):
            window = bounds[rows - lag]
            values[:, column], values[:, column + 1] = window[:, 0] < window[:, 1], window[:, 2] < window[:, 3]
            column += 2
    require(column == values.shape[1], "raw feature dimension")
    return values


def raw_dense_ranks(prices, rows, n):
    """NumPy sorting and inverse permutation provide an independent rank oracle."""
    bounds = endpoints(prices)
    window = bounds[np.asarray(rows)[:, None] - np.arange(n)].reshape(len(rows), 4 * n)
    order = np.argsort(window, axis=1, kind="stable")
    sorted_values = np.take_along_axis(window, order, axis=1)
    changes = np.ones(sorted_values.shape, dtype=np.uint8)
    changes[:, 1:] = sorted_values[:, 1:] != sorted_values[:, :-1]
    levels = (np.cumsum(changes, axis=1) - 1).astype(np.uint8)
    ranks = np.empty_like(levels)
    np.put_along_axis(ranks, order, levels, axis=1)
    return ranks.reshape(len(rows), n, 4)


def decode_words(words, n=10):
    words = np.asarray(words, dtype=np.uint64)
    require(words.ndim == 2 and words.shape[1] == 4, "key word shape")
    ranks = np.empty((len(words), n, 4), dtype=np.uint8)
    for index in range(4 * n):
        bit = 6 * index
        word, shift = divmod(bit, 64)
        value = words[:, word] >> np.uint64(shift)
        if shift > 58:
            value = value | (words[:, word + 1] << np.uint64(64 - shift))
        ranks[:, index // 4, index % 4] = value & np.uint64(63)
    up = np.column_stack([((words[:, 3] >> np.uint64(48 + i)) & np.uint64(1)).astype(bool)
                          for i in range(n)])
    require(np.all(((words[:, 3] >> np.uint64(58)) & np.uint64(15)) == n), "key width")
    require(np.all(((words[:, 3] >> np.uint64(62)) & np.uint64(1)) == 1), "key orientation")
    require(np.all((words[:, 3] >> np.uint64(63)) == 0), "reserved key bit")
    require(np.all(ranks[:, :, :-1] <= ranks[:, :, 1:]), "unordered key candle")
    require(np.all(ranks < 4 * n), "key rank outside window")
    require(not np.any(up & (ranks[:, :, 1] == ranks[:, :, 2])), "flat body has up flag")
    # Generic widths are checked too, although this protocol always uses ten.
    for index in range(4 * n, 40):
        bit = 6 * index
        word, shift = divmod(bit, 64)
        value = words[:, word] >> np.uint64(shift)
        if shift > 58:
            value |= words[:, word + 1] << np.uint64(64 - shift)
        require(np.all((value & np.uint64(63)) == 0), "nonzero unused rank")
    if n < 10:
        require(np.all(((words[:, 3] >> np.uint64(48 + n)) & np.uint64((1 << (10 - n)) - 1)) == 0),
                "nonzero unused up flag")
    return ranks, up


def key_features(ranks, up, n, family):
    """A second projection establishes decoded-key versus raw-price parity."""
    cols = []
    close = np.where(up, ranks[:, :, 2], ranks[:, :, 1])
    for k in range(n):
        cols.extend((up[:, k], (~up[:, k]) & (ranks[:, k, 1] < ranks[:, k, 2])))
    for k in range(n - 1):
        cols.extend((close[:, k] > close[:, k + 1], close[:, k] < close[:, k + 1]))
    if family == "G":
        for k in range(1, n):
            for a in range(4):
                for b in range(4):
                    cols.extend((ranks[:, 0, a] < ranks[:, k, b], ranks[:, 0, a] == ranks[:, k, b]))
        for k in range(n):
            cols.extend((ranks[:, k, 0] < ranks[:, k, 1], ranks[:, k, 2] < ranks[:, k, 3]))
    return np.column_stack(cols).astype(np.uint8)


def audit_native_keys(directory, source, protocol, producer_features=None):
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    seal = (directory / "manifest.sha256").read_text().strip()
    require(HEX.fullmatch(seal) and digest(manifest_path) == seal, "native manifest seal")
    manifest, context = json_file(manifest_path), json_file(directory / "context.json")
    context_sha = digest(directory / "context.json")
    require(context["format"] == manifest["format"] == "geometry-keys-v1", "native format")
    require(manifest["status"] == "COMPLETE", "incomplete native export")
    require(context["mode"] == manifest["mode"] == "oriented" and context["bars"] == manifest["bars"] == 10,
            "native protocol width/mode")
    require(context["key_layout"] == "geometry-key-256-v1" and
            context["eligibility"] == "all_window_rows_in_history_consecutive_past_only", "native eligibility/layout")
    require(context["history_start"] == protocol["data"]["history_start"] and
            context["end"] == protocol["data"]["end_exclusive"], "native protocol period")
    require(context["source_sha256"] == manifest["source_sha256"] == source["sha256"], "native source identity")
    require(manifest["context_sha256"] == context_sha and HEX.fullmatch(context["engine_sha256"]), "native context/engine identity")
    require(manifest["timings_sha256"] == digest(directory / "timings.json"), "native timings identity")
    ts, step = source["timestamp"], source["interval_seconds"]
    require(context["interval_seconds"] == step, "native timeframe")
    first, end = map(int, np.searchsorted(ts, [epoch(context["history_start"]), epoch(context["end"])]))
    candidates = np.arange(first + 9, end, dtype=np.int64)
    expected_rows = candidates[(ts[candidates] - ts[candidates - 9]) == 9 * step]
    counters = {"source_bytes": source["bytes"], "source_rows": len(ts), "selected_first_index": first,
                "selected_end_index_exclusive": end, "selected_rows": end - first,
                "initial_warmup_rows": 9, "gap_window_skips": len(candidates) - len(expected_rows),
                "source_gap_count": source["gap_count"], "source_missing_grid_bars": source["missing_grid_bars"],
                "records": len(expected_rows), "header_bytes": 168, "record_bytes": 40}
    for name, expected in counters.items():
        require(manifest[name] == expected, "native metadata " + name)
    require(manifest["keys_file"] == "keys.bin", "native key path")
    keys_path = directory / "keys.bin"
    payload_bytes = 168 + 40 * len(expected_rows)
    require(keys_path.stat().st_size == payload_bytes + 64 == manifest["keys_file_bytes"], "native key file length")
    with keys_path.open("rb") as stream:
        header = stream.read(168)
        stream.seek(payload_bytes)
        payload_seal = stream.read(64).decode("ascii")
    require(header[:8] == b"FGKEYS01", "native key magic")
    require(header[8:72].decode("ascii") == context_sha and header[72:136].decode("ascii") == source["sha256"],
            "native binary source/context")
    require(struct.unpack("<4Q", header[136:168]) == (len(ts), step, 10, len(expected_rows)), "native binary header")
    require(HEX.fullmatch(payload_seal) and digest(keys_path, payload_bytes) == payload_seal == manifest["keys_payload_sha256"],
            "native key payload seal")
    require(manifest["keys_payload_bytes"] == payload_bytes and digest(keys_path) == manifest["keys_file_sha256"],
            "native whole-file identity")
    records = np.memmap(keys_path, mode="r", dtype="<u8", offset=168, shape=(len(expected_rows), 5))
    require(np.array_equal(records[:, 0], expected_rows), "native original-row mapping/causal eligibility")
    hashes = {(n, family): hashlib.sha256() for n in HISTORIES for family in FAMILIES}
    rank_hash, up_hash = hashlib.sha256(), hashlib.sha256()
    for start in range(0, len(records), 4096):
        stop = min(start + 4096, len(records))
        rows = expected_rows[start:stop]
        ranks, up = decode_words(records[start:stop, 1:])
        expected_ranks = raw_dense_ranks(source["prices"], rows, 10)
        expected_up = source["prices"][rows[:, None] - np.arange(10), 3] > source["prices"][rows[:, None] - np.arange(10), 0]
        require(np.array_equal(ranks, expected_ranks) and np.array_equal(up, expected_up), "native raw-OHLC key mismatch")
        rank_hash.update(ranks.tobytes(order="C"))
        up_hash.update(up.astype(np.uint8).tobytes(order="C"))
        for n in HISTORIES:
            for family in FAMILIES:
                direct = raw_features(source["prices"], rows, n, family)
                require(np.array_equal(direct, key_features(ranks, up, n, family)), "raw/key projected feature mismatch")
                hashes[n, family].update(direct.tobytes(order="C"))
    features = {f"{family}{n}": {"n": n, "family": family, "columns": feature_names(n, family),
                                "shape": [len(expected_rows), len(feature_names(n, family))],
                                "sha256": hashes[n, family].hexdigest()}
                for n in HISTORIES for family in FAMILIES}
    receipt = {"status": "PASS", "source_sha256": source["sha256"], "native_manifest_sha256": seal,
               "context_sha256": context_sha, "engine_sha256": context["engine_sha256"],
               "keys_file_sha256": manifest["keys_file_sha256"], "records_checked": len(expected_rows),
               "record_indices_sha256": array_digest(expected_rows, "<i8"),
               "all_native_records_checked": True, "all_raw_vs_key_projections_checked": True,
               "producer_feature_digests_checked": False,
               "ranks_sha256": rank_hash.hexdigest(), "up_flags_sha256": up_hash.hexdigest(),
               "features": features, **counters}
    if producer_features is not None:
        audit_feature_manifest(producer_features, receipt)
        receipt["producer_feature_digests_checked"] = True
    return receipt, expected_rows


def phase_oracle(source, causal_rows, start, end):
    ts, prices, step = source["timestamp"], source["prices"], source["interval_seconds"]
    size = len(ts)
    causal = np.zeros(size, dtype=bool)
    causal[np.asarray(causal_rows, dtype=np.int64)] = True
    phase = (ts >= start) & (ts < end)
    valid = np.zeros(size, dtype=bool)
    rows = np.flatnonzero(causal & phase)
    rows = rows[rows + 2 < size]
    rows = rows[(ts[rows + 2] - ts[rows - 9] == 11 * step) & (ts[rows + 2] < end)]
    valid[rows] = True
    direction = np.zeros(size, dtype=np.int8)
    direction[rows] = np.sign(prices[rows + 2, 0] - prices[rows + 1, 0]).astype(np.int8)
    returns = np.full(size, np.nan)
    returns[rows] = prices[rows + 2, 0] / prices[rows + 1, 0] - 1
    entry, exit_ = np.full(size, -1, dtype=np.int64), np.full(size, -1, dtype=np.int64)
    entry[rows], exit_[rows] = rows + 1, rows + 2
    return {"row_index": np.arange(size, dtype=np.int64), "timestamp": ts,
            "causal_feature_valid": causal, "phase_mask": phase, "classification_valid": valid,
            "binary_mask": valid & (direction != 0), "direction": direction,
            "target_return": returns, "entry_row": entry, "exit_row": exit_}


def stable_sigmoid(logits):
    logits = np.asarray(logits, dtype=np.float64)
    result = np.empty_like(logits)
    positive = logits >= 0
    result[positive] = 1 / (1 + np.exp(-logits[positive]))
    exp = np.exp(logits[~positive])
    result[~positive] = exp / (1 + exp)
    return result


def objective_gradient(x, y, intercept, coefficients, penalty):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    coefficients = np.asarray(coefficients, dtype=np.float64)
    z = x @ coefficients + float(intercept)
    residual = stable_sigmoid(z) - y
    objective = float(np.mean(np.logaddexp(0, z) - y * z) + penalty * np.dot(coefficients, coefficients) / 2)
    gradient = np.concatenate(([residual.mean()], x.T @ residual / len(y) + penalty * coefficients))
    return objective, gradient


def scores(y, probability):
    y, p = np.asarray(y, dtype=np.int8), np.asarray(probability, dtype=np.float64)
    require(len(y) == len(p) and len(y) > 0 and np.isin(y, [0, 1]).all(), "binary scoring inputs")
    require(np.isfinite(p).all() and np.all((p > 0) & (p < 1)), "binary scoring probability domain")
    up, down = int(y.sum()), int((y == 0).sum())
    prediction = p >= .5
    return {"n_binary": len(y), "n_up": up, "n_down": down,
            "log_loss": float(np.mean(np.where(y == 1, -np.log(p), -np.log1p(-p)))),
            "brier": float(np.mean((p - y) ** 2)), "accuracy": float(np.mean(prediction == y)),
            "balanced_accuracy": (float((prediction[y == 1].mean() + (~prediction[y == 0]).mean()) / 2)
                                  if up and down else None)}


def score_oracle(direction, probability, logits=None, flat_count=0):
    direction, p = np.asarray(direction), np.asarray(probability, dtype=float)
    require(len(direction) > 0 and np.isin(direction, [-1, 1]).all(), "score labels")
    require(np.isfinite(p).all() and np.all((p >= 0) & (p <= 1)), "score probabilities")
    y = direction == 1
    if logits is None:
        require(np.all((p > 0) & (p < 1)), "interior baseline probability")
        losses = np.where(y, -np.log(p), -np.log1p(-p))
    else:
        # softplus(-z) for up and softplus(z) for down, independently
        # rearranged from the producer's softplus(z)-y*z expression.
        z = np.asarray(logits, dtype=float)
        losses = np.logaddexp(0, np.where(y, -z, z))
    predicted = p >= .5
    count, up = len(y), int(y.sum())
    up_correct, down_correct = int(np.sum(predicted & y)), int(np.sum((~predicted) & (~y)))
    loss_sum, brier_sum = float(losses.sum()), float(np.square(p-y).sum())
    return {"binary_count": count, "up_count": up, "down_count": count-up, "flat_count": int(flat_count),
            "binary_log_loss": loss_sum/count, "loss_sum": loss_sum, "brier": brier_sum/count,
            "brier_sum": brier_sum, "accuracy": (up_correct+down_correct)/count,
            "correct_count": up_correct+down_correct, "up_correct_count": up_correct,
            "down_correct_count": down_correct,
            "balanced_accuracy": (up_correct/up+down_correct/(count-up))/2 if 0 < up < count else None}


def phase_scores(arrays):
    mask = arrays["binary_mask"]
    flat = int(np.sum(arrays["classification_valid"] & (arrays["direction"] == 0)))
    return {name: score_oracle(arrays["direction"][mask], arrays[f"p_{name}"][mask],
            arrays[f"logit_{name}"][mask] if name in FAMILIES else None, flat)
            for name in ("B", "G", "unconditional", "lag1")}


def daily_oracle(arrays, start, end):
    days = np.arange(start//86400, (end-1)//86400+1, dtype=np.int64)
    binary, classified = arrays["binary_mask"], arrays["classification_valid"]
    where = arrays["timestamp"][arrays["exit_row"][binary]]//86400-days[0]
    flat = classified & (arrays["direction"] == 0)
    flat_where = arrays["timestamp"][arrays["exit_row"][flat]]//86400-days[0]
    result = {"day": days, "binary_count": np.zeros(len(days), dtype=np.int64),
              "flat_count": np.zeros(len(days), dtype=np.int64)}
    np.add.at(result["binary_count"], where, 1)
    np.add.at(result["flat_count"], flat_where, 1)
    y = arrays["direction"][binary] == 1
    for name in ("B", "G", "unconditional", "lag1"):
        p = arrays[f"p_{name}"][binary]
        if name in FAMILIES:
            z = arrays[f"logit_{name}"][binary]
            losses = np.logaddexp(0, np.where(y, -z, z))
        else:
            losses = np.where(y, -np.log(p), -np.log1p(-p))
        loss, correct = np.zeros(len(days)), np.zeros(len(days), dtype=np.int64)
        np.add.at(loss, where, losses)
        np.add.at(correct, where, (p >= .5) == y)
        result[f"loss_sum_{name}"], result[f"correct_{name}"] = loss, correct
    result["paired_loss_sum"] = result["loss_sum_B"]-result["loss_sum_G"]
    return result


def bootstrap_oracle(folds, minutes, block, replicas=2000, seed=20261008):
    count = sum(int(f["binary_count"].sum()) for f in folds)
    gain = sum(float(f["paired_loss_sum"].sum()) for f in folds)/count
    generator = np.random.default_rng(seed+1000*minutes+block)
    draws, null = np.empty(replicas), np.empty(replicas)
    for replica in range(replicas):
        numerator, centered, denominator = 0.0, 0.0, 0
        for fold in folds:
            counts, sums = fold["binary_count"], fold["paired_loss_sum"]
            length = len(counts)
            starts = generator.integers(0, length, size=math.ceil(length/block), dtype=np.int64)
            sample = np.concatenate([np.arange(int(start), int(start)+block) % length for start in starts])[:length]
            numerator += float(np.sum(sums[sample]))
            centered += float(np.sum((sums-gain*counts)[sample]))
            denominator += int(np.sum(counts[sample]))
        require(denominator > 0, "empty bootstrap sample")
        draws[replica], null[replica] = numerator/denominator, centered/denominator
    ordered = np.sort(draws)
    def percentile(p):
        offset = (len(ordered)-1)*p
        left = int(math.floor(offset))
        right = min(left+1, len(ordered)-1)
        return float(ordered[left]+(ordered[right]-ordered[left])*(offset-left))
    result = {"block_days": block, "replicates": replicas, "seed": seed+1000*minutes+block,
              "gain": gain, "ci95_low": percentile(.025), "ci95_high": percentile(.975),
              "p_one_sided": (1+int(np.sum(null >= gain)))/(replicas+1)}
    return result, {"ordinary": draws, "centered": null}


def pooled_score_oracle(folds):
    output = {}
    integer_names = ("binary_count", "up_count", "down_count", "flat_count", "correct_count", "up_correct_count", "down_correct_count")
    for policy in ("B", "G", "unconditional", "lag1"):
        rows = [f["scores"][policy] for f in folds]
        totals = {name: sum(row[name] for row in rows) for name in integer_names}
        total, up, down = totals["binary_count"], totals["up_count"], totals["down_count"]
        loss, brier = sum(r["loss_sum"] for r in rows), sum(r["brier_sum"] for r in rows)
        output[policy] = {**totals, "loss_sum": loss, "brier_sum": brier,
            "binary_log_loss": loss/total, "brier": brier/total, "accuracy": totals["correct_count"]/total,
            "balanced_accuracy": (totals["up_correct_count"]/up+totals["down_correct_count"]/down)/2}
    return output


def cash_share_oracle(timestamps, opens, probability, *, start, end, interval_seconds,
                      fee_bps, slippage_bps, policy="threshold", entry_threshold=.5, exit_threshold=.5):
    """Independent quantity account, normalized after every marked opening.

    Normalizing cash and coin together preserves all return ratios while avoiding
    underflow. A separate frictionless account follows the same exposure path.
    No producer logarithmic cost factors or ledger helpers are imported.
    """
    timestamps = np.asarray(timestamps, dtype=np.int64)
    opens, probability = np.asarray(opens, dtype=float), np.asarray(probability, dtype=float)
    require(timestamps.ndim == 1 and opens.shape == probability.shape == timestamps.shape, "ledger vectors")
    require(len(timestamps) >= 2 and np.all(np.diff(timestamps) > 0) and np.all(np.isfinite(opens)) and np.all(opens > 0), "ledger source")
    require(interval_seconds > 0 and end > start and 0 <= exit_threshold <= entry_threshold <= 1, "ledger period/thresholds")
    require(not np.isinf(probability).any() and np.all((probability[np.isfinite(probability)] >= 0) &
                                                    (probability[np.isfinite(probability)] <= 1)), "ledger probabilities")
    require(policy in ("threshold", "cash", "buy_hold"), "ledger policy")
    fee, slip = fee_bps / 10000.0, slippage_bps / 10000.0
    require(0 <= fee < 1 and 0 <= slip < 1, "ledger costs")
    indices = np.flatnonzero((timestamps >= start) & (timestamps < end))
    require(len(indices) >= 2, "ledger requires two period openings")
    cash, coin, free_cash, free_coin = 1.0, 0.0, 1.0, 0.0
    exposure, seconds, entry = 0, 0, None
    cumulative_net, cumulative_gross = 0.0, 0.0
    rows, trades, gaps = [], [], []
    for ordinal, original in enumerate(indices):
        i, price = int(original), float(opens[original])
        before = exposure
        marked, free_marked = cash + coin * price, free_cash + free_coin * price
        gross_mark = math.log(free_marked)
        if ordinal:
            seconds += before * int(timestamps[i] - timestamps[indices[ordinal - 1]])
        signal, close, delay, used, want = -1, -1, 0, float("nan"), 0
        if ordinal and timestamps[i - 1] >= start:
            signal, close = i - 1, int(timestamps[i - 1] + interval_seconds)
            delay, used = max(0, int(timestamps[i] - close)), float(probability[i - 1])
            if policy == "buy_hold":
                want = 1
            elif policy == "threshold" and math.isfinite(used):
                want = int(used >= (exit_threshold if before else entry_threshold))
        terminal = ordinal == len(indices) - 1
        if terminal:
            want = 0
        cost = 0.0
        if want != before:
            if want:
                coin = marked * (1 - fee) / (price * (1 + slip))
                cash, free_coin, free_cash = 0.0, free_marked / price, 0.0
                cost = math.log((cash + coin * price) / marked)
                entry = {"entry_row": i, "entry_timestamp": int(timestamps[i]), "entry_open": price,
                         "entry_log_cost": cost, "signal_row": signal, "signal_close": close,
                         "entry_delay_seconds": delay, "net_before_entry": cumulative_net}
            else:
                cash = coin * price * (1 - slip) * (1 - fee)
                coin, free_cash, free_coin = 0.0, free_marked, 0.0
                cost = math.log(cash / marked)
        wealth, free_wealth = cash + coin * price, free_cash + free_coin * price
        net_change = math.log(wealth)
        cumulative_net += net_change
        cumulative_gross += gross_mark
        if before and not want:
            require(entry is not None, "oracle sale without entry")
            trade_net = cumulative_net - entry["net_before_entry"]
            trade = {k: v for k, v in entry.items() if k != "net_before_entry"}
            trade.update(exit_row=i, exit_timestamp=int(timestamps[i]), exit_open=price, exit_log_cost=cost,
                         gross_log_return=math.log(price / entry["entry_open"]), net_log_return=trade_net,
                         net_return=math.expm1(trade_net), holding_seconds=int(timestamps[i] - entry["entry_timestamp"]),
                         terminal_liquidation=terminal)
            trades.append(trade)
            entry = None
        exposure = want
        rows.append((i, int(timestamps[i]), price, signal, close, used, delay, before, want, exposure,
                     gross_mark, cost, net_change))
        if ordinal and timestamps[i] - timestamps[i - 1] != interval_seconds:
            gaps.append({"previous_row": i - 1, "row": i, "previous_open": int(timestamps[i - 1]),
                         "open_timestamp": int(timestamps[i]), "missing_seconds": int(timestamps[i] - timestamps[i - 1] - interval_seconds),
                         "signal_close": close, "delay_seconds": delay, "position_before": before,
                         "position_after": exposure, "gap_gross_log_return": gross_mark, "net_log_return": net_change})
        cash, coin = cash / wealth, coin / wealth
        free_cash, free_coin = free_cash / free_wealth, free_coin / free_wealth
    require(exposure == 0 and entry is None, "oracle terminal position")
    names = ("row", "timestamp", "open", "signal_row", "signal_close", "signal_probability", "delay_seconds",
             "position_before", "desired", "position_after", "gross_log_return", "log_cost", "net_log_return")
    integers = {"row", "timestamp", "signal_row", "signal_close", "delay_seconds", "position_before", "desired", "position_after"}
    trace = {name: np.asarray([row[k] for row in rows], dtype=np.int64 if name in integers else np.float64)
             for k, name in enumerate(names)}
    days = np.arange(start // 86400, (end - 1) // 86400 + 1, dtype=np.int64)
    daily_net, daily_gross = np.zeros(len(days)), np.zeros(len(days))
    for row in rows:
        day = row[1] // 86400 - int(days[0])
        daily_net[day] += row[12]
        daily_gross[day] += row[10]
    net_total, gross_total = float(trace["net_log_return"].sum()), float(trace["gross_log_return"].sum())
    sides = int(np.count_nonzero(trace["position_before"] != trace["position_after"]))
    running, high, drawdown = 0.0, 0.0, 0.0
    for change in trace["net_log_return"]:
        running += float(change)
        high = max(high, running)
        drawdown = max(drawdown, 1 - math.exp(running - high))
    daily_mean = float(daily_net.sum() / len(days))
    daily_sd = math.sqrt(float(np.square(daily_net - daily_mean).sum()) / (len(days) - 1)) if len(days) > 1 else 0.0
    active = {row[1] // 86400 for row in rows if row[7] or row[9]}
    metrics = {"start": int(start), "end_exclusive": int(end), "observed_openings": len(indices),
               "calendar_days": len(days), "terminal_open": int(timestamps[indices[-1]]), "policy": policy,
               "entry_threshold": entry_threshold, "exit_threshold": exit_threshold,
               "fee_bps_per_side": fee_bps, "slippage_bps_per_side": slippage_bps,
               "net_log_return": net_total, "gross_log_return": gross_total,
               "net_return": math.expm1(net_total), "gross_return": math.expm1(gross_total),
               "log_cost_drag": -float(trace["log_cost"].sum()), "max_drawdown": drawdown,
               "annualized_daily_log_sharpe": daily_mean / daily_sd * math.sqrt(365.25) if daily_sd else None,
               "annualized_return": math.expm1(net_total * 365.25 / len(days)),
               "one_way_turnover": sides, "completed_trades": len(trades),
               "trade_win_rate": sum(t["net_return"] > 0 for t in trades) / len(trades) if trades else None,
               "mean_trade_net_return": sum(t["net_return"] for t in trades) / len(trades) if trades else None,
               "seconds_long": seconds, "exposure_fraction": seconds / int(timestamps[indices[-1]] - timestamps[indices[0]]),
               "active_days": len(active), "gap_count": len(gaps),
               "gap_gross_log_return": sum(g["gap_gross_log_return"] for g in gaps),
               "delayed_exposure_changes": sum(row[6] > 0 and row[7] != row[9] for row in rows),
               "break_even_symmetric_cost_bps_per_side": -math.expm1(-gross_total / sides) * 10000 if sides else None}
    return {"metrics": metrics, "daily_days": days, "daily_net_log": daily_net, "daily_gross_log": daily_gross,
            "trades": trades, "gaps": gaps, "trace": trace}


def audit_feature_manifest(producer, expected):
    """Adapter is intentionally strict; final producer schema is checked here."""
    require(producer["source_sha256"] == expected["source_sha256"], "producer feature source")
    require(producer["source_rows"] == expected["source_rows"] and
            producer["record_count"] == expected["records_checked"], "producer feature coverage")
    require(producer["record_indices_sha256"] == expected["record_indices_sha256"] and
            producer["ranks_sha256"] == expected["ranks_sha256"] and
            producer["up_sha256"] == expected["up_flags_sha256"], "producer decoded arrays")
    compare(producer["native"], {"context_sha256": expected["context_sha256"],
            "manifest_sha256": expected["native_manifest_sha256"], "keys_sha256": expected["keys_file_sha256"],
            "engine_sha256": expected["engine_sha256"]}, "producer native identities")
    for key, value in expected["features"].items():
        item = producer["features"][str(value["n"])][value["family"]]
        compare(item, {"shape": value["shape"], "dtype": "uint8", "sha256": value["sha256"],
                       "columns_sha256": json_digest(value["columns"])}, "producer feature values/order: " + key)


def read_npz(path):
    with np.load(path, allow_pickle=False) as saved:
        result = {key: saved[key] for key in saved.files}
    require(all(value.dtype.kind != "O" for value in result.values()), "object array in " + str(path))
    return result


def audit_run_identity(args, protocol):
    root = args.run.resolve()
    manifest_path = root / "manifest.json"
    require((root / "manifest.sha256").read_text() == digest(manifest_path)+"\n", "producer manifest seal")
    manifest = json_file(manifest_path)
    require(manifest["schema"] == "filang-information-run-manifest-v1", "producer manifest schema")
    for relative, record in manifest["files"].items():
        path = (root / relative).resolve()
        require(root in path.parents and not Path(relative).is_absolute(), "producer artifact path escape")
        require(path.is_file() and path.stat().st_size == record["bytes"] and digest(path) == record["sha256"],
                "producer artifact integrity: " + relative)
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and
              p.name not in ("manifest.json", "manifest.sha256") and p.resolve() != args.out.resolve()}
    require(actual == set(manifest["files"]), "unsealed or missing producer artifacts")
    require((root / "protocol.json").read_bytes() == args.protocol.read_bytes(), "producer frozen protocol bytes")
    protocol_sha = digest(args.protocol)
    require(protocol_sha == "abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a", "unexpected frozen protocol")
    run = json_file(root / "run.json")
    require(run["schema"] == "filang-information-run-v1" and run["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "producer run incomplete")
    require(run["protocol_sha256"] == protocol_sha and
            run["freeze_commit"] == "b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd", "freeze identity")
    require(not run["amendments"] and not run["deviations"], "undeclared protocol amendment/deviation")
    require(json_digest(run["implementation"]["files"]) == run["implementation"]["sha256"], "implementation object identity")
    repo = HERE.parents[1]
    for relative, checksum in run["implementation"]["files"].items():
        require(digest(repo / relative) == checksum, "retained/current producer source differs: " + relative)
    require(set(run["implementation"]["files"]) ==
            {"experiments/geometry_information/"+name for name in ("run_round1.py", "common.py", "economics.py")},
            "producer implementation coverage")
    provenance = json_file(root / "provenance.json")
    require(digest(root / "provenance.json") == run["source_provenance_sha256"] == digest(args.data_dir / "provenance.json"),
            "source provenance identity")
    require(provenance["protocol_sha256"] == protocol["predecessor"]["protocol_sha256"], "predecessor protocol")
    require(len(provenance["sources"]) == 5, "provenance source coverage")
    for spec in protocol["data"]["sources"]:
        matches = [s for s in provenance["sources"] if s["minutes"] == spec["minutes"]]
        require(len(matches) == 1, "provenance timeframe")
        row = matches[0]
        for name in ("repo", "revision", "filename", "sha256", "expected_source_rows", "expected_source_bytes", "minutes"):
            require(row["source"][name] == spec[name], "raw source pin: " + name)
        raw = args.data_dir / "raw" / spec["filename"]
        require(raw.stat().st_size == spec["expected_source_bytes"] and digest(raw) == spec["sha256"] == row["source_sha256"],
                "raw pinned artifact bytes")
        require(row["csv_sha256"] == spec["prepared_csv_sha256"] and row["missing_grid_bars"] == spec["missing_grid_bars"],
                "prepared provenance metadata")
    return manifest, run


def audit_fit(model, source, receipt, feature, labels, fold, family, n, penalty, stage,
              protocol_sha, implementation_sha, parent):
    rows = np.flatnonzero(labels["binary_mask"])
    y = (labels["direction"][rows] == 1).astype(np.uint8)
    bounds = ("inner_train_start", "inner_train_end_exclusive") if stage == "inner" else ("refit_start", "refit_end_exclusive")
    metadata = {"schema": "filang-information-fit-v1", "minutes": receipt["minutes"], "outer_year": fold["year"],
        "family": family, "n": n, "lambda": penalty, "stage": stage,
        "fit_start": epoch(fold[bounds[0]]), "fit_end_exclusive": epoch(fold[bounds[1]]),
        "fit_count": len(rows), "fit_up_count": int(y.sum()), "fit_down_count": int(len(y)-y.sum()),
        "fit_rows_sha256": array_digest(rows, "<i8"), "fit_labels_sha256": array_digest(y, np.uint8),
        "feature_sha256": receipt["features"][f"{family}{n}"]["sha256"],
        "feature_columns_sha256": json_digest(feature_names(n, family)),
        "source_sha256": source["sha256"], "native_keys_sha256": receipt["keys_file_sha256"],
        "protocol_sha256": protocol_sha, "implementation_sha256": implementation_sha,
        "initializer": {"kind": "warm_previous_lambda" if parent else "beta11_zero",
            "parent_fit_id": parent["fit_id"] if parent else None,
            "parent_coefficient_sha256": parent["coefficient_sha256"] if parent else None}, "cache_hit": False}
    for name, expected in metadata.items():
        compare(model[name], expected, "fit metadata " + name)
    require(model["fit_id"] == json_digest(metadata), "fit identity hash")
    theta = np.asarray([model["intercept"], *model["coefficients"]], dtype=np.float64)
    require(theta.shape == (feature.shape[1]+1,) and np.isfinite(theta).all(), "fit coefficient dimensions/finite")
    require(model["coefficient_sha256"] == array_digest(theta, "<f8"), "fit coefficient identity")
    initial = np.zeros(len(theta))
    if parent:
        initial[:] = [parent["intercept"], *parent["coefficients"]]
    else:
        p = (y.sum()+1)/(len(y)+2)
        initial[0] = math.log(p/(1-p))
    require(model["initializer_sha256"] == array_digest(initial, "<f8"), "fit initializer identity")
    objective, gradient = objective_gradient(feature, y, theta[0], theta[1:], penalty)
    error = max(compare(model["objective"], objective, "fit objective"),
                compare(np.asarray(model["gradient"]), gradient, "fit gradient"),
                compare(model["max_abs_gradient"], float(np.max(np.abs(gradient))), "fit gradient maximum"),
                compare(model["optimizer"]["reported_objective"], objective, "optimizer objective"))
    require(model["accepted"] is True and model["optimizer"]["success"] is True and
            np.max(np.abs(gradient)) <= 5e-6 and model["optimizer"]["status"] == 0, "unaccepted required fit")
    require(0 <= model["optimizer"]["iterations"] <= 1000 and model["optimizer"]["function_evaluations"] > 0 and
            model["optimizer"]["gradient_evaluations"] > 0, "optimizer iteration/evaluation bounds")
    return error


def baseline_oracle(source, fit_labels, prediction_mask):
    prices = source["prices"]
    signs = np.zeros(len(prices), dtype=np.int8)
    signs[1:] = np.sign(prices[1:, 3]-prices[:-1, 3]).astype(np.int8)
    mask, direction = fit_labels["binary_mask"], fit_labels["direction"]
    count, up = int(mask.sum()), int(np.sum(direction[mask] == 1))
    unconditional = (up+1)/(count+2)
    model = {"unconditional": unconditional, "binary_count": count, "up_count": up, "lag1": {}}
    a, b = np.full(len(prices), np.nan), np.full(len(prices), np.nan)
    a[prediction_mask] = unconditional
    for sign in (-1, 0, 1):
        selected = mask & (signs == sign)
        n, u = int(selected.sum()), int(np.sum(direction[selected] == 1))
        p = (u+1)/(n+2) if n else unconditional
        model["lag1"][str(sign)] = {"count": n, "up": u, "probability": p}
        b[prediction_mask & (signs == sign)] = p
    return model, a, b


def audit_predictions(root, fold_root, phase, source, causal_rows, fold, models, fit_labels, protocol_sha, receipt):
    start, end = epoch(fold[f"{phase}_start"]), epoch(fold[f"{phase}_end_exclusive"])
    expected = phase_oracle(source, causal_rows, start, end)
    mask = expected["causal_feature_valid"] & expected["phase_mask"]
    rows = np.flatnonzero(mask)
    for family in FAMILIES:
        model = models[family]
        x = raw_features(source["prices"], rows, model["n"], family).astype(float)
        z = x @ np.asarray(model["coefficients"]) + model["intercept"]
        expected[f"p_{family}"] = np.full(len(mask), np.nan)
        expected[f"logit_{family}"] = np.full(len(mask), np.nan)
        expected[f"p_{family}"][rows] = stable_sigmoid(z)
        expected[f"logit_{family}"][rows] = z
    baseline, expected["p_unconditional"], expected["p_lag1"] = baseline_oracle(source, fit_labels, mask)
    path = fold_root / f"{phase}.npz"
    actual, sidecar = read_npz(path), json_file(path.with_suffix(".json"))
    error = compare(actual, expected, str(path))
    for name in expected:
        require(actual[name].dtype == expected[name].dtype, "prediction array dtype: " + name)
        compare(sidecar["arrays"][name], {"dtype": actual[name].dtype.str, "shape": list(actual[name].shape),
                "sha256": array_digest(actual[name])}, "prediction array identity: " + name)
    require(set(sidecar["arrays"]) == set(expected), "prediction sidecar array coverage")
    identities = {"schema": "filang-information-predictions-v1", "minutes": receipt["minutes"],
        "outer_year": fold["year"], "phase": phase, "phase_start": start, "phase_end_exclusive": end,
        "source_sha256": source["sha256"], "protocol_sha256": protocol_sha,
        "native_keys_sha256": receipt["keys_file_sha256"], "npz_sha256": digest(path), "npz_bytes": path.stat().st_size,
        "baseline_fit_rows_sha256": array_digest(np.flatnonzero(fit_labels["binary_mask"]), "<i8"),
        "baseline_fit_labels_sha256": array_digest(fit_labels["direction"][fit_labels["binary_mask"]] == 1, np.uint8)}
    for name, value in identities.items():
        compare(sidecar[name], value, "prediction sidecar " + name)
    error = max(error, compare(sidecar["baseline_fit"], baseline, "descriptive baseline training counts"))
    for family in FAMILIES:
        model = models[family]
        compare(sidecar["models"][family], {"fit_id": model["fit_id"], "coefficient_sha256": model["coefficient_sha256"],
                "path": model["path"], "file_sha256": digest(root / model["path"])}, "prediction fitted identity")
    # Score serialized predictions only after every element passes raw-model replay.
    metrics = phase_scores(actual)
    error = max(error, compare(sidecar["scores"], metrics, "prediction scores"))
    return actual, metrics, error


def feature_stage(args, protocol):
    records = []
    for spec in protocol["data"]["sources"]:
        minutes = int(spec["minutes"])
        source = load_source(args.data_dir / f"{minutes}m/ohlcv.csv", minutes * 60, spec["prepared_csv_sha256"])
        require(len(source["timestamp"]) == spec["expected_source_rows"] and
                source["missing_grid_bars"] == spec["missing_grid_bars"], "pinned source row/gap counts")
        producer = None
        if args.run is not None and (args.run / f"{minutes}m/features.json").exists():
            producer = json_file(args.run / f"{minutes}m/features.json")
        checked, _ = audit_native_keys(args.keys_root / f"{minutes}m", source, protocol, producer)
        checked["minutes"] = minutes
        records.append(checked)
        print(json.dumps({"features_verified": minutes, "records": checked["records_checked"],
                          "producer_features_verified": checked["producer_feature_digests_checked"]}), flush=True)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("features", "all"), default="all")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--keys-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=HERE / "round1_protocol.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    protocol = json_file(args.protocol)
    require(protocol["schema"] == "filang-geometry-information-protocol-v1", "protocol schema")
    records = feature_stage(args, protocol)
    require(args.stage == "features", "full scientific artifact adapter is not yet available; no full audit was certified")
    result = {"schema": "filang-r1-independent-verification-v1", "status": "PASS", "stage": args.stage,
              "protocol_sha256": digest(args.protocol), "verifier_sha256": digest(__file__),
              "native_records_checked": sum(r["records_checked"] for r in records),
              "all_raw_keys_and_projections_checked": True,
              "all_producer_feature_digests_checked": all(r["producer_feature_digests_checked"] for r in records),
              "scientific_models_checked": False, "features": records,
              "elapsed_seconds": time.perf_counter() - started}
    save_json(args.out, result)
    print(json.dumps({"status": "PASS", "stage": args.stage, "receipt": str(args.out)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("independent R1 audit: " + str(error), file=__import__("sys").stderr)
        raise SystemExit(2)
