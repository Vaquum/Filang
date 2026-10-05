#!/usr/bin/env python3
"""Exhaustive independent verification of captured, bounded dense domains.
Checks every region's exact mask certificate, disjoint state-pair coverage,
weighted parameter count and sequential cash/share metrics. Caps the in-memory
state-pair table explicitly; use verify_dense.py for large retained summaries.
"""
from __future__ import annotations
import argparse,json,hashlib,re,time
from pathlib import Path
import numpy as np
from verify_dense import settings,sealed,load_bank,ordered,frontier_ranges,task_record,truth_table
from verify_joint import Oracle,sha
from cohort_reference import check_values

def bounds(table,a,b):
    pa=[~a[0],a[1]];pb=[~b[0],b[1]]
    yes=np.zeros_like(a[0]);no=yes.copy()
    for i in range(2):
        for j in range(2):
            possible=pa[i]&pb[j]
            if table&(1<<(i*2+j)):yes|=possible
            else:no|=possible
    return ~no&a[2]&b[2],yes&a[3]&b[3]

def summaries(states):
    cache={}
    def get(lo,hi):
        key=(lo,hi)
        if key not in cache:
            x=states[lo:hi]
            cache[key]=(np.bitwise_and.reduce(x['bits'],axis=0),np.bitwise_or.reduce(x['bits'],axis=0),np.bitwise_and.reduce(x['valid'],axis=0),np.bitwise_or.reduce(x['valid'],axis=0))
        return cache[key]
    return get

def verify(root):
    root=Path(root);clock=time.perf_counter();cfg=settings(root/'experiment.cfg');s=json.loads((root/'summary.json').read_text())
    if not s['capture'] or s['status']!='PASS':raise ValueError('complete captured run required')
    if sha(cfg['data'])!=s['data_sha256']:raise ValueError('input changed')
    families=cfg['families'].split(',');rules=cfg['rules'].split(';');banks=[];orders=[]
    for i in range(len(families)):
        bank,rows,_,_=load_bank(root/'banks'/f'bank-{i:02}.bin');order=ordered(bank);orders.append(order);banks.append(bank[order])
    if any(len(a)*len(b)>4000000 for a in banks for b in banks):raise ValueError('bounded capture verifier state-pair budget exceeded')
    d=np.loadtxt(cfg['data'],delimiter=',',skiprows=1);prices=d[len(d)-rows-1:,1];oracle=Oracle(root/'verification'/'capture-cash')
    dtype=np.dtype([('ranges','<u8',(4,)),('weight','<u8',(2,)),('metrics','<f8',(10,))]);assert dtype.itemsize==128
    task=0;count=0;total=0;error=0.;table_paths={}
    for ai,a in enumerate(banks):
        sa=summaries(a);ap=np.r_[0,np.cumsum(a['count'][:,0],dtype=np.uint64)]
        for bi,b in enumerate(banks):
            if ai==bi:continue
            sb=summaries(b);bp=np.r_[0,np.cumsum(b['count'][:,0],dtype=np.uint64)]
            for ti,rule in enumerate(rules):
                numeric=np.empty((len(a),len(b),10));numeric.fill(np.nan)
                for al,ah in frontier_ranges(len(a),int(cfg['task_states'])):
                    cp,_=task_record(root/'tasks'/f'task-{task:08}.chk',s['context_sha256']);path=root/'tasks'/f'task-{task:08}.boxes'
                    digest,size=sealed(path)
                    if digest!=cp['digest'] or size!=cp['regions']*128:raise ValueError('captured checkpoint digest/count')
                    records=np.memmap(path,mode='r',dtype=dtype,shape=(cp['regions'],));covered=np.zeros((ah-al,len(b)),dtype=np.int32)
                    for start in range(0,len(records),1024):
                        chunk=records[start:start+1024]
                        rr=np.asarray(chunk['ranges'],dtype=np.int64);ll,hh,bl,bh=rr.T
                        if not np.all((ll>=al)&(hh<=ah)&(ll<hh)&(bl>=0)&(bh<=len(b))&(bl<bh)):raise ValueError('box outside task')
                        expected_weights=(ap[hh]-ap[ll]).astype(object)*(bp[bh]-bp[bl]).astype(object)
                        got_weights=chunk['weight'][:,0].astype(object)+chunk['weight'][:,1].astype(object)*(1<<64)
                        if not np.array_equal(expected_weights,got_weights):raise ValueError('weighted region count')
                        total+=sum(map(int,got_weights));count+=len(chunk)
                        masks=np.empty((len(chunk),a['bits'].shape[1]),dtype=np.uint64)
                        leaf=(hh-ll==1)&(bh-bl==1);ix=np.flatnonzero(leaf)
                        if len(ix):
                            aa=a[ll[ix]];bb=b[bl[ix]];table=truth_table(rule)
                            yes=np.zeros_like(aa['bits'])
                            for i in range(2):
                                for j in range(2):
                                    if table&(1<<(i*2+j)):yes|=(aa['bits'] if i else ~aa['bits'])&(bb['bits'] if j else ~bb['bits'])
                            masks[ix]=yes&aa['valid']&bb['valid']
                            np.add.at(covered,(ll[ix]-al,bl[ix]),1)
                            numeric[ll[ix],bl[ix]]=chunk['metrics'][ix]
                        for j in np.flatnonzero(~leaf):
                            lo,hi,left,right=map(int,rr[j])
                            if covered[lo-al:hi-al,left:right].any():raise ValueError('overlapping regions')
                            covered[lo-al:hi-al,left:right]+=1
                            low,high=bounds(truth_table(rule),sa(lo,hi),sb(left,right))
                            if not np.array_equal(low,high):raise ValueError('nonconstant product mask')
                            masks[j]=low;numeric[lo:hi,left:right]=chunk['metrics'][j]
                        ref=oracle.score(np.asarray(masks),rows,prices,float(cfg['fee_bps']),float(cfg['slip_bps']),14400)
                        error=max(error,check_values(ref,chunk['metrics'],'all captured dense region metrics',1e-7))
                        if not np.array_equal(ref[:,[5,9]],chunk['metrics'][:,[5,9]]):raise ValueError('exact metric counts')
                    if not np.all(covered==1):raise ValueError('incomplete state-pair coverage')
                    task+=1
                dest=root/'verification'/f'metrics-{ai}-{bi}-{ti}.npy';np.save(dest,numeric);table_paths[f'{ai}:{bi}:{ti}']=str(dest)
    if total!=int(s['resolved_strategy_addresses']) or count!=s['metric_regions_evaluated'] or task!=s['completed_tasks']:raise ValueError('capture total coverage')
    result={'status':'PASS','all_captured_region_masks_metrics_and_coverage_checked':True,'logical_addresses':str(total),'regions_checked':count,'task_count':task,'mask_disagreements':0,'max_metric_absolute_error':error,'seconds':time.perf_counter()-clock,'state_metric_tables':table_paths}
    (root/'verification'/'capture.json').write_text(json.dumps(result,indent=2)+'\n');print({k:v for k,v in result.items() if k!='state_metric_tables'});return result

