#!/usr/bin/env python3
"""Derive the walk-search prefix from the already-pinned, verified spot CSV."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

def publish(path, payload):
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f'refusing to replace different data: {path}')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='examples/btc4h-walk.cfg')
    p.add_argument('--source', default='data/btc4h/evaluation.csv')
    p.add_argument('--provenance', default='data/btc4h/provenance.json')
    a = p.parse_args()
    cfg = dict(line.split('=', 1) for line in Path(a.config).read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#'))
    source = Path(a.source).read_bytes()
    parent = json.loads(Path(a.provenance).read_text())
    expected = parent['outputs']['evaluation']['sha256']
    actual = hashlib.sha256(source).hexdigest()
    if actual != expected:
        raise ValueError('source CSV does not match pinned preparation provenance')
    end = int(datetime.strptime(cfg['validation_end'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    lines = source.splitlines(keepends=True)
    selected = [lines[0]] + [line for line in lines[1:] if int(line.split(b',', 1)[0]) < end]
    payload = b''.join(selected)
    step = int(cfg['interval_seconds'])
    if int(selected[-1].split(b',', 1)[0]) + step != end:
        raise ValueError('source does not cover the last selection boundary exactly')
    target = Path(cfg['data'])
    publish(target, payload)
    provenance = {'role':'retrospective_walkforward_not_untouched', 'source_csv_sha256':actual,
                  'source_snapshot':parent['source'], 'selection_end_exclusive':end,
                  'rows':len(selected)-1, 'sha256':hashlib.sha256(payload).hexdigest()}
    publish(target.with_suffix('.provenance.json'), (json.dumps(provenance, indent=2)+'\n').encode())
    print(json.dumps(provenance, indent=2))

if __name__ == '__main__':
    main()
