#!/usr/bin/env python3
"""Reproduce the fixed captured dense controls before running matched timings."""
import argparse,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--gate',required=True);p.add_argument('--plan-only',action='store_true');a=p.parse_args()
    root=Path(a.out);root.mkdir(parents=True,exist_ok=False);binary=str(Path('target/release/filang').resolve())
    def run(*args):subprocess.run(list(args),check=True)
    run(binary,'dense-example','--out',str(root/'base.cfg'),'--coefficients','3')
    raw=(root/'base.cfg').read_text();all_families='families=sma,ema,rsi,macd,bollinger,stochastic,atr,roc,cci,vwap'
    domains={'small':raw.replace(all_families,'families=sma,ema').replace('cutoffs=20001','cutoffs=3'),
             'all-small':raw.replace('cutoffs=20001','cutoffs=3'),
             'mixed':raw.replace(all_families,'families=rsi,cci,vwap').replace('cutoffs=20001','cutoffs=21')}
    for name,text in domains.items():(root/(name+'.cfg')).write_text(text)
    run('cargo','build','--release','--locked','--offline','--example','export_dense_joint')
    for case in domains:
        run('./target/release/examples/export_dense_joint',str(root/(case+'.cfg')),str(root/('joint-'+case)))
    if a.plan_only:return
    for case in domains:
        cfg=str(root/(case+'.cfg'));dest=root/('proof-'+case)
        run(binary,'dense-sweep','--config',cfg,'--gate',a.gate,'--out',str(dest),'--workers','1','--capture','true')
        run(sys.executable,'scripts/verify_dense.py','--run',str(dest),'--stage','banks','--workers','4')
        run(sys.executable,'scripts/verify_dense_capture.py','--run',str(dest))
        leaf=root/('leaf-'+case)
        run(binary,'dense-sweep','--config',cfg,'--gate',a.gate,'--out',str(leaf),'--workers','1','--capture','true','--certificates','false')
        run(sys.executable,'scripts/verify_dense_capture.py','--run',str(leaf),'--reference-run',str(dest))
    run(binary,'strategy-sweep','--config',str(root/'joint-small/sweep.cfg'),'--gate',a.gate,'--out',str(root/'joint-expanded'),'--plan','expanded','--cache-mib','0','--capture','true','--output','boxes')
    run(sys.executable,'scripts/verify_dense_capture.py','--run',str(root/'proof-small'),'--compare-joint',str(root/'joint-expanded'))
    print('All control domains verified. Run benchmark_dense.py with this --proof-root.')
if __name__=='__main__':main()