def compare_joint(dense,joint):
    dense=Path(dense);joint=Path(joint);dc=settings(dense/'experiment.cfg');m=json.loads((joint/'manifest.json').read_text());s=json.loads((joint/'summary.json').read_text())
    families=dc['families'].split(',');templates=dc['rules'].split(';')
    if m['templates']!=templates or len(m['costs'])!=1:raise ValueError('comparison rule/cost domain')
    state_maps={};metric_tables={}
    for f in range(len(families)):
        states,_,_,_=load_bank(dense/'banks'/f'bank-{f:02}.bin');idx=np.empty(len(states),dtype=np.int64);idx[ordered(states)]=np.arange(len(states))
        p=dense/'banks'/f'members-{f:02}.bin';_,size=sealed(p);mem=np.memmap(p,mode='r',dtype='<u8',offset=104,shape=((size-104)//40,5))
        for atom,qual,lo,hi,sid in mem:
            key=(f,int(atom),int(qual));v=state_maps.setdefault(key,np.empty(int(dc['cutoffs']),dtype=np.int64));v[int(lo):int(hi)]=idx[sid]
    options={}
    for opt in m['options']:
        match=re.fullmatch(r'f(\d+)-a(\d+)-q(\d+)',opt['label'])
        if not match:raise ValueError('unrecognized exported coordinate')
        options[opt['id']]=tuple(map(int,match.groups()))
    typ=np.dtype([('template','<u8'),('slots','<u8',(2,3)),('metrics','<f8',(10,))])
    if typ.itemsize!=m['binary_record_bytes']:raise ValueError('joint result schema')
    data=np.memmap(joint/'boxes.bin',dtype=typ,mode='r');checked=0;error=0.
    for row in data:
        ai,al,ah=map(int,row['slots'][0]);bi,bl,bh=map(int,row['slots'][1]);a=options[ai];b=options[bi];t=int(row['template']);key=(a[0],b[0],t)
        if key not in metric_tables:metric_tables[key]=np.load(dense/'verification'/f'metrics-{key[0]}-{key[1]}-{t}.npy',mmap_mode='r')
        aa=np.unique(state_maps[a][al:ah]);bb=np.unique(state_maps[b][bl:bh]);want=metric_tables[key][aa[:,None],bb[None,:]]
        got=np.broadcast_to(row['metrics'],want.shape);error=max(error,check_values(got,want,'ordinary joint vs dense',1e-7))
        if not np.array_equal(got[:,:,[5,9]],want[:,:,[5,9]]):raise ValueError('joint/dense count mismatch')
        checked+=(ah-al)*(bh-bl)
    ds=json.loads((dense/'summary.json').read_text())
    if checked!=int(ds['resolved_strategy_addresses']) or checked!=int(m['logical_addresses']):raise ValueError('joint comparison domain mismatch')
    r={'status':'PASS','all_logical_metrics_compared':str(checked),'joint_boxes':len(data),'max_metric_absolute_error':error,'joint_result_sha256':sha(joint/'boxes.bin')}
    (dense/'verification'/('comparison-'+joint.name+'.json')).write_text(json.dumps(r,indent=2)+'\n');print(r);return r

def compare_leaf_capture(root,reference):
    root=Path(root);reference=Path(reference);cfg=settings(root/'experiment.cfg')
    if settings(reference/'experiment.cfg')!=cfg:raise ValueError('different benchmark domains')
    original=json.loads((reference/'verification'/'capture.json').read_text())
    if not original.get('all_captured_region_masks_metrics_and_coverage_checked'):raise ValueError('reference not independently verified')
    current=json.loads((root/'summary.json').read_text());source=json.loads((reference/'summary.json').read_text())
    if current['proof'] or not current['capture'] or current['status']!='PASS' or current['engine_sha256']!=source['engine_sha256']:raise ValueError('requires matching completed leaf capture')
    families=cfg['families'].split(',');banks=[]
    for f in range(len(families)):
        a,_,_,_=load_bank(root/'banks'/f'bank-{f:02}.bin');b,_,_,_=load_bank(reference/'banks'/f'bank-{f:02}.bin')
        if not np.array_equal(a,b):raise ValueError('benchmark predicate banks differ')
        banks.append(a[ordered(a)])
    task=0;regions=0;covered=0;error=0.;dt=np.dtype([('ranges','<u8',(4,)),('weight','<u8',(2,)),('metrics','<f8',(10,))])
    for a,aa in enumerate(banks):
        for b,bb in enumerate(banks):
            if a==b:continue
            for t in range(len(cfg['rules'].split(';'))):
                expected=np.load(reference/'verification'/f'metrics-{a}-{b}-{t}.npy',mmap_mode='r')
                for lo,hi in frontier_ranges(len(aa),int(cfg['task_states'])):
                    cp,_=task_record(root/'tasks'/f'task-{task:08}.chk',current['context_sha256']);p=root/'tasks'/f'task-{task:08}.boxes';digest,size=sealed(p)
                    if cp['digest']!=digest or size!=cp['regions']*128:raise ValueError('leaf result digest')
                    rows=np.memmap(p,dtype=dt,mode='r',shape=(cp['regions'],));seen=np.zeros((hi-lo,len(bb)),dtype=np.int32)
                    for start in range(0,len(rows),4096):
                        block=rows[start:start+4096];r=block['ranges'].astype(np.int64);al,ah,bl,bh=r.T
                        if not np.all((al>=lo)&(ah<=hi)&(ah-al==1)&(bl>=0)&(bh<=len(bb))&(bh-bl==1)):raise ValueError('invalid leaf range')
                        np.add.at(seen,(al-lo,bl),1)
                        weights=aa['count'][al,0].astype(object)*bb['count'][bl,0].astype(object)
                        if not np.array_equal(weights,block['weight'][:,0].astype(object)+block['weight'][:,1].astype(object)*(1<<64)):raise ValueError('leaf weights')
                        want=expected[al,bl];got=block['metrics'];error=max(error,check_values(want,got,'leaf-vs-verified-product metrics',1e-7))
                        if not np.array_equal(want[:,[5,9]],got[:,[5,9]]):raise ValueError('leaf exact counts')
                        covered+=sum(map(int,weights));regions+=len(block)
                    if not np.all(seen==1):raise ValueError('leaf product partition')
                    task+=1
    if covered!=int(current['resolved_strategy_addresses']) or regions!=current['metric_regions_evaluated']:raise ValueError('leaf aggregate coverage')
    result={'status':'PASS','all_leaf_result_metrics_compared':regions,'logical_addresses':str(covered),'max_metric_absolute_error':error,'independent_reference':str(reference),'reference_capture_check_sha256':sha(reference/'verification'/'capture.json')}
    dest=root/'verification';dest.mkdir(exist_ok=True);(dest/'leaf-comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--compare-joint');p.add_argument('--reference-run');a=p.parse_args()
    if a.compare_joint:compare_joint(a.run,a.compare_joint)
    elif a.reference_run:compare_leaf_capture(a.run,a.reference_run)
    else:verify(a.run)
