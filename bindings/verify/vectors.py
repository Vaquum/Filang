"""Run the canonical Filang vectors through an installed Python wheel or the CLI."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
AXES = ("volume", "trades", "delta", "size", "imbalance")
INTERVAL = 900000


def expect(record, reading, dimensions):
    base = record["chained" if reading == "chained" else "as_recorded"]
    parts = [record["parts"][axis] for axis in dimensions]
    return base, None if None in parts else "|".join([base, *parts])


def vectors():
    for source in ("chained", "dimension"):
        data = json.loads((ROOT / f"study/verify/{source}-vectors.json").read_text())
        for vector in data["vectors"]:
            vector.setdefault("parts", {})
            for reading in ("recorded", "chained"):
                for mask in range(1 << len(vector["parts"])):
                    dims = tuple(axis for i, axis in enumerate(AXES) if mask & (1 << i))
                    yield vector, reading, dims


def radius_vectors():
    return json.loads((ROOT / "study/verify/radius-vectors.json").read_text())["vectors"]


def expected_radius(distances, radius):
    outcome = [None if cost is None else cost <= radius for cost in distances]
    counts = dict(matched=outcome.count(True), false_count=outcome.count(False),
                  unknown=outcome.count(None))
    slots = [slot for slot, value in enumerate(outcome) if value]
    histogram = [[cost, distances.count(cost)] for cost in sorted(
        {cost for cost in distances if cost is not None and cost <= radius}
    )]
    return counts, slots, outcome, histogram


def verify_python():
    from filang_engine import Engine, FilangError

    with Engine() as engine:
        assert engine.version()["abi"] == 1
        last = None
        total = 0
        for vector, reading, dims in vectors():
            bars = vector["bars"]
            if last is not bars:
                assert engine.load(bars)["slots"] == len(bars)
                last = bars
            base, expected = expect(vector, reading, dims)
            seen = engine.at(len(bars) - 1, len(bars), reading=reading, dimensions=dims)
            assert (None if seen is None else seen["code"]) == expected, vector["name"]
            if seen:
                assert engine.inspect(expected) == seen
                assert len(seen["words"]) == 4 + len(dims)
                assert engine.counts(expected, reading=reading) == {
                    "matched": 1, "false_count": 0, "unknown": len(bars) - 1
                }
                assert engine.positions(expected, reading=reading) == [len(bars) - 1]
            else:
                # Turn on an unknown dimension using a valid order on it.
                fallback = [base, *(f"{d}:" + ",".join("0" for _ in bars)
                    + ("/0" if d in ("delta", "imbalance") else "") for d in dims)]
                assert engine.counts("|".join(fallback), reading=reading) == {
                    "matched": 0, "false_count": 0, "unknown": len(bars)
                }
            total += 1
        try:
            engine.inspect("g1:o:0,1,1,2,u")
        except FilangError:
            pass
        else:
            raise AssertionError("accepted an oriented doji as upward")
        for case in radius_vectors():
            engine.load(case["bars"])
            options = dict(reading=case["reading"], oriented=case["oriented"],
                           dimensions=case["dimensions"])
            assert engine.at(case["anchor"], case["width"], **options)["code"] == case["code"]
            for radius in (0, 1, 2, 4, 8, 16, 64):
                kwargs = dict(reading=case["reading"], radius=radius)
                counts, slots, outcomes, histogram = expected_radius(case["distances"], radius)
                assert engine.counts(case["code"], **kwargs) == counts
                assert engine.positions(case["code"], **kwargs) == slots
                assert engine.classify(case["code"], **kwargs) == outcomes
                assert engine.neighbourhood(case["code"], **kwargs) == {
                    "counts": counts, "by_distance": histogram
                }
                total += 1
            op = "exact_g1" if case["reading"] == "recorded" else "chained_g1"
            source = f'on BTCUSDT 15m\nfind {op}("{case["code"]}"'
            engine.load_csv(recording_csv(case["bars"]), INTERVAL)
            assert engine.study(source + ", radius: 0)") == engine.study(source + ")")
            result = engine.study(source + ", radius: 2)")["results"][0]
            _, slots, _, _ = expected_radius(case["distances"], 2)
            assert result["anchors"] == [(slot + 1) * INTERVAL for slot in slots]
    print(f"Python wheel: {total} vector cases")


def recording_csv(rows):
    ext = len(rows[0]) == 7
    head = "open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count" if ext \
        else "open_ms,open,high,low,close,volume"
    def decimal(cents):
        return f"{cents // 100}.{cents % 100:02d}"
    lines = [head]
    for i, row in enumerate(rows):
        if row is None:
            continue
        lines.append(",".join([str(i * INTERVAL), *(decimal(x) for x in row[:4]), "0",
                               *(str(x).lower() for x in row[4:])]))
    return "\n".join(lines) + "\n"


def verify_cli(binary):
    with tempfile.TemporaryDirectory() as directory:
        csv = Path(directory) / "vector.csv"
        last = None
        total = 0
        def run(operation, *args):
            return json.loads(subprocess.check_output(
                [binary, "engine", "--operation", operation, *map(str, args)]
            ))
        for vector, reading, dims in vectors():
            bars = vector["bars"]
            if last is not bars:
                csv.write_text(recording_csv(bars))
                last = bars
            _, expected = expect(vector, reading, dims)
            common = ["--bars", csv, "--interval-ms", INTERVAL, "--reading", reading]
            seen = run("at", *common, "--end-slot", len(bars) - 1, "--width", len(bars),
                       "--dimensions", ",".join(dims))
            assert (None if seen is None else seen["code"]) == expected, vector["name"]
            if seen:
                assert run("inspect", "--pattern", expected) == seen
                assert run("counts", *common, "--pattern", expected) == {
                    "matched": 1, "false_count": 0, "unknown": len(bars) - 1
                }
            total += 1
        for case in radius_vectors():
            csv.write_text(recording_csv(case["bars"]))
            common = ["--bars", csv, "--interval-ms", INTERVAL, "--reading",
                      case["reading"], "--pattern", case["code"]]
            for radius in (0, 1, 2, 4, 8, 16, 64):
                counts, slots, outcomes, histogram = expected_radius(case["distances"], radius)
                assert run("counts", *common, "--radius", radius) == counts
                assert run("positions", *common, "--radius", radius) == slots
                assert run("classify", *common, "--radius", radius) == outcomes
                assert run("neighbourhood", *common, "--radius", radius) == {
                    "counts": counts, "by_distance": histogram
                }
                total += 1
    print(f"CLI: {total} vector cases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli")
    args = parser.parse_args()
    if args.cli:
        verify_cli(args.cli)
    else:
        verify_python()
