#!/usr/bin/env python3
"""Execute the reviewed, frozen R1 protocol; refuses existing output directories.

Thread limits are set before any numerical-library import, including in spawned
workers. No implicit resume/cache, omitted candidate, or economic selection.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

THREAD_VARIABLES = ("VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS")


def protocol_repository_path(path, repo):
    relative = Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    if relative not in ("experiments/geometry_information/round1_protocol.json",
                        "experiments/geometry_information/round1a_protocol.json"):
        raise ValueError("unsupported protocol repository path")
    return relative


def numerical():
    global np, c, economics
    import numpy as np
    import common as c
    import economics


def save_npz(path, arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for value in arrays.values():
        c.require(np.asarray(value).dtype.kind != "O", "object arrays prohibited")
    with path.with_name(path.name+".pending").open("wb") as f:
        np.savez_compressed(f, **arrays)
    path.with_name(path.name+".pending").replace(path)


def nullable_failure(value):
    """A rejected solver may contain NaN/Inf; JSON must still retain its record."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: nullable_failure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [nullable_failure(item) for item in value]
    return value


def metrics_for(arrays):
    mask = arrays["binary_mask"]
    flats = int(np.sum(arrays["classification_valid"] & (arrays["direction"] == 0)))
    return {name: c.scores(arrays["direction"][mask], arrays[f"p_{name}"][mask],
                         arrays[f"logit_{name}"][mask] if name in ("B", "G") else None, flats)
            for name in ("B", "G", "unconditional", "lag1")}


def aggregate_scores(folds):
    result = {}
    for name in ("B", "G", "unconditional", "lag1"):
        parts = [f["scores"][name] for f in folds]
        counts = {key: sum(p[key] for p in parts) for key in
                  ("binary_count", "up_count", "down_count", "flat_count", "correct_count", "up_correct_count", "down_correct_count")}
        loss = sum(p["loss_sum"] for p in parts)
        brier = sum(p["brier_sum"] for p in parts)
        result[name] = {**counts, "loss_sum": loss, "brier_sum": brier,
                        "binary_log_loss": loss/counts["binary_count"], "brier": brier/counts["binary_count"],
                        "accuracy": counts["correct_count"]/counts["binary_count"],
                        "balanced_accuracy": (counts["up_correct_count"]/counts["up_count"]
                                               + counts["down_correct_count"]/counts["down_count"])/2}
    return result


def aggregate_ledgers(parts, years):
    """Compound independent yearly ledgers, retaining their cash resets."""
    selected = [parts[y] for y in years]
    metrics = [p["metrics"] for p in selected]
    daily = np.concatenate([p["daily_net_log"] for p in selected])
    net = np.concatenate([p["trace"]["net_log_return"] for p in selected])
    gross = sum(m["gross_log_return"] for m in metrics)
    total = float(net.sum())
    cumulative = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = -np.expm1(cumulative-np.maximum.accumulate(cumulative))
    trades = [t for p in selected for t in p["trades"]]
    sides = sum(m["one_way_turnover"] for m in metrics)
    seconds = sum(m["seconds_long"] for m in metrics)
    elapsed = sum(int(p["trace"]["timestamp"][-1]-p["trace"]["timestamp"][0]) for p in selected)
    std = float(np.std(daily, ddof=1))
    return {"folds": years, "independent_annual_cash_resets": True,
            "calendar_days": len(daily), "net_log_return": total, "net_return": float(np.expm1(total)),
            "gross_log_return": gross, "gross_return": float(np.expm1(gross)),
            "log_cost_drag": sum(m["log_cost_drag"] for m in metrics), "max_drawdown": float(drawdown.max()),
            "annualized_daily_log_sharpe": float(daily.mean()/std*np.sqrt(365.25)) if std else None,
            "annualized_return": float(np.expm1(total*365.25/len(daily))), "one_way_turnover": sides,
            "completed_trades": len(trades), "trade_win_rate": float(np.mean([t["net_return"] > 0 for t in trades])) if trades else None,
            "mean_trade_net_return": float(np.mean([t["net_return"] for t in trades])) if trades else None,
            "seconds_long": seconds, "exposure_fraction": seconds/elapsed,
            "active_days": sum(m["active_days"] for m in metrics), "gap_count": sum(m["gap_count"] for m in metrics),
            "gap_gross_log_return": sum(m["gap_gross_log_return"] for m in metrics),
            "delayed_exposure_changes": sum(m["delayed_exposure_changes"] for m in metrics),
            "break_even_symmetric_cost_bps_per_side": float(-np.expm1(-gross/sides)*10000) if sides else None}


