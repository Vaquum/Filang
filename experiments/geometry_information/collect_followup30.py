#!/usr/bin/env python3
"""Package the complete audited F30-D1 record without changing its producer.

All selected predecessor forecasts, native keys and new numerical bundles are
copied byte-for-byte. Raw Parquet and prepared CSV inputs retain their external
immutable pins. This collector performs no fitting or new market analysis.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys


PROTOCOL_SHA256 = "4099e7a6620387d0fbe2267819ca0d37dff0f52da3e6bf8689705e979adf497b"
FREEZE_COMMIT = "ed7e0b9bccedebc6bda75d7ab701829a6a708c5f"
YEARS = (2023, 2024, 2025, 2026)
COVERAGE = {
    "native_keys": 118432, "adapter_fits": 8,
    "original_prediction_phases": 8, "adapted_prediction_phases": 8,
    "aggregate_periods": 55, "magnitude_cells": 30, "decision_cells": 40,
    "score_boundaries": 16, "score_distributions": 32,
    "correction_distributions": 16, "sample_censuses": 8,
    "weighted_gains": 10, "past_means": 4, "calendar_days": 1376,
    "bootstrap_cases": 3, "exact_tail_bits": 6000,
    "all_records": True, "sampled": False,
}
CHECKS = {
    "predecessor_exact_bytes_and_full_audit", "raw_prepared_source_pins",
    "all_native_keys_and_projections",
    "all_original_phases_predictions_and_model_ownership",
    "all_adapter_samples_objectives_gradients", "all_full_row_adapted_predictions",
    "all_diagnostic_tables_and_partitions",
    "all_daily_arrays_and_raw_gain_reconciliation",
    "all_exact_encodings_replicas_and_tail_bits", "primary_and_continuation_decisions",
    "all_input_and_producer_artifact_identities", "no_model_fitting_by_verifier",
}
TABLES = {
    "periods": 55, "magnitude_cells": 30, "decision_cells": 40,
    "score_boundaries": 16, "distribution": 32, "corrections": 16,
    "sample_census": 8, "weighted_gains": 10, "past_means": 4,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def record(path):
    path = Path(path)
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def load_json(path):
    def bad(value):
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(Path(path).read_text(), parse_constant=bad)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def bounded(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    require(not relative.is_absolute() and ".." not in relative.parts,
            "artifact path must be a confined relative path")
    path = root / relative
    require(path.resolve().is_relative_to(root), "artifact path escapes its root")
    require(not path.is_symlink(), "symbolic-link artifact is not an immutable file")
    return path


def checked_manifest(run):
    run = Path(run)
    seal = (run / "manifest.sha256").read_text()
    require(seal == digest(run / "manifest.json") + "\n", "producer manifest seal differs")
    manifest = load_json(run / "manifest.json")
    require(manifest.get("schema") == "filang-followup30-run-manifest-v1" and isinstance(manifest.get("files"), dict),
            "producer manifest schema/entries missing")
    files = manifest["files"]
    required = {"protocol.json", "run.json", "analysis.json", "inputs.json", "diagnostics.json",
                "fits.jsonl", "daily.csv", "daily.npz", "bootstrap-exact.json",
                "bootstrap-1.npz", "bootstrap-7.npz", "bootstrap-28.npz"}
    for year in YEARS:
        required.update(f"{year}/adapters/{family}.json" for family in ("B", "G"))
        required.update(f"{year}/{phase}.{extension}" for phase in ("validation", "outer")
                        for extension in ("npz", "json"))
        required.add(f"{year}/diagnostic-membership.npz")
    require(required <= set(files), "required producer records missing")
    copied = load_json(run / "inputs.json")["copied_files"]
    require(all(p.startswith(("predecessor/", "native/30m/")) for p in copied),
            "input bundle uses an undeclared location")
    require(set(files) == required | set(copied), "producer manifest has incorrect declared file coverage")
    sources = {}
    for relative, identity in sorted(files.items()):
        require(relative not in {"manifest.json", "manifest.sha256", "verification.json"},
                "self/audit included in producer manifest")
        source = bounded(run, relative)
        require(source.is_file(), "missing producer artifact: " + relative)
        require(record(source) == {"bytes": identity["bytes"], "sha256": identity["sha256"]},
                "producer artifact digest differs: " + relative)
        sources[relative] = source
    actual = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()}
    require(actual == set(files) | {"manifest.json", "manifest.sha256", "verification.json"},
            "producer run has a missing or unsealed file")
    return manifest, sources


def check_audit(run, audit, identity):
    require(audit.get("schema") == "filang-30m-signal-followup-verification-v1" and
            audit.get("stage") == "full" and audit.get("status") == "PASS",
            "full accepted independent audit required")
    require(audit.get("protocol_sha256") == PROTOCOL_SHA256 and
            audit.get("freeze_commit") == FREEZE_COMMIT, "audit protocol/freeze differs")
    require(audit.get("producer_manifest_sha256") == digest(run / "manifest.json") and
            audit.get("analysis_sha256") == digest(run / "analysis.json"),
            "audit is stale or bound to another run")
    require(audit.get("implementation_commit") == identity["implementation"]["git_commit"] and
            audit.get("no_model_fitting_by_verifier") is True,
            "audit implementation/independence receipt differs")
    coverage = audit.get("coverage", {})
    require(all(type(coverage.get(k)) is type(v) and coverage[k] == v for k, v in COVERAGE.items()),
            "independent audit is partial or has incorrect coverage")
    require(set(audit.get("checks", {})) == CHECKS and all(v is True for v in audit["checks"].values()),
            "missing or failed required independent check")
    require(audit.get("all_array_members_checked") is True and
            type(audit.get("audited_array_members")) is int and audit["audited_array_members"] > 0,
            "full array-member verification assertion required")
    require(math.isfinite(audit.get("max_adapter_gradient", math.inf)) and
            0 <= audit["max_adapter_gradient"] <= 1e-10, "adapter gradient acceptance failed")
    require(math.isfinite(audit.get("max_numeric_error", math.inf)) and audit["max_numeric_error"] >= 0,
            "finite audit numerical error required")
    require(identity["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "original producer completion status must be preserved")


def check_tables(diagnostics):
    require(diagnostics.get("schema") == "filang-followup30-diagnostics-v1", "diagnostic schema differs")
    for name, count in TABLES.items():
        require(isinstance(diagnostics.get(name), list) and len(diagnostics[name]) == count,
                "diagnostic table coverage differs: " + name)
    periods = diagnostics["periods"]
    expected_periods = {("year", str(y)) for y in YEARS} | {("pooled", "pooled")}
    expected_periods |= {("leave_one_year_out", "without-" + str(y)) for y in YEARS}
    expected_periods |= {("month", f"{year}-{month:02}") for year in YEARS
                         for month in range(1, 13 if year < 2026 else 11)}
    require({(p["kind"], p["period"]) for p in periods} == expected_periods,
            "a required annual/monthly/leave-one-out period is missing or duplicated")
    scopes = [str(y) for y in YEARS] + ["pooled"]
    require({(r["period"], r["bin"]) for r in diagnostics["magnitude_cells"]} ==
            {(p, b) for p in scopes for b in range(6)}, "magnitude partition coverage differs")
    require({(r["period"], r["variant"], r["state"]) for r in diagnostics["decision_cells"]} ==
            {(p, v, s) for p in scopes for v in ("raw", "adapted") for s in range(4)},
            "decision partition coverage differs")
    boundaries = diagnostics["score_boundaries"]
    expected_boundaries = {(y, v, f) for y in YEARS for v in ("raw", "adapted") for f in ("B", "G")}
    require({(r["year"], r["variant"], r["family"]) for r in boundaries} == expected_boundaries,
            "score boundary coverage differs")
    cells = diagnostics.get("score_cells", [])
    expected_cells = {(r["year"], r["variant"], r["family"], b)
                      for r in boundaries for b in range(r["bin_count"])}
    require(len(cells) == len(expected_cells) and
            {(r["year"], r["variant"], r["family"], r["bin"]) for r in cells} == expected_cells,
            "score cell coverage differs")
    return {row["period"]: row["cell"] for row in periods if row["kind"] in ("year", "pooled")}


def check_analysis(analysis, diagnostics, identity):
    require(analysis.get("schema") == "filang-followup30-analysis-v1" and
            analysis.get("status") == "COMPLETE_PENDING_INDEPENDENT_AUDIT", "analysis is incomplete")
    require(analysis.get("protocol_sha256") == PROTOCOL_SHA256 and
            analysis.get("freeze_commit") == FREEZE_COMMIT, "analysis freeze identity differs")
    require(identity.get("protocol_sha256") == PROTOCOL_SHA256 and
            identity.get("freeze_commit") == FREEZE_COMMIT and
            identity.get("attempt_id") == "F30-D1", "producer identity differs")
    require(identity.get("amendments", []) == [] and identity.get("deviations", []) == [],
            "undeclared amendment or deviation")
    scopes = check_tables(diagnostics)
    bootstrap = analysis["bootstrap"]
    require(set(bootstrap) == {"1", "7", "28"}, "bootstrap case coverage differs")
    for block, row in bootstrap.items():
        require(row["block_days"] == int(block) and row["replicates"] == 2000 and
                row["seed"] == 20261008 + 30000 + int(block), "bootstrap configuration differs")
        hits = row["exact_tail_hit_count"]
        require(type(hits) is int and 0 <= hits <= 2000 and
                row["p_one_sided"] == (hits + 1) / 2001, "exact p-value/count differs")
        require(row["ci95_low"] <= row["ci95_high"] and row["original_count"] > 0,
                "bootstrap interval/count domain differs")
    gains = {str(y): scopes[str(y)]["variants"]["adapted"]["paired"]["log_loss_gain"] for y in YEARS}
    positive = sum(v is not None and v > 0 for v in gains.values())
    primary = bootstrap["7"]
    conditions = {"positive_pooled_gain": primary["gain"] > 0,
                  "ci_above_zero": primary["ci95_low"] > 0,
                  "p_below_005": primary["p_one_sided"] < 0.05,
                  "three_positive_years": positive >= 3,
                  "latest_2026_positive": gains["2026"] is not None and gains["2026"] > 0}
    supported = all(conditions.values())
    outcome = "supported" if supported else "not-supported"
    require(analysis["primary"]["conditions"] == conditions and
            analysis["primary"]["annual_gains"] == gains and
            analysis["primary"]["positive_years"] == positive and
            analysis["primary"]["criterion_met"] is supported,
            "recorded primary criterion differs from its evidence")
    require(analysis["primary"]["outcome"] == "inconclusive" and
            analysis["primary"]["outcome_if_verified"] == outcome and
            analysis["outcome"] == "inconclusive" and analysis["outcome_if_verified"] == outcome,
            "producer promoted an unaudited result or misstated its conditional outcome")
    alignment = {str(y): scopes[str(y)]["variants"]["adapted"]["paired"]["centered_alignment"] for y in YEARS}
    pooled_alignment = scopes["pooled"]["variants"]["adapted"]["paired"]["centered_alignment"]
    continuation = {"primary_supported_if_verified": supported,
                    "pooled_alignment_positive": pooled_alignment is not None and pooled_alignment > 0,
                    "latest_2026_alignment_positive": alignment["2026"] is not None and alignment["2026"] > 0,
                    "three_positive_alignment_years": sum(v is not None and v > 0 for v in alignment.values()) >= 3}
    require(analysis["continuation"]["conditions"] == continuation and
            analysis["continuation"]["gate_if_verified"] is all(continuation.values()) and
            analysis["continuation"]["annual_centered_alignment"] == alignment and
            analysis["continuation"]["pooled_centered_alignment"] == pooled_alignment and
            analysis["continuation"]["status"] == "PENDING_INDEPENDENT_AUDIT",
            "recorded continuation gate differs from its evidence")
    return outcome, scopes


def flatten(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = prefix + key
        if isinstance(item, dict):
            result.update(flatten(item, name + "."))
        elif isinstance(item, (list, tuple)):
            result[name] = json.dumps(item, separators=(",", ":"), allow_nan=False)
        else:
            result[name] = item
    return result


def write_csv(path, rows):
    rows = [flatten(row) for row in rows]
    fields = sorted({field for row in rows for field in row})
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def number(value, digits=10):
    return "unavailable" if value is None else f"{value:.{digits}g}"


def audit_history(receipt_paths, identity, manifest_sha256):
    """Describe supplied audit attempts without changing numerical admission."""
    records = [(path, load_json(path)) for path in receipt_paths if path.suffix == ".json"]
    records = [(path, value) for path, value in records if isinstance(value, dict)]
    history = []
    for path, value in records:
        if value.get("schema") != "filang-30m-signal-followup-verification-v1" or value.get("status") != "FAIL":
            continue
        require(value.get("stage") == "full" and value.get("protocol_sha256") == PROTOCOL_SHA256 and
                value.get("freeze_commit") == FREEZE_COMMIT, "supplied failed audit belongs to another protocol")
        failure_sha = digest(path)
        retention = any(v.get("schema") == "filang-audit-retention-receipt-v1" and
                        v.get("sha256") == failure_sha and
                        v.get("producer_manifest_sha256_unchanged") == manifest_sha256 and
                        v.get("original_producer_not_rerun") is True for _, v in records)
        retry = any(v.get("schema") == "filang-operation-receipt-v1" and v.get("status") == "COMPLETE" and
                    v.get("exit_code") == 0 and v.get("first_failed_audit_sha256") == failure_sha and
                    v.get("producer_implementation_commit") == identity["implementation"]["git_commit"] and
                    v.get("producer_rerun") is False for _, v in records)
        history.append({"receipt": path.name, "sha256": failure_sha,
                        "error": str(value.get("error", "unspecified")),
                        "verifier_sha256": value.get("verifier_sha256"),
                        "same_producer_reaudit_receipts": retention and retry})
    return history


def render_report(identity, analysis, diagnostics, audit, outcome, scopes, history=()):
    primary = analysis["bootstrap"]["7"]
    gate = analysis["continuation"]["gate_if_verified"]
    lines = ["# F30-D1 — 30-minute signal follow-up", "",
             f"**Final scientific outcome: {outcome}.** Full independent audit: PASS.", "",
             "This is a retrospective diagnosis of the already selected R1a 30-minute lead. "
             "The complete stability claim requires the matched affine-score gain, primary uncertainty "
             "conditions, annual consistency, and a positive partial-2026 effect. "
             "It is not a prospective confirmation, isolated wick effect, mutual-information estimate, or trading result.", "",
             "## Primary result", "",
             "| Quantity | Result |", "|---|---:|",
             f"| Adapted B−G log-loss gain, nats per binary observation | {number(primary['gain'])} |",
             f"| Individual 95% interval, seven-day bootstrap | [{number(primary['ci95_low'])}, {number(primary['ci95_high'])}] |",
             f"| Exact one-sided p-value | {number(primary['p_one_sided'])} |",
             f"| Exact tail hits / replicas | {primary['exact_tail_hit_count']} / 2000 |",
             f"| Scored binary observations | {primary['original_count']} |",
             f"| Positive annual adapted gains | {analysis['primary']['positive_years']} / 4 |", "",
             "| Required condition | Passed |", "|---|---|",]
    labels = {"p_below_005": "One-sided p < 0.05"}
    lines.extend(f"| {labels.get(key, key.replace('_', ' '))} | {str(value).lower()} |"
                 for key, value in analysis["primary"]["conditions"].items())
    lines.extend(["| Eight accepted fits and full independent audit | true |", "",
                  "A failure of the latest-year gate does not erase pooled evidence. "
                  "The original unaudited producer outcome remains byte-preserved; this report joins it to the later full audit.", "",
                  "## Annual and pooled attribution", "",
                  "| Period | Binary count | Raw B−G gain | Adapted B−G gain | Raw payoff alignment | Adapted payoff alignment |",
                  "|---|---:|---:|---:|---:|---:|"])
    for year in [str(y) for y in YEARS] + ["pooled"]:
        c = scopes[year]
        raw, adapted = c["variants"]["raw"]["paired"], c["variants"]["adapted"]["paired"]
        lines.append(f"| {year} | {c['counts']['binary']} | {number(raw['log_loss_gain'])} | "
                     f"{number(adapted['log_loss_gain'])} | {number(raw['centered_alignment'])} | "
                     f"{number(adapted['centered_alignment'])} |")
    lines.extend(["", "Alignment is mean((pG−pB) × (log return−past validation mean)) over all target-valid rows, "
                  "including flats. It is an association statistic, not strategy P&L. "
                  "The 2026 period ends at the pinned exclusive 2026-10-08 boundary.", "",
                  "## Magnitude attribution", "",
                  "Every bin is defined by the realized next open-to-open log return. "
                  "These are ex-post diagnostic partitions and cannot act as entry filters.", "",
                  "| Pooled outcome bin | Valid count | Raw gain | Adapted gain | Mean log return | One-bar break-even up frequency |",
                  "|---|---:|---:|---:|---:|---:|"])
    for row in diagnostics["magnitude_cells"]:
        if row["period"] == "pooled":
            c = row["cell"]
            lines.append(f"| {row['label']} | {c['counts']['target_valid']} | "
                         f"{number(c['variants']['raw']['paired']['log_loss_gain'])} | "
                         f"{number(c['variants']['adapted']['paired']['log_loss_gain'])} | "
                         f"{number(c['payoff']['mean_log_return'])} | {number(c['payoff']['break_even_up_probability'])} |")
    lines.extend(["", "The break-even calculation uses realized conditional magnitudes and the declared isolated "
                  "one-bar round-trip cost of 10 bps fee plus 2 bps slippage per side. "
                  "It is not a fitted threshold for persistent exposure. Undefined conditional quantities remain unavailable.", "",
                  "| Period | Variant | Absolute-return-weighted log-loss gain |", "|---|---|---:|"])
    lines.extend(f"| {row['period']} | {row['variant']} | {number(row['gain'])} |"
                 for row in diagnostics["weighted_gains"])
    lines.extend(["", "Weighted gain scores a return-magnitude-tilted outcome distribution. "
                  "It is neither an additional primary test nor a realized economic return.", "",
                  "## Primary block sensitivity", "",
                  "| Block days | Gain | Individual 95% interval | Exact one-sided p |", "|---|---:|---|---:|"])
    for block in ("1", "7", "28"):
        row = analysis["bootstrap"][block]
        lines.append(f"| {block} | {number(row['gain'])} | [{number(row['ci95_low'])}, "
                     f"{number(row['ci95_high'])}] | {number(row['p_one_sided'])} |")
    lines.extend(["", "Only seven-day blocks provide the primary decision. Every replicate resamples paired daily "
                  "loss sums and observation counts. Exact tails use N×T >= 2×S×N*, with equality included, "
                  "not R3's fixed-denominator predicate. All 6,000 decisions and executed integer encodings are retained.", "",
                  "## Continuation decision", "",
                  f"**The declared F30-M1 continuation gate {'passes' if gate else 'fails'}.**", "",
                  "| Required gate condition | Passed |", "|---|---|"])
    lines.extend(f"| {key.replace('_', ' ')} | {str(value).lower()} |"
                 for key, value in analysis["continuation"]["conditions"].items())
    lines.extend(["", ("The evidence permits one separately frozen probability-to-payoff experiment using the same "
                       "heads/adapters and common past-only magnitude estimates. No trading edge is established here."
                       if gate else
                       "This bounded follow-up closes with its full diagnostic findings. Favorable bins, months, "
                       "or magnitude-weighted scores cannot rescue the failed gate. A later fresh-data study would "
                       "require a separate frozen specification and execution evidence."), "",
                  "## Audit, provenance and runtime", "",
                  f"- Published freeze: `{FREEZE_COMMIT}`.",
                  f"- Protocol SHA-256: `{PROTOCOL_SHA256}`.",
                  f"- Producer implementation: `{identity['implementation']['git_commit']}`.",
                  f"- All {audit['coverage']['native_keys']:,} native keys, eight original and eight adapted "
                  "prediction phases, eight new fits, 55 aggregate periods and every declared detailed cell were checked.",
                  f"- Maximum adapter gradient: {number(audit['max_adapter_gradient'], 16)}.",
                  f"- Maximum continuous numerical discrepancy: {number(audit['max_numeric_error'], 16)}; "
                  "acceptance uses absolute 1e−10 plus relative 1e−10, with exact discrete checks on validated executed inputs.",
                  f"- Independent audit wall time: {number(audit.get('elapsed_seconds'), 12)} seconds.",
                  "- Runtime/package/thread/memory settings and operational receipts are retained; no matched speedup claim is made.", "",
                  "The pinned original full R1a audit covers its original unconsumed candidate fits and other timeframes. "
                  "This audit reconstructs every consumed 30m selected prediction and every new computation. "
                  "It does not claim to rerun the entire earlier five-timeframe search.", "",
                  "## Complete retained record", "",
                  "All sealed producer artifacts, including every selected predecessor forecast, coefficient/selection record "
                  "and exact native artifact, are copied with their original bytes. `report.json` binds the producer, audit, "
                  "source copies, collector and final decision. `manifest.json` and `manifest.sha256` seal this report.", "",
                  "[run/diagnostics.json](run/diagnostics.json) contains the complete fixed panel. The `tables/` directory presents every declared "
                  "table as CSV, preserving empty cells and undefined values. Original and adapted full-row arrays, "
                  "sidecars, fit records, daily arrays, bootstrap replicas and exact integer encodings remain in the copied run.", "",
                  "Raw Parquet and prepared OHLC CSV inputs remain external with the original immutable dataset revision "
                  "and exact byte identities. The scoped source bundle intentionally contains the consumed R1a evidence, "
                  "not every original five-timeframe run file. Refer to "
                  "[FOLLOWUP30.md](../../../experiments/geometry_information/FOLLOWUP30.md) for the scientific contract "
                  "and reproduction commands.", ""])
    if history:
        lines.extend(["## Retained audit attempts", "",
                      "Earlier failed full audits are inconclusive validation attempts. "
                      "Their original receipts remain visible alongside the successful full audit.", ""])
        for attempt in history:
            error = json.dumps(attempt["error"], ensure_ascii=True)
            lines.extend([f"- Retained FAIL: [{attempt['receipt']}](receipts/{attempt['receipt']}); "
                          f"error `{error}`; verifier `{attempt['verifier_sha256']}`."])
            if attempt["same_producer_reaudit_receipts"]:
                lines.extend(["  The retention and successful retry receipts bind this failure to a re-audit "
                              "of the same sealed producer. The producer, fitted adapters, forecasts and "
                              "scientific results were not rerun or replaced."])
            if (attempt["error"] == "'minutes'" and attempt["verifier_sha256"] ==
                    "876fcfde2896e0c3c77157e09adc9895b611cc8b9f7cd63ec06d31e9a98e0e89"):
                lines.extend(["  The verifier had passed a native-key receipt without the timeframe context "
                              "expected by the inherited prediction oracle. The reviewed verifier-only repair "
                              "restored that context with source/interval/key checks and an unmocked integration regression."])
        lines.append("")
    return "\n".join(lines)


def collect(run, out, receipts=()):
    run, out = Path(run).resolve(), Path(out).resolve()
    require(not out.exists(), "report output must be a fresh path")
    require(not out.is_relative_to(run) and not run.is_relative_to(out), "report/run paths must not overlap")
    require(digest(run / "protocol.json") == PROTOCOL_SHA256, "unrecognized frozen protocol")
    manifest, sources = checked_manifest(run)
    identity, analysis = load_json(run / "run.json"), load_json(run / "analysis.json")
    diagnostics, audit = load_json(run / "diagnostics.json"), load_json(run / "verification.json")
    inputs = load_json(run / "inputs.json")
    for field in ("predecessor_root", "data_root", "keys_root"):
        source_root = Path(inputs[field]).resolve()
        require(not out.is_relative_to(source_root) and not source_root.is_relative_to(out),
                "report output must not overlap an immutable input tree")
    check_audit(run, audit, identity)
    require(analysis["diagnostics_sha256"] == digest(run / "diagnostics.json") and
            analysis["inputs_sha256"] == digest(run / "inputs.json"), "analysis input/table binding differs")
    outcome, scopes = check_analysis(analysis, diagnostics, identity)
    require(audit.get("primary_outcome") == outcome and
            audit.get("continuation_gate") is analysis["continuation"]["gate_if_verified"],
            "audit final decision differs from the checked analysis")
    require(audit["coverage"].get("score_cells") == len(diagnostics["score_cells"]),
            "audit score-cell coverage differs")
    receipt_paths = []
    for value in receipts:
        source = Path(value).resolve()
        require(source.is_file() and not source.is_relative_to(run), "operational receipt must be an external file")
        require(source.name not in {p.name for p in receipt_paths}, "duplicate operational receipt name")
        receipt_paths.append(source)
    history = audit_history(receipt_paths, identity, digest(run / "manifest.json"))
    out.mkdir(parents=True)
    copied = {}
    for relative in sorted(set(sources) | {"manifest.json", "manifest.sha256", "verification.json"}):
        source, destination = bounded(run, relative), bounded(out, "run/" + relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        require(record(source) == record(destination), "report source copy differs")
        copied["run/" + relative] = {"source_relative_path": relative, **record(destination)}
    for source in receipt_paths:
        destination = bounded(out, "receipts/" + source.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        require(record(source) == record(destination), "operational receipt copy differs")
        copied["receipts/" + source.name] = {"source_path": str(source), **record(destination)}
    table_dir = out / "tables"
    table_dir.mkdir()
    for key in [*TABLES, "score_cells"]:
        write_csv(table_dir / (key + ".csv"), diagnostics[key])
    readme = render_report(identity, analysis, diagnostics, audit, outcome, scopes, history)
    (out / "README.md").write_text(readme)
    summary = {"schema": "filang-30m-signal-followup-report-v1", "attempt_id": "F30-D1",
               "protocol_sha256": PROTOCOL_SHA256, "freeze_commit": FREEZE_COMMIT,
               "producer_manifest_sha256": digest(run / "manifest.json"),
               "analysis_sha256": digest(run / "analysis.json"), "audit_sha256": digest(run / "verification.json"),
               "collector_sha256": digest(__file__), "outcome": outcome,
               "primary_conditions": analysis["primary"]["conditions"], "full_independent_audit": "PASS",
               "continuation_gate": analysis["continuation"]["gate_if_verified"],
               "coverage": audit["coverage"], "source_copies": copied, "audit_history": history,
               "csv_rows": {key: len(diagnostics[key]) for key in [*TABLES, "score_cells"]},
               "raw_source_storage": "external immutable pins; all consumed prediction/model/native artifacts copied"}
    write_json(out / "report.json", summary)
    files = {p.relative_to(out).as_posix(): record(p) for p in sorted(out.rglob("*")) if p.is_file()}
    write_json(out / "manifest.json", {"schema": "filang-30m-signal-followup-report-manifest-v1", "files": files})
    (out / "manifest.sha256").write_text(digest(out / "manifest.json") + "\n")
    return {"path": str(out), "outcome": outcome, "continuation_gate": summary["continuation_gate"],
            "files": len(files) + 2, "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file()),
            "manifest_sha256": digest(out / "manifest.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--receipt", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = collect(args.run, args.out, args.receipt)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"F30-D1 collection rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
