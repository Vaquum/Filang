#!/usr/bin/env python3
"""Independent audit of the frozen F30-D1 affine-score follow-up.

This verifier never fits a model and does not import the new producer. The
previous independent raw-OHLC/key/prediction oracle is the only computational
dependency; its exact source is recorded by every full audit. New objectives,
diagnostics, partitions, inference and continuation decisions are reconstructed
here rather than imported from producer helpers.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

try:
    from . import verify_round1 as original
except ImportError:
    import verify_round1 as original

np = original.np
require = original.require
digest, array_digest = original.digest, original.array_digest
json_file, json_digest = original.json_file, original.json_digest
epoch, read_npz = original.epoch, original.read_npz
HERE = Path(__file__).resolve().parent
YEARS = (2023, 2024, 2025, 2026)
FAMILIES = ("B", "G")
VARIANTS = ("raw", "adapted")
PHASES = ("validation", "outer")
MAGNITUDES = ("flat", "nonflat_lt1", "1_to5", "5_to12", "12_to24", "ge24")
DECISIONS = ("B_down_G_down", "B_down_G_up", "B_up_G_down", "B_up_G_up")
TOLERANCE = 1e-10
PENALTY = 1e-4
PROTOCOL_SHA256 = "4099e7a6620387d0fbe2267819ca0d37dff0f52da3e6bf8689705e979adf497b"
FREEZE_COMMIT = "ed7e0b9bccedebc6bda75d7ab701829a6a708c5f"


def compare(actual, expected, label="value"):
    """Exact discrete structure, absolute-plus-relative float reconciliation."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), label + ": fields")
        return max((compare(actual[k], v, label + "/" + str(k)) for k, v in expected.items()), default=0.0)
    if isinstance(expected, (list, tuple)):
        require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + ": sequence")
        return max((compare(a, e, label + f"/{i}") for i, (a, e) in enumerate(zip(actual, expected))), default=0.0)
    if isinstance(expected, np.ndarray):
        require(isinstance(actual, np.ndarray) and actual.dtype == expected.dtype, label + ": dtype")
        return original.compare(actual, expected, label, TOLERANCE)
    if expected is None:
        require(actual is None, label + ": null")
        return 0.0
    if isinstance(expected, (bool, np.bool_)):
        require(type(actual) is bool and actual == bool(expected), label + ": boolean")
        return 0.0
    if isinstance(expected, (int, np.integer)):
        require(type(actual) is int and actual == int(expected), label + ": integer")
        return 0.0
    if isinstance(expected, str):
        require(type(actual) is str and actual == expected, label + ": string")
        return 0.0
    require(type(actual) in (int, float) and math.isfinite(actual) and math.isfinite(float(expected)), label + ": numeric domain")
    require(math.isclose(actual, float(expected), abs_tol=TOLERANCE, rel_tol=TOLERANCE), label + ": numeric value")
    return abs(actual - float(expected))


def bounded(root, relative):
    require(type(relative) is str and not Path(relative).is_absolute(), "relative artifact path required")
    root, result = Path(root).resolve(), (Path(root) / relative).resolve()
    require(result != root and root in result.parents, "artifact path escape")
    return result


def file_record(path):
    path = Path(path)
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def check_audit_output(run, data_dir, output, source_roots=()):
    """An audit may append only its declared canonical receipt inside a run."""
    run, output = Path(run).resolve(), Path(output).resolve()
    require(output != run and run not in output.parents or output == run / "verification.json",
            "audit output inside a producer run must be its canonical verification.json")
    require(output not in run.parents, "audit output cannot contain a producer run")
    for source in (data_dir, *source_roots):
        source = Path(source).resolve()
        require(output != source and source not in output.parents and output not in source.parents,
                "audit output overlaps immutable source root")
    require(not output.exists(), "fresh audit output required; preserve previous audit attempts")


def read_npz(path):
    with np.load(path, allow_pickle=False) as saved:
        require(len(saved.files) == len(set(saved.files)), "duplicate binary array member")
        result = {name: saved[name] for name in saved.files}
    require(all(value.dtype.kind != "O" for value in result.values()), "object/pickle binary arrays prohibited")
    return result


def adapter_objective_gradient_hessian(z, y, parameters, penalty=PENALTY):
    """Direct two-column row objective, independently rearranged softplus loss."""
    z, y = np.asarray(z, dtype=np.float64), np.asarray(y, dtype=np.float64)
    theta = np.asarray(parameters, dtype=np.float64)
    require(z.ndim == 1 and y.shape == z.shape and len(z) and theta.shape == (2,), "adapter sample shape")
    require(np.isfinite(z).all() and np.isfinite(theta).all() and np.isin(y, (0, 1)).all(), "adapter sample domain")
    a, b = theta
    linear = a + b * z
    p = original.stable_sigmoid(linear)
    design = np.column_stack((np.ones(len(z)), z))
    centered = np.array([a, b - 1], dtype=np.float64)
    objective = float(np.logaddexp(0, np.where(y == 1, -linear, linear)).mean() + penalty * np.dot(centered, centered) / 2)
    gradient = design.T @ (p - y) / len(z) + penalty * centered
    q = np.exp(-np.abs(linear))
    weights = q / (1 + q) ** 2
    hessian = design.T @ (weights[:, None] * design) / len(z) + penalty * np.eye(2)
    return objective, gradient, hessian


def auc_oracle(direction, probabilities):
    """Tie-aware Mann-Whitney probability computed from tied sorted groups."""
    direction, values = np.asarray(direction), np.asarray(probabilities, dtype=float)
    require(direction.shape == values.shape and direction.ndim == 1, "AUC aligned vectors")
    require(np.isin(direction, (-1, 1)).all() and np.isfinite(values).all(), "AUC domain")
    ups, downs = int(np.sum(direction == 1)), int(np.sum(direction == -1))
    if not ups or not downs:
        return None
    order = np.argsort(values, kind="stable")
    score, label = values[order], direction[order]
    starts = np.r_[0, np.flatnonzero(score[1:] != score[:-1]) + 1]
    stops = np.r_[starts[1:], len(score)]
    negative_before, twice_pairs = 0, 0
    for left, right in zip(starts, stops):
        positive = int(np.sum(label[left:right] == 1))
        negative = int(right - left) - positive
        twice_pairs += positive * (2 * negative_before + negative)
        negative_before += negative
    return twice_pairs / (2 * ups * downs)


def _mean(values):
    return float(np.mean(values)) if len(values) else None


def losses(direction, logits):
    direction, logits = np.asarray(direction), np.asarray(logits, dtype=np.float64)
    require(direction.shape == logits.shape and np.isin(direction, (-1, 1)).all(), "binary loss sample")
    return np.logaddexp(0, np.where(direction == 1, -logits, logits))


def probability(arrays, variant, family):
    return arrays[f"p_{family}" if variant == "raw" else f"adapted_p_{family}"]


def logit(arrays, variant, family):
    return arrays[f"logit_{family}" if variant == "raw" else f"adapted_logit_{family}"]


def score_oracle(direction, p, z):
    direction, p, z = np.asarray(direction), np.asarray(p), np.asarray(z)
    require(direction.shape == p.shape == z.shape and np.isfinite(p).all() and np.isfinite(z).all(), "cell probability domain")
    binary = direction != 0
    y, pb, zb = direction[binary], p[binary], z[binary]
    ups, downs, n = int(np.sum(y == 1)), int(np.sum(y == -1)), len(y)
    values = losses(y, zb)
    brier = np.square(pb - (y == 1))
    prediction = pb >= .5
    correct = int(np.sum(prediction == (y == 1)))
    balanced = ((float(np.mean(prediction[y == 1])) + float(np.mean(~prediction[y == -1]))) / 2 if ups and downs else None)
    return {"binary_count": n, "mean_probability_binary": _mean(pb), "mean_probability_target": _mean(p),
            "up_frequency": ups / n if n else None, "loss_sum": float(values.sum()), "log_loss": _mean(values),
            "brier_sum": float(brier.sum()), "brier": _mean(brier), "correct_count": correct,
            "accuracy": correct / n if n else None, "balanced_accuracy": balanced, "auc": auc_oracle(y, pb)}


