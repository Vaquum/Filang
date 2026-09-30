#!/usr/bin/env python3
"""Matched exhaustive logical results with/without shared dependencies and regions.
All timed modes use summary output; separate proof reconstructs every small-grid metric.
"""
import argparse, hashlib, json, platform, statistics, subprocess, sys, time
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gate',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    out=Path(a.out)
    if out.exists() or a.repeats<1:raise ValueError('new output and positive repeats required')
    out.mkdir(parents=True)
    raw=Path('examples/sma-micro.cfg').read_text().replace('source_grid=-20:1:41:2000','source_grid=-1:1:3:2000').replace('mean_grid=0:1:41:400','mean_grid=0:1:3:400').replace('offset_grid=999000:1:2001:1000000','offset_grid=999000:10:201:1000000')
    cfg=out/'experiment.cfg';cfg.write_text(raw);binary=str(Path('target/release/filang').resolve());common=[binary,'micro-sweep','--config',str(cfg),'--gate',a.gate]
    dtype=np.dtype([('base','<u8'),('lo','<u8'),('hi','<u8'),('metrics','<f8',(2,10))])
    def execute(name,plan,shared,output):
        path=out/name;cmd=common+['--out',str(path),'--plan',plan,'--shared',str(shared).lower(),'--output',output]
        if sys.platform=='darwin':cmd=['/usr/bin/time','-l','-o',str(out/(name+'.time.txt'))]+cmd
        t=time.perf_counter()
        with (out/(name+'.stdout.txt')).open('w') as stdout,(out/(name+'.stderr.txt')).open('w') as stderr:subprocess.run(cmd,stdout=stdout,stderr=stderr,check=True)
        return time.perf_counter()-t,json.loads((path/'summary.json').read_text())
    def expand(path):
        rows=np.fromfile(path,dtype=dtype);ans=[]
        for row in rows:ans.extend([row['metrics']]*int(row['hi']-row['lo']))
        return np.asarray(ans)
    execute('proof-expanded','expanded',True,'regions');execute('proof-regions','regions',True,'regions');execute('proof-no-share','regions',False,'regions')
    ref=expand(out/'proof-expanded/regions.bin')
    for name in ['proof-regions','proof-no-share']:
        got=expand(out/name/'regions.bin')
        if ref.shape!=got.shape or not np.allclose(ref,got,atol=1e-7,rtol=1e-9,equal_nan=True) or not np.array_equal(ref[:,:,[5,9]],got[:,:,[5,9]]):raise ValueError('exhaustive small-grid metric parity')
    modes=[('expanded','expanded',True),('regions_unshared','regions',False),('regions_shared','regions',True)];results=[]
    for rep in range(a.repeats):
        for name,plan,shared in modes[rep%3:]+modes[:rep%3]:
            t,s=execute(f'{name}-{rep+1}',plan,shared,'summary')
            proof_name='proof-expanded' if plan=='expanded' else ('proof-regions' if shared else 'proof-no-share')
            expected=json.loads((out/proof_name/'summary.json').read_text())
            if s['region_sha256']!=expected['region_sha256'] or s['full_parameter_addresses_resolved']!=expected['full_parameter_addresses_resolved']:raise ValueError('timed execution differs from fully verified proof')
            results.append({'mode':name,'repeat':rep+1,'wall_seconds':t,'summary':s});print(name,rep+1,round(t,6),flush=True)
    med={name:statistics.median(r['wall_seconds'] for r in results if r['mode']==name) for name,_,_ in modes}
    result={'status':'PASS','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'engine_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest(),'platform':platform.platform(),'workers':1,'repeats':a.repeats,'cpu_pinning':False,'os_cache_flushed':False,'all_small_grid_metrics_compared':int(ref.shape[0]*ref.shape[1]),'output_contract':'summary; per-parameter full results versus exact region results, not byte-identical physical encodings','median_wall_seconds':med,'expanded_over_shared':med['expanded']/med['regions_shared'],'measurements':results}
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='measurements'},indent=2))
if __name__=='__main__':main()
