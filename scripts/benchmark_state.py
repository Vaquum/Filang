#!/usr/bin/env python3
"""Matched native state benchmarks: thresholds, distinct period programs, weak reuse.

Every timed path emits all ten metrics. No experiment selects a market winner.
Run the anchor parity gate before calling this script. TA-Lib feature verification
and explicit cash/share traces are separate from these matched native timings.
"""
from __future__ import annotations
import argparse,hashlib,json,platform,statistics,subprocess,sys,time
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gate',required=True);p.add_argument('--data',default='data/btc4h/evaluation.csv');p.add_argument('--out',required=True)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--period-end',type=int,default=2048)
    p.add_argument('--axes',default='programs,low_similarity,thresholds')
    a=p.parse_args();root=Path(a.out);root.mkdir(parents=True,exist_ok=False)
    if a.repeats<1 or a.period_end<64:raise ValueError('repeats>=1 and period-end>=64')
    axes=a.axes.split(',')
    if len(set(axes))!=len(axes) or not set(axes)<= {'programs','low_similarity','thresholds'}:raise ValueError('unknown or duplicate axis')
    binary=Path('target/release/filang').resolve()
    # Same established SMA-distance family, alternate its already-supported direction.
    # This is an adversarial execution-order workload, not novel-feature research.
    expr=root/'alternating-known-directions.txt'
    expr.write_text('\n'.join((lambda x: f'(neg {x})' if n%2 else x)(f'(sub (div close (mean_sum {n} close)) (constant 3ff0000000000000))') for n in range(2,min(a.period_end,1024)+1))+'\n')
    common=[str(binary),'program-sweep','--data',a.data,'--gate',a.gate,'--start','2023-01-01','--end','2026-09-28','--gaps','2023-07-01,2024-01-01,2024-07-01,2025-01-01,2025-07-01,2026-01-01,2026-07-01','--backend','auto','--page-size','32','--output','all']
    recipes={
      'programs':(common+['--source','periods','--kind','sma','--period-start','2','--period-end',str(a.period_end),'--rules','gt:0'],['replay','rebuild','events','delta','auto']),
      'low_similarity':(common+['--source','expressions','--expressions',str(expr),'--rules','gt:0'],['replay','rebuild','delta','auto']),
      'thresholds':([str(binary),'anchor-sweep','--data',a.data,'--gate',a.gate,'--radius','4','--thresholds','129','--capture','false'],['family','state-legacy','state-events','state'])}
    rows=[]
    def call(tag,command):
        timefile=root/f'{tag}.time.txt';cmd=(['/usr/bin/time','-l','-o',str(timefile)]+command)if sys.platform=='darwin'else command
        before=time.perf_counter()
        with(root/f'{tag}.out.txt').open('w')as o,(root/f'{tag}.err.txt').open('w')as e:subprocess.run(cmd,stdout=o,stderr=e,check=True)
        return time.perf_counter()-before
    for axis in axes:
        cmd,variants=recipes[axis];ref=None
        for rep in range(a.repeats):
            order=variants[rep%len(variants):]+variants[:rep%len(variants)]
            for mode in order:
                tag=f'{axis}-{mode}-{rep+1}';out=root/tag
                command=cmd+['--mode'if axis=='thresholds'else'--scorer',mode,'--out',str(out)]
                elapsed=call(tag,command);values=np.fromfile(out/'metrics.bin',dtype='<f8').reshape(-1,10)
                if ref is None:ref=values.copy()
                if values.shape!=ref.shape or not np.allclose(values,ref,atol=1e-7,rtol=1e-9,equal_nan=True):raise AssertionError(f'full metric parity failed {tag}')
                if not np.array_equal(values[:,[5,9]],ref[:,[5,9]]):raise AssertionError(f'exact counts failed {tag}')
                summary=json.loads((out/'summary.json').read_text());rss=None;timefile=root/f'{tag}.time.txt'
                if timefile.exists():
                    for line in timefile.read_text().splitlines():
                        if 'maximum resident set size' in line:rss=int(line.split()[0])
                row={'axis':axis,'path':mode,'repeat':rep+1,'wall_seconds':elapsed,'max_rss_bytes':rss,'metric_sets':len(values),'summary':summary}
                rows.append(row);print(f'{axis} {mode} {rep+1}: {elapsed:.6f}s, {len(values):,} metric sets, parity PASS',flush=True)
    med={axis:{mode:statistics.median(r['wall_seconds']for r in rows if r['axis']==axis and r['path']==mode)for mode in recipes[axis][1]}for axis in axes}
    result={'status':'PASS','role':'systems_parity_regression_not_selection','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'engine_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'data_sha256':hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),'platform':platform.platform(),'native_workers':1,'affinity':'not pinned','os_caches':'not flushed','repeats':a.repeats,'all_metrics_verified':True,'count_columns_exact':True,'median_wall_seconds':med,'measurements':rows}
    (root/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items()if k!='measurements'},indent=2))
if __name__=='__main__':main()
