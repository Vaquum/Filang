#!/usr/bin/env python3
"""Collect compact, complete R3 evidence only after a full independent audit.

No fitting, policy selection, ledger replay or source-run mutation occurs here.
Larger numerical arrays remain externally retained by their sealed identities.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shlex
import sys

import numpy as np

try:
    from . import collect_round1 as shared
except ImportError:
    import collect_round1 as shared


TIMEFRAMES = (15, 30, 60, 120, 240)
YEARS = (2023, 2024, 2025, 2026)
COMPARISONS = ("I_minus_A", "I_minus_cash")
# Only this exact published protocol/freeze pair is admitted.
SUPPORTED_PROTOCOLS = {
    "486fd2b2f1bfa0e4e2ce19b77485386cef833c8b6341d5eca2403556dcdf67a7": {
        "freeze_commit": "bcc49b113c59f2a2c72524605d26b2dedca98353",
        "attempt_id": "R3", "experiment_id": "btc-geometry-interaction-payoff-r3",
        "protocol_filename": "round3_protocol.json", "report_name": "20261008-geometry-interactions-r3",
    },
}
CATALOGUE_SHA256 = "dca090d73c32419bc525b71101f6cf0b584b1c8b91cf79808d4ed2f5d710bcdb"
TAIL_METHOD = "exact_binary64_rational_weighted_sum_ge_twice_original_sum"
COVERAGE = {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40,
            "policy_choices": 60, "validation_ledgers": 420, "outer_ledgers": 400,
            "ledger_replays": 820, "prediction_phases": 40, "all_records": True, "sampled": False}
PRODUCER_COVERAGE = {"inner_fits": 640, "refits": 40, "statistics_built": 25,
                     "policy_choices": 60, "validation_ledgers": 420, "outer_ledgers": 400, "prediction_phases": 40}
SCENARIOS = ("zero", "reduced", "primary", "stress")
FAMILIES = ("A", "I", "U", "cash", "buy_hold")
POLICIES = ("cash", "e0_xm05", "e0_x0", "e05_xm05", "e05_x0", "e1_xm05", "e1_x0")
CONDITIONS = ("both_positive_gain", "both_ci_above_zero", "holm_below_005", "three_same_positive_years", "twenty_I_completed_trades")
CHECKS = {
    "raw_source_provenance", "all_native_keys", "all_feature_columns_and_projections",
    "all_targets_zeros_masks_boundaries", "all_statistics_samples_values_and_cache_identities",
    "all_fit_rows_targets_direct_objectives_gradients", "all_candidate_mse_and_model_choices",
    "all_unconditional_inner_and_refit_means", "all_full_row_causal_predictions",
    "all_validation_trials_and_policy_choices", "all_signed_score_cash_share_ledgers",
    "all_daily_trade_gap_trace_and_aggregate_metrics", "all_shared_bootstrap_replicas",
    "composite_holm_joint_year_and_activity_criteria", "all_binary_array_members",
    "all_retained_artifact_identities", "no_model_fitting_by_verifier",
    "all_catalogue_states_and_columns", "all_exact_integer_metadata_and_tail_events"}


def require(condition, message):
    shared.require(condition, message)


def admitted_protocol(run, identity):
    checksum = shared.digest(run / "protocol.json")
    require(checksum in SUPPORTED_PROTOCOLS, "R3 protocol hash is not explicitly admitted")
    profile = {**SUPPORTED_PROTOCOLS[checksum], "protocol_sha256": checksum}
    freeze = profile["freeze_commit"]
    require(isinstance(freeze, str) and len(freeze) == 40 and all(c in "0123456789abcdef" for c in freeze),
            "R3 protocol freeze is unpublished; drafts cannot be collected")
    protocol = shared.load_json(run / "protocol.json")
    require(identity["freeze_commit"] == freeze and identity["protocol_sha256"] == checksum,
            "R3 run protocol/freeze binding differs")
    require(protocol["attempt_id"] == profile["attempt_id"] and protocol["experiment_id"] == profile["experiment_id"],
            "R3 protocol identity differs")
    require(identity["amendments"] == [] and identity["deviations"] == [], "R3 has an undeclared amendment or deviation")
    return profile, protocol


def checked_manifest(run):
    manifest_path = run / "manifest.json"
    require(shared.digest(manifest_path) == (run / "manifest.sha256").read_text().strip(), "R3 producer seal differs")
    manifest = shared.load_json(manifest_path)
    require(manifest["schema"] == "filang-interaction-payoff-run-manifest-v1", "R3 manifest schema differs")
    files = manifest["files"]
    required = {"protocol.json", "provenance.json", "run.json", "analysis.json", "features.json", "catalogue.json"}
    for minutes in TIMEFRAMES:
        required.update(f"{minutes}m/{name}" for name in
                        ("features.json", "fits.jsonl", "statistics.jsonl", "selections.jsonl", "ledgers.jsonl",
                         "arrays.json", "summary.json", "timings.json", "bootstrap-exact.json", "bootstrap.npz"))
        required.update(f"{minutes}m/year{year}.npz" for year in YEARS)
    require(required == set(files), "R3 producer manifest lacks required artifacts or contains unexpected artifacts")
    sources = {}
    for relative, record in sorted(files.items()):
        require(relative not in ("manifest.json", "manifest.sha256", "verification.json"), "invalid self/audit manifest entry")
        source = shared.bounded(run, relative)
        require(source.is_file() and shared.file_record(source) == {"bytes": record["bytes"], "sha256": record["sha256"]},
                "R3 producer artifact checksum differs: " + relative)
        sources[relative] = source
    actual = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()}
    allowed = {"manifest.json", "manifest.sha256"} | ({"verification.json"} if (run / "verification.json").is_file() else set())
    require(actual == set(files) | allowed,
            "unsealed file inside R3 producer run; external receipts must remain outside")
    return manifest, sources


def check_audit(run, audit, profile):
    require(audit["schema"] == "filang-geometry-interaction-payoff-verification-v1" and audit["stage"] == "full" and
            audit["status"] == "PASS", "complete independent R3 scientific audit required")
    require(audit["protocol_sha256"] == profile["protocol_sha256"] and audit["freeze_commit"] == profile["freeze_commit"],
            "R3 audit protocol/freeze differs")
    require(audit["producer_manifest_sha256"] == shared.digest(run / "manifest.json") and
            audit["analysis_sha256"] == shared.digest(run / "analysis.json"), "R3 audit is stale or bound to another run")
    require(audit["audited_timeframes"] == list(TIMEFRAMES) and audit["audited_outer_years"] == list(YEARS),
            "R3 independent timeframe/year coverage differs")
    require(all(type(audit["coverage"].get(k)) is type(v) and audit["coverage"][k] == v for k, v in COVERAGE.items()),
            "R3 full audit coverage is incomplete or sampled")
    require(set(audit["checks"]) == CHECKS and all(v is True for v in audit["checks"].values()), "R3 required independent check failed or missing")
    require(audit["no_model_fitting_by_verifier"] is True and audit["all_array_members_checked"] is True and
            audit["scientific_models_checked"] is True and type(audit["audited_array_members"]) is int and
            audit["audited_array_members"] > 0, "R3 complete independent numerical audit assertions required")
    require(math.isfinite(audit["max_independent_fit_gradient"]) and 0 <= audit["max_independent_fit_gradient"] <= 1e-10,
            "R3 independent direct-gradient acceptance failed")
    require(math.isfinite(audit["max_numeric_error"]) and audit["max_numeric_error"] >= 0, "R3 finite audit error required")
    require(audit["catalogue_sha256"] == CATALOGUE_SHA256 and audit["catalogue"] == {
        "oriented_two_bar_states": 7452, "body_entries": 75, "range_entries": 150, "all_columns_reachable": True},
        "R3 complete independently reconstructed fixed catalogue required")
    require(audit["all_exact_metadata_and_tail_events_checked"] is True and
            type(audit["exact_bootstrap_metadata_checked"]) is int and audit["exact_bootstrap_metadata_checked"] == 5 and
            type(audit["exact_tail_event_count"]) is int and audit["exact_tail_event_count"] == 60000 and
            audit["tail_method"] == TAIL_METHOD, "R3 complete exact metadata/tail event audit required")


def jsonl(path):
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("non-finite JSONL"))))
    return rows


def criterion(frame):
    primary = frame["bootstrap"]["7"]["comparisons"]
    same_years = sum(all(fold["effects"][name] > 0 for name in COMPARISONS) for fold in frame["folds"])
    trades = frame["economics"]["all_outer"]["primary"]["I"]["completed_trades"]
    return {"both_positive_gain": all(primary[n]["mean_daily_net_log_gain"] > 0 for n in COMPARISONS),
            "both_ci_above_zero": all(primary[n]["ci95_low"] > 0 for n in COMPARISONS),
            "holm_below_005": frame["p_holm"] < .05,
            "three_same_positive_years": same_years >= 3, "twenty_I_completed_trades": trades >= 20}, same_years, trades


def check_analysis(analysis, profile):
    require(analysis["schema"] == "filang-interaction-payoff-analysis-v1" and analysis["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT" and
            analysis["protocol_sha256"] == profile["protocol_sha256"], "R3 analysis incomplete or protocol differs")
    require(analysis["coverage"] == PRODUCER_COVERAGE, "R3 producer coverage differs")
    frames = sorted(analysis["timeframes"], key=lambda x: x["minutes"])
    require([f["minutes"] for f in frames] == list(TIMEFRAMES), "R3 analysis timeframe coverage differs")
    for frame in frames:
        require(sorted(f["year"] for f in frame["folds"]) == list(YEARS), "R3 analysis annual coverage differs")
        require(set(frame["bootstrap"]) == {"1", "7", "28"}, "R3 bootstrap block coverage differs")
        for block, bs in frame["bootstrap"].items():
            require(set(bs["comparisons"]) == set(COMPARISONS), "R3 comparison family differs")
            require(bs["block_days"] == int(block) and bs["replicates"] == 2000 and
                    bs["seed"] == 20261008 + 1000 * frame["minutes"] + int(block), "R3 bootstrap settings differ")
            require(all(0 <= v["p_one_sided"] <= 1 and v["ci95_low"] <= v["ci95_high"]
                        for v in bs["comparisons"].values()), "R3 inference ranges differ")
            require(bs["intersection_union_p"] == max(v["p_one_sided"] for v in bs["comparisons"].values()),
                    "R3 composite p must be the maximum component p")
        conditions, same_years, trades = criterion(frame)
        require(frame["joint_positive_years"] == same_years and frame["completed_I_trades"] == trades,
                "R3 annual/activity summaries differ")
        expected = "supported" if all(conditions.values()) else "not-supported"
        require(frame["conditions"] == conditions and frame["criterion_met"] == all(conditions.values()),
                "R3 recorded success conditions differ")
        require(frame["outcome"] == "inconclusive" and frame["outcome_if_verified"] == expected,
                "R3 producer promoted unaudited results or conditional outcome differs")
    previous = 0.0
    for rank, frame in enumerate(sorted(frames, key=lambda x: (x["bootstrap"]["7"]["intersection_union_p"], x["minutes"]))):
        previous = min(1.0, max(previous, (len(frames) - rank) * frame["bootstrap"]["7"]["intersection_union_p"]))
        require(abs(previous - frame["p_holm"]) <= 1e-15, "R3 composite Holm adjustment differs")
    return frames


def _compact_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _decimal(value):
    require(isinstance(value, str), "R3 integer metadata must use decimal strings")
    result = int(value)
    require(str(result) == value, "R3 noncanonical integer numerator")
    return result


def check_exact_bootstrap(run, audit, frames, arrays):
    """Check compact encodings and exact bool counts; the auditor replays draws."""
    rows = audit["exact_tail_audit"]
    expected = {(m, b, n) for m in TIMEFRAMES for b in (1, 7, 28) for n in COMPARISONS}
    require(len(rows) == 30 and {(r["minutes"], r["block_days"], r["comparison"]) for r in rows} == expected,
            "R3 exact tail receipt must cover every case exactly once")
    row_map = {(r["minutes"], r["block_days"], r["comparison"]): r for r in rows}
    for frame in frames:
        minutes = frame["minutes"]
        metadata = shared.load_json(run / f"{minutes}m/bootstrap-exact.json")
        payload = {k: v for k, v in metadata.items() if k != "encoding_sha256"}
        require(metadata["schema"] == "filang-exact-bootstrap-input-v1" and
                metadata["comparison_order"] == list(COMPARISONS) and
                metadata["tail_event"] == "resampled_numerator_sum >= 2 * pooled_numerator_sum" and
                hashlib.sha256(_compact_json(payload) + b"\n").hexdigest() == metadata["encoding_sha256"],
                "R3 exact input encoding identity differs")
        lengths = metadata["fold_lengths"]
        require(len(lengths) == 4 and all(type(n) is int and n > 0 for n in lengths) and
                sum(lengths) == metadata["calendar_days"] and len(metadata["fold_binary64_sha256"]) == 4,
                "R3 exact input calendar coverage differs")
        require(set(metadata["contrasts"]) == set(COMPARISONS), "R3 integer comparison order/coverage differs")
        for name, contrast in metadata["contrasts"].items():
            numerators = [_decimal(value) for value in contrast["numerators_decimal"]]
            exponent = contrast["denominator_exponent"]
            require(type(exponent) is int and 0 <= exponent <= 1074 and
                    len(numerators) == metadata["calendar_days"] and
                    sum(numerators) == _decimal(contrast["pooled_numerator_decimal"]) and
                    sum(n != 0 for n in numerators) == contrast["nonzero_days"], "R3 exact numerator count/sum differs")
            require(exponent == 0 or any(n % 2 for n in numerators), "R3 common denominator is not minimal")
            encoded = "".join(value + "\n" for value in contrast["numerators_decimal"]).encode("ascii")
            require(hashlib.sha256(encoded).hexdigest() == contrast["numerators_sha256"], "R3 exact numerator vector digest differs")
        path = f"{minutes}m/bootstrap.npz"
        index = arrays[path]["arrays"]
        expected_members = {f"block{block}__{kind}" for block in (1, 7, 28) for kind in ("ordinary", "centered", "exact_hits")}
        require(set(index) == expected_members, "R3 exact bootstrap member census differs")
        with np.load(run / path, allow_pickle=False) as bundle:
            require(set(bundle.files) == expected_members, "R3 retained exact bootstrap payload member census differs")
            for block in (1, 7, 28):
                bs = frame["bootstrap"][str(block)]
                require(bs["tail_method"] == TAIL_METHOD and bs["exact_encoding_sha256"] == metadata["encoding_sha256"],
                        "R3 floating tail substitute or wrong exact encoding")
                for kind in ("ordinary", "centered", "exact_hits"):
                    member = f"block{block}__{kind}"
                    values = bundle[member]
                    checksum = hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()
                    require(values.shape == (2000, 2) and
                            (values.dtype == np.bool_ if kind == "exact_hits" else values.dtype == np.dtype("<f8")) and
                            np.isfinite(values).all(), "R3 exact bootstrap payload dtype/shape differs")
                    require(index[member] == {"dtype": values.dtype.str, "shape": [2000, 2], "sha256": checksum} and
                            bs[kind + "_sha256"] == checksum, "R3 bootstrap member/hash binding differs")
                hits = bundle[f"block{block}__exact_hits"]
                for column, name in enumerate(COMPARISONS):
                    comparison, receipt = bs["comparisons"][name], row_map[minutes, block, name]
                    count = int(np.count_nonzero(hits[:, column]))
                    p = (1 + count) / 2001
                    require(type(comparison["exact_tail_count"]) is int and comparison["exact_tail_count"] == count and
                            comparison["p_one_sided"] == p and comparison["calendar_days"] == metadata["calendar_days"],
                            "R3 exact tail bits/count/p differ from analysis")
                    require(receipt["replicates"] == 2000 and receipt["exact_tail_count"] == count and
                            receipt["p_one_sided"] == p and receipt["encoding_sha256"] == metadata["encoding_sha256"] and
                            receipt["exact_hits_sha256"] == bs["exact_hits_sha256"] and
                            receipt["integer_metadata_match"] is True and receipt["exact_tail_bits_match"] is True,
                            "R3 exact tail audit receipt differs from retained metadata/bits/analysis")


def check_catalogue(run, protocol, identity, features):
    require(shared.digest(run / "catalogue.json") == CATALOGUE_SHA256 == identity["catalogue_sha256"] ==
            protocol["features"]["catalogue"]["catalogue_sha256"] == features["catalogue_sha256"],
            "R3 fixed catalogue identity differs")
    catalogue = shared.load_json(run / "catalogue.json")
    require(catalogue["version"] == "filang-interval-interactions-v1" and len(catalogue["records"]) == 225 and
            (run / "catalogue.json").read_bytes() == _compact_json(catalogue), "R3 canonical catalogue bytes differ")
    for record in features["timeframes"]:
        info = record["interaction_indices"]
        require(record["catalogue_sha256"] == CATALOGUE_SHA256 and info["dtype"] == "<i2" and
                info["shape"] == [record["record_count"], 2] and len(info["sha256"]) == 64,
                "R3 fixed interaction-index binding differs")


def read_records(run):
    fits, selections, ledgers = [], [], []
    for minutes in TIMEFRAMES:
        root = run / f"{minutes}m"
        f, s, l = jsonl(root / "fits.jsonl"), jsonl(root / "selections.jsonl"), jsonl(root / "ledgers.jsonl")
        require((len(f), len(s), len(l)) == (136, 12, 164), "R3 per-timeframe compact record coverage differs")
        require(all(row["accepted"] is True for row in f), "R3 incomplete or rejected fit cannot support a result")
        fits.extend(f); selections.extend(s); ledgers.extend(l)
    require(len({f["fit_id"] for f in fits}) == 680 and sum(f["stage"] == "inner" for f in fits) == 640 and
            sum(f["stage"] == "refit" for f in fits) == 40, "R3 fitting record identities/stages differ")
    require(len({l["ledger_id"] for l in ledgers}) == 820 and sum(l["phase"] == "validation" for l in ledgers) == 420 and
            sum(l["phase"] == "outer" for l in ledgers) == 400, "R3 ledger coverage/identities differ")
    return fits, selections, ledgers


def check_record_bindings(run, manifest, identity, protocol, frames, features, fits, selections, ledgers):
    """Check compact-record closure; the separate auditor checks their mathematics."""
    feature_map = {f["minutes"]: f for f in features["timeframes"]}
    require(sorted(feature_map) == list(TIMEFRAMES), "R3 feature coverage differs")
    expected_sources = {s["minutes"]: s["prepared_csv_sha256"] for s in protocol["data"]["sources"]}
    require(sum(f["record_count"] for f in feature_map.values()) == COVERAGE["native_keys"], "R3 native record census differs")
    indexed_arrays = {}
    for minutes, feature in feature_map.items():
        require(feature == shared.load_json(run / f"{minutes}m/features.json"), "R3 root/per-timeframe features differ")
        require(feature["source_sha256"] == expected_sources[minutes], "R3 prepared source differs from frozen pin")
        array_index = shared.load_json(run / f"{minutes}m/arrays.json")
        require(array_index["schema"] == "filang-interaction-payoff-arrays-v1" and
                set(array_index["files"]) == {"bootstrap.npz", *(f"year{y}.npz" for y in YEARS)},
                "R3 external bundle census differs")
        for name, record in array_index["files"].items():
            relative = f"{minutes}m/{name}"
            require(all(record[k] == manifest["files"][relative][k] for k in ("bytes", "sha256")),
                    "R3 bundle index/manifest identity differs")
            require(record["arrays"] and all(set(v) == {"dtype", "shape", "sha256"} for v in record["arrays"].values()),
                    "R3 complete numeric member index required")
            indexed_arrays[relative] = record
        statistics = jsonl(run / f"{minutes}m/statistics.jsonl")
        require(len(statistics) == 5 and len({s["statistics_id"] for s in statistics}) == 5,
                "R3 unique sample statistics coverage differs")
        for row in statistics:
            require(row["protocol_sha256"] == identity["protocol_sha256"] and
                    row["source_sha256"] == feature["source_sha256"], "R3 statistics source/protocol differs")
            members = indexed_arrays[row["arrays_file"]]["arrays"]
            require(all(members.get(member) == row["array_identities"][name] for name, member in row["arrays"].items()),
                    "R3 statistics member identity differs")
    expected_npz = set(indexed_arrays)
    require({p for p in manifest["files"] if p.endswith(".npz")} == expected_npz,
            "R3 unindexed or missing retained numerical bundle")
    fit_map = {f["fit_id"]: f for f in fits}
    ledger_map = {l["ledger_id"]: l for l in ledgers}
    selection_map = {(s["minutes"], s["outer_year"], s["family"]): s for s in selections}
    require(set(selection_map) == {(m, y, f) for m in TIMEFRAMES for y in YEARS for f in ("A", "I", "U")},
            "R3 complete unique selection grid required")
    for row in [*fits, *ledgers]:
        feature = feature_map[row["minutes"]]
        require(row["outer_year"] in YEARS and row["protocol_sha256"] == identity["protocol_sha256"] and
                row["implementation_sha256"] == identity["implementation"]["sha256"] and
                row["source_sha256"] == feature["source_sha256"] and
                row["native_keys_sha256"] == feature["native"]["keys_sha256"], "R3 record identity binding differs")
    for minutes in TIMEFRAMES:
        for year in YEARS:
            subset = [f for f in fits if f["minutes"] == minutes and f["outer_year"] == year]
            require({(f["family"], f["n"], f["lambda"]) for f in subset if f["stage"] == "inner"} ==
                    {(family, n, p) for family in ("A", "I") for n in (2, 3, 5, 10) for p in (.1, .01, .001, .0001)},
                    "R3 complete candidate grid required")
            require(sorted(f["family"] for f in subset if f["stage"] == "refit") == ["A", "I"],
                    "R3 selected refits required even when policy selects cash")
            subset_ledgers = [l for l in ledgers if l["minutes"] == minutes and l["outer_year"] == year]
            require({(l["phase"], l["scenario"], l["family"], l["policy"]["id"]) for l in subset_ledgers if l["phase"] == "validation"} ==
                    {("validation", "primary", family, p) for family in ("A", "I", "U") for p in POLICIES},
                    "R3 all seven validation policy trials required")
            require({(l["scenario"], l["family"]) for l in subset_ledgers if l["phase"] == "outer"} ==
                    {(cost, family) for cost in SCENARIOS for family in FAMILIES}, "R3 outer cost/control grid differs")
    for row in ledgers:
        members = indexed_arrays[row["arrays_file"]]["arrays"]
        require(row["arrays_file"] == f"{row['minutes']}m/year{row['outer_year']}.npz", "R3 ledger bundle binding differs")
        referenced = []
        for value in row["arrays"].values():
            referenced.extend(value.values() if isinstance(value, dict) else [value])
        require(referenced and all(name in members for name in referenced), "R3 ledger refers to absent numerical members")
    for choice in selections:
        require(choice["policy"]["id"] in POLICIES and len(choice["policy_trials"]) == 7 and
                {r["policy_id"] for r in choice["policy_trials"]} == set(POLICIES), "R3 policy choice/trials differ")
        for trial in choice["policy_trials"]:
            ledger = ledger_map[trial["ledger_id"]]
            require((ledger["minutes"], ledger["outer_year"], ledger["family"], ledger["phase"]) ==
                    (choice["minutes"], choice["outer_year"], choice["family"], "validation") and
                    ledger["policy"]["id"] == trial["policy_id"] and
                    ledger["metrics"]["net_log_return"] == trial["net_log_return"] and
                    ledger["metrics"]["one_way_turnover"] == trial["one_way_turnover"], "R3 validation trial reference differs")
        best = ledger_map[choice["selected_validation_ledger_id"]]
        require(best["policy"] == choice["policy"] and
                best["metrics"]["net_log_return"] == choice["validation_selected_net_log_return"], "R3 chosen policy ledger differs")
        for stage in ("inner", "refit"):
            model = choice[stage + "_mean"] if choice["family"] == "U" else fit_map[choice[stage + "_fit_id"]]
            require(model["fit_id"] == choice[stage + "_fit_id"] and model["stage"] == stage,
                    "R3 selected model stage/identity differs")
            if choice["family"] != "U":
                require((model["minutes"], model["outer_year"], model["family"], model["n"], model["lambda"]) ==
                        (choice["minutes"], choice["outer_year"], choice["family"], choice["n"], choice["lambda"]),
                        "R3 selected model hyperparameters differ")
    for frame in frames:
        for fold in frame["folds"]:
            for family in ("A", "I", "U"):
                require(fold["selected"][family] == selection_map[frame["minutes"], fold["year"], family],
                        "R3 analysis selection differs from retained record")
            require(set(fold["predictions"]) == {"validation", "outer"}, "R3 prediction phase coverage differs")
            for phase, record in fold["predictions"].items():
                require(record["arrays_file"] == f"{frame['minutes']}m/year{fold['year']}.npz" and
                        record["array_prefix"] == phase, "R3 prediction bundle identity differs")
                members = indexed_arrays[record["arrays_file"]]["arrays"]
                required = ("row_index", "timestamp", "entry_row", "exit_row", "causal_feature_valid", "phase_mask", "target_valid",
                            "direction", "target_log_return", "target_simple_return", "mu_A", "mu_I", "mu_U")
                require(all(phase + "__" + n in members for n in required), "R3 full-row prediction member omitted")
            for cost in SCENARIOS:
                for family in FAMILIES:
                    found = [r for r in ledgers if (r["minutes"], r["outer_year"], r["phase"], r["scenario"], r["family"]) ==
                             (frame["minutes"], fold["year"], "outer", cost, family)]
                    require(len(found) == 1 and found[0]["metrics"] == fold["economics"][cost][family],
                            "R3 analysis annual metrics differ from retained ledger")
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
                                "completed_I_trades": frame["completed_I_trades"]})
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


def render_readme(run, profile, protocol, identity, audit, frames, retained, launcher):
    number, pct, table = shared.number, shared.percentage, shared.table
    supported = [frame["minutes"] for frame in frames if frame["criterion_met"]]
    headline = ("The frozen R3 criterion is **supported for " + ", ".join(f"{m}m" for m in supported) +
                "**; it is **not-supported** for every other timeframe.") if supported else (
        "The frozen R3 criterion is **not-supported in all five timeframes**.")
    primary, gates, annual, economics, gaps, costs = [], [], [], [], [], []
    cash_selections = 0
    for frame in frames:
        minutes, bs = frame["minutes"], frame["bootstrap"]["7"]
        def effect(name):
            row = bs["comparisons"][name]
            return f"{row['mean_daily_net_log_gain']:.8f} [{row['ci95_low']:.8f}, {row['ci95_high']:.8f}]"
        primary.append([minutes, effect("I_minus_A"), effect("I_minus_cash"),
            *[number(bs["comparisons"][name]["p_one_sided"], 9) for name in COMPARISONS],
            number(frame["p_holm"], 9), frame["outcome_if_verified"]])
        gates.append([minutes, *["yes" if frame["conditions"][name] else "no" for name in CONDITIONS],
                      frame["joint_positive_years"], frame["completed_I_trades"]])
        for fold in frame["folds"]:
            def choice(family):
                row = fold["selected"][family]
                model = "mean" if family == "U" else f"n={row['n']}, λ={row['lambda']:g}"
                return model + "; " + row["policy"]["id"]
            annual.append([minutes, fold["year"], number(fold["effects"]["I_minus_A"]),
                           number(fold["effects"]["I_minus_cash"]), *[choice(f) for f in ("A", "I", "U")]])
            cash_selections += fold["selected"]["I"]["policy"]["id"] == "cash"
        for family in FAMILIES:
            row = frame["economics"]["all_outer"]["primary"][family]
            economics.append([minutes, family, pct(row["net_return"]), number(row["net_log_return"]),
                pct(row["gross_return"]), pct(row["max_drawdown"]), pct(row["exposure_fraction"]),
                row["one_way_turnover"], row["completed_trades"], number(row["break_even_symmetric_cost_bps_per_side"], 3)])
        first = next(f for f in frame["folds"] if f["year"] == 2023)
        for family in ("A", "I", "U", "buy_hold"):
            old = first["economics"]["primary"][family]
            recent = frame["economics"]["continuous_2024_plus"]["primary"][family]
            gaps.append([minutes, family, pct(old["net_return"]), old["gap_count"], number(old["gap_gross_log_return"]),
                         old["delayed_exposure_changes"], pct(recent["net_return"])])
        for scenario in SCENARIOS:
            rows = frame["economics"]["all_outer"][scenario]
            costs.append([minutes, scenario, *[pct(rows[family]["net_return"]) for family in FAMILIES]])
    positive = sum(frame["economics"]["all_outer"]["primary"]["I"]["net_log_return"] > 0 for frame in frames)
    native_bytes = sum(record["bytes"] for record in retained["external_native_keys"].values())
    external_bytes = sum(record["bytes"] for record in retained["external_numerical_bundles"].values())
    count = len(retained["copied_producer_artifacts"]) + 20 + 3 + 7 + 2 + len(retained["external_operational_receipts"])
    proto_path = "experiments/geometry_information/" + profile["protocol_filename"]
    command, python = shlex.join(identity["command"]), shlex.quote(identity["command"][0])
    data, keys = (shlex.quote(identity["input_paths"][name]) for name in ("data_dir", "keys_dir"))
    run_arg = shlex.quote(str(run))
    execution = "No external launcher receipt was supplied."
    if launcher is not None:
        launch = shared.load_json(launcher)
        execution = f"The external launcher records exit 0 and {number(launch['elapsed_seconds'], 6)} seconds."
    return f"""# R3: fixed qualitative interactions beyond additive geometry

