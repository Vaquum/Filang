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
R1_PROTOCOL_SHA256 = "abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a"
R1A_PROTOCOL_SHA256 = "cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34"
# Admission is explicit. A reviewed draft is not executable until its actual
# frozen commit is recorded here; neither a CLI flag nor run metadata admits it.
SUPPORTED_PROTOCOLS = {
    R1_PROTOCOL_SHA256: {"attempt_id": "R1", "freeze_commit": "b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd",
                         "optimizer_method": "L-BFGS-B"},
    R1A_PROTOCOL_SHA256: {"attempt_id": "R1a", "freeze_commit": "3df6416a2de59ac396617be49326a834c94aca92",
                          "optimizer_method": "Newton-Cholesky-Armijo"},
}


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


def admitted_protocol(protocol_sha):
    require(protocol_sha in SUPPORTED_PROTOCOLS, "unrecognized frozen protocol digest")
    contract = SUPPORTED_PROTOCOLS[protocol_sha]
    require(contract["freeze_commit"] is not None and
            re.fullmatch(r"[0-9a-f]{40}", contract["freeze_commit"]), "protocol draft has no admitted freeze commit")
    return contract


def unchanged_scientific_contract(original, amended):
    """Only the separately frozen numerical optimizer amendment is allowed."""
    allowed = {"experiment_id", "attempt_id", "protocol_status", "estimation", "amendment"}
    require(set(amended) == set(original) | {"amendment"}, "amendment top-level fields")
    changed = {key for key in set(original) | set(amended) if original.get(key) != amended.get(key)}
    require(changed == allowed, "amendment changed undeclared scientific fields")
    original_estimation = {k: value for k, value in original["estimation"].items() if k != "optimizer"}
    amended_estimation = {k: value for k, value in amended["estimation"].items() if k != "optimizer"}
    require(original_estimation == amended_estimation, "amendment changed scientific estimation settings")
    declaration = amended["amendment"]
    require(declaration["changed_fields"] == ["experiment_id", "attempt_id", "protocol_status", "estimation.optimizer", "amendment"],
            "amendment declared field coverage")
    require(declaration["from_attempt"] == "R1" and declaration["from_protocol_sha256"] == R1_PROTOCOL_SHA256 and
            declaration["from_freeze_commit"] == SUPPORTED_PROTOCOLS[R1_PROTOCOL_SHA256]["freeze_commit"], "amendment parent identity")


def protocol_contract(protocol_path, original_path=None):
    protocol_sha = digest(protocol_path)
    contract = admitted_protocol(protocol_sha)
    protocol = json_file(protocol_path)
    require(protocol["attempt_id"] == contract["attempt_id"] and
            protocol["estimation"]["optimizer"]["method"] == contract["optimizer_method"], "frozen attempt/method identity")
    if protocol_sha == R1A_PROTOCOL_SHA256:
        original_path = Path(original_path) if original_path is not None else HERE / "round1_protocol.json"
        require(digest(original_path) == R1_PROTOCOL_SHA256, "original R1 protocol changed")
        unchanged_scientific_contract(json_file(original_path), protocol)
    return contract


def run_protocol_binding(run, protocol, protocol_sha):
    contract = admitted_protocol(protocol_sha)
    require(run["protocol_sha256"] == protocol_sha and run["freeze_commit"] == contract["freeze_commit"], "freeze identity")
    expected_amendments = [protocol["amendment"]] if protocol_sha == R1A_PROTOCOL_SHA256 else []
    require(run["amendments"] == expected_amendments and run["deviations"] == [], "undeclared protocol amendment/deviation")


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
            # Reconstruct the completed trade from one unit of entry cash.
            # This also preserves exactly flat zero-cost trades: cancellation
            # across thousands of normalized log marks must not create wins.
            purchased = (1-fee)/(entry["entry_open"]*(1+slip))
            trade_wealth = purchased*price*(1-slip)*(1-fee)
            if fee == 0 and slip == 0 and price == entry["entry_open"]:
                trade_wealth = 1.0
            trade_net = math.log(trade_wealth)
            require(math.isclose(trade_net, cumulative_net-entry["net_before_entry"], abs_tol=1e-10, rel_tol=1e-10),
                    "oracle trade/marked account reconciliation")
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


def audit_run_identity(args, protocol, expected_status="COMPLETE_PENDING_INDEPENDENT_AUDIT"):
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
    protocol_contract(args.protocol)
    run = json_file(root / "run.json")
    require(run["schema"] == "filang-information-run-v1" and run["status"] == expected_status,
            "producer run incomplete")
    run_protocol_binding(run, protocol, protocol_sha)
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