def timeframe_job(options, minutes):
    numerical()
    began, process_cpu = time.perf_counter(), time.process_time()
    out = Path(options["out"])
    protocol = json.loads((out / "protocol.json").read_bytes())
    provenance = json.loads((out / "provenance.json").read_bytes())
    specification = next(s for s in protocol["data"]["sources"] if s["minutes"] == minutes)
    source = c.load_source(options["data_dir"], specification, provenance)
    history_start, history_end = map(c.timestamp, (protocol["data"]["history_start"], protocol["data"]["end_exclusive"]))
    keys = c.decode_keys(Path(options["keys_dir"]) / f"{minutes}m", source, history_start, history_end)
    root = out / f"{minutes}m"
    root.mkdir(parents=True)
    indices = keys["indices"]
    feature_cache, feature_info = {}, {}
    for n in protocol["features"]["histories"]:
        feature_info[str(n)] = {}
        for family in protocol["features"]["families"]:
            X = c.features(keys["ranks"], keys["up"], n, family)
            feature_cache[n, family] = X
            feature_info[str(n)][family] = {"shape": list(X.shape), "dtype": "uint8", "sha256": c.array_sha(X),
                                            "columns_sha256": c.object_sha(c.feature_names(n, family))}
    feature_receipt = {"minutes": minutes, "source_sha256": source["sha256"], "source_rows": source["rows"],
                       "native": {"context_sha256": keys["context_sha256"], "manifest_sha256": keys["manifest_sha256"],
                                  "keys_sha256": keys["keys_sha256"], "engine_sha256": keys["context"]["engine_sha256"]},
                       "record_count": len(indices), "record_indices_sha256": c.array_sha(indices, "<i8"),
                       "ranks_sha256": c.array_sha(keys["ranks"], np.uint8), "up_sha256": c.array_sha(keys["up"], np.uint8),
                       "features": feature_info}
    c.write_json(root / "features.json", feature_receipt)
    source_feature_seconds = time.perf_counter()-began
    signs = np.zeros(source["rows"], dtype=np.int8)
    close = np.where(keys["up"], keys["ranks"][:, :, 2], keys["ranks"][:, :, 1]).astype(np.int16)
    signs[indices] = np.sign(close[:, 0]-close[:, 1]).astype(np.int8)
    fits, selections, fold_results, daily_folds = [], [], [], []
    candidate_rows = []
    ledger_parts = {s["name"]: {p: {} for p in ("B", "G", "unconditional", "lag1", "cash", "buy_hold")}
                    for s in protocol["economic_diagnostic"]["cost_scenarios_bps_per_side"]}
    fitting_seconds, economics_seconds = 0.0, 0.0

    def fit_one(fold, family, n, penalty, labels, stage, parent=None, fitting_matrix=None):
        nonlocal fitting_seconds
        start_name, end_name = (("inner_train_start", "inner_train_end_exclusive") if stage == "inner"
                                else ("refit_start", "refit_end_exclusive"))
        mask = labels["binary_mask"]
        feature = feature_cache[n, family]
        fit_rows = np.flatnonzero(mask)
        y = (labels["direction"][mask] == 1).astype(np.uint8)
        info = feature_info[str(n)][family]
        metadata = {"schema": "filang-information-fit-v1", "minutes": minutes, "outer_year": fold["year"],
                    "family": family, "n": n, "lambda": penalty, "stage": stage,
                    "fit_start": c.timestamp(fold[start_name]), "fit_end_exclusive": c.timestamp(fold[end_name]),
                    "fit_count": len(fit_rows), "fit_up_count": int(y.sum()), "fit_down_count": int(len(y)-y.sum()),
                    "fit_rows_sha256": c.array_sha(fit_rows, "<i8"), "fit_labels_sha256": c.array_sha(y, np.uint8),
                    "feature_sha256": info["sha256"], "feature_columns_sha256": info["columns_sha256"],
                    "source_sha256": source["sha256"], "native_keys_sha256": keys["keys_sha256"],
                    "protocol_sha256": options["protocol_sha256"], "implementation_sha256": options["implementation_sha256"],
                    "initializer": {"kind": "warm_previous_lambda" if parent else "beta11_zero",
                                    "parent_fit_id": parent["fit_id"] if parent else None,
                                    "parent_coefficient_sha256": parent["coefficient_sha256"] if parent else None},
                    "cache_hit": False}
        metadata["fit_id"] = c.object_sha(metadata)
        folder = root / str(fold["year"]) / family
        path = folder / "candidates" / f"n{n:02}-l{penalty:g}.json" if stage == "inner" else folder / "refit.json"
        try:
            fitting_began = time.perf_counter()
            if fitting_matrix is None:
                fitting_matrix = feature[mask[indices]].astype(np.float64)
            result = c.fit_model(fitting_matrix, y, penalty,
                                 protocol["estimation"]["optimizer"], c.theta(parent) if parent else None)
            fitting_seconds += time.perf_counter()-fitting_began
            model = {**metadata, **result, "path": str(path.relative_to(out))}
            # Persist rejected fits before the run fails; no candidate is dropped.
            if not model["accepted"]:
                failed_arrays = path.with_name(path.stem+"-failed-parameters.npz")
                save_npz(failed_arrays, {"theta": c.theta(model), "gradient": np.asarray(model["gradient"]),
                                         "objective": np.array(model["objective"])})
                model = nullable_failure(model)
                model["failure_parameters_path"] = str(failed_arrays.relative_to(out))
                model["failure_reason"] = "optimizer failure, nonfinite output, or gradient above frozen tolerance"
            c.write_json(path, model)
            fits.append(model)
            c.require(model["accepted"], f"rejected required fit {model['fit_id']}")
            return model, path
        except Exception as error:
            if not path.exists():
                failed = {**metadata, "accepted": False, "exception": repr(error), "path": str(path.relative_to(out))}
                c.write_json(path, failed)
                fits.append(failed)
            with (root / "fits.jsonl").open("wb") as f:
                for record in fits: f.write(c.json_bytes(record))
            raise

    for fold in protocol["target_and_phases"]["outer_folds"]:
        year = fold["year"]
        fold_root = root / str(year)
        train = c.phase_labels(source, keys["valid"], c.timestamp(fold["inner_train_start"]), c.timestamp(fold["inner_train_end_exclusive"]))
        validation = c.phase_labels(source, keys["valid"], c.timestamp(fold["validation_start"]), c.timestamp(fold["validation_end_exclusive"]))
        refit = c.phase_labels(source, keys["valid"], c.timestamp(fold["refit_start"]), c.timestamp(fold["refit_end_exclusive"]))
        selected_inner, selected_outer, choices = {}, {}, {}
        for family in protocol["features"]["families"]:
            candidates = []
            for n in protocol["features"]["histories"]:
                parent = None
                X_train = feature_cache[n, family][train["binary_mask"][indices]].astype(np.float64)
                X_validation = feature_cache[n, family][validation["binary_mask"][indices]].astype(np.float64)
                for penalty in protocol["estimation"]["lambda_grid_descending"]:
                    model, path = fit_one(fold, family, n, penalty, train, "inner", parent, X_train)
                    p, z = c.predict(X_validation, model)
                    model["validation_scores"] = c.scores(validation["direction"][validation["binary_mask"]], p, z,
                        int(np.sum(validation["classification_valid"] & (validation["direction"] == 0))))
                    model["validation_mask_sha256"] = c.array_sha(validation["binary_mask"], np.uint8)
                    c.write_json(path, model)
                    candidates.append(model)
                    candidate_rows.append({"minutes": minutes, "outer_year": year, "family": family, "n": n,
                        "lambda": penalty, "fit_id": model["fit_id"], "accepted": model["accepted"], **model["validation_scores"]})
                    parent = model
                del X_train, X_validation
            best, minimum = c.select_candidate(candidates)
            fitted, _ = fit_one(fold, family, best["n"], best["lambda"], refit, "refit")
            selected_inner[family], selected_outer[family] = best, fitted
            choice = {"minutes": minutes, "outer_year": year, "family": family, "n": best["n"], "lambda": best["lambda"],
                      "validation_minimum_loss": minimum, "validation_selected_loss": best["validation_scores"]["binary_log_loss"],
                      "inner_fit_id": best["fit_id"], "refit_fit_id": fitted["fit_id"],
                      "inner_model_path": best["path"], "refit_model_path": fitted["path"]}
            choices[family] = choice
            selections.append(choice)
            c.write_json(fold_root / family / "selected.json", choice)
        fold_result = {"year": year, "selected": choices}
        for phase in ("validation", "outer"):
            start, end = c.timestamp(fold[f"{phase}_start"]), c.timestamp(fold[f"{phase}_end_exclusive"])
            arrays = c.phase_labels(source, keys["valid"], start, end)
            models, fitting_labels = (selected_inner, train) if phase == "validation" else (selected_outer, refit)
            prediction_mask = arrays["phase_mask"] & keys["valid"]
            selected_key_rows = prediction_mask[indices]
            for family, model in models.items():
                p, z = c.predict(feature_cache[model["n"], family][selected_key_rows].astype(np.float64), model)
                arrays[f"p_{family}"] = np.full(source["rows"], np.nan)
                arrays[f"logit_{family}"] = np.full(source["rows"], np.nan)
                arrays[f"p_{family}"][prediction_mask], arrays[f"logit_{family}"][prediction_mask] = p, z
            baselines = c.baseline_fit(signs, fitting_labels["direction"], fitting_labels["binary_mask"])
            arrays["p_unconditional"], arrays["p_lag1"] = c.baseline_predict(baselines, signs, prediction_mask)
            path = fold_root / f"{phase}.npz"
            save_npz(path, arrays)
            phase_scores = metrics_for(arrays)
            sidecar = {"schema": "filang-information-predictions-v1", "minutes": minutes, "outer_year": year,
                       "phase": phase, "phase_start": start, "phase_end_exclusive": end,
                       "source_sha256": source["sha256"], "protocol_sha256": options["protocol_sha256"],
                       "native_keys_sha256": keys["keys_sha256"], "models": {k: {"fit_id": m["fit_id"],
                           "coefficient_sha256": m["coefficient_sha256"], "path": m["path"], "file_sha256": c.digest(out / m["path"])} for k, m in models.items()},
                       "baseline_fit": baselines, "baseline_fit_rows_sha256": c.array_sha(np.flatnonzero(fitting_labels["binary_mask"]), "<i8"),
                       "baseline_fit_labels_sha256": c.array_sha(fitting_labels["direction"][fitting_labels["binary_mask"]] == 1, np.uint8),
                       "scores": phase_scores, "npz_sha256": c.digest(path), "npz_bytes": path.stat().st_size,
                       "arrays": {name: {"dtype": a.dtype.str, "shape": list(a.shape), "sha256": c.array_sha(a)} for name, a in arrays.items()}}
            c.write_json(path.with_suffix(".json"), sidecar)
            if phase == "outer":
                daily = c.daily_classification(arrays, start, end)
                daily_folds.append(daily)
                save_npz(fold_root / "classification_daily.npz", daily)
                fold_result["scores"] = phase_scores
                fold_result["gain"] = phase_scores["B"]["binary_log_loss"]-phase_scores["G"]["binary_log_loss"]
                fold_result["economics"] = {}
            economic_began = time.perf_counter()
            for scenario in protocol["economic_diagnostic"]["cost_scenarios_bps_per_side"]:
                name = scenario["name"]
                if phase == "outer": fold_result["economics"][name] = {}
                for policy in ("B", "G", "unconditional", "lag1", "cash", "buy_hold"):
                    probability = arrays[f"p_{policy}"] if policy not in ("cash", "buy_hold") else np.full(source["rows"], np.nan)
                    ledger = economics.run_ledger(source["timestamps"], source["ohlc"][:, 0], probability,
                        start=start, end=end, interval_seconds=source["interval_seconds"], fee_bps=scenario["fee"],
                        slippage_bps=scenario["slippage"], entry_threshold=protocol["economic_diagnostic"]["entry_threshold"],
                        exit_threshold=protocol["economic_diagnostic"]["exit_threshold"],
                        policy=policy if policy in ("cash", "buy_hold") else "threshold")
                    location = fold_root / "economics" / phase / name / policy
                    c.write_json(location / "metrics.json", ledger["metrics"])
                    c.write_json(location / "trades.json", ledger["trades"])
                    c.write_json(location / "gaps.json", ledger["gaps"])
                    save_npz(location / "daily.npz", {k: ledger[k] for k in ("daily_days", "daily_net_log", "daily_gross_log")})
                    save_npz(location / "trace.npz", ledger["trace"])
                    if phase == "outer":
                        fold_result["economics"][name][policy] = ledger["metrics"]
                        ledger_parts[name][policy][year] = ledger
            economics_seconds += time.perf_counter()-economic_began
        fold_results.append(fold_result)
        print(f"completed {minutes}m outer fold {year}", flush=True)
    with (root / "fits.jsonl").open("wb") as f:
        for record in fits: f.write(c.json_bytes(record))
    c.write_json(root / "candidates.json", candidate_rows)
    c.write_json(root / "selected.json", {"schema": "filang-information-selection-v1", "selections": selections})
    inference_began = time.perf_counter()
    settings = protocol["inference"]["bootstrap"]
    bootstraps = {}
    for block in [settings["primary_block_days"], *settings["sensitivity_block_days"]]:
        summary, ordinary, centered = c.bootstrap_gain(daily_folds, minutes, block, settings["replicates"], settings["base_seed"])
        bootstraps[str(block)] = summary
        save_npz(root / f"bootstrap-{block}.npz", {"ordinary": ordinary, "centered": centered})
    years = [f["year"] for f in fold_results]
    aggregates = {label: {name: {policy: aggregate_ledgers(parts, included) for policy, parts in policies.items()}
                         for name, policies in ledger_parts.items()}
                  for label, included in (("all_outer", years), ("continuous_2024_plus", [y for y in years if y >= 2024]))}
    result = {"minutes": minutes, "folds": fold_results, "pooled_scores": aggregate_scores(fold_results),
              "bootstrap": bootstraps, "positive_years": sum(f["gain"] > 0 for f in fold_results), "economics": aggregates}
    c.write_json(root / "summary.json", result)
    receipt = {"minutes": minutes, "source_feature_seconds": source_feature_seconds, "fitting_seconds": fitting_seconds,
               "economics_seconds": economics_seconds, "inference_aggregation_seconds": time.perf_counter()-inference_began,
               "total_seconds": time.perf_counter()-began, "cpu_seconds": time.process_time()-process_cpu,
               "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)*(1 if sys.platform == "darwin" else 1024),
               "inner_fits": sum(f["stage"] == "inner" for f in fits), "refits": sum(f["stage"] == "refit" for f in fits)}
    c.write_json(root / "timings.json", receipt)
    return result, receipt