{headline} These outcomes follow a full independent audit of the complete attempt. They are retrospective evidence under the declared OHLC execution proxy, not a live trading-edge claim or proof of outperformance against passive Bitcoin ownership. **R3 completes the campaign's third and final hypothesis family.**

The unchanged producer [analysis](analysis.json) remains `COMPLETE_PENDING_INDEPENDENT_AUDIT` with conditional outcomes. This report joins it to the later [full independent audit](verification.json); the collector does not refit models, select policies or mutate producer files. Every timeframe, annual fold, cash choice and cost/control result is retained.

## Controlled feature change

A is exactly the additive geometry feature basis called G in R2, fitted freshly in R3. I contains A and one fixed 225-column block for the **current and immediately prior candle only**. The block contains 75 body-interval weak orders and 150 full low-to-high range weak orders, each conditioned on both body directions. It uses only native endpoint ranks and orientation. Each row activates exactly one body entry and one range entry.

{table(['History', 'A columns', 'I columns'], [[2,42,267],[3,80,305],[5,156,381],[10,346,571]])}

Two intervals allowing points have 26 possible weak orders: 13 proper/proper, five point/proper, five proper/point and three point/point. Body intervals are points exactly when their direction is flat, giving `4×13 + 4×5 + 3 = 75` conditioned entries. Flat bodies may still have proper full ranges, giving `4×13 + 4×18 + 26 = 150` range entries. The exact [catalogue](catalogue.json), SHA-256 `{CATALOGUE_SHA256}`, is fixed by mathematical admissibility. Exhaustive synthetic enumeration covers all 7,452 oriented two-bar states and reaches every declared column. Market-zero-support columns remain present.