def predecessor_binding(args, protocol):
    """Bind supplied provenance to prior published evidence when available."""
    folder = (HERE.parents[1] / protocol["predecessor"]["published_provenance_path"]).parent
    manifest_path = folder / "manifest.json"
    supplied = args.data_dir / "provenance.json"
    if not manifest_path.exists():
        return {"status": "UNAVAILABLE", "manifest_path": str(manifest_path),
                "supplied_provenance_sha256": digest(supplied),
                "scope": "Prior compact manifest absent locally; all frozen raw/prepared pins remain checked."}
    manifest = json_file(manifest_path)
    require(manifest["status"] == "PASS", "predecessor manifest status")
    published = folder / "provenance.json"
    record = manifest["files"]["provenance.json"]
    require(published.stat().st_size == record["bytes"] and digest(published) == record["sha256"] == digest(supplied),
            "predecessor published/supplied provenance binding")
    prior_protocol = folder / "protocol.json"
    record = manifest["files"]["protocol.json"]
    require(prior_protocol.stat().st_size == record["bytes"] and digest(prior_protocol) == record["sha256"] ==
            protocol["predecessor"]["protocol_sha256"], "predecessor manifest protocol binding")
    return {"status": "PASS", "manifest_path": str(manifest_path), "manifest_sha256": digest(manifest_path),
            "supplied_provenance_sha256": digest(supplied), "published_provenance_sha256": digest(published),
            "protocol_sha256": digest(prior_protocol),
            "scope": "Prior manifest binds exact supplied provenance and frozen predecessor protocol; unrelated prior report outputs not re-audited."}


def optimizer_record(optimizer, gradient, protocol_sha):
    """Audit retained optimizer telemetry without taking an optimization step.

    The numerical method is selected exclusively by the admitted protocol hash.
    The terminal objective and every gradient coordinate are independently
    reconstructed by audit_fit; counters/steps are checked against that method's
    fixed budget. This does not claim to replay every historical Armijo trial.
    """
    method = admitted_protocol(protocol_sha)["optimizer_method"]
    require(isinstance(optimizer["success"], bool) and
            (optimizer["status"] == 0) == optimizer["success"], "optimizer success/status disagreement")
    if method == "L-BFGS-B":
        require(optimizer.get("method", "L-BFGS-B") == "L-BFGS-B", "R1 optimizer method differs")
        require(0 <= optimizer["iterations"] <= 1000 and optimizer["function_evaluations"] > 0 and
                optimizer["gradient_evaluations"] > 0, "optimizer iteration/evaluation bounds")
        return
    require(method == "Newton-Cholesky-Armijo" and optimizer["method"] == method, "R1a optimizer method differs")
    reasons = {0: "gradient_tolerance", 1: "maximum_iterations", 2: "nonfinite_evaluation",
        3: "nonfinite_hessian", 4: "factorization_failure", 5: "nonfinite_direction",
        6: "non_descent_direction", 7: "line_search_failure", 8: "terminal_recomputation_failure"}
    for field in ("status", "iterations", "function_evaluations", "gradient_evaluations", "hessian_evaluations", "nonfinite_line_search_trials"):
        require(type(optimizer[field]) is int and optimizer[field] >= 0, "Newton integer counter: " + field)
    status, iterations = optimizer["status"], optimizer["iterations"]
    require(status in reasons and optimizer["stop_reason"] == reasons[status], "Newton stop reason/status")
    require(iterations <= 100, "Newton update budget")
    steps, backtracks, trials = optimizer["step_sizes"], optimizer["backtrack_counts"], optimizer["line_search_trial_counts"]
    require(isinstance(steps, list) and isinstance(backtracks, list) and isinstance(trials, list) and
            len(steps) == len(backtracks) == iterations, "Newton accepted update telemetry")
    require(all(type(value) is int and 0 <= value < 50 for value in backtracks), "Newton backtracking budget")
    require(all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and
                value == 2.0**(-backtracks[i]) for i, value in enumerate(steps)), "Newton step size schedule")
    require(all(type(value) is int and 1 <= value <= 50 for value in trials), "Newton line-search trial budget")
    expected_trials = [value+1 for value in backtracks]
    if status == 7:
        expected_trials.append(50)
    require(trials == expected_trials, "Newton trial/update counter reconciliation")
    expected_hessians = iterations + int(status in (3, 4, 5, 6, 7))
    require(optimizer["hessian_evaluations"] == expected_hessians, "Newton attempted Hessian count")
    require(optimizer["function_evaluations"] == optimizer["gradient_evaluations"] == 1+sum(trials),
            "Newton objective/gradient evaluation counts")
    require(optimizer["nonfinite_line_search_trials"] <= sum(trials)-iterations, "Newton nonfinite trial count")
    final_gradient = np.asarray(gradient, dtype=float)
    norm = float(np.max(np.abs(final_gradient)))
    require(np.isfinite(final_gradient).all(), "Newton terminal gradient finite")
    if status == 0:
        require(norm <= 1e-7, "Newton success requires gradient tolerance")
    elif status == 1:
        require(iterations == 100 and norm > 1e-7, "Newton iteration-limit termination")
    elif status == 8:
        require(norm > 1e-7, "Newton terminal recomputation failure condition")
    else:
        require(iterations < 100 and norm > 1e-7, "Newton failure must precede convergence/update limit")


def audit_fit(model, source, receipt, feature, labels, fold, family, n, penalty, stage,
              protocol_sha, implementation_sha, parent, require_accepted=True):
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
    acceptance = bool(model["optimizer"]["success"] and np.max(np.abs(gradient)) <= 5e-6)
    require(model["accepted"] is acceptance, "stored acceptance disagrees with full optimizer/gradient criterion")
    optimizer_record(model["optimizer"], gradient, protocol_sha)
    if require_accepted:
        require(acceptance, "unaccepted required fit")
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


