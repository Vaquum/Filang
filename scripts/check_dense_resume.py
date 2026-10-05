#!/usr/bin/env python3
"""Process-level deterministic dense restart and failed-integrity tests."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--gate',required=True);p.add_argument('--reference',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.out);root.mkdir(parents=True,exist_ok=False);binary=str(Path('target/release/filang').resolve());common=[binary,'dense-sweep','--config',a.config,'--gate',a.gate,'--capture','true']
    def run(name,flags=(),env=None,expected=0):
        cmd=common+['--out',str(root/name)]+list(flags)
        r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        (root/(name+f'.{len(list(root.glob(name+".*")))}.log')).write_text(r.stdout+'\n'+r.stderr)
        if r.returncode!=expected:raise ValueError(f'{name}: unexpected exit {r.returncode}: {r.stderr[-500:]}')
        return r
    ref=Path(a.reference)
    def same(path):
        for sub in ('context.chk','best.json','best-rule.txt','best-parameters.tsv'):
            if (ref/sub).read_bytes()!=(path/sub).read_bytes():raise ValueError('resume content mismatch '+sub)
        for part in ('banks','tasks'):
            files=[f for f in (ref/part).iterdir() if not f.name.startswith('preparation-')]
            for f in files:
                if f.read_bytes()!=(path/part/f.name).read_bytes():raise ValueError('resume artifact mismatch '+f.name)
        x=json.loads((path/'summary.json').read_text());y=json.loads((ref/'summary.json').read_text())
        for k in ('status','coverage_complete','result_digest','resolved_strategy_addresses','best'):
            if x[k]!=y[k]:raise ValueError('resume summary mismatch '+k)
    run('pause',['--max-tasks','2','--workers','1']);s=json.loads((root/'pause/summary.json').read_text())
    if s['status']!='PAUSED' or s['completed_tasks']!=2:raise ValueError('not paused exactly')
    run('pause',['--resume','true','--workers','4']);same(root/'pause')
    env=dict(os.environ,FILANG_DENSE_TEST_INTERRUPT='1')
    run('interrupted',['--workers','4'],env,1);run('interrupted',['--resume','true','--workers','2']);same(root/'interrupted')
    shutil.copytree(root/'pause',root/'corrupted');q=next((root/'corrupted/tasks').glob('*.chk'));raw=bytearray(q.read_bytes());raw[160]^=1;q.write_bytes(raw)
    run('corrupted',['--resume','true','--workers','1'],expected=1)
    cfg=root/'changed.cfg';cfg.write_text(Path(a.config).read_text().replace('slip_bps=10','slip_bps=11'))
    cmd=common.copy();cmd[cmd.index('--config')+1]=str(cfg);r=subprocess.run(cmd+['--out',str(root/'pause'),'--resume','true'],capture_output=True,text=True)
    if r.returncode==0:raise ValueError('changed context accepted')
    (root/'changed-context.log').write_text(r.stdout+r.stderr)
    result={'status':'PASS','graceful_resume_exact':True,'interrupted_precommit_resume_exact':True,'worker_count_changes_preserve_every_artifact':True,'corrupt_checkpoint_rejected':True,'changed_context_rejected':True,'reference':str(ref),'engine_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest()}
    (root/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