There is no learned vocabulary, arbitrary reference-column removal, extra direction-pair block, body-by-range crossing or added interaction with older lags. Longer histories enlarge only A. The complete one-hot groups share direction-pair spans and overlap with A and the intercept. Positive ridge penalties make the fitted solution unique, but this declared redundant basis changes effective shrinkage. The hypothesis concerns the **entire richer pipeline**; it does not isolate wick information or compare equal parameter capacity.

## Frozen model, policy and execution contract

The five pinned source series span January 2020 through October 7, 2026. Four outer folds cover 2023, 2024, 2025 and partial 2026. Each uses the prior calendar year for inner validation and earlier history for inner training, then refits the selected model on all admissible pre-outer data. An earlier outer year may enter a later fold's fitting history under that frozen schedule. Nothing from R2's coefficients, policies, scores, predictions or return statistics substitutes for a fresh R3 fit.

The target is `log(O[t+2]/O[t+1])`, retaining exact zero returns. All candidates share causal ten-bar eligibility. Scored candle t must open in its phase, have two consecutive subsequent bars, and exit strictly before the phase cutoff. Causal predictions also cover valid final and pre-gap feature rows without future labels. The ridge objective is mean squared error divided by two plus `λ·sum(beta²)/2`, with unpenalized intercept, unscaled fixed binary features, n∈{{2,3,5,10}} and λ∈{{0.1,0.01,0.001,0.0001}}. Inner MSE selects each A/I model; the predeclared tie order and direct-gradient acceptance rule apply to every fit. U is the contemporaneous fitting-sample mean return.

