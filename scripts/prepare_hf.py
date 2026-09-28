#!/usr/bin/env python3
"""Pinned public-Hub adapter; no Limen dependency and no token required.

Only this optional preparation adapter requires Polars. Filang itself is Rust/std.
Never backfills absent prices, compresses gaps or asks the Hub for a moving latest file.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def epoch(date: str) -> int:
    return int(datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())


def publish(path: Path, payload: bytes) -> None:
    """Idempotent same-bytes writes; refuse to overwrite different experiment input."""
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f'{path} already exists with different contents')
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(payload)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='examples/binance_btc4h.source.json')
    parser.add_argument('--raw', type=Path, help='Verify/reuse an already downloaded Parquet snapshot')
    args = parser.parse_args()
    import polars as pl
    cfg = json.loads(Path(args.source).read_text())
    if cfg['version'] != 1 or not re.fullmatch(r'[a-f0-9]{40}', cfg['revision']):
        raise ValueError('a version-1 config and full immutable revision are required')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+', cfg['repo']):
        raise ValueError('invalid repository id')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.parquet', cfg['filename']):
        raise ValueError('invalid snapshot filename')
    if not re.fullmatch(r'[a-f0-9]{64}', cfg['sha256']):
        raise ValueError('full source SHA-256 required')
    out = Path(cfg['output_dir'])
    out.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/datasets/{cfg['repo']}/resolve/{cfg['revision']}/{cfg['filename']}"
    raw = args.raw or out / cfg['filename']
    if not raw.exists():
        # Bounded memory and size; this adapter does not need multi-GB downloads.
        with urllib.request.urlopen(url, timeout=60) as response, tempfile.NamedTemporaryFile(dir=out, delete=False) as stream:
            tmp = Path(stream.name)
            total = 0
            try:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 128 * 1024 * 1024:
                        raise ValueError('download exceeds this adapter\'s 128 MiB cap')
                    stream.write(chunk)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        if digest(tmp) != cfg['sha256']:
            tmp.unlink()
            raise ValueError('downloaded source SHA-256 mismatch')
        os.replace(tmp, raw)
    if digest(raw) != cfg['sha256']:
        raise ValueError('source SHA-256 mismatch')
    df = pl.read_parquet(raw)
    if len(df) != cfg['expected_source_rows']:
        raise ValueError('source row count mismatch')
    needed = ['datetime', 'open', 'high', 'low', 'close', 'volume']
    if any(k not in df.columns for k in needed):
        raise ValueError('source lacks required fields')
    if not isinstance(df.schema['datetime'], pl.Datetime) or df.schema['datetime'].time_zone != 'UTC':
        raise ValueError('timestamp column must be timezone-aware UTC datetime')
    if df.select(needed).null_count().row(0) != (0, 0, 0, 0, 0, 0):
        raise ValueError('source has missing OHLCV/timestamps')
    x = df.select(pl.col('datetime').dt.epoch('s').alias('timestamp'), *needed[1:])
    times = x['timestamp'].to_list()
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('timestamps must be strictly increasing; never silently reorder')
    x = x.filter((pl.col('timestamp') >= epoch(cfg['history_start'])) & (pl.col('timestamp') < epoch(cfg['evaluation_end'])))
    times = x['timestamp'].to_list()
    step = cfg['interval_seconds']
    if len(times) < 4 or times[0] != epoch(cfg['history_start']) or times[-1] + step != epoch(cfg['evaluation_end']):
        raise ValueError('requested date boundaries are not completely covered')
    if any(b - a != step for a, b in zip(times, times[1:])):
        raise ValueError('gap inside requested history; choose explicit contiguous episodes, not forward filling')
    bad = x.filter(
        ~pl.all_horizontal(pl.col(k).is_finite() for k in needed[1:])
        | (pl.min_horizontal('open', 'high', 'low', 'close') <= 0)
        | (pl.col('high') < pl.max_horizontal('open', 'close'))
        | (pl.col('low') > pl.min_horizontal('open', 'close'))
        | (pl.col('volume') < 0)
    )
    if len(bad):
        raise ValueError(f'{len(bad)} invalid OHLCV rows')
    split = epoch(cfg['discovery_end'])
    discovery = x.filter(pl.col('timestamp') < split)
    if not len(discovery) or discovery['timestamp'][-1] + step != split:
        raise ValueError('discovery boundary is not exactly covered')
    outputs = {}
    for name, frame in [('discovery', discovery), ('evaluation', x)]:
        payload = frame.write_csv().encode()
        publish(out / f'{name}.csv', payload)
        outputs[name] = {'file': f'{name}.csv', 'rows': len(frame), 'sha256': hashlib.sha256(payload).hexdigest(),
                         'first_open_timestamp': frame['timestamp'][0], 'last_open_timestamp': frame['timestamp'][-1]}
    manifest = {'adapter_version': 1, 'source': cfg, 'resolved_url': url, 'polars_version': pl.__version__,
                'source_sha256': digest(raw), 'outputs': outputs,
                'policy': 'discovery CSV excludes all final-evaluation bars; evaluation CSV includes identical causal warm-up prefix'}
    publish(out / 'provenance.json', (json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
