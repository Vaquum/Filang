#!/usr/bin/env python3
"""Streaming differential check of full discovery ledgers (standard library only)."""
import argparse
if not __debug__:
    raise RuntimeError("verification must not run with Python assertions disabled")
import itertools
import json
import math
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('left');p.add_argument('right');p.add_argument('--out')
a=p.parse_args()
maxima={k:0.0 for k in ('training_net_pct','validation_net_pct','validation_sharpe','selection_score')}
count=0
with (Path(a.left)/'discovery.jsonl').open() as left,(Path(a.right)/'discovery.jsonl').open() as right:
    for l,r in itertools.zip_longest(left,right):
        assert l is not None and r is not None,'ledger lengths differ'
        x,y=json.loads(l),json.loads(r)
        for k in x.keys()-maxima.keys(): assert x[k]==y[k],(count,k,x[k],y[k])
        for k in maxima:
            if x[k] is None or y[k] is None:
                assert x[k] is None and y[k] is None,(count,k)
            else:
                err=abs(x[k]-y[k]);maxima[k]=max(maxima[k],err)
                assert math.isclose(x[k],y[k],abs_tol=1e-8,rel_tol=1e-10),(count,k,x[k],y[k])
        count+=1
assert (Path(a.left)/'frozen.tsv').read_bytes()==(Path(a.right)/'frozen.tsv').read_bytes(),'frozen selections differ'
text=json.dumps({'status':'PASS','readouts_compared':count,'max_abs_errors':maxima,'frozen_selection':'byte-identical'},indent=2)+'\n'
if a.out: Path(a.out).write_text(text)
print(text)