def cell_oracle(arrays, mask, past_mean):
    """A complete descriptive cell, retaining empty and one-class outcomes."""
    mask = np.asarray(mask, dtype=bool) & arrays["classification_valid"]
    direction = arrays["direction"][mask]
    returns = arrays["target_log_return"][mask]
    drift = np.asarray(past_mean, dtype=float)
    drift = np.full(len(mask), float(drift)) if drift.ndim == 0 else drift
    require(drift.shape == mask.shape, "row-specific past drift alignment")
    n = len(direction)
    up, down, flat = direction == 1, direction == -1, direction == 0
    positive_n, negative_n, zero_n = int(up.sum()), int(down.sum()), int(flat.sum())
    binary_n = positive_n + negative_n
    total = float(returns.sum())
    positive, negative = float(returns[up].sum()), float(returns[down].sum())
    mplus = _mean(returns[up])
    mminus = _mean(-returns[down])
    mean = total / n if n else None
    z = zero_n / n if n else None
    q = positive_n / binary_n if binary_n else None
    conditional = (1 - z) * (q * mplus - (1 - q) * mminus) if positive_n and negative_n else None
    roundtrip = -math.log((1 - .001) ** 2 * (1 - .0002) / (1 + .0002))
    qstar = ((mminus + roundtrip / (1 - z)) / (mplus + mminus)
             if positive_n and negative_n and mplus + mminus > 0 else None)
    result = {"counts": {"target_valid": n, "binary": binary_n, "up": positive_n, "down": negative_n, "flat": zero_n},
              "payoff": {"log_return_sum": total, "mean_log_return": mean, "positive_sum": positive,
                         "negative_sum": negative, "positive_mean_magnitude": mplus, "negative_mean_magnitude": mminus,
                         "flat_fraction": z, "conditional_up_frequency": q,
                         "contribution_reconstruction_error": abs(mean - (positive + negative) / n) if n else None,
                         "conditional_reconstruction_error": abs(mean - conditional) if conditional is not None else None,
                         "break_even_up_probability": qstar}, "variants": {}}
    for variant in VARIANTS:
        families = {family: score_oracle(direction, probability(arrays, variant, family)[mask], logit(arrays, variant, family)[mask])
                    for family in FAMILIES}
        correction = (probability(arrays, variant, "G") - probability(arrays, variant, "B"))[mask]
        product = correction * returns
        centered = correction * (returns - drift[mask])
        loss_sum = families["B"]["loss_sum"] - families["G"]["loss_sum"]
        brier_sum = families["B"]["brier_sum"] - families["G"]["brier_sum"]
        result["variants"][variant] = {"families": families,
            "paired": {"loss_sum": loss_sum, "log_loss_gain": loss_sum / binary_n if binary_n else None,
                       "brier_sum": brier_sum, "brier_gain": brier_sum / binary_n if binary_n else None,
                       "probability_correction_mean_binary": _mean(correction[direction != 0]),
                       "probability_correction_mean_target": _mean(correction),
                       "alignment_product_sum": float(product.sum()), "alignment": _mean(product),
                       "centered_alignment_product_sum": float(centered.sum()), "centered_alignment": _mean(centered)}}
    return result


def magnitude_membership(direction, returns):
    direction, returns = np.asarray(direction), np.asarray(returns, dtype=float)
    require(direction.shape == returns.shape and np.isin(direction, (-1, 0, 1)).all(), "magnitude inputs")
    result = np.searchsorted(np.array([1., 5., 12., 24.]), np.abs(returns) * 10000, side="right") + 1
    result[direction == 0] = 0
    return result.astype(np.int64)


def decision_membership(p_b, p_g):
    return ((np.asarray(p_b) >= .5).astype(np.int64) * 2 + (np.asarray(p_g) >= .5).astype(np.int64))


def linear_quantiles(values, quantiles):
    """Linear interpolation written independently of np.quantile."""
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    require(ordered.ndim == 1 and len(ordered) > 0 and np.isfinite(ordered).all(), "quantile sample")
    result = []
    for quantile in quantiles:
        position = (len(ordered) - 1) * float(quantile)
        left = int(math.floor(position))
        right = min(left + 1, len(ordered) - 1)
        result.append(float(ordered[left] + (ordered[right] - ordered[left]) * (position - left)))
    return result


def distribution_oracle(values):
    values = np.asarray(values, dtype=np.float64)
    require(values.ndim == 1 and np.isfinite(values).all(), "distribution finite sample")
    quantiles = [.05, .25, .5, .75, .95]
    return {"count": len(values), "mean": _mean(values), "std_population": float(np.std(values, ddof=0)) if len(values) else None,
            "minimum": float(values.min()) if len(values) else None, "maximum": float(values.max()) if len(values) else None,
            "quantiles": quantiles, "quantile_values": linear_quantiles(values, quantiles) if len(values) else [None] * 5}


