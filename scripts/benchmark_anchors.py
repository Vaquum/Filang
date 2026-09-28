#!/usr/bin/env python3
"""Matched end-to-end TA-Lib/native/factorized known-family sweep benchmark.

Every timed path emits the same full metrics and no captured histories. A separate
captured verification run checks all numerical outputs and all requested masks.
This runner never changes a formula, threshold, cost, time range or metric to win.
"""
from __future__ import annotations
import argparse, hashlib, json, platform, shutil, statistics, subprocess, sys, time
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',default='data/btc4h/evaluation.csv');p.add_argument('--gate',required=True)
    p.add_argument('--out',required=True);p.add_argument('--radius',type=int,default=4);p.add_argument('--thresholds',type=int,default=129)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--verify-capture',action='store_true')
    p.add_argument('--paths',default='talib_numpy,native_direct,native_shared,family_scalar,family_simd')
    a=p.parse_args()
    root=Path(a.out)
    if root.exists():raise ValueError('output exists')
    root.mkdir(parents=True)
    bin=Path('target/release/filang').resolve();common=[str(bin),'anchor-sweep','--data',a.data,'--gate',a.gate,'--radius',str(a.radius),'--thresholds',str(a.thresholds)]
    def execute(tag,command):
        timefile=root/(tag+'.time.txt');wrapped=(['/usr/bin/time','-l','-o',str(timefile)]+command) if sys.platform=='darwin' else command
        start=time.perf_counter()
        with (root/(tag+'.stdout.txt')).open('w') as out,(root/(tag+'.stderr.txt')).open('w') as err:subprocess.run(wrapped,stdout=out,stderr=err,check=True)
        return time.perf_counter()-start
    proof=root/'proof'
    execute('proof',common+['--out',str(proof),'--capture',str(a.verify_capture).lower()])
    execute('reference-proof',[sys.executable,'scripts/anchor_reference.py','--data',a.data,'--manifest',str(proof/'manifest.json'),'--native',str(proof),'--out',str(root/'reference-proof')])
    proof_values=np.fromfile(proof/'metrics.bin',dtype='<f8').reshape(-1,10)
    results=[];variants=a.paths.split(',')
    supported={'talib_numpy','native_direct','native_shared','family_scalar','family_simd'}
    if a.repeats<1 or len(variants)!=len(set(variants)) or not set(variants)<=supported or not {'talib_numpy','family_simd'}<=set(variants):
        raise ValueError('paths must include talib_numpy and family_simd without duplicates; repeats must be positive')
    for rep in range(a.repeats):
        order=variants[rep%len(variants):]+variants[:rep%len(variants)]
        for name in order:
            tag=f'{name}-{rep+1}';out=root/tag
            if name=='talib_numpy':
                # Matched no-history manifest. The reference caches shared TA-Lib calls.
                manifest=json.loads((proof/'manifest.json').read_text());manifest['capture']=False
                path=root/'timing-manifest.json';path.write_text(json.dumps(manifest))
                command=[sys.executable,'scripts/anchor_reference.py','--data',a.data,'--manifest',str(path),'--out',str(out)]
            else:
                mode={'native_direct':'direct','native_shared':'shared'}.get(name,'family')
                backend='auto' if name=='family_simd' else 'scalar'
                command=common+['--out',str(out),'--capture','false','--mode',mode,'--backend',backend]
            wall=execute(tag,command);got=np.fromfile(out/'metrics.bin',dtype='<f8').reshape(-1,10)
            if got.shape!=proof_values.shape or not np.allclose(got,proof_values,rtol=1e-9,atol=1e-7,equal_nan=True):raise ValueError('all-metric parity failure: '+tag)
            if not np.array_equal(got[:,[5,9]],proof_values[:,[5,9]]):raise ValueError('count parity failure: '+tag)
            summary=json.loads((out/'summary.json').read_text());results.append({'path':name,'repeat':rep+1,'wall_seconds':wall,'summary':summary})
            print(f'{tag}: {wall:.6f}s; all {len(got):,} full-metric rows matched',flush=True)
    med={name:statistics.median(r['wall_seconds'] for r in results if r['path']==name) for name in variants}
    result={'status':'PASS','role':'performance_and_semantic_regression_not_alpha_search','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
       'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'platform':platform.platform(),'machine':platform.machine(),
       'threads_per_native_process':1,'cpu_affinity':'not pinned','os_file_cache':'not flushed','radius':a.radius,'thresholds_per_direction':a.thresholds,'repeats':a.repeats,
       'engine_sha256':hashlib.sha256(bin.read_bytes()).hexdigest(),'gate_sha256':hashlib.sha256(Path(a.gate).read_bytes()).hexdigest(),'full_metric_queries':len(proof_values),
       'all_metric_columns':json.loads((proof/'manifest.json').read_text())['metric_columns'],'all_timed_metrics_verified':True,'capture_verification':a.verify_capture,
       'median_wall_seconds':med,'talib_pipeline_over_family':med['talib_numpy']/med['family_simd'],'native_direct_over_family':med['native_direct']/med['family_simd'] if 'native_direct' in med else None,'measurements':results}
    (root/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='measurements'},indent=2))
if __name__=='__main__':main()