Inner validation chooses one of seven policies independently for A, I and U: cash, or entry multiples {{0,0.5,1}} crossed with exit multiples {{−0.5,0}} of the primary round-trip log-cost hurdle. It maximizes validation net log return with the frozen cash/turnover/threshold/id tie order. While cash, enter when the signed forecast is at least the entry threshold; while long, remain long when it is at least the exit threshold. When exit < entry, equality at exit preserves current state. NaN requests cash. These are conditional return forecasts, not probabilities, and positions may span multiple forecast horizons.

Primary fees/slippage are **10+2 bps per side**; zero (0+0), reduced (5+1) and stress (20+4) scenarios reuse the same selected model, primary-cost thresholds and request path. They are declared scenarios, not account-specific fee evidence. A completed candle's request executes only at the next observed opening. Existing positions are marked through source gaps; no future gap triggers an anticipatory exit. Every annual phase starts in cash, imports no earlier pending request, and liquidates at its prescribed terminal opening. Cash and buy-and-hold use the same administrative boundaries.

## Primary paired results

Effects are mean daily net-log-return differences, equally weighted across every calendar day including inactive days. Brackets are individual seven-day moving-block-bootstrap 95% intervals, **not a joint simultaneous 95% region**. Both positive effects, both positive interval lower endpoints, composite Holm p<.05 across five timeframes, at least three of the same four positive years, and twenty completed I trades are mandatory. The activity count is not an effective sample size or proof of independent trades.

