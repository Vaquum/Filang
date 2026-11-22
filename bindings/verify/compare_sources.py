"""Compare exact g1 identities on two declared recordings at common grid closes."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from filang_engine import Engine


def bounds(text, dimensions):
    rows = csv.DictReader(text.splitlines())
    if dimensions and not {"volume", "taker_buy_volume", "trade_count"}.issubset(rows.fieldnames):
        raise ValueError("both recordings need all three counters for dimension parity")
    start = int(next(rows)["open_ms"])
    end = start
    for row in rows:
        end = int(row["open_ms"])
    return start, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--interval-ms", type=int, default=900000)
    parser.add_argument("--width", type=int, default=2)
    parser.add_argument("--reading", choices=("recorded", "chained"), default="recorded")
    parser.add_argument("--dimensions", default="")
    args = parser.parse_args()
    dimensions = [axis for axis in args.dimensions.split(",") if axis]
    raws = [path.read_bytes() for path in (args.left, args.right)]
    texts = [raw.decode() for raw in raws]
    (left_start, left_end), (right_start, right_end) = [bounds(text, dimensions) for text in texts]
    interval = args.interval_ms
    start = max(left_start, right_start) + (args.width - 1) * interval
    end = min(left_end, right_end)
    if start > end:
        parser.error("the recordings have no complete common windows")
    options = {"reading": args.reading, "dimensions": dimensions}
    equal = 0
    both_unknown = 0
    different = 0
    examples = []
    with Engine() as left, Engine() as right:
        left.load_csv(texts[0], interval)
        right.load_csv(texts[1], interval)
        for t in range(start, end + 1, interval):
            a = left.at((t - left_start) // interval, args.width, **options)
            b = right.at((t - right_start) // interval, args.width, **options)
            if a is None and b is None:
                both_unknown += 1
            elif a == b:
                equal += 1
            else:
                different += 1
                if len(examples) < 5:
                    examples.append({"close_ms": t + interval,
                                     "left": a and a["code"], "right": b and b["code"]})
    print(json.dumps({
        "sources_sha256": [hashlib.sha256(raw).hexdigest() for raw in raws],
        "width": args.width, **options, "equal": equal, "both_unknown": both_unknown,
        "different": different, "examples": examples,
    }, indent=2))
    if different:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
