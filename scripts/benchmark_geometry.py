#!/usr/bin/env python3
"""Matched geometry sweep timings with independent verification outside the timer.

Every mode uses exactly the same data, full pattern universe, qualifiers, rules,
costs and output policy. Logical addresses and physical metric work are reported
separately. Use --capture on bounded domains to independently replay every region;
summary mode verifies all banks/coverage and every retained task winner only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(command, stdout, stderr):
    with stdout.open("w") as out, stderr.open("w") as err:
        start = time.perf_counter()
        peak_rss = cpu_seconds = None
        with subprocess.Popen(command, stdout=out, stderr=err) as process:
            if hasattr(os, "wait4"):
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = (os.WEXITSTATUS(status) if os.WIFEXITED(status)
                                      else -os.WTERMSIG(status))
                # Darwin reports bytes; Linux reports KiB. This is per child,
                # so a preceding verifier cannot contaminate the next sweep.
                peak_rss = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
                cpu_seconds = usage.ru_utime + usage.ru_stime
            else:
                process.wait()
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        return time.perf_counter() - start, peak_rss, cpu_seconds


def same_metrics(left, right):
    if len(left) != len(right):
        return False
    return all((a is None and b is None) or
               (a is not None and b is not None and
                math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9))
               for a, b in zip(left, right))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--binary", default="target/release/filang")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--ledger", choices=("auto", "python", "c"), default="auto")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100 or not 1 <= args.workers <= 1024:
        parser.error("repeats must be 1..100 and workers 1..1024")
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    binary = Path(args.binary).resolve()
    config = Path(args.config).resolve()
    config_text = config.read_text()
    (root / "experiment.cfg").write_text(config_text)
    plan = json.loads(subprocess.check_output(
        [str(binary), "geometry-inspect", "--config", str(config)], text=True))
    logical = int(plan["requested_strategy_addresses"])
    modes = [
        ("leaf_scalar", "scalar", False, 1),
        ("certificates_scalar", "scalar", True, 1),
        ("certificates_native", "auto", True, 1),
        ("certificates_parallel", "auto", True, args.workers),
    ]
    verifier = Path(__file__).resolve().with_name("verify_geometry.py")
    records = []
    reference_best = None
    for label, backend, certificates, workers in modes:
        for repeat in range(1, args.repeats + 1):
            name = f"{label}-{repeat}"
            destination = root / name
            command = [
                str(binary), "geometry-sweep", "--config", str(config),
                "--out", str(destination), "--backend", backend,
                "--workers", str(workers), "--certificates",
                str(certificates).lower(), "--capture", str(args.capture).lower(),
            ]
            seconds, peak_rss, cpu_seconds = run(
                command, root / f"{name}.stdout.log", root / f"{name}.stderr.log")
            summary = json.loads((destination / "summary.json").read_text())
            if (not summary["coverage_complete"] or
                    int(summary["resolved_strategy_addresses"]) != logical):
                raise ValueError("incomplete matched benchmark: " + name)
            verification_seconds, _, _ = run(
                [sys.executable, str(verifier), "--run", str(destination),
                 "--ledger", args.ledger],
                root / f"{name}.verification.stdout.log",
                root / f"{name}.verification.stderr.log")
            verification = json.loads(
                (destination / "verification" / "geometry.json").read_text())
            if verification["status"] != "PASS":
                raise ValueError("independent verification failed: " + name)
            best = summary["best"]["metrics"]
            if reference_best is None:
                reference_best = best
            elif not same_metrics(best, reference_best):
                raise ValueError("matched best metrics differ: " + name)
            records.append({
                "mode": label, "repeat": repeat, "seconds": seconds,
                "peak_rss_bytes": peak_rss, "cpu_seconds": cpu_seconds,
                "average_cpu_cores": cpu_seconds / seconds if cpu_seconds is not None else None,
                "verification_seconds_outside_timer": verification_seconds,
                "backend": summary["backend"], "workers": workers,
                "logical_addresses": str(logical),
                "metric_regions": summary["metric_regions_evaluated"],
                "tree_node_pairs": summary["tree_node_pairs_visited"],
                "certified_nonleaf_products": summary["certified_nonleaf_products"],
                "signature_pair_products": summary["signature_pair_products_resolved"],
                "result_digest": summary["result_digest"],
                "best_metrics": best,
                "verification": str(destination / "verification" / "geometry.json"),
                "verification_sha256": digest(destination / "verification" / "geometry.json"),
                "all_captured_regions_verified": verification.get(
                    "all_captured_region_masks_metrics_and_coverage_checked", False),
                "command": command,
            })
            (root / "records.json").write_text(json.dumps(records, indent=2) + "\n")
            print(f"{name}: {seconds:.6f}s; {summary['metric_regions_evaluated']} physical metric regions", flush=True)
    medians = {
        label: statistics.median(r["seconds"] for r in records if r["mode"] == label)
        for label, *_ in modes
    }
    baseline = medians["leaf_scalar"]
    result = {
        "version": 1, "status": "PASS", "platform": platform.platform(),
        "machine": platform.machine(), "logical_cpus": os.cpu_count(),
        "binary_sha256": digest(binary), "config_sha256": digest(config),
        "capture": args.capture, "logical_addresses": str(logical),
        "verification_scope": ("all captured regions and full logical coverage"
                               if args.capture else
                               "all bank memberships/full coverage and every retained task winner; not every region metric"),
        "median_seconds": medians,
        "peak_rss_bytes": {
            label: max((r["peak_rss_bytes"] for r in records
                        if r["mode"] == label and r["peak_rss_bytes"] is not None), default=None)
            for label, *_ in modes
        },
        "speedup_vs_leaf_scalar": {name: baseline / value for name, value in medians.items()},
        "records": records,
        "interpretation": "logical addresses are exactly covered programs, not independent physical backtests; costs of setup, hashing and durable output are included",
    }
    (root / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "median_seconds": medians,
                      "speedup_vs_leaf_scalar": result["speedup_vs_leaf_scalar"]}))


if __name__ == "__main__":
    main()
