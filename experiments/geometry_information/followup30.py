"""Frozen F30-D1 numerical primitives; no market reads or base-model fitting.

The executable producer binds its exact protocol, source and implementation.
These functions accept arrays so synthetic tests can exercise the scientific
contract without admitting any market input. The independent verifier does not
import this module.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np


FAMILIES = ("B", "G")
VARIANTS = ("raw", "adapted")
MAGNITUDE_LABELS = ("flat", "nonflat_lt1", "1_to5", "5_to12", "12_to24", "ge24")
DECISION_LABELS = ("B_down_G_down", "B_down_G_up", "B_up_G_down", "B_up_G_up")
SOURCE_ARRAYS = {
    "row_index": "<i8", "timestamp": "<i8", "causal_feature_valid": "|b1",
    "phase_mask": "|b1", "classification_valid": "|b1", "binary_mask": "|b1",
    "direction": "|i1", "target_return": "<f8", "entry_row": "<i8", "exit_row": "<i8",
    "p_B": "<f8", "p_G": "<f8", "logit_B": "<f8", "logit_G": "<f8",
    "p_unconditional": "<f8", "p_lag1": "<f8",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def array_sha(values):
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def object_sha(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    pending.write_bytes(json_bytes(value))
    pending.replace(path)


def read_json(path):
    def reject(value):
        raise ValueError("nonfinite JSON constant " + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def array_record(values):
    return {"dtype": values.dtype.str, "shape": list(values.shape), "sha256": array_sha(values)}


def write_npz(path, arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(all(isinstance(a, np.ndarray) and a.dtype.kind != "O" for a in arrays.values()), "object arrays forbidden")
    pending = path.with_name(path.name + ".pending")
    with pending.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    pending.replace(path)
    return {"bytes": path.stat().st_size, "sha256": digest(path),
            "arrays": {k: array_record(v) for k, v in arrays.items()}}


def read_npz(path):
    with np.load(path, allow_pickle=False) as data:
        require(len(data.files) == len(set(data.files)), "duplicate NPZ member")
        result = {k: data[k] for k in data.files}
    require(all(a.dtype.kind != "O" for a in result.values()), "object arrays forbidden")
    return result


def epoch(value):
    return int(dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc).timestamp())


def sigmoid(z):
    z = np.asarray(z, dtype=np.float64)
    result = np.empty_like(z)
    nonnegative = z >= 0
    result[nonnegative] = 1 / (1 + np.exp(-z[nonnegative]))
    q = np.exp(z[~nonnegative])
    result[~nonnegative] = q / (1 + q)
    return result


def adapter_objective_gradient(parameters, z, y, penalty=0.0001):
    parameters, z, y = (np.asarray(v, dtype=np.float64) for v in (parameters, z, y))
    v = parameters[0] + parameters[1] * z
    error = sigmoid(v) - y
    centered = parameters - np.array([0.0, 1.0])
    objective = float(np.mean(np.logaddexp(0.0, v) - y*v) + penalty * np.dot(centered, centered) / 2)
    gradient = np.array([error.mean(), np.mean(error*z)]) + penalty*centered
    return objective, gradient


def adapter_hessian(parameters, z, penalty=0.0001):
    v = parameters[0]+parameters[1]*z
    q = np.exp(-np.abs(v))
    w = q/(1+q)**2
    return np.array([[w.mean(), np.mean(w*z)], [np.mean(w*z), np.mean(w*z*z)]]) + penalty*np.eye(2)


def adapter_objective(parameters, z, y, penalty=0.0001):
    objective, gradient = adapter_objective_gradient(parameters, z, y, penalty)
    return objective, gradient, adapter_hessian(np.asarray(parameters), np.asarray(z), penalty)


def fit_adapter(z, y, *, penalty=0.0001, max_updates=100, gradient_acceptance=1e-10):
    """Retain a complete finite terminal record, including rejected iterations."""
    z, y = np.asarray(z, dtype=np.float64), np.asarray(y, dtype=np.float64)
    require(z.ndim == y.ndim == 1 and len(z) == len(y) and len(z) > 0, "adapter sample shape/count")
    require(np.isfinite(z).all() and np.all((y == 0) | (y == 1)), "adapter sample finite/binary")
    require(penalty > 0 and 0 <= max_updates <= 100 and gradient_acceptance > 0, "adapter numerical settings")
    parameters = np.array([0.0, 1.0])
    objective, gradient = adapter_objective_gradient(parameters, z, y, penalty)
    function_evaluations, hessian_evaluations = 1, 0
    step_sizes, backtracks, trial_counts, path = [], [], [], []
    reason = "maximum_updates"
    for update in range(max_updates + 1):
        finite = np.isfinite(parameters).all() and np.isfinite(objective) and np.isfinite(gradient).all()
        if not finite:
            reason = "nonfinite_evaluation"
            break
        if np.max(np.abs(gradient)) <= gradient_acceptance:
            reason = "gradient_tolerance"
            break
        if update == max_updates:
            break
        hessian_evaluations += 1
        hessian = adapter_hessian(parameters, z, penalty)
        if not np.isfinite(hessian).all():
            reason = "nonfinite_hessian"
            break
        try:
            factor = np.linalg.cholesky(hessian)
            direction = np.linalg.solve(factor.T, np.linalg.solve(factor, -gradient))
        except np.linalg.LinAlgError:
            reason = "factorization_failure"
            break
        slope = float(gradient @ direction)
        if not np.isfinite(direction).all() or not np.isfinite(slope):
            reason = "nonfinite_direction"
            break
        if slope >= 0:
            reason = "non_descent_direction"
            break
        accepted = False
        for backtrack in range(50):
            alpha = 2.0**(-backtrack)
            trial = parameters + alpha*direction
            candidate, candidate_gradient = adapter_objective_gradient(trial, z, y, penalty)
            function_evaluations += 1
            if (np.isfinite(trial).all() and np.isfinite(candidate) and np.isfinite(candidate_gradient).all()
                    and candidate <= objective + 0.0001*alpha*slope):
                path.append({"objective_before": objective, "gradient_max_before": float(np.max(np.abs(gradient))),
                             "directional_derivative": slope, "objective_after": candidate})
                parameters, objective, gradient = trial, candidate, candidate_gradient
                step_sizes.append(alpha)
                backtracks.append(backtrack)
                trial_counts.append(backtrack + 1)
                accepted = True
                break
        if not accepted:
            trial_counts.append(50)
            reason = "line_search_failure"
            break
    terminal_objective, terminal_gradient = adapter_objective_gradient(parameters, z, y, penalty)
    finite = bool(np.isfinite(parameters).all() and np.isfinite(terminal_objective) and np.isfinite(terminal_gradient).all())
    accepted = bool(reason == "gradient_tolerance" and finite and np.max(np.abs(terminal_gradient)) <= gradient_acceptance)
    if reason == "gradient_tolerance" and not accepted:
        reason = "terminal_recomputation_failure"
    # Infinities are never serialized as JSON numbers; the last finite parameters
    # remain retained. The failure reason records any invalid attempted step.
    return {"accepted": accepted, "parameters": parameters.tolist(), "a": float(parameters[0]), "b": float(parameters[1]),
            "slope_negative": bool(parameters[1] < 0), "slope_zero": bool(parameters[1] == 0),
            "objective": float(terminal_objective) if np.isfinite(terminal_objective) else None,
            "gradient": [float(v) if np.isfinite(v) else None for v in terminal_gradient],
            "max_abs_gradient": float(np.max(np.abs(terminal_gradient))) if np.isfinite(terminal_gradient).all() else None,
            "parameters_sha256": array_sha(parameters), "optimizer": {
                "method": "Newton-Cholesky-Armijo-2", "success": accepted, "stop_reason": reason,
                "iterations": len(step_sizes), "function_evaluations": function_evaluations,
                "gradient_evaluations": function_evaluations, "hessian_evaluations": hessian_evaluations,
                "step_sizes": step_sizes, "backtrack_counts": backtracks, "line_search_trial_counts": trial_counts,
                "accepted_path": path, "terminal_recomputations": 1}}


def transformed_arrays(original, adapters, opens):
    arrays = {name: values.copy() for name, values in original.items()}
    valid = original["classification_valid"]
    log_return = np.full(len(valid), np.nan)
    log_return[valid] = np.log(opens[original["exit_row"][valid]] / opens[original["entry_row"][valid]])
    arrays["target_log_return"] = log_return
    for family in FAMILIES:
        model = adapters[family]
        require(model["accepted"], "rejected adapter cannot produce forecasts")
        z = original[f"logit_{family}"]
        finite = np.isfinite(z)
        adapted_z, adapted_p = np.full(len(z), np.nan), np.full(len(z), np.nan)
        adapted_z[finite] = model["a"] + model["b"]*z[finite]
        adapted_p[finite] = sigmoid(adapted_z[finite])
        require(np.isfinite(adapted_z[finite]).all(), "nonfinite transformed available forecast")
        arrays[f"adapted_logit_{family}"] = adapted_z
        arrays[f"adapted_p_{family}"] = adapted_p
    return arrays


def prediction_names(variant, family):
    prefix = "" if variant == "raw" else "adapted_"
    require(variant in VARIANTS and family in FAMILIES, "forecast identity")
    return prefix + "p_" + family, prefix + "logit_" + family


def auc(y, p):
    y, p = np.asarray(y, dtype=bool), np.asarray(p, dtype=np.float64)
    positive, negative = int(y.sum()), int((~y).sum())
    if not positive or not negative:
        return None
    order = np.argsort(p, kind="stable")
    ordered_p, ordered_y = p[order], y[order]
    starts = np.r_[0, np.flatnonzero(ordered_p[1:] != ordered_p[:-1]) + 1]
    ends = np.r_[starts[1:], len(p)]
    ranks = np.repeat((starts + 1 + ends) / 2.0, ends-starts)
    return float((ranks[ordered_y].sum() - positive*(positive+1)/2) / (positive*negative))


def _mean(values):
    return float(np.mean(values)) if len(values) else None


def score(y, probabilities, logits, target_probabilities):
    y = np.asarray(y, dtype=np.float64)
    p, z = np.asarray(probabilities), np.asarray(logits)
    loss = np.logaddexp(0.0, z) - y*z
    brier = (p-y)**2
    up, down = y == 1, y == 0
    correct = (p >= 0.5) == up
    balanced = (float(np.mean(p[up] >= 0.5)) + float(np.mean(p[down] < 0.5)))/2 if up.any() and down.any() else None
    return {"binary_count": len(y), "mean_probability_binary": _mean(p),
            "mean_probability_target": _mean(target_probabilities), "up_frequency": _mean(y),
            "loss_sum": float(loss.sum()), "log_loss": _mean(loss), "brier_sum": float(brier.sum()),
            "brier": _mean(brier), "correct_count": int(correct.sum()), "accuracy": _mean(correct),
            "balanced_accuracy": balanced, "auc": auc(up, p)}


def compact_outer(arrays, year, past_mean):
    mask = arrays["classification_valid"]
    result = {name: arrays[name][mask] for name in
              ("direction", "binary_mask", "target_log_return", "p_B", "p_G", "logit_B", "logit_G",
               "adapted_p_B", "adapted_p_G", "adapted_logit_B", "adapted_logit_G")}
    result["outer_year"] = np.full(int(mask.sum()), year, dtype=np.int64)
    result["exit_timestamp"] = arrays["timestamp"][arrays["exit_row"][mask]]
    result["past_mean"] = np.full(int(mask.sum()), past_mean, dtype=np.float64)
    return result


def cell(data, mask=None):
    """Common complete outcome-cell structure for the fixed diagnostic tables."""
    mask = np.ones(len(data["direction"]), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    d = {k: v[mask] for k, v in data.items()}
    direction, returns = d["direction"], d["target_log_return"]
    n = len(direction)
    up, down, flat = direction == 1, direction == -1, direction == 0
    binary = up | down
    nb = int(binary.sum())
    y = up[binary].astype(np.float64)
    pos_sum, neg_sum = float(returns[up].sum()), float(returns[down].sum())
    mean_return = _mean(returns)
    plus, minus = _mean(returns[up]), _mean(-returns[down])
    z, q = (float(flat.mean()) if n else None), (float(up.sum()/nb) if nb else None)
    reconstruction = (1-z)*(q*plus-(1-q)*minus) if plus is not None and minus is not None else None
    k = -math.log((1-0.001)**2*(1-0.0002)/(1+0.0002))
    qstar = ((minus+k/(1-z))/(plus+minus)
             if plus is not None and minus is not None and z < 1 and plus+minus > 0 else None)
    out = {"counts": {"target_valid": n, "binary": nb, "up": int(up.sum()), "down": int(down.sum()), "flat": int(flat.sum())},
           "payoff": {"log_return_sum": float(returns.sum()), "mean_log_return": mean_return,
                      "positive_sum": pos_sum, "negative_sum": neg_sum,
                      "positive_mean_magnitude": plus, "negative_mean_magnitude": minus,
                      "flat_fraction": z, "conditional_up_frequency": q,
                      "contribution_reconstruction_error": abs((pos_sum+neg_sum)/n-mean_return) if n else None,
                      "conditional_reconstruction_error": abs(reconstruction-mean_return) if reconstruction is not None else None,
                      "break_even_up_probability": qstar}, "variants": {}}
    for variant in VARIANTS:
        families, losses, briers, probabilities = {}, {}, {}, {}
        for family in FAMILIES:
            pname, zname = prediction_names(variant, family)
            probabilities[family] = d[pname]
            p, logit = d[pname][binary], d[zname][binary]
            families[family] = score(y, p, logit, d[pname])
            losses[family] = np.logaddexp(0.0, logit)-y*logit
            briers[family] = (p-y)**2
        loss_delta, brier_delta = losses["B"]-losses["G"], briers["B"]-briers["G"]
        correction = probabilities["G"]-probabilities["B"]
        aligned, centered = correction*returns, correction*(returns-d["past_mean"])
        paired = {"loss_sum": float(loss_delta.sum()), "log_loss_gain": _mean(loss_delta),
                  "brier_sum": float(brier_delta.sum()), "brier_gain": _mean(brier_delta),
                  "probability_correction_mean_binary": _mean(correction[binary]),
                  "probability_correction_mean_target": _mean(correction),
                  "alignment_product_sum": float(aligned.sum()), "alignment": _mean(aligned),
                  "centered_alignment_product_sum": float(centered.sum()), "centered_alignment": _mean(centered)}
        out["variants"][variant] = {"families": families, "paired": paired}
    return out


def magnitude_membership(direction, log_return):
    direction, log_return = np.asarray(direction), np.asarray(log_return)
    require(np.isfinite(log_return).all() and np.all(np.isin(direction, [-1, 0, 1])), "magnitude domain")
    result = np.zeros(len(direction), dtype=np.int8)
    nonflat = direction != 0
    result[nonflat] = 1 + np.searchsorted([1.0, 5.0, 12.0, 24.0], np.abs(log_return[nonflat])*10000, side="right")
    return result


def decision_membership(p_b, p_g):
    return (2*(np.asarray(p_b) >= 0.5) + (np.asarray(p_g) >= 0.5)).astype(np.int8)


def score_boundaries(arrays, variant, family):
    pname, _ = prediction_names(variant, family)
    rows = np.flatnonzero(arrays["phase_mask"] & arrays["causal_feature_valid"])
    probabilities = arrays[pname][rows]
    require(len(rows) and np.isfinite(probabilities).all(), "score boundary sample")
    raw = np.quantile(probabilities, [0.2, 0.4, 0.6, 0.8], method="linear")
    cuts = np.unique(raw)
    return {"variant": variant, "family": family, "quantiles": [0.2, 0.4, 0.6, 0.8],
            "raw_cuts": raw.tolist(), "cuts": cuts.tolist(), "bin_count": len(cuts)+1,
            "training_count": len(rows), "training_rows_sha256": array_sha(rows.astype(np.int64)),
            "training_probabilities_sha256": array_sha(probabilities)}


def distribution(values):
    values = np.asarray(values, dtype=np.float64)
    require(np.isfinite(values).all(), "finite descriptive distribution")
    quantiles = [0.05, 0.25, 0.5, 0.75, 0.95]
    return {"count": len(values), "mean": _mean(values), "std_population": float(np.std(values)) if len(values) else None,
            "minimum": float(np.min(values)) if len(values) else None,
            "maximum": float(np.max(values)) if len(values) else None,
            "quantiles": quantiles, "quantile_values": np.quantile(values, quantiles, method="linear").tolist() if len(values) else [None]*5}


def sample_census(arrays, start, end, interval_seconds=1800):
    times = arrays["timestamp"]
    phase, causal = arrays["phase_mask"], arrays["causal_feature_valid"]
    valid, binary = arrays["classification_valid"], arrays["binary_mask"]
    forecast = phase & causal
    rows = np.flatnonzero(forecast)
    future_present = rows+2 < len(times)
    complete = np.zeros(len(rows), dtype=bool)
    complete[future_present] = times[rows[future_present]+2]-times[rows[future_present]] == 2*interval_seconds
    inside = np.zeros(len(rows), dtype=bool)
    inside[future_present] = times[rows[future_present]+2] < end
    receiving = np.flatnonzero(np.diff(times) > interval_seconds)+1
    receiving = receiving[(times[receiving] >= start) & (times[receiving] < end)]
    return {"source_rows": len(times), "in_phase": int(phase.sum()), "causal_forecasts": int(forecast.sum()),
            "label_valid": int(valid.sum()), "binary": int(binary.sum()), "flat": int((valid & ~binary).sum()),
            "forecast_valid_future_label_invalid": int((forecast & ~valid).sum()),
            "in_phase_causal_invalid": int((phase & ~causal).sum()),
            "future_source_rows_missing": int((~future_present).sum()),
            "future_gap_exclusions": int((future_present & ~complete).sum()),
            "exit_boundary_exclusions": int((future_present & complete & ~inside).sum()),
            "gaps_receiving_inside_phase": [{"receiving_row": int(i), "previous_timestamp": int(times[i-1]),
                "receiving_timestamp": int(times[i]), "missing_bars": int((times[i]-times[i-1])//interval_seconds-1)} for i in receiving],
            "phase_start": int(start), "phase_end_exclusive": int(end)}


def daily_arrays(arrays, year, start, end):
    days = np.arange(start//86400, (end-1)//86400+1, dtype=np.int64)
    mask = arrays["binary_mask"]
    index = arrays["timestamp"][arrays["exit_row"][mask]]//86400-days[0]
    y = (arrays["direction"][mask] == 1).astype(np.float64)
    daily = {"outer_year": np.full(len(days), year, dtype=np.int64), "day": days,
             "binary_count": np.bincount(index, minlength=len(days)).astype(np.int64)}
    for variant in VARIANTS:
        losses = {}
        for family in FAMILIES:
            _, zname = prediction_names(variant, family)
            z = arrays[zname][mask]
            losses[family] = np.logaddexp(0.0, z)-y*z
            daily[f"{variant}_loss_sum_{family}"] = np.bincount(index, weights=losses[family], minlength=len(days))
        daily[f"{variant}_paired_loss_sum"] = np.bincount(index, weights=losses["B"]-losses["G"], minlength=len(days))
    return daily


def weighted_gain(data, variant):
    binary = data["binary_mask"]
    y = (data["direction"][binary] == 1).astype(np.float64)
    losses = {}
    for family in FAMILIES:
        _, name = prediction_names(variant, family)
        z = data[name][binary]
        losses[family] = np.logaddexp(0.0, z)-y*z
    weights = np.abs(data["target_log_return"][binary])
    numerator, denominator = float(np.sum(weights*(losses["B"]-losses["G"]))), float(weights.sum())
    return {"numerator": numerator, "denominator": denominator, "gain": numerator/denominator if denominator else None}


def aggregate_score_cell(data, mask):
    complete = cell(data, mask)
    return {"counts": complete["counts"], "variants": {variant: {
        "families": complete["variants"][variant]["families"],
        "paired": {key: complete["variants"][variant]["paired"][key] for key in
                   ("loss_sum", "log_loss_gain", "brier_sum", "brier_gain")}}
        for variant in VARIANTS}}


def build_diagnostics(phases, folds):
    """Return diagnostics, daily arrays, and explicit outer membership arrays.

    phases[(year, phase)] contains transformed full-row arrays. No selection or
    fitting occurs here. Every outer bucket boundary is a validation statistic.
    """
    result = {"schema": "filang-followup30-diagnostics-v1", "periods": [], "magnitude_cells": [],
              "decision_cells": [], "score_cells": [], "score_boundaries": [], "distribution": [],
              "corrections": [], "sample_census": [], "weighted_gains": [], "past_means": []}
    compact, daily_folds, memberships = {}, [], {}
    for fold in folds:
        year = fold["year"]
        validation, outer = phases[year, "validation"], phases[year, "outer"]
        valid = validation["classification_valid"]
        past_returns = validation["target_log_return"][valid]
        require(len(past_returns), "past target mean sample")
        past_mean = float(past_returns.mean())
        result["past_means"].append({"year": year, "mean": past_mean, "count": len(past_returns),
            "rows_sha256": array_sha(np.flatnonzero(valid).astype(np.int64)), "returns_sha256": array_sha(past_returns),
            "return_sum": float(past_returns.sum())})
        compact[year] = compact_outer(outer, year, past_mean)
        out_valid = outer["classification_valid"]
        memberships[year] = {}
        magnitude = np.full(len(out_valid), -1, dtype=np.int8)
        magnitude[out_valid] = magnitude_membership(outer["direction"][out_valid], outer["target_log_return"][out_valid])
        memberships[year]["magnitude"] = magnitude
        daily_folds.append(daily_arrays(outer, year, epoch(fold["outer_start"]), epoch(fold["outer_end_exclusive"])))
        for phase in ("validation", "outer"):
            arrays = phases[year, phase]
            result["sample_census"].append({"year": year, "phase": phase, **sample_census(
                arrays, epoch(fold[f"{phase}_start"]), epoch(fold[f"{phase}_end_exclusive"]))})
            available = arrays["phase_mask"] & arrays["causal_feature_valid"]
            for variant in VARIANTS:
                for family in FAMILIES:
                    pname, zname = prediction_names(variant, family)
                    result["distribution"].append({"year": year, "phase": phase, "variant": variant, "family": family,
                        "probability": distribution(arrays[pname][available]), "logit": distribution(arrays[zname][available])})
                bname, _ = prediction_names(variant, "B")
                gname, _ = prediction_names(variant, "G")
                result["corrections"].append({"year": year, "phase": phase, "variant": variant,
                    "probability_G_minus_B": distribution(arrays[gname][available]-arrays[bname][available])})
        for variant in VARIANTS:
            bname, _ = prediction_names(variant, "B")
            gname, _ = prediction_names(variant, "G")
            states = np.full(len(out_valid), -1, dtype=np.int8)
            states[out_valid] = decision_membership(outer[bname][out_valid], outer[gname][out_valid])
            memberships[year][f"decision_{variant}"] = states
            for family in FAMILIES:
                boundary = {"year": year, **score_boundaries(validation, variant, family)}
                result["score_boundaries"].append(boundary)
                pname, _ = prediction_names(variant, family)
                bins = np.full(len(out_valid), -1, dtype=np.int8)
                bins[out_valid] = np.searchsorted(boundary["cuts"], outer[pname][out_valid], side="right")
                memberships[year][f"score_{variant}_{family}"] = bins
                for bin_id in range(boundary["bin_count"]):
                    result["score_cells"].append({"year": year, "variant": variant, "family": family, "bin": bin_id,
                        "lower": boundary["cuts"][bin_id-1] if bin_id else None,
                        "upper": boundary["cuts"][bin_id] if bin_id < len(boundary["cuts"]) else None,
                        "cell": cell(compact[year], bins[out_valid] == bin_id)})
    years = [f["year"] for f in folds]
    pooled = {name: np.concatenate([compact[y][name] for y in years]) for name in compact[years[0]]}
    scopes = [(str(y), compact[y]) for y in years] + [("pooled", pooled)]
    for period, data in scopes:
        result["periods"].append({"kind": "year" if period != "pooled" else "pooled", "period": period, "cell": cell(data)})
        magnitude = magnitude_membership(data["direction"], data["target_log_return"])
        for bin_id, label in enumerate(MAGNITUDE_LABELS):
            result["magnitude_cells"].append({"period": period, "bin": bin_id, "label": label, "cell": cell(data, magnitude == bin_id)})
        for variant in VARIANTS:
            bname, _ = prediction_names(variant, "B")
            gname, _ = prediction_names(variant, "G")
            states = decision_membership(data[bname], data[gname])
            for state, label in enumerate(DECISION_LABELS):
                result["decision_cells"].append({"period": period, "variant": variant, "state": state, "label": label,
                    "cell": cell(data, states == state)})
            result["weighted_gains"].append({"period": period, "variant": variant, **weighted_gain(data, variant)})
    months = np.asarray(pooled["exit_timestamp"], dtype="datetime64[s]").astype("datetime64[M]")
    first = np.datetime64(folds[0]["outer_start"][:7], "M")
    last = np.datetime64(folds[-1]["outer_end_exclusive"][:7], "M")
    for month in np.arange(first, last+np.timedelta64(1, "M"), dtype="datetime64[M]"):
        result["periods"].append({"kind": "month", "period": str(month), "cell": aggregate_score_cell(pooled, months == month)})
    for year in years:
        result["periods"].append({"kind": "leave_one_year_out", "period": f"without-{year}",
            "cell": aggregate_score_cell(pooled, pooled["outer_year"] != year)})
    daily = {name: np.concatenate([part[name] for part in daily_folds]) for name in daily_folds[0]}
    return result, daily, memberships


def integer_encoding(values, counts, years, days):
    values = np.asarray(values, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.int64)
    require(np.isfinite(values).all() and values.ndim == counts.ndim == 1 and values.shape == counts.shape,
            "exact encoding shapes/finite")
    require(np.all(counts >= 0), "nonnegative observation counts")
    ratios = [float(value).as_integer_ratio() for value in values]
    denominator = max((ratio[1] for ratio in ratios), default=1)
    integers = [n*(denominator//d) for n, d in ratios]
    require(all(denominator % d == 0 for _, d in ratios), "binary denominators")
    return {"schema": "filang-followup30-exact-ratio-v1", "denominator_power_of_two": denominator.bit_length()-1,
            "numerators": [str(n) for n in integers], "counts": counts.tolist(),
            "outer_year": np.asarray(years, dtype=np.int64).tolist(), "day": np.asarray(days, dtype=np.int64).tolist(),
            "numerator_sum": str(sum(integers)), "count_sum": int(counts.sum()),
            "float_sums_sha256": array_sha(values), "counts_sha256": array_sha(counts)}, integers


def ratio_bootstrap(daily, block_days, *, replicates=2000, base_seed=20261008):
    sums = np.asarray(daily["adapted_paired_loss_sum"], dtype=np.float64)
    counts = np.asarray(daily["binary_count"], dtype=np.int64)
    years, days = np.asarray(daily["outer_year"]), np.asarray(daily["day"])
    encoding, integers = integer_encoding(sums, counts, years, days)
    original_count = int(counts.sum())
    require(original_count > 0, "original bootstrap denominator must be positive")
    require(block_days > 0 and replicates > 0, "bootstrap settings")
    year_values = sorted(set(years.tolist()))
    ranges = [np.flatnonzero(years == year) for year in year_values]
    require(all(len(r) and np.all(np.diff(r) == 1) for r in ranges), "ordered contiguous annual daily records")
    observed = float(sums.sum()/original_count)
    seed = base_seed+1000*30+block_days
    generator = np.random.default_rng(seed)
    ordinary, centered = np.empty(replicates), np.empty(replicates)
    resampled_counts = np.empty(replicates, dtype=np.int64)
    hits = np.empty(replicates, dtype=bool)
    original_integer = sum(integers)
    draw_digest = hashlib.sha256()
    for replica in range(replicates):
        total, null_total, count, integer_total = 0.0, 0.0, 0, 0
        for rows in ranges:
            n = len(rows)
            starts = generator.integers(0, n, size=(n+block_days-1)//block_days, dtype=np.int64)
            local = ((starts[:, None]+np.arange(block_days)) % n).ravel()[:n]
            draw_digest.update(np.ascontiguousarray(starts, dtype="<i8").tobytes())
            selected = rows[local]
            total += float(sums[selected].sum())
            null_total += float((sums-observed*counts)[selected].sum())
            count += int(counts[selected].sum())
            multiplicity = np.bincount(local, minlength=n)
            integer_total += sum(integers[int(rows[i])]*int(multiplicity[i]) for i in np.flatnonzero(multiplicity))
        require(count > 0, "resampled bootstrap denominator must be positive; no redraw")
        ordinary[replica], centered[replica] = total/count, null_total/count
        resampled_counts[replica] = count
        hits[replica] = original_count*integer_total >= 2*original_integer*count
    interval = np.quantile(ordinary, [0.025, 0.975], method="linear")
    arrays = {"ordinary": ordinary, "centered": centered, "resampled_count": resampled_counts, "exact_tail_hits": hits}
    summary = {"block_days": block_days, "replicates": replicates, "seed": seed, "gain": observed,
               "ci95_low": float(interval[0]), "ci95_high": float(interval[1]),
               "exact_tail_hit_count": int(hits.sum()), "p_one_sided": float((1+int(hits.sum()))/(replicates+1)),
               "original_count": original_count, "draw_starts_sha256": draw_digest.hexdigest(),
               "array_hashes": {k: array_sha(v) for k, v in arrays.items()}}
    return summary, arrays, encoding


def decisions(diagnostics, bootstrap):
    annual = {int(row["period"]): row["cell"] for row in diagnostics["periods"] if row["kind"] == "year"}
    pooled = next(row["cell"] for row in diagnostics["periods"] if row["kind"] == "pooled")
    gains = {str(year): row["variants"]["adapted"]["paired"]["log_loss_gain"] for year, row in annual.items()}
    primary = bootstrap["7"]
    positive_years = sum(value is not None and value > 0 for value in gains.values())
    conditions = {"positive_pooled_gain": primary["gain"] > 0, "ci_above_zero": primary["ci95_low"] > 0,
                  "p_below_005": primary["p_one_sided"] < 0.05, "three_positive_years": positive_years >= 3,
                  "latest_2026_positive": gains.get("2026") is not None and gains["2026"] > 0}
    criterion_met = all(conditions.values())
    alignment = {str(year): row["variants"]["adapted"]["paired"]["centered_alignment"] for year, row in annual.items()}
    pooled_alignment = pooled["variants"]["adapted"]["paired"]["centered_alignment"]
    alignment_conditions = {"pooled_alignment_positive": pooled_alignment is not None and pooled_alignment > 0,
        "latest_2026_alignment_positive": alignment.get("2026") is not None and alignment["2026"] > 0,
        "three_positive_alignment_years": sum(value is not None and value > 0 for value in alignment.values()) >= 3}
    return {"primary": {"conditions": conditions, "criterion_met": criterion_met, "annual_gains": gains,
                        "positive_years": positive_years, "outcome": "inconclusive",
                        "outcome_if_verified": "supported" if criterion_met else "not-supported"},
            "continuation": {"conditions": {"primary_supported_if_verified": criterion_met, **alignment_conditions},
                             "gate_if_verified": bool(criterion_met and all(alignment_conditions.values())),
                             "annual_centered_alignment": alignment, "pooled_centered_alignment": pooled_alignment,
                             "status": "PENDING_INDEPENDENT_AUDIT"}}