def audit_ledger(folder, expected):
    error = 0.0
    for name in ("metrics", "trades", "gaps"):
        error = max(error, compare(json_file(folder / f"{name}.json"), expected[name], "ledger " + str(folder/name)))
    error = max(error, compare(read_npz(folder / "trace.npz"), expected["trace"], "ledger opening trace " + str(folder)))
    error = max(error, compare(read_npz(folder / "daily.npz"),
                {name: expected[name] for name in ("daily_days", "daily_net_log", "daily_gross_log")}, "ledger calendar " + str(folder)))
    return error


def aggregate_ledger_oracle(parts, years):
    chosen = [parts[year] for year in years]
    daily = np.concatenate([p["daily_net_log"] for p in chosen])
    changes = np.concatenate([p["trace"]["net_log_return"] for p in chosen])
    metrics = [p["metrics"] for p in chosen]
    trades = [trade for part in chosen for trade in part["trades"]]
    total, gross = float(changes.sum()), sum(m["gross_log_return"] for m in metrics)
    running, maximum, drawdown = 0.0, 0.0, 0.0
    for value in changes:
        running += float(value)
        maximum = max(maximum, running)
        drawdown = max(drawdown, 1-math.exp(running-maximum))
    sides, seconds = sum(m["one_way_turnover"] for m in metrics), sum(m["seconds_long"] for m in metrics)
    elapsed = sum(int(p["trace"]["timestamp"][-1]-p["trace"]["timestamp"][0]) for p in chosen)
    mean = float(daily.sum()/len(daily))
    std = math.sqrt(float(np.square(daily-mean).sum())/(len(daily)-1))
    result = {"folds": years, "independent_annual_cash_resets": True, "calendar_days": len(daily),
        "net_log_return": total, "net_return": math.expm1(total), "gross_log_return": gross, "gross_return": math.expm1(gross),
        "log_cost_drag": sum(m["log_cost_drag"] for m in metrics), "max_drawdown": drawdown,
        "annualized_daily_log_sharpe": mean/std*math.sqrt(365.25) if std else None,
        "annualized_return": math.expm1(total*365.25/len(daily)), "one_way_turnover": sides,
        "completed_trades": len(trades), "trade_win_rate": sum(t["net_return"] > 0 for t in trades)/len(trades) if trades else None,
        "mean_trade_net_return": sum(t["net_return"] for t in trades)/len(trades) if trades else None,
        "seconds_long": seconds, "exposure_fraction": seconds/elapsed,
        "break_even_symmetric_cost_bps_per_side": -math.expm1(-gross/sides)*10000 if sides else None}
    for field in ("active_days", "gap_count", "gap_gross_log_return", "delayed_exposure_changes"):
        result[field] = sum(m[field] for m in metrics)
    return result


def audit_csv(path, expected):
    with Path(path).open(newline="") as stream:
        actual = list(csv.DictReader(stream))
    require(len(actual) == len(expected), "CSV complete row coverage: " + str(path))
    error = 0.0
    for observed, desired in zip(actual, expected):
        require(set(observed) == set(desired), "CSV columns: " + str(path))
        for key, value in desired.items():
            if value is None:
                require(observed[key] == "", "CSV absent value " + key)
            elif isinstance(value, bool):
                require(observed[key] == str(value), "CSV bool " + key)
            elif isinstance(value, (int, np.integer)):
                require(observed[key] == str(value), "CSV integer " + key)
            elif isinstance(value, (float, np.floating)):
                error = max(error, compare(float(observed[key]), float(value), "CSV " + key))
            else:
                require(observed[key] == value, "CSV text " + key)
    return error


