#!/usr/bin/env python3
"""Process interruption, deterministic parallel tasks and fail-closed artifacts."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, time
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--gate',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();root=Path(a.out);root.mkdir(exist_ok=False);clock=time.perf_counter()
    raw=Path(a.config).read_text();lines=[]
    changes={'families':'sma,atr','coefficients':'3','cutoffs':'21','task_states':'8'}
    for line in raw.splitlines():
        key=line.split('=',1)[0];lines.append(key+'='+changes[key] if key in changes else line)
    cfg=root/'test.cfg';cfg.write_text('\n'.join(lines)+'\n')
    binary=str(Path('target/release/filang').resolve())
    def run(name,workers=1,resume=False,limit=0,interrupt=None,config=None,expected=0):
        cmd=[binary,'dense-sweep','--config',str(config or cfg),'--gate',a.gate,'--out',str(root/name),'--workers',str(workers),'--resume',str(resume).lower(),'--max-tasks',str(limit),'--capture','true']
        env=os.environ.copy()
        if interrupt is not None:env['FILANG_DENSE_TEST_INTERRUPT']=str(interrupt)
        r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        (root/f'{name}-{workers}-{resume}-{limit}.log').write_text(r.stdout+r.stderr)
        if (r.returncode==0)!=(expected==0):raise ValueError('unexpected process status: '+r.stderr)
        return r
    run('serial');run('parallel',workers=4)
    run('paused',limit=2)
    if json.loads((root/'paused/summary.json').read_text())['coverage_complete']:raise ValueError('pause claimed completion')
    run('paused',workers=4,resume=True)
    run('interrupted',interrupt=1,expected=1)
    if not (root/'interrupted/tasks/task-00000000.chk').exists() or (root/'interrupted/tasks/task-00000001.chk').exists():raise ValueError('interrupted task incorrectly committed')
    run('interrupted',workers=4,resume=True)
    reference=json.loads((root/'serial/summary.json').read_text())
    files=sorted((root/'serial/tasks').glob('*'))
    for name in ['parallel','paused','interrupted']:
        s=json.loads((root/name/'summary.json').read_text())
        if not s['coverage_complete'] or s['result_digest']!=reference['result_digest'] or s['best']!=reference['best']:raise ValueError('restart/parallel result mismatch')
        for f in files:
            if f.read_bytes()!=(root/name/'tasks'/f.name).read_bytes():raise ValueError('checkpoint or full output byte mismatch')
    changed=root/'changed.cfg';changed.write_text(cfg.read_text().replace('fee_bps=10','fee_bps=11'))
    r=run('serial',resume=True,config=changed,expected=1)
    if 'context mismatch' not in r.stderr:raise ValueError('changed domain was not rejected')
    copied=root/'altered';shutil.copytree(root/'serial',copied)
    f=next((copied/'tasks').glob('*.chk'));body=bytearray(f.read_bytes());body[90]^=1;f.write_bytes(body)
    r=run('altered',resume=True,expected=1)
    if 'checksum mismatch' not in r.stderr:raise ValueError('changed checkpoint was not rejected')
    result={'status':'PASS','parallel_workers':4,'byte_identical_task_records_and_outputs':True,'graceful_pause_and_injected_process_exit_checked':True,'uncommitted_task_recomputed':True,'changed_domain_and_checkpoint_rejected':True,'coverage':reference['resolved_strategy_addresses'],'completed_tasks':reference['completed_tasks'],'engine_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest(),'seconds':time.perf_counter()-clock}
    (root/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
