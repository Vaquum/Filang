#!/usr/bin/env python3
"""Matched cold-process dense ablations with full, preverified result hashes.
Does not time external verification or extrapolate an unexecuted large baseline.
"""
from __future__ import annotations
import argparse,hashlib,json,platform,statistics,subprocess,sys,time
from pathlib import Path
from verify_dense import sealed,task_record

def task_digests(root):
    root=Path(root);s=json.loads((root/'summary.json').read_text())
    return [task_record(f,s['context_sha256'])[0]['digest'] for f in sorted((root/'tasks').glob('*.chk'))]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--proof-root',required=True);p.add_argument('--gate',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    if not 1<=a.repeats<=20:raise ValueError('repeats must be 1..20')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False);proof=Path(a.proof_root);binary=str(Path('target/release/filang').resolve());records=[]
    # Require the retained correctness results BEFORE benchmark timing starts.
    for case in ('small','all-small','mixed'):
        for path in (proof/f'proof-{case}'/'verification/capture.json',proof/f'leaf-{case}'/'verification/leaf-comparison.json'):
            if json.loads(path.read_text())['status']!='PASS':raise ValueError('unverified proof')
    joint_ref=json.loads((proof/'joint-expanded/summary.json').read_text())
    if json.loads((proof/'proof-small/verification/comparison-joint-expanded.json').read_text())['status']!='PASS':raise ValueError('ordinary joint comparison missing')
    def execute(name,cmd):
        if sys.platform=='darwin':cmd=['/usr/bin/time','-l','-o',str(out/(name+'.time.txt'))]+cmd
        start=time.perf_counter()
        with (out/(name+'.stdout')).open('w') as o,(out/(name+'.stderr')).open('w') as e:subprocess.run(cmd,stdout=o,stderr=e,check=True)
        return time.perf_counter()-start
    for case in ('small','all-small','mixed'):
        modes=[('leaf_scalar',False,'scalar',1),('envelope_scalar',True,'scalar',1),('envelope_native',True,'auto',1),('envelope_parallel',True,'auto',4)]
        for rep in range(a.repeats):
            order=modes[rep%len(modes):]+modes[:rep%len(modes)]
            for mode,cert,backend,workers in order:
                name=f'{case}-{mode}-{rep+1}';dest=out/name
                cmd=[binary,'dense-sweep','--config',str(proof/(case+'.cfg')),'--gate',a.gate,'--out',str(dest),'--certificates',str(cert).lower(),'--backend',backend,'--workers',str(workers),'--capture','false']
                wall=execute(name,cmd);s=json.loads((dest/'summary.json').read_text());reference=proof/(('proof-' if cert else 'leaf-')+case)
                if task_digests(dest)!=task_digests(reference):raise ValueError('timed metrics differ from verified complete capture')
                if s['best']!=json.loads((reference/'summary.json').read_text())['best']:raise ValueError('selection differs')
                records.append({'case':case,'mode':mode,'repeat':rep+1,'whole_process_seconds':wall,'summary':s,'all_task_result_hashes_match_verified_capture':True})
                print(name,round(wall,4),flush=True)
            if case=='small':
                name=f'{case}-expanded-{rep+1}';dest=out/name
                cmd=[binary,'strategy-sweep','--config',str(proof/'joint-small/sweep.cfg'),'--gate',a.gate,'--out',str(dest),'--plan','expanded','--cache-mib','0','--capture','false','--output','summary']
                wall=execute(name,cmd);s=json.loads((dest/'summary.json').read_text())
                if s['result_sha256']!=joint_ref['result_sha256']:raise ValueError('timed expanded output differs from verified capture')
                records.append({'case':case,'mode':'expanded','repeat':rep+1,'whole_process_seconds':wall,'summary':s,'all_task_result_hashes_match_verified_capture':True});print(name,round(wall,4),flush=True)
    medians={}
    for r in records:
        key=(r['case'],r['mode']);medians.setdefault(key,[]).append(r['whole_process_seconds'])
    result={'status':'PASS','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True)),'engine_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest(),'repeats':a.repeats,'platform':platform.platform(),'cpu_pinned':False,'os_cache_flushed':False,'output':'summary; original joint per-address encoding versus dense set-product encoding; all full metrics retained semantically','median_wall_seconds':{case:{mode:statistics.median(values) for (name,mode),values in medians.items() if name==case} for case in ('small','all-small','mixed')},'measurements':records}
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['median_wall_seconds'],indent=2))
if __name__=='__main__':main()
