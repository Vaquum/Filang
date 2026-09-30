#!/usr/bin/env python3
"""Matched small and full micro-grid ablations for all ten declared families."""
import argparse,json,platform,statistics,subprocess,sys,time
from pathlib import Path
from cohort_reference import KINDS,digest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gate',required=True);p.add_argument('--verified',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    root=Path(a.out);verified=Path(a.verified)
    if root.exists() or a.repeats<1:raise ValueError('new output and positive repeats required')
    if not json.loads((verified/'verification_index.json').read_text()).get('all_ten_families_verified'):raise ValueError('exhaustive cohort reference verification required first')
    root.mkdir(parents=True);(root/'small').mkdir();(root/'full').mkdir();binary=str(Path('target/release/filang').resolve())
    small=[]
    for kind in KINDS:
        dest=root/'small'/kind
        command=[sys.executable,'scripts/benchmark_micro.py','--config',str(verified/(kind+'.cfg')),'--gate',a.gate,'--out',str(dest),'--repeats',str(a.repeats)]
        with (root/'small'/(kind+'.log')).open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=json.loads((dest/'benchmark.json').read_text());small.append({'family':kind,'benchmark':result})
        print(kind,'small expanded/shared ratio',round(result['expanded_over_shared'],3),flush=True)
    runs=[]
    for rep in range(a.repeats):
        kinds=KINDS[rep%10:]+KINDS[:rep%10]
        for kind in kinds:
            target=json.loads((verified/kind/'summary.json').read_text())
            for shared in ([True,False] if rep%2==0 else [False,True]):
                tag=f"{kind}-{'shared' if shared else 'unshared'}-{rep+1}";dest=root/'full'/tag;resource=root/'full'/(tag+'.time.txt')
                cmd=[binary,'micro-sweep','--config',str(verified/(kind+'.cfg')),'--gate',a.gate,'--out',str(dest),'--output','summary','--shared',str(shared).lower()]
                if sys.platform=='darwin':cmd=['/usr/bin/time','-l','-o',str(resource)]+cmd
                start=time.perf_counter()
                with (root/'full'/(tag+'.log')).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
                wall=time.perf_counter()-start;s=json.loads((dest/'summary.json').read_text())
                if s['region_sha256']!=target['region_sha256'] or s['full_parameter_addresses_resolved']!=target['full_parameter_addresses_resolved'] or (dest/'frozen.tsv').read_bytes()!=(verified/kind/'frozen.tsv').read_bytes():raise ValueError('full-region parity mismatch: '+tag)
                runs.append({'family':kind,'shared':shared,'repeat':rep+1,'wall_seconds':wall,'summary':s})
                print(tag,round(wall,4),'all region results identical',flush=True)
    medians={kind:{label:statistics.median(x['wall_seconds'] for x in runs if x['family']==kind and x['shared']==shared) for label,shared in [('shared',True),('unshared',False)]} for kind in KINDS}
    result={'status':'PASS','role':'systems_ablation_not_alpha_selection','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'engine_sha256':digest(binary),'platform':platform.platform(),'native_workers':1,'repeats':a.repeats,'cpu_pinned':False,'os_cache_flushed':False,'no_reference_verification_concurrent':True,'all_full_region_hashes_and_frozen_selections_identical':True,'full_median_wall_seconds':medians,'small':small,'full_runs':runs}
    (root/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'PASS','full_median_wall_seconds':medians},indent=2))
if __name__=='__main__':main()
