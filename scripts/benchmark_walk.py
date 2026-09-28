#!/usr/bin/env python3
"""Matched native walk-forward ablations; no outer-period evaluation or reselection."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

VARIANTS = {
    'direct_scalar': {'threads':'1','kernel_backend':'scalar','batch_size':'1','reuse_basis':'false',
                      'reuse_prefix_quantiles':'false','reuse_cost_scenarios':'false','reuse_windows':'false','scorer':'scan'},
    'factorized_scalar': {'threads':'1','kernel_backend':'scalar'},
    'factorized_simd': {'threads':'1','kernel_backend':'auto'},
    'factorized_parallel': {'threads':'4','kernel_backend':'auto'},
}

def configure(raw, changes):
    return '\n'.join(k+'='+changes.get(k,v) if '=' in line and not line.lstrip().startswith('#')
                     else line for line in raw.splitlines()
                     for k,v in [line.split('=',1) if '=' in line else (line,'')])+'\n'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='examples/btc4h-walk.cfg')
    p.add_argument('--out',required=True)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--features',type=int)
    a=p.parse_args()
    if not 1<=a.repeats<=20: raise ValueError('repeats must be 1..20')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    raw=Path(a.config).read_text();rows=[];expected=None
    binary=Path('target/release/filang').resolve()
    names=list(VARIANTS)
    for repeat in range(a.repeats):
        order=names[repeat%len(names):]+names[:repeat%len(names)]
        for name in order:
            dest=out/f'{name}-{repeat+1}'
            changes=dict(VARIANTS[name],out=str(dest))
            if a.features is not None: changes['feature_addresses']=str(a.features)
            cfg=out/f'{name}-{repeat+1}.cfg';cfg.write_text(configure(raw,changes))
            timing=out/f'{name}-{repeat+1}.time.txt'
            command=['/usr/bin/time','-l' if sys.platform=='darwin' else '-v',str(binary),'walk-search','--config',str(cfg)]
            start=time.perf_counter()
            with timing.open('w') as err:
                result=subprocess.run(command,stdout=subprocess.PIPE,stderr=err,text=True)
            elapsed=time.perf_counter()-start
            if result.returncode: raise RuntimeError(timing.read_text())
            summary=json.loads(result.stdout)
            frozen=(dest/'walk.tsv').read_bytes()
            if expected is None: expected=frozen
            if frozen!=expected: raise AssertionError(f'nonmatching frozen selections: {name}; benchmark invalid')
            rows.append({'variant':name,'repeat':repeat+1,'wall_seconds':elapsed,
                         'summary':summary,'timing_log':timing.name})
            print(f'{name} {repeat+1}: {elapsed:.4f}s; identical selection',flush=True)
    medians={name:statistics.median(r['wall_seconds'] for r in rows if r['variant']==name)for name in names}
    report={'status':'PASS','scope':'same paged programs, folds, cutoffs, costs, selection and frozen output',
            'platform':platform.platform(),'cpu_affinity':'not pinned','os_cache':'not flushed',
            'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'engine_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'config_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'repeats':a.repeats,'median_wall_seconds':medians,
            'speedup_direct_to_parallel':medians['direct_scalar']/medians['factorized_parallel'],
            'frozen_sha256':hashlib.sha256(expected).hexdigest(),'measurements':rows}
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='measurements'},indent=2))

if __name__=='__main__': main()