def full_stage(args, protocol, receipts, manifest, run):
    root, protocol_sha = args.run, digest(args.protocol)
    error, fits, selections, candidate_rows, daily_rows, results = 0.0, [], [], [], [], []
    coverage = {"native_keys": sum(r["records_checked"] for r in receipts), "candidate_fits": 0, "refit_fits": 0,
                "outer_predictions": 0, "validation_predictions": 0, "ledger_replays": 0, "all_records": True, "sampled": False}
    global_features = json_file(root / "features.json")
    compare(global_features["column_names"], {str(n): {f: feature_names(n, f) for f in FAMILIES} for n in HISTORIES},
            "global feature names/order")
    require(global_features["schema"] == "filang-information-features-v1" and
            global_features["protocol_sha256"] == protocol_sha, "global feature identity")
    expected_features = [json_file(root / f"{minutes}m/features.json") for minutes in TIMES]
    compare(global_features["timeframes"], expected_features, "global/per-timeframe feature copies")
    require(all(r["producer_feature_digests_checked"] for r in receipts), "producer feature matrices not all audited")
    analysis = json_file(root / "analysis.json")
    require(analysis["schema"] == "filang-information-analysis-v1" and analysis["protocol_sha256"] == protocol_sha and
            analysis["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT", "analysis incomplete/identity")
    require(analysis["experiment_id"] == protocol["experiment_id"] and analysis["primary_scope"] == protocol["primary_scope"] and
            analysis["prior_exposure"] == protocol["predecessor"]["prior_exposure"], "analysis scope/exposure")
    compare(analysis["coverage"], {"inner_fits": 640, "selected_refits": 40, "timeframes": 5, "outer_folds": 4}, "analysis coverage")
    for receipt, spec in zip(receipts, protocol["data"]["sources"]):
        minutes = receipt["minutes"]
        require(minutes == spec["minutes"], "ordered timeframe coverage")
        folder = root / f"{minutes}m"
        source = load_source(args.data_dir / f"{minutes}m/ohlcv.csv", minutes*60, spec["prepared_csv_sha256"])
        ts = source["timestamp"]
        candidates = np.arange(9, len(ts), dtype=np.int64)
        causal_rows = candidates[(ts[candidates]-ts[candidates-9] == 9*minutes*60) &
            (ts[candidates-9] >= epoch(protocol["data"]["history_start"])) & (ts[candidates] < epoch(protocol["data"]["end_exclusive"]))]
        tf_fits, tf_selections, tf_candidates, folds, daily_folds = [], [], [], [], []
        policies = ("B", "G", "unconditional", "lag1", "cash", "buy_hold")
        scenarios = protocol["economic_diagnostic"]["cost_scenarios_bps_per_side"]
        ledgers = {scenario["name"]: {policy: {} for policy in policies} for scenario in scenarios}
        for fold in protocol["target_and_phases"]["outer_folds"]:
            year, fold_root = fold["year"], folder / str(fold["year"])
            train = phase_oracle(source, causal_rows, epoch(fold["inner_train_start"]), epoch(fold["inner_train_end_exclusive"]))
            validation = phase_oracle(source, causal_rows, epoch(fold["validation_start"]), epoch(fold["validation_end_exclusive"]))
            refit = phase_oracle(source, causal_rows, epoch(fold["refit_start"]), epoch(fold["refit_end_exclusive"]))
            selected_inner, selected_refit, choices = {}, {}, {}
            for family in FAMILIES:
                models, independent_validation_losses = [], {}
                for n in HISTORIES:
                    fitting_features = raw_features(source["prices"], np.flatnonzero(train["binary_mask"]), n, family).astype(float)
                    validation_features = raw_features(source["prices"], np.flatnonzero(validation["binary_mask"]), n, family).astype(float)
                    parent = None
                    for penalty in protocol["estimation"]["lambda_grid_descending"]:
                        path = fold_root / family / "candidates" / f"n{n:02}-l{penalty:g}.json"
                        model = json_file(path)
                        require(model["path"] == str(path.relative_to(root)), "candidate file identity")
                        error = max(error, audit_fit(model, source, receipt, fitting_features, train, fold, family, n, penalty,
                                    "inner", protocol_sha, run["implementation"]["sha256"], parent))
                        z = validation_features @ np.asarray(model["coefficients"]) + model["intercept"]
                        metrics = score_oracle(validation["direction"][validation["binary_mask"]], stable_sigmoid(z), z,
                                    int(np.sum(validation["classification_valid"] & (validation["direction"] == 0))))
                        error = max(error, compare(model["validation_scores"], metrics, "candidate validation scores"))
                        independent_validation_losses[model["fit_id"]] = metrics["binary_log_loss"]
                        require(model["validation_mask_sha256"] == array_digest(validation["binary_mask"], np.uint8),
                                "candidate validation sample")
                        row = {"minutes": minutes, "outer_year": year, "family": family, "n": n, "lambda": penalty,
                            "fit_id": model["fit_id"], "accepted": True, **metrics}
                        tf_candidates.append(row)
                        models.append(model)
                        tf_fits.append(model)
                        parent = model
                        coverage["candidate_fits"] += 1
                del fitting_features, validation_features
                minimum = min(independent_validation_losses.values())
                tied = [m for m in models if independent_validation_losses[m["fit_id"]] <= minimum+1e-12]
                best = sorted(tied, key=lambda m: (m["n"], -m["lambda"]))[0]
                path = fold_root / family / "refit.json"
                fitted = json_file(path)
                require(fitted["path"] == str(path.relative_to(root)), "refit file identity")
                fitting_features = raw_features(source["prices"], np.flatnonzero(refit["binary_mask"]), best["n"], family).astype(float)
                error = max(error, audit_fit(fitted, source, receipt, fitting_features, refit, fold, family, best["n"], best["lambda"],
                            "refit", protocol_sha, run["implementation"]["sha256"], None))
                del fitting_features
                tf_fits.append(fitted)
                coverage["refit_fits"] += 1
                choice = {"minutes": minutes, "outer_year": year, "family": family, "n": best["n"], "lambda": best["lambda"],
                    "validation_minimum_loss": minimum, "validation_selected_loss": best["validation_scores"]["binary_log_loss"],
                    "inner_fit_id": best["fit_id"], "refit_fit_id": fitted["fit_id"], "inner_model_path": best["path"],
                    "refit_model_path": fitted["path"]}
                error = max(error, compare(json_file(fold_root / family / "selected.json"), choice, "validation selection"))
                choices[family] = choice
                tf_selections.append(choice)
                selected_inner[family], selected_refit[family] = best, fitted
            fold_result = {"year": year, "selected": choices}
            for phase in ("validation", "outer"):
                start, end = epoch(fold[f"{phase}_start"]), epoch(fold[f"{phase}_end_exclusive"])
                phase_models, fitting_labels = (selected_inner, train) if phase == "validation" else (selected_refit, refit)
                arrays, metrics, discrepancy = audit_predictions(root, fold_root, phase, source, causal_rows, fold,
                                                phase_models, fitting_labels, protocol_sha, receipt)
                error = max(error, discrepancy)
                coverage[phase+"_predictions"] += 1
                if phase == "outer":
                    daily = daily_oracle(arrays, start, end)
                    error = max(error, compare(read_npz(fold_root / "classification_daily.npz"), daily, "classification UTC daily units"))
                    daily_folds.append(daily)
                    for i, day in enumerate(daily["day"]):
                        daily_rows.append({"minutes": minutes, "outer_year": year,
                            "utc_date": datetime.fromtimestamp(int(day)*86400, timezone.utc).date().isoformat(),
                            **{name: value[i].item() for name, value in daily.items()}})
                    fold_result.update(scores=metrics, gain=metrics["B"]["binary_log_loss"]-metrics["G"]["binary_log_loss"], economics={})
                for scenario in scenarios:
                    name = scenario["name"]
                    if phase == "outer": fold_result["economics"][name] = {}
                    for policy in policies:
                        p = arrays[f"p_{policy}"] if policy not in ("cash", "buy_hold") else np.full(len(ts), np.nan)
                        ledger = cash_share_oracle(ts, source["prices"][:, 0], p, start=start, end=end,
                            interval_seconds=source["interval_seconds"], fee_bps=scenario["fee"], slippage_bps=scenario["slippage"],
                            policy=policy if policy in ("cash", "buy_hold") else "threshold",
                            entry_threshold=protocol["economic_diagnostic"]["entry_threshold"],
                            exit_threshold=protocol["economic_diagnostic"]["exit_threshold"])
                        error = max(error, audit_ledger(fold_root / "economics" / phase / name / policy, ledger))
                        coverage["ledger_replays"] += 1
                        if phase == "outer":
                            fold_result["economics"][name][policy] = ledger["metrics"]
                            # Keep only what independently reset aggregate accounting needs.
                            ledger["trace"] = {k: ledger["trace"][k] for k in ("timestamp", "net_log_return")}
                            ledger.pop("gaps")
                            ledgers[name][policy][year] = ledger
                del arrays
            folds.append(fold_result)
            print(json.dumps({"verified_minutes": minutes, "verified_year": year,
                              "candidate_fits": coverage["candidate_fits"], "ledger_replays": coverage["ledger_replays"]}), flush=True)
        bootstrap = {}
        settings = protocol["inference"]["bootstrap"]
        producer_summary = json_file(folder / "summary.json")
        for block in (7, 1, 28):
            summary, values = bootstrap_oracle(daily_folds, minutes, block, settings["replicates"], settings["base_seed"])
            retained = read_npz(folder / f"bootstrap-{block}.npz")
            error = max(error, compare(retained, values, "bootstrap all replicas"))
            # Numeric recomputation is independent; byte hashes bind the actual retained arrays.
            summary.update(ordinary_sha256=array_digest(retained["ordinary"], "<f8"),
                           centered_sha256=array_digest(retained["centered"], "<f8"))
            bootstrap[str(block)] = summary
        economics = {label: {name: {policy: aggregate_ledger_oracle(parts, included) for policy, parts in policies_.items()}
                        for name, policies_ in ledgers.items()}
                    for label, included in (("all_outer", list(YEARS)), ("continuous_2024_plus", [2024, 2025, 2026]))}
        result = {"minutes": minutes, "folds": folds, "pooled_scores": pooled_score_oracle(folds), "bootstrap": bootstrap,
                  "positive_years": sum(f["gain"] > 0 for f in folds), "economics": economics}
        error = max(error, compare(producer_summary, result, "timeframe full summary"))
        compare([json.loads(line) for line in (folder / "fits.jsonl").read_text().splitlines()], tf_fits, "timeframe fit catalogue")
        error = max(error, compare(json_file(folder / "candidates.json"), tf_candidates, "timeframe candidate catalogue"))
        compare(json_file(folder / "selected.json"), {"schema": "filang-information-selection-v1", "selections": tf_selections},
                "timeframe selections")
        fits.extend(tf_fits)
        selections.extend(tf_selections)
        candidate_rows.extend(tf_candidates)
        results.append(result)
        del ledgers
    order = sorted(results, key=lambda result: (result["bootstrap"]["7"]["p_one_sided"], result["minutes"]))
    previous = 0.0
    for rank, result in enumerate(order):
        previous = max(previous, min(1.0, (len(order)-rank)*result["bootstrap"]["7"]["p_one_sided"]))
        result["p_holm"] = previous
    for result in results:
        primary = result["bootstrap"]["7"]
        conditions = {"positive_gain": primary["gain"] > 0, "ci_above_zero": primary["ci95_low"] > 0,
            "holm_below_005": result["p_holm"] < .05, "three_positive_years": result["positive_years"] >= 3}
        result.update(conditions=conditions, criterion_met=all(conditions.values()), outcome="inconclusive",
                      outcome_if_verified="supported" if all(conditions.values()) else "not-supported")
    error = max(error, compare(analysis["timeframes"], results, "complete inference, Holm and decision conditions"))
    compare([json.loads(line) for line in (root / "fits.jsonl").read_text().splitlines()], fits, "global complete fit catalogue")
    compare(json_file(root / "selected.json"), {"schema": "filang-information-selection-v1", "selections": selections}, "global selections")
    error = max(error, audit_csv(root / "candidates.csv", candidate_rows), audit_csv(root / "classification_daily.csv", daily_rows))
    fit_paths = {f["path"] for f in fits}
    retained_fit_paths = {p for p in manifest["files"] if ("/candidates/" in p and p.endswith(".json")) or p.endswith("/refit.json")}
    require(len(fit_paths) == 680 and fit_paths == retained_fit_paths, "all retained fit coverage")
    ledger_files = [p for p in manifest["files"] if "/economics/" in p and p.endswith("/metrics.json")]
    require(len(ledger_files) == coverage["ledger_replays"] == 960, "all retained ledger coverage")
    require(coverage == {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40, "outer_predictions": 20,
        "validation_predictions": 20, "ledger_replays": 960, "all_records": True, "sampled": False}, "complete frozen experiment coverage")
    return {"coverage": coverage, "max_numeric_error": error,
        "audited_timeframes": list(TIMES), "audited_outer_years": list(YEARS),
        "producer_manifest_sha256": digest(root / "manifest.json"), "analysis_sha256": digest(root / "analysis.json"),
        "scientific_models_checked": True, "checks": {"raw_source_provenance": True, "all_native_keys": True,
            "all_feature_columns": True, "all_fit_rows_labels_objectives_gradients": True,
            "all_candidate_validation_scores_and_choices": True, "all_full_row_predictions_and_masks": True,
            "all_daily_units_and_bootstrap_replicas": True, "holm_and_frozen_criteria": True,
            "all_cash_share_ledger_traces": True, "all_reset_aggregate_ledgers": True,
            "all_retained_artifact_identities": True, "no_optimizer_run_by_verifier": True}}


def failed_stage(args, protocol, receipts, manifest, run):
    """Audit the complete retained execution prefix, never infer market results.

    R1 stopped at the first rejected fit in each independent timeframe worker.
    Later required cells are missing by design and remain scientifically
    inconclusive. This stage cannot emit the full-success receipt contract.
    """
    root, protocol_sha = args.run, digest(args.protocol)
    error, failures, retained_paths, selection_paths, parameter_paths = 0.0, [], set(), set(), set()
    coverage = {"native_keys": sum(r["records_checked"] for r in receipts), "fits": 0,
        "candidate_fits": 0, "accepted_candidate_fits": 0, "candidate_validation_scores": 0,
        "refit_fits": 0, "rejected_fits": 0, "selections": 0, "outer_predictions": 0,
        "validation_predictions": 0, "ledger_replays": 0, "all_retained_records": True, "sampled": False}
    require(all(r["producer_feature_digests_checked"] for r in receipts), "failed-run producer feature coverage")
    require(sorted(f["minutes"] for f in run["failures"]) == list(TIMES), "failed worker coverage")
    fold = protocol["target_and_phases"]["outer_folds"][0]
    require(fold["year"] == 2023, "failed-run first outer fold")
    for receipt, spec in zip(receipts, protocol["data"]["sources"]):
        minutes, records, stopped = receipt["minutes"], [], False
        source = load_source(args.data_dir / f"{minutes}m/ohlcv.csv", minutes*60, spec["prepared_csv_sha256"])
        folder, fold_root = root / f"{minutes}m", root / f"{minutes}m/2023"
        ts = source["timestamp"]
        candidates = np.arange(9, len(ts), dtype=np.int64)
        causal_rows = candidates[(ts[candidates]-ts[candidates-9] == 9*minutes*60) &
            (ts[candidates-9] >= epoch(protocol["data"]["history_start"])) & (ts[candidates] < epoch(protocol["data"]["end_exclusive"]))]
        train = phase_oracle(source, causal_rows, epoch(fold["inner_train_start"]), epoch(fold["inner_train_end_exclusive"]))
        validation = phase_oracle(source, causal_rows, epoch(fold["validation_start"]), epoch(fold["validation_end_exclusive"]))
        refit = phase_oracle(source, causal_rows, epoch(fold["refit_start"]), epoch(fold["refit_end_exclusive"]))
        for family in FAMILIES:
            models, independent_losses = [], {}
            for n in HISTORIES:
                features = raw_features(source["prices"], np.flatnonzero(train["binary_mask"]), n, family).astype(float)
                validation_features = raw_features(source["prices"], np.flatnonzero(validation["binary_mask"]), n, family).astype(float)
                parent = None
                for penalty in protocol["estimation"]["lambda_grid_descending"]:
                    path = fold_root / family / "candidates" / f"n{n:02}-l{penalty:g}.json"
                    model = json_file(path)
                    require(model["path"] == str(path.relative_to(root)), "failed-run candidate path")
                    error = max(error, audit_fit(model, source, receipt, features, train, fold, family, n, penalty, "inner",
                                protocol_sha, run["implementation"]["sha256"], parent, require_accepted=False))
                    retained_paths.add(model["path"])
                    records.append(model)
                    coverage["fits"] += 1
                    coverage["candidate_fits"] += 1
                    if not model["accepted"]:
                        expected_parameters = str(path.with_name(path.stem+"-failed-parameters.npz").relative_to(root))
                        require(model["failure_parameters_path"] == expected_parameters, "failed raw parameter path")
                        parameter_arrays = read_npz(root / expected_parameters)
                        expected_arrays = {"theta": np.asarray([model["intercept"], *model["coefficients"]], dtype=np.float64),
                            "gradient": np.asarray(model["gradient"], dtype=np.float64),
                            "objective": np.asarray(model["objective"], dtype=np.float64)}
                        compare(parameter_arrays, expected_arrays, "failed parameter array/JSON binding", tolerance=0)
                        require(all(value.dtype == np.dtype("float64") for value in parameter_arrays.values()),
                                "failed parameter array precision")
                        require(array_digest(parameter_arrays["theta"], "<f8") == model["coefficient_sha256"],
                                "failed parameter coefficient identity")
                        parameter_paths.add(expected_parameters)
                        require("validation_scores" not in model and "validation_mask_sha256" not in model,
                                "rejected candidate was used for validation selection")
                        require(model["optimizer"]["iterations"] == 1000 and model["optimizer"]["status"] == 1 and
                                model["optimizer"]["success"] is False and
                                "ITERATIONS REACHED LIMIT" in model["optimizer"]["message"], "unexpected R1 stop reason")
                        record = {"minutes": minutes, "outer_year": 2023, "family": family, "n": n, "lambda": penalty,
                            "fit_id": model["fit_id"], "path": model["path"], "objective": model["objective"],
                            "max_abs_gradient": model["max_abs_gradient"], "gradient_threshold_satisfied": model["max_abs_gradient"] <= 5e-6,
                            "accepted": False, "optimizer": model["optimizer"]}
                        failures.append(record)
                        worker = next(f for f in run["failures"] if f["minutes"] == minutes)
                        compare(json_file(root / f"failure-{minutes}m.json"), worker, "worker failure record")
                        require(model["fit_id"] in worker["traceback"], "worker stopped at retained rejected fit")
                        coverage["rejected_fits"] += 1
                        stopped = True
                        break
                    z = validation_features @ np.asarray(model["coefficients"]) + model["intercept"]
                    metrics = score_oracle(validation["direction"][validation["binary_mask"]], stable_sigmoid(z), z,
                                int(np.sum(validation["classification_valid"] & (validation["direction"] == 0))))
                    error = max(error, compare(model["validation_scores"], metrics, "retained candidate validation scores"))
                    require(model["validation_mask_sha256"] == array_digest(validation["binary_mask"], np.uint8), "retained validation rows")
                    coverage["accepted_candidate_fits"] += 1
                    coverage["candidate_validation_scores"] += 1
                    independent_losses[model["fit_id"]] = metrics["binary_log_loss"]
                    models.append(model)
                    parent = model
                if stopped:
                    break
            del features, validation_features
            if stopped:
                break
            require(len(models) == 16, "selection attempted before complete family grid")
            minimum = min(independent_losses.values())
            tied = [m for m in models if independent_losses[m["fit_id"]] <= minimum+1e-12]
            best = sorted(tied, key=lambda m: (m["n"], -m["lambda"]))[0]
            path = fold_root / family / "refit.json"
            fitted = json_file(path)
            require(fitted["path"] == str(path.relative_to(root)), "retained refit path")
            features = raw_features(source["prices"], np.flatnonzero(refit["binary_mask"]), best["n"], family).astype(float)
            error = max(error, audit_fit(fitted, source, receipt, features, refit, fold, family, best["n"], best["lambda"],
                        "refit", protocol_sha, run["implementation"]["sha256"], None))
            del features
            require("validation_scores" not in fitted, "refit used to recreate inner validation scores")
            retained_paths.add(fitted["path"])
            records.append(fitted)
            coverage["fits"] += 1
            coverage["refit_fits"] += 1
            choice = {"minutes": minutes, "outer_year": 2023, "family": family, "n": best["n"], "lambda": best["lambda"],
                "validation_minimum_loss": minimum, "validation_selected_loss": best["validation_scores"]["binary_log_loss"],
                "inner_fit_id": best["fit_id"], "refit_fit_id": fitted["fit_id"], "inner_model_path": best["path"],
                "refit_model_path": fitted["path"]}
            selection = fold_root / family / "selected.json"
            error = max(error, compare(json_file(selection), choice, "retained complete-family selection"))
            selection_paths.add(str(selection.relative_to(root)))
            coverage["selections"] += 1
        require(stopped, "failed worker lacks rejected fit")
        compare([json.loads(line) for line in (folder / "fits.jsonl").read_text().splitlines()], records, "all retained failure fit records")
        print(json.dumps({"forensic_minutes": minutes, "all_retained_fits": len(records), "rejected_fit": failures[-1]["fit_id"]}), flush=True)
    all_fit_paths = {p for p in manifest["files"] if ("/candidates/" in p and p.endswith(".json")) or p.endswith("/refit.json")}
    require(retained_paths == all_fit_paths, "unaudited retained fit or post-failure continuation")
    require(selection_paths == {p for p in manifest["files"] if p.endswith("/selected.json")}, "unaudited retained selection")
    require(parameter_paths == {p for p in manifest["files"] if p.endswith("-failed-parameters.npz")} and len(parameter_paths) == 5,
            "all retained failed parameter arrays")
    forbidden = [p for p in manifest["files"] if (p.endswith(".npz") and p not in parameter_paths) or "/economics/" in p or
                 p in ("analysis.json", "candidates.csv", "classification_daily.csv", "selected.json", "fits.jsonl") or
                 p.endswith("/summary.json") or p.endswith("/outer.json") or p.endswith("/validation.json")]
    require(not forbidden, "failed stage cannot certify prediction/inference/economic outputs: " + repr(forbidden))
    expected = {"native_keys": 458972, "fits": 161, "candidate_fits": 156, "accepted_candidate_fits": 151,
        "candidate_validation_scores": 151, "refit_fits": 5, "rejected_fits": 5, "selections": 5,
        "outer_predictions": 0, "validation_predictions": 0, "ledger_replays": 0, "all_retained_records": True, "sampled": False}
    require(coverage == expected, "R1 failed execution coverage")
    return {"experiment_status": "FAILED", "outcome": "inconclusive", "criterion_evaluable": False,
        "coverage": coverage, "failures": failures, "max_numeric_error": error, "audited_timeframes": list(TIMES),
        "audited_outer_years": [2023], "producer_manifest_sha256": digest(root / "manifest.json"), "analysis_sha256": None,
        "scientific_models_checked": False, "retained_model_parameters_checked": True,
        "scientific_models_scope": "Every retained point and accepted candidate validation score checked; required grid incomplete, no outer predictions or scientific inference.",
        "checks": {"raw_source_provenance": True, "all_native_keys_and_projections": True,
            "all_retained_fit_rows_labels_objectives_gradients": True, "all_retained_acceptance_flags": True,
            "all_failed_parameter_arrays": True,
            "all_retained_candidate_validation_scores": True, "all_retained_complete_family_selections": True,
            "all_worker_failure_records": True, "no_post_failure_predictions_or_economics": True,
            "all_retained_artifact_identities": True, "no_optimizer_run_by_verifier": True}}


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
    parser.add_argument("--stage", choices=("features", "failed", "full", "all"), default="full")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--keys-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=HERE / "round1_protocol.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    protocol = json_file(args.protocol)
    require(protocol["schema"] == "filang-geometry-information-protocol-v1", "protocol schema")
    protocol_contract(args.protocol)
    require(args.stage != "failed" or digest(args.protocol) == R1_PROTOCOL_SHA256,
            "failed-stage prefix audit is specific to the original frozen R1 attempt")
    model_stage = args.stage != "features"
    full = args.stage in ("full", "all")
    expected_status = "FAILED" if args.stage == "failed" else "COMPLETE_PENDING_INDEPENDENT_AUDIT"
    require(not model_stage or args.run is not None, "--run required for model audit")
    manifest, run = audit_run_identity(args, protocol, expected_status) if model_stage else (None, None)
    records = feature_stage(args, protocol)
    result = {"schema": "filang-geometry-information-verification-v1", "status": "PASS", "stage": "full" if full else args.stage,
              "protocol_sha256": digest(args.protocol), "verifier_sha256": digest(__file__),
              "native_records_checked": sum(r["records_checked"] for r in records),
              "all_raw_keys_and_projections_checked": True,
              "all_producer_feature_digests_checked": all(r["producer_feature_digests_checked"] for r in records),
              "scientific_models_checked": False, "features": records,
              "predecessor_binding": predecessor_binding(args, protocol)}
    if model_stage:
        result.update((full_stage if full else failed_stage)(args, protocol, records, manifest, run))
        # Rehash the manifest and every sealed file at the end as well, so an
        # artifact changed while being audited cannot inherit a stale receipt.
        audit_run_identity(args, protocol, expected_status)
        require(result["producer_manifest_sha256"] == digest(args.run / "manifest.json"), "producer changed during audit")
        if full:
            require(result["analysis_sha256"] == digest(args.run / "analysis.json"), "analysis changed during audit")
    result["elapsed_seconds"] = time.perf_counter() - started
    save_json(args.out, result)
    print(json.dumps({"status": "PASS", "stage": args.stage, "receipt": str(args.out)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("independent R1 audit: " + str(error), file=__import__("sys").stderr)
        raise SystemExit(2)
