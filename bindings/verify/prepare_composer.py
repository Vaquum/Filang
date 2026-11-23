"""Materialize the pinned Composer oracle and the equivalent Filang price tapes."""

import argparse
import csv
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composer", type=Path)
    parser.add_argument("out", type=Path)
    opts = parser.parse_args()
    sys.path.insert(0, str(opts.composer.resolve()))
    import bars

    root = Path(__file__).resolve().parents[2]
    pins = root / "benchmarks/reports/composer-search/sources.json"
    sources = [bars.Source(**row) for row in json.loads(pins.read_text())]
    opts.out.mkdir(parents=True, exist_ok=True)
    frames = []
    for source in sources:
        frame = bars.frame(source, bars.download(source))
        frames.append(frame)
        dest = opts.out / f"tape-{source.name}.csv"
        with dest.open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("open_ms", "open", "high", "low", "close", "volume"))
            for t, o, h, l, c, volume in zip(
                frame.times, frame.opens, frame.highs, frame.lows, frame.closes, frame.volumes
            ):
                prices = (f"{v // 100}.{v % 100:02d}" for v in (o, h, l, c))
                writer.writerow((t * 1000, *prices, volume))
    (opts.out / "bars").write_bytes(bars.encode(frames))
    (opts.out / "activity").write_bytes(bars.encode_activity(frames))


if __name__ == "__main__":
    main()
