#!/usr/bin/env python3
"""Frozen, chronological analysis of the native complete-geometry direction map.

The native map is descriptive and may catalogue identities first seen in test.
Only training labels fit a validation prediction. Validation selects exactly one
(length, orientation, alpha) per timeframe and target; train+validation then fit
the frozen test predictor. No test label participates in either operation.

NumPy is the only non-standard-library dependency. The primary paired bootstrap
uses UTC target-day aggregates, circular seven-day blocks, 2,000 resamples and a
fixed seed. One- and 28-day blocks are declared sensitivity analyses.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
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
ALPHAS = (1, 10, 100, 1000)
THRESHOLDS = (1, 5, 20, 100)
BOOTSTRAP_SEED = 20261008
BOOTSTRAP_REPLICATES = 2000
BLOCK_DAYS = (7, 1, 28)
SELECTION_TOLERANCE = 1e-12
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
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def epoch(value):
    if isinstance(value, (int, float)) or str(value).isdigit():
        return int(value)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    require(parsed.tzinfo is None or parsed.utcoffset().total_seconds() == 0,
            "protocol dates must use UTC")
    return int(parsed.replace(tzinfo=timezone.utc).timestamp())


def dump_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def read_protocol(path):
    if path is None:
        return {}, None
    protocol = json.loads(Path(path).read_text())
    settings = protocol.get("analysis", {})
    require(tuple(settings.get("alpha_grid", ALPHAS)) == ALPHAS, "undeclared alpha grid")
    require(settings.get("selection_metric", "binary_log_loss") == "binary_log_loss",
            "undeclared selection criterion")
    require(settings.get("selection_tolerance", SELECTION_TOLERANCE) == SELECTION_TOLERANCE,
            "undeclared selection tolerance")
    require(tuple(settings.get("support_thresholds", THRESHOLDS)) == THRESHOLDS,
            "undeclared support thresholds")
    bootstrap = settings.get("bootstrap", {})
    require(tuple(bootstrap.get("block_days", BLOCK_DAYS)) == BLOCK_DAYS,
            "undeclared bootstrap blocks")
    require(bootstrap.get("replicates", BOOTSTRAP_REPLICATES) == BOOTSTRAP_REPLICATES,
            "undeclared bootstrap replicate count")
    require(bootstrap.get("seed", BOOTSTRAP_SEED) == BOOTSTRAP_SEED,
            "undeclared bootstrap seed")
    require(bootstrap.get("unit", "UTC_day") == "UTC_day", "bootstrap unit must be UTC day")
    return protocol, sha256(path)


def discover_tasks(root):
    tasks = []
    for path in sorted(Path(root).rglob("summary.json")):
        if not re.fullmatch(r"n[0-9]{2}-(unoriented|oriented)", path.parent.name):
            continue
        info = json.loads(path.read_text())
        require(info["mode"] in ("oriented", "unoriented"), "invalid task mode")
        require(2 <= int(info["bars"]) <= 10, "invalid direction window")
        require((path.parent / "patterns.tsv").is_file() and
                (path.parent / "events.tsv").is_file(), "incomplete native task")
        info = dict(info)
        info["path"] = path.parent
        info["task_id"] = path.parent.name
        info["interval_seconds"] = int(info["interval_seconds"])
        info["bars"] = int(info["bars"])
        tasks.append(info)
    require(bool(tasks), "no native direction tasks found")
    keys = [(t["interval_seconds"], t["bars"], t["mode"]) for t in tasks]
    require(len(keys) == len(set(keys)), "duplicate timeframe/window/mode task")
    return sorted(tasks, key=lambda t: (t["interval_seconds"], t["bars"], t["mode"]))


def read_counts(task):
    path = task["path"] / "patterns.tsv"
    with path.open() as source:
        require(source.readline().rstrip("\n\r").split("\t") == PATTERN_FIELDS,
                f"pattern schema mismatch: {path}")
    matrix = np.loadtxt(path, delimiter="\t", skiprows=1, dtype=np.int64,
                        usecols=(0, *range(2, 20)), ndmin=2)
    require(matrix.shape[1] == 19 and matrix.shape[0] > 0, "empty or invalid pattern matrix")
    require(np.array_equal(matrix[:, 0], np.arange(len(matrix))),
            "pattern IDs must be contiguous from zero")
    counts = np.ascontiguousarray(matrix[:, 1:].reshape((-1, 3, 2, 3)))
    require(np.all(counts >= 0), "negative pattern counts")
    require(np.all(counts.sum(axis=3)[:, :, 0] == counts.sum(axis=3)[:, :, 1]),
            "target count totals disagree")
    require(len(counts) == int(task["observed_patterns"]), "observed pattern count mismatch")
    return counts


def read_events(task):
    path = task["path"] / "events.tsv"
    with path.open() as source:
        require(source.readline().rstrip("\n\r").split("\t") == EVENT_FIELDS,
                f"event schema mismatch: {path}")
    events = np.loadtxt(path, delimiter="\t", skiprows=1, dtype=EVENT_DTYPE, ndmin=1)
    require(len(events) == int(task["events"]), "event count mismatch")
    require(len(events) > 0 and np.all(np.diff(events["decision"]) > 0),
            "events must be strictly chronological")
    require(np.all(np.isin(events["split"], [s.encode() for s in SPLITS])), "invalid event split")
    for field in ("cc", "body", "current_cc", "current_body"):
        require(np.all(np.abs(events[field].astype(np.int16)) <= 1), "invalid sign label")
    require(int(events["pid"].max()) < int(task["observed_patterns"]), "event pattern ID out of bounds")
    return events


def common_decisions(tasks):
    """Identical future outcomes for all candidates, even around source gaps."""
    longest = max(t["bars"] for t in tasks)
    reference = next(t for t in tasks if t["bars"] == longest)
    events = read_events(reference)
    return {s: events["decision"][events["split"] == s.encode()].copy()
            for s in ("validation", "test")}, longest


def on_common_timeline(events, times):
    if not len(times):
        return np.zeros(len(events), dtype=bool)
    index = np.searchsorted(times, events["decision"])
    return (index < len(times)) & (times[np.minimum(index, len(times) - 1)] == events["decision"])


def event_counts(events, mask, target, size):
    ids = events["pid"][mask].astype(np.int64)
    labels = events[target][mask].astype(np.int64) + 1
    return np.bincount(ids * 3 + labels, minlength=size * 3).reshape((size, 3))


def global_probability(counts):
    down, _, up = counts.sum(axis=0)
    return float((float(up) + 0.5) / (float(down + up) + 1.0))


def geometry_probability(counts, alpha, prior=None):
    prior = global_probability(counts) if prior is None else float(prior)
    binary = counts[:, 0] + counts[:, 2]
    probability = (counts[:, 2].astype(float) + alpha * prior) / (binary + alpha)
    probability[binary == 0] = prior
    return probability, prior


def metrics(counts, probability):
    probability = np.asarray(probability, dtype=float)
    require(np.all(np.isfinite(probability)) and np.all((probability > 0) & (probability < 1)),
            "scored probabilities must lie strictly between zero and one")
    down = counts[:, 0].astype(float)
    up = counts[:, 2].astype(float)
    n_down, n_up = int(down.sum()), int(up.sum())
    n_binary = n_down + n_up
    require(n_binary > 0, "no binary outcomes in scoring period")
    prediction = probability >= 0.5
    true_up = int(up[prediction].sum())
    true_down = int(down[~prediction].sum())
    loss = float((-np.log(probability) * up - np.log1p(-probability) * down).sum() / n_binary)
    brier = float((((1 - probability) ** 2) * up + probability ** 2 * down).sum() / n_binary)
    return {"n_events": int(counts.sum()), "n_binary": n_binary,
            "n_flat": int(counts[:, 1].sum()), "n_up": n_up, "n_down": n_down,
            "up_rate": n_up / n_binary, "log_loss": loss, "brier": brier,
            "accuracy": (true_up + true_down) / n_binary,
            "balanced_accuracy": ((true_up / n_up + true_down / n_down) / 2
                                   if n_up and n_down else None),
            "mean_probability_up": float((probability * (up + down)).sum() / n_binary),
            "true_up": true_up, "true_down": true_down,
            "false_up": n_down - true_down, "false_down": n_up - true_up}


def conditional_fit(events, mask, target, current):
    mask = mask & (events[target] != 0)
    state = events[current][mask].astype(np.int64) + 1
    outcome = (events[target][mask] > 0).astype(np.int64)
    counts = np.bincount(state * 2 + outcome, minlength=6).reshape((3, 2))
    return (counts[:, 1] + 0.5) / (counts.sum(axis=1) + 1.0), counts


def event_metrics(events, mask, target, probability):
    labels = events[target][mask]
    counts = np.column_stack((labels < 0, labels == 0, labels > 0)).astype(np.int64)
    return metrics(counts, np.asarray(probability))


def baseline_set(events, fit_mask, score_mask, target, prior):
    lag_p, lag_counts = conditional_fit(events, fit_mask, target, "current_cc")
    body_p, body_counts = conditional_fit(events, fit_mask, target, "current_body")
    predictions = {"unconditional": np.full(int(score_mask.sum()), prior),
                   "lag1": lag_p[events["current_cc"][score_mask].astype(int) + 1],
                   "current_body": body_p[events["current_body"][score_mask].astype(int) + 1]}
    result = {name: event_metrics(events, score_mask, target, p)
              for name, p in predictions.items()}
    labels = events[target][score_mask]
    for field in ("current_cc", "current_body"):
        current = events[field][score_mask]
        active = (labels != 0) & (current != 0)
        total = int(active.sum())
        momentum_correct = int((labels[active] == current[active]).sum())
        result[field + "_momentum_reversal"] = {
            "n_binary_with_nonflat_current": total,
            "abstained_flat_current": int(((labels != 0) & (current == 0)).sum()),
            "momentum_accuracy": momentum_correct / total if total else None,
            "reversal_accuracy": 1 - momentum_correct / total if total else None}
    model = {"unconditional_probability": prior,
             "lag1_probability_by_current_sign": lag_p.tolist(),
             "lag1_fit_down_up_by_current_sign": lag_counts.tolist(),
             "current_body_probability_by_current_sign": body_p.tolist(),
             "current_body_fit_down_up_by_current_sign": body_counts.tolist(),
             "current_sign_order": [-1, 0, 1]}
    return result, model, predictions


def support_summary(fit_counts, score_counts):
    support = fit_counts.sum(axis=1)
    score_binary = score_counts[:, 0] + score_counts[:, 2]
    total = int(score_binary.sum())
    total_events = int(score_counts.sum())
    return {"support_definition": "all eligible fitting occurrences, including flat targets",
            "fit_observed_patterns": int((support > 0).sum()),
            "fit_singleton_patterns": int((support == 1).sum()),
            "fit_patterns_with_at_most_5_occurrences": int(((support > 0) & (support <= 5)).sum()),
            "evaluation_observed_patterns": int((score_counts.sum(axis=1) > 0).sum()),
            "binary_unseen_in_fit": int(score_binary[support == 0].sum()),
            "binary_unseen_fraction": float(score_binary[support == 0].sum() / total),
            "thresholds": {str(k): {
                "binary_events": int(score_binary[support >= k].sum()),
                "binary_fraction": float(score_binary[support >= k].sum() / total),
                "all_events": int(score_counts[support >= k].sum()),
                "all_event_fraction": float(score_counts[support >= k].sum() / total_events)}
                for k in THRESHOLDS}}


def candidate_key(row):
    return (row["bars"], 0 if row["mode"] == "unoriented" else 1, row["alpha"])


def select_candidate(rows):
    """Ignore arithmetic roundoff when equivalent predictions have equal loss."""
    rows = list(rows)
    minimum = min(row["validation"]["log_loss"] for row in rows)
    return min((row for row in rows if row["validation"]["log_loss"] <= minimum + SELECTION_TOLERANCE),
               key=candidate_key)


def daily_receipt(events, mask, target, geometry, baselines, start, end):
    """Sums, rather than day means, preserve exact observation weighting."""
    begin_day = epoch(start) // 86400
    end_day = (epoch(end) + 86399) // 86400
    days = np.arange(begin_day, end_day, dtype=np.int64)
    labels = events[target][mask]
    binary = labels != 0
    y = labels[binary] > 0
    day_index = events["target"][mask][binary] // 86400 - begin_day
    require(np.all((day_index >= 0) & (day_index < len(days))), "test day outside protocol")
    n = np.bincount(day_index, minlength=len(days)).astype(np.int64)
    g = geometry[binary]
    gl = np.where(y, -np.log(g), -np.log1p(-g))
    gc = (g >= 0.5) == y
    result = {"utc_day": days, "n_binary": n,
              "geometry_loss_sum": np.bincount(day_index, weights=gl, minlength=len(days)),
              "geometry_correct_sum": np.bincount(day_index, weights=gc.astype(float), minlength=len(days))}
    for name, pred in baselines.items():
        p = pred[binary]
        loss = np.where(y, -np.log(p), -np.log1p(-p))
        correct = (p >= 0.5) == y
        result[name + "_loss_sum"] = np.bincount(day_index, weights=loss, minlength=len(days))
        result[name + "_correct_sum"] = np.bincount(day_index, weights=correct.astype(float), minlength=len(days))
        result[name + "_loss_improvement_sum"] = np.bincount(day_index, weights=loss - gl, minlength=len(days))
        result[name + "_accuracy_change_sum"] = np.bincount(
            day_index, weights=gc.astype(float) - correct.astype(float), minlength=len(days))
    return result


def paired_bootstrap(daily, baseline, block_days=7, replicates=2000, seed=BOOTSTRAP_SEED):
    n = np.asarray(daily["n_binary"], dtype=float)
    require(len(n) > 0 and n.sum() > 0 and block_days > 0 and replicates > 0,
            "invalid bootstrap domain")
    deltas = np.column_stack((daily[baseline + "_loss_improvement_sum"],
                              daily[baseline + "_accuracy_change_sum"]))
    observed = deltas.sum(axis=0) / n.sum()
    rng = np.random.default_rng(seed)
    samples = np.empty((replicates, 2), dtype=float)
    blocks = math.ceil(len(n) / block_days)
    offsets = np.arange(block_days)
    for first in range(0, replicates, 128):
        stop = min(first + 128, replicates)
        starts = rng.integers(0, len(n), size=(stop - first, blocks))
        indices = ((starts[:, :, None] + offsets) % len(n)).reshape(stop - first, -1)[:, :len(n)]
        denominators = n[indices].sum(axis=1)
        require(np.all(denominators > 0), "bootstrap draw contains no binary outcomes")
        samples[first:stop] = deltas[indices].sum(axis=1) / denominators[:, None]
    result = {"unit": "UTC target day", "method": "paired circular moving-block bootstrap",
              "block_days": block_days, "replicates": replicates, "seed": seed,
              "days_including_empty": len(n), "binary_events": int(n.sum()),
              "alternative": "geometry improves over the named baseline",
              "p_value_method": "one-sided centered-null bootstrap; (exceedances+1)/(replicates+1)"}
    for col, name in enumerate(("log_loss_improvement", "accuracy_change")):
        centered = samples[:, col] - observed[col]
        result[name] = {"estimate": float(observed[col]),
                       "percentile_95_ci": np.quantile(samples[:, col], [0.025, 0.975]).tolist(),
                       "one_sided_p": float((1 + (centered >= observed[col]).sum()) / (replicates + 1))}
    return result


def holm_adjust(p_values):
    order = sorted(range(len(p_values)), key=lambda i: (p_values[i], i))
    adjusted = [0.0] * len(p_values)
    previous = 0.0
    for rank, index in enumerate(order):
        previous = max(previous, (len(order) - rank) * p_values[index])
        adjusted[index] = min(1.0, previous)
    return adjusted


def write_daily(path, daily):
    fields = list(daily)
    with Path(path).open("w", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(["date", *fields[1:]])
        for i, day in enumerate(daily["utc_day"]):
            date = datetime.fromtimestamp(int(day) * 86400, timezone.utc).date().isoformat()
            writer.writerow([date, *[int(daily[k][i]) if k == "n_binary" else format(float(daily[k][i]), ".17g")
                                     for k in fields[1:]]])


def write_probabilities(path, fit_counts, probability):
    with Path(path).open("w", newline="") as destination:
        writer = csv.writer(destination, delimiter="\t")
        writer.writerow(["pattern_id", "fit_down", "fit_flat", "fit_up", "p_up", "empirical_up_rate"])
        for i, (counts, p) in enumerate(zip(fit_counts, probability)):
            down, flat, up = map(int, counts)
            writer.writerow([i, down, flat, up, format(float(p), ".17g"),
                             format(up / (up + down), ".17g") if up + down else ""])


def public_task(task, root):
    return {"task": str(task["path"].relative_to(root)), "task_id": task["task_id"],
            "interval_seconds": task["interval_seconds"], "bars": task["bars"], "mode": task["mode"],
            "universe_patterns": str(task["universe_patterns"]),
            "observed_patterns": int(task["observed_patterns"]),
            "unobserved_patterns": str(task["unobserved_patterns"]),
            "training_observed_patterns": int(task["training_observed_patterns"]),
            "training_unobserved_patterns": str(task["training_unobserved_patterns"]),
            "source_sha256": task["source_sha256"],
            "summary_sha256": sha256(task["path"] / "summary.json"),
            "patterns_sha256": sha256(task["path"] / "patterns.tsv"),
            "events_sha256": sha256(task["path"] / "events.tsv")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--allow-partial", action="store_true",
                        help="explicitly analyze an incomplete design; never label it the complete five-test family")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    root, out = args.runs.resolve(), args.out.resolve()
    protocol_path = args.protocol or (root / "protocol.json" if (root / "protocol.json").is_file() else None)
    protocol, protocol_sha = read_protocol(protocol_path)
    tasks = discover_tasks(root)
    frames = sorted({t["interval_seconds"] for t in tasks})
    expected_frames = {900, 1800, 3600, 7200, 14400}
    full = set(frames) == expected_frames and all(
        {(t["bars"], t["mode"]) for t in tasks if t["interval_seconds"] == frame} ==
        {(n, mode) for n in range(2, 11) for mode in ("oriented", "unoriented")}
        for frame in frames)
    require(full or args.allow_partial, "incomplete 5-timeframe x 9-length x 2-mode design; use --allow-partial explicitly")
    for task in tasks:
        for field in ("history_start", "validation_start", "test_start", "end"):
            if field in protocol:
                require(epoch(task[field]) == epoch(protocol[field]), "native/protocol date mismatch: " + field)
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected").mkdir(exist_ok=True)
    candidates, selected, task_records = [], [], []
    for frame in frames:
        group = [t for t in tasks if t["interval_seconds"] == frame]
        common, max_bars = common_decisions(group)
        for period in ("validation", "test"):
            require(len(common[period]) > 0, f"empty common {period} sample")
        baseline_task = next((t for t in group if t["bars"] == 2 and t["mode"] == "oriented"),
                             min(group, key=lambda t: (t["bars"], t["mode"])))
        reference_counts, reference_events = read_counts(baseline_task), read_events(baseline_task)
        reference_masks = {s: reference_events["split"] == s.encode() for s in SPLITS}
        reference_scoring = {s: reference_masks[s] & on_common_timeline(reference_events, common[s])
                             for s in common}
        shared = {}
        for ti, target in enumerate(TARGETS):
            train_prior = global_probability(reference_counts[:, 0, ti, :])
            refit_prior = global_probability(reference_counts[:, :2, ti, :].sum(axis=1))
            val_baselines, _, _ = baseline_set(reference_events, reference_masks["train"],
                                               reference_scoring["validation"], target, train_prior)
            test_baselines, baseline_model, test_predictions = baseline_set(
                reference_events, reference_masks["train"] | reference_masks["validation"],
                reference_scoring["test"], target, refit_prior)
            baseline_model["shared_reference_task"] = str(baseline_task["path"].relative_to(root))
            shared[target] = {"train_prior": train_prior, "refit_prior": refit_prior,
                              "val_baselines": val_baselines, "test_baselines": test_baselines,
                              "baseline_model": baseline_model, "test_predictions": test_predictions}
        frame_candidates = []
        for task in group:
            counts, events = read_counts(task), read_events(task)
            masks = {s: events["split"] == s.encode() for s in SPLITS}
            scoring_masks = {s: masks[s] & on_common_timeline(events, common[s])
                             for s in ("validation", "test")}
            require(all(int(scoring_masks[s].sum()) == len(common[s]) for s in common),
                    "a shorter task is missing a longest-window comparison event")
            task_record = public_task(task, root)
            task_record["mapped_patterns_by_split"] = {
                s: int((counts[:, i, 0, :].sum(axis=1) > 0).sum()) for i, s in enumerate(SPLITS)}
            task_record["all_native_events_by_split"] = {s: int(masks[s].sum()) for s in SPLITS}
            task_record["common_scored_events_by_split"] = {s: int(scoring_masks[s].sum()) for s in common}
            task_records.append(task_record)
            for ti, target in enumerate(TARGETS):
                train_counts = counts[:, 0, ti, :]
                fit_counts = counts[:, :2, ti, :].sum(axis=1)
                val_counts = event_counts(events, scoring_masks["validation"], target, len(counts))
                test_counts = event_counts(events, scoring_masks["test"], target, len(counts))
                val_baselines = shared[target]["val_baselines"]
                test_baselines = shared[target]["test_baselines"]
                val_support = support_summary(train_counts, val_counts)
                test_support = support_summary(fit_counts, test_counts)
                for alpha in ALPHAS:
                    val_p, _ = geometry_probability(train_counts, alpha, shared[target]["train_prior"])
                    test_p, _ = geometry_probability(fit_counts, alpha, shared[target]["refit_prior"])
                    row = {"interval_seconds": frame, "timeframe_minutes": frame // 60,
                           "task": task_record["task"], "task_id": task["task_id"],
                           "bars": task["bars"], "mode": task["mode"], "target": target, "alpha": alpha,
                           "validation": metrics(val_counts, val_p), "test": metrics(test_counts, test_p),
                           "validation_baselines": val_baselines, "test_baselines": test_baselines,
                           "validation_support": val_support, "test_support": test_support,
                           "comparison_max_bars": max_bars,
                           "heldout_interpretation": "descriptive until selected using validation alone"}
                    candidates.append(row)
                    frame_candidates.append(row)
            print(json.dumps({"analyzed": task_record["task"], "patterns": len(counts), "events": len(events)}), flush=True)
        for target in TARGETS:
            winner = select_candidate(c for c in frame_candidates if c["target"] == target)
            task = next(t for t in group if t["task_id"] == winner["task_id"])
            counts, events = read_counts(task), read_events(task)
            test_mask = (events["split"] == b"test") & on_common_timeline(events, common["test"])
            ti = TARGETS.index(target)
            fit_counts = counts[:, :2, ti, :].sum(axis=1)
            p, prior = geometry_probability(fit_counts, winner["alpha"], shared[target]["refit_prior"])
            baseline_model = shared[target]["baseline_model"]
            baseline_predictions = shared[target]["test_predictions"]
            geometric_predictions = p[events["pid"][test_mask]]
            daily = daily_receipt(events, test_mask, target, geometric_predictions, baseline_predictions,
                                  task["test_start"], task["end"])
            name = f"{frame // 60:03d}m-{target}"
            daily_path = out / "selected" / (name + ".daily.csv")
            probability_path = out / "selected" / (name + ".probabilities.tsv")
            write_daily(daily_path, daily)
            write_probabilities(probability_path, fit_counts, p)
            primary_baseline = "lag1" if target == "cc" else "current_body"
            inference = {baseline: {str(block): paired_bootstrap(daily, baseline, block,
                                                                  BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED)
                                    for block in BLOCK_DAYS}
                         for baseline in ("unconditional", "lag1", "current_body")}
            record = dict(winner)
            record.update({"selected_on": "validation binary log loss only",
                           "selection_tie_break": "within 1e-12 of minimum validation log loss: fewer bars, unoriented before oriented, smaller alpha",
                           "heldout_interpretation": "retrospective test held out from this fit and selection; not asserted previously untouched",
                           "fit_splits": ["train", "validation"], "global_fit_probability": prior,
                           "unseen_pattern_probability": prior, "baseline_model": baseline_model,
                           "primary_baseline": primary_baseline, "inference": inference,
                           "daily_file": str(daily_path.relative_to(out)), "daily_sha256": sha256(daily_path),
                           "probabilities_file": str(probability_path.relative_to(out)),
                           "probabilities_sha256": sha256(probability_path),
                           "pattern_table_sha256": sha256(task["path"] / "patterns.tsv"),
                           "inference_family": "primary_cc_five_timeframes" if target == "cc" else "secondary_body_exploratory"})
            selected.append(record)
            print(json.dumps({"selected": name, "bars": record["bars"], "mode": record["mode"],
                              "alpha": record["alpha"], "test_log_loss": record["test"]["log_loss"]}), flush=True)
    for target in TARGETS:
        family = [s for s in selected if s["target"] == target]
        p_values = [s["inference"][s["primary_baseline"]]["7"]["log_loss_improvement"]["one_sided_p"] for s in family]
        for row, adjusted in zip(family, holm_adjust(p_values)):
            row["holm_adjusted_primary_log_loss_p"] = adjusted
            row["holm_family_size"] = len(family)
            row["complete_five_timeframe_family"] = full
    result = {"version": 1, "status": "complete", "protocol_sha256": protocol_sha,
              "analysis_script_sha256": sha256(__file__), "numpy_version": np.__version__,
              "complete_design": full, "task_count": len(tasks), "candidate_count": len(candidates),
              "timeframes_minutes": [f // 60 for f in frames],
              "estimator": "(fit_up + alpha * Jeffreys_unconditional_fit_up_probability) / (fit_up + fit_down + alpha)",
              "global_prior_and_baselines": "shared per timeframe and target, fitted on every eligible n02-oriented event in training or train+validation",
              "selection": "within 1e-12 of minimum validation binary log loss: fewer bars, unoriented, smaller alpha",
              "selection_roundoff_tolerance": SELECTION_TOLERANCE,
              "evaluation_timeline": "common valid longest-window decisions within each timeframe; all eligible training/refit events fit each candidate",
              "flat_policy": "retain all three outcomes in maps; exclude target-flat events from binary fitting and scoring",
              "prediction_tie_policy": "probability >= 0.5 predicts up",
              "alpha_grid": list(ALPHAS), "support_thresholds": list(THRESHOLDS),
              "primary_inference": "five validation-selected close-to-close models; seven-day paired bootstrap; Holm family correction",
              "secondary_inference": "body target is exploratory, with its own separate five-timeframe Holm family",
              "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
                            "blocks_days": list(BLOCK_DAYS), "unit": "UTC target day"},
              "candidate_tests": "all candidate test metrics are descriptive; test labels never choose a model",
              "tasks": task_records, "selected": selected, "candidates": candidates}
    dump_json(out / "analysis.json", result)
    fields = ["timeframe_minutes", "target", "bars", "mode", "alpha", "validation_log_loss",
              "test_log_loss", "test_brier", "test_accuracy", "test_balanced_accuracy", "test_n_binary",
              "test_unseen_fraction", "test_primary_baseline_log_loss", "test_primary_log_loss_improvement"]
    for filename, rows in (("candidates.csv", candidates), ("selected.csv", selected)):
        with (out / filename).open("w", newline="") as destination:
            extra = (["p_raw_7day", "p_holm", "ci95_low", "ci95_high"] if filename == "selected.csv" else [])
            writer = csv.DictWriter(destination, fieldnames=fields + extra)
            writer.writeheader()
            for row in rows:
                baseline = "lag1" if row["target"] == "cc" else "current_body"
                flat = {k: row[k] for k in fields[:5]}
                flat.update({"validation_log_loss": row["validation"]["log_loss"],
                             **{"test_" + k: row["test"][k] for k in ("log_loss", "brier", "accuracy", "balanced_accuracy", "n_binary")},
                             "test_unseen_fraction": row["test_support"]["binary_unseen_fraction"],
                             "test_primary_baseline_log_loss": row["test_baselines"][baseline]["log_loss"],
                             "test_primary_log_loss_improvement": row["test_baselines"][baseline]["log_loss"] - row["test"]["log_loss"]})
                if extra:
                    inference = row["inference"][baseline]["7"]["log_loss_improvement"]
                    flat.update({"p_raw_7day": inference["one_sided_p"], "p_holm": row["holm_adjusted_primary_log_loss_p"],
                                 "ci95_low": inference["percentile_95_ci"][0], "ci95_high": inference["percentile_95_ci"][1]})
                writer.writerow(flat)
    dump_json(out / "artifacts.json", {"version": 1, "files": {
        str(p.relative_to(out)): {"sha256": sha256(p), "bytes": p.stat().st_size}
        for p in sorted(out.rglob("*")) if p.is_file() and p.name != "artifacts.json"}})
    print(json.dumps({"status": "PASS", "analysis": str(out / "analysis.json"),
                      "tasks": len(tasks), "selected_models": len(selected),
                      "elapsed_seconds": time.perf_counter() - started}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print("direction analysis: " + str(error), file=sys.stderr)
        raise SystemExit(2)
