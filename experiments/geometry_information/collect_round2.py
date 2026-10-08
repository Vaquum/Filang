#!/usr/bin/env python3
"""Collect compact, complete R2 evidence only after a full independent audit.

No fitting, policy selection, ledger replay or source-run mutation occurs here.
Larger numerical arrays remain externally retained by their sealed identities.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import shlex
import sys

try:
    from . import collect_round1 as shared
except ImportError:
    import collect_round1 as shared


TIMEFRAMES = (15, 30, 60, 120, 240)
YEARS = (2023, 2024, 2025, 2026)
COMPARISONS = ("G_minus_B", "G_minus_cash")
# Only exact published protocol/freeze pairs can be collected.
SUPPORTED_PROTOCOLS = {
    "40162d6e1a6ced930bb8c8cfb578f6d9eb4935b7f2ef4ae37a363dc75e52d11d": {
        "freeze_commit": "9489c22556898603268fbad9124e0268f0d99852", "attempt_id": "R2", "experiment_id": "btc-geometry-payoff-r2",
        "protocol_filename": "round2_protocol.json", "report_name": "20261008-geometry-payoff-r2",
    },
}
COVERAGE = {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40,
            "policy_choices": 60, "validation_ledgers": 420, "outer_ledgers": 400,
            "ledger_replays": 820, "prediction_phases": 40, "all_records": True, "sampled": False}
PRODUCER_COVERAGE = {"inner_fits": 640, "refits": 40, "statistics_built": 25,
                     "policy_choices": 60, "validation_ledgers": 420, "outer_ledgers": 400, "prediction_phases": 40}
SCENARIOS = ("zero", "reduced", "primary", "stress")
FAMILIES = ("B", "G", "U", "cash", "buy_hold")
POLICIES = ("cash", "e0_xm05", "e0_x0", "e05_xm05", "e05_x0", "e1_xm05", "e1_x0")
CONDITIONS = ("both_positive_gain", "both_ci_above_zero", "holm_below_005", "three_same_positive_years", "twenty_G_completed_trades")
CHECKS = {
    "raw_source_provenance", "all_native_keys", "all_feature_columns_and_projections",
    "all_targets_zeros_masks_boundaries", "all_statistics_samples_values_and_cache_identities",
    "all_fit_rows_targets_direct_objectives_gradients", "all_candidate_mse_and_model_choices",
    "all_unconditional_inner_and_refit_means", "all_full_row_causal_predictions",
    "all_validation_trials_and_policy_choices", "all_signed_score_cash_share_ledgers",
    "all_daily_trade_gap_trace_and_aggregate_metrics", "all_shared_bootstrap_replicas",
    "composite_holm_joint_year_and_activity_criteria", "all_binary_array_members",
    "all_retained_artifact_identities", "no_model_fitting_by_verifier"}


def require(condition, message):
    shared.require(condition, message)


def admitted_protocol(run, identity):
    checksum = shared.digest(run / "protocol.json")
    require(checksum in SUPPORTED_PROTOCOLS, "R2 protocol hash is not explicitly admitted")
    profile = {**SUPPORTED_PROTOCOLS[checksum], "protocol_sha256": checksum}
    freeze = profile["freeze_commit"]
    require(isinstance(freeze, str) and len(freeze) == 40 and all(c in "0123456789abcdef" for c in freeze),
            "R2 protocol freeze is unpublished; drafts cannot be collected")
    protocol = shared.load_json(run / "protocol.json")
    require(identity["freeze_commit"] == freeze and identity["protocol_sha256"] == checksum,
            "R2 run protocol/freeze binding differs")
    require(protocol["attempt_id"] == profile["attempt_id"] and protocol["experiment_id"] == profile["experiment_id"],
            "R2 protocol identity differs")
    require(identity["amendments"] == [] and identity["deviations"] == [], "R2 has an undeclared amendment or deviation")
    return profile, protocol


def checked_manifest(run):
    manifest_path = run / "manifest.json"
    require(shared.digest(manifest_path) == (run / "manifest.sha256").read_text().strip(), "R2 producer seal differs")
    manifest = shared.load_json(manifest_path)
    require(manifest["schema"] == "filang-payoff-run-manifest-v1", "R2 manifest schema differs")
    files = manifest["files"]
    required = {"protocol.json", "provenance.json", "run.json", "analysis.json", "features.json"}
    for minutes in TIMEFRAMES:
        required.update(f"{minutes}m/{name}" for name in
                        ("features.json", "fits.jsonl", "statistics.jsonl", "selections.jsonl", "ledgers.jsonl",
                         "arrays.json", "summary.json", "timings.json", "bootstrap.npz"))
        required.update(f"{minutes}m/year{year}.npz" for year in YEARS)
    require(required == set(files), "R2 producer manifest lacks required artifacts or contains unexpected artifacts")
    sources = {}
    for relative, record in sorted(files.items()):
        require(relative not in ("manifest.json", "manifest.sha256", "verification.json"), "invalid self/audit manifest entry")
        source = shared.bounded(run, relative)
        require(source.is_file() and shared.file_record(source) == {"bytes": record["bytes"], "sha256": record["sha256"]},
                "R2 producer artifact checksum differs: " + relative)
        sources[relative] = source
    actual = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()}
    allowed = {"manifest.json", "manifest.sha256"} | ({"verification.json"} if (run / "verification.json").is_file() else set())
    require(actual == set(files) | allowed,
            "unsealed file inside R2 producer run; external receipts must remain outside")
    return manifest, sources


def check_audit(run, audit, profile):
    require(audit["schema"] == "filang-geometry-payoff-verification-v1" and audit["stage"] == "full" and
            audit["status"] == "PASS", "complete independent R2 scientific audit required")
    require(audit["protocol_sha256"] == profile["protocol_sha256"] and audit["freeze_commit"] == profile["freeze_commit"],
            "R2 audit protocol/freeze differs")
    require(audit["producer_manifest_sha256"] == shared.digest(run / "manifest.json") and
            audit["analysis_sha256"] == shared.digest(run / "analysis.json"), "R2 audit is stale or bound to another run")
    require(audit["audited_timeframes"] == list(TIMEFRAMES) and audit["audited_outer_years"] == list(YEARS),
            "R2 independent timeframe/year coverage differs")
    require(all(type(audit["coverage"].get(k)) is type(v) and audit["coverage"][k] == v for k, v in COVERAGE.items()),
            "R2 full audit coverage is incomplete or sampled")
    require(set(audit["checks"]) == CHECKS and all(v is True for v in audit["checks"].values()), "R2 required independent check failed or missing")
    require(audit["no_model_fitting_by_verifier"] is True and audit["all_array_members_checked"] is True and
            audit["scientific_models_checked"] is True and type(audit["audited_array_members"]) is int and
            audit["audited_array_members"] > 0, "R2 complete independent numerical audit assertions required")
    require(math.isfinite(audit["max_independent_fit_gradient"]) and 0 <= audit["max_independent_fit_gradient"] <= 1e-10,
            "R2 independent direct-gradient acceptance failed")
    require(math.isfinite(audit["max_numeric_error"]) and audit["max_numeric_error"] >= 0, "R2 finite audit error required")


def jsonl(path):
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("non-finite JSONL"))))
    return rows


def criterion(frame):
    primary = frame["bootstrap"]["7"]["comparisons"]
    same_years = sum(all(fold["effects"][name] > 0 for name in COMPARISONS) for fold in frame["folds"])
    trades = frame["economics"]["all_outer"]["primary"]["G"]["completed_trades"]
    return {"both_positive_gain": all(primary[n]["mean_daily_net_log_gain"] > 0 for n in COMPARISONS),
            "both_ci_above_zero": all(primary[n]["ci95_low"] > 0 for n in COMPARISONS),
            "holm_below_005": frame["p_holm"] < .05,
            "three_same_positive_years": same_years >= 3, "twenty_G_completed_trades": trades >= 20}, same_years, trades


def check_analysis(analysis, profile):
    require(analysis["schema"] == "filang-payoff-analysis-v1" and analysis["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT" and
            analysis["protocol_sha256"] == profile["protocol_sha256"], "R2 analysis incomplete or protocol differs")
    require(analysis["coverage"] == PRODUCER_COVERAGE, "R2 producer coverage differs")
    frames = sorted(analysis["timeframes"], key=lambda x: x["minutes"])
    require([f["minutes"] for f in frames] == list(TIMEFRAMES), "R2 analysis timeframe coverage differs")
    for frame in frames:
        require(sorted(f["year"] for f in frame["folds"]) == list(YEARS), "R2 analysis annual coverage differs")
        require(set(frame["bootstrap"]) == {"1", "7", "28"}, "R2 bootstrap block coverage differs")
        for block, bs in frame["bootstrap"].items():
            require(set(bs["comparisons"]) == set(COMPARISONS), "R2 comparison family differs")
            require(bs["block_days"] == int(block) and bs["replicates"] == 2000 and
                    bs["seed"] == 20261008 + 1000 * frame["minutes"] + int(block), "R2 bootstrap settings differ")
            require(all(0 <= v["p_one_sided"] <= 1 and v["ci95_low"] <= v["ci95_high"]
                        for v in bs["comparisons"].values()), "R2 inference ranges differ")
            require(bs["intersection_union_p"] == max(v["p_one_sided"] for v in bs["comparisons"].values()),
                    "R2 composite p must be the maximum component p")
        conditions, same_years, trades = criterion(frame)
        require(frame["joint_positive_years"] == same_years and frame["completed_G_trades"] == trades,
                "R2 annual/activity summaries differ")
        expected = "supported" if all(conditions.values()) else "not-supported"
        require(frame["conditions"] == conditions and frame["criterion_met"] == all(conditions.values()),
                "R2 recorded success conditions differ")
        require(frame["outcome"] == "inconclusive" and frame["outcome_if_verified"] == expected,
                "R2 producer promoted unaudited results or conditional outcome differs")
    previous = 0.0
    for rank, frame in enumerate(sorted(frames, key=lambda x: (x["bootstrap"]["7"]["intersection_union_p"], x["minutes"]))):
        previous = min(1.0, max(previous, (len(frames) - rank) * frame["bootstrap"]["7"]["intersection_union_p"]))
        require(abs(previous - frame["p_holm"]) <= 1e-15, "R2 composite Holm adjustment differs")
    return frames


def check_bootstrap_audit(audit, frames):
    """Bind all continuous/discrete audit cases without equating oracle p's."""
    method = audit.get("bootstrap_audit_method", {})
    require(type(method.get("uniform_cases")) is int and method["uniform_cases"] == 30 and
            "predicate_epsilon" in method and method["predicate_epsilon"] is None and
            method.get("producer_or_protocol_changed") is False and
            method.get("alternate_oracle_p_agreement_claimed") is False,
            "R2 requires the uniform two-stage bootstrap audit with no predicate epsilon or changed producer/protocol")
    require(all(isinstance(method.get(name), str) and method[name] for name in ("continuous_replay", "discrete_tail", "diagnostics")),
            "R2 bootstrap audit method explanation is incomplete")
    rows = audit.get("bootstrap_tail_diagnostics", [])
    expected = {(m, b, name) for m in TIMEFRAMES for b in (1, 7, 28) for name in COMPARISONS}
    require(len(rows) == 30 and {(r["minutes"], r["block_days"], r["comparison"]) for r in rows} == expected,
            "R2 bootstrap diagnostic census must cover all thirty cases exactly once")
    frames_by_minutes = {frame["minutes"]: frame for frame in frames}
    error_fields = ("ordinary_max_abs_oracle_error", "centered_max_abs_oracle_error", "observed_abs_oracle_error",
                    "ordinary_max_abs_retained_arithmetic_error", "centered_max_abs_retained_arithmetic_error")
    for row in rows:
        bs = frames_by_minutes[row["minutes"]]["bootstrap"][str(row["block_days"])]
        comparison = bs["comparisons"][row["comparison"]]
        replicas = row["replicates"]
        require(type(replicas) is int and replicas == bs["replicates"] == 2000, "R2 bootstrap diagnostic replica count differs")
        for field in ("independent_oracle_tail_count", "retained_tail_count", "predicate_disagreement_count", "literal_equal_margin_count"):
            require(type(row[field]) is int and 0 <= row[field] <= replicas, "R2 invalid bootstrap diagnostic tail count")
        require(row["retained_p_one_sided"] == (1 + row["retained_tail_count"]) / (replicas + 1) == comparison["p_one_sided"],
                "R2 retained literal tail p/count differs from analysis")
        require(row["independent_oracle_p_one_sided"] == (1 + row["independent_oracle_tail_count"]) / (replicas + 1),
                "R2 diagnostic oracle p/count differs")
        difference = abs(row["retained_tail_count"] - row["independent_oracle_tail_count"])
        require(difference <= row["predicate_disagreement_count"] and
                (row["predicate_disagreement_count"] - difference) % 2 == 0,
                "R2 bootstrap predicate disagreement count is inconsistent")
        require(all(math.isfinite(row[name]) for name in ("retained_input_observed", "independent_oracle_observed")) and
                math.isclose(row["retained_input_observed"], comparison["mean_daily_net_log_gain"], rel_tol=1e-10, abs_tol=1e-10),
                "R2 diagnostic observed effect differs from analysis")
        require(all(math.isfinite(row[name]) and row[name] >= 0 for name in error_fields) and
                row["observed_abs_oracle_error"] == abs(row["retained_input_observed"] - row["independent_oracle_observed"]),
                "R2 bootstrap numeric-error diagnostics differ")
        require(math.isfinite(row["minimum_absolute_tail_margin"]) and row["minimum_absolute_tail_margin"] >= 0,
                "R2 invalid minimum tail margin")
        for field, sign in (("nearest_negative_tail_margin", -1), ("nearest_positive_tail_margin", 1)):
            value = row[field]
            require(value is None or (math.isfinite(value) and sign * value > 0), "R2 invalid signed tail margin")
        require(all(type(row[name]) is bool for name in ("retained_arithmetic_ordinary_exact", "retained_arithmetic_centered_exact")),
                "R2 retained arithmetic equality assertions missing")
        nonzero = row["nonzero_daily_effects"]
        require(type(nonzero) is int and 0 <= nonzero <= comparison["calendar_days"], "R2 nonzero daily effect count differs")
        atom_p, histogram = row["single_atom_exact_algebraic_p"], row["single_atom_sample_multiplicity_histogram"]
        if nonzero > 1:
            require(atom_p is None and histogram is None, "R2 single-atom diagnostic has multiple atoms")
        else:
            require(isinstance(histogram, dict) and histogram and all(
                key.isdigit() and str(int(key)) == key and type(value) is int and value > 0
                for key, value in histogram.items()) and sum(histogram.values()) == replicas,
                "R2 single-atom multiplicity histogram is incomplete")
            if nonzero == 0:
                require(histogram == {"0": replicas}, "R2 zero-effect multiplicities differ")
                tail_count = replicas
            else:
                positive = row["retained_input_observed"] > 0
                tail_count = sum(value for key, value in histogram.items() if (int(key) >= 2 if positive else int(key) <= 2))
            require(atom_p == (1 + tail_count) / (replicas + 1), "R2 single-atom diagnostic p/histogram differs")
    return rows


