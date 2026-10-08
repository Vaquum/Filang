#!/usr/bin/env python3
"""Execute the frozen R2 payoff experiment in a fresh, sealed output directory.

Compact JSONL records retain all fits and policy trials. Twenty annual NPZ
bundles retain full predictions, cash/share-ledger traces and reusable normal
statistics. No scientific setting is selected from a same-fold outer outcome.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.metadata
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
PROTOCOL_PATH = "experiments/geometry_information/round2_protocol.json"
PROTOCOL_SHA256 = "40162d6e1a6ced930bb8c8cfb578f6d9eb4935b7f2ef4ae37a363dc75e52d11d"
FREEZE_COMMIT = "9489c22556898603268fbad9124e0268f0d99852"
FIT_SCHEMA = "filang-payoff-fit-v1"
SELECTION_SCHEMA = "filang-payoff-selection-v1"
LEDGER_SCHEMA = "filang-payoff-ledger-v1"


def numerical():
    global np, c, r
    import numpy as np
    try:
        from . import common as c
        from . import returns as r
    except ImportError:
        import common as c
        import returns as r


def save_npz(path, arrays):
    path = Path(path)
    for value in arrays.values():
        c.require(np.asarray(value).dtype.kind in "biuf", "only real numeric and boolean arrays permitted")
    pending = path.with_name(path.name + ".pending")
    with pending.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    pending.replace(path)


def nullable_failure(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: nullable_failure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [nullable_failure(item) for item in value]
    return value


def append_record(path, record):
    with Path(path).open("ab") as stream:
        stream.write(c.json_bytes(nullable_failure(record)))
        stream.flush()


def array_info(array):
    array = np.asarray(array)
    return {"dtype": array.dtype.str, "shape": list(array.shape), "sha256": c.array_sha(array)}


def save_bundle(root, year, arrays, registry):
    path = root / f"year{year}.npz"
    save_npz(path, arrays)
    registry[path.name] = {"bytes": path.stat().st_size, "sha256": c.digest(path),
                           "arrays": {name: array_info(value) for name, value in arrays.items()}}
    c.write_json(root / "arrays.json", {"schema": "filang-payoff-arrays-v1", "files": registry})


def aggregate_ledgers(parts, years):
    selected = [parts[year] for year in years]
    metrics = [part["metrics"] for part in selected]
    daily = np.concatenate([part["daily_net_log"] for part in selected])
    net = np.concatenate([part["trace"]["net_log_return"] for part in selected])
    total, gross = float(net.sum()), sum(row["gross_log_return"] for row in metrics)
    cumulative = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = -np.expm1(cumulative - np.maximum.accumulate(cumulative))
    trades = [trade for part in selected for trade in part["trades"]]
    sides = sum(row["one_way_turnover"] for row in metrics)
    seconds = sum(row["seconds_long"] for row in metrics)
    elapsed = sum(int(part["trace"]["timestamp"][-1] - part["trace"]["timestamp"][0]) for part in selected)
    std = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0
    return {"folds": years, "independent_annual_cash_resets": True, "calendar_days": len(daily),
        "net_log_return": total, "net_return": float(np.expm1(total)),
        "gross_log_return": gross, "gross_return": float(np.expm1(gross)),
        "log_cost_drag": sum(row["log_cost_drag"] for row in metrics), "max_drawdown": float(drawdown.max()),
        "annualized_daily_log_sharpe": float(daily.mean() / std * np.sqrt(365.25)) if std else None,
        "annualized_return": float(np.expm1(total * 365.25 / len(daily))), "one_way_turnover": sides,
        "completed_trades": len(trades), "trade_win_rate": float(np.mean([trade["net_return"] > 0 for trade in trades])) if trades else None,
        "mean_trade_net_return": float(np.mean([trade["net_return"] for trade in trades])) if trades else None,
        "seconds_long": seconds, "exposure_fraction": seconds / elapsed,
        "active_days": sum(row["active_days"] for row in metrics), "gap_count": sum(row["gap_count"] for row in metrics),
        "gap_gross_log_return": sum(row["gap_gross_log_return"] for row in metrics),
        "delayed_exposure_changes": sum(row["delayed_exposure_changes"] for row in metrics),
        "break_even_symmetric_cost_bps_per_side": float(-np.expm1(-gross / sides) * 10000) if sides else None}


TRADE_FIELDS = {"entry_row": "<i8", "entry_timestamp": "<i8", "entry_open": "<f8",
    "entry_log_cost": "<f8", "signal_row": "<i8", "signal_close": "<i8", "entry_delay_seconds": "<i8",
    "exit_row": "<i8", "exit_timestamp": "<i8", "exit_open": "<f8", "exit_log_cost": "<f8",
    "gross_log_return": "<f8", "net_log_return": "<f8", "net_return": "<f8",
    "holding_seconds": "<i8", "terminal_liquidation": "?"}
GAP_FIELDS = {"previous_row": "<i8", "row": "<i8", "previous_open": "<i8", "open_timestamp": "<i8",
    "missing_seconds": "<i8", "signal_close": "<i8", "delay_seconds": "<i8", "position_before": "i1",
    "position_after": "i1", "gap_gross_log_return": "<f8", "net_log_return": "<f8"}


def pack_ledger(ledger, prefix, arrays):
    names = {}
    for name in ("daily_days", "daily_net_log", "daily_gross_log"):
        key = f"{prefix}__{name}"
        arrays[key], names[name] = ledger[name], key
    for group, values in (("trace", ledger["trace"]),
                          ("trades", {name: np.array([row[name] for row in ledger["trades"]], dtype=dtype)
                                      for name, dtype in TRADE_FIELDS.items()}),
                          ("gaps", {name: np.array([row[name] for row in ledger["gaps"]], dtype=dtype)
                                    for name, dtype in GAP_FIELDS.items()})):
        names[group] = {}
        for name, value in values.items():
            key = f"{prefix}__{group}__{name}"
            arrays[key], names[group][name] = value, key
    return names


def timeframe_job(options, minutes):
    numerical()
    began, cpu = time.perf_counter(), time.process_time()
    out = Path(options["out"])
    root = out / f"{minutes}m"
    root.mkdir(parents=True)
    for name in ("fits", "statistics", "selections", "ledgers"):
        (root / f"{name}.jsonl").write_bytes(b"")
    protocol = json.loads((out / "protocol.json").read_bytes())
    provenance = json.loads((out / "provenance.json").read_bytes())
    specification = next(item for item in protocol["data"]["sources"] if item["minutes"] == minutes)
    source = c.load_source(options["data_dir"], specification, provenance)
    bounds = [c.timestamp(protocol["data"][key]) for key in ("history_start", "end_exclusive")]
    keys = c.decode_keys(Path(options["keys_dir"]) / f"{minutes}m", source, *bounds)
    indices = keys["indices"]
    feature_cache, feature_info, projections = {}, {}, {}
    for n in protocol["features"]["histories"]:
        feature_info[str(n)] = {}
        for family in protocol["features"]["families"]:
            X = c.features(keys["ranks"], keys["up"], n, family)
            feature_cache[n, family], projections[n, family] = X, r.feature_projection(n, family)
            feature_info[str(n)][family] = {"shape": list(X.shape), "dtype": "uint8", "sha256": c.array_sha(X),
                "columns_sha256": c.object_sha(c.feature_names(n, family)),
                "full_G10_projection": projections[n, family].tolist()}
    features = {"schema": "filang-payoff-features-v1", "minutes": minutes,
        "source_sha256": source["sha256"], "source_rows": source["rows"],
        "native": {"context_sha256": keys["context_sha256"], "manifest_sha256": keys["manifest_sha256"],
                   "keys_sha256": keys["keys_sha256"], "engine_sha256": keys["context"]["engine_sha256"]},
        "record_count": len(indices), "record_indices_sha256": c.array_sha(indices, "<i8"),
        "ranks_sha256": c.array_sha(keys["ranks"], np.uint8), "up_sha256": c.array_sha(keys["up"], np.uint8),
        "features": feature_info}
    c.write_json(root / "features.json", features)
    source_feature_seconds = time.perf_counter() - began
    primary = next(item for item in protocol["economics"]["cost_scenarios_bps_per_side"] if item["name"] == "primary")
    policies = r.policy_grid(primary["fee"], primary["slippage"])
    stats_cache, registry, fits, selections, ledger_records, fold_results, daily_folds = {}, {}, [], [], [], [], []
    ledger_parts = {cost["name"]: {family: {} for family in ("B", "G", "U", "cash", "buy_hold")}
                    for cost in protocol["economics"]["cost_scenarios_bps_per_side"]}
    fitting_seconds = statistics_seconds = economics_seconds = 0.0

    def statistics_for(labels, start, end, year, arrays):
        nonlocal statistics_seconds
        rows = np.flatnonzero(labels["target_valid"])
        y = labels["target_log_return"][rows]
        identity = {"source_sha256": source["sha256"], "native_keys_sha256": keys["keys_sha256"],
            "full_feature_sha256": feature_info["10"]["G"]["sha256"],
            "full_feature_columns_sha256": feature_info["10"]["G"]["columns_sha256"],
            "fit_rows_sha256": c.array_sha(rows, "<i8"), "fit_targets_sha256": c.array_sha(y, "<f8"),
            "fit_count": len(rows), "fit_start": start, "fit_end_exclusive": end,
            "protocol_sha256": options["protocol_sha256"], "implementation_sha256": options["implementation_sha256"]}
        identity["statistics_id"] = c.object_sha(identity)
        sid = identity["statistics_id"]
        hit = sid in stats_cache
        if not hit:
            tic = time.perf_counter()
            X = feature_cache[10, "G"][labels["target_valid"][indices]].astype(np.float64)
            stats = r.build_statistics(X, y)
            statistics_seconds += time.perf_counter() - tic
            prefix = "statistics__" + sid
            member_names = {}
            for name in ("x_mean", "gram_mean", "xy_mean", "y_mean", "y2_mean"):
                member = f"{prefix}__{name}"
                arrays[member] = np.asarray(stats[name], dtype=np.float64)
                member_names[name] = member
            record = {"schema": "filang-payoff-statistics-v1", **identity,
                "first_outer_year": year, "arrays_file": f"{minutes}m/year{year}.npz", "arrays": member_names,
                "array_identities": {name: array_info(arrays[member]) for name, member in member_names.items()},
                "reuse_scope": "within_attempt_exact_sample_only"}
            append_record(root / "statistics.jsonl", record)
            stats_cache[sid] = (stats, record)
        return stats_cache[sid][0], stats_cache[sid][1], hit

    def fit_one(fold, family, n, penalty, labels, stage, statistics, stats_record, cache_hit,
                validation=None, arrays=None):
        nonlocal fitting_seconds
        rows = np.flatnonzero(labels["target_valid"])
        y = labels["target_log_return"][rows]
        X = feature_cache[n, family][labels["target_valid"][indices]].astype(np.float64)
        identity = {"schema": FIT_SCHEMA, "minutes": minutes, "outer_year": fold["year"],
            "family": family, "n": n, "lambda": penalty, "stage": stage,
            "fit_start": stats_record["fit_start"], "fit_end_exclusive": stats_record["fit_end_exclusive"],
            "fit_count": len(rows), "fit_zero_count": int(np.count_nonzero(y == 0)),
            "fit_rows_sha256": c.array_sha(rows, "<i8"), "fit_targets_sha256": c.array_sha(y, "<f8"),
            "source_sha256": source["sha256"], "native_keys_sha256": keys["keys_sha256"],
            "protocol_sha256": options["protocol_sha256"], "implementation_sha256": options["implementation_sha256"],
            "feature_sha256": feature_info[str(n)][family]["sha256"],
            "feature_columns_sha256": feature_info[str(n)][family]["columns_sha256"],
            "statistics_id": stats_record["statistics_id"], "statistics_cache_hit": cache_hit,
            "statistics_projection": projections[n, family].tolist(), "fit_cache_hit": False}
        identity["fit_id"] = c.object_sha(identity)
        model = identity.copy()
        try:
            tic = time.perf_counter()
            model.update(r.fit_ridge(X, y, penalty, statistics, projections[n, family]))
            fitting_seconds += time.perf_counter() - tic
            if not model["accepted"]:
                prefix = "failed_fit__" + model["fit_id"]
                arrays[prefix + "__theta"] = np.array([model["intercept"], *model["coefficients"]])
                arrays[prefix + "__gradient"] = np.asarray(model["gradient"])
                for diagnostic in ("objective", "normal_residual", "max_abs_gradient", "max_abs_normal_residual"):
                    arrays[prefix + "__" + diagnostic] = np.asarray(model[diagnostic], dtype=np.float64)
                model["nonfinite_payload_prefix"] = prefix
                model["failure_reason"] = model["solver"]["message"]
                raise RuntimeError("required ridge fit rejected")
            if validation is not None:
                mask = validation["target_valid"]
                prediction = r.predict(feature_cache[n, family][mask[indices]], model)
                model["validation_scores"] = r.return_scores(validation["target_log_return"][mask], prediction)
                model["validation_mask_sha256"] = c.array_sha(mask, np.uint8)
            return model
        except Exception as error:
            model.setdefault("accepted", False)
            model.setdefault("failure_reason", str(error))
            raise
        finally:
            fits.append(model)
            append_record(root / "fits.jsonl", model)

    def save_ledger(fold, phase, cost, family, policy, model_identity, score, arrays):
        nonlocal economics_seconds
        start, end = [c.timestamp(fold[f"{phase}_{field}"]) for field in ("start", "end_exclusive")]
        tic = time.perf_counter()
        ledger = r.run_score_ledger(source["timestamps"], source["ohlc"][:, 0], score,
            start=start, end=end, interval_seconds=source["interval_seconds"],
            fee_bps=cost["fee"], slippage_bps=cost["slippage"], score_policy=policy)
        economics_seconds += time.perf_counter() - tic
        prefix = f"ledger__{phase}__{cost['name']}__{family}__{policy['id']}"
        identity = {"schema": LEDGER_SCHEMA, "minutes": minutes, "outer_year": fold["year"],
            "phase": phase, "phase_start": start, "phase_end_exclusive": end, "scenario": cost["name"],
            "family": family, "policy": policy, "model": model_identity,
            "source_sha256": source["sha256"], "native_keys_sha256": keys["keys_sha256"],
            "protocol_sha256": options["protocol_sha256"], "implementation_sha256": options["implementation_sha256"]}
        identity["ledger_id"] = c.object_sha(identity)
        record = {**identity, "metrics": ledger["metrics"], "arrays_file": f"{minutes}m/year{fold['year']}.npz",
                  "array_prefix": prefix, "arrays": pack_ledger(ledger, prefix, arrays),
                  "trade_count": len(ledger["trades"]), "gap_count": len(ledger["gaps"])}
        ledger_records.append(record)
        append_record(root / "ledgers.jsonl", record)
        return ledger, record

    for fold in protocol["target_and_phases"]["outer_folds"]:
        year, arrays = fold["year"], {}
        try:
            labels = {}
            for phase in ("inner_train", "validation", "refit", "outer"):
                start, end = [c.timestamp(fold[f"{phase}_{field}"]) for field in ("start", "end_exclusive")]
                labels[phase] = r.phase_targets(source, keys["valid"], start, end)
            stats = {}
            for phase in ("inner_train", "refit"):
                start, end = [c.timestamp(fold[f"{phase}_{field}"]) for field in ("start", "end_exclusive")]
                stats[phase] = statistics_for(labels[phase], start, end, year, arrays)
            inner_models, outer_models, choices = {}, {}, {}
            for family in protocol["features"]["families"]:
                candidates = []
                for n in protocol["features"]["histories"]:
                    for penalty in protocol["estimation"]["lambda_grid_descending"]:
                        candidates.append(fit_one(fold, family, n, penalty, labels["inner_train"], "inner",
                            *stats["inner_train"], validation=labels["validation"], arrays=arrays))
                best, minimum = r.select_model(candidates)
                outer = fit_one(fold, family, best["n"], best["lambda"], labels["refit"], "refit", *stats["refit"], arrays=arrays)
                inner_models[family], outer_models[family] = best, outer
                choices[family] = {"schema": SELECTION_SCHEMA, "minutes": minutes, "outer_year": year,
                    "family": family, "n": best["n"], "lambda": best["lambda"],
                    "validation_minimum_mse": minimum, "validation_selected_mse": best["validation_scores"]["mse"],
                    "inner_fit_id": best["fit_id"], "refit_fit_id": outer["fit_id"],
                    "inner_coefficient_sha256": best["coefficient_sha256"], "refit_coefficient_sha256": outer["coefficient_sha256"]}
            means = {}
            for stage, label_key in (("inner", "inner_train"), ("refit", "refit")):
                lab = labels[label_key]
                rows = np.flatnonzero(lab["target_valid"])
                y = lab["target_log_return"][rows]
                record = {"stage": stage, "mean": float(y.mean()), "fit_count": len(y),
                    "fit_zero_count": int(np.count_nonzero(y == 0)), "fit_rows_sha256": c.array_sha(rows, "<i8"),
                    "fit_targets_sha256": c.array_sha(y, "<f8"), "statistics_id": stats[label_key][1]["statistics_id"]}
                record["fit_id"] = c.object_sha(record)
                means[stage] = record
            choices["U"] = {"schema": SELECTION_SCHEMA, "minutes": minutes, "outer_year": year,
                "family": "U", "n": None, "lambda": None, "inner_mean": means["inner"], "refit_mean": means["refit"],
                "inner_fit_id": means["inner"]["fit_id"], "refit_fit_id": means["refit"]["fit_id"]}
            phases, phase_models, prediction_records = {}, {}, {}
            for phase, models, mean_stage in (("validation", inner_models, "inner"), ("outer", outer_models, "refit")):
                values = labels[phase]
                prediction_mask = values["phase_mask"] & keys["valid"]
                model_refs = {}
                for family in ("B", "G"):
                    model = models[family]
                    values[f"mu_{family}"] = np.full(source["rows"], np.nan)
                    values[f"mu_{family}"][prediction_mask] = r.predict(
                        feature_cache[model["n"], family][prediction_mask[indices]], model)
                    model_refs[family] = {"fit_id": model["fit_id"], "coefficient_sha256": model["coefficient_sha256"]}
                values["mu_U"] = np.full(source["rows"], np.nan)
                values["mu_U"][prediction_mask] = means[mean_stage]["mean"]
                model_refs["U"] = {"fit_id": means[mean_stage]["fit_id"], "mean": means[mean_stage]["mean"]}
                scores = {family: r.return_scores(values["target_log_return"][values["target_valid"]],
                    values[f"mu_{family}"][values["target_valid"]]) for family in ("B", "G", "U")}
                for name, value in values.items():
                    arrays[f"{phase}__{name}"] = value
                prediction_records[phase] = {"phase_start": c.timestamp(fold[f"{phase}_start"]),
                    "phase_end_exclusive": c.timestamp(fold[f"{phase}_end_exclusive"]),
                    "arrays_file": f"{minutes}m/year{year}.npz", "array_prefix": phase,
                    "prediction_count": int(prediction_mask.sum()), "models": model_refs, "scores": scores}
                phases[phase], phase_models[phase] = values, model_refs
            for family in ("B", "G", "U"):
                trials = []
                for policy in policies:
                    _, record = save_ledger(fold, "validation", primary, family, policy,
                        phase_models["validation"][family], phases["validation"][f"mu_{family}"], arrays)
                    trials.append(record)
                best, maximum = r.select_policy(trials)
                choices[family].update(policy=best["policy"], selected_validation_ledger_id=best["ledger_id"],
                    validation_maximum_net_log_return=maximum,
                    validation_selected_net_log_return=best["metrics"]["net_log_return"],
                    policy_trials=[{"policy_id": row["policy"]["id"], "ledger_id": row["ledger_id"],
                                    "net_log_return": row["metrics"]["net_log_return"],
                                    "one_way_turnover": row["metrics"]["one_way_turnover"]} for row in trials])
                selections.append(choices[family])
                append_record(root / "selections.jsonl", choices[family])
            fold_result = {"year": year, "selected": choices, "predictions": prediction_records, "economics": {}}
            for cost in protocol["economics"]["cost_scenarios_bps_per_side"]:
                fold_result["economics"][cost["name"]] = {}
                for family in ("B", "G", "U", "cash", "buy_hold"):
                    if family in choices:
                        policy, model, score = choices[family]["policy"], phase_models["outer"][family], phases["outer"][f"mu_{family}"]
                    else:
                        policy = policies[0] if family == "cash" else {"id": "buy_hold", "kind": "buy_hold"}
                        model, score = None, np.full(source["rows"], np.nan)
                    ledger, _ = save_ledger(fold, "outer", cost, family, policy, model, score, arrays)
                    ledger_parts[cost["name"]][family][year] = ledger
                    fold_result["economics"][cost["name"]][family] = ledger["metrics"]
            primary_G, primary_B = ledger_parts["primary"]["G"][year], ledger_parts["primary"]["B"][year]
            c.require(np.array_equal(primary_G["daily_days"], primary_B["daily_days"]), "paired complete day axes")
            daily_folds.append({"daily_G": primary_G["daily_net_log"], "daily_B": primary_B["daily_net_log"]})
            fold_result["effects"] = {
                "G_minus_B": primary_G["metrics"]["net_log_return"] - primary_B["metrics"]["net_log_return"],
                "G_minus_cash": primary_G["metrics"]["net_log_return"]}
            fold_results.append(fold_result)
            print(f"completed {minutes}m R2 outer fold {year}", flush=True)
        finally:
            save_bundle(root, year, arrays, registry)
    inference_began = time.perf_counter()
    settings = protocol["inference"]["bootstrap"]
    bootstraps, bootstrap_arrays = {}, {}
    for block in (settings["primary_block_days"], *settings["sensitivity_block_days"]):
        summary, ordinary, centered = r.bootstrap_economics(daily_folds, minutes, block,
            settings["replicates"], settings["base_seed"])
        bootstraps[str(block)] = summary
        bootstrap_arrays[f"block{block}__ordinary"] = ordinary
        bootstrap_arrays[f"block{block}__centered"] = centered
    path = root / "bootstrap.npz"
    save_npz(path, bootstrap_arrays)
    registry[path.name] = {"bytes": path.stat().st_size, "sha256": c.digest(path),
                          "arrays": {name: array_info(value) for name, value in bootstrap_arrays.items()}}
    c.write_json(root / "arrays.json", {"schema": "filang-payoff-arrays-v1", "files": registry})
    years = [fold["year"] for fold in fold_results]
    aggregates = {label: {cost: {family: aggregate_ledgers(parts, included) for family, parts in families.items()}
                         for cost, families in ledger_parts.items()}
                  for label, included in (("all_outer", years), ("continuous_2024_plus", [year for year in years if year >= 2024]))}
    result = {"minutes": minutes, "folds": fold_results, "bootstrap": bootstraps, "economics": aggregates,
        "joint_positive_years": sum(all(effect > 0 for effect in fold["effects"].values()) for fold in fold_results),
        "completed_G_trades": aggregates["all_outer"]["primary"]["G"]["completed_trades"]}
    c.write_json(root / "summary.json", result)
    receipt = {"minutes": minutes, "source_feature_seconds": source_feature_seconds, "statistics_seconds": statistics_seconds,
        "fitting_seconds": fitting_seconds, "economics_seconds": economics_seconds,
        "inference_aggregation_seconds": time.perf_counter() - inference_began,
        "total_seconds": time.perf_counter() - began, "cpu_seconds": time.process_time() - cpu,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == "darwin" else 1024),
        "inner_fits": sum(row["stage"] == "inner" for row in fits), "refits": sum(row["stage"] == "refit" for row in fits),
        "statistics_built": len(stats_cache), "policy_choices": len(selections),
        "validation_ledgers": sum(row["phase"] == "validation" for row in ledger_records),
        "outer_ledgers": sum(row["phase"] == "outer" for row in ledger_records), "prediction_phases": 2 * len(fold_results)}
    c.write_json(root / "timings.json", receipt)
    return result, receipt, features


def outcome_conditions(result, adjusted_p):
    comparisons = result["bootstrap"]["7"]["comparisons"]
    return {"both_positive_gain": all(row["mean_daily_net_log_gain"] > 0 for row in comparisons.values()),
            "both_ci_above_zero": all(row["ci95_low"] > 0 for row in comparisons.values()),
            "holm_below_005": adjusted_p < 0.05, "three_same_positive_years": result["joint_positive_years"] >= 3,
            "twenty_G_completed_trades": result["completed_G_trades"] >= 20}


def runtime_receipt():
    import threadpoolctl
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        np.show_config()
    packages = {}
    for name in ("numpy", "scipy", "polars", "threadpoolctl"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages,
            "numpy_config": buffer.getvalue(), "threadpoolctl": threadpoolctl.threadpool_info(),
            "thread_environment": {name: os.environ.get(name) for name in THREAD_VARIABLES}}


def seal_run(out):
    files = {str(path.relative_to(out)): {"bytes": path.stat().st_size, "sha256": c.digest(path),
             "schema_or_format": path.suffix.lstrip(".")} for path in sorted(out.rglob("*"))
             if path.is_file() and path.name not in ("manifest.json", "manifest.sha256")}
    c.write_json(out / "manifest.json", {"schema": "filang-payoff-run-manifest-v1", "files": files})
    (out / "manifest.sha256").write_text(c.digest(out / "manifest.json") + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-dir", "keys-dir", "out", "protocol"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--blas-threads", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 5 or not 1 <= args.blas_threads <= 64:
        parser.error("workers must be 1..5 and blas-threads 1..64")
    for name in THREAD_VARIABLES:
        os.environ[name] = str(args.blas_threads)
    numerical()
    began = time.perf_counter()
    repo = Path(__file__).resolve().parents[2]
    c.require(args.freeze_commit == FREEZE_COMMIT, "unsupported R2 freeze commit")
    c.require(c.digest(args.protocol) == PROTOCOL_SHA256, "unsupported R2 protocol bytes")
    c.require(args.protocol.resolve().relative_to(repo).as_posix() == PROTOCOL_PATH, "unsupported R2 protocol repository path")
    frozen = subprocess.run(["git", "show", f"{args.freeze_commit}:{PROTOCOL_PATH}"], cwd=repo,
                            check=True, capture_output=True).stdout
    c.require(frozen == args.protocol.read_bytes(), "supplied protocol differs from published freeze commit")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "merge-base", "--is-ancestor", args.freeze_commit, head], cwd=repo, check=True, capture_output=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True).stdout
    c.require(status == "", "R2 execution requires a clean committed worktree")
    protocol = json.loads(frozen)
    c.require(protocol["schema"] == "filang-geometry-payoff-protocol-v1" and protocol["attempt_id"] == "R2", "R2 protocol schema/attempt")
    c.require(protocol["features"]["histories"] == [2, 3, 5, 10] and protocol["features"]["families"] == ["B", "G"], "frozen feature family")
    c.require(protocol["estimation"]["lambda_grid_descending"] == [0.1, 0.01, 0.001, 0.0001], "frozen penalty family")
    c.require(protocol["data"]["timeframes_minutes"] == [15, 30, 60, 120, 240], "frozen timeframe family")
    c.require(not args.out.exists(), "output already exists; no fit resume or implicit cross-attempt reuse")
    provenance_path = args.data_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_bytes())
    c.require(provenance["protocol_sha256"] == protocol["predecessor"]["protocol_sha256"], "pinned prepared provenance")
    c.require(len(provenance["sources"]) == 5, "source provenance coverage")
    implementation_files = {}
    for name in ("run_round2.py", "returns.py", "common.py", "economics.py"):
        path = Path(__file__).with_name(name).resolve()
        relative = str(path.relative_to(repo))
        committed = subprocess.run(["git", "show", f"{head}:{relative}"], cwd=repo, check=True, capture_output=True).stdout
        c.require(committed == path.read_bytes(), "implementation differs from retained committed bytes")
        implementation_files[relative] = c.digest(path)
    args.out.mkdir(parents=True)
    out = args.out.resolve()
    (out / "protocol.json").write_bytes(frozen)
    (out / "provenance.json").write_bytes(provenance_path.read_bytes())
    options = {"out": str(out), "data_dir": str(args.data_dir.resolve()), "keys_dir": str(args.keys_dir.resolve()),
        "protocol_sha256": c.digest(out / "protocol.json"), "implementation_sha256": c.object_sha(implementation_files)}
    run = {"schema": "filang-payoff-run-v1", "status": "RUNNING", "command": [sys.executable, *sys.argv],
        "attempt_id": protocol["attempt_id"], "experiment_id": protocol["experiment_id"], "freeze_commit": args.freeze_commit,
        "protocol_repository_path": PROTOCOL_PATH, "protocol_sha256": options["protocol_sha256"],
        "source_provenance_sha256": c.digest(provenance_path), "input_paths": options,
        "implementation": {"files": implementation_files, "sha256": options["implementation_sha256"],
                           "git_head": head, "worktree_status_porcelain": status},
        "runtime": runtime_receipt(), "settings": {"workers": args.workers, "blas_threads": args.blas_threads},
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "amendments": [], "deviations": []}
    c.write_json(out / "run.json", run)
    results, receipts, features, failures = [], [], [], []
    try:
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = {pool.submit(timeframe_job, options, minutes): minutes for minutes in protocol["data"]["timeframes_minutes"]}
            for future in as_completed(futures):
                try:
                    result, receipt, feature = future.result()
                    results.append(result)
                    receipts.append(receipt)
                    features.append(feature)
                except Exception:
                    failure = {"minutes": futures[future], "traceback": traceback.format_exc()}
                    failures.append(failure)
                    c.write_json(out / f"failure-{futures[future]}m.json", failure)
        c.require(not failures, "required timeframe failed; partial retained records remain inconclusive")
        results.sort(key=lambda row: row["minutes"])
        receipts.sort(key=lambda row: row["minutes"])
        features.sort(key=lambda row: row["minutes"])
        expected = {"inner_fits": 640, "refits": 40, "statistics_built": 25, "policy_choices": 60,
                    "validation_ledgers": 420, "outer_ledgers": 400, "prediction_phases": 40}
        coverage = {name: sum(row[name] for row in receipts) for name in expected}
        c.require(coverage == expected, "required complete R2 coverage")
        adjusted = c.holm({str(row["minutes"]): row["bootstrap"]["7"]["intersection_union_p"] for row in results})
        for result in results:
            result["p_holm"] = adjusted[str(result["minutes"])]
            result["conditions"] = outcome_conditions(result, result["p_holm"])
            result["criterion_met"] = all(result["conditions"].values())
            result["outcome"] = "inconclusive"
            result["outcome_if_verified"] = "supported" if result["criterion_met"] else "not-supported"
        c.write_json(out / "features.json", {"schema": "filang-payoff-features-v1", "protocol_sha256": options["protocol_sha256"],
            "column_names": {str(n): {family: c.feature_names(n, family) for family in ("B", "G")} for n in (2, 3, 5, 10)},
            "timeframes": features})
        c.write_json(out / "analysis.json", {"schema": "filang-payoff-analysis-v1", "experiment_id": protocol["experiment_id"],
            "protocol_sha256": options["protocol_sha256"], "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "coverage": coverage, "audit_required": "Every required independent check must PASS before promoting conditional outcomes.",
            "prior_exposure": protocol["round_predecessor"]["prior_exposure"], "primary_scope": protocol["primary_scope"], "timeframes": results})
        run.update(status="COMPLETE_PENDING_INDEPENDENT_AUDIT", completed_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            stage_timings={"timeframes": receipts, "total_seconds_before_final_seal": time.perf_counter() - began})
    except Exception:
        run.update(status="FAILED", failures=failures, parent_failure=traceback.format_exc(),
                   completed_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        raise
    finally:
        c.write_json(out / "run.json", run)
        seal_run(out)
    print(json.dumps({"status": run["status"], "out": str(out), **coverage}))


if __name__ == "__main__":
    main()
