"""Exact feature decoding and the frozen Round 1 estimation primitives.

This module never selects a scientific setting from outer outcomes. Runtime
thread controls must be established by the entry point before importing it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import struct
import time

import numpy as np
from scipy.optimize import minimize
from scipy.linalg import cho_factor, cho_solve
from scipy.special import expit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def object_sha(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def array_sha(value, dtype=None):
    a = np.asarray(value, dtype=dtype)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_bytes(json_bytes(value))
    temporary.replace(path)


def timestamp(date):
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp())


def load_source(data_dir, source, provenance):
    """Verify pinned raw/prepared identities and validate original source rows."""
    minutes = source["minutes"]
    records = [s for s in provenance["sources"] if s["minutes"] == minutes]
    require(len(records) == 1, "source provenance coverage")
    record = records[0]
    for key in ("repo", "revision", "filename", "sha256", "expected_source_rows", "expected_source_bytes", "minutes"):
        require(record["source"][key] == source[key], f"provenance source {key}")
    require(record["source_sha256"] == source["sha256"], "provenance raw checksum")
    require(record["csv_sha256"] == source["prepared_csv_sha256"], "provenance prepared checksum")
    raw = Path(data_dir) / "raw" / source["filename"]
    require(raw.stat().st_size == source["expected_source_bytes"] and digest(raw) == source["sha256"], "raw source bytes/checksum")
    path = Path(data_dir) / f"{minutes}m" / "ohlcv.csv"
    require(path.stat().st_size == record["csv_bytes"] and digest(path) == source["prepared_csv_sha256"], "prepared source bytes/checksum")
    with path.open() as f:
        require(f.readline().rstrip("\r\n") == "timestamp,open,high,low,close,volume", "CSV schema")
    values = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float64, ndmin=2)
    require(values.shape == (source["expected_source_rows"], 6), "CSV shape")
    require(np.isfinite(values).all(), "finite source values")
    times = values[:, 0].astype(np.int64)
    ohlc = np.ascontiguousarray(values[:, 1:5])
    step = minutes * 60
    require(np.array_equal(times, values[:, 0]) and np.all(times % step == 0), "timestamp integer/grid")
    require(np.all(np.diff(times) > 0), "timestamp ordering")
    require(np.all(ohlc > 0) and np.all(values[:, 5] >= 0), "positive prices/nonnegative volume")
    require(np.all(ohlc[:, 2] <= np.minimum(ohlc[:, 0], ohlc[:, 3])) and
            np.all(ohlc[:, 1] >= np.maximum(ohlc[:, 0], ohlc[:, 3])), "OHLC geometry")
    missing = int(np.sum(np.diff(times) // step - 1))
    require(missing == source["missing_grid_bars"] == record["missing_grid_bars"], "source gaps")
    return {"timestamps": times, "ohlc": ohlc, "path": str(path.resolve()),
            "sha256": source["prepared_csv_sha256"], "raw_sha256": source["sha256"],
            "rows": len(times), "interval_seconds": step, "missing_grid_bars": missing}


def causal_mask(times, step, history_start, end, width=10):
    times = np.asarray(times, dtype=np.int64)
    valid = np.zeros(len(times), dtype=bool)
    if len(times) >= width:
        # Strictly increasing grid timestamps make endpoint distance equivalent
        # to checking every internal step; missing grid points increase it.
        valid[width-1:] = ((times[width-1:] - times[:len(times)-width+1] == (width-1)*step)
                           & (times[:len(times)-width+1] >= history_start)
                           & (times[width-1:] < end))
    return valid


def decode_keys(folder, source, history_start, end):
    """Check all seals/identities and decode canonical native ten-bar keys."""
    folder = Path(folder)
    manifest_path = folder / "manifest.json"
    require((folder / "manifest.sha256").read_text() == digest(manifest_path) + "\n", "native manifest seal")
    manifest = json.loads(manifest_path.read_bytes())
    context_path = folder / "context.json"
    context = json.loads(context_path.read_bytes())
    context_sha = digest(context_path)
    require(manifest["status"] == "COMPLETE" and manifest["format"] == "geometry-keys-v1", "native completeness/schema")
    require(manifest["context_sha256"] == context_sha, "native context binding")
    require(context["source_sha256"] == source["sha256"] == manifest["source_sha256"], "native source identity")
    require(context["bars"] == 10 and context["mode"] == "oriented" and context["key_layout"] == "geometry-key-256-v1", "native geometry ABI")
    require(timestamp(context["history_start"]) == history_start and timestamp(context["end"]) == end,
            "native history bounds")
    require(context["interval_seconds"] == source["interval_seconds"], "native interval")
    require(context["eligibility"] == "all_window_rows_in_history_consecutive_past_only", "native eligibility")
    require(digest(folder / "timings.json") == manifest["timings_sha256"], "native timing binding")
    path = folder / "keys.bin"
    raw = path.read_bytes()
    require(len(raw) >= 232 and raw[:8] == b"FGKEYS01", "native key magic/size")
    payload_sha = hashlib.sha256(raw[:-64]).hexdigest()
    require(raw[-64:] == payload_sha.encode() == manifest["keys_payload_sha256"].encode(), "native payload seal")
    require(hashlib.sha256(raw).hexdigest() == manifest["keys_file_sha256"], "native full-file binding")
    require(len(raw) == manifest["keys_file_bytes"] and len(raw)-64 == manifest["keys_payload_bytes"], "native byte counts")
    require(raw[8:72].decode() == context_sha and raw[72:136].decode() == source["sha256"], "native header identities")
    nrows, interval, width, count = struct.unpack_from("<4Q", raw, 136)
    require(nrows == source["rows"] == manifest["source_rows"] and interval == source["interval_seconds"] and width == 10,
            "native header parameters")
    require(len(raw) == 168 + 40*count + 64 and count == manifest["records"], "native record count")
    records = np.frombuffer(raw, dtype="<u8", count=count*5, offset=168).reshape(-1, 5)
    indices = records[:, 0].astype(np.int64)
    valid = causal_mask(source["timestamps"], interval, history_start, end)
    require(np.array_equal(indices, np.flatnonzero(valid)), "native complete original-row coverage")
    words = records[:, 1:]
    require(np.all(words[:, 3] >> np.uint64(58) == np.uint64(26)), "native width/orientation/reserved bits")
    ranks = np.empty((len(indices), 10, 4), dtype=np.uint8)
    for lag in range(10):
        for endpoint in range(4):
            bit = 6*(4*lag+endpoint)
            word, shift = divmod(bit, 64)
            value = words[:, word] >> np.uint64(shift)
            if shift > 58:
                value = value | (words[:, word+1] << np.uint64(64-shift))
            ranks[:, lag, endpoint] = (value & np.uint64(63)).astype(np.uint8)
    up = ((words[:, 3, None] >> np.arange(48, 58, dtype=np.uint64)) & np.uint64(1)).astype(bool)
    require(np.all(ranks < 40) and np.all(np.diff(ranks.astype(np.int16), axis=2) >= 0), "native rank bounds/order")
    sorted_ranks = np.sort(ranks.reshape(-1, 40), axis=1)
    require(np.all(sorted_ranks[:, 0] == 0) and np.all(np.diff(sorted_ranks.astype(np.int16), axis=1) <= 1), "native dense global ranks")
    require(not np.any(up & (ranks[:, :, 1] == ranks[:, :, 2])), "native flat-body up bit")
    return {"indices": indices, "ranks": ranks, "up": up, "valid": valid,
            "context": context, "manifest": manifest, "context_sha256": context_sha,
            "manifest_sha256": digest(manifest_path), "keys_sha256": digest(path)}


def feature_names(n, family):
    names = [f"body[{k}].{side}" for k in range(n) for side in ("up", "down")]
    names += [f"cc[{k}].{side}" for k in range(n-1) for side in ("up", "down")]
    if family == "G":
        names += [f"comparison[{k},{a},{b}].{relation}" for k in range(1, n)
                  for a in range(4) for b in range(4) for relation in ("less", "equal")]
        names += [f"wick[{k}].{side}_present" for k in range(n) for side in ("lower", "upper")]
    else:
        require(family == "B", "feature family")
    return names


def features(ranks, up, n, family):
    require(n in (2, 3, 5, 10), "history width")
    r, u = ranks[:, :n], up[:, :n]
    cols = []
    for k in range(n):
        cols.extend([u[:, k], (~u[:, k]) & (r[:, k, 1] < r[:, k, 2])])
    close = np.where(u, r[:, :, 2], r[:, :, 1])
    for k in range(n-1):
        cols.extend([close[:, k] > close[:, k+1], close[:, k] < close[:, k+1]])
    if family == "G":
        for k in range(1, n):
            for a in range(4):
                for b in range(4):
                    cols.extend([r[:, 0, a] < r[:, k, b], r[:, 0, a] == r[:, k, b]])
        for k in range(n):
            cols.extend([r[:, k, 0] < r[:, k, 1], r[:, k, 2] < r[:, k, 3]])
    else:
        require(family == "B", "feature family")
    result = np.ascontiguousarray(np.column_stack(cols), dtype=np.uint8)
    require(result.shape[1] == len(feature_names(n, family)), "feature dimensions")
    return result


def phase_labels(source, causal_valid, start, end):
    """Full original-row labels. Phase membership is the decision candle OPEN."""
    times, opens, step = source["timestamps"], source["ohlc"][:, 0], source["interval_seconds"]
    count = len(times)
    phase = (times >= start) & (times < end)
    valid = np.zeros(count, dtype=bool)
    valid[:-2] = (causal_valid[:-2] & phase[:-2] & (times[2:] < end)
                  & (times[2:]-times[:-2] == 2*step))
    rows = np.flatnonzero(valid)
    direction = np.zeros(count, dtype=np.int8)
    direction[rows] = np.sign(opens[rows+2]-opens[rows+1]).astype(np.int8)
    returns = np.full(count, np.nan)
    returns[rows] = opens[rows+2]/opens[rows+1]-1
    entry, exit_ = np.full(count, -1, dtype=np.int64), np.full(count, -1, dtype=np.int64)
    entry[rows], exit_[rows] = rows+1, rows+2
    return {"row_index": np.arange(count, dtype=np.int64), "timestamp": times,
            "causal_feature_valid": causal_valid.copy(), "phase_mask": phase,
            "classification_valid": valid, "binary_mask": valid & (direction != 0),
            "direction": direction, "target_return": returns, "entry_row": entry, "exit_row": exit_}


def objective(theta, X, y, penalty):
    z = X @ theta[1:] + theta[0]
    residual = expit(z)-y
    value = float(np.mean(np.logaddexp(0.0, z)-y*z) + penalty*np.dot(theta[1:], theta[1:])/2)
    gradient = np.empty_like(theta)
    gradient[0] = residual.mean()
    gradient[1:] = X.T @ residual / len(y) + penalty*theta[1:]
    return value, gradient


def _fit_lbfgs_model(X, y, penalty, optimizer, initial=None):
    X, y = np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)
    require(len(y) > 0 and np.any(y == 0) and np.any(y == 1) and np.all((y == 0) | (y == 1)), "fit needs both binary classes")
    if initial is None:
        p = (y.sum()+1)/(len(y)+2)
        initial = np.zeros(X.shape[1]+1)
        initial[0] = math.log(p/(1-p))
    initial = np.asarray(initial, dtype=np.float64).copy()
    began, cpu = time.perf_counter(), time.process_time()
    result = minimize(objective, initial, args=(X, y, penalty), method="L-BFGS-B", jac=True,
                      options={k: optimizer[k] for k in ("maxiter", "ftol", "gtol", "maxls")})
    value, gradient = objective(result.x, X, y, penalty)
    accepted = bool(result.success and np.isfinite(result.x).all() and np.isfinite(value)
                    and np.isfinite(gradient).all() and np.max(np.abs(gradient)) <= 5e-6)
    return {"intercept": float(result.x[0]), "coefficients": result.x[1:].tolist(),
            "objective": value, "gradient": gradient.tolist(), "max_abs_gradient": float(np.max(np.abs(gradient))),
            "coefficient_sha256": array_sha(result.x, "<f8"), "initializer_sha256": array_sha(initial, "<f8"),
            "accepted": accepted, "optimizer": {"success": bool(result.success), "status": int(result.status),
            "message": str(result.message), "iterations": int(result.nit), "function_evaluations": int(result.nfev),
            "gradient_evaluations": int(result.njev), "reported_objective": float(result.fun)},
            "wall_seconds": time.perf_counter()-began, "cpu_seconds": time.process_time()-cpu}


def objective_hessian(theta, X, penalty):
    """Full curvature for [intercept, beta], without penalizing the intercept.

    This block construction equals [1,X].T @ diag(w) @ [1,X]. Computing the
    weight from exp(-abs(z)) retains positive curvature when expit(z) rounds
    to one. There is no diagonal jitter, scaling, or dropped constant column.
    """
    z = X @ theta[1:] + theta[0]
    tail = np.exp(-np.abs(z))
    weights = tail / (1.0+tail)**2 / len(X)
    hessian = np.empty((X.shape[1]+1, X.shape[1]+1), dtype=np.float64)
    hessian[0, 0] = weights.sum()
    cross = X.T @ weights
    hessian[0, 1:], hessian[1:, 0] = cross, cross
    hessian[1:, 1:] = X.T @ (weights[:, None]*X)
    hessian[np.arange(1, len(hessian)), np.arange(1, len(hessian))] += penalty
    return hessian


def _fit_newton_model(X, y, penalty, optimizer, initial=None):
    X, y = np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64)
    require(X.ndim == 2 and y.shape == (len(X),), "aligned Newton matrix and labels")
    require(len(y) > 0 and np.any(y == 0) and np.any(y == 1) and np.all((y == 0) | (y == 1)), "fit needs both binary classes")
    require(np.isfinite(penalty) and penalty > 0, "Newton requires positive finite ridge penalty")
    if initial is None:
        p = (y.sum()+1)/(len(y)+2)
        initial = np.zeros(X.shape[1]+1)
        initial[0] = math.log(p/(1-p))
    initial = np.asarray(initial, dtype=np.float64).copy()
    require(initial.shape == (X.shape[1]+1,), "Newton initializer dimension")
    maximum = optimizer["maxiter"]
    trials = optimizer["max_line_search_trials"]
    tolerance = optimizer["gtol"]
    first_step = optimizer["initial_step"]
    shrink = optimizer["backtracking_factor"]
    armijo = optimizer["armijo_c1"]
    require(isinstance(maximum, int) and maximum >= 0 and isinstance(trials, int) and trials >= 1,
            "Newton iteration/trial bounds")
    require(np.isfinite(tolerance) and tolerance > 0 and first_step == 1.0 and shrink == 0.5
            and armijo == 1e-4, "Newton frozen gradient/Armijo settings")
    began, cpu = time.perf_counter(), time.process_time()
    current = initial.copy()
    updates, nfev, njev, nhev = 0, 0, 0, 0
    steps, backtracks, trial_counts = [], [], []
    nonfinite_trials = 0
    value, gradient = objective(current, X, y, penalty)
    nfev += 1
    njev += 1
    status, reason, detail = 1, "maximum_iterations", "maximum accepted Newton updates reached"
    success = False
    while True:
        if not (np.isfinite(current).all() and np.isfinite(value) and np.isfinite(gradient).all()):
            status, reason, detail = 2, "nonfinite_evaluation", "nonfinite parameters, objective, or analytic gradient"
            break
        # This is the sole success condition, checked before any update and
        # again immediately after every accepted update, including the last.
        if np.max(np.abs(gradient)) <= tolerance:
            success, status, reason, detail = True, 0, "gradient_tolerance", "maximum absolute analytic gradient reached tolerance"
            break
        if updates >= maximum:
            break
        hessian = objective_hessian(current, X, penalty)
        nhev += 1
        if not np.isfinite(hessian).all():
            status, reason, detail = 3, "nonfinite_hessian", "full Newton Hessian is nonfinite"
            break
        try:
            factor = cho_factor(hessian, lower=True, check_finite=True)
            direction = cho_solve(factor, -gradient, check_finite=True)
        except (np.linalg.LinAlgError, ValueError) as error:
            status, reason, detail = 4, "factorization_failure", str(error)
            break
        if not np.isfinite(direction).all():
            status, reason, detail = 5, "nonfinite_direction", "Cholesky direction is nonfinite"
            break
        slope = float(gradient @ direction)
        if not np.isfinite(slope) or slope >= 0:
            status, reason, detail = 6, "non_descent_direction", "gradient dot Newton direction must be finite and negative"
            break
        accepted_step = False
        for j in range(trials):
            alpha = first_step*shrink**j
            candidate = current+alpha*direction
            trial_value, trial_gradient = objective(candidate, X, y, penalty)
            nfev += 1
            njev += 1
            finite = (np.isfinite(candidate).all() and np.isfinite(trial_value)
                      and np.isfinite(trial_gradient).all())
            if not finite:
                nonfinite_trials += 1
                continue
            if trial_value <= value+armijo*alpha*slope:
                current, value, gradient = candidate, trial_value, trial_gradient
                updates += 1
                steps.append(float(alpha))
                backtracks.append(j)
                trial_counts.append(j+1)
                accepted_step = True
                break
        if not accepted_step:
            trial_counts.append(trials)
            status, reason, detail = 7, "line_search_failure", "no finite Armijo trial accepted within the fixed trial budget"
            break
    reported_objective = float(value)
    # Match the existing fit contract: independently recompute terminal value
    # and analytic gradient outside the optimizer's evaluation counters.
    value, gradient = objective(current, X, y, penalty)
    finite_final = (np.isfinite(current).all() and np.isfinite(value) and np.isfinite(gradient).all())
    max_gradient = float(np.max(np.abs(gradient)))
    if success and (not finite_final or max_gradient > tolerance):
        success, status, reason, detail = False, 8, "terminal_recomputation_failure", "terminal recomputation does not meet finite gradient tolerance"
    accepted = bool(success and finite_final and max_gradient <= 5e-6)
    return {"intercept": float(current[0]), "coefficients": current[1:].tolist(),
            "objective": float(value), "gradient": gradient.tolist(), "max_abs_gradient": max_gradient,
            "coefficient_sha256": array_sha(current, "<f8"), "initializer_sha256": array_sha(initial, "<f8"),
            "accepted": accepted, "optimizer": {"method": "Newton-Cholesky-Armijo", "success": success,
            "status": status, "stop_reason": reason, "message": detail, "iterations": updates,
            "function_evaluations": nfev, "gradient_evaluations": njev, "hessian_evaluations": nhev,
            "reported_objective": reported_objective, "step_sizes": steps, "backtrack_counts": backtracks,
            "line_search_trial_counts": trial_counts, "nonfinite_line_search_trials": nonfinite_trials},
            "wall_seconds": time.perf_counter()-began, "cpu_seconds": time.process_time()-cpu}


def fit_model(X, y, penalty, optimizer, initial=None):
    """Dispatch only the method frozen for this attempt; never fall back."""
    method = optimizer.get("method", "L-BFGS-B")
    if method == "L-BFGS-B":
        return _fit_lbfgs_model(X, y, penalty, optimizer, initial)
    if method == "Newton-Cholesky-Armijo":
        return _fit_newton_model(X, y, penalty, optimizer, initial)
    raise ValueError(f"unsupported frozen optimizer method: {method}")


def theta(model):
    return np.array([model["intercept"], *model["coefficients"]], dtype=np.float64)


def predict(X, model):
    z = X @ np.asarray(model["coefficients"]) + model["intercept"]
    return expit(z), z


def log_losses(y, probabilities=None, logits=None):
    y = np.asarray(y, dtype=np.float64)
    if logits is not None:
        return np.logaddexp(0.0, logits)-y*logits
    p = np.asarray(probabilities, dtype=np.float64)
    require(np.all((p > 0) & (p < 1)), "baseline probabilities must be strictly interior")
    return -np.where(y == 1, np.log(p), np.log1p(-p))


def scores(direction, probabilities, logits=None, flat_count=0):
    direction = np.asarray(direction)
    y = (direction == 1).astype(np.float64)
    require(len(y) > 0 and np.all(direction != 0), "scores need binary observations")
    p = np.asarray(probabilities)
    require(np.isfinite(p).all(), "finite scored probabilities")
    loss = log_losses(y, p, logits)
    predicted = p >= 0.5
    up, down = y == 1, y == 0
    accuracy_up = float(predicted[up].mean()) if up.any() else None
    accuracy_down = float((~predicted[down]).mean()) if down.any() else None
    return {"binary_count": len(y), "up_count": int(up.sum()), "down_count": int(down.sum()),
            "flat_count": int(flat_count), "binary_log_loss": float(loss.mean()), "loss_sum": float(loss.sum()),
            "brier": float(np.mean((p-y)**2)), "brier_sum": float(np.sum((p-y)**2)),
            "accuracy": float(np.mean(predicted == up)), "correct_count": int(np.sum(predicted == up)),
            "up_correct_count": int(np.sum(predicted & up)), "down_correct_count": int(np.sum((~predicted) & down)),
            "balanced_accuracy": (accuracy_up+accuracy_down)/2 if up.any() and down.any() else None}


def select_candidate(candidates, tolerance=1e-12):
    require(bool(candidates) and all(c["accepted"] for c in candidates), "all candidates must be accepted before selection")
    minimum = min(c["validation_scores"]["binary_log_loss"] for c in candidates)
    tied = [c for c in candidates if c["validation_scores"]["binary_log_loss"] <= minimum+tolerance]
    return min(tied, key=lambda c: (c["n"], -c["lambda"])), minimum


def baseline_fit(signs, direction, fitting_mask):
    y = direction[fitting_mask] == 1
    require(len(y) > 0, "baseline fitting sample")
    unconditional = float((y.sum()+1)/(len(y)+2))
    groups = {}
    for sign in (-1, 0, 1):
        g = y[signs[fitting_mask] == sign]
        groups[str(sign)] = {"count": len(g), "up": int(g.sum()),
                             "probability": float((g.sum()+1)/(len(g)+2)) if len(g) else unconditional}
    return {"unconditional": unconditional, "binary_count": len(y), "up_count": int(y.sum()), "lag1": groups}


def baseline_predict(model, signs, mask):
    unconditional, lag1 = np.full(len(signs), np.nan), np.full(len(signs), np.nan)
    unconditional[mask] = model["unconditional"]
    for sign in (-1, 0, 1):
        selected = mask & (signs == sign)
        lag1[selected] = model["lag1"][str(sign)]["probability"]
    return unconditional, lag1


def daily_classification(arrays, start, end):
    days = np.arange(start//86400, (end-1)//86400+1, dtype=np.int64)
    mask = arrays["binary_mask"]
    exits = arrays["exit_row"][mask]
    day_index = arrays["timestamp"][exits]//86400-days[0]
    count = np.bincount(day_index, minlength=len(days)).astype(np.int64)
    flat = arrays["classification_valid"] & (arrays["direction"] == 0)
    flat_index = arrays["timestamp"][arrays["exit_row"][flat]]//86400-days[0]
    result = {"day": days, "binary_count": count,
              "flat_count": np.bincount(flat_index, minlength=len(days)).astype(np.int64)}
    y = (arrays["direction"][mask] == 1).astype(np.float64)
    for name in ("B", "G", "unconditional", "lag1"):
        p = arrays[f"p_{name}"][mask]
        z = arrays[f"logit_{name}"][mask] if name in ("B", "G") else None
        losses = log_losses(y, p, z)
        result[f"loss_sum_{name}"] = np.bincount(day_index, weights=losses, minlength=len(days))
        result[f"correct_{name}"] = np.bincount(day_index, weights=((p >= 0.5) == (y == 1)).astype(np.int64), minlength=len(days)).astype(np.int64)
    result["paired_loss_sum"] = result["loss_sum_B"]-result["loss_sum_G"]
    return result


def bootstrap_gain(folds, minutes, block_days, replicates=2000, base_seed=20261008):
    total_count = sum(int(f["binary_count"].sum()) for f in folds)
    require(total_count > 0, "bootstrap needs binary observations")
    observed = sum(float(f["paired_loss_sum"].sum()) for f in folds)/total_count
    rng = np.random.default_rng(base_seed+1000*minutes+block_days)
    ordinary, centered = np.empty(replicates), np.empty(replicates)
    for replicate in range(replicates):
        loss, null_loss, count = 0.0, 0.0, 0
        for fold in folds:
            sums, counts = fold["paired_loss_sum"], fold["binary_count"]
            days = len(counts)
            starts = rng.integers(0, days, size=(days+block_days-1)//block_days, dtype=np.int64)
            indices = ((starts[:, None]+np.arange(block_days)) % days).ravel()[:days]
            loss += float(sums[indices].sum())
            null_loss += float((sums-observed*counts)[indices].sum())
            count += int(counts[indices].sum())
        require(count > 0, "bootstrap drew no observations")
        ordinary[replicate], centered[replicate] = loss/count, null_loss/count
    ci = np.quantile(ordinary, [0.025, 0.975], method="linear")
    return {"block_days": block_days, "replicates": replicates, "seed": base_seed+1000*minutes+block_days,
            "gain": observed, "ci95_low": float(ci[0]), "ci95_high": float(ci[1]),
            "p_one_sided": float((1+np.count_nonzero(centered >= observed))/(replicates+1)),
            "ordinary_sha256": array_sha(ordinary, "<f8"), "centered_sha256": array_sha(centered, "<f8")}, ordinary, centered


def holm(p_values):
    order = sorted(p_values, key=lambda k: (p_values[k], int(k)))
    adjusted, previous = {}, 0.0
    for rank, key in enumerate(order):
        previous = max(previous, min(1.0, (len(order)-rank)*p_values[key]))
        adjusted[key] = previous
    return adjusted
