#!/usr/bin/env python3
"""Reproduce the pinned five-timeframe, 2..10-bar Bitcoin direction experiment.

Stages are explicit so a long independent audit can resume after the fast native
map. Native elapsed time includes reading, canonicalization and durable outputs;
data download, build, analysis and independent verification are timed separately.
Use a fresh output directory for a fresh timing measurement.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from prepare_direction import load_protocol
from prepare_hf import digest, publish


ROOT = Path(__file__).resolve().parents[1]


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def measured(command: list[str], log: Path) -> dict:
    """Measure this child only. Darwin reports ru_maxrss in bytes, Linux in KiB."""
    if not hasattr(os, "wait4"):
        raise RuntimeError("per-child CPU/RSS measurement currently requires macOS or Linux")
    log.parent.mkdir(parents=True, exist_ok=True)
    begin = time.perf_counter()
    with log.open("w") as output:
        child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    result = {
        "command": command, "exit_code": child.returncode,
        "elapsed_seconds": time.perf_counter() - begin,
        "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
        "peak_rss_bytes": int(usage.ru_maxrss * (1 if platform.system() == "Darwin" else 1024)),
        "log": str(log), "log_sha256": digest(log)
    }
    if child.returncode:
        raise RuntimeError(f"stage failed with code {child.returncode}; see {log}")
    return result


def stage_done(run: Path, name: str, value: dict) -> None:
    # Timing receipts can be replaced when explicitly resuming a stage; native
    # scientific artifacts retain their stricter context and checksum contract.
    path = run / "timings" / (name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".pending")
    temp.write_bytes(json_bytes(value))
    temp.replace(path)
    print(json.dumps({"stage": name, "status": "PASS", **{
        k: value[k] for k in ("elapsed_seconds", "peak_rss_bytes") if k in value}}), flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, default=ROOT / "experiments/geometry_direction/protocol.json")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data/geometry-direction")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--stage", choices=("all", "prepare", "map", "analyze", "verify"), default="all")
    p.add_argument("--workers", type=int, default=min(os.cpu_count() or 1, 1024))
    p.add_argument("--memory-mib", type=int, default=4096)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--binary", type=Path, default=ROOT / "target/release/filang")
    p.add_argument("--cargo", default=shutil.which("cargo") or "cargo")
    p.add_argument("--verify-sample-per-task", type=int, default=0,
                   help="positive value requests a labeled sample audit; zero is exhaustive")
    args = p.parse_args()
    if not 1 <= args.workers <= 1024 or args.memory_mib < 16 or args.verify_sample_per_task < 0:
        p.error("invalid worker, memory or sample bound")
    config = load_protocol(args.protocol)
    run, data_dir = args.out.resolve(), args.data_dir.resolve()
    run.mkdir(parents=True, exist_ok=True)
    protocol = args.protocol.resolve()
    publish(run / "protocol.json", protocol.read_bytes())
    logs = run / "logs"
    logs.mkdir(exist_ok=True)
    stages = ("prepare", "map", "analyze", "verify") if args.stage == "all" else (args.stage,)
    if "prepare" in stages:
        stage_done(run, "prepare", measured([
            sys.executable, str(ROOT / "scripts/prepare_direction.py"),
            "--protocol", str(protocol), "--out", str(data_dir)], logs / "prepare.log"))
    if "map" in stages:
        if not args.skip_build:
            stage_done(run, "build", measured([
                args.cargo, "+1.63.0", "build", "--release", "--locked", "--offline"], logs / "build.log"))
        binary = args.binary.resolve()
        provenance_path = data_dir / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        if provenance["protocol_sha256"] != digest(protocol):
            raise ValueError("prepared input protocol differs from run protocol")
        identity = {"version": 1, "protocol_sha256": digest(protocol), "engine_sha256": digest(binary),
                    "data_provenance_sha256": digest(provenance_path)}
        publish(run / "experiment.identity.json", json_bytes(identity))
        for source in provenance["sources"]:
            minutes = source["minutes"]
            csv_path = data_dir / f"{minutes}m" / "ohlcv.csv"
            if digest(csv_path) != source["csv_sha256"]:
                raise ValueError("prepared CSV no longer matches source provenance")
            destination = run / f"{minutes}m"
            cmd = [str(binary), "geometry-direction-sweep", "--data", str(csv_path),
                   "--out", str(destination), "--interval-seconds", str(minutes * 60),
                   "--bars", ",".join(map(str, config["bars"])), "--modes", ",".join(config["modes"]),
                   "--workers", str(args.workers), "--memory-mib", str(args.memory_mib)]
            for key in ("history_start", "validation_start", "test_start", "end"):
                cmd.extend(["--" + key.replace("_", "-"), config[key]])
            if args.resume and destination.exists():
                cmd.extend(["--resume", "true"])
            result = measured(cmd, logs / f"native-{minutes}m.log")
            native = json.loads((destination / "manifest.json").read_text())
            if native["status"] != "COMPLETE" or native["completed_tasks"] != len(config["bars"]) * len(config["modes"]):
                raise ValueError("native mapping is incomplete")
            result["native_manifest_sha256"] = digest(destination / "manifest.json")
            result["minutes"] = minutes
            result["requested_workers"] = args.workers
            result["effective_workers"] = native["effective_workers"]
            result["resumed_tasks"] = native["resumed_tasks"]
            result["fresh_measurement"] = native["resumed_tasks"] == 0
            stage_done(run, f"native-{minutes}m", result)
        machine = {"version": 1, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                   "system": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                   "python": sys.version, "python_executable": sys.executable,
                   "git_head": git_value("rev-parse", "HEAD"), "git_status": git_value("status", "--short"),
                   "runner_sha256": digest(Path(__file__)), "protocol_sha256": digest(protocol),
                   "engine_sha256": digest(binary), "requested_workers": args.workers,
                   "measurement_policy": "Native child includes CSV, encoding, mapping and durable artifacts. Build/preparation/analysis/verification measured separately."}
        (run / "environment.json").write_bytes(json_bytes(machine))
    if "analyze" in stages:
        stage_done(run, "analysis", measured([
            sys.executable, str(ROOT / "scripts/analyze_direction.py"), "--runs", str(run),
            "--out", str(run / "analysis"), "--protocol", str(protocol)], logs / "analysis.log"))
    if "verify" in stages:
        cmd = [sys.executable, str(ROOT / "scripts/verify_direction.py"), "--runs", str(run),
               "--out", str(run / "verification.json")]
        if (run / "analysis/analysis.json").exists():
            cmd.extend(["--analysis", str(run / "analysis")])
        if args.verify_sample_per_task:
            cmd.extend(["--sample-per-task", str(args.verify_sample_per_task)])
        stage_done(run, "verification", measured(cmd, logs / "verification.log"))
    print(json.dumps({"status": "PASS", "run": str(run), "stages": list(stages)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print("direction experiment: " + str(error), file=sys.stderr)
        raise SystemExit(2)
