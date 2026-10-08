#!/usr/bin/env python3
"""Independent audit of every eligible window, next-bar label and map count.

This script never imports Filang's native encoder or the analysis implementation.
Canonical geometry is reconstructed by independently sorting distinct endpoint
prices. Exact universe counts use occupied-level inclusion/exclusion with Python
integers, rather than the native chain-merging recurrence.

By default every event is reconstructed. --sample-per-task only reduces geometry
reconstruction; chronology, eligibility, labels, counts and checksums are still
checked exhaustively, and the receipt explicitly records the reduced scope.
An optional --analysis audit independently recalculates every candidate score,
validation selection, frozen probability, baseline and daily paired receipt.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import re
import sys
import time

import numpy as np


SPLITS = ("train", "validation", "test")
TARGETS = ("cc", "body")
SIGNS = ("down", "flat", "up")
COUNT_FIELDS = [f"{s}_{t}_{y}" for s in SPLITS for t in TARGETS for y in SIGNS]
PATTERN_FIELDS = ["pattern_id", "pattern", *COUNT_FIELDS]
EVENT_FIELDS = ["decision_timestamp", "target_timestamp", "split", "pattern_id",
                "target_cc", "target_body", "current_cc", "current_body"]
EVENT_DTYPE = np.dtype([("decision", "i8"), ("target", "i8"), ("split", "S10"),
                        ("pid", "u4"), ("cc", "i1"), ("body", "i1"),
                        ("current_cc", "i1"), ("current_body", "i1")])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def epoch(value):
    if isinstance(value, (int, float)) or str(value).isdigit():
        return int(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    require(parsed.tzinfo is None or parsed.utcoffset().total_seconds() == 0, "UTC date required")
    return int(parsed.replace(tzinfo=timezone.utc).timestamp())


def dump_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


@lru_cache(maxsize=32)
def domain_count(bars, mode):
    """Surjections of independent weak four-endpoint chains onto occupied levels."""
    weights = {"unoriented": (1, 3, 3, 1), "oriented": (1, 4, 5, 2)}[mode]
    require(1 <= bars <= 10, "unsupported verification count window")
    occupied = [0] * (4 * bars + 1)
    for levels in range(1, 4 * bars + 1):
        one_candle = sum(weight * math.comb(levels, k)
                         for k, weight in enumerate(weights, 1) if k <= levels)
        occupied[levels] = one_candle ** bars - sum(
            math.comb(levels, used) * occupied[used] for used in range(1, levels))
        require(occupied[levels] >= 0, "negative occupied-level term")
    return sum(occupied)


def canonical_pattern(candles, mode):
    boundaries, directions = [], []
    for open_, high, low, close in candles:
        require(all(math.isfinite(float(x)) for x in (open_, high, low, close)), "nonfinite feature")
        bottom, top = min(open_, close), max(open_, close)
        require(low <= bottom <= top <= high, "invalid feature OHLC")
        boundaries.append((low, bottom, top, high))
        directions.append("u" if close > open_ else "d" if close < open_ else "z")
    rank = {price: i for i, price in enumerate(sorted({p for row in boundaries for p in row}))}
    rows = []
    for i, row in enumerate(boundaries):
        text = ",".join(str(rank[value]) for value in row)
        if mode == "oriented":
            text += "," + directions[i]
        rows.append(text)
    return ("g1:o:" if mode == "oriented" else "g1:u:") + ";".join(rows)


def validate_pattern(pattern, bars, mode):
    prefix = "g1:o:" if mode == "oriented" else "g1:u:"
    require(pattern.startswith(prefix), "pattern prefix/mode")
    rows = pattern[len(prefix):].split(";")
    require(len(rows) == bars, "pattern candle count")
    seen = set()
    for row in rows:
        values = row.split(",")
        require(len(values) == (5 if mode == "oriented" else 4), "pattern row arity")
        require(all(re.fullmatch(r"0|[1-9][0-9]*", value) for value in values[:4]), "noncanonical rank")
        ranks = list(map(int, values[:4]))
        require(ranks == sorted(ranks), "body/wick ordering")
        seen.update(ranks)
        if mode == "oriented":
            require(values[4] in ("u", "d", "z"), "invalid body direction")
            require((ranks[1] == ranks[2]) == (values[4] == "z"), "flat body direction mismatch")
    require(seen == set(range(len(seen))), "global ranks are not dense")


def discover_tasks(root):
    tasks = []
    for path in sorted(Path(root).rglob("summary.json")):
        if not re.fullmatch(r"n[0-9]{2}-(unoriented|oriented)", path.parent.name):
            continue
        task = json.loads(path.read_text())
        task["path"] = path.parent
        require(task["status"] == "COMPLETE", "unfinished task")
        tasks.append(task)
    require(bool(tasks), "no native direction tasks")
    keys = [(t["interval_seconds"], t["bars"], t["mode"]) for t in tasks]
    require(len(keys) == len(set(keys)), "duplicate task identity")
    return sorted(tasks, key=lambda t: (t["interval_seconds"], t["bars"], t["mode"]))


def audit_artifacts(directory):
    path = Path(directory) / "artifacts.tsv"
    expected_seal = (Path(directory) / "artifacts.tsv.sha256").read_text().strip()
    require(re.fullmatch(r"[a-f0-9]{64}", expected_seal) is not None and sha256(path) == expected_seal,
            "native artifact manifest checksum")
    checked = []
    with path.open(newline="") as source:
        rows = csv.DictReader(source, delimiter="\t")
        require(rows.fieldnames == ["file", "bytes", "sha256"], "artifact manifest schema")
        for row in rows:
            require(row["file"] in ("events.tsv", "patterns.tsv", "summary.json", "task.identity", "timing.json"),
                    "unexpected artifact path")
            target = Path(directory) / row["file"]
            require(target.stat().st_size == int(row["bytes"]), "artifact length mismatch")
            require(sha256(target) == row["sha256"], "artifact digest mismatch: " + str(target))
            checked.append(row["file"])
    require(checked == ["events.tsv", "patterns.tsv", "summary.json", "task.identity", "timing.json"],
            "native artifact manifest entries/order")
    return expected_seal


def read_source(task, source_map=None):
    source_path = Path((source_map or {}).get(task["source_csv"], task["source_csv"]))
    require(sha256(source_path) == task["source_sha256"], "source CSV checksum")
    if "source_bytes" in task:
        require(source_path.stat().st_size == int(task["source_bytes"]), "source CSV size")
    with source_path.open() as source:
        require(source.readline().rstrip("\r\n") == "timestamp,open,high,low,close,volume", "OHLCV CSV schema")
    data = np.loadtxt(source_path, delimiter=",", skiprows=1, dtype=float, ndmin=2)
    require(data.shape[1] == 6 and len(data) >= 3, "OHLCV CSV dimensions")
    require(np.all(np.isfinite(data)), "nonfinite OHLCV value")
    times = data[:, 0].astype(np.int64)
    require(np.all(data[:, 0] == times), "noninteger timestamp")
    step = int(task["interval_seconds"])
    differences = np.diff(times)
    require(step > 0 and np.all(times % step == 0) and np.all(differences > 0)
            and np.all(differences % step == 0), "duplicate, unordered or off-grid source time")
    prices = np.ascontiguousarray(data[:, 1:5])
    require(np.all(prices > 0) and np.all(data[:, 5] >= 0), "OHLCV value domain")
    require(np.all(prices[:, 2] <= np.minimum(prices[:, 0], prices[:, 3])) and
            np.all(np.maximum(prices[:, 0], prices[:, 3]) <= prices[:, 1]), "invalid OHLC order")
    del data
    for field, value in (("input_rows", len(times)), ("first_timestamp", int(times[0])),
                         ("last_timestamp", int(times[-1])), ("gap_count", int((differences > step).sum())),
                         ("missing_grid_bars", int((differences // step - 1).sum()))):
        if field in task:
            require(int(task[field]) == value, "source metadata mismatch: " + field)
    return {"times": times, "prices": prices, "path": str(source_path),
            "sha256": task["source_sha256"], "interval_seconds": step}


def eligible_indices(source, task):
    times, step = source["times"], source["interval_seconds"]
    bounds = [epoch(task[k]) for k in ("history_start", "validation_start", "test_start", "end")]
    require(all(a < b for a, b in zip(bounds, bounds[1:])), "split boundary order")
    require(times[0] <= bounds[0] and times[-1] + step >= bounds[-1], "source does not span declared experiment")
    first, end = np.searchsorted(times, [bounds[0], bounds[-1]])
    n = int(task["bars"])
    indices = np.arange(int(first) + n - 1, int(end) - 1, dtype=np.int64)
    require(len(indices) > 0, "empty feature domain")
    contiguous = times[indices + 1] - times[indices - n + 1] == n * step
    splits = np.searchsorted(np.asarray(bounds[1:3]), times[indices], side="right")
    endings = np.asarray(bounds[1:])[splits]
    inside = (times[indices + 1] < endings) & (times[indices + 1] + step <= endings)
    eligible = contiguous & inside
    counters = {"candidate_decisions": len(indices), "gap_purged": int((~contiguous).sum()),
                "boundary_purged": int((contiguous & ~inside).sum()), "events": int(eligible.sum()),
                "selected_rows": int(end - first)}
    return indices[eligible], splits[eligible], counters


def read_patterns(task, validate=True):
    size = int(task["observed_patterns"])
    patterns = []
    counts = np.empty((size, 18), dtype=np.int64)
    with (task["path"] / "patterns.tsv").open(newline="") as source:
        reader = csv.reader(source, delimiter="\t")
        require(next(reader, None) == PATTERN_FIELDS, "pattern table schema")
        for index, row in enumerate(reader):
            require(index < size and len(row) == 20 and int(row[0]) == index,
                    "pattern table ID, arity or row count")
            if validate:
                validate_pattern(row[1], int(task["bars"]), task["mode"])
            patterns.append(row[1])
            counts[index] = [int(x) for x in row[2:]]
    require(len(patterns) == size and len(set(patterns)) == size, "duplicate or missing canonical pattern")
    require(np.all(counts >= 0), "negative catalogue count")
    require(np.all(counts[:, 0:3].sum(axis=1) == counts[:, 3:6].sum(axis=1)) and
            np.all(counts[:, 6:9].sum(axis=1) == counts[:, 9:12].sum(axis=1)) and
            np.all(counts[:, 12:15].sum(axis=1) == counts[:, 15:18].sum(axis=1)),
            "target totals disagree")
    return patterns, counts


def audit_task(task, source, sample_per_task=None):
    started = time.perf_counter()
    seal = audit_artifacts(task["path"])
    indices, splits, counters = eligible_indices(source, task)
    for field, expected in counters.items():
        if field in task:
            require(int(task[field]) == expected, f"native eligibility counter {field}")
    universe = domain_count(int(task["bars"]), task["mode"])
    require(str(universe) == task["universe_patterns"], "exact universe count mismatch")
    patterns, reported = read_patterns(task, validate=sample_per_task is not None)
    require(str(universe - len(patterns)) == task["unobserved_patterns"], "unobserved complement mismatch")
    expected = np.zeros_like(reported)
    checked = len(indices) if sample_per_task is None else min(sample_per_task, len(indices))
    sample = None if checked == len(indices) else set(np.linspace(0, len(indices) - 1, checked, dtype=int).tolist())
    seen = np.zeros(len(patterns), dtype=bool)
    next_id = 0
    times, prices = source["times"], source["prices"]
    n, mode = int(task["bars"]), task["mode"]
    close_sign = np.sign(np.diff(prices[:, 3])).astype(np.int8)
    body_sign = np.sign(prices[:, 3] - prices[:, 0]).astype(np.int8)
    with (task["path"] / "events.tsv").open(newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        require(next(reader, None) == EVENT_FIELDS, "event table schema")
        for ordinal, pair in enumerate(zip_longest(zip(indices, splits), reader)):
            reference, row = pair
            require(reference is not None and row is not None, "missing or extra native event")
            t, split = map(int, reference)
            require(len(row) == 8, "event row arity")
            decision, target, pid = int(row[0]), int(row[1]), int(row[3])
            require(decision == int(times[t]) and target == int(times[t + 1]) and row[2] == SPLITS[split],
                    "decision/target chronology or boundary split")
            require(0 <= pid < len(patterns), "pattern ID out of range")
            labels = tuple(map(int, row[4:]))
            correct = (int(close_sign[t]), int(body_sign[t + 1]), int(close_sign[t - 1]), int(body_sign[t]))
            require(labels == correct, "next/current direction label mismatch")
            if not seen[pid]:
                require(pid == next_id, "pattern IDs do not follow first occurrence")
                seen[pid], next_id = True, next_id + 1
            if sample is None or ordinal in sample:
                candles = prices[t - np.arange(n)]
                require(canonical_pattern(candles, mode) == patterns[pid],
                        f"canonical geometry mismatch at event {ordinal}, t={decision}")
            expected[pid, split * 6 + labels[0] + 1] += 1
            expected[pid, split * 6 + 3 + labels[1] + 1] += 1
    require(next_id == len(patterns) and np.array_equal(expected, reported), "pattern identity/count audit")
    training_observed = int((expected[:, :6].sum(axis=1) > 0).sum())
    require(training_observed == int(task["training_observed_patterns"]), "training observed count")
    require(str(universe - training_observed) == task["training_unobserved_patterns"], "training complement count")
    totals = expected.sum(axis=0).reshape((3, 2, 3))
    for si, split in enumerate(SPLITS):
        for ti, target in enumerate(TARGETS):
            for yi, sign in enumerate(SIGNS):
                require(int(task["split_counts"][split][target][sign]) == int(totals[si, ti, yi]),
                        "summary label count mismatch")
    return {"task": str(task["path"]), "status": "PASS", "bars": n, "mode": mode,
            "interval_seconds": source["interval_seconds"], "universe_patterns": str(universe),
            "observed_patterns": len(patterns), "unobserved_patterns": str(universe - len(patterns)),
            "training_observed_patterns": training_observed, **counters,
            "canonical_events_checked": checked, "all_canonical_events_checked": checked == len(indices),
            "all_event_labels_and_eligibility_checked": True, "all_catalogue_counts_checked": True,
            "artifact_manifest_sha256": seal, "source_sha256": source["sha256"],
            "elapsed_seconds": time.perf_counter() - started}


def close(actual, expected, label, tolerance=2e-12):
    require(actual is not None and math.isfinite(float(actual)) and
            math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance),
            f"{label}: {actual!r} != {expected!r}")
    return abs(float(actual) - float(expected))


def score_labels(labels, probabilities):
    labels = np.asarray(labels)
    probabilities = np.asarray(probabilities, dtype=float)
    valid = labels != 0
    y = labels[valid] > 0
    p = probabilities[valid]
    require(len(y) > 0 and np.all((p > 0) & (p < 1)), "invalid independent binary score")
    pred = p >= 0.5
    log_loss = float(np.mean(-np.log(np.where(y, p, 1 - p))))
    return {"n_binary": int(valid.sum()), "n_flat": int((~valid).sum()), "n_events": len(labels),
            "n_up": int(y.sum()), "n_down": int((~y).sum()), "up_rate": float(y.mean()),
            "log_loss": log_loss, "brier": float(np.mean((p - y.astype(float)) ** 2)),
            "accuracy": float(np.mean(pred == y)),
            "balanced_accuracy": float((np.mean(pred[y]) + np.mean(~pred[~y])) / 2)
            if np.any(y) and np.any(~y) else None,
            "mean_probability_up": float(p.mean()), "true_up": int((pred & y).sum()),
            "true_down": int((~pred & ~y).sum()), "false_up": int((pred & ~y).sum()),
            "false_down": int((~pred & y).sum())}


def compare_metrics(actual, expected, label):
    error = 0.0
    for key, value in expected.items():
        if value is None:
            require(actual[key] is None, label + " nullable metric")
        elif isinstance(value, int):
            require(actual[key] == value, label + " count: " + key)
        else:
            error = max(error, close(actual[key], value, label + ": " + key))
    return error


def event_array(task):
    return np.loadtxt(task["path"] / "events.tsv", delimiter="\t", skiprows=1,
                      dtype=EVENT_DTYPE, ndmin=1)


def independent_fit(events, target, fit_splits):
    fitting = np.isin(events["split"], [s.encode() for s in fit_splits])
    binary = fitting & (events[target] != 0)
    n_up = int((events[target][binary] > 0).sum())
    n = int(binary.sum())
    result = {"unconditional": (n_up + 0.5) / (n + 1), "conditionals": {}}
    for baseline, field in (("lag1", "current_cc"), ("current_body", "current_body")):
        probabilities, counts = [], []
        for state in (-1, 0, 1):
            selected = binary & (events[field] == state)
            up = int((events[target][selected] > 0).sum())
            down = int((events[target][selected] < 0).sum())
            probabilities.append((up + 0.5) / (up + down + 1))
            counts.append([down, up])
        result["conditionals"][baseline] = {"probabilities": np.asarray(probabilities), "counts": counts}
    return result


def independent_predictions(events, fit):
    return {"unconditional": np.full(len(events), fit["unconditional"]),
            "lag1": fit["conditionals"]["lag1"]["probabilities"][events["current_cc"].astype(int) + 1],
            "current_body": fit["conditionals"]["current_body"]["probabilities"][events["current_body"].astype(int) + 1]}


def independent_bootstrap(day_sums, block_days, replicates=2000, seed=20261008):
    """Independent prefix-sum resampling; no analyzer index tensor or helpers."""
    values = np.asarray(day_sums, dtype=float)
    days = len(values)
    require(days > 0 and values[:, 0].sum() > 0, "empty bootstrap audit")
    observed = values[:, 1:].sum(axis=0) / values[:, 0].sum()
    repeated = np.tile(values, (math.ceil(block_days / days) + 2, 1))
    prefix = np.vstack((np.zeros(3), np.cumsum(repeated, axis=0)))
    blocks = math.ceil(days / block_days)
    lengths = np.full(blocks, block_days, dtype=int)
    lengths[-1] = days - (blocks - 1) * block_days
    random = np.random.default_rng(seed)
    samples = np.empty((replicates, 2))
    for replica in range(replicates):
        starts = random.integers(0, days, size=blocks)
        totals = (prefix[starts + lengths] - prefix[starts]).sum(axis=0)
        require(totals[0] > 0, "empty bootstrap draw")
        samples[replica] = totals[1:] / totals[0]
    output = {}
    for i, name in enumerate(("log_loss_improvement", "accuracy_change")):
        output[name] = {"estimate": float(observed[i]),
                        "percentile_95_ci": np.percentile(samples[:, i], [2.5, 97.5]).tolist(),
                        "one_sided_p": float((1 + np.count_nonzero(samples[:, i] - observed[i] >= observed[i])) /
                                              (replicates + 1))}
    return output


def audit_analysis(root, analysis_dir, tasks, protocol_path=None):
    analysis_dir = Path(analysis_dir)
    result = json.loads((analysis_dir / "analysis.json").read_text())
    artifacts = json.loads((analysis_dir / "artifacts.json").read_text())
    for relative, metadata in artifacts["files"].items():
        path = (analysis_dir / relative).resolve()
        require(analysis_dir.resolve() in path.parents, "analysis artifact path traversal")
        require(path.stat().st_size == metadata["bytes"] and sha256(path) == metadata["sha256"],
                "analysis artifact checksum")
    if protocol_path is not None:
        require(result["protocol_sha256"] == sha256(protocol_path), "analysis protocol checksum")
    require(result["alpha_grid"] == [1, 10, 100, 1000], "analysis alpha grid")
    task_by_path = {str(t["path"].relative_to(root)): t for t in tasks}
    candidates = {(c["task"], c["target"], c["alpha"]): c for c in result["candidates"]}
    require(len(candidates) == len(tasks) * 2 * 4 == result["candidate_count"], "candidate coverage")
    selected = {(s["interval_seconds"], s["target"]): s for s in result["selected"]}
    max_error, scored = 0.0, 0
    expected_selection, frozen_receipts = {}, []
    frames = sorted({t["interval_seconds"] for t in tasks})
    for frame in frames:
        group = [t for t in tasks if t["interval_seconds"] == frame]
        longest = max(t["bars"] for t in group)
        reference = event_array(next(t for t in group if t["bars"] == longest))
        common = {s: reference["decision"][reference["split"] == s.encode()]
                  for s in ("validation", "test")}
        baseline_task = next((t for t in group if t["bars"] == 2 and t["mode"] == "oriented"),
                             min(group, key=lambda t: (t["bars"], t["mode"])))
        baseline_events = event_array(baseline_task)
        fits = {target: {"validation": independent_fit(baseline_events, target, ["train"]),
                         "test": independent_fit(baseline_events, target, ["train", "validation"])}
                for target in TARGETS}
        frame_rows = {target: [] for target in TARGETS}
        for task in group:
            relative = str(task["path"].relative_to(root))
            _, counts = read_patterns(task, validate=False)
            counts = counts.reshape((-1, 3, 2, 3))
            events = event_array(task)
            for ti, target in enumerate(TARGETS):
                for period in ("validation", "test"):
                    # independent set-membership path, distinct from analyzer's searchsorted
                    mask = (events["split"] == period.encode()) & np.isin(events["decision"], common[period])
                    evaluation = events[mask]
                    require(np.array_equal(evaluation["decision"], common[period]), "common comparison timeline")
                    fit_counts = counts[:, 0, ti, :] if period == "validation" else counts[:, :2, ti, :].sum(axis=1)
                    up, down = fit_counts[:, 2].astype(float), fit_counts[:, 0].astype(float)
                    prior = fits[target][period]["unconditional"]
                    baselines = independent_predictions(evaluation, fits[target][period])
                    baseline_scores = {name: score_labels(evaluation[target], p) for name, p in baselines.items()}
                    for alpha in (1, 10, 100, 1000):
                        candidate = candidates[(relative, target, alpha)]
                        probability = (up + alpha * prior) / (up + down + alpha)
                        predictions = probability[evaluation["pid"]]
                        scores = score_labels(evaluation[target], predictions)
                        max_error = max(max_error, compare_metrics(candidate[period], scores, "candidate " + period))
                        for name, score in baseline_scores.items():
                            max_error = max(max_error, compare_metrics(candidate[period + "_baselines"][name], score, "baseline " + period))
                        scored += 1
                        if period == "validation":
                            frame_rows[target].append((scores["log_loss"], task["bars"],
                                                       0 if task["mode"] == "unoriented" else 1, alpha,
                                                       relative, task["mode"]))
                    winner = selected[(frame, target)]
                    if winner["task"] != relative or period != "test":
                        continue
                    require(winner["pattern_table_sha256"] == sha256(task["path"] / "patterns.tsv"),
                            "frozen pattern table binding")
                    alpha = int(winner["alpha"])
                    probability = (up + alpha * prior) / (up + down + alpha)
                    frozen_path = analysis_dir / winner["probabilities_file"]
                    require(sha256(frozen_path) == winner["probabilities_sha256"], "frozen probabilities checksum")
                    with frozen_path.open(newline="") as source:
                        reader = csv.reader(source, delimiter="\t")
                        require(next(reader, None) == ["pattern_id", "fit_down", "fit_flat", "fit_up", "p_up", "empirical_up_rate"],
                                "frozen probability schema")
                        for i, pair in enumerate(zip_longest(reader, probability)):
                            row, expected_p = pair
                            require(row is not None and expected_p is not None and int(row[0]) == i, "frozen probability coverage")
                            require(list(map(int, row[1:4])) == list(map(int, fit_counts[i])), "frozen fitting counts")
                            max_error = max(max_error, close(float(row[4]), expected_p, "frozen probability"))
                            if up[i] + down[i]:
                                max_error = max(max_error, close(float(row[5]), up[i] / (up[i] + down[i]), "empirical rate"))
                            else:
                                require(row[5] == "", "unobserved pattern must have no empirical rate")
                    max_error = max(max_error, close(winner["global_fit_probability"], prior, "shared unconditional prior"),
                                    close(winner["unseen_pattern_probability"], prior, "unseen fallback"))
                    model = winner["baseline_model"]
                    for name, field in (("lag1", "lag1"), ("current_body", "current_body")):
                        condition = fits[target]["test"]["conditionals"][name]
                        require(model[field + "_fit_down_up_by_current_sign"] == condition["counts"], "frozen baseline count")
                        for a, b in zip(model[field + "_probability_by_current_sign"], condition["probabilities"]):
                            max_error = max(max_error, close(a, b, "frozen baseline probability"))
                    daily_path = analysis_dir / winner["daily_file"]
                    require(sha256(daily_path) == winner["daily_sha256"], "daily receipt checksum")
                    binary = evaluation[target] != 0
                    y = evaluation[target][binary] > 0
                    p = probability[evaluation["pid"]][binary]
                    geometry_loss = -np.log(np.where(y, p, 1 - p))
                    geometry_correct = ((p >= .5) == y).astype(float)
                    days = evaluation["target"][binary] // 86400
                    require(np.all(np.diff(days) >= 0), "daily target ordering")
                    primary = "lag1" if target == "cc" else "current_body"
                    day_sums = []
                    with daily_path.open(newline="") as stream:
                        reader = csv.DictReader(stream)
                        expected_days = range(epoch(task["test_start"]) // 86400,
                                              (epoch(task["end"]) + 86399) // 86400)
                        for pair in zip_longest(expected_days, reader):
                            day, row = pair
                            require(day is not None and row is not None and epoch(row["date"]) // 86400 == day,
                                    "daily timeline coverage")
                            start, stop = np.searchsorted(days, [day, day + 1])
                            require(int(row["n_binary"]) == int(stop - start), "daily binary count")
                            expected_fields = {"geometry_loss_sum": float(geometry_loss[start:stop].sum()),
                                               "geometry_correct_sum": float(geometry_correct[start:stop].sum())}
                            for name, values in baselines.items():
                                b = values[binary][start:stop]
                                actual_y = y[start:stop]
                                loss = -np.log(np.where(actual_y, b, 1 - b))
                                correct = ((b >= .5) == actual_y).astype(float)
                                expected_fields[name + "_loss_sum"] = float(loss.sum())
                                expected_fields[name + "_correct_sum"] = float(correct.sum())
                                expected_fields[name + "_loss_improvement_sum"] = float((loss - geometry_loss[start:stop]).sum())
                                expected_fields[name + "_accuracy_change_sum"] = float((geometry_correct[start:stop] - correct).sum())
                            for field, expected_value in expected_fields.items():
                                max_error = max(max_error, close(float(row[field]), expected_value, "daily " + field, 2e-11))
                            day_sums.append((int(row["n_binary"]), expected_fields[primary + "_loss_improvement_sum"],
                                             expected_fields[primary + "_accuracy_change_sum"]))
                    for block in (7, 1, 28):
                        expected_bootstrap = independent_bootstrap(day_sums, block)
                        actual_bootstrap = winner["inference"][primary][str(block)]
                        require(actual_bootstrap["seed"] == 20261008 and actual_bootstrap["replicates"] == 2000
                                and actual_bootstrap["block_days"] == block, "bootstrap settings")
                        for statistic in ("log_loss_improvement", "accuracy_change"):
                            for field in ("estimate", "one_sided_p"):
                                max_error = max(max_error, close(actual_bootstrap[statistic][field],
                                                                expected_bootstrap[statistic][field], "bootstrap " + field, 2e-11))
                            for a, b in zip(actual_bootstrap[statistic]["percentile_95_ci"],
                                            expected_bootstrap[statistic]["percentile_95_ci"]):
                                max_error = max(max_error, close(a, b, "bootstrap confidence bound", 2e-11))
                    frozen_receipts.append({"interval_seconds": frame, "target": target, "bars": task["bars"],
                                            "mode": task["mode"], "alpha": alpha, "frozen_patterns_checked": len(probability),
                                            "test_binary_predictions_checked": int(binary.sum()), "daily_rows_checked": len(day_sums),
                                            "probabilities_sha256": winner["probabilities_sha256"],
                                            "primary_bootstrap_blocks_independently_checked": [7, 1, 28],
                                            "primary_daily_log_loss_improvement": math.fsum(row[1] for row in day_sums) /
                                                sum(row[0] for row in day_sums), "status": "PASS"})
        for target in TARGETS:
            chosen = min(frame_rows[target])
            winner = selected[(frame, target)]
            # A different summation order can differ at roundoff; verify the selected
            # row is within 2e-12 of the independently minimal loss, then apply the
            # exact analyzer order recorded in the immutable candidate table.
            require(winner["validation"]["log_loss"] <= chosen[0] + 2e-12, "validation winner is not minimal")
            supplied = [c for c in result["candidates"] if c["interval_seconds"] == frame and c["target"] == target]
            minimum = min(c["validation"]["log_loss"] for c in supplied)
            require(result["selection_roundoff_tolerance"] == 1e-12, "selection roundoff tolerance")
            declared = min((c for c in supplied if c["validation"]["log_loss"] <= minimum + 1e-12),
                           key=lambda c: (c["bars"], 0 if c["mode"] == "unoriented" else 1, c["alpha"]))
            require((winner["task"], winner["alpha"]) == (declared["task"], declared["alpha"]), "selection tie break")
            expected_selection[f"{frame}:{target}"] = {"task": winner["task"], "alpha": winner["alpha"]}
    for target in TARGETS:
        family = [selected[(frame, target)] for frame in frames]
        ordered = sorted(family, key=lambda row: row["inference"][row["primary_baseline"]]["7"]["log_loss_improvement"]["one_sided_p"])
        previous = 0.0
        for rank, row in enumerate(ordered):
            raw = row["inference"][row["primary_baseline"]]["7"]["log_loss_improvement"]["one_sided_p"]
            previous = min(1.0, max(previous, (len(ordered) - rank) * raw))
            max_error = max(max_error, close(row["holm_adjusted_primary_log_loss_p"], previous, "Holm correction"))
            require(row["holm_family_size"] == len(ordered), "Holm family size")
    return {"status": "PASS", "analysis_sha256": sha256(analysis_dir / "analysis.json"),
            "candidate_period_scores_checked": scored, "selected_models_checked": len(frozen_receipts),
            "selection": expected_selection, "max_absolute_metric_error": max_error,
            "frozen_models": frozen_receipts,
            "scope": "independent candidate and baseline scores, validation-only selection, frozen probabilities, every daily sum, primary-comparator 1/7/28-day bootstrap and Holm corrections"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-per-task", type=int)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--source-map", type=Path, help="JSON mapping recorded source CSV paths to relocated exact-byte CSVs")
    parser.add_argument("--analysis-only", action="store_true",
                        help="recheck analysis against existing native artifacts without claiming a new geometry audit")
    args = parser.parse_args(argv)
    require(args.sample_per_task is None or args.sample_per_task > 0, "sample count must be positive")
    require(not args.analysis_only or args.analysis is not None, "analysis-only requires --analysis")
    started = time.perf_counter()
    root = args.runs.resolve()
    tasks = discover_tasks(root)
    source_map = json.loads(args.source_map.read_text()) if args.source_map else {}
    records, sources = [], {}
    if not args.analysis_only:
        for task in tasks:
            key = (task["source_csv"], task["source_sha256"], int(task["interval_seconds"]))
            if key not in sources:
                # Only one timeframe CSV remains resident; per-task state is freed.
                sources.clear()
                sources[key] = read_source(task, source_map)
            record = audit_task(task, sources[key], args.sample_per_task)
            record["task"] = str(task["path"].relative_to(root))
            records.append(record)
            print(json.dumps({"verified": record["task"], "events": record["events"],
                              "canonical_checked": record["canonical_events_checked"],
                              "elapsed_seconds": record["elapsed_seconds"]}), flush=True)
        sources.clear()
    analysis = audit_analysis(root, args.analysis, tasks, args.protocol) if args.analysis else None
    receipt = {"version": 1, "status": "PASS", "verifier_sha256": sha256(__file__),
               "independent_encoder": "sort distinct OHLC body/wick endpoints; exact equality; current-first",
               "independent_counter": "occupied-level inclusion/exclusion with Python arbitrary-precision integers",
               "task_count": len(records), "events_checked": sum(r["events"] for r in records),
               "canonical_events_checked": sum(r["canonical_events_checked"] for r in records),
               "all_native_geometry_reconstructed": bool(records) and all(r["all_canonical_events_checked"] for r in records),
               "sample_per_task": args.sample_per_task, "analysis_only": args.analysis_only,
               "tasks": records, "analysis": analysis,
               "elapsed_seconds": time.perf_counter() - started}
    dump_json(args.out, receipt)
    print(json.dumps({"status": "PASS", "receipt": str(args.out), "tasks": len(records),
                      "events_checked": receipt["events_checked"],
                      "all_native_geometry_reconstructed": receipt["all_native_geometry_reconstructed"],
                      "elapsed_seconds": receipt["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print("direction verification: " + str(error), file=sys.stderr)
        raise SystemExit(2)
