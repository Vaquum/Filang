#!/usr/bin/env python3
"""Collect compact, byte-preserved evidence from a verified direction experiment.

Large pattern/event tables remain in the original run. Their sealed identities
are retained, and every main-run file named by the matched benchmark reference
is streamed again to connect performance evidence to independently audited work.
Existing identical evidence is accepted; different existing files are refused.
README, figures, validation logs and other report files are never overwritten.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

from prepare_hf import digest, publish


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text())


def payload(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def bounded(root, relative):
    path = (root / relative).resolve()
    require(root in path.parents, f"artifact path escapes its source directory: {relative}")
    return path


def sealed(path):
    require(digest(path) == path.with_name(path.name + ".sha256").read_text().strip(),
            f"artifact seal mismatch: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "benchmark", "data-dir", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run, benchmark, data, out = (p.resolve() for p in (args.run, args.benchmark, args.data_dir, args.out))
    protocol, identity = load(run / "protocol.json"), load(run / "experiment.identity.json")
    environment, provenance = load(run / "environment.json"), load(data / "provenance.json")
    verification, timing = load(run / "verification.json"), load(benchmark / "benchmark.json")
    analysis = load(run / "analysis/analysis.json")
    protocol_sha, provenance_sha = digest(run / "protocol.json"), digest(data / "provenance.json")
    engine = identity["engine_sha256"]
    frames = [15, 30, 60, 120, 240]
    ids = [f"n{n:02}-{mode}" for n in range(2, 11) for mode in ("oriented", "unoriented")]
    expected_tasks = {f"{minute}m/tasks/{task}" for minute in frames for task in ids}
    require(sorted(protocol["timeframes_minutes"]) == frames and sorted(protocol["bars"]) == list(range(2, 11))
            and sorted(protocol["modes"]) == ["oriented", "unoriented"], "incomplete declared experiment")
    require(all(record["protocol_sha256"] == protocol_sha for record in
                (identity, environment, provenance, analysis, timing)), "inconsistent protocol identity")
    require(identity["data_provenance_sha256"] == timing["data_provenance_sha256"] == provenance_sha
            and environment["engine_sha256"] == timing["binary_sha256"] == engine,
            "inconsistent input or native-engine identity")
    require(digest(benchmark / "protocol.json") == protocol_sha, "benchmark protocol copy differs")
    require(verification["status"] == "PASS" and verification["task_count"] == 90
            and verification["all_native_geometry_reconstructed"] is True
            and verification["analysis_only"] is False and verification["sample_per_task"] is None,
            "collection requires the complete unsampled native audit")
    audits = {row["task"]: row for row in verification["tasks"]}
    require(len(verification["tasks"]) == len(audits) == 90 and set(audits) == expected_tasks,
            "verification task coverage differs")
    for audit in audits.values():
        require(audit["status"] == "PASS" and all(audit[key] is True for key in (
            "all_canonical_events_checked", "all_catalogue_counts_checked", "all_event_labels_and_eligibility_checked"))
            and audit["canonical_events_checked"] == audit["events"], "incomplete per-task independent audit")
    require(sum(a["events"] for a in audits.values()) == verification["events_checked"]
            == verification["canonical_events_checked"], "verification event totals differ")
    reviewed = verification["analysis"]
    require(reviewed["status"] == "PASS" and reviewed["candidate_period_scores_checked"] == 1440
            and reviewed["selected_models_checked"] == 10 and analysis["status"] == "complete"
            and analysis["complete_design"] is True and analysis["task_count"] == 90
            and analysis["candidate_count"] == len(analysis["candidates"]) == 720
            and len(analysis["selected"]) == 10
            and reviewed["analysis_sha256"] == digest(run / "analysis/analysis.json"),
            "analysis is not bound to a complete independent audit")
    require(timing["status"] == "PASS" and timing["all_scientific_outputs_byte_identical_within_timeframe"] is True,
            "benchmark has not passed scientific parity")
    references = timing["reference_artifacts"]
    require(set(references) == {str(m) for m in timing["timeframes_minutes"]}, "benchmark reference coverage")
    expected_runs = {(m, w, r) for m in timing["timeframes_minutes"] for w in timing["worker_counts"]
                     for r in range(1, timing["repeats_per_worker_and_timeframe"] + 1)}
    actual_runs = {(r["minutes"], r["requested_workers"], r["repeat"]) for r in timing["records"]}
    require(actual_runs == expected_runs and len(timing["records"]) == len(expected_runs), "benchmark repeat coverage")
    for record in timing["records"]:
        require(record["exit_code"] == 0 and record["fresh_measurement"] is True
                and record["equivalence_status"] == "PASS"
                and record["artifact_equivalence_sha256"] == references[str(record["minutes"])]["artifact_sha256"],
                "benchmark record lacks matching fresh-run evidence")

    files, metadata, generated = {}, {}, {}
    def include(source, relative):
        source = source.resolve()
        require(relative not in files or files[relative] == source, "duplicate collected destination")
        files[relative] = source
        metadata[relative] = {"bytes": source.stat().st_size, "sha256": digest(source), "source": str(source)}

    for name in ("protocol.json", "environment.json", "experiment.identity.json", "verification.json"):
        include(run / name, name)
    include(data / "provenance.json", "provenance.json")
    include(benchmark / "benchmark.json", "benchmark.json")
    for source in sorted((run / "timings").glob("*.json")):
        include(source, "timings/" + source.name)
    required_timings = {"analysis.json", "verification.json", *(f"native-{m}m.json" for m in frames)}
    require(required_timings <= {p.name for p in (run / "timings").glob("*.json")}, "missing stage timing evidence")
    analysis_root = run / "analysis"
    analysis_seal = load(analysis_root / "artifacts.json")
    required_analysis = {"analysis.json", "candidates.csv", "selected.csv"}
    required_analysis.update(s[key] for s in analysis["selected"] for key in ("daily_file", "probabilities_file"))
    require(set(analysis_seal["files"]) == required_analysis, "analysis artifact coverage differs")
    for relative, record in analysis_seal["files"].items():
        source = bounded(analysis_root, relative)
        require(source.stat().st_size == record["bytes"] and digest(source) == record["sha256"], "analysis artifact checksum")
        include(source, relative)
    include(analysis_root / "artifacts.json", "analysis-artifacts.json")
    source_records = {s["minutes"]: s for s in provenance["sources"]}
    require(set(source_records) == set(frames) and len(provenance["sources"]) == 5, "source provenance coverage")
    pinned = {s["minutes"]: s for s in protocol["sources"]}
    require(all(source_records[m]["source"] == pinned[m] and source_records[m]["source_sha256"] == pinned[m]["sha256"]
                for m in frames), "prepared provenance differs from pinned Hub identities")
    task_files = {}
    for minute in frames:
        frame = run / f"{minute}m"
        manifest, config = load(frame / "manifest.json"), load(frame / "run.config.json")
        sealed(frame / "manifest.json")
        csv_path = data / f"{minute}m/ohlcv.csv"
        source = source_records[minute]
        require(digest(csv_path) == source["csv_sha256"] and csv_path.stat().st_size == source["csv_bytes"], "source CSV changed")
        require(manifest["status"] == "COMPLETE" and manifest["completed_tasks"] == manifest["total_tasks"] == 18
                and {t["id"] for t in manifest["tasks"]} == set(ids) and all(t["status"] == "COMPLETE" for t in manifest["tasks"])
                and manifest["engine_sha256"] == config["engine_sha256"] == engine
                and manifest["source_sha256"] == config["source_sha256"] == source["csv_sha256"]
                and manifest["context_sha256"] == digest(frame / "run.config.json"), "native frame identity differs")
        for key in ("history_start", "validation_start", "test_start", "end"):
            require(manifest[key] == config[key] == protocol[key], "native phase boundaries differ")
        for name in ("manifest.json", "manifest.json.sha256", "run.config.json"):
            include(frame / name, f"native/{minute}m/{name}")
        for task in ids:
            relative = f"{minute}m/tasks/{task}"
            folder, audit = run / relative, audits[relative]
            sealed(folder / "artifacts.tsv")
            require(digest(folder / "artifacts.tsv") == audit["artifact_manifest_sha256"], "task manifest changed since independent audit")
            with (folder / "artifacts.tsv").open() as stream:
                records = list(csv.DictReader(stream, delimiter="\t"))
            declared = {r["file"]: {"bytes": int(r["bytes"]), "sha256": r["sha256"]} for r in records}
            require(set(declared) == {"patterns.tsv", "events.tsv", "summary.json", "task.identity", "timing.json"}
                    and len(records) == 5, "task artifact schema differs")
            summary = load(folder / "summary.json")
            for key in ("bars", "mode", "interval_seconds", "source_sha256", "events", "observed_patterns", "training_observed_patterns",
                        "universe_patterns", "unobserved_patterns", "candidate_decisions", "gap_purged", "boundary_purged"):
                require(summary[key] == audit[key], "task summary differs from its independent audit")
            require(summary["engine_sha256"] == engine and summary["context_sha256"] == manifest["context_sha256"]
                    and (folder / "task.identity").read_text() == f"{manifest['context_sha256']}\n{summary['bars']}\n{summary['mode']}\n",
                    "task context differs")
            task_files[relative] = declared
            for name in ("summary.json", "timing.json", "task.identity", "artifacts.tsv", "artifacts.tsv.sha256"):
                if name in declared:
                    require((folder / name).stat().st_size == declared[name]["bytes"] and digest(folder / name) == declared[name]["sha256"], "small task artifact changed")
                include(folder / name, f"native/{relative}/{name}")
    linked = {}
    for minute, reference in references.items():
        expected = {f"tasks/{task}/{name}" for task in ids for name in ("patterns.tsv", "events.tsv")}
        require(set(reference["files"]) == expected, "benchmark reference file coverage")
        require(hashlib.sha256(payload({"files": reference["files"], "tasks": reference["tasks"]})).hexdigest()
                == reference["artifact_sha256"], "benchmark reference aggregate checksum")
        for relative, record in reference["files"].items():
            source = bounded(run, f"{minute}m/{relative}")
            main_record = task_files[f"{minute}m/{Path(relative).parent}"][Path(relative).name]
            require(record == main_record and source.stat().st_size == record["bytes"] and digest(source) == record["sha256"],
                    "benchmark scientific bytes differ from independently audited main run")
            linked[f"{minute}m/{relative}"] = record
    generated["benchmark-main-equivalence.json"] = payload({
        "version": 1, "status": "PASS", "method": "Stream SHA-256 of actual main-run scientific files; equality to independently audited task artifact seals and every benchmark reference",
        "protocol_sha256": protocol_sha, "engine_sha256": engine, "verification_sha256": digest(run / "verification.json"),
        "benchmark_sha256": digest(benchmark / "benchmark.json"), "files_checked": len(linked),
        "bytes_streamed": sum(r["bytes"] for r in linked.values()), "files": linked})
    for relative, content in generated.items():
        metadata[relative] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "source": "generated by collect_direction_report.py"}
    generated["evidence-manifest.json"] = payload({"version": 1, "status": "PASS", "source_run": str(run),
        "source_benchmark": str(benchmark), "source_data_dir": str(data), "collector_sha256": digest(Path(__file__)), "files": metadata})
    # Check every collision before copying anything. Other report files remain untouched.
    for relative in [*files, *generated]:
        target = bounded(out, relative)
        expected = hashlib.sha256(generated[relative]).hexdigest() if relative in generated else metadata[relative]["sha256"]
        require(not target.exists() or digest(target) == expected, f"existing report file differs: {target}")
    for relative, source in files.items():
        target = bounded(out, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        publish(target, source.read_bytes())
    for relative, content in generated.items():
        target = bounded(out, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        publish(target, content)
    print(json.dumps({"status": "PASS", "out": str(out), "collected_files": len(metadata),
                      "audited_events": verification["events_checked"], "benchmark_main_files_checked": len(linked)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("direction report collection: " + str(error), file=sys.stderr)
        raise SystemExit(2)
