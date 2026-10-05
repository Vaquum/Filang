#!/usr/bin/env python3
"""Matched native joint-strategy ablations; no per-address feature recomputation.
Small proofs expand every result box to its logical addresses. Full-domain timing
compares all box coordinates and metrics, never a projected chronological replay.
"""
from __future__ import annotations
import argparse,itertools,json,platform,statistics,subprocess,sys,time
from pathlib import Path
import numpy as np
from verify_joint import sha,verify

def read_rows(root):
    root=Path(root);m=json.loads((root/'manifest.json').read_text())
    dtype=np.dtype([('template','<u8'),('axes','<u8',(m['slots'],3)),('metrics','<f8',(len(m['costs']),10))])
    return m,np.memmap(root/'boxes.bin',dtype=dtype,mode='r')

def expanded(root):
    m,rows=read_rows(root)
    if m['logical_addresses']>1000000:raise ValueError('small proof address cap')
    opts={o['id']:o for o in m['options']};slots=[[o['id'] for o in m['options'] if o['slot']==s] for s in range(m['slots'])]
    mapping={};offset=0
    for ti in range(len(m['templates'])):
        for choices in itertools.product(*slots):
            if m['different_tags'] and len({opts[x]['tag'] for x in choices})!=len(choices):continue
            shape=tuple(int(opts[x]['grid'].split(':')[2]) for x in choices)
            size=int(np.prod(shape,dtype=np.int64));mapping[(ti,choices)]=(offset,size,shape);offset+=size
    if offset!=m['logical_addresses']:raise ValueError('logical count mismatch')
    ans=np.full((offset,len(m['costs']),10),np.nan);seen=np.zeros(offset,bool)
    for row in rows:
        key=(int(row['template']),tuple(map(int,row['axes'][:,0])));off,size,shape=mapping[key]
        indices=tuple(slice(int(l),int(h)) for l,h in row['axes'][:,1:])
        touched=seen[off:off+size].reshape(shape)
        if touched[indices].any():raise ValueError('overlapping boxes')
        touched[indices]=True;ans[off:off+size].reshape(shape+(len(m['costs']),10))[indices]=row['metrics']
    if not seen.all():raise ValueError('missing addresses')
    return ans

def parity(a,b):
    if a.shape!=b.shape or not np.allclose(a,b,rtol=1e-9,atol=1e-7,equal_nan=True) or not np.array_equal(a[..., [5,9]],b[..., [5,9]]):
        raise ValueError('full metrics/counts differ')

def boxes_equal(a,b):
    ma,aa=read_rows(a);mb,bb=read_rows(b)
    if len(aa)!=len(bb) or ma['logical_addresses']!=mb['logical_addresses']:raise ValueError('different box partitions')
    for lo in range(0,len(aa),65536):
        x,y=aa[lo:lo+65536],bb[lo:lo+65536]
        if not np.array_equal(x['template'],y['template']) or not np.array_equal(x['axes'],y['axes']):raise ValueError('different coordinates')
        parity(x['metrics'],y['metrics'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--gate',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=3);p.add_argument('--full',action='store_true');p.add_argument('--reference-run');p.add_argument('--compact-proofs',action='store_true');a=p.parse_args()
    out=Path(a.out)
    if out.exists() or a.repeats<1:raise ValueError('fresh output and positive repeats required')
    out.mkdir(parents=True);binary=str(Path('target/release/filang').resolve())
    common=[binary,'strategy-sweep','--config',a.config,'--gate',a.gate]
    modes=([('expanded','expanded','scalar',0)] if not a.full else [])+[
      ('cells_scalar','cells','scalar',0),('cofactor_scalar','cofactor','scalar',0),
      ('cofactor_native','cofactor','auto',0),('cofactor_cached','cofactor','auto',8)]
    def run(name,plan,backend,cache,proof):
        root=out/name;cmd=common+['--out',str(root),'--plan',plan,'--backend',backend,'--cache-mib',str(cache),'--capture',str(proof).lower(),'--output','boxes' if proof else 'summary']
        actual=cmd
        if sys.platform=='darwin':actual=['/usr/bin/time','-l','-o',str(out/(name+'.time.txt'))]+cmd
        start=time.perf_counter()
        with (out/(name+'.stdout.txt')).open('w') as o,(out/(name+'.stderr.txt')).open('w') as e:subprocess.run(actual,stdout=o,stderr=e,check=True)
        wall=time.perf_counter()-start;summary=json.loads((root/'summary.json').read_text())
        if not summary['coverage_complete']:raise ValueError('incomplete result')
        return wall,summary
    if a.compact_proofs and (not a.full or not a.reference_run):raise ValueError('compact proofs require full mode and reference-run')
    proofs={};ref=str(Path(a.reference_run).resolve()) if a.reference_run else None
    if ref:
        v=json.loads((Path(ref)/'verification.json').read_text())
        if v['status']!='PASS' or v['boxes_sha256']!=sha(Path(ref)/'boxes.bin'):raise ValueError('reference proof incomplete/changed')
    for name,plan,backend,cache in modes:
        _,s=run('proof-'+name,plan,backend,cache,True);proofs[name]=s
        if a.full:
            if ref is not None:boxes_equal(out/ref,out/('proof-'+name))
            else:ref='proof-'+name
        else:
            values=expanded(out/('proof-'+name))
            if ref is None:ref=values
            else:parity(ref,values)
        print('proof',name,s['logical_strategy_addresses'],s['work']['result_boxes'],'PASS',flush=True)
        if a.compact_proofs:
            proof_root=out/('proof-'+name)
            record={f:sha(proof_root/f) for f in ['boxes.bin','predicate-cells.bin']}
            (proof_root/'checked_large_files.json').write_text(json.dumps({'status':'PASS','reference':ref,'files':record,'removed_after_complete_comparison':True},indent=2)+'\n')
            for f in record:(proof_root/f).unlink()
    if not a.full:verify(out/'proof-cofactor_cached',out/'independent-verification.json')
    results=[]
    for rep in range(a.repeats):
        k=rep%len(modes)
        for name,plan,backend,cache in modes[k:]+modes[:k]:
            wall,s=run(f'{name}-{rep+1}',plan,backend,cache,False)
            if s['result_sha256']!=proofs[name]['result_sha256']:raise ValueError('timed result differs from fully checked proof')
            results.append({'mode':name,'repeat':rep+1,'wall_seconds':wall,'summary':s})
            print(name,rep+1,round(wall,6),'PASS',flush=True)
    med={name:statistics.median(r['wall_seconds'] for r in results if r['mode']==name) for name,_,_,_ in modes}
    result={'status':'PASS','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
      'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'engine_sha256':sha(binary),
      'platform':platform.platform(),'native_workers':1,'cpu_pinned':False,'os_caches_flushed':False,'repeats':a.repeats,
      'reference_run':a.reference_run,'compact_proofs':a.compact_proofs,'mode':'full-domain box-parity' if a.full else 'exhaustive small-domain address parity',
      'logical_addresses':proofs[modes[0][0]]['logical_strategy_addresses'],'all_timed_metrics_verified':True,
      'output_contract':'summary; all results computed; expanded addresses versus exact boxes differ physically',
      'median_wall_seconds':med,'proof_summaries':proofs,'measurements':results}
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(med,indent=2))
if __name__=='__main__':main()
