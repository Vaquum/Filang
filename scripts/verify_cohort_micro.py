#!/usr/bin/env python3
"""Exhaustive compressed-path and full cash/share metric verification for a family."""
from __future__ import annotations
import argparse, json, struct, time
from pathlib import Path
import numpy as np
from cohort_reference import stripe, output, columns, CashOracle, digest, setup, portfolio, check_values
from verify_micro import config,grid

def verify(root,out):
    root=Path(root);out=Path(out);setup();clock=time.perf_counter()
    cfg=config(root/'experiment.cfg');summary=json.loads((root/'summary.json').read_text());kind=cfg.get('family','sma')
    if digest(cfg['data'])!=summary['data_sha256']:raise ValueError('data changed')
    data=np.loadtxt(cfg['data'],delimiter=',',skiprows=1);cols=columns(data)
    lo=int(np.searchsorted(data[:,0],int(np.datetime64(cfg['discovery_start'],'s').astype('int64'))));length=len(data)-lo-2;prices=cols['open'][lo+1:]
    aa=grid(cfg['source_grid']);bb=grid(cfg['mean_grid']);cc=grid(cfg['offset_grid']);windows=list(map(int,cfg['windows'].split(',')))
    dtype=np.dtype([('base','<u8'),('lo','<u8'),('hi','<u8'),('metrics','<f8',(2,10))]);assert dtype.itemsize==184
    rows=np.memmap(root/'regions.bin',dtype=dtype,mode='r');cursor=base=coverage=metric_count=numpy_checks=0;max_error=0.
    costs=[(float(cfg['fee_bps'])/10000,float(cfg['slip_bps'])/10000),(float(cfg['stress_fee_bps'])/10000,float(cfg['stress_slip_bps'])/10000)]
    oracle=CashOracle(root/'reference-build');step=int(cfg['interval_seconds'])
    with (root/'transitions.bin').open('rb') as proof:
        for n in windows:
            for alpha in aa:
                ids=stripe(kind,n,alpha,cols)
                for beta in bb:
                    x=np.ascontiguousarray(output(kind,ids,beta)[lo:-2])
                    header=proof.read(40)
                    if len(header)!=40:raise ValueError('truncated proof')
                    gotbase,ln,count,nwords,nevents=struct.unpack('<5Q',header)
                    if (gotbase,ln,count,nwords)!=(base,length,len(cc),(length+63)//64):raise ValueError('proof context')
                    actual_words=np.frombuffer(proof.read(nwords*8),dtype='<u8')
                    actual_events=np.frombuffer(proof.read(nevents*16),dtype='<u8').reshape(-1,2)
                    finite=np.isfinite(x);initial=finite&((x-cc[0])>0)
                    pad=np.zeros(nwords*64,dtype='u1');pad[:length]=initial
                    expected_words=np.packbits(pad,bitorder='little').view('<u8')
                    ix=np.flatnonzero(finite&(x>cc[0])&(x<=cc[-1]));q=np.searchsorted(cc,x[ix],side='left')
                    expected_events=np.column_stack([q,ix]).astype('<u8');expected_events=expected_events[np.lexsort((ix,q))]
                    if not np.array_equal(actual_words,expected_words) or not np.array_equal(actual_events,expected_events):raise ValueError(f'exact mask/event mismatch: {kind} base={base}, n={n}, a={alpha}, b={beta}')
                    cuts=np.r_[0,np.unique(q),len(cc)];block=rows[cursor:cursor+len(cuts)-1]
                    if not np.all(block['base']==base) or not np.array_equal(block['lo'],cuts[:-1]) or not np.array_equal(block['hi'],cuts[1:]):raise ValueError('partition mismatch')
                    constants=cc[block['lo']]
                    for ci,(fee,slip) in enumerate(costs):
                        expected=oracle.score(x,prices,constants,fee,slip,step);actual=np.asarray(block['metrics'][:,ci])
                        max_error=max(max_error,check_values(expected,actual,f'{kind} base{base} metrics',1e-7))
                        if not np.array_equal(expected[:,[5,9]],actual[:,[5,9]]):raise ValueError('exact count mismatch')
                        metric_count+=len(block)
                        if base%256==0:
                            for j in sorted(set([0,len(block)//2,len(block)-1])):
                                pos=np.isfinite(x)&((x-constants[j])>0)
                                independent=portfolio(prices,pos,fee,slip,step)
                                max_error=max(max_error,check_values(independent,actual[j],kind+' NumPy crosscheck',1e-7));numpy_checks+=1
                    coverage+=int((block['hi']-block['lo']).sum());cursor+=len(block);base+=1
        if proof.read(1):raise ValueError('trailing transition bytes')
    if cursor!=len(rows) or coverage!=summary['full_parameter_addresses_resolved']:raise ValueError('incomplete coverage')
    result={'status':'PASS','family':kind,'upstream_constructions':base,'addresses_covered':coverage,'physical_regions':cursor,'all_position_paths_verified_by_exact_event_arrays':True,'all_physical_scenario_metric_sets_checked':True,'cash_share_metric_sets_checked':metric_count,'numpy_chronological_crosschecks':numpy_checks,'mask_disagreements':0,'max_metric_absolute_error':max_error,'data_sha256':summary['data_sha256'],'engine_sha256':summary['engine_sha256'],'oracle_c_sha256':digest(oracle.source),'oracle_library_sha256':digest(oracle.library),'regions_sha256':digest(root/'regions.bin'),'transitions_sha256':digest(root/'transitions.bin'),'seconds':time.perf_counter()-clock}
    if out.exists():raise ValueError('verification exists')
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--out',required=True);args=p.parse_args();verify(args.run,args.out)
