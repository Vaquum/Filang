"""Reproduce the seven paired native geometry runs declared in Filang PR #35."""

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


SOURCE_SHA256 = "21df2ed15f787479b3e871be0048b5721cd18e7e085881e4175975c8d056889a"
FLAGS = [
    "--interval-seconds", "900", "--history-start", "2025-01-01",
    "--validation-start", "2025-03-01", "--test-start", "2025-05-01",
    "--end", "2025-06-01", "--bars", "2,3,4,5,6,7,8,9,10",
    "--modes", "oriented,unoriented", "--workers", "1",
]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, path):
    header, *rows = source.read_text().splitlines()
    if header != "open_ms,open,high,low,close,volume" or len(rows) != 14_496:
        raise ValueError("Expected the pinned 14,496-row study recording")
    with path.open("w") as stream:
        stream.write("timestamp,open,high,low,close,volume\n")
        for row in rows:
            opened, fields = row.split(",", 1)
            seconds, remainder = divmod(int(opened), 1000)
            if remainder:
                raise ValueError("Open time is off the seconds grid")
            stream.write(f"{seconds},{fields}\n")


def run(binary, source):
    with tempfile.TemporaryDirectory(prefix="geometry-run-") as task:
        directory = Path(task) / "result"
        command = [
            "/usr/bin/time", "-l", str(binary), "geometry-direction-sweep",
            "--data", str(source), "--out", str(directory), *FLAGS,
        ]
        start = time.perf_counter()
        proc = subprocess.run(command, capture_output=True, text=True)
        wall = time.perf_counter() - start
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        peak = re.search(r"^\s*(\d+)\s+maximum resident set size\s*$", proc.stderr, re.MULTILINE)
        if peak is None:
            raise RuntimeError("macOS time did not report peak RSS")
        files = [*directory.rglob("events.tsv"), *directory.rglob("patterns.tsv")]
        if len(files) != 36:
            raise RuntimeError(f"Expected 36 scientific output files, got {len(files)}")
        digests = {str(path.relative_to(directory)): sha256(path) for path in sorted(files)}
        return {"wall_seconds": wall, "peak_rss_bytes": int(peak[1])}, digests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["baseline", "candidate", "input", "out"]:
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    source_hash = sha256(args.input)
    if source_hash != SOURCE_SHA256:
        parser.error("Input differs from the preregistered recording")
    if platform.system() != "Darwin":
        parser.error("This measurement uses macOS time and peak resident bytes")

    binary = {name: getattr(args, name).resolve(strict=True) for name in ("baseline", "candidate")}
    report = {
        "workload": "geometry-direction-sweep",
        "flags": FLAGS,
        "recording_sha256": source_hash,
        "machine": subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip(),
        "platform": platform.platform(),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "binary_sha256": {name: sha256(path) for name, path in binary.items()},
        "pairs": [],
    }
    reference = None
    equal = True
    with tempfile.TemporaryDirectory(prefix="geometry-tape-") as folder:
        source = Path(folder) / "open-seconds.csv"
        prepare(args.input, source)
        report["converted_sha256"] = sha256(source)
        for i in range(7):
            order = ("candidate", "baseline") if i % 2 else ("baseline", "candidate")
            pair = {"order": order}
            for name in order:
                pair[name], digests = run(binary[name], source)
                if reference is None:
                    reference = digests
                equal = equal and reference == digests
            report["pairs"].append(pair)

    medians = {}
    for metric in ("wall_seconds", "peak_rss_bytes"):
        medians[metric] = {name: statistics.median(pair[name][metric] for pair in report["pairs"])
                           for name in binary}
        medians[metric]["candidate_over_baseline"] = medians[metric]["candidate"] / medians[metric]["baseline"]
    report["median"] = medians
    report["all_output_digests_equal"] = equal
    report["reference_output_sha256"] = reference
    report["supported"] = equal and all(m["candidate_over_baseline"] <= 1.05 for m in medians.values())
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(medians, indent=2))
    print(f"Scientific output digest parity: {equal}")
    return 0 if report["supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
