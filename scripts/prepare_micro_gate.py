#!/usr/bin/env python3
"""Authorize an immutable discovery CSV prefix without exposing later data to search."""
import argparse, hashlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--gate', required=True);p.add_argument('--full', required=True);p.add_argument('--discovery', required=True)
a=p.parse_args();g=Path(a.gate);raw=g.read_bytes()
if hashlib.sha256(raw).hexdigest()!=Path(str(g)+'.sha256').read_text().strip():raise ValueError('gate checksum')
m=dict(l.split('=',1) for l in raw.decode().splitlines())
full=Path(a.full).read_bytes();prefix=Path(a.discovery).read_bytes()
if m['status']!='PASS' or hashlib.sha256(full).hexdigest()!=m['data_sha256'] or not full.startswith(prefix):raise ValueError('not verified source prefix')
if not prefix.endswith(b'\n'):raise ValueError('partial CSV line')
out=g.parent/'micro_gate.txt'
if out.exists():raise ValueError('micro gate exists')
m['authorized_prefix_sha256']=hashlib.sha256(prefix).hexdigest()
text=''.join(f'{k}={v}\n' for k,v in m.items());out.write_text(text)
Path(str(out)+'.sha256').write_text(hashlib.sha256(text.encode()).hexdigest()+'\n')
print(out)
