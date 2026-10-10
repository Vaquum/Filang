#!/usr/bin/env python3
"""QINF-R0 producer. Fixed precommitted BTC retrospective experiment.

The native binary emits only causal Phase 2 signatures. This runner owns
future labels, folds, fitted count tables and statistics. Independent audit
must not import this file.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from collections import defaultdict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN_SHA = "3f84a6331f1f6c07f3924dfefa9ede739efaa597c98448e382accc45cb2e56ea"
FIELDS = ("index", "timestamp", "valid", "lag", "body", "range", "joint")
PRED_FIELDS = ("year", "index", "timestamp", "exit_day", "lag", "y", "body",
               "range", "joint", "baseline", "p_body", "p_range", "p_joint")
MODELS = ("body", "range", "joint")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def load_source(path: Path, minute: int, expected_rows: int):
    source = []
    step = 60 * minute
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        if next(reader) != ["timestamp", "open", "high", "low", "close", "volume"]:
            raise ValueError("unexpected source columns")
        previous = None
        for raw in reader:
            if len(raw) != 6:
                raise ValueError("bad source width")
            ts = int(raw[0])
            numeric = tuple(float(v) for v in raw[1:])
            o, h, l, c, v = numeric
            if (ts % step or (previous is not None and ts <= previous)
                or not all(math.isfinite(x) for x in numeric)
                or min(o,h,l,c) <= 0 or v < 0 or h < max(o,c) or l > min(o,c)):
                raise ValueError("invalid or unordered source price")
            previous = ts
            source.append((ts, o, h, l, c))
    if len(source) != expected_rows:
        raise ValueError("source count disagrees with pinned protocol")
    return source


def run_native(binary: Path, source: Path, minutes: int, dest: Path):
    command = [str(binary), "--data", str(source), "--out", str(dest),
               "--minutes", str(minutes)]
    done = subprocess.run(command, check=True, capture_output=True, text=True)
    summary = json.loads(done.stdout)
    if summary.get("status") != "ok":
        raise ValueError("native export not successful")
    return summary


def read_features(path: Path, source):
    features = []
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("wrong native feature header")
        for i, raw in enumerate(reader):
            if i >= len(source) or int(raw["index"]) != i or int(raw["timestamp"]) != source[i][0]:
                raise ValueError("native feature row misaligned")
            if raw["valid"] not in ("0", "1"):
                raise ValueError("bad native validity")
            if raw["valid"] == "0":
                if any(raw[k] != "-" for k in ("lag", *MODELS)):
                    raise ValueError("invalid feature has nonempty values")
                features.append(None)
            else:
                lag = int(raw["lag"])
                if lag not in (-1, 0, 1):
                    raise ValueError("bad lag sign")
                codes = tuple(int(raw[m]) for m in MODELS)
                if any(x < 0 for x in codes):
                    raise ValueError("negative signature")
                features.append((lag, *codes))
    if len(features) != len(source):
        raise ValueError("native features have incorrect row count")
    return features


def events_from_source(source, features, minutes):
    step = 60 * minutes
    events = []
    for index in range(1, len(source) - 1):
        feature = features[index]
        if feature is None or source[index + 1][0] != source[index][0] + step:
            continue
        current = source[index]
        nxt = source[index + 1]
        difference = nxt[4] - current[4]
        y = 1 if difference > 0 else 0 if difference < 0 else -1
        events.append({
            "i": index, "ts": current[0], "exit": nxt[0] + step,
            "day": (nxt[0] + step) // 86400,
            "lag": feature[0], "body": feature[1],
            "range": feature[2], "joint": feature[3], "y": y,
        })
    return events


def training(events, before):
    return [e for e in events if e["exit"] < before and e["y"] >= 0]


def scoring(events, start, end):
    eligible = [e for e in events if start <= e["ts"] < end and e["exit"] < end]
    return [e for e in eligible if e["y"] >= 0], sum(e["y"] < 0 for e in eligible)


def estimate(train, alpha: float, override=None):
    total_up = sum(e["y"] for e in train)
    overall = (total_up + 0.5) / (len(train) + 1)
    lag_counts = defaultdict(lambda: [0, 0])
    cells = {name: defaultdict(lambda: [0, 0]) for name in MODELS}
    for i, e in enumerate(train):
        lag = e["lag"]
        up = e["y"]
        lag_counts[lag][0] += up
        lag_counts[lag][1] += 1
        for name in MODELS:
            key = override[i] if override is not None and name == "joint" else e[name]
            cells[name][(lag, key)][0] += up
            cells[name][(lag, key)][1] += 1
    priors = {
        lag: (counts[0] + 0.5) / (counts[1] + 1)
        for lag, counts in lag_counts.items()
    }
    return {"prior": overall, "lag": priors, "cells": cells, "alpha": alpha}


def probabilities(model, event, overrides=None):
    lag = event["lag"]
    baseline = model["lag"].get(lag, model["prior"])
    outputs = {"baseline": baseline}
    for name in MODELS:
        key = event[name] if overrides is None or name != "joint" else overrides
        up, n = model["cells"][name].get((lag, key), (0, 0))
        outputs[name] = (up + model["alpha"] * baseline) / (n + model["alpha"])
    return outputs


def losses(probs, y):
    result = {}
    for name, p in probs.items():
        if not 0 < p < 1:
            raise ValueError("invalid conditional probability")
        result[name] = -(math.log(p) if y == 1 else math.log1p(-p))
    return result


def fold_score(train, evaluation, alpha, year, native_writer):
    m = estimate(train, alpha)
    sums = defaultdict(float)
    daily = defaultdict(lambda: [0.0, 0])
    unseen = {name: 0 for name in MODELS}
    for event in evaluation:
        ps = probabilities(m, event)
        ls = losses(ps, event["y"])
        for name, loss in ls.items():
            sums[name] += loss
        for name in MODELS:
            if (event["lag"], event[name]) not in m["cells"][name]:
                unseen[name] += 1
        day = daily[event["day"]]
        day[0] += ls["baseline"] - ls["joint"]
        day[1] += 1
        native_writer.writerow([
            year, event["i"], event["ts"], event["day"],
            event["lag"], event["y"], *[event[name] for name in MODELS],
            *[format(ps[name], ".17g") for name in ("baseline", *MODELS)]
        ])
    n = len(evaluation)
    return {
        "train_binary": len(train), "score_binary": n,
        "train_lag_strata": {str(k): sum(e["lag"] == k for e in train) for k in (-1, 0, 1)},
        "classes_train": {name: len(m["cells"][name]) for name in MODELS},
        "unseen_test": unseen,
        "sums": dict(sums),
        "mean_losses": {name: sums[name] / n if n else None for name in ("baseline", *MODELS)},
        "gain_joint": (sums["baseline"] - sums["joint"]) / n if n else None,
        "bits_joint": (sums["baseline"] - sums["joint"]) / math.log(2),
        "daily": daily,
        "baseline": m,
    }


def calendar_days(start: int, end: int):
    left = start // 86400
    right = end // 86400
    return list(range(left, right))


def bootstrap(daily_folds, protocol):
    config = protocol["uncertainty"]
    rng = random.Random(config["seed"])
    annual = [(year, rows) for year, rows in sorted(daily_folds.items())]
    original_sum = math.fsum(sum(row[0] for row in rows) for _, rows in annual)
    original_n = sum(sum(row[1] for row in rows) for _, rows in annual)
    if original_n <= 0:
        raise ValueError("empty primary evaluation")
    observed = original_sum / original_n
    sims = []
    exceed = 0
    for _ in range(config["replicates"]):
        total_sum = 0.0
        centered = 0.0
        total_n = 0
        for _, days in annual:
            nday = len(days)
            consumed = 0
            while consumed < nday:
                begin = rng.randrange(nday)
                steps = min(config["block_days"], nday - consumed)
                for step in range(steps):
                    gain, count = days[(begin + step) % nday]
                    total_sum += gain
                    centered += gain - observed * count
                    total_n += count
                consumed += steps
        if not total_n:
            raise ValueError("bootstrap drew no scored observations")
        sims.append(total_sum / total_n)
        if centered / total_n >= observed:
            exceed += 1
    sims.sort()
    low = sims[int(0.025 * config["replicates"])]
    high = sims[int(0.975 * config["replicates"])]
    return {
        "observed_gain_nats": observed,
        "ci95": [low, high],
        "one_sided_centered_null_p": (exceed + 1) / (config["replicates"] + 1),
        "exceedances": exceed,
        "replicates": config["replicates"],
        "block_days": config["block_days"],
        "seed": config["seed"],
    }


def roll_joint(rows, positions):
    count = len(rows)
    if not count:
        return []
    amount = positions % count
    return [rows[(i - amount) % count]["joint"] for i in range(count)]


def placebo(folds, protocol):
    results = []
    interval = protocol["primary"]["timeframe_minutes"]
    alpha = protocol["estimator"]["alpha"]
    for days in protocol["placebo"]["shifts_days"]:
        shift = days * 1440 // interval
        b_sum, j_sum, count = 0.0, 0.0, 0
        for train, evaluation in folds:
            train_keys = roll_joint(train, shift)
            eval_keys = roll_joint(evaluation, shift)
            m = estimate(train, alpha, override=train_keys)
            for event, key in zip(evaluation, eval_keys):
                probs = probabilities(m, event, overrides=key)
                ls = losses(probs, event["y"])
                b_sum += ls["baseline"]
                j_sum += ls["joint"]
                count += 1
        results.append({"nominal_shift_days": days, "gain_nats": (b_sum-j_sum)/count})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=HERE / "protocol_r0a.json")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.protocol) != FROZEN_SHA:
        raise ValueError("protocol changed since Law 1 freeze")
    p = json.loads(args.protocol.read_text())
    if p["schema"] != "filang-qualitative-information-r0a-v1":
        raise ValueError("unknown scientific schema")
    binary = args.binary.resolve()
    if not binary.is_file():
        raise ValueError("native binary absent")
    if args.out.exists():
        raise ValueError("run directory already exists; use a fresh one")
    # Resolve and verify *every* source before running or fitting any model.
    sources = {}
    for source in p["source_policy"]["sources"]:
        minute = source["minutes"]
        path = (args.data_dir / f"{minute}m" / "ohlcv.csv").resolve()
        if digest(path) != source["csv_sha256"]:
            raise ValueError(f"source SHA mismatch for {minute}m")
        sources[minute] = (path, load_source(path, minute, source["expected_rows"]))

    args.out.mkdir(parents=True)
    (args.out / "native").mkdir()
    (args.out / "predictions").mkdir()
    summary = {
        "schema": "qinf-r0-producer-v1", "status": "PRELIMINARY_PENDING_INDEPENDENT_AUDIT",
        "frozen_protocol_sha256": FROZEN_SHA,
        "frozen_protocol_commit": "c2eecc24103b049866de2881ca8141ac194a0927",
        "binary_sha256": digest(binary), "runner_sha256": digest(Path(__file__)),
        "timeframes": {}, "primary": {},
    }
    primary_daily = {}
    primary_folds = []
    alpha = p["estimator"]["alpha"]
    for minute in sorted(sources):
        source_path, rows = sources[minute]
        output = args.out / "native" / f"{minute}m.tsv"
        nsummary = run_native(binary, source_path, minute, output)
        feature_rows = read_features(output, rows)
        events = events_from_source(rows, feature_rows, minute)
        predictions = args.out / "predictions" / f"{minute}m.tsv"
        folds = {}
        totals = defaultdict(float)
        count = 0
        with predictions.open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(PRED_FIELDS)
            for f in p["period"]["outer_folds"]:
                start, end = epoch(f["start"]), epoch(f["end"])
                prior = training(events, start)
                eval_rows, flats = scoring(events, start, end)
                if not prior or not eval_rows:
                    raise ValueError(f"empty training/test fold for {minute}m {f['year']}")
                r = fold_score(prior, eval_rows, alpha, f["year"], writer)
                for name, total in r["sums"].items():
                    totals[name] += total
                count += r["score_binary"]
                folds[str(f["year"])] = {
                    k: v for k, v in r.items() if k not in ("daily", "baseline")
                }
                folds[str(f["year"])]["score_flat_excluded"] = flats
                if minute == p["primary"]["timeframe_minutes"]:
                    primary_folds.append((prior, eval_rows))
                    raw_days = r["daily"]
                    primary_daily[f["year"]] = [
                        raw_days.get(day, [0.0, 0]) for day in calendar_days(start, end)
                    ]
        means = {name: totals[name] / count for name in ("baseline", *MODELS)}
        summary["timeframes"][str(minute)] = {
            "source_sha256": digest(source_path), "source_rows": len(rows),
            "native": nsummary, "features_sha256": digest(output),
            "predictions_sha256": digest(predictions),
            "eligible_binary": count, "folds": folds,
            "pooled_mean_losses": means,
            "pooled_gain_joint_nats": means["baseline"] - means["joint"],
            "pooled_bits_joint": (totals["baseline"] - totals["joint"]) / math.log(2),
        }
    b = bootstrap(primary_daily, p)
    shifts = placebo(primary_folds, p)
    selected = summary["timeframes"][str(p["primary"]["timeframe_minutes"])]
    years = [selected["folds"][str(f["year"])]["gain_joint"] for f in p["period"]["outer_folds"]]
    checks = {
        "positive_pooled": b["observed_gain_nats"] > 0,
        "ci_lower_positive": b["ci95"][0] > 0,
        "one_sided_p_below_0.05": b["one_sided_centered_null_p"] < 0.05,
        "at_least_three_positive_years": sum(value > 0 for value in years) >= 3,
        "latest_2026_positive": years[-1] > 0,
        "independent_audit": False,
    }
    summary["primary"] = {
        "minute": p["primary"]["timeframe_minutes"],
        "bootstrap": b, "placebo_shifts": shifts,
        "placebo_max_gain": max(entry["gain_nats"] for entry in shifts),
        "checks": checks, "positive_year_count": sum(value > 0 for value in years),
        "provisional": "INCONCLUSIVE_PENDING_INDEPENDENT_AUDIT",
    }
    report = args.out / "producer.json"
    report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": summary["status"], "out": str(args.out),
        "primary": summary["primary"], "timeframe_rows": {
            k: v["eligible_binary"] for k, v in summary["timeframes"].items()
        }}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
