#!/usr/bin/env python3
"""Matched whole-process ladder; no final-period input or evaluation is used."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time


def run():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='examples/btc4h.cfg')
    p.add_argument('--binary',default='target/release/filang')
    p.add_argument('--out',required=True)
    p.add_argument('--repeats',type=int,default=3)
    a=p.parse_args()
    if not 2<=a.repeats<=20: raise ValueError('use 2..20 complete repetitions')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    base=Path(a.config).read_text()
    def config(dest, batch, scorer):
        s=base
        for key,value in [('out',str(dest)),('batch_size',str(batch)),('scorer',scorer)]:
            s,count=re.subn(rf'^{key}=.*$',f'{key}={value}',s,flags=re.M)
            if count!=1: raise ValueError(f'expected one {key}')
        return s
    rows=[];seal=None
    variants=[('direct',1,'scan'),('shared',32,'scan'),('events',32,'events')]
    for repeat in range(a.repeats):
        # Rotate order to avoid assigning every warmest/coldest slot to one variant.
        order=variants[repeat%3:]+variants[:repeat%3]
        for name,batch,scorer in order:
            job=out/f'{name}-{repeat+1}';cfg=out/f'{name}-{repeat+1}.cfg';cfg.write_text(config(job,batch,scorer))
            command=[str(Path(a.binary).resolve()),'search','--config',str(cfg)]
            timer=['/usr/bin/time','-l'] if platform.system()=='Darwin' else ['/usr/bin/time','-v']
            started=time.perf_counter()
            with (out/f'{name}-{repeat+1}.stdout').open('w') as stdout,(out/f'{name}-{repeat+1}.time.txt').open('w') as stderr:
                subprocess.run(timer+command,stdout=stdout,stderr=stderr,check=True)
            elapsed=time.perf_counter()-started
            summary=json.loads((job/'summary.json').read_text())
            current=(job/'frozen.tsv').read_bytes()
            if seal is None: seal=current
            elif current!=seal: raise AssertionError('physical scheduling changed frozen selection')
            log=(out/f'{name}-{repeat+1}.time.txt').read_text()
            if platform.system()=='Darwin':
                match=re.search(r'^\s*(\d+)\s+maximum resident set size',log,re.M)
                rss=int(match.group(1)) if match else None
            else:
                match=re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)',log)
                rss=int(match.group(1))*1024 if match else None
            row={'variant':name,'repeat':repeat+1,'wall_seconds':elapsed,'peak_rss_bytes':rss,'summary':summary}
            rows.append(row)
            print(name,repeat+1,round(elapsed,4),'s',flush=True)
    medians={name:statistics.median(r['wall_seconds'] for r in rows if r['variant']==name) for name,_,_ in variants}
    result={'status':'PASS','scope':'identical discovery inputs/genomes/readouts/costs/metrics/frozen outputs; no holdout access',
        'platform':platform.platform(),'machine':platform.machine(),'threads':1,'affinity':'not pinned','os_file_cache':'not flushed',
        'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
        'engine_sha256':hashlib.sha256(Path(a.binary).read_bytes()).hexdigest(),
        'input_config_sha256':hashlib.sha256(base.encode()).hexdigest(),
        'repeats':a.repeats,'median_wall_seconds':medians,
        'median_direct_over_events':medians['direct']/medians['events'],'runs':rows}
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    subprocess.run(['python3','scripts/compare_discovery.py',str(out/'direct-1'),str(out/'events-1'),'--out',str(out/'differential.json')],check=True)
    print(json.dumps({k:v for k,v in result.items() if k!='runs'},indent=2))


if __name__=='__main__':run()