{table(['Minutes','I−A/day [95% CI]','I−cash/day [95% CI]','Exact p I−A','Exact p I−cash','Composite p Holm','Audited outcome'], primary)}

{table(['Minutes','Both gains >0','Both CI lower >0','Holm <.05','Same ≥3 years','≥20 I trades','Same positive years','I trades'], gates)}

## Exact bootstrap tail arithmetic

All thirty cases use 2,000 shared-draw replicas: five timeframes × three block lengths × two comparisons. For each executed binary64 daily contrast, its exact binary-rational value is encoded with a common power-of-two denominator. Let S be the exact original numerator sum and T the sum under a replica's integer sampling multiplicities. Every replicate contains the same total number N of calendar days, so the centered one-sided event `(T−S)/N >= S/N` is exactly **T≥2S**. Signed integer arithmetic decides the event, includes equality, and uses no epsilon, padding or float-tail substitution. The recorded p is `(1 + exact true events) / 2001`; the timeframe composite takes the maximum of its two p-values before Holm adjustment.

Each timeframe's `bootstrap-exact.json` retains all decimal numerators, denominator exponents, fold lengths, pooled sums and canonical hashes. Its external `bootstrap.npz` retains ordinary and centered float64 arrays and all boolean exact-hit arrays. The full audit independently checks all five encodings and **60,000 exact tail bits**, then every exact count, p, composite, adjusted p and success condition. The collector also binds the compact integer sums/hashes and retained hit counts directly to the unchanged analysis and audit receipt. This is the separately declared R3 definition, not the R2 floating-tail audit workaround.