def read_records(run):
    fits, selections, ledgers = [], [], []
    for minutes in TIMEFRAMES:
        root = run / f"{minutes}m"
        f, s, l = jsonl(root / "fits.jsonl"), jsonl(root / "selections.jsonl"), jsonl(root / "ledgers.jsonl")
        require((len(f), len(s), len(l)) == (136, 12, 164), "R2 per-timeframe compact record coverage differs")
        require(all(row["accepted"] is True for row in f), "R2 incomplete or rejected fit cannot support a result")
        fits.extend(f); selections.extend(s); ledgers.extend(l)
    require(len({f["fit_id"] for f in fits}) == 680 and sum(f["stage"] == "inner" for f in fits) == 640 and
            sum(f["stage"] == "refit" for f in fits) == 40, "R2 fitting record identities/stages differ")
    require(len({l["ledger_id"] for l in ledgers}) == 820 and sum(l["phase"] == "validation" for l in ledgers) == 420 and
            sum(l["phase"] == "outer" for l in ledgers) == 400, "R2 ledger coverage/identities differ")
    return fits, selections, ledgers


def check_record_bindings(run, manifest, identity, protocol, frames, features, fits, selections, ledgers):
    """Check compact-record closure; the separate auditor checks their mathematics."""
    feature_map = {f["minutes"]: f for f in features["timeframes"]}
    require(sorted(feature_map) == list(TIMEFRAMES), "R2 feature coverage differs")
    expected_sources = {s["minutes"]: s["prepared_csv_sha256"] for s in protocol["data"]["sources"]}
    require(sum(f["record_count"] for f in feature_map.values()) == COVERAGE["native_keys"], "R2 native record census differs")
    indexed_arrays = {}
    for minutes, feature in feature_map.items():
        require(feature == shared.load_json(run / f"{minutes}m/features.json"), "R2 root/per-timeframe features differ")
        require(feature["source_sha256"] == expected_sources[minutes], "R2 prepared source differs from frozen pin")
        array_index = shared.load_json(run / f"{minutes}m/arrays.json")
        require(array_index["schema"] == "filang-payoff-arrays-v1" and
                set(array_index["files"]) == {"bootstrap.npz", *(f"year{y}.npz" for y in YEARS)},
                "R2 external bundle census differs")
        for name, record in array_index["files"].items():
            relative = f"{minutes}m/{name}"
            require(all(record[k] == manifest["files"][relative][k] for k in ("bytes", "sha256")),
                    "R2 bundle index/manifest identity differs")
            require(record["arrays"] and all(set(v) == {"dtype", "shape", "sha256"} for v in record["arrays"].values()),
                    "R2 complete numeric member index required")
            indexed_arrays[relative] = record
        statistics = jsonl(run / f"{minutes}m/statistics.jsonl")
        require(len(statistics) == 5 and len({s["statistics_id"] for s in statistics}) == 5,
                "R2 unique sample statistics coverage differs")
        for row in statistics:
            require(row["protocol_sha256"] == identity["protocol_sha256"] and
                    row["source_sha256"] == feature["source_sha256"], "R2 statistics source/protocol differs")
            members = indexed_arrays[row["arrays_file"]]["arrays"]
            require(all(members.get(member) == row["array_identities"][name] for name, member in row["arrays"].items()),
                    "R2 statistics member identity differs")
    expected_npz = set(indexed_arrays)
    require({p for p in manifest["files"] if p.endswith(".npz")} == expected_npz,
            "R2 unindexed or missing retained numerical bundle")
    fit_map = {f["fit_id"]: f for f in fits}
    ledger_map = {l["ledger_id"]: l for l in ledgers}
    selection_map = {(s["minutes"], s["outer_year"], s["family"]): s for s in selections}
    require(set(selection_map) == {(m, y, f) for m in TIMEFRAMES for y in YEARS for f in ("B", "G", "U")},
            "R2 complete unique selection grid required")
    for row in [*fits, *ledgers]:
        feature = feature_map[row["minutes"]]
        require(row["outer_year"] in YEARS and row["protocol_sha256"] == identity["protocol_sha256"] and
                row["implementation_sha256"] == identity["implementation"]["sha256"] and
                row["source_sha256"] == feature["source_sha256"] and
                row["native_keys_sha256"] == feature["native"]["keys_sha256"], "R2 record identity binding differs")
    for minutes in TIMEFRAMES:
        for year in YEARS:
            subset = [f for f in fits if f["minutes"] == minutes and f["outer_year"] == year]
            require({(f["family"], f["n"], f["lambda"]) for f in subset if f["stage"] == "inner"} ==
                    {(family, n, p) for family in ("B", "G") for n in (2, 3, 5, 10) for p in (.1, .01, .001, .0001)},
                    "R2 complete candidate grid required")
            require(sorted(f["family"] for f in subset if f["stage"] == "refit") == ["B", "G"],
                    "R2 selected refits required even when policy selects cash")
            subset_ledgers = [l for l in ledgers if l["minutes"] == minutes and l["outer_year"] == year]
            require({(l["phase"], l["scenario"], l["family"], l["policy"]["id"]) for l in subset_ledgers if l["phase"] == "validation"} ==
                    {("validation", "primary", family, p) for family in ("B", "G", "U") for p in POLICIES},
                    "R2 all seven validation policy trials required")
            require({(l["scenario"], l["family"]) for l in subset_ledgers if l["phase"] == "outer"} ==
                    {(cost, family) for cost in SCENARIOS for family in FAMILIES}, "R2 outer cost/control grid differs")
    for row in ledgers:
        members = indexed_arrays[row["arrays_file"]]["arrays"]
        require(row["arrays_file"] == f"{row['minutes']}m/year{row['outer_year']}.npz", "R2 ledger bundle binding differs")
        referenced = []
        for value in row["arrays"].values():
            referenced.extend(value.values() if isinstance(value, dict) else [value])
        require(referenced and all(name in members for name in referenced), "R2 ledger refers to absent numerical members")
    for choice in selections:
        require(choice["policy"]["id"] in POLICIES and len(choice["policy_trials"]) == 7 and
                {r["policy_id"] for r in choice["policy_trials"]} == set(POLICIES), "R2 policy choice/trials differ")
        for trial in choice["policy_trials"]:
            ledger = ledger_map[trial["ledger_id"]]
            require((ledger["minutes"], ledger["outer_year"], ledger["family"], ledger["phase"]) ==
                    (choice["minutes"], choice["outer_year"], choice["family"], "validation") and
                    ledger["policy"]["id"] == trial["policy_id"] and
                    ledger["metrics"]["net_log_return"] == trial["net_log_return"] and
                    ledger["metrics"]["one_way_turnover"] == trial["one_way_turnover"], "R2 validation trial reference differs")
        best = ledger_map[choice["selected_validation_ledger_id"]]
        require(best["policy"] == choice["policy"] and
                best["metrics"]["net_log_return"] == choice["validation_selected_net_log_return"], "R2 chosen policy ledger differs")
        for stage in ("inner", "refit"):
            model = choice[stage + "_mean"] if choice["family"] == "U" else fit_map[choice[stage + "_fit_id"]]
            require(model["fit_id"] == choice[stage + "_fit_id"] and model["stage"] == stage,
                    "R2 selected model stage/identity differs")
            if choice["family"] != "U":
                require((model["minutes"], model["outer_year"], model["family"], model["n"], model["lambda"]) ==
                        (choice["minutes"], choice["outer_year"], choice["family"], choice["n"], choice["lambda"]),
                        "R2 selected model hyperparameters differ")
    for frame in frames:
        for fold in frame["folds"]:
            for family in ("B", "G", "U"):
                require(fold["selected"][family] == selection_map[frame["minutes"], fold["year"], family],
                        "R2 analysis selection differs from retained record")
            require(set(fold["predictions"]) == {"validation", "outer"}, "R2 prediction phase coverage differs")
            for phase, record in fold["predictions"].items():
                require(record["arrays_file"] == f"{frame['minutes']}m/year{fold['year']}.npz" and
                        record["array_prefix"] == phase, "R2 prediction bundle identity differs")
                members = indexed_arrays[record["arrays_file"]]["arrays"]
                required = ("row_index", "timestamp", "entry_row", "exit_row", "causal_feature_valid", "phase_mask", "target_valid",
                            "direction", "target_log_return", "target_simple_return", "mu_B", "mu_G", "mu_U")
                require(all(phase + "__" + n in members for n in required), "R2 full-row prediction member omitted")
            for cost in SCENARIOS:
                for family in FAMILIES:
                    found = [r for r in ledgers if (r["minutes"], r["outer_year"], r["phase"], r["scenario"], r["family"]) ==
                             (frame["minutes"], fold["year"], "outer", cost, family)]
                    require(len(found) == 1 and found[0]["metrics"] == fold["economics"][cost][family],
                            "R2 analysis annual metrics differ from retained ledger")
    return indexed_arrays


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return stream.getvalue().encode()


