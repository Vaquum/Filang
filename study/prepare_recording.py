"""Recreate the pinned study recording and Composer tapes from their source checkouts."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import polars as pl


ROOT = Path(__file__).resolve().parent
ENCODER = "133e3017ba9143f7dc255df7218ff7bfe46d9d06"
ENCODER_SHA256 = "773f156d8d4118b4dbbb44d380625ddc47fdf818ca6aaae72ef89417e20e0092"


def show(repo, revision, path):
    return subprocess.check_output(["git", "-C", repo, "show", f"{revision}:{path}"])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    recording = parser.add_mutually_exclusive_group(required=True)
    recording.add_argument("--limen")
    recording.add_argument("--parquet", type=Path)
    encoder = parser.add_mutually_exclusive_group(required=True)
    encoder.add_argument("--composer")
    encoder.add_argument("--encoder", type=Path)
    args = parser.parse_args()
    provenance = json.loads((ROOT / "data-provenance.json").read_text())
    source = args.parquet.read_bytes() if args.parquet else show(
        args.limen, provenance["source_commit"], provenance["source_path"]
    )
    if digest(source) != provenance["source_sha256"]:
        raise ValueError("The source Parquet differs from its pin.")
    # Composer's pinned encoding is the interchange contract for its worker.
    bars = types.ModuleType("composer_study_bars")
    sys.modules[bars.__name__] = bars
    encoder = args.encoder.read_bytes() if args.encoder else show(args.composer, ENCODER, "bars.py")
    if digest(encoder) != ENCODER_SHA256:
        raise ValueError("The Composer encoder differs from its pin.")
    exec(compile(encoder, "Composer bars.py", "exec"), bars.__dict__)
    frame = bars.frame(
        bars.Source("15m", 900, "Vaquum/Limen", provenance["source_commit"],
                    provenance["source_path"], provenance["source_sha256"], provenance["row_count"]),
        source,
    )
    csv = pl.read_parquet(io.BytesIO(source)).select(
        pl.col("datetime").dt.epoch("ms").alias("open_ms"), *provenance["columns"][1:]
    ).write_csv().encode()
    resulting = {
        "recorded-bars.csv": csv,
        "composer/bars": bars.encode([frame]),
        "composer/activity": bars.encode_activity([frame]),
    }
    pins = json.loads((ROOT / "recording-lock.json").read_text())["files"]
    for name, data in resulting.items():
        if digest(data) != pins[name]:
            raise ValueError(f"{name} differs from its published byte digest ({digest(data)}).")
    dest = Path(os.environ.get("FILANG_STUDY_DATA", ROOT.parent / "data" / "study"))
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in resulting.items():
        (dest / Path(name).name).write_bytes(data)
    print(f"Recreated all three pinned assets at {dest}")


if __name__ == "__main__":
    main()
