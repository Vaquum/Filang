"""Run the paired adaptive posting benchmarks and preserve every sample."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).with_name("benchmark.rs").resolve()


def compile_probe(checkout, output):
    release = checkout.resolve() / "target/release"
    subprocess.run(
        ["rustc", "+1.100.0", "--edition=2021", "-O", "-C", "panic=abort", "-C", "lto=fat",
         "--extern", f"filang={release / 'libfilang.rlib'}",
         "-L", f"dependency={release / 'deps'}", SOURCE, "-o", output],
        check=True,
    )


def measure(probe, workload, cube):
    with tempfile.TemporaryFile() as out:
        with subprocess.Popen([probe, workload, cube], stdout=out, close_fds=False) as child:
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            if child.returncode:
                raise subprocess.CalledProcessError(child.returncode, child.args)
        out.seek(0)
        result = json.load(out)
    result["peak_rss"] = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    return result


def summary(samples):
    result = {}
    for metric in ("prepare_ms", "count_ms", "peak_rss"):
        baseline = [x[metric] for x in samples["base"]]
        candidate = [x[metric] for x in samples["candidate"]]
        result[metric] = {
            "baseline_median": statistics.median(baseline),
            "baseline_p75": statistics.quantiles(baseline, n=4, method="inclusive")[2],
            "candidate_median": statistics.median(candidate),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("cube", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cases = {key: {"base": [], "candidate": []} for key in ("dense", "2", "4", "24")}
    with tempfile.TemporaryDirectory(prefix="filang-adaptive-") as tmp:
        probes = {side: Path(tmp) / side for side in ("base", "candidate")}
        for side, source in (("base", args.base), ("candidate", args.candidate)):
            compile_probe(source, probes[side])
        for i in range(5):
            order = ("base", "candidate") if i % 2 == 0 else ("candidate", "base")
            for workload, samples in cases.items():
                for side in order:
                    samples[side].append(measure(probes[side], workload, args.cube))
                print(f"Completed {workload} pair {i + 1}", flush=True)
    parity = {
        workload: len({item["receipt"] for side in samples.values() for item in side}) == 1
        for workload, samples in cases.items()
    }
    result = {
        "cube_sha256": hashlib.sha256(args.cube.read_bytes()).hexdigest(),
        "parity": parity,
        "summary": {workload: summary(samples) for workload, samples in cases.items()},
        "samples": cases,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    assert all(parity.values())


if __name__ == "__main__":
    main()
