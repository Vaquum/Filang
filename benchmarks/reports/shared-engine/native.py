"""Interleave matched native baseline and candidate workloads and record all trials."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
RSS_SCALE = 1 if sys.platform == "darwin" else 1024


def measure(command):
    with tempfile.TemporaryFile() as out:
        start = time.monotonic_ns()
        with subprocess.Popen(command, stdout=out) as child:
            _, status, ru = os.wait4(child.pid, 0)
            elapsed = (time.monotonic_ns() - start) / 1e6
            child.returncode = os.waitstatus_to_exitcode(status)
            if child.returncode:
                raise subprocess.CalledProcessError(child.returncode, command)
        out.seek(0)
        return elapsed, ru.ru_maxrss * RSS_SCALE, out.read()


def study(binary, recording, calendar, wires):
    digest = sha256()
    start = time.monotonic_ns()
    with subprocess.Popen(
        [binary, "study", "--bars", recording, "--calendar", calendar, "--interval-ms", "900000"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as child:
        assert json.loads(child.stdout.readline()) == {"ready": "filang-study-v1"}
        ready = time.monotonic_ns()
        for wire in wires:
            child.stdin.write(wire.encode() + b"\n")
            child.stdin.flush()
            reply = child.stdout.readline()
            if not reply.startswith(b'{"engine":'):
                raise ValueError(reply.decode())
            digest.update(reply)
        last = time.monotonic_ns()
        child.stdin.close()
        _, status, ru = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        if child.returncode:
            raise subprocess.CalledProcessError(child.returncode, child.args)
    return dict(cold_ms=(ready - start) / 1e6, warm_ms=(last - ready) / 1e6,
                peak_rss=ru.ru_maxrss * RSS_SCALE, result_sha256=digest.hexdigest())


def geometry(binary, config, output):
    prepared, resident_prepared, _ = measure(
        [binary, "geometry-prepare", "--config", config, "--out", output,
         "--workers", "1", "--capture", "true"])
    swept, resident_swept, _ = measure(
        [binary, "geometry-sweep", "--config", config, "--out", output,
         "--workers", "1", "--resume", "true", "--capture", "true"])
    best = (output / "best-geometry.tsv").read_bytes()
    return dict(prepare_ms=prepared, sweep_ms=swept, prepare_rss=resident_prepared,
                sweep_rss=resident_swept, best_sha256=sha256(best).hexdigest())


def compile_key_probe(toolchain, release, out):
    lib = release / "libfilang.rlib"
    subprocess.run(
        ["rustc", "+" + toolchain, "--edition", "2021", "-O", "--extern", f"filang={lib}",
         "-L", f"dependency={release / 'deps'}", ROOT / "bench_price_keys.rs", "-o", out],
        check=True,
    )


def gates(samples, fields):
    prior, current = samples["base"], samples["candidate"]
    verdicts = {}
    for field in fields:
        initial = sorted(row[field] for row in prior)
        p75 = statistics.quantiles(initial, n=4, method="inclusive")[2]
        candidate = statistics.median(row[field] for row in current)
        verdicts[field] = {"base_median": statistics.median(initial),
                           "base_p75": p75, "candidate_median": candidate,
                           "passed": candidate <= p75}
    return verdicts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--study-csv", required=True, type=Path)
    parser.add_argument("--geometry-csv", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--toolchain", default="1.100.0")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.rounds < 5:
        parser.error("at least five rounds")
    wires = [q["wire"] for q in json.loads(args.corpus.read_text())]
    roots = {"base": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    release = {name: repo / "target/release" for name, repo in roots.items()}
    calendar = ROOT.parents[2] / "study/catalogue/nyse.tsv"
    samples = {"study": {}, "geometry": {}, **{f"key_{n}": {} for n in (2, 4, 10)}}
    for group in samples.values():
        group.update(base=[], candidate=[])
    with tempfile.TemporaryDirectory(prefix="filang-bench-") as temp:
        temp = Path(temp)
        config = temp / "smoke.cfg"
        subprocess.run([release["base"] / "filang", "geometry-example", "--out", config,
                        "--profile", "smoke", "--data", args.geometry_csv.resolve(),
                        "--start", "2024-01-01", "--end", "2025-01-01"],
                       check=True, stdout=subprocess.DEVNULL)
        for side in release:
            compile_key_probe(args.toolchain, release[side], temp / f"key-{side}")
        for i in range(args.rounds):
            for side in (("base", "candidate") if i % 2 == 0 else ("candidate", "base")):
                print(f"round {i + 1}/{args.rounds} {side}", file=sys.stderr, flush=True)
                binary = release[side] / "filang"
                for width in (2, 4, 10):
                    _, rss, output = measure([temp / f"key-{side}", args.geometry_csv,
                                              "14400", str(width), "oriented", "100"])
                    row = json.loads(output)
                    row["peak_rss"] = rss
                    samples[f"key_{width}"][side].append(row)
                samples["geometry"][side].append(
                    geometry(binary, config, temp / f"run-{i}-{side}"))
                samples["study"][side].append(study(binary, args.study_csv, calendar, wires))
    parity = {}
    for kind, pair in samples.items():
        field = "result_sha256" if kind == "study" else "best_sha256" if kind == "geometry" else "key_digest"
        parity[kind] = len({row[field] for trials in pair.values() for row in trials}) == 1
    criteria = {
        kind: gates(pair, ("cold_ms", "warm_ms", "peak_rss") if kind == "study"
                    else ("prepare_ms", "sweep_ms", "prepare_rss", "sweep_rss") if kind == "geometry"
                    else ("seconds", "peak_rss"))
        for kind, pair in samples.items()
    }
    args.out.write_text(json.dumps({"trials": samples, "parity": parity, "gates": criteria}, indent=2) + "\n")
    assert all(parity.values()), parity


if __name__ == "__main__":
    main()