def daily_oracle(arrays, year, start, end):
    days = np.arange(start // 86400, (end - 1) // 86400 + 1, dtype=np.int64)
    mask = arrays["binary_mask"]
    dates = arrays["timestamp"][arrays["exit_row"][mask]] // 86400 - days[0]
    result = {"outer_year": np.full(len(days), year, dtype=np.int64), "day": days,
              "binary_count": np.zeros(len(days), dtype=np.int64)}
    np.add.at(result["binary_count"], dates, 1)
    for variant in VARIANTS:
        for family in FAMILIES:
            result[f"{variant}_loss_sum_{family}"] = np.zeros(len(days), dtype=np.float64)
            np.add.at(result[f"{variant}_loss_sum_{family}"], dates,
                      losses(arrays["direction"][mask], logit(arrays, variant, family)[mask]))
        result[f"{variant}_paired_loss_sum"] = result[f"{variant}_loss_sum_B"] - result[f"{variant}_loss_sum_G"]
    return result


def exact_integer_vectors(parts, counts):
    """Exact binary64 rational numerators and integer observation counts."""
    values = np.concatenate([np.asarray(part, dtype=np.float64) for part in parts])
    sample_counts = np.concatenate([np.asarray(count, dtype=np.int64) for count in counts])
    require(values.shape == sample_counts.shape and values.ndim == 1 and np.isfinite(values).all(), "exact ratio vectors")
    require(np.all(sample_counts >= 0) and int(sample_counts.sum()) > 0, "exact ratio original denominator")
    ratios = [float(value).as_integer_ratio() for value in values]
    exponent = max(denominator.bit_length() - 1 for _, denominator in ratios)
    integers = [numerator * (1 << (exponent - (denominator.bit_length() - 1))) for numerator, denominator in ratios]
    return exponent, integers, sample_counts


def exact_ratio_bootstrap(parts, counts, block, replicas=2000, seed=20261008):
    """Independent variable-count centered tail: N*T >= 2*S*Nstar."""
    parts = [np.asarray(part, dtype=np.float64) for part in parts]
    counts = [np.asarray(count, dtype=np.int64) for count in counts]
    require(len(parts) == len(counts) and all(p.shape == c.shape and len(p) for p, c in zip(parts, counts)), "bootstrap paired folds")
    exponent, integers, all_counts = exact_integer_vectors(parts, counts)
    original_n, original_sum = int(all_counts.sum()), sum(integers)
    gain = sum(float(part.sum()) for part in parts) / original_n
    rng = np.random.default_rng(seed + 30000 + block)
    ordinary, centered = np.empty(replicas), np.empty(replicas)
    sample_n = np.empty(replicas, dtype=np.int64)
    hits = np.empty(replicas, dtype=bool)
    fold_integers, offset = [], 0
    for part in parts:
        fold_integers.append(integers[offset:offset + len(part)])
        offset += len(part)
    for replica in range(replicas):
        numerator, null, denominator, exact_total = 0.0, 0.0, 0, 0
        for values, count, integer in zip(parts, counts, fold_integers):
            size = len(values)
            starts = rng.integers(0, size, size=math.ceil(size / block), dtype=np.int64)
            draw = np.concatenate([np.arange(int(start), int(start) + block) % size for start in starts])[:size]
            numerator += float(values[draw].sum())
            null += float((values - gain * count)[draw].sum())
            denominator += int(count[draw].sum())
            multiplicity = np.bincount(draw, minlength=size)
            exact_total += sum(int(weight) * value for weight, value in zip(multiplicity, integer))
        require(denominator > 0, "bootstrap resampled denominator is zero")
        ordinary[replica], centered[replica], sample_n[replica] = numerator / denominator, null / denominator, denominator
        hits[replica] = original_n * exact_total >= 2 * original_sum * denominator
    return {"ordinary": ordinary, "centered": centered, "resampled_count": sample_n, "exact_tail_hits": hits}


def admitted_protocol(path):
    require(digest(path) == PROTOCOL_SHA256, "unrecognized published F30-D1 protocol")
    protocol = json_file(path)
    require(protocol["schema"] == "filang-30m-signal-followup-protocol-v1" and
            protocol["attempt_id"] == "F30-D1" and protocol["data"]["minutes"] == 30, "F30-D1 protocol identity")
    require([f["year"] for f in protocol["target_and_phases"]["outer_folds"]] == list(YEARS), "complete frozen years")
    return protocol


def predecessor_paths(root, protocol):
    """Exact consumed original-relative paths, including selected model owners."""
    root = Path(root)
    required = set(protocol["predecessor"]["required_root_files"])
    required.update(("provenance.json", "features.json", "30m/features.json", "selected.json", "30m/selected.json"))
    for year in YEARS:
        for phase in PHASES:
            required.update((f"30m/{year}/{phase}.json", f"30m/{year}/{phase}.npz"))
        required.add(f"30m/{year}/classification_daily.npz")
        for family in FAMILIES:
            relative = f"30m/{year}/{family}/selected.json"
            required.add(relative)
            selection = json_file(bounded(root, relative))
            for key in ("inner_model_path", "refit_model_path"):
                model_path = selection[key]
                bounded(root, model_path)
                require(model_path.startswith(f"30m/{year}/{family}/"), "selected model timeframe/year/family path")
                required.add(model_path)
    return required


def check_predecessor_bundle(root, native, data_dir, protocol):
    """Replay the consumed 30m inputs; explicitly reuse the pinned full audit."""
    root, native, data_dir = Path(root), Path(native), Path(data_dir)
    expected_paths = predecessor_paths(root, protocol)
    actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(actual_paths == expected_paths, "scoped predecessor bundle has missing or unconsumed files")
    for relative, expected in protocol["predecessor"]["required_root_files"].items():
        compare(file_record(bounded(root, relative)), expected, "pinned predecessor " + relative)
    manifest = json_file(root / "manifest.json")
    require(manifest["schema"] == "filang-information-run-manifest-v1", "predecessor manifest schema")
    require((root / "manifest.sha256").read_text() == digest(root / "manifest.json") + "\n", "predecessor manifest seal")
    for relative in expected_paths - {"manifest.json", "manifest.sha256", "verification.json"}:
        require(relative in manifest["files"], "consumed predecessor file missing from original seal")
        record = manifest["files"][relative]
        compare(file_record(bounded(root, relative)), {k: record[k] for k in ("bytes", "sha256")}, "predecessor bytes " + relative)
    audit, identity = json_file(root / "verification.json"), json_file(root / "run.json")
    old_protocol = json_file(root / "protocol.json")
    original.protocol_contract(root / "protocol.json")
    require(identity["protocol_sha256"] == protocol["predecessor"]["protocol_sha256"] and
            identity["freeze_commit"] == protocol["predecessor"]["freeze_commit"] and
            identity["implementation"]["git_head"] == protocol["predecessor"]["execution_commit"], "original run ownership")
    require(audit["status"] == "PASS" and audit["stage"] == "full" and
            audit["schema"] == "filang-geometry-information-verification-v1", "original complete full audit required")
    require(audit["producer_manifest_sha256"] == digest(root / "manifest.json") and
            audit["analysis_sha256"] == digest(root / "analysis.json") and
            audit["protocol_sha256"] == digest(root / "protocol.json"), "original full audit input bindings")
    require(audit["audited_timeframes"] == [15, 30, 60, 120, 240] and audit["audited_outer_years"] == list(YEARS),
            "original full audit timeframe/year scope")
    for name, expected in {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40,
                           "outer_predictions": 20, "validation_predictions": 20, "ledger_replays": 960,
                           "all_records": True, "sampled": False}.items():
        compare(audit["coverage"][name], expected, "original full audit coverage " + name)
    spec = protocol["data"]["source"]
    require(next(s for s in old_protocol["data"]["sources"] if s["minutes"] == 30) == spec, "D1 original source pin equality")
    raw = data_dir / "raw" / spec["filename"]
    require(raw.stat().st_size == spec["expected_source_bytes"] and digest(raw) == spec["sha256"], "original raw parquet pin")
    source = original.load_source(data_dir / "30m" / "ohlcv.csv", 1800, spec["prepared_csv_sha256"])
    require(len(source["timestamp"]) == spec["expected_source_rows"] and source["missing_grid_bars"] == spec["missing_grid_bars"],
            "prepared rows and original gaps")
    provenance = json_file(root / "provenance.json")
    require(digest(root / "provenance.json") == identity["source_provenance_sha256"], "original provenance binding")
    prior_source = next(s for s in provenance["sources"] if s["minutes"] == 30)
    require(prior_source["source_sha256"] == spec["sha256"] and prior_source["csv_sha256"] == spec["prepared_csv_sha256"],
            "prepared/raw original provenance")
    native_paths = {p.relative_to(native).as_posix() for p in native.rglob("*") if p.is_file()}
    require(native_paths == {"keys.bin", "context.json", "manifest.json", "manifest.sha256", "timings.json"}, "native scoped file census")
    pins = protocol["data"]["native"]
    require(digest(native / "keys.bin") == pins["keys_sha256"] and (native / "keys.bin").stat().st_size == pins["keys_bytes"] and
            digest(native / "context.json") == pins["context_sha256"] and digest(native / "manifest.json") == pins["manifest_sha256"],
            "exact pinned native inputs")
    receipt, causal_rows = original.audit_native_keys(native, source, old_protocol, json_file(root / "30m/features.json"))
    require(receipt["records_checked"] == pins["records"], "all native causal records checked")
    root_features = next(f for f in json_file(root / "features.json")["timeframes"] if f["minutes"] == 30)
    compare(root_features, json_file(root / "30m/features.json"), "original root/local feature receipts")
    phases, selections, models = {}, {}, {}
    max_error = 0.0
    global_choices = json_file(root / "selected.json")["selections"]
    local_choices = json_file(root / "30m/selected.json")["selections"]
    require(len(global_choices) == 40 and len(local_choices) == 8, "original global and 30m choice counts")
    frame = next(f for f in json_file(root / "analysis.json")["timeframes"] if f["minutes"] == 30)
    for fold in protocol["target_and_phases"]["outer_folds"]:
        year = fold["year"]
        for family in FAMILIES:
            choice = json_file(root / f"30m/{year}/{family}/selected.json")
            require(choice["minutes"] == 30 and choice["outer_year"] == year and choice["family"] == family, "selected model cell owner")
            require(sum(row == choice for row in global_choices) == 1 and sum(row == choice for row in local_choices) == 1,
                    "original global/local/per-model choices agree")
            require(choice["n"] in (2, 3, 5, 10) and choice["lambda"] in (.1, .01, .001, .0001), "selected original grid")
            for stage, key, fit_key in (("inner", "inner_model_path", "inner_fit_id"), ("refit", "refit_model_path", "refit_fit_id")):
                model = json_file(root / choice[key])
                require(model["fit_id"] == choice[fit_key] and model["path"] == choice[key] and model["stage"] == stage and
                        model["family"] == family and model["outer_year"] == year and model["minutes"] == 30 and
                        model["n"] == choice["n"] and model["lambda"] == choice["lambda"] and model["accepted"] is True,
                        "selected original model identity/ownership")
                start_key, end_key = (("inner_train_start", "inner_train_end_exclusive") if stage == "inner" else
                                      ("refit_start", "refit_end_exclusive"))
                labels = original.phase_oracle(source, causal_rows, epoch(fold[start_key]), epoch(fold[end_key]))
                rows = np.flatnonzero(labels["binary_mask"])
                require(model["fit_start"] == epoch(fold[start_key]) and model["fit_end_exclusive"] == epoch(fold[end_key]) and
                        model["fit_count"] == len(rows) and model["fit_rows_sha256"] == array_digest(rows, "<i8") and
                        model["fit_labels_sha256"] == array_digest(labels["direction"][rows] == 1, np.uint8),
                        "selected original model strict fitting sample")
                require(model["coefficient_sha256"] == array_digest(np.asarray([model["intercept"], *model["coefficients"]]), "<f8"),
                        "selected original model coefficients")
                models[year, family, stage] = model
            selections[year, family] = choice
        for phase in PHASES:
            stage = "inner" if phase == "validation" else "refit"
            start_key, end_key = (("inner_train_start", "inner_train_end_exclusive") if stage == "inner" else
                                  ("refit_start", "refit_end_exclusive"))
            fitting = original.phase_oracle(source, causal_rows, epoch(fold[start_key]), epoch(fold[end_key]))
            values, scores, error = original.audit_predictions(root, root / f"30m/{year}", phase, source, causal_rows,
                    fold, {family: models[year, family, stage] for family in FAMILIES}, fitting,
                    protocol["predecessor"]["protocol_sha256"], receipt)
            require(len(values) == 16, "complete sixteen original prediction arrays")
            max_error = max(max_error, error)
            phases[year, phase] = values
            if phase == "outer":
                old_fold = next(f for f in frame["folds"] if f["year"] == year)
                max_error = max(max_error, compare(scores, old_fold["scores"], "original annual score reproduction"))
                daily = original.daily_oracle(values, epoch(fold["outer_start"]), epoch(fold["outer_end_exclusive"]))
                max_error = max(max_error, compare(read_npz(root / f"30m/{year}/classification_daily.npz"), daily,
                                                  "original complete daily reproduction"))
    return {"source": source, "native_receipt": receipt, "causal_rows": causal_rows, "phases": phases,
            "selections": selections, "models": models, "original_frame": frame,
            "expected_paths": expected_paths, "max_error": max_error}


def census_oracle(arrays, start, end):
    times = arrays["timestamp"]
    in_phase, causal = arrays["phase_mask"], arrays["causal_feature_valid"]
    valid, binary = arrays["classification_valid"], arrays["binary_mask"]
    forecast = in_phase & causal
    absent = gap = boundary = 0
    for row in np.flatnonzero(forecast & ~valid):
        if row + 2 >= len(times):
            absent += 1
        elif times[row + 2] - times[row] != 3600:
            gap += 1
        elif times[row + 2] >= end:
            boundary += 1
        else:
            raise ValueError("unexpected reason for a valid causal forecast's missing target")
    gaps = []
    for row in np.flatnonzero(np.diff(times) > 1800) + 1:
        if start <= times[row] < end:
            gaps.append({"receiving_row": int(row), "previous_timestamp": int(times[row - 1]),
                         "receiving_timestamp": int(times[row]), "missing_bars": int((times[row] - times[row - 1]) // 1800 - 1)})
    return {"source_rows": len(times), "in_phase": int(in_phase.sum()), "causal_forecasts": int(forecast.sum()),
            "label_valid": int(valid.sum()), "binary": int(binary.sum()), "flat": int(np.sum(valid & ~binary)),
            "forecast_valid_future_label_invalid": int(np.sum(forecast & ~valid)),
            "in_phase_causal_invalid": int(np.sum(in_phase & ~causal)), "future_source_rows_missing": absent,
            "future_gap_exclusions": gap, "exit_boundary_exclusions": boundary, "gaps_receiving_inside_phase": gaps,
            "phase_start": start, "phase_end_exclusive": end}


def boundary_oracle(arrays, year, variant, family):
    rows = np.flatnonzero(arrays["phase_mask"] & arrays["causal_feature_valid"])
    p = probability(arrays, variant, family)[rows]
    # NumPy linear interpolation is the explicitly frozen primitive. Exact
    # downstream groups use these already validated executed probabilities.
    cuts = np.quantile(p, [.2, .4, .6, .8], method="linear")
    distinct = np.unique(cuts)
    return {"year": year, "variant": variant, "family": family, "quantiles": [.2, .4, .6, .8],
            "raw_cuts": cuts.tolist(), "cuts": distinct.tolist(), "bin_count": len(distinct) + 1,
            "training_count": len(rows), "training_rows_sha256": array_digest(rows, "<i8"),
            "training_probabilities_sha256": array_digest(p)}


def compact_outer(arrays, year, past_mean):
    selected = arrays["classification_valid"]
    names = ("direction", "binary_mask", "target_log_return", "p_B", "p_G", "logit_B", "logit_G",
             "adapted_p_B", "adapted_p_G", "adapted_logit_B", "adapted_logit_G")
    result = {name: arrays[name][selected] for name in names}
    result["classification_valid"] = np.ones(int(selected.sum()), dtype=bool)
    result["outer_year"] = np.full(int(selected.sum()), year, dtype=np.int64)
    result["exit_timestamp"] = arrays["timestamp"][arrays["exit_row"][selected]]
    result["past_mean"] = np.full(int(selected.sum()), past_mean, dtype=np.float64)
    return result


def compact_cell(data, mask=None, aggregate_only=False):
    if mask is None:
        mask = np.ones(len(data["direction"]), dtype=bool)
    result = cell_oracle(data, mask, data["past_mean"])
    if aggregate_only:
        result = {"counts": result["counts"], "variants": {
            variant: {"families": result["variants"][variant]["families"],
                      "paired": {key: result["variants"][variant]["paired"][key]
                                 for key in ("loss_sum", "log_loss_gain", "brier_sum", "brier_gain")}}
            for variant in VARIANTS}}
    return result


def weighted_gain_oracle(data, variant):
    mask = data["binary_mask"]
    weights = np.abs(data["target_log_return"][mask])
    delta = losses(data["direction"][mask], logit(data, variant, "B")[mask]) - losses(data["direction"][mask], logit(data, variant, "G")[mask])
    numerator, denominator = float(np.dot(weights, delta)), float(weights.sum())
    return {"numerator": numerator, "denominator": denominator, "gain": numerator / denominator if denominator else None}


def diagnostics_oracle(phases, folds):
    result = {"schema": "filang-followup30-diagnostics-v1", "periods": [], "magnitude_cells": [],
              "decision_cells": [], "score_cells": [], "score_boundaries": [], "distribution": [],
              "corrections": [], "sample_census": [], "weighted_gains": [], "past_means": []}
    compact, calendars, membership = {}, [], {}
    for fold in folds:
        year = fold["year"]
        validation, outer = phases[year, "validation"], phases[year, "outer"]
        fit_rows = np.flatnonzero(validation["classification_valid"])
        fit_returns = validation["target_log_return"][fit_rows]
        require(len(fit_rows) > 0, "complete prior mean sample")
        past_mean = float(fit_returns.mean())
        result["past_means"].append({"year": year, "mean": past_mean, "count": len(fit_rows),
            "rows_sha256": array_digest(fit_rows, "<i8"), "returns_sha256": array_digest(fit_returns),
            "return_sum": float(fit_returns.sum())})
        compact[year] = compact_outer(outer, year, past_mean)
        valid = outer["classification_valid"]
        calendar = daily_oracle(outer, year, epoch(fold["outer_start"]), epoch(fold["outer_end_exclusive"]))
        calendars.append(calendar)
        membership[year] = {}
        membership[year]["magnitude"] = np.full(len(valid), -1, dtype=np.int8)
        membership[year]["magnitude"][valid] = magnitude_membership(outer["direction"][valid], outer["target_log_return"][valid])
        for phase in PHASES:
            arrays = phases[year, phase]
            result["sample_census"].append({"year": year, "phase": phase,
                **census_oracle(arrays, epoch(fold[f"{phase}_start"]), epoch(fold[f"{phase}_end_exclusive"]))})
            available = arrays["phase_mask"] & arrays["causal_feature_valid"]
            for variant in VARIANTS:
                for family in FAMILIES:
                    result["distribution"].append({"year": year, "phase": phase, "variant": variant, "family": family,
                        "probability": distribution_oracle(probability(arrays, variant, family)[available]),
                        "logit": distribution_oracle(logit(arrays, variant, family)[available])})
                result["corrections"].append({"year": year, "phase": phase, "variant": variant,
                    "probability_G_minus_B": distribution_oracle((probability(arrays, variant, "G") - probability(arrays, variant, "B"))[available])})
        for variant in VARIANTS:
            states = np.full(len(valid), -1, dtype=np.int8)
            states[valid] = decision_membership(probability(outer, variant, "B")[valid], probability(outer, variant, "G")[valid])
            membership[year][f"decision_{variant}"] = states
            for family in FAMILIES:
                boundary = boundary_oracle(validation, year, variant, family)
                result["score_boundaries"].append(boundary)
                bins = np.full(len(valid), -1, dtype=np.int8)
                bins[valid] = np.searchsorted(boundary["cuts"], probability(outer, variant, family)[valid], side="right")
                membership[year][f"score_{variant}_{family}"] = bins
                for bucket in range(boundary["bin_count"]):
                    result["score_cells"].append({"year": year, "variant": variant, "family": family, "bin": bucket,
                        "lower": boundary["cuts"][bucket - 1] if bucket else None,
                        "upper": boundary["cuts"][bucket] if bucket < len(boundary["cuts"]) else None,
                        "cell": compact_cell(compact[year], bins[valid] == bucket)})
    pooled = {name: np.concatenate([compact[year][name] for year in YEARS]) for name in compact[YEARS[0]]}
    for period, data in [(str(year), compact[year]) for year in YEARS] + [("pooled", pooled)]:
        result["periods"].append({"kind": "pooled" if period == "pooled" else "year", "period": period, "cell": compact_cell(data)})
        magnitudes = magnitude_membership(data["direction"], data["target_log_return"])
        for bucket, label in enumerate(MAGNITUDES):
            result["magnitude_cells"].append({"period": period, "bin": bucket, "label": label,
                                               "cell": compact_cell(data, magnitudes == bucket)})
        for variant in VARIANTS:
            states = decision_membership(probability(data, variant, "B"), probability(data, variant, "G"))
            for state, label in enumerate(DECISIONS):
                result["decision_cells"].append({"period": period, "variant": variant, "state": state, "label": label,
                                                  "cell": compact_cell(data, states == state)})
            result["weighted_gains"].append({"period": period, "variant": variant, **weighted_gain_oracle(data, variant)})
    year, month = 2023, 1
    exit_months = np.array([datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m") for t in pooled["exit_timestamp"]])
    while (year, month) <= (2026, 10):
        period = f"{year:04d}-{month:02d}"
        result["periods"].append({"kind": "month", "period": period,
                                  "cell": compact_cell(pooled, exit_months == period, aggregate_only=True)})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    for year in YEARS:
        result["periods"].append({"kind": "leave_one_year_out", "period": f"without-{year}",
                                  "cell": compact_cell(pooled, pooled["outer_year"] != year, aggregate_only=True)})
    daily = {name: np.concatenate([calendar[name] for calendar in calendars]) for name in calendars[0]}
    return result, daily, membership


def exact_encoding_oracle(daily):
    values, counts = daily["adapted_paired_loss_sum"], daily["binary_count"]
    exponent, integers, _ = exact_integer_vectors([values], [counts])
    return {"schema": "filang-followup30-exact-ratio-v1", "denominator_power_of_two": exponent,
            "numerators": [str(value) for value in integers], "counts": counts.tolist(),
            "outer_year": daily["outer_year"].tolist(), "day": daily["day"].tolist(),
            "numerator_sum": str(sum(integers)), "count_sum": int(counts.sum()),
            "float_sums_sha256": array_digest(values), "counts_sha256": array_digest(counts)}


def bootstrap_summary_oracle(daily, block, retained):
    parts = [daily["adapted_paired_loss_sum"][daily["outer_year"] == year] for year in YEARS]
    counts = [daily["binary_count"][daily["outer_year"] == year] for year in YEARS]
    expected = exact_ratio_bootstrap(parts, counts, block)
    error = compare(retained, expected, f"bootstrap-{block} all arrays")
    # Every continuous array element is validated first. Metadata digests and
    # literal p-values bind retained executed arrays, not approximate replays.
    gain = float(daily["adapted_paired_loss_sum"].sum() / daily["binary_count"].sum())
    ci = np.quantile(retained["ordinary"], [.025, .975], method="linear")
    seed, draw_digest = 20261008 + 30000 + block, hashlib.sha256()
    generator = np.random.default_rng(seed)
    for _ in range(2000):
        for part in parts:
            starts = generator.integers(0, len(part), size=math.ceil(len(part) / block), dtype=np.int64)
            draw_digest.update(np.ascontiguousarray(starts, dtype="<i8").tobytes())
    hit_count = int(retained["exact_tail_hits"].sum())
    return {"block_days": block, "replicates": 2000, "seed": seed, "gain": gain,
            "ci95_low": float(ci[0]), "ci95_high": float(ci[1]), "exact_tail_hit_count": hit_count,
            "p_one_sided": (1 + hit_count) / 2001, "original_count": int(daily["binary_count"].sum()),
            "draw_starts_sha256": draw_digest.hexdigest(),
            "array_hashes": {name: array_digest(value) for name, value in retained.items()}}, error


def decisions_oracle(diagnostics, bootstrap):
    years = {int(row["period"]): row["cell"] for row in diagnostics["periods"] if row["kind"] == "year"}
    pooled = next(row["cell"] for row in diagnostics["periods"] if row["kind"] == "pooled")
    gains = {str(year): years[year]["variants"]["adapted"]["paired"]["log_loss_gain"] for year in YEARS}
    positive = sum(value is not None and value > 0 for value in gains.values())
    primary = bootstrap["7"]
    conditions = {"positive_pooled_gain": primary["gain"] > 0, "ci_above_zero": primary["ci95_low"] > 0,
                  "p_below_005": primary["p_one_sided"] < .05, "three_positive_years": positive >= 3,
                  "latest_2026_positive": gains["2026"] is not None and gains["2026"] > 0}
    passed = all(conditions.values())
    align = {str(year): years[year]["variants"]["adapted"]["paired"]["centered_alignment"] for year in YEARS}
    pooled_align = pooled["variants"]["adapted"]["paired"]["centered_alignment"]
    gate = {"primary_supported_if_verified": passed, "pooled_alignment_positive": pooled_align is not None and pooled_align > 0,
            "latest_2026_alignment_positive": align["2026"] is not None and align["2026"] > 0,
            "three_positive_alignment_years": sum(value is not None and value > 0 for value in align.values()) >= 3}
    return {"primary": {"conditions": conditions, "criterion_met": passed, "annual_gains": gains,
                        "positive_years": positive, "outcome": "inconclusive",
                        "outcome_if_verified": "supported" if passed else "not-supported"},
            "continuation": {"conditions": gate, "gate_if_verified": all(gate.values()), "annual_centered_alignment": align,
                             "pooled_centered_alignment": pooled_align, "status": "PENDING_INDEPENDENT_AUDIT"}}


def checked_run(root, protocol_path, output_path):
    root = Path(root).resolve()
    output_path = Path(output_path).resolve()
    require(root not in output_path.parents or output_path == root / "verification.json", "audit receipt cannot mutate a sealed input subdirectory")
    protocol = admitted_protocol(protocol_path)
    require((root / "protocol.json").read_bytes() == Path(protocol_path).read_bytes(), "new run frozen protocol bytes")
    require((root / "manifest.sha256").read_text() == digest(root / "manifest.json") + "\n", "new run manifest seal")
    manifest = json_file(root / "manifest.json")
    require(manifest["schema"] == "filang-followup30-run-manifest-v1", "new run manifest schema")
    for relative, record in manifest["files"].items():
        compare(file_record(bounded(root, relative)), record, "new sealed artifact " + relative)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    allowed = {"manifest.json", "manifest.sha256"}
    if (root / "verification.json").is_file():
        allowed.add("verification.json")
    require(actual == set(manifest["files"]) | allowed, "new producer run unsealed/missing file census")
    require("verification.json" not in manifest["files"], "audit cannot be inside original producer seal")
    run = json_file(root / "run.json")
    require(run["schema"] == "filang-followup30-run-v1" and run["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT" and
            run["freeze_commit"] == FREEZE_COMMIT and run["protocol_sha256"] == PROTOCOL_SHA256 and
            run["attempt_id"] == "F30-D1" and run["experiment_id"] == protocol["experiment_id"], "completed new producer identity")
    require(run["deviations"] == [] and run["settings"] == {"workers": 1, "blas_threads": 2}, "frozen execution settings")
    implementation = run["implementation"]
    require(implementation["worktree_status_porcelain"] == "" and implementation["sha256"] == json_digest(implementation["files"]),
            "clean original execution and implementation object seal")
    expected_code = {"experiments/geometry_information/" + name for name in ("run_followup30.py", "followup30.py", "common.py")}
    require(set(implementation["files"]) == expected_code, "complete producer implementation dependency coverage")
    repository = HERE.parents[1]
    for relative, expected_sha in implementation["files"].items():
        require(digest(repository / relative) == expected_sha, "retained/current producer source differs")
        committed = subprocess.run(["git", "show", f"{implementation['git_commit']}:{relative}"], cwd=repository,
                                   check=True, capture_output=True).stdout
        require(hashlib.sha256(committed).hexdigest() == expected_sha, "producer implementation commit blob differs")
    frozen = subprocess.run(["git", "show", f"{FREEZE_COMMIT}:experiments/geometry_information/followup30_protocol.json"],
                            cwd=repository, check=True, capture_output=True).stdout
    require(frozen == Path(protocol_path).read_bytes(), "published protocol commit content differs")
    subprocess.run(["git", "merge-base", "--is-ancestor", FREEZE_COMMIT, implementation["git_commit"]], cwd=repository,
                   check=True, capture_output=True)
    dependencies = {"experiments/geometry_information/verify_round1.py": digest(HERE / "verify_round1.py")}
    compare(run["verification_dependencies"], dependencies, "bound independent raw/key oracle source")
    return protocol, manifest, run


def check_inputs(root, protocol, replay):
    inputs = json_file(root / "inputs.json")
    require(inputs["schema"] == "filang-followup30-inputs-v1" and inputs["protocol_sha256"] == PROTOCOL_SHA256,
            "new input receipt schema/protocol")
    old = root / "predecessor"
    bindings = {"predecessor_manifest_sha256": digest(old / "manifest.json"),
                "predecessor_analysis_sha256": digest(old / "analysis.json"),
                "predecessor_audit_sha256": digest(old / "verification.json"),
                "predecessor_protocol_sha256": digest(old / "protocol.json"),
                "predecessor_execution_commit": protocol["predecessor"]["execution_commit"]}
    for name, value in bindings.items():
        compare(inputs[name], value, "scoped input predecessor binding " + name)
    copies = {}
    for relative in sorted(replay["expected_paths"]):
        copies["predecessor/" + relative] = {**file_record(old / relative), "origin_kind": "predecessor", "origin_relative": relative}
    for name in ("keys.bin", "context.json", "manifest.json", "manifest.sha256", "timings.json"):
        copies["native/30m/" + name] = {**file_record(root / "native/30m" / name), "origin_kind": "native", "origin_relative": "30m/" + name}
    compare(inputs["copied_files"], copies, "all copied input identity/origin records")
    phase_bindings = []
    for year in YEARS:
        for phase in PHASES:
            path = f"30m/{year}/{phase}.npz"
            sidecar = path.replace(".npz", ".json")
            phase_bindings.append({"year": year, "phase": phase, "prediction_path": path,
                "prediction_sha256": digest(old / path), "sidecar_path": sidecar,
                "sidecar_sha256": digest(old / sidecar), "models": json_file(old / sidecar)["models"]})
    compare(inputs["phases"], phase_bindings, "all original phase input bindings")
    source = replay["source"]
    compare(inputs["coverage"], {"source_rows": len(source["timestamp"]), "native_keys": len(replay["causal_rows"]),
        "original_prediction_phases": 8, "selected_models": 16, "selection_records": 8, "copied_files": len(copies)}, "input coverage")
    external = inputs["external_sources"]
    compare(external["source_specification"], protocol["data"]["source"], "external exact source specification")
    for kind, spec in (("prepared_csv", {"bytes": source["bytes"], "sha256": source["sha256"]}),
                       ("raw_parquet", {"bytes": protocol["data"]["source"]["expected_source_bytes"],
                                        "sha256": protocol["data"]["source"]["sha256"]})):
        require(type(external[kind]["path"]) is str and bool(external[kind]["path"]), "recorded original external source path")
        compare({k: external[kind][k] for k in ("bytes", "sha256")}, spec, "external source identity")
    return inputs, {(row["year"], row["phase"]): row for row in phase_bindings}


def adapter_oracle(record, arrays, fold, family, binding, implementation_sha):
    rows = np.flatnonzero(arrays["binary_mask"])
    labels = (arrays["direction"][rows] == 1).astype(np.uint8)
    z = arrays[f"logit_{family}"][rows]
    metadata = {"schema": "filang-followup30-adapter-v1", "year": fold["year"], "family": family, "lambda": PENALTY,
        "initial_parameters": [0.0, 1.0], "protocol_sha256": PROTOCOL_SHA256, "implementation_sha256": implementation_sha,
        "source_prediction_path": binding["prediction_path"], "source_prediction_sha256": binding["prediction_sha256"],
        "source_model": binding["models"][family], "training_start": epoch(fold["validation_start"]),
        "training_end_exclusive": epoch(fold["validation_end_exclusive"]), "sample_count": len(rows),
        "sample_up_count": int(labels.sum()), "sample_down_count": int(len(rows) - labels.sum()),
        "sample_rows_sha256": array_digest(rows, "<i8"), "sample_logits_sha256": array_digest(z),
        "sample_labels_sha256": array_digest(labels)}
    metadata["fit_id"] = json_digest(metadata)
    for name, value in metadata.items():
        compare(record[name], value, "adapter sample/owner " + name)
    require(record["lambda"] == PENALTY and record["initial_parameters"] == [0., 1.], "exact adapter objective specification")
    parameters = np.asarray(record["parameters"], dtype=np.float64)
    require(parameters.shape == (2,) and np.isfinite(parameters).all(), "finite two-parameter adapter")
    require(record["a"] == parameters[0] and record["b"] == parameters[1] and
            record["parameters_sha256"] == array_digest(parameters), "adapter retained parameter aliases and bytes")
    compare(record["slope_negative"], bool(parameters[1] < 0), "unconstrained negative slope flag")
    compare(record["slope_zero"], bool(parameters[1] == 0), "zero slope flag")
    objective, gradient, hessian = adapter_objective_gradient_hessian(z, labels, parameters)
    maximum = float(np.max(np.abs(gradient)))
    require(maximum <= TOLERANCE and np.linalg.eigvalsh(hessian).min() > 0, "independent adapter optimum acceptance")
    error = max(compare(record["objective"], objective, "adapter direct objective"),
                compare(record["gradient"], gradient.tolist(), "adapter direct gradient"),
                compare(record["max_abs_gradient"], maximum, "adapter direct maximum gradient"))
    require(record["accepted"] is True, "all eight required adapters must be accepted")
    optimizer = record["optimizer"]
    require(optimizer["method"] == "Newton-Cholesky-Armijo-2" and optimizer["success"] is True and
            optimizer["stop_reason"] == "gradient_tolerance" and optimizer["terminal_recomputations"] == 1,
            "adapter declared solver successful gradient termination")
    n = optimizer["iterations"]
    require(type(n) is int and 0 <= n <= 100, "adapter bounded update count")
    require(all(len(optimizer[name]) == n for name in ("step_sizes", "backtrack_counts", "line_search_trial_counts", "accepted_path")),
            "adapter complete iteration receipts")
    require(optimizer["hessian_evaluations"] == n and optimizer["function_evaluations"] == 1 + sum(optimizer["line_search_trial_counts"]) and
            optimizer["gradient_evaluations"] == optimizer["function_evaluations"], "adapter truthful evaluation counts")
    initial_objective, initial_gradient, _ = adapter_objective_gradient_hessian(z, labels, [0., 1.])
    previous = initial_objective
    for index, path in enumerate(optimizer["accepted_path"]):
        backtrack, step, trials = optimizer["backtrack_counts"][index], optimizer["step_sizes"][index], optimizer["line_search_trial_counts"][index]
        require(type(backtrack) is int and 0 <= backtrack < 50 and step == 2. ** (-backtrack) and trials == backtrack + 1,
                "adapter frozen alpha/backtracking grammar")
        error = max(error, compare(path["objective_before"], previous, "adapter accepted objective continuity"))
        require(path["directional_derivative"] < 0 and math.isfinite(path["directional_derivative"]) and
                path["gradient_max_before"] > TOLERANCE and
                path["objective_after"] <= path["objective_before"] + .0001 * step * path["directional_derivative"],
                "adapter finite descent and retained Armijo criterion")
        if index == 0:
            error = max(error, compare(path["gradient_max_before"], float(np.max(np.abs(initial_gradient))), "adapter initial gradient"))
        previous = path["objective_after"]
    error = max(error, compare(previous, record["objective"], "adapter terminal objective continuity"))
    expected_keys = set(metadata) | {"accepted", "parameters", "a", "b", "slope_negative", "slope_zero", "objective",
                                    "gradient", "max_abs_gradient", "parameters_sha256", "optimizer"}
    require(set(record) == expected_keys, "adapter full record fields")
    return error, maximum


def transformed_phase_oracle(root, old, models, fold, phase, binding, implementation_sha, source):
    year = fold["year"]
    expected = {name: value.copy() for name, value in old.items()}
    valid = old["classification_valid"]
    expected["target_log_return"] = np.full(len(valid), np.nan)
    expected["target_log_return"][valid] = np.log(source["prices"][old["exit_row"][valid], 0] / source["prices"][old["entry_row"][valid], 0])
    for family in FAMILIES:
        known = old["phase_mask"] & old["causal_feature_valid"]
        z = np.full(len(valid), np.nan)
        z[known] = models[family]["a"] + models[family]["b"] * old[f"logit_{family}"][known]
        expected[f"adapted_logit_{family}"] = z
        expected[f"adapted_p_{family}"] = original.stable_sigmoid(z)
    path = root / f"{year}/{phase}.npz"
    actual = read_npz(path)
    error = compare(actual, expected, "all full-row affine predictions and targets")
    require(len(actual) == 21, "complete twenty-one transformed arrays")
    for name in old:
        require(array_digest(actual[name]) == array_digest(old[name]), "original phase array changed in transformed bundle")
    sidecar = {"schema": "filang-followup30-predictions-v1", "year": year, "phase": phase,
        "phase_start": epoch(fold[f"{phase}_start"]), "phase_end_exclusive": epoch(fold[f"{phase}_end_exclusive"]),
        "source_prediction_path": binding["prediction_path"], "source_prediction_sha256": binding["prediction_sha256"],
        "source_sidecar_path": binding["sidecar_path"], "source_sidecar_sha256": binding["sidecar_sha256"],
        "source_sha256": source["sha256"], "native_keys_sha256": json_file(root / "protocol.json")["data"]["native"]["keys_sha256"],
        "protocol_sha256": PROTOCOL_SHA256, "implementation_sha256": implementation_sha,
        "adapter_records": {family: {"path": f"{year}/adapters/{family}.json", "sha256": digest(root / f"{year}/adapters/{family}.json"),
                                    "fit_id": models[family]["fit_id"]} for family in FAMILIES},
        "npz_sha256": digest(path), "npz_bytes": path.stat().st_size,
        "arrays": {name: {"dtype": value.dtype.str, "shape": list(value.shape), "sha256": array_digest(value)} for name, value in actual.items()}}
    compare(json_file(path.with_suffix(".json")), sidecar, "complete affine phase sidecar")
    return actual, error


def raw_reconciliation_oracle(daily, old_frame, predecessor_root):
    annual, error = [], 0.0
    for old in old_frame["folds"]:
        year = old["year"]
        selected = daily["outer_year"] == year
        prior = read_npz(predecessor_root / f"30m/{year}/classification_daily.npz")
        for name in ("day", "binary_count"):
            compare(daily[name][selected], prior[name], "original and followed daily counts/calendar")
        for family in FAMILIES:
            error = max(error, compare(daily[f"raw_loss_sum_{family}"][selected], prior[f"loss_sum_{family}"], "original daily raw loss"))
            error = max(error, compare(float(daily[f"raw_loss_sum_{family}"][selected].sum()), old["scores"][family]["loss_sum"],
                                       "original annual raw numerator"))
        error = max(error, compare(daily["raw_paired_loss_sum"][selected], prior["paired_loss_sum"], "original raw daily contrast"))
        count = int(daily["binary_count"][selected].sum())
        numerator = float(daily["raw_paired_loss_sum"][selected].sum())
        gain = numerator / count
        require(count == old["scores"]["B"]["binary_count"] == old["scores"]["G"]["binary_count"], "original raw annual score sample")
        require(abs(gain - old["gain"]) <= TOLERANCE, "published raw annual gain reconciliation")
        annual.append({"year": year, "count": count, "numerator": numerator, "gain": gain,
                       "original_gain": old["gain"], "absolute_error": abs(gain - old["gain"])})
    count = int(daily["binary_count"].sum())
    numerator = float(daily["raw_paired_loss_sum"].sum())
    gain = numerator / count
    reference = .0005687510773535314
    require(abs(gain - reference) <= TOLERANCE, "published pooled R1a raw gain")
    return {"status": "PASS", "annual": annual, "pooled_count": count, "pooled_numerator": numerator,
            "pooled_gain": gain, "reference_gain": reference, "absolute_error": abs(gain - reference)}, error


def daily_csv_oracle(path, daily):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ["utc_date", *daily], "complete daily CSV columns and order")
        rows = list(reader)
    require(len(rows) == len(daily["day"]), "complete daily CSV row coverage")
    error = 0.0
    for index, row in enumerate(rows):
        date = datetime.fromtimestamp(int(daily["day"][index]) * 86400, timezone.utc).date().isoformat()
        require(row["utc_date"] == date, "daily CSV UTC date")
        for name, array in daily.items():
            if array.dtype.kind in "iu":
                require(str(int(array[index])) == row[name], "daily CSV exact integer")
            else:
                error = max(error, compare(float(row[name]), float(array[index]), "daily CSV numeric member"))
    return error


def full_audit(args):
    started = time.perf_counter()
    root = args.run.resolve()
    protocol, manifest, run = checked_run(root, args.protocol, args.out)
    replay = check_predecessor_bundle(root / "predecessor", root / "native/30m", args.data_dir, protocol)
    inputs, bindings = check_inputs(root, protocol, replay)
    required_paths = set(inputs["copied_files"]) | {"protocol.json", "run.json", "inputs.json", "fits.jsonl",
        "diagnostics.json", "analysis.json", "daily.npz", "daily.csv", "bootstrap-exact.json",
        "bootstrap-1.npz", "bootstrap-7.npz", "bootstrap-28.npz"}
    for year in YEARS:
        required_paths.update(f"{year}/adapters/{family}.json" for family in FAMILIES)
        required_paths.update(f"{year}/{phase}.{extension}" for phase in PHASES for extension in ("json", "npz"))
        required_paths.add(f"{year}/diagnostic-membership.npz")
    require(set(manifest["files"]) == required_paths, "complete fixed D1 producer artifact census")
    fits = [json.loads(line) for line in (root / "fits.jsonl").read_text().splitlines() if line.strip()]
    require(len(fits) == 8, "exactly eight retained affine adapter records")
    max_error, max_gradient = replay["max_error"], 0.0
    adapted, fit_index = {}, 0
    for fold in protocol["target_and_phases"]["outer_folds"]:
        year, models = fold["year"], {}
        for family in FAMILIES:
            model = json_file(root / f"{year}/adapters/{family}.json")
            require(model == fits[fit_index], "fit stream and adapter file exact record equality")
            fit_index += 1
            error, gradient = adapter_oracle(model, replay["phases"][year, "validation"], fold, family,
                                           bindings[year, "validation"], run["implementation"]["sha256"])
            max_error, max_gradient = max(max_error, error), max(max_gradient, gradient)
            models[family] = model
        for phase in PHASES:
            values, error = transformed_phase_oracle(root, replay["phases"][year, phase], models, fold, phase,
                    bindings[year, phase], run["implementation"]["sha256"], replay["source"])
            adapted[year, phase] = values
            max_error = max(max_error, error)
    expected_diagnostics, expected_daily, memberships = diagnostics_oracle(adapted, protocol["target_and_phases"]["outer_folds"])
    diagnostics = json_file(root / "diagnostics.json")
    max_error = max(max_error, compare(diagnostics, expected_diagnostics, "every declared diagnostic cell"))
    # Raw and adapted values have now passed complete independent replay. Use
    # retained executed values for discrete bins, AUC ties and exact predicates.
    daily = read_npz(root / "daily.npz")
    max_error = max(max_error, compare(daily, expected_daily, "all original-calendar daily arrays"),
                    daily_csv_oracle(root / "daily.csv", daily))
    require(len(daily["day"]) == 1376, "complete 1376-day outer calendar")
    for year in YEARS:
        compare(read_npz(root / f"{year}/diagnostic-membership.npz"), memberships[year], "every exact partition membership")
    # Boundary values also govern discrete membership, so require their
    # prescribed NumPy-linear results exactly, beyond the numeric cell check.
    for actual, expected in zip(diagnostics["score_boundaries"], expected_diagnostics["score_boundaries"]):
        require(actual == expected, "exact executed validation cut values and bin count")
    raw, error = raw_reconciliation_oracle(daily, replay["original_frame"], root / "predecessor")
    max_error = max(max_error, error)
    encoding = exact_encoding_oracle(daily)
    require(json_file(root / "bootstrap-exact.json") == encoding, "every exact rational numerator/count and identity")
    bootstrap = {}
    for block in (7, 1, 28):
        retained = read_npz(root / f"bootstrap-{block}.npz")
        summary, error = bootstrap_summary_oracle(daily, block, retained)
        bootstrap[str(block)] = summary
        max_error = max(max_error, error)
    analysis = json_file(root / "analysis.json")
    expected_coverage = {"adapter_fits": 8, "accepted_adapter_fits": 8, "prediction_phases": 8, "prediction_array_members": 168,
        "native_keys": 118432, "source_rows": 118576, "calendar_days": 1376, "periods": 55,
        "magnitude_cells": 30, "decision_cells": 40, "score_cells": len(diagnostics["score_cells"]), "score_boundaries": 16,
        "distributions": 32, "correction_distributions": 16, "sample_censuses": 8, "weighted_gains": 10, "past_means": 4,
        "bootstrap_cases": 3, "exact_tail_bits": 6000, "all_records": True, "sampled": False}
    decision = decisions_oracle(diagnostics, bootstrap)
    expected_analysis = {"schema": "filang-followup30-analysis-v1", "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
        "experiment_id": protocol["experiment_id"], "attempt_id": "F30-D1", "protocol_sha256": PROTOCOL_SHA256,
        "freeze_commit": FREEZE_COMMIT, "implementation_sha256": run["implementation"]["sha256"],
        "inputs_sha256": digest(root / "inputs.json"), "diagnostics_sha256": digest(root / "diagnostics.json"),
        "coverage": expected_coverage, "bootstrap": bootstrap, **decision, "raw_reconciliation": raw,
        "outcome": "inconclusive", "outcome_if_verified": decision["primary"]["outcome_if_verified"],
        "audit_required": "Every required independent check must PASS before conditional outcomes or continuation can be promoted."}
    max_error = max(max_error, compare(analysis, expected_analysis, "complete D1 analysis and decisions"))
    for block in (7, 1, 28):
        for name in ("exact_tail_hit_count", "p_one_sided", "original_count", "draw_starts_sha256", "array_hashes"):
            require(analysis["bootstrap"][str(block)][name] == bootstrap[str(block)][name], "exact p-value/count/draw/array identity")
    array_members = 0
    for relative in manifest["files"]:
        if relative.endswith(".npz"):
            array_members += len(read_npz(root / relative))
    checks = {name: True for name in (
        "predecessor_exact_bytes_and_full_audit", "raw_prepared_source_pins", "all_native_keys_and_projections",
        "all_original_phases_predictions_and_model_ownership", "all_adapter_samples_objectives_gradients",
        "all_full_row_adapted_predictions", "all_diagnostic_tables_and_partitions", "all_daily_arrays_and_raw_gain_reconciliation",
        "all_exact_encodings_replicas_and_tail_bits", "primary_and_continuation_decisions",
        "all_input_and_producer_artifact_identities", "no_model_fitting_by_verifier")}
    coverage = {"native_keys": 118432, "adapter_fits": 8, "original_prediction_phases": 8, "adapted_prediction_phases": 8,
        "aggregate_periods": 55, "magnitude_cells": 30, "decision_cells": 40, "score_cells": len(diagnostics["score_cells"]),
        "score_boundaries": 16, "score_distributions": 32, "correction_distributions": 16, "sample_censuses": 8,
        "weighted_gains": 10, "past_means": 4, "calendar_days": 1376, "bootstrap_cases": 3, "exact_tail_bits": 6000,
        "all_records": True, "sampled": False}
    return {"schema": "filang-30m-signal-followup-verification-v1", "stage": "full", "status": "PASS",
        "freeze_commit": FREEZE_COMMIT, "protocol_sha256": PROTOCOL_SHA256,
        "producer_manifest_sha256": digest(root / "manifest.json"), "analysis_sha256": digest(root / "analysis.json"),
        "verifier_sha256": digest(Path(__file__)), "independent_oracle_sha256": digest(HERE / "verify_round1.py"),
        "implementation_commit": run["implementation"]["git_commit"], "coverage": coverage, "checks": checks,
        "all_array_members_checked": True, "audited_array_members": array_members, "no_model_fitting_by_verifier": True,
        "max_numeric_error": max_error, "max_adapter_gradient": max_gradient,
        "predecessor_full_audit_sha256": digest(root / "predecessor/verification.json"),
        "predecessor_inherited_scope": "Pinned original full audit covers unconsumed original candidates, fitting and selection, and other timeframes; this audit independently replays every consumed 30m selected prediction and fitting-sample ownership.",
        "discrete_arithmetic_scope": "Retained executed probabilities and daily sums are independently validated numerically before exact bin/AUC/tail decisions; no claim that discontinuous predicates commute with approximate floating reconstruction.",
        "primary_outcome": decision["primary"]["outcome_if_verified"], "continuation_gate": decision["continuation"]["gate_if_verified"],
        "elapsed_seconds": time.perf_counter() - started}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("full",), default="full")
    for name in ("run", "data-dir", "protocol", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args(argv)
    source_roots = []
    if (args.run / "inputs.json").is_file():
        input_receipt = json_file(args.run / "inputs.json")
        source_roots = [input_receipt[key] for key in ("predecessor_root", "data_root", "keys_root")]
    check_audit_output(args.run, args.data_dir, args.out, source_roots)
    started = time.perf_counter()
    try:
        result = full_audit(args)
    except Exception as error:
        import traceback
        result = {"schema": "filang-30m-signal-followup-verification-v1", "stage": args.stage, "status": "FAIL",
                  "protocol_sha256": digest(args.protocol), "freeze_commit": FREEZE_COMMIT,
                  "verifier_sha256": digest(Path(__file__)), "independent_oracle_sha256": digest(HERE / "verify_round1.py"),
                  "run": str(args.run.resolve()), "error": str(error), "traceback": traceback.format_exc(),
                  "elapsed_seconds": time.perf_counter() - started}
        original.save_json(args.out, result)
        raise
    original.save_json(args.out, result)
    print(json.dumps({"status": result["status"], "out": str(args.out), "coverage": result["coverage"],
                      "max_numeric_error": result["max_numeric_error"], "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
