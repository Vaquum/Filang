"""Prove the drop-in Limen geometry feature on original stored kline counters."""

import argparse
from collections import Counter
import csv
import hashlib
from pathlib import Path
import sys

from filang_engine import Engine

STEP = 900000
AXES = ("volume", "trades", "delta", "size", "imbalance")


def load_rows(path):
    rows = []
    start = None
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            t = int(row["open_ms"])
            if start is None:
                start = t
            slot = (t - start) // STEP
            assert t - start == slot * STEP and slot >= len(rows), "invalid candle grid"
            rows.extend([None] * (slot - len(rows)))
            rows.append(tuple(float(row[k]) for k in (
                "open", "high", "low", "close", "volume", "taker_buy_volume", "trade_count"
            )))
    return rows


def order(values):
    levels = sorted(set(values))
    ranks = {value: i for i, value in enumerate(levels)}
    return [ranks[v] for v in values]


def axis_values(bars):
    values = [[] for _ in AXES]
    for _, _, _, _, quote, buy, trades in bars:
        delta = 2 * buy - quote
        row = (quote, trades, delta, quote / trades if trades else None,
               delta / quote if quote else None)
        for column, value in zip(values, row):
            column.append(value)
    return values


def reference(bars, reading, dimensions):
    if None in bars:
        return None
    endpoints = []
    directions = []
    previous = None
    for open_, high, low, close, *_ in bars:
        if reading == "chained" and previous is not None:
            open_ = previous
            high = max(high, open_)
            low = min(low, open_)
        endpoints.extend((low, min(open_, close), max(open_, close), high))
        directions.append("u" if open_ < close else "d" if open_ > close else "z")
        previous = close
    ranks = order(endpoints)
    price = ";".join(",".join([*map(str, ranks[4*i:4*i+4]), direction])
                     for i, direction in enumerate(directions))
    parts = ["g1:o:" + price]
    for axis, column in zip(AXES, axis_values(bars)):
        if axis not in dimensions:
            continue
        if None in column:
            return None
        if axis in ("delta", "imbalance"):
            ranks = order([*column, 0])
            parts.append(axis + ":" + ",".join(map(str, ranks[:-1])) + "/" + str(ranks[-1]))
        else:
            parts.append(axis + ":" + ",".join(map(str, order(column))))
    return "|".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    assert not {"polars", "numpy", "pandas", "torch", "pyarrow"} & sys.modules.keys()
    bars = load_rows(args.csv)
    with Engine() as engine:
        assert engine.load(bars) == {"slots": len(bars)}
        checks = 0
        for reading in ("recorded", "chained"):
            for width in (2, 4, 12):
                for dimensions in ((), ("volume", "delta"), AXES):
                    seen = [None] * (width - 1)
                    seen.extend(reference(bars[end+1-width:end+1], reading, dimensions)
                                for end in range(width - 1, len(bars)))
                    frequency = Counter(seen)
                    unknown = frequency.pop(None, 0)
                    engine.prepare(width, reading=reading, dimensions=dimensions)
                    for code, n in sorted(frequency.items(), key=lambda x: (-x[1], x[0]))[:7]:
                        assert engine.counts(code, reading=reading) == {
                            "matched": n, "false_count": len(bars) - unknown - n,
                            "unknown": unknown,
                        }
                        values = []
                        for start in range(0, len(bars), 4096):
                            values.extend(engine.classify(code, reading=reading, start=start))
                        expected = [None if actual is None else actual == code for actual in seen]
                        assert values == expected
                        checks += 1
                    engine.release(width)
    sha = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    print(f"Limen Python {sys.version.split()[0]}: {checks} full-grid features across "
          f"{len(bars)} slots, CSV SHA-256 {sha}")


if __name__ == "__main__":
    main()