def report_tables(frames):
    primary, annual, choices, economics, prediction_scores = [], [], [], [], []
    for frame in frames:
        minutes = frame["minutes"]
        for block, bs in frame["bootstrap"].items():
            for comparison, values in bs["comparisons"].items():
                primary.append({"minutes": minutes, "block_days": int(block), "comparison": comparison, **values,
                                "intersection_union_p": bs["intersection_union_p"],
                                "primary_p_holm": frame["p_holm"], "primary_outcome": frame["outcome_if_verified"],
                                **frame["conditions"], "same_positive_years": frame["joint_positive_years"],
                                "completed_G_trades": frame["completed_G_trades"]})
        for fold in frame["folds"]:
            annual.append({"minutes": minutes, "year": fold["year"], **fold["effects"]})
            for family, choice in fold["selected"].items():
                choices.append({"minutes": minutes, "year": fold["year"], "family": family,
                    "n": choice["n"], "lambda": choice["lambda"], "policy": choice["policy"]["id"],
                    "inner_fit_id": choice["inner_fit_id"], "refit_fit_id": choice["refit_fit_id"],
                    "validation_model_mse": choice.get("validation_selected_mse"),
                    "validation_policy_net_log": choice["validation_selected_net_log_return"]})
            for phase, record in fold["predictions"].items():
                for family, score in record["scores"].items():
                    prediction_scores.append({"minutes": minutes, "year": fold["year"], "phase": phase,
                                              "family": family, **score})
        scopes = {str(fold["year"]): fold["economics"] for fold in frame["folds"]}
        scopes.update(frame["economics"])
        for scope, costs in scopes.items():
            for cost, families in costs.items():
                for family, metrics in families.items():
                    economics.append({"minutes": minutes, "scope": scope, "cost": cost, "family": family,
                        **{key: metrics.get(key) for key in (
                            "net_return", "net_log_return", "gross_return", "gross_log_return", "log_cost_drag",
                            "max_drawdown", "annualized_daily_log_sharpe", "annualized_return", "one_way_turnover",
                            "completed_trades", "trade_win_rate", "mean_trade_net_return", "seconds_long", "exposure_fraction",
                            "active_days", "gap_count", "gap_gross_log_return", "delayed_exposure_changes",
                            "break_even_symmetric_cost_bps_per_side")}})
    return {"primary-and-sensitivity.csv": csv_bytes(primary), "annual-effects.csv": csv_bytes(annual),
            "model-policy-choices.csv": csv_bytes(choices), "economics.csv": csv_bytes(economics),
            "prediction-scores.csv": csv_bytes(prediction_scores)}


