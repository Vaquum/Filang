#!/usr/bin/env python3
"""Independently verify every compressed offset transition, and full metrics.
TA-Lib computes each modified source's actual means, not a commuted approximation.
Two output bytes streams are compared as data, not hash-only behavioral evidence.
"""
import argparse, hashlib, json, struct, time
from pathlib import Path
import numpy as np
import talib
from anchor_reference import portfolio, ledger

def config(path):
    return dict(l.strip().split('=',1) for l in Path(path).read_text().splitlines() if l.strip() and not l.lstrip().startswith('#'))
def grid(s):
    start,step,count,den=map(int,s.split(':'))
    return np.array([float(start+i*step)/float(den) for i in range(count)])
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--out',required=True);p.add_argument('--all-metrics',action='store_true');a=p.parse_args()
    root=Path(a.run);cfg=config(root/'experiment.cfg');summary=json.loads((root/'summary.json').read_text());clock=time.perf_counter()
    if talib.__version__!='0.6.8':raise ValueError('requires pinned reference wrapper')
    raw=Path(cfg['data']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=summary['data_sha256']:raise ValueError('input changed')
    d=np.loadtxt(cfg['data'],delimiter=',',skiprows=1);ts=d[:,0].astype('int64');op=d[:,1];cl=d[:,4]
    start=int(np.datetime64(cfg['discovery_start'],'s').astype('int64'));lo=int(np.searchsorted(ts,start));length=len(d)-lo-2
    aa=grid(cfg['source_grid']);bb=grid(cfg['mean_grid']);cc=grid(cfg['offset_grid']);windows=list(map(int,cfg['windows'].split(',')))
    if len(cc)>100000:raise ValueError('verification grid allocation limited to 100000; use smaller grid or boundary-only probe')
    dtype=np.dtype([('base','<u8'),('lo','<u8'),('hi','<u8'),('metrics','<f8',(2,10))]);assert dtype.itemsize==184
    rows=np.memmap(root/'regions.bin',dtype=dtype,mode='r');cursor=0;base=0;metric_count=0;cash_count=0;coverage=0;max_error=0.
    costs=[(float(cfg['fee_bps']),float(cfg['slip_bps'])),(float(cfg['stress_fee_bps']),float(cfg['stress_slip_bps']))];step=int(cfg['interval_seconds'])
    with (root/'transitions.bin').open('rb') as proof:
        for n in windows:
            for alpha in aa:
                price=cl if alpha==0 else cl+alpha*(op-cl)
                m=talib.SMA(price,n);nxt=talib.SMA(price,n+1)
                for beta in bb:
                    denominator=m if beta==0 else m+beta*(nxt-m)
                    with np.errstate(invalid='ignore',divide='ignore'):
                        x=np.where(np.abs(denominator)>1e-12,price/denominator,np.nan)[lo:-2]
                    head=proof.read(40)
                    if len(head)!=40:raise ValueError('truncated transition header')
                    gotbase,ln,count,nwords,nevents=struct.unpack('<5Q',head)
                    if (gotbase,ln,count,nwords)!=(base,length,len(cc),(length+63)//64):raise ValueError('transition context')
                    actual_words=np.frombuffer(proof.read(nwords*8),dtype='<u8')
                    actual_events=np.frombuffer(proof.read(nevents*16),dtype='<u8').reshape(-1,2)
                    finite=np.isfinite(x);initial=finite&(x>cc[0]);pad=np.zeros(nwords*64,dtype='u1');pad[:length]=initial
                    expected_words=np.packbits(pad,bitorder='little').view('<u8')
                    ix=np.flatnonzero(finite&(x>cc[0])&(x<=cc[-1]));q=np.searchsorted(cc,x[ix],side='left')
                    expected_events=np.column_stack([q,ix]).astype('<u8');expected_events=expected_events[np.lexsort((ix,q))]
                    if not np.array_equal(actual_words,expected_words) or not np.array_equal(actual_events,expected_events):raise ValueError(f'exact transition parity failure at {base}')
                    cuts=np.r_[0,np.unique(q),len(cc)]
                    block=rows[cursor:cursor+len(cuts)-1]
                    if not np.array_equal(block['base'],np.full(len(block),base)) or not np.array_equal(block['lo'],cuts[:-1]) or not np.array_equal(block['hi'],cuts[1:]):raise ValueError(f'region partition mismatch {base}')
                    # Verify every region when requested; otherwise all regions in each
                    # 64th upstream and the first/last/central region of every upstream.
                    checks=range(len(block)) if a.all_metrics or base%64==0 else sorted(set([0,len(block)-1,int(np.searchsorted(block['hi'],len(cc)//2,side='right'))]))
                    for j in checks:
                        row=block[j];q0=int(row['lo']);c=cc[q0];f=x-c;pos=np.isfinite(f)&(f>0)
                        for ci,(fee,slip) in enumerate(costs):
                            mtr=portfolio(op[lo+1:],pos,fee/10000,slip/10000,step);got=row['metrics'][ci]
                            valid=np.isfinite(mtr)&np.isfinite(got);max_error=max(max_error,float(np.max(np.abs(mtr[valid]-got[valid]),initial=0.)))
                            if not np.allclose(mtr,got,rtol=1e-9,atol=1e-7,equal_nan=True) or not np.array_equal(mtr[[5,9]],got[[5,9]]):raise ValueError(f'metric mismatch {base} {q0} {ci}')
                            metric_count+=1
                            if base%512==0 and j==0:
                                independent=ledger(op[lo+1:],pos,fee/10000,slip/10000,step)
                                names=['net_return_pct','gross_return_pct','cagr_pct','max_drawdown_pct','sharpe_annualized_naive','trades','exposure_pct','mean_bps_per_bar','mean_trade_bps','periods']
                                other=np.array([np.nan if independent[k] is None else independent[k] for k in names])
                                if not np.allclose(got,other,rtol=1e-9,atol=1e-7,equal_nan=True):raise ValueError('cash-share mismatch')
                                cash_count+=1
                    coverage+=sum(int(h)-int(l) for l,h in zip(block['lo'],block['hi']));cursor+=len(block);base+=1
        if proof.read(1):raise ValueError('trailing transition bytes')
    if cursor!=len(rows) or coverage!=summary['full_parameter_addresses_resolved']:raise ValueError('coverage mismatch')
    result={'status':'PASS','role':'independent_TA_Lib_source_means_and_exact_transition_verification','upstream_programs':base,'addresses_covered':coverage,'physical_regions':cursor,'all_position_paths_verified_by_exact_event_records':True,'all_region_metrics_checked':a.all_metrics,'metric_sets_checked':metric_count,'extra_cash_share_replays':cash_count,'max_metric_absolute_error':max_error,'talib_wrapper':talib.__version__,'talib_c':talib.__ta_version__.decode(),'elapsed_seconds':time.perf_counter()-clock}
    out=Path(a.out)
    if out.exists():raise ValueError('verification output exists')
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
