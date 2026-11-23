"""Check dense, sparse, absent and undefined cases on a large exact grid."""

import json
import math
import time

from filang_engine import Engine

HEIGHT = 66000
GAP = 33000
NO_ACTIVITY = 44000
OUTLIER = 10000
AXES = ("volume", "trades", "delta", "size", "imbalance")


def percentile(values, rank):
    return sorted(values)[math.ceil(len(values) * rank) - 1]


def main():
    bar = [10.0, 11.0, 9.0, 10.0, 16.0, 8.0, 4]
    bars = [bar] * HEIGHT
    bars[GAP] = None
    bars[NO_ACTIVITY] = [*bar[:4], 0, 0, 0]
    bars[OUTLIER] = [10.0, 12.0, 9.0, 11.0, 16.0, 8.0, 4]
    summary = []
    with Engine() as engine:
        engine.load(bars)
        for width in (2, 24, 128):
            start = time.perf_counter_ns()
            engine.prepare(width, dimensions=AXES)
            cold_ms = (time.perf_counter_ns() - start) / 1e6
            dense = engine.at(width - 1, width, dimensions=AXES)["code"]
            sparse = engine.at(OUTLIER, width, dimensions=AXES)["code"]
            unobserved = engine.draw([[1, 2, 1, 2]] * width, axes={
                axis: [0] * width for axis in AXES
            })["code"]
            unknown = width - 1 + 2 * width
            valid = HEIGHT - unknown
            for code, count in [(dense, valid - width), (sparse, 1), (unobserved, 0)]:
                assert engine.counts(code) == {
                    "matched": count, "false_count": valid - count, "unknown": unknown
                }
            assert engine.positions(sparse) == [OUTLIER]
            samples = []
            for _ in range(21):
                start = time.perf_counter_ns()
                engine.counts(dense)
                samples.append((time.perf_counter_ns() - start) / 1e6)
            summary.append({"width": width, "valid": valid, "dense": valid - width,
                            "sparse": 1, "absent": 0, "unknown": unknown,
                            "cold_ms": cold_ms, "dense_warm_p95_ms": percentile(samples, 0.95)})
            engine.release(width)
    print(json.dumps({"slots": HEIGHT, "axes": AXES, "checks": summary}, indent=2))


if __name__ == "__main__":
    main()
