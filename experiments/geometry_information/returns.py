"""Frozen R2 conditional-return estimation and causal signed-score policies.

The only numerical fit is a ridge normal-equation solve. A full G10 sufficient
statistic may be reused only inside this attempt for the exact same fitting
rows, targets and feature source. Shorter geometry matrices are name-projected,
not truncated: their wick columns occur at different positions in G10.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.linalg import cho_factor, cho_solve

try:
    from . import common as c
    from . import economics
except ImportError:  # Direct executable entry points.
    import common as c
    import economics


def phase_targets(source, causal_valid, start, end):
    """Full-source executable next-bar log targets, retaining actual zeros."""
    ts = source["timestamps"]
    opens = source["ohlc"][:, 0]
    step = source["interval_seconds"]
    phase = (ts >= start) & (ts < end)
    valid = np.zeros(len(ts), dtype=bool)
    valid[:-2] = (causal_valid[:-2] & phase[:-2] & (ts[2:] < end)
                  & (ts[2:] - ts[:-2] == 2 * step))
    rows = np.flatnonzero(valid)
    target = np.full(len(ts), np.nan, dtype=np.float64)
    simple = target.copy()
    target[rows] = np.log(opens[rows + 2] / opens[rows + 1])
    simple[rows] = opens[rows + 2] / opens[rows + 1] - 1
    direction = np.zeros(len(ts), dtype=np.int8)
    direction[rows] = np.sign(opens[rows + 2] - opens[rows + 1]).astype(np.int8)
    entry = np.full(len(ts), -1, dtype=np.int64)
    exit_ = entry.copy()
    entry[rows], exit_[rows] = rows + 1, rows + 2
    c.require(np.isfinite(target[rows]).all(), "finite log-return targets")
    return {"row_index": np.arange(len(ts), dtype=np.int64), "timestamp": ts,
            "causal_feature_valid": np.asarray(causal_valid, dtype=bool).copy(),
            "phase_mask": phase, "target_valid": valid, "direction": direction,
            "target_log_return": target, "target_simple_return": simple,
            "entry_row": entry, "exit_row": exit_}


def feature_projection(n, family):
    full = c.feature_names(10, "G")
    lookup = {name: i for i, name in enumerate(full)}
    names = c.feature_names(n, family)
    c.require(len(lookup) == len(full), "unique full geometry columns")
    return np.array([lookup[name] for name in names], dtype=np.int64)


def build_statistics(X, y):
    """Construct one full-feature float64 Gram and cross-product sample."""
    X, y = np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)
    c.require(X.ndim == 2 and y.shape == (len(X),) and len(y) > 0,
              "aligned nonempty ridge fitting sample")
    c.require(np.isfinite(X).all() and np.isfinite(y).all(), "finite ridge fitting sample")
    return {"count": len(y), "x_mean": X.mean(axis=0), "gram_mean": X.T @ X / len(y),
            "xy_mean": X.T @ y / len(y), "y_mean": float(y.mean()),
            "y2_mean": float(y @ y / len(y))}


def ridge_objective(theta, X, y, penalty):
    residual = X @ theta[1:] + theta[0] - y
    gradient = np.empty_like(theta)
    gradient[0] = residual.mean()
    gradient[1:] = X.T @ residual / len(y) + penalty * theta[1:]
    value = float((residual @ residual / len(y) + penalty * (theta[1:] @ theta[1:])) / 2)
    return value, gradient


def fit_ridge(X, y, penalty, statistics, columns, tolerance=1e-10):
    """Solve the declared centered system, then check the direct row gradient.

    There is no jitter, pseudoinverse, iterative fallback, scaling or additional
    regularization. Failed parameters and diagnostics remain returned for the
    caller to retain before stopping the attempt.
    """
    X, y = np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)
    columns = np.asarray(columns, dtype=np.int64)
    c.require(X.shape == (len(y), len(columns)) and len(y) == statistics["count"] > 0,
              "ridge projected sample alignment")
    c.require(np.isfinite(X).all() and np.isfinite(y).all(), "finite ridge fitting sample")
    c.require(np.isfinite(penalty) and penalty > 0 and tolerance == 1e-10,
              "positive ridge penalty and frozen direct-gradient tolerance")
    began, cpu = time.perf_counter(), time.process_time()
    xm = statistics["x_mean"][columns]
    matrix = statistics["gram_mean"][np.ix_(columns, columns)] - np.outer(xm, xm)
    matrix[np.diag_indices_from(matrix)] += penalty
    rhs = statistics["xy_mean"][columns] - xm * statistics["y_mean"]
    parameters = np.full(len(columns) + 1, np.nan)
    value, gradient = np.nan, np.full_like(parameters, np.nan)
    normal_residual = np.full(len(columns), np.nan)
    success, status, message = False, "factorization_failure", ""
    try:
        factor = cho_factor(matrix, lower=True, check_finite=True)
        parameters[1:] = cho_solve(factor, rhs, check_finite=True)
        parameters[0] = statistics["y_mean"] - xm @ parameters[1:]
        normal_residual = matrix @ parameters[1:] - rhs
        value, gradient = ridge_objective(parameters, X, y, penalty)
        finite = (np.isfinite(parameters).all() and np.isfinite(value)
                  and np.isfinite(gradient).all() and np.isfinite(normal_residual).all())
        success = bool(finite and np.max(np.abs(gradient)) <= tolerance)
        status = "direct_gradient_tolerance" if success else "terminal_gradient_failure"
        message = "direct analytic gradient within frozen tolerance" if success else "nonfinite or excessive direct analytic gradient"
    except (np.linalg.LinAlgError, ValueError) as error:
        message = str(error)
    return {"intercept": float(parameters[0]), "coefficients": parameters[1:].tolist(),
            "coefficient_sha256": c.array_sha(parameters, "<f8"),
            "objective": float(value), "gradient": gradient.tolist(),
            "max_abs_gradient": float(np.max(np.abs(gradient))),
            "normal_residual": normal_residual.tolist(),
            "max_abs_normal_residual": float(np.max(np.abs(normal_residual))),
            "accepted": success,
            "solver": {"method": "centered-normal-equations-Cholesky", "success": success,
                       "status": status, "message": message, "factorizations": 1,
                       "direct_gradient_tolerance": tolerance, "jitter": 0.0, "fallback": None},
            "wall_seconds": time.perf_counter() - began, "cpu_seconds": time.process_time() - cpu}


def predict(X, model):
    return np.asarray(X, dtype=np.float64) @ np.asarray(model["coefficients"]) + model["intercept"]


def return_scores(y, prediction):
    y, prediction = np.asarray(y, dtype=np.float64), np.asarray(prediction, dtype=np.float64)
    c.require(y.shape == prediction.shape and len(y) > 0 and np.isfinite(y).all()
              and np.isfinite(prediction).all(), "aligned finite return scores")
    residual = prediction - y
    nonzero = y != 0
    return {"target_count": len(y), "zero_count": int(np.count_nonzero(~nonzero)),
            "target_sum": float(y.sum()), "prediction_sum": float(prediction.sum()),
            "squared_error_sum": float(residual @ residual), "mse": float(np.mean(residual ** 2)),
            "absolute_error_sum": float(np.abs(residual).sum()),
            "nonzero_direction_correct": int(np.count_nonzero(np.sign(prediction[nonzero]) == np.sign(y[nonzero])))}


def select_model(candidates, tolerance=1e-12):
    c.require(bool(candidates) and all(row["accepted"] for row in candidates),
              "every ridge candidate must be accepted before selection")
    minimum = min(row["validation_scores"]["mse"] for row in candidates)
    tied = [row for row in candidates if row["validation_scores"]["mse"] <= minimum + tolerance]
    return min(tied, key=lambda row: (row["n"], -row["lambda"])), minimum


def policy_grid(fee_bps=10, slippage_bps=2):
    f, s = fee_bps / 10000, slippage_bps / 10000
    c.require(0 <= f < 1 and 0 <= s < 1, "valid primary policy costs")
    k = -math.log((1 - f) ** 2 * (1 - s) / (1 + s))
    result = [{"id": "cash", "kind": "cash", "entry_multiple": None, "exit_multiple": None,
               "entry_threshold": None, "exit_threshold": None, "roundtrip_log_cost": k}]
    for entry, etag in ((0.0, "0"), (0.5, "05"), (1.0, "1")):
        for exit_, xtag in ((-0.5, "m05"), (0.0, "0")):
            result.append({"id": f"e{etag}_x{xtag}", "kind": "threshold",
                           "entry_multiple": entry, "exit_multiple": exit_,
                           "entry_threshold": entry * k, "exit_threshold": exit_ * k,
                           "roundtrip_log_cost": k})
    return result


def score_requests(timestamps, scores, *, start, end, policy):
    """Vectorized stateful signed-score requests, aligned to source candles.

    Requests are decisions at each candle close, not positions at that open.
    The existing ledger executes them at the next observed opening. A gap thus
    cannot be anticipated by this adapter. State starts cash at each phase.
    """
    ts, score = np.asarray(timestamps, dtype=np.int64), np.asarray(scores, dtype=np.float64)
    c.require(ts.shape == score.shape and ts.ndim == 1 and np.all(np.diff(ts) > 0),
              "aligned chronological signed scores")
    c.require(not np.isinf(score).any() and end > start, "finite or missing signed scores")
    rows = np.flatnonzero((ts >= start) & (ts < end))
    out = np.full(len(ts), np.nan)
    if policy["kind"] == "cash":
        out[rows] = 0
        return out
    c.require(policy["kind"] == "threshold", "signed-score policy kind")
    entry, exit_ = policy["entry_threshold"], policy["exit_threshold"]
    c.require(np.isfinite(entry) and np.isfinite(exit_) and exit_ <= entry,
              "ordered finite signed-score thresholds")
    values = score[rows]
    event = np.where(np.isfinite(values) & (values >= entry), 1,
                     np.where(~np.isfinite(values) | (values < exit_), 0, -1)).astype(np.int8)
    if len(rows):
        previous = np.maximum.accumulate(np.where(event >= 0, np.arange(len(rows)), -1))
        out[rows] = np.where(previous >= 0, event[np.maximum(previous, 0)], 0)
    return out


def run_score_ledger(timestamps, opens, scores, *, start, end, interval_seconds,
                     fee_bps, slippage_bps, score_policy):
    """Use signed forecasts through explicit 0/1 requests; never use sigmoid."""
    if score_policy["kind"] == "buy_hold":
        requests = np.full(len(timestamps), np.nan)
        mode = "buy_hold"
    else:
        requests = score_requests(timestamps, scores, start=start, end=end, policy=score_policy)
        mode = "cash" if score_policy["kind"] == "cash" else "threshold"
    ledger = economics.run_ledger(timestamps, opens, requests, start=start, end=end,
        interval_seconds=interval_seconds, fee_bps=fee_bps, slippage_bps=slippage_bps,
        entry_threshold=0.5, exit_threshold=0.5, policy=mode)
    trace = ledger["trace"]
    trace["signal_request"] = trace.pop("signal_probability")
    trace["signal_score"] = np.full(len(trace["row"]), np.nan)
    available = trace["signal_row"] >= 0
    trace["signal_score"][available] = np.asarray(scores)[trace["signal_row"][available]]
    ledger["metrics"]["signal_kind"] = "binary_position_request_from_signed_conditional_log_return"
    ledger["metrics"]["score_policy_id"] = score_policy["id"]
    ledger["metrics"]["score_entry_threshold"] = score_policy.get("entry_threshold")
    ledger["metrics"]["score_exit_threshold"] = score_policy.get("exit_threshold")
    return ledger


def select_policy(candidates, tolerance=1e-12):
    c.require(len(candidates) == 7 and len({row["policy"]["id"] for row in candidates}) == 7,
              "complete seven-policy selection")
    maximum = max(row["metrics"]["net_log_return"] for row in candidates)
    tied = [row for row in candidates if row["metrics"]["net_log_return"] >= maximum - tolerance]
    def order(row):
        policy = row["policy"]
        return (policy["kind"] != "cash", row["metrics"]["one_way_turnover"],
                -(policy["entry_threshold"] or 0), policy["exit_threshold"] or 0, policy["id"])
    return min(tied, key=order), maximum


def bootstrap_economics(folds, minutes, block_days, replicates=2000, base_seed=20261008):
    """Equal-calendar-day paired economic tests using identical block draws."""
    parts = [np.column_stack((fold["daily_G"] - fold["daily_B"], fold["daily_G"])) for fold in folds]
    c.require(bool(parts) and all(len(part) > 0 and np.isfinite(part).all() for part in parts),
              "finite complete calendar-day economic observations")
    count = sum(len(part) for part in parts)
    observed = sum((part.sum(axis=0) for part in parts), np.zeros(2)) / count
    rng = np.random.default_rng(base_seed + 1000 * minutes + block_days)
    ordinary, centered = np.empty((replicates, 2)), np.empty((replicates, 2))
    for replicate in range(replicates):
        total, null_total = np.zeros(2), np.zeros(2)
        for part in parts:
            days = len(part)
            starts = rng.integers(0, days, size=(days + block_days - 1) // block_days, dtype=np.int64)
            indices = ((starts[:, None] + np.arange(block_days)) % days).ravel()[:days]
            total += part[indices].sum(axis=0)
            null_total += (part - observed)[indices].sum(axis=0)
        ordinary[replicate], centered[replicate] = total / count, null_total / count
    ci = np.quantile(ordinary, [0.025, 0.975], axis=0, method="linear")
    comparisons = {}
    for index, name in enumerate(("G_minus_B", "G_minus_cash")):
        comparisons[name] = {"mean_daily_net_log_gain": float(observed[index]),
            "total_net_log_gain": float(observed[index] * count), "calendar_days": count,
            "ci95_low": float(ci[0, index]), "ci95_high": float(ci[1, index]),
            "p_one_sided": float((1 + np.count_nonzero(centered[:, index] >= observed[index])) / (replicates + 1))}
    return {"block_days": block_days, "replicates": replicates,
            "seed": base_seed + 1000 * minutes + block_days, "comparisons": comparisons,
            "intersection_union_p": max(row["p_one_sided"] for row in comparisons.values()),
            "ordinary_sha256": c.array_sha(ordinary, "<f8"), "centered_sha256": c.array_sha(centered, "<f8")}, ordinary, centered