def bootstrap_audit_section(audit, retained, frames):
    differing = sorted((row for row in audit["bootstrap_tail_diagnostics"]
        if row["predicate_disagreement_count"] or row["independent_oracle_p_one_sided"] != row["retained_p_one_sided"]),
        key=lambda row: (row["minutes"], row["block_days"], row["comparison"]))
    rows = []
    for row in differing:
        atom = ("—" if row["single_atom_exact_algebraic_p"] is None else
                shared.number(row["single_atom_exact_algebraic_p"], 9) + f" ({row['nonzero_daily_effects']} nonzero days)")
        rows.append([row["minutes"], row["block_days"], row["comparison"],
            shared.number(row["independent_oracle_p_one_sided"], 9), shared.number(row["retained_p_one_sided"], 9),
            f"{row['predicate_disagreement_count']} / {row['literal_equal_margin_count']}",
            f"{row['minimum_absolute_tail_margin']:.6e} / {row['centered_max_abs_oracle_error']:.6e}", atom])
    cases = shared.table(["Minutes", "Block days", "Comparison", "Raw-account oracle p (diagnostic)",
        "Retained literal p", "Predicate disagreements / exact margins", "Min absolute margin / max centered error", "Algebraic atom p (diagnostic)"], rows) if rows else (
        "No case has differing literal tail decisions between the two arithmetic replays in this receipt.")
    archived = sorted(name for name in retained["external_operational_receipts"] if name.startswith("operational/audit/"))
    archive = ("The preserved audit-development attachments are archived byte-for-byte in this package: " +
               ", ".join(f"[{Path(name).name}]({name})" for name in archived) + ".") if archived else (
        "No audit-development attachments were supplied to this collection. The preserved first failed audit source, tests, log and receipt must accompany publication; pass them as external `--audit-receipt` files.")
    activity = ("All five timeframes independently fail the minimum-twenty-completed-G-trades condition. Changing which diagnostic p-value is displayed cannot make the frozen joint criterion pass.") if all(
        not frame["conditions"]["twenty_G_completed_trades"] for frame in frames) else (
        "The minimum-twenty-completed-G-trades condition remains a separate mandatory gate; no diagnostic p-value substitutes for it.")
    return f"""## Bootstrap arithmetic audit

The first audit attempt stopped at a bootstrap tail-count discrepancy. That failed audit is preserved as audit-development history; it is not erased or treated as another market-model attempt. {archive}

The final audit uses the same two-stage method for **all thirty cases** (five timeframes × three block lengths × two contrasts). First, it independently reconstructs raw cash/share daily effects and checks every ordinary and centered bootstrap replica with the unchanged absolute-plus-relative numerical tolerance of `1e-10`. Second, it reconstructs the committed two-column reduction from the already-audited retained daily values, then applies the frozen **literal `>=`** predicate to the sealed centered float64 replicas. The retained integer tail count must give exactly the p-value in `analysis.json` through `(1 + count) / 2001`.

Numerically close continuous replicas need not give identical discrete tail decisions at an equality boundary. There is **no generic claim of raw-account oracle p-value agreement**. No predicate epsilon was introduced, no existing numeric tolerance was changed, and no producer, protocol, observations, bootstrap draws or model/policy selections were changed. The following table includes only cases with differing tail decisions or p-values; all thirty diagnostics, observed effects, signed nearest margins and retained-arithmetic errors are in [verification.json](verification.json).

{cases}

Here the margin is `retained_centered_replica − retained_observed_effect`; exact margins count literal zero differences. The error column is the largest absolute difference between independently replayed and retained centered replicas. With one nonzero daily effect `a`, the extra algebraic diagnostic counts `m*a >= 2*a` using the sampled multiplicity `m`; with no nonzero days its algebraic tail probability is one. These diagnostic p-values expose the equality mass and arithmetic sensitivity. They are **not replacement or corrected mathematical p-values** for the frozen retained-array result, and they are never used for promotion. {activity}
"""


