#!/usr/bin/env python3
"""Independent NumPy feature arithmetic, vote reconstruction and cash/share accounting."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
from verify_reference import feature, parse_expr, ledger

def compare(got, expected, context):
    worst=0.0
    for key,value in expected.items():
        actual=got[key]
        if value is None:
            if actual is not None: raise AssertionError((context,key,actual,value))
        elif key in ('periods','trades'):
            if actual!=value: raise AssertionError((context,key,actual,value))
        else:
            error=abs(actual-value);worst=max(worst,error)
            if error>1e-8+1e-10*abs(value): raise AssertionError((context,key,actual,value,error))
    return worst

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',required=True);p.add_argument('--selection',required=True)
    p.add_argument('--report',required=True);p.add_argument('--out')
    a=p.parse_args();sel=Path(a.selection).read_bytes()
    if hashlib.sha256(sel).hexdigest()!=Path(a.selection+'.sha256').read_text().strip(): raise ValueError('selection hash mismatch')
    report=json.loads(Path(a.report).read_text());frame=np.loadtxt(a.data,delimiter=',',skiprows=1)
    ts=frame[:,0].astype(np.int64);columns={k:frame[:,i+1]for i,k in enumerate(('open','high','low','close','volume'))}
    members={};ranges={}
    for line in sel.decode().splitlines():
        if not line or line.startswith('#') or line.startswith('fold\t'): continue
        fold,start,end,portfolio,name,fid,greater,bits,q,score,expression=line.split('\t')
        fold=int(fold);ranges[fold]=(int(start),int(end));cutoff=struct.unpack('>d',int(bits,16).to_bytes(8,'big'))[0]
        members.setdefault((fold,portfolio),[]).append((parse_expr(expression),greater=='true',cutoff))
    start=np.searchsorted(ts,min(s for s,e in ranges.values()));end=np.searchsorted(ts,max(e for s,e in ranges.values()))
    positions={name:np.zeros(end-start-2,dtype=bool)for _,name in members};cache={};worst=0.0;fold_checked=0
    fee=report['fee_bps']/10000;slip=report['slip_bps']/10000;step=report['interval_seconds']
    fold_reports={(r['fold'],r['portfolio']):r['metrics']for r in report['fold_results']}
    for (fold,name),items in members.items():
        lo,hi=(np.searchsorted(ts,t)for t in ranges[fold]);masks=[]
        for expr,greater,cutoff in items:
            x=feature(expr,columns,cache)[lo:hi-2]
            masks.append(np.isfinite(x)&(x>cutoff if greater else x<cutoff))
        active=np.sum(masks,axis=0)*2>len(masks)
        positions[name][lo-start:hi-start-2]=active
        expected=ledger(columns['open'][lo+1:hi],active,fee,slip,step)
        worst=max(worst,compare(fold_reports[(fold,name)],expected,(fold,name)));fold_checked+=1
    positions['buy_hold_continuous']=np.ones(end-start-2,dtype=bool)
    trace_dir=Path(a.report).parent;disagreements=0
    for row in report['portfolios']:
        name=row['portfolio'];active=positions[name]
        trace=np.loadtxt(trace_dir/(name+'.csv'),delimiter=',',skiprows=1)
        disagreements+=int(np.count_nonzero(trace[:,3].astype(bool)!=active))
        expected=ledger(columns['open'][start+1:end],active,fee,slip,step)
        worst=max(worst,compare(row['metrics'],expected,name))
    if disagreements: raise AssertionError(f'{disagreements} position disagreements')
    result={'status':'PASS','role':'independent direct-window features / Boolean votes / cash-share ledger',
            'fold_portfolios_checked':fold_checked,'aggregate_portfolios_checked':len(report['portfolios']),
            'position_disagreements':disagreements,'max_absolute_metric_error':worst,'numpy_version':np.__version__,
            'selection_sha256':hashlib.sha256(sel).hexdigest(),'report':a.report}
    if a.out: Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