Observed means and percentile confidence intervals remain the declared binary64 calculations; centered float replicas are diagnostic. Exact integer tails remove summation ambiguity only for the executed binary64 daily contrasts. They do not make the economic account exact real arithmetic, require an approximately replayed account to have identical discontinuous decisions, or turn previously inspected history into fresh evidence. [primary-and-sensitivity.csv](primary-and-sensitivity.csv) contains aggregate summaries for 7-, 1- and 28-day blocks. Complete replica arrays remain in the sealed external bundles indexed by each `arrays.json`. Sensitivity blocks add no alternative route to success.

## Annual outcomes and all frozen choices

Annual effects are total net log returns at primary costs. Policy ids encode the entry/exit multiples (`xm05` means −0.5); full numeric thresholds, all seven trials and selected model identities remain in `selections.jsonl` and `ledgers.jsonl`. [model-policy-choices.csv](model-policy-choices.csv) lists all sixty choices. [prediction-scores.csv](prediction-scores.csv) includes both phases' A/I/U MSE and zero-target counts.

{table(['Minutes','Year','I−A log','I−cash log','A model; policy','I model; policy','U; policy'], annual)}

## Primary costs and descriptive controls

The aggregate concatenates separately reset annual accounts. Turnover is one-way full-account exposure changes; completed trades include terminal liquidations. The break-even cost is implied by the realized gross path and turnover and is undefined without turnover. It is not a promised executable allowance. Return, drawdown and other risk measures are descriptive. U and buy-and-hold remain controls; the primary success rule does not test superiority against either.

