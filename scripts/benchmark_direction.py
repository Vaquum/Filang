#!/usr/bin/env python3
"""Matched full-mapping timings for the pinned Bitcoin geometry experiment.

The default compares one and ten workers, three times each, on the largest
15-minute source. Every run maps all 2..10-bar windows in both modes, writes
every observed pattern and event, and accounts for the complete legal domain.
CSV loading, encoding, counting, hashing and durable native output are timed.
Input checks and cross-run byte-equivalence checks are outside the timer.

Use --timeframes all for the complete five-source corpus. Output must be a fresh
directory, normally under runs/. Every repeat's native artifacts are retained.
This benchmark checks execution equivalence; the separate experiment verifier
establishes independent mathematical and statistical correctness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys

from prepare_direction import load_protocol
from prepare_hf import digest
from run_direction_experiment import ROOT, git_value, json_bytes, measured


def comma_integers(value: str, name: str, minimum: int, maximum: int) -> list[int]:
    try:
        values = [int(part) for part in value.split(",")]
    except ValueError as error:
        raise ValueError(f"{name} must be comma-separated integers") from error
    if (not values or len(values) != len(set(values))
            or any(not minimum <= item <= maximum for item in values)):
        raise ValueError(f"{name} must be distinct integers in {minimum}..{maximum}")
    return values


def save_report(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".pending")
    with temporary.open("wb") as output:
        output.write(json_bytes(value))
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def prepared_sources(config: dict, protocol: Path, data_dir: Path,
                     minutes: list[int]) -> tuple[dict, dict[int, dict]]:
    provenance = json.loads((data_dir / "provenance.json").read_text())
    if provenance.get("version") != 1 or provenance["protocol_sha256"] != digest(protocol):
        raise ValueError("prepared input protocol differs from benchmark protocol")
    records = provenance["sources"]
    if len({record["minutes"] for record in records}) != len(records):
        raise ValueError("duplicate prepared timeframe")
    declared = {source["minutes"]: source for source in config["sources"]}
    indexed = {record["minutes"]: record for record in records}
    if set(indexed) != set(declared):
        raise ValueError("prepared sources do not match the protocol timeframe set")
    selected = {}
    for minute in minutes:
        record = indexed[minute]
        if record["source"] != declared[minute] or record["source_sha256"] != declared[minute]["sha256"]:
            raise ValueError(f"{minute}m provenance differs from the pinned Hub source")
        csv = data_dir / f"{minute}m" / "ohlcv.csv"
        if csv.stat().st_size != record["csv_bytes"] or digest(csv) != record["csv_sha256"]:
            raise ValueError(f"{minute}m prepared CSV no longer matches its provenance")
        selected[minute] = {**record, "csv": str(csv)}
    return provenance, selected


def task_ids(config: dict) -> list[str]:
    return sorted(f"n{bars:02}-{mode}" for bars in config["bars"] for mode in config["modes"])


def native_work(destination: Path, config: dict, source: dict,
                engine_sha256: str, workers: int) -> tuple[dict, dict, dict]:
    """Check actual emitted bytes and gather physical work outside the timer."""
    manifest_path = destination / "manifest.json"
    seal = (destination / "manifest.json.sha256").read_text().strip()
    if digest(manifest_path) != seal:
        raise ValueError(f"native manifest checksum differs: {destination}")
    manifest = json.loads(manifest_path.read_text())
    ids = task_ids(config)
    if (manifest["status"] != "COMPLETE" or manifest["resumed_tasks"] != 0
            or manifest["completed_tasks"] != len(ids) or manifest["total_tasks"] != len(ids)
            or sorted(task["id"] for task in manifest["tasks"]) != ids
            or any(task["status"] != "COMPLETE" for task in manifest["tasks"])):
        raise ValueError("benchmark requires a fresh, complete native mapping")
    if (manifest["engine_sha256"] != engine_sha256
            or manifest["source_sha256"] != source["csv_sha256"]
            or manifest["interval_seconds"] != source["minutes"] * 60
            or manifest["requested_workers"] != workers
            or not 1 <= manifest["effective_workers"] <= min(workers, len(ids))
            or manifest["workers_used_this_invocation"] != manifest["effective_workers"]):
        raise ValueError("native run differs from the declared source, binary or worker settings")
    for name in ("history_start", "validation_start", "test_start", "end"):
        if manifest[name] != config[name]:
            raise ValueError(f"native {name} differs from the protocol")
    files = {}
    tasks = []
    for task_id in ids:
        task_dir = destination / "tasks" / task_id
        summary = json.loads((task_dir / "summary.json").read_text())
        bars, mode = task_id[1:].split("-", 1)
        if (summary["status"] != "COMPLETE" or summary["task"] != task_id
                or summary["bars"] != int(bars) or summary["mode"] != mode):
            raise ValueError(f"task identity differs: {task_id}")
        universe = int(summary["universe_patterns"])
        observed = summary["observed_patterns"]
        training = summary["training_observed_patterns"]
        events = summary["events"]
        if (not 0 <= training <= observed <= events
                or universe - observed != int(summary["unobserved_patterns"])
                or universe - training != int(summary["training_unobserved_patterns"])
                or summary["candidate_decisions"] != events + summary["gap_purged"] + summary["boundary_purged"]):
            raise ValueError(f"task coverage counters do not reconcile: {task_id}")
        for target in ("cc", "body"):
            total = sum(summary["split_counts"][split][target][direction]
                        for split in ("train", "validation", "test")
                        for direction in ("down", "flat", "up"))
            if total != events:
                raise ValueError(f"task label totals do not reconcile: {task_id}/{target}")
        for name in ("patterns.tsv", "events.tsv"):
            path = task_dir / name
            relative = f"tasks/{task_id}/{name}"
            files[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}
        tasks.append({name: summary[name] for name in (
            "task", "bars", "mode", "universe_patterns", "observed_patterns",
            "training_observed_patterns", "candidate_decisions", "gap_purged",
            "boundary_purged", "events")})
    work = {
        "task_count": len(tasks),
        "encoded_windows": sum(task["events"] for task in tasks),
        "emitted_event_rows": sum(task["events"] for task in tasks),
        "emitted_pattern_rows": sum(task["observed_patterns"] for task in tasks),
        "scientific_output_bytes": sum(file["bytes"] for file in files.values()),
        "all_native_output_bytes": sum(path.stat().st_size for path in destination.rglob("*") if path.is_file()),
    }
    return manifest, {"files": files, "tasks": tasks}, work


def aggregate(records: list[dict], minutes: list[int], workers: list[int]) -> list[dict]:
    summaries = []
    for minute in minutes:
        frame = []
        for worker in workers:
            group = [record for record in records
                     if record["minutes"] == minute and record["requested_workers"] == worker]
            if not group:
                continue
            seconds = [record["elapsed_seconds"] for record in group]
            median = statistics.median(seconds)
            frame.append({
                "minutes": minute, "requested_workers": worker, "repeats": len(group),
                "effective_workers": sorted({record["effective_workers"] for record in group}),
                "median_seconds": median, "minimum_seconds": min(seconds), "maximum_seconds": max(seconds),
                "median_cpu_seconds": statistics.median(record["cpu_seconds"] for record in group),
                "median_average_cpu_cores": statistics.median(record["average_cpu_cores"] for record in group),
                "maximum_peak_rss_bytes": max(record["peak_rss_bytes"] for record in group),
                "encoded_windows": group[0]["work"]["encoded_windows"],
                "encoded_windows_per_second_at_median": group[0]["work"]["encoded_windows"] / median,
                "scientific_output_bytes": group[0]["work"]["scientific_output_bytes"],
            })
        baseline = next((value["median_seconds"] for value in frame if value["requested_workers"] == 1), None)
        for value in frame:
            value["speedup_vs_one_worker_median"] = baseline / value["median_seconds"] if baseline else None
        summaries.extend(frame)
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "experiments/geometry_direction/protocol.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/geometry-direction")
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/filang")
    parser.add_argument("--out", type=Path, required=True, help="fresh benchmark directory, normally under runs/")
    parser.add_argument("--workers", default="1,10", help="comma-separated matched worker counts (default: 1,10)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeframes", default="15", help="comma-separated minutes or all (default: 15)")
    parser.add_argument("--memory-mib", type=int, default=4096)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100 or args.memory_mib < 16:
        parser.error("repeats must be 1..100 and memory-mib at least 16")
    workers = comma_integers(args.workers, "workers", 1, 1024)
    protocol, data_dir, binary = args.protocol.resolve(), args.data_dir.resolve(), args.binary.resolve()
    config = load_protocol(protocol)
    if sorted(config["bars"]) != list(range(2, 11)) or sorted(config["modes"]) != ["oriented", "unoriented"]:
        raise ValueError("matched benchmark requires every 2..10-bar window and both geometry modes")
    minutes = (sorted(config["timeframes_minutes"]) if args.timeframes == "all"
               else comma_integers(args.timeframes, "timeframes", 1, 1440))
    if any(minute not in config["timeframes_minutes"] for minute in minutes):
        raise ValueError("selected timeframe is not declared in the protocol")
    provenance, sources = prepared_sources(config, protocol, data_dir, minutes)
    engine_sha256, protocol_sha256 = digest(binary), digest(protocol)
    provenance_sha256 = digest(data_dir / "provenance.json")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "protocol.json").write_bytes(protocol.read_bytes())
    (out / "data-provenance.json").write_bytes(json_bytes(provenance))
    records = []
    references = {}
    order = []
    for repeat in range(1, args.repeats + 1):
        # Rotate which worker count goes first; retain deterministic order and
        # report it. The benchmark makes no claim that filesystem caches are cold.
        rotation = (repeat - 1) % len(workers)
        worker_order = workers[rotation:] + workers[:rotation]
        for minute in minutes:
            for worker in worker_order:
                order.append((repeat, minute, worker))
    report = {
        "version": 1, "status": "RUNNING", "experiment_id": config.get("experiment_id"),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
        "python": sys.version, "python_executable": sys.executable,
        "git_head": git_value("rev-parse", "HEAD"), "git_status": git_value("status", "--short"),
        "benchmark_script_sha256": digest(Path(__file__)),
        "measurement_runner_sha256": digest(Path(__file__).with_name("run_direction_experiment.py")),
        "binary": str(binary), "binary_sha256": engine_sha256,
        "protocol_sha256": protocol_sha256, "data_provenance_sha256": provenance_sha256,
        "sources": [{name: sources[minute][name] for name in (
            "minutes", "source_sha256", "csv", "csv_sha256", "csv_bytes", "rows")}
            for minute in minutes],
        "bars": config["bars"], "modes": config["modes"], "timeframes_minutes": minutes,
        "worker_counts": workers, "repeats_per_worker_and_timeframe": args.repeats,
        "memory_mib": args.memory_mib,
        "measurement_policy": "Per-child wall, CPU and peak RSS include CSV read, canonical encoding, grouped counts, hashing and durable native artifacts. Input validation and full output hashing/parity are outside the timer. Every run is fresh; no cache flushing; worker ordering rotates by repeat.",
        "equivalence_scope": "Actual SHA-256 and byte length of every task's complete patterns.tsv and events.tsv, plus exact physical work counters. Context and timing metadata are excluded. Independent mathematical/statistical verification is performed by verify_direction.py outside this benchmark.",
        "all_repeat_outputs_retained": True,
        "execution_order": [{"repeat": repeat, "minutes": minute, "workers": worker}
                            for repeat, minute, worker in order],
        "reference_artifacts": references, "records": records,
    }
    save_report(out / "benchmark.json", report)
    try:
        for repeat, minute, worker in order:
            # Detect concurrent source/binary/protocol changes before and after
            # each measurement. These checks are outside the native timer.
            source = sources[minute]
            if (digest(binary) != engine_sha256 or digest(protocol) != protocol_sha256
                    or digest(Path(source["csv"])) != source["csv_sha256"]):
                raise ValueError("benchmark inputs changed before a matched run")
            name = f"repeat{repeat:02}-{minute}m-workers{worker:04}"
            destination = out / "runs" / name
            command = [str(binary), "geometry-direction-sweep", "--data", source["csv"],
                       "--out", str(destination), "--interval-seconds", str(minute * 60),
                       "--bars", ",".join(map(str, config["bars"])), "--modes", ",".join(config["modes"]),
                       "--workers", str(worker), "--memory-mib", str(args.memory_mib)]
            for key in ("history_start", "validation_start", "test_start", "end"):
                command.extend(["--" + key.replace("_", "-"), config[key]])
            record = measured(command, out / "logs" / f"{name}.log")
            if (digest(binary) != engine_sha256 or digest(protocol) != protocol_sha256
                    or digest(Path(source["csv"])) != source["csv_sha256"]):
                raise ValueError("benchmark inputs changed during a matched run")
            native, artifacts, work = native_work(destination, config, source, engine_sha256, worker)
            frame = str(minute)
            equivalent_digest = hashlib.sha256(json_bytes(artifacts)).hexdigest()
            if frame not in references:
                references[frame] = {"reference_run": name, "artifact_sha256": equivalent_digest, **artifacts}
            elif (references[frame]["files"] != artifacts["files"]
                  or references[frame]["tasks"] != artifacts["tasks"]):
                raise ValueError(f"scientific output differs across matched runs: {name}")
            cpu_seconds = record["user_cpu_seconds"] + record["system_cpu_seconds"]
            record.update({
                "run": name, "repeat": repeat, "minutes": minute, "requested_workers": worker,
                "effective_workers": native["effective_workers"], "fresh_measurement": True,
                "cpu_seconds": cpu_seconds, "average_cpu_cores": cpu_seconds / record["elapsed_seconds"],
                "native_manifest_sha256": digest(destination / "manifest.json"),
                "artifact_equivalence_sha256": equivalent_digest,
                "reference_run": references[frame]["reference_run"], "equivalence_status": "PASS",
                "work": work,
            })
            records.append(record)
            report["summaries"] = aggregate(records, minutes, workers)
            save_report(out / "benchmark.json", report)
            print(json.dumps({"run": name, "status": "PASS", "seconds": record["elapsed_seconds"],
                              "peak_rss_bytes": record["peak_rss_bytes"], "encoded_windows": work["encoded_windows"],
                              "scientific_output_bytes": work["scientific_output_bytes"],
                              "equivalence_sha256": equivalent_digest}), flush=True)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        save_report(out / "benchmark.json", report)
        raise
    report["status"] = "PASS"
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["all_scientific_outputs_byte_identical_within_timeframe"] = True
    save_report(out / "benchmark.json", report)
    print(json.dumps({"status": "PASS", "benchmark": str(out / "benchmark.json"),
                      "summaries": report["summaries"]}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        print("direction benchmark: " + str(error), file=sys.stderr)
        raise SystemExit(2)
