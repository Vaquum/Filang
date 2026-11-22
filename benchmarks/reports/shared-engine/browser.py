"""Summarize raw browser trials while retaining every latency sample."""

import argparse
import json
import math
from pathlib import Path
import statistics


def p(values, rank):
    return sorted(values)[math.ceil(len(values) * rank) - 1]


def summary(values):
    return {"p50": p(values, 0.5), "p95": p(values, 0.95),
            "p99": p(values, 0.99), "max": max(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trials", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rounds = [json.loads(file.read_text()) for file in sorted(args.trials.glob("trial-*.json"))]
    assert len(rounds) == 5 and all(row["passed"] for row in rounds)
    assert {row["bars"] for row in rounds} == {66000}
    assert all(len(row["edits"]) == 300 for row in rounds)
    assert all(len(row["price"]["base"]) == len(row["price"]["candidate"]) == 400 for row in rounds)
    all_edits = [ms for row in rounds for ms in row["edits"]]
    worker = [ms for row in rounds for ms in row["workerEdits"]]
    base = [sum(row["price"]["base"]) for row in rounds]
    cand = [sum(row["price"]["candidate"]) for row in rounds]
    result = {
        "trials": rounds,
        "edit_ms": summary(all_edits),
        "worker_ms": summary(worker),
        "supported": p(all_edits, 0.95) <= 16.7,
        "cold_load_ms": summary([row["loadMs"] for row in rounds]),
        "peak_wasm_bytes": max(row["memoryBytes"] for row in rounds),
        "price_only_corpus_ms": {
            "base": base, "candidate": cand, "base_p75": p(base, 0.75),
            "candidate_median": statistics.median(cand),
            "supported": statistics.median(cand) <= p(base, 0.75),
        },
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "trials"}))


if __name__ == "__main__":
    main()