{table(['Minutes','Family','Net return','Net log','Gross return','Max drawdown','Exposure','Turnover','Trades','Break-even bps/side'], economics)}

The source gap period is separated below. Continuous 2024+ means separately reset 2024, 2025 and partial-2026 accounts; positions are not carried across fold boundaries.

{table(['Minutes','Family','2023 net return','2023 gaps','Gap gross log','Delayed changes','2024+ net return'], gaps)}

All cost sensitivities use the same primary-selected policies without reselection:

{table(['Minutes','Scenario','A net return','I net return','U net return','Cash net return','Buy-hold net return'], costs)}

[economics.csv](economics.csv) preserves all annual and aggregate cost/control metrics, including cost drag, turnover, exposure, completed trades, gaps, drawdown and annualized descriptive measures.

## Audit, retained artifacts and reproduction

The [protocol](protocol.json) is bound to freeze `{profile['freeze_commit']}` and SHA-256 `{profile['protocol_sha256']}`. [provenance.json](provenance.json) binds all 459,503 source rows and the same five immutable snapshots. [features.json](features.json) binds all 458,972 native keys, the fixed catalogue and every N×2 interaction-index digest. [run.json](run.json) retains code, command, runtime, package, thread and settings identities. Native preparation receipts are archived separately.

The [full audit](verification.json) checks 640 candidates, 40 refits, 60 policy choices, 420 inner-validation and 400 outer ledgers, all 40 prediction phases, every array member and every exact tail event. Its largest recorded numeric comparison error is `{audit['max_numeric_error']}` and maximum independent direct fit gradient is `{audit['max_independent_fit_gradient']}`. Neither collector nor verifier runs an optimizer. All coefficients, fitting identities, direct objectives/gradients, validation scores and choices remain in compact JSONL records.

