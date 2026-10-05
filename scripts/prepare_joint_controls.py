#!/usr/bin/env python3
"""Predetermined compound-temporal/relative/crossover/slope control domain.
Uses the same public strategy TSV and CLI, not private benchmark execution.
"""
import argparse
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--gate',required=True);a=p.parse_args()
    d=Path(a.out)
    if d.exists():raise ValueError('fresh output required')
    d.mkdir(parents=True)
    rsi='(div0 (wilder 14 (add (abs (diff 1 close)) (diff 1 close))) (wilder 14 (abs (diff 1 close))))'
    volume='(div volume (lag 1 (mean_sum 20 volume)))'
    rows=[
      (0,'ema_relative','trend','relative:gt','plain','0:1:1:1','(ema 24 close)','(ema 96 close)'),
      (0,'ema_cross','trend','cross:above','recent:3','0:1:1:1','(ema 24 close)','(ema 96 close)'),
      (0,'sma_slope','trend','slope:rising:3','persist:2','0:1:1:1','(mean_sum 20 close)','-'),
      (1,'rsi_gt','momentum','threshold:gt','plain','98:1:5:100',rsi,'-'),
      (1,'rsi_inclusive','momentum','threshold:ge','recent:2','98:1:5:100',rsi,'-'),
      (1,'rsi_onset','momentum','threshold:lt','onset','98:1:5:100',rsi,'-'),
      (2,'relative_volume','activity','threshold:gt','plain','98:1:5:100',volume,'-'),
      (2,'volume_comparison','activity','relative:ge','persist:2','0:1:1:1','volume','(mean_sum 20 volume)'),
      (2,'volume_inequality','activity','threshold:ne','recent:2','98:1:5:100',volume,'-')]
    (d/'parameters.tsv').write_text('# public generic control inputs\n'+'\n'.join('\t'.join(map(str,r)) for r in rows)+'\n')
    (d/'rules.txt').write_text('(and s0 (or s1 s2))\n(recent 3 (and s0 (and s1 (not s2))))\n(or (persist 2 s0) (and s1 (onset s2)))\n')
    (d/'sweep.cfg').write_text(f'version=1\ndata=data/btc4h/discovery.csv\nout=runs/control\nparameters={d}/parameters.tsv\ntemplates={d}/rules.txt\nstart=2024-01-01\nend=2025-01-01\ninterval_seconds=14400\ncosts=10:10\nmemory_mib=128\ncache_mib=8\ndifferent_tags=true\nplan=cofactor\nbackend=auto\noutput=boxes\ncapture=true\ngate={a.gate}\nmax_boxes=1000000\n')
    print(d/'sweep.cfg')
if __name__=='__main__':main()
