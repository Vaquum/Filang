#!/usr/bin/env python3
"""Repeat a fixed ten-family discovery; verification and later replay are separate."""
from __future__ import annotations
import argparse,json,subprocess,sys,time
from pathlib import Path
from cohort_reference import KINDS,digest

def verify_one(run):
    from verify_cohort_micro import verify
    return verify(run,Path(run)/"verification.json")

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['discover','verify']);p.add_argument('--out',required=True);p.add_argument('--gate');p.add_argument('--cohort-gate');p.add_argument('--workers',type=int,default=1);a=p.parse_args();root=Path(a.out)
    if a.stage=='verify':
        from verify_cohort_micro import verify
        if not (root/'discovery_index.json').exists():raise ValueError('discovery missing')
        if not 1<=a.workers<=8:raise ValueError('reference workers must be 1..8')
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=a.workers) as pool:results=list(pool.map(verify_one,[str(root/k) for k in KINDS]))
        (root/'verification_index.json').write_text(json.dumps({'status':'PASS','all_ten_families_verified':True,'external_reference_workers':a.workers,'families':results},indent=2)+'\n');return
    if not a.gate or not a.cohort_gate:raise ValueError('both independent gates required')
    if root.exists():raise ValueError('use a new output directory')
    root.mkdir(parents=True);binary=str(Path('target/release/filang').resolve());records=[];clock=time.perf_counter()
    for kind in KINDS:
        raw=Path(f'examples/micro10/{kind}.cfg').read_text()
        raw='\n'.join(('cohort_gate='+a.cohort_gate) if l.startswith('cohort_gate=') else l for l in raw.splitlines())+'\n'
        cfg=root/(kind+'.cfg');cfg.write_text(raw)
        cmd=[binary,'micro-sweep','--config',str(cfg),'--gate',a.gate,'--out',str(root/kind)]
        if sys.platform=='darwin':cmd=['/usr/bin/time','-l','-o',str(root/(kind+'.time.txt'))]+cmd
        start=time.perf_counter()
        with (root/(kind+'.stdout.txt')).open('w') as o,(root/(kind+'.stderr.txt')).open('w') as e:subprocess.run(cmd,stdout=o,stderr=e,check=True)
        wall=time.perf_counter()-start;s=json.loads((root/kind/'summary.json').read_text());comp=json.loads((root/kind/'comparisons.json').read_text())
        if s['full_parameter_addresses_resolved']!=10091043 or not s['coverage_complete']:raise ValueError('coverage mismatch')
        records.append({'family':kind,'wall_seconds':wall,'summary':s,'comparisons':comp,'frozen_sha256':digest(root/kind/'frozen.tsv')})
        print(f"{kind}: {wall:.3f}s; anchor={s['anchor']['primary']['net_return_pct']:.2f}%; descriptive best={s['descriptive_best_not_additionally_selected']['primary']['net_return_pct']:.2f}%; eligible addresses={s['eligible_addresses']}",flush=True)
    index={'status':'PASS','role':'retrospective_discovery_before_later_replay','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'engine_sha256':digest(binary),'native_workers_per_process':1,'cohort_is_not_a_measured_popularity_ranking':True,'parameter_addresses':sum(r['summary']['full_parameter_addresses_resolved'] for r in records),'upstream_constructions':sum(r['summary']['upstream_parameter_constructions'] for r in records),'physical_regions':sum(r['summary']['physical_result_regions'] for r in records),'whole_campaign_seconds':time.perf_counter()-clock,'families':records}
    (root/'discovery_index.json').write_text(json.dumps(index,indent=2)+'\n')
    print('All ten discoveries complete. Freeze selections before separate later replay.',flush=True)
if __name__=='__main__':main()