{execution} These are operational receipts, not a matched speedup benchmark or a compute-ceiling claim. The original [producer manifest](producer-manifest.json) and seal are copied unchanged. The independent [report manifest](manifest.json) seals this {count}-file package, including any supplied external launcher/execution/audit receipts. The twenty annual plus five bootstrap NPZ files ({external_bytes:,} bytes) and native key payloads ({native_bytes:,} bytes) remain externally retained through [exact identities](retained-artifacts.json). All integer metadata is copied into the report. Large bundles are required for complete replay; compact packaging does not reduce audit scope.

Use the completed R3 publication tree containing the final verifier and exactly the producer file hashes recorded in `run.json`. Later edits to computational files will fail original-run identity checks. Reuse the recorded sealed native-key directory. The original producer invocation was:

```sh
{command}
```

Re-execution requires a new unused `--out` directory, identical pinned inputs, and the recorded implementation and freeze pair. To audit and collect the retained run:

```sh
{python} -m pip install -r requirements-information.txt
{python} experiments/geometry_information/verify_round3.py --stage full --run {run_arg} --keys-root {keys} --data-dir {data} --protocol {proto_path} --out {run_arg}/verification.json
{python} experiments/geometry_information/collect_round3.py --run {run_arg} --out benchmarks/reports/{profile['report_name']}
```

Optional `--launcher` and repeatable `--audit-receipt` archive external operational evidence. Keep those files outside the sealed run. Different existing report evidence is never overwritten.

## Residue and campaign stop

I has positive pooled primary-cost net log return in {positive} of five timeframes and selects cash in {cash_selections} of twenty timeframe/year cases. The complete joint criterion is supported in {len(supported)} of five timeframes. These are complete outcomes for the fixed family; no outer winner is used to change the vocabulary, penalty grid, policies, horizon or cost assumptions.

The record preserves the [exact-pattern predecessor](../20261008-bitcoin-direction/README.md), [R1 numerical failure](../20261008-geometry-information-r1-failed/README.md), [R1a information experiment](../20261008-geometry-information-r1a/README.md), and [R2 payoff experiment with audit-development history](../20261008-geometry-payoff-r2/README.md). All historical data and preceding outcomes were exposed before R3. Nested fitting controls row availability within each fold but does not erase adaptive research exposure; the five-timeframe Holm family does not account away the whole campaign.

A not-supported result does not prove all geometric functions useless; a supported result does not establish live tradeability or excess return over passive Bitcoin. This finite current/previous interaction projection omits many possible functions. The execution proxy lacks quotes, depth, latency, market impact and actual fills; no real orders were placed. **The finite campaign ends with R3's retained result.** Any eventual trading-edge claim needs separately frozen future-data and execution evidence, rather than extending the historical search until a favorable outcome appears.

Bibliography: [declared fee-scenario reference](https://www.binance.com/en/fee/trading); [backtest-overfitting research](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). These are contextual links rather than substitutes for this protocol and its measured evidence.
"""


def collect(run, out, keys_dir=None, launcher=None, audit_receipts=(), verification=None):
    run, out = Path(run).resolve(), Path(out).resolve()
    require(run != out and run not in out.parents and out not in run.parents, "report and sealed run must be separate directories")
    manifest, sources = checked_manifest(run)
    identity = shared.load_json(run / "run.json")
    require(identity["schema"] == "filang-interaction-payoff-run-v1" and identity["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "complete R3 producer execution required")
    profile, protocol = admitted_protocol(run, identity)
    require(identity["source_provenance_sha256"] == shared.digest(run / "provenance.json"), "R3 provenance identity differs")
    audit_path = (Path(verification) if verification is not None else run / "verification.json").resolve()
    audit = shared.load_json(audit_path)
    check_audit(run, audit, profile)
    analysis = shared.load_json(run / "analysis.json")
    frames = check_analysis(analysis, profile)
    features = shared.load_json(run / "features.json")
    check_catalogue(run, protocol, identity, features)
    fits, choices, ledgers = read_records(run)
    arrays = check_record_bindings(run, manifest, identity, protocol, frames, features, fits, choices, ledgers)
    check_exact_bootstrap(run, audit, frames, arrays)
    require(audit["audited_array_members"] == sum(len(record["arrays"]) for record in arrays.values()),
            "R3 audit and retained array-member census differ")
    copies = {name: path for name, path in sources.items() if not name.endswith(".npz")}
    require(all(path.suffix in (".json", ".jsonl") for path in copies.values()), "unexpected R3 compact artifact format")
    copies.update({"producer-manifest.json": run / "manifest.json", "producer-manifest.sha256": run / "manifest.sha256",
                   "verification.json": audit_path})
    native_copies, retained_keys = shared.native_receipts(identity, features, keys_dir)
    operational_copies, operational = shared.operational_receipts(run, identity, launcher, audit_receipts)
    copies.update(native_copies)
    copies.update(operational_copies)
    retained = {"schema": "filang-interaction-payoff-report-retained-artifacts-v1", "source_run": str(run),
        "protocol_sha256": profile["protocol_sha256"], "freeze_commit": profile["freeze_commit"],
        "producer_manifest_sha256": shared.digest(run / "manifest.json"), "analysis_sha256": shared.digest(run / "analysis.json"),
        "verification_sha256": shared.digest(audit_path), "audit_admission": "full PASS only",
        "catalogue_sha256": CATALOGUE_SHA256, "tail_method": TAIL_METHOD,
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
    require(len(copies) + len(generated) + 2 < 100, "R3 compact report exceeds frozen target of fewer than 100 files")
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
