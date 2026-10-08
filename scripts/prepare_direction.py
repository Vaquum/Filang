#!/usr/bin/env python3
"""Prepare immutable Vaquum OHLCV inputs for the next-bar geometry experiment.

Only this optional adapter needs Polars. It retains every real grid-aligned bar
inside the protocol interval; gaps are recorded and remain explicit in the CSV.
The native direction sweep excludes windows whose feature/target span a gap.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.request

from prepare_hf import digest, publish


def epoch(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def load_protocol(path: Path) -> dict:
    config = json.loads(path.read_text())
    if config.get("version") != 1:
        raise ValueError("expected protocol version 1")
    times = [epoch(config[k]) for k in ("history_start", "validation_start", "test_start", "end")]
    if not all(a < b for a, b in zip(times, times[1:])):
        raise ValueError("strict chronological train/validation/test boundaries required")
    sources = config["sources"]
    if sorted(s["minutes"] for s in sources) != sorted(config["timeframes_minutes"]):
        raise ValueError("source/timeframe mismatch")
    if len({s["minutes"] for s in sources}) != len(sources):
        raise ValueError("duplicate timeframe")
    for source in sources:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", source["repo"]):
            raise ValueError("unsafe repository name")
        if not re.fullmatch(r"[a-f0-9]{40}", source["revision"]):
            raise ValueError("immutable full Hub revision required")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+\.parquet", source["filename"]):
            raise ValueError("unsafe snapshot name")
        if not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("full source SHA-256 required")
        if source["expected_source_bytes"] <= 0 or source["expected_source_rows"] < 4:
            raise ValueError("invalid expected source size")
        if source["minutes"] <= 0 or any(t % (60 * source["minutes"]) for t in times):
            raise ValueError("unaligned timeframe/split boundary")
    return config


def download(source: dict, raw_dir: Path) -> tuple[Path, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / source["filename"]
    url = (f"https://huggingface.co/datasets/{source['repo']}/resolve/"
           f"{source['revision']}/{source['filename']}")
    if raw.exists():
        if raw.stat().st_size != source["expected_source_bytes"] or digest(raw) != source["sha256"]:
            raise ValueError(f"existing raw source differs from pinned identity: {raw}")
        return raw, url
    temp = None
    try:
        with urllib.request.urlopen(url, timeout=60) as response, tempfile.NamedTemporaryFile(
            dir=raw_dir, prefix="download-", delete=False
        ) as stream:
            temp = Path(stream.name)
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > source["expected_source_bytes"]:
                    raise ValueError("source exceeds pinned byte length")
                stream.write(chunk)
        if total != source["expected_source_bytes"] or digest(temp) != source["sha256"]:
            raise ValueError("downloaded source size/SHA-256 mismatch")
        temp.replace(raw)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return raw, url


def prepare_one(source: dict, config: dict, out: Path) -> dict:
    import polars as pl

    raw, url = download(source, out / "raw")
    needed = ["datetime", "open", "high", "low", "close", "volume"]
    df = pl.read_parquet(raw, columns=needed)
    if len(df) != source["expected_source_rows"]:
        raise ValueError("source row count differs from pinned metadata")
    dtype = df.schema["datetime"]
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
        raise ValueError("source datetime must be timezone-aware UTC")
    if df.null_count().row(0) != (0,) * len(needed):
        raise ValueError("null source value")
    # Reject sub-second timestamps instead of silently rounding them away.
    if df.select((pl.col("datetime").dt.epoch("us") % 1000000 != 0).any()).item():
        raise ValueError("sub-second candle opening timestamp")
    x = df.select(pl.col("datetime").dt.epoch("s").alias("timestamp"), *needed[1:])
    step = source["minutes"] * 60
    source_times = x["timestamp"].to_list()
    if any(t % step for t in source_times) or any(b <= a for a, b in zip(source_times, source_times[1:])):
        raise ValueError("off-grid, duplicate or unordered source timestamps")
    bad = x.filter(
        ~pl.all_horizontal(pl.col(k).is_finite() for k in needed[1:])
        | (pl.min_horizontal("open", "high", "low", "close") <= 0)
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("volume") < 0)
    )
    if len(bad):
        raise ValueError(f"{len(bad)} invalid OHLCV source rows")
    begin, end = epoch(config["history_start"]), epoch(config["end"])
    x = x.filter((pl.col("timestamp") >= begin) & (pl.col("timestamp") < end))
    times = x["timestamp"].to_list()
    if not times or times[0] != begin or times[-1] + step != end:
        raise ValueError("source does not exactly cover the requested outer boundaries")
    time_set = set(times)
    for k in ("validation_start", "test_start"):
        if epoch(config[k]) not in time_set:
            raise ValueError(f"split opening candle absent: {k}")
    gaps = [{"previous_open": a, "next_open": b, "missing_grid_bars": (b - a) // step - 1}
            for a, b in zip(times, times[1:]) if b - a != step]
    frame_dir = out / f"{source['minutes']}m"
    frame_dir.mkdir(parents=True, exist_ok=True)
    payload = x.write_csv().encode()
    csv_path = frame_dir / "ohlcv.csv"
    publish(csv_path, payload)
    record = {
        "minutes": source["minutes"], "interval_seconds": step,
        "source": source, "resolved_url": url, "source_sha256": digest(raw),
        "csv": str(csv_path.resolve()), "csv_sha256": hashlib.sha256(payload).hexdigest(),
        "csv_bytes": len(payload), "rows": len(x), "first_open": times[0], "last_open": times[-1],
        "expected_grid_rows": (end - begin) // step,
        "missing_grid_bars": sum(g["missing_grid_bars"] for g in gaps), "gaps": gaps,
        "feature_columns": ["open", "high", "low", "close"],
        "policy": "Real rows retained; gaps remain explicit and invalidate crossing feature/target windows.",
        "polars_version": pl.__version__
    }
    publish(frame_dir / "provenance.json", (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())
    return record


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, default=Path("experiments/geometry_direction/protocol.json"))
    p.add_argument("--out", type=Path, default=Path("data/geometry-direction"))
    p.add_argument("--download-workers", type=int, default=3)
    args = p.parse_args()
    if not 1 <= args.download_workers <= 5:
        p.error("download workers must be 1..5")
    config = load_protocol(args.protocol)
    args.out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.download_workers) as pool:
        records = list(pool.map(lambda source: prepare_one(source, config, args.out), config["sources"]))
    manifest = {"version": 1, "protocol_sha256": digest(args.protocol), "sources": records,
                "adapter_sha256": digest(Path(__file__))}
    publish(args.out / "provenance.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"status": "PASS", "output": str(args.out), "timeframes": [
        {k: r[k] for k in ("minutes", "rows", "missing_grid_bars", "csv_sha256")} for r in records]}, indent=2))


if __name__ == "__main__":
    main()