def render_readme(run, profile, protocol, identity, audit, frames, retained, launcher):
    number, pct, table = shared.number, shared.percentage, shared.table
    supported = [f["minutes"] for f in frames if f["criterion_met"]]
    supported_text = ", ".join(f"{m}m" for m in supported) if supported else "none"
    outcome_text = (f"The frozen R2 criterion is **supported for {supported_text}** after a complete independent audit. "
                    "Every other timeframe is **not-supported** for this declared model and policy family." if supported else
                    "The frozen R2 economic criterion is **not-supported at all five timeframes** after a complete independent audit.")
    primary_rows, gate_rows, annual_rows, control_rows, separated_rows, sensitivity_rows = [], [], [], [], [], []
    cash_choices = 0
    for frame in frames:
        minutes = frame["minutes"]
        comparisons = frame["bootstrap"]["7"]["comparisons"]
        primary_rows.append([minutes,
            *[number(comparisons[k]["mean_daily_net_log_gain"], 8) + " [" +
              number(comparisons[k]["ci95_low"], 8) + ", " + number(comparisons[k]["ci95_high"], 8) + "]" for k in COMPARISONS],
            *[number(comparisons[k]["p_one_sided"], 6) for k in COMPARISONS],
            number(frame["p_holm"], 6), frame["outcome_if_verified"]])
        gate_rows.append([minutes, *["yes" if frame["conditions"][name] else "no" for name in CONDITIONS],
                          frame["joint_positive_years"], frame["completed_G_trades"]])
        for fold in frame["folds"]:
            choices = fold["selected"]
            def choice_text(family):
                row = choices[family]
                model = "mean" if family == "U" else f"n={row['n']}, λ={row['lambda']:g}"
                return model + "; " + row["policy"]["id"]
            annual_rows.append([minutes, fold["year"], number(fold["effects"]["G_minus_B"]),
                number(fold["effects"]["G_minus_cash"]), *[choice_text(family) for family in ("B", "G", "U")]])
            cash_choices += choices["G"]["policy"]["id"] == "cash"
        for family in FAMILIES:
            metrics = frame["economics"]["all_outer"]["primary"][family]
            control_rows.append([minutes, family, pct(metrics["net_return"]), number(metrics["net_log_return"]),
                pct(metrics["gross_return"]), pct(metrics["max_drawdown"]), pct(metrics["exposure_fraction"]),
                metrics["one_way_turnover"], metrics["completed_trades"],
                number(metrics["break_even_symmetric_cost_bps_per_side"], 3)])
        first = next(f for f in frame["folds"] if f["year"] == 2023)
        for family in ("G", "B", "U", "buy_hold"):
            early = first["economics"]["primary"][family]
            later = frame["economics"]["continuous_2024_plus"]["primary"][family]
            separated_rows.append([minutes, family, pct(early["net_return"]), early["gap_count"],
                number(early["gap_gross_log_return"]), early["delayed_exposure_changes"], pct(later["net_return"])])
        for cost in SCENARIOS:
            metrics = frame["economics"]["all_outer"][cost]
            sensitivity_rows.append([minutes, cost, *[pct(metrics[f]["net_return"]) for f in FAMILIES]])
    amount_positive = sum(f["economics"]["all_outer"]["primary"]["G"]["net_log_return"] > 0 for f in frames)
    total_external = sum(x["bytes"] for x in retained["external_numerical_bundles"].values())
    path = f"experiments/geometry_information/{profile['protocol_filename']}"
    recorded = shlex.join(identity["command"])
    data = shlex.quote(identity["input_paths"]["data_dir"])
    keys = shlex.quote(identity["input_paths"]["keys_dir"])
    run_arg = shlex.quote(str(run))
    python = shlex.quote(identity["command"][0])
    audit_cmd = (f"{python} experiments/geometry_information/verify_round2.py --stage full "
                 f"--run {run_arg} --keys-root {keys} --data-dir {data} --protocol {path} "
                 f"--out {run_arg}/verification.json")
    elapsed = "No external launcher was supplied."
    if launcher is not None:
        launch = shared.load_json(launcher)
        elapsed = f"The external launcher records exit 0 and {number(launch['elapsed_seconds'], 6)} seconds."
    package_count = len(retained["copied_producer_artifacts"]) + 20 + 2 + 1 + 1 + 1 + 5 + len(retained["external_operational_receipts"]) + 2
    arithmetic_audit = bootstrap_audit_section(audit, retained, frames)
    return f"""# R2: qualitative geometry and cost-aware conditional payoffs

{outcome_text} This is retrospective evidence under the specified OHLC execution proxy; it does not establish a live trading edge or superiority to passive Bitcoin ownership.

This report joins the unchanged producer [analysis](analysis.json) to the later [full independent audit](verification.json). The producer remains `COMPLETE_PENDING_INDEPENDENT_AUDIT`, with conditional outcomes, by design. The collector does not fit models, select policies, replay accounts or overwrite the source run. All five timeframes, including cash selections and unfavorable results, are retained.

## Frozen claim and method

R2 asks whether additive bar geometry beyond sign history provides both a positive net payoff and an incremental payoff over the sign-history baseline after declared transaction costs. B uses body and close-return direction indicators. G adds current-to-prior endpoint comparisons and wick presence. Both use the same native ten-bar causal geometry keys; n∈{{2,3,5,10}} selects a projection of those keys. U predicts the fitting-sample mean log return. No volume, absolute price or numeric return magnitude enters B or G as a feature.

The target is `log(O[t+2]/O[t+1])`, including exact zero returns. The forecast horizon runs from the next opening to the following opening. A policy uses candle t only after its close and executes its requested exposure at the next observed opening; stateful policies may remain long across multiple forecast horizons. Model scoring requires contiguous n10 history and two subsequent bars, candle t opening in its phase, and the exit opening strictly before the phase cutoff. Causal forecasts also cover valid final and pre-gap feature rows lacking future labels; future label availability never suppresses a trading request.

The four outer periods are 2023, 2024, 2025 and 2026 through October 7. Each has the previous calendar year for inner validation and earlier history starting January 2020 for inner training. For B and G independently, validation MSE selects n and λ∈{{0.1,0.01,0.001,0.0001}} for an unscaled ridge regression with an unpenalized intercept. The selected model is then refit on all data strictly before the outer year. Positive penalties make the centered normal equations well-defined; every fit must pass the frozen direct-gradient acceptance check.

Each selected inner B/G/U model evaluates seven validation policies at primary costs: cash, or entry multiples {{0,0.5,1}} crossed with exit multiples {{−0.5,0}} of the primary round-trip log-cost hurdle. A cash account enters when score ≥ entry; a long account stays long when score ≥ exit. Otherwise it requests cash. NaN requests cash. When exit < entry, a score equal to exit preserves the current position; scores at or above entry request long. There is no sigmoid and these are signed return forecasts, not probabilities. Policy selection uses validation total net log return, with the frozen cash/turnover/threshold/id tie order. All selected refits are retained even when cash wins.

Primary fees and slippage are **10+2 bps per side**. Zero (0+0), reduced (5+1), and stress (20+4) scenarios reuse the same primary-selected model, thresholds and position requests. These are declared scenarios, not a claim about an account's actual fees. Buy-and-hold and cash use the same administrative annual reset and terminal liquidation rules. All accounting retains observed gaps, applies pending requests at the next observed opening, and never exits in anticipation of a future gap.

## Primary paired results

Effects are **mean daily net-log-return differences**, with all calendar days including inactive days and equal daily weight. Brackets show each comparison's individual seven-day circular moving-block-bootstrap 95% interval. These two intervals are **not** a joint simultaneous 95% confidence region. The composite one-sided p is the larger of the two component p-values; Holm correction applies to those five timeframe composites. Summary results for all three block lengths are preserved in [primary-and-sensitivity.csv](primary-and-sensitivity.csv). All 2,000 ordinary and centered replicas per setting remain in the indexed external bootstrap bundles.

{table(['Minutes', 'G−B/day [95% CI]', 'G−cash/day [95% CI]', 'p G−B', 'p G−cash', 'Composite p Holm', 'Audited outcome'], primary_rows)}

Every success condition must hold. The annual condition requires the **same** three or more outer years to have both positive effects; twenty completed G round trips is an activity requirement, not an effective sample size or proof of independent trades.

{table(['Minutes', 'Both gains >0', 'Both CI lower >0', 'Holm <.05', 'Same ≥3 years', '≥20 G trades', 'Same positive years', 'G trades'], gate_rows)}

{arithmetic_audit}

## Annual effects and frozen choices

Annual effects below are total net log returns at primary costs. Policy ids encode entry/exit multiples (`xm05` means −0.5); full numeric thresholds and every losing or cash validation trial remain in each timeframe's `selections.jsonl` and `ledgers.jsonl`. [model-policy-choices.csv](model-policy-choices.csv) provides all sixty choices; [prediction-scores.csv](prediction-scores.csv) includes validation and outer B/G/U MSE, true zero counts and the remaining recorded score summaries.

{table(['Minutes', 'Outer year', 'G−B log', 'G−cash log', 'B model; policy', 'G model; policy', 'U; policy'], annual_rows)}

## Primary-cost account outcomes and controls

All-outer figures compound the separately reset annual accounts. Turnover counts one-way changes of full account exposure; completed trades include prescribed terminal liquidations. Break-even is the symmetric per-side cost implied by the realized gross path and turnover, and is undefined when there is no turnover. It is not a predicted executable allowance. Drawdown and all return/risk metrics are descriptive.

{table(['Minutes', 'Family', 'Net return', 'Net log', 'Gross return', 'Max drawdown', 'Exposure', 'One-way turnover', 'Trades', 'Break-even bps/side'], control_rows)}

The 2023 source gap is reported separately. The 2024+ column concatenates independently reset 2024, 2025 and partial-2026 accounts; it does not carry positions across annual boundaries. Gap mark and delayed-exposure counts expose the next-observed-open fill assumption.

{table(['Minutes', 'Family', '2023 net return', '2023 gaps', 'Gap gross log', 'Delayed changes', '2024+ net return'], separated_rows)}

## Cost sensitivity without re-selection

{table(['Minutes', 'Scenario', 'B net return', 'G net return', 'U net return', 'Cash net return', 'Buy-hold net return'], sensitivity_rows)}

[economics.csv](economics.csv) retains every annual and aggregate cost/control result, including gross and net returns, cost drag, exposure, turnover, drawdown, trade counts, gaps, and annualized descriptive metrics. The 1- and 28-day block checks do not add another route to success or alter the primary criterion.

## Evidence, execution and reproduction

The exact [protocol](protocol.json) was published at freeze commit `{profile['freeze_commit']}` with SHA-256 `{profile['protocol_sha256']}`. The five immutable source snapshots and prepared CSV identities are in [provenance.json](provenance.json) and the protocol: 459,503 source rows, January 2020 through October 7, 2026. The common native export contains 458,972 causal ten-bar keys. The source and feature hashes, all runtime/package/thread settings, and implementation identity are retained in [run.json](run.json), [features.json](features.json), and the native preparation receipts.

The [full audit](verification.json) covers 640 candidate fits, 40 refits, 60 policy choices, all 40 prediction phases, 420 validation ledgers and 400 outer ledgers. Its largest recorded numeric comparison error is `{audit['max_numeric_error']}`. All coefficient, objective, direct-gradient, validation-MSE and model/threshold choice records remain in five `fits.jsonl`/`selections.jsonl` groups. No optimizer is run by the collector. The audit independently reconstructs targets, forecasts and signed-score cash/share accounting and verifies the complete array census.

{elapsed} These are operational receipts, not a matched performance benchmark or a compute-ceiling claim. External launcher and audit logs, if supplied, live under `operational/` in this report and remain outside the sealed producer run.

The [producer manifest](producer-manifest.json) and its seal preserve the original artifact identities. The separate [report manifest](manifest.json) seals this compact package. [retained-artifacts.json](retained-artifacts.json) records all externally retained large files: twenty annual numeric bundles and five bootstrap bundles ({total_external:,} bytes), plus native key payloads. Each timeframe's `arrays.json` retains every member's dtype, shape and digest. These bundles are required for a full replay; their omission from Git is a packaging choice, not reduced audit scope. The package contains {package_count} files including its own manifest and seal.

Use the completed PR26 tree containing the final verifier and exactly the producer file hashes in `run.json`. Later edits to producer computational files will fail identity checks when replaying this original run. Install `requirements-information.txt` with the recorded Python/package environment. Reuse the sealed native keys at the recorded key directory; preparing keys again is unnecessary. The original producer invocation, retained verbatim as arguments, was:

```sh
{recorded}
```

Re-execution requires a **new unused `--out` directory**, the frozen protocol/freeze pair above, identical pinned inputs and the recorded implementation. The producer refuses to resume or overwrite a completed attempt. To audit the original retained run and collect it:

```sh
{python} -m pip install -r requirements-information.txt
{audit_cmd}
{python} experiments/geometry_information/collect_round2.py --run {run_arg} --out benchmarks/reports/{profile['report_name']}
```

Supply optional `--launcher /path/to/external-launch.json` and repeatable `--audit-receipt /path/to/external-audit.log` to archive operational evidence. Those files must stay outside the sealed run. A report destination already containing different evidence is rejected.

## Empirical residue and limits

At primary costs, G has a positive all-outer net log return in {amount_positive} of five timeframes; its inner selector chooses cash in {cash_choices} of twenty timeframe/year cases. The complete joint criterion is supported in {len(supported)} of five timeframes. These counts describe this audited attempt and do not authorize selecting an outer winner after inspection or changing thresholds to improve the result.

R2 follows the [exact-pattern predecessor](../20261008-bitcoin-direction/README.md), the retained [R1 numerical failure](../20261008-geometry-information-r1-failed/README.md), and the [R1a information experiment](../20261008-geometry-information-r1a/README.md). All historical observations and prior outcomes were exposed before R2. Nesting controls which rows enter each fit and selector; it does not make those historical observations fresh. An earlier outer year may enter a later fold's fitting history under the explicit frozen schedule. Bootstrap uncertainty is conditional on the declared procedure and does not erase adaptive campaign history.

This finite additive/current-to-prior geometry projection and seven-policy family cannot exhaust all geometric functions. A not-supported result is not proof that geometry contains zero information; a supported result is not a live-edge guarantee. Execution uses OHLC openings with prescribed fees, slippage and delayed gap fills; there are no quotes, order-book depth, latency, market impact, financing, custody, taxes or real orders. Buy-and-hold is a descriptive control rather than a primary superiority test. The remaining campaign budget permits only a separately justified, frozen limited-interaction round, followed by stopping if the declared evidence does not support an edge. Any eventual tradeability claim needs separately frozen future data and execution evidence.

Bibliography: [declared fee-scenario reference](https://www.binance.com/en/fee/trading); [backtest-overfitting research](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). These links provide context and do not substitute for the frozen protocol or measured artifacts.
"""