def runtime_receipt():
    import scipy
    import threadpoolctl
    import importlib.metadata
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer): np.show_config()
    packages = {}
    for name in ("numpy", "scipy", "polars", "threadpoolctl"):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages,
            "numpy_config": buffer.getvalue(), "threadpoolctl": threadpoolctl.threadpool_info(),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_VARIABLES}}


def seal_run(out):
    files = {}
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name not in ("manifest.json", "manifest.sha256"):
            files[str(path.relative_to(out))] = {"bytes": path.stat().st_size, "sha256": c.digest(path),
                                                "schema_or_format": path.suffix.lstrip(".")}
    c.write_json(out / "manifest.json", {"schema": "filang-information-run-manifest-v1", "files": files})
    (out / "manifest.sha256").write_text(c.digest(out / "manifest.json")+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-dir", "keys-dir", "out", "protocol"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--blas-threads", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.workers <= 5 or not 1 <= args.blas_threads <= 64:
        parser.error("workers must be 1..5 and blas-threads 1..64")
    for name in THREAD_VARIABLES: os.environ[name] = str(args.blas_threads)
    numerical()
    began = time.perf_counter()
    repo = Path(__file__).resolve().parents[2]
    protocol_path = protocol_repository_path(args.protocol, repo)
    frozen = subprocess.run(["git", "show", f"{args.freeze_commit}:{protocol_path}"],
                            cwd=repo, check=True, capture_output=True).stdout
    c.require(frozen == args.protocol.read_bytes(), "supplied protocol differs from freeze commit")
    protocol = json.loads(frozen)
    c.require(protocol["schema"] == "filang-geometry-information-protocol-v1", "protocol schema")
    c.require(protocol["features"]["histories"] == [2, 3, 5, 10] and protocol["features"]["families"] == ["B", "G"], "protocol feature families")
    c.require(protocol["estimation"]["lambda_grid_descending"] == [0.1, 0.01, 0.001, 0.0001], "protocol lambda grid")
    c.require(protocol["data"]["timeframes_minutes"] == [15, 30, 60, 120, 240], "protocol timeframe family")
    c.require(not args.out.exists(), "output exists; R1 requires a fresh directory and does not silently reuse fits")
    provenance_path = args.data_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    c.require(provenance["protocol_sha256"] == protocol["predecessor"]["protocol_sha256"], "predecessor provenance identity")
    c.require(len(provenance["sources"]) == 5, "predecessor source coverage")
    args.out.mkdir(parents=True)
    out = args.out.resolve()
    (out / "protocol.json").write_bytes(frozen)
    (out / "provenance.json").write_bytes(provenance_path.read_bytes())
    implementation_files = {str(path.relative_to(repo)): c.digest(path) for path in
                            [Path(__file__).resolve(), Path(__file__).with_name("common.py").resolve(),
                             Path(__file__).with_name("economics.py").resolve()]}
    implementation_sha = c.object_sha(implementation_files)
    implementation_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                                         capture_output=True, text=True).stdout.strip()
    implementation_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True,
                                           capture_output=True, text=True).stdout
    options = {"out": str(out), "data_dir": str(args.data_dir.resolve()), "keys_dir": str(args.keys_dir.resolve()),
               "protocol_sha256": c.digest(out / "protocol.json"), "implementation_sha256": implementation_sha}
    run = {"schema": "filang-information-run-v1", "status": "RUNNING", "command": [sys.executable, *sys.argv],
           "attempt_id": protocol["attempt_id"], "experiment_id": protocol["experiment_id"],
           "freeze_commit": args.freeze_commit, "protocol_repository_path": protocol_path,
           "protocol_sha256": options["protocol_sha256"],
           "source_provenance_sha256": c.digest(provenance_path), "input_paths": options,
           "implementation": {"files": implementation_files, "sha256": implementation_sha,
                              "git_head": implementation_head, "worktree_status_porcelain": implementation_status},
           "runtime": runtime_receipt(), "settings": {"workers": args.workers, "blas_threads": args.blas_threads},
           "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "amendments": [protocol["amendment"]] if "amendment" in protocol else [], "deviations": []}
    c.write_json(out / "run.json", run)
    results, receipts, errors = [], [], []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = {pool.submit(timeframe_job, options, minutes): minutes for minutes in protocol["data"]["timeframes_minutes"]}
        for future in as_completed(futures):
            minutes = futures[future]
            try:
                result, receipt = future.result()
                results.append(result)
                receipts.append(receipt)
            except Exception:
                error = {"minutes": minutes, "traceback": traceback.format_exc()}
                errors.append(error)
                c.write_json(out / f"failure-{minutes}m.json", error)
    if errors:
        run.update(status="FAILED", failures=errors, completed_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        c.write_json(out / "run.json", run)
        seal_run(out)
        raise RuntimeError("required timeframe fit/analysis failed; failures and incomplete fit coverage retained")
    aggregation_began = time.perf_counter()
    results.sort(key=lambda r: r["minutes"])
    receipts.sort(key=lambda r: r["minutes"])
    c.require(sum(r["inner_fits"] for r in receipts) == 640 and sum(r["refits"] for r in receipts) == 40, "required fit coverage")
    adjusted = c.holm({str(r["minutes"]): r["bootstrap"]["7"]["p_one_sided"] for r in results})
    for result in results:
        primary = result["bootstrap"]["7"]
        result["p_holm"] = adjusted[str(result["minutes"])]
        result["conditions"] = {"positive_gain": primary["gain"] > 0, "ci_above_zero": primary["ci95_low"] > 0,
                                "holm_below_005": result["p_holm"] < 0.05, "three_positive_years": result["positive_years"] >= 3}
        result["criterion_met"] = all(result["conditions"].values())
        result["outcome"] = "inconclusive"
        result["outcome_if_verified"] = "supported" if result["criterion_met"] else "not-supported"
    all_features, candidates, selections = [], [], []
    with (out / "fits.jsonl").open("wb") as fit_stream:
        for result in results:
            root = out / f"{result['minutes']}m"
            all_features.append(json.loads((root / "features.json").read_bytes()))
            candidates.extend(json.loads((root / "candidates.json").read_bytes()))
            selections.extend(json.loads((root / "selected.json").read_bytes())["selections"])
            fit_stream.write((root / "fits.jsonl").read_bytes())
    c.write_json(out / "features.json", {"schema": "filang-information-features-v1", "protocol_sha256": options["protocol_sha256"],
        "column_names": {str(n): {f: c.feature_names(n, f) for f in ("B", "G")} for n in (2, 3, 5, 10)}, "timeframes": all_features})
    c.write_json(out / "selected.json", {"schema": "filang-information-selection-v1", "selections": selections})
    with (out / "candidates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(candidates[0]))
        writer.writeheader(); writer.writerows(candidates)
    daily_rows = []
    for result in results:
        for fold in result["folds"]:
            with np.load(out / f"{result['minutes']}m" / str(fold["year"]) / "classification_daily.npz", allow_pickle=False) as daily:
                for i, day in enumerate(daily["day"]):
                    daily_rows.append({"minutes": result["minutes"], "outer_year": fold["year"],
                        "utc_date": dt.datetime.fromtimestamp(int(day)*86400, dt.timezone.utc).date().isoformat(),
                        **{name: daily[name][i].item() for name in daily.files}})
    with (out / "classification_daily.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(daily_rows[0]))
        writer.writeheader(); writer.writerows(daily_rows)
    analysis = {"schema": "filang-information-analysis-v1", "experiment_id": protocol["experiment_id"],
                "protocol_sha256": options["protocol_sha256"], "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "coverage": {"inner_fits": 640, "selected_refits": 40, "timeframes": 5, "outer_folds": 4},
                "audit_required": "Every required independent check must PASS before promoting conditional outcomes.",
                "prior_exposure": protocol["predecessor"]["prior_exposure"], "primary_scope": protocol["primary_scope"], "timeframes": results}
    c.write_json(out / "analysis.json", analysis)
    run.update(status="COMPLETE_PENDING_INDEPENDENT_AUDIT", completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
               stage_timings={"timeframes": receipts, "aggregation_seconds": time.perf_counter()-aggregation_began,
                              "total_seconds_before_final_seal": time.perf_counter()-began})
    c.write_json(out / "run.json", run)
    seal_run(out)
    print(json.dumps({"status": run["status"], "out": str(out), "inner_fits": 640, "selected_refits": 40}))


if __name__ == "__main__":
    main()