def collect(run, out, keys_dir=None, launcher=None, audit_receipts=(), verification=None):
    run, out = Path(run).resolve(), Path(out).resolve()
    require(run != out and run not in out.parents and out not in run.parents, "report and sealed run must be separate directories")
    manifest, sources = checked_manifest(run)
    identity = shared.load_json(run / "run.json")
    require(identity["schema"] == "filang-payoff-run-v1" and identity["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "complete R2 producer execution required")
    profile, protocol = admitted_protocol(run, identity)
    require(identity["source_provenance_sha256"] == shared.digest(run / "provenance.json"), "R2 provenance identity differs")
    audit_path = (Path(verification) if verification is not None else run / "verification.json").resolve()
    audit = shared.load_json(audit_path)
    check_audit(run, audit, profile)
    analysis = shared.load_json(run / "analysis.json")
    frames = check_analysis(analysis, profile)
    check_bootstrap_audit(audit, frames)
    features = shared.load_json(run / "features.json")
    fits, choices, ledgers = read_records(run)
    arrays = check_record_bindings(run, manifest, identity, protocol, frames, features, fits, choices, ledgers)
    require(audit["audited_array_members"] == sum(len(record["arrays"]) for record in arrays.values()),
            "R2 audit and retained array-member census differ")
    copies = {name: path for name, path in sources.items() if not name.endswith(".npz")}
    require(all(path.suffix in (".json", ".jsonl") for path in copies.values()), "unexpected R2 compact artifact format")
    copies.update({"producer-manifest.json": run / "manifest.json", "producer-manifest.sha256": run / "manifest.sha256",
                   "verification.json": audit_path})
    native_copies, retained_keys = shared.native_receipts(identity, features, keys_dir)
    operational_copies, operational = shared.operational_receipts(run, identity, launcher, audit_receipts)
    copies.update(native_copies)
    copies.update(operational_copies)
    retained = {"schema": "filang-payoff-report-retained-artifacts-v1", "source_run": str(run),
        "protocol_sha256": profile["protocol_sha256"], "freeze_commit": profile["freeze_commit"],
        "producer_manifest_sha256": shared.digest(run / "manifest.json"), "analysis_sha256": shared.digest(run / "analysis.json"),
        "verification_sha256": shared.digest(audit_path), "audit_admission": "full PASS only",
        "copied_producer_artifacts": {name: manifest["files"][name] for name in sources if not name.endswith(".npz")},
        "external_numerical_bundles": {name: {"bytes": record["bytes"], "sha256": record["sha256"],
            "source_path": str(sources[name]), "array_index": name.split('/')[0] + "/arrays.json",
            "array_members": len(record["arrays"])} for name, record in arrays.items()},
        "external_native_keys": retained_keys, "external_operational_receipts": operational,
        "collector_sha256": shared.digest(Path(__file__)), "copied_artifacts_byte_preserved": True,
        "producer_status_preserved": identity["status"], "outcomes_after_full_audit":
            {str(frame["minutes"]): frame["outcome_if_verified"] for frame in frames}}
    generated = report_tables(frames)
    generated["retained-artifacts.json"] = shared.json_bytes(retained)
    generated["README.md"] = render_readme(run, profile, protocol, identity, audit, frames, retained, launcher).encode()
    require(len(copies) + len(generated) + 2 < 100, "R2 compact report exceeds frozen target of fewer than 100 files")
    return shared.write_package(out, copies, generated, profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keys-dir", type=Path)
    parser.add_argument("--verification", type=Path, help="full audit receipt; default RUN/verification.json")
    parser.add_argument("--launcher", type=Path, help="external successful launcher receipt")
    parser.add_argument("--audit-receipt", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    result = collect(args.run, args.out, args.keys_dir, args.launcher, args.audit_receipt, args.verification)
    print(json.dumps({"status": "COLLECTED_FULL_AUDIT_PASS", "out": str(args.out.resolve()), "files": len(result["files"]) + 2}))


if __name__ == "__main__":
    main()
