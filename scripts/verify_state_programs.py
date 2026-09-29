#!/usr/bin/env python3
"""Verify captured period-source programs against pinned TA-Lib and full backtests.

This verifier supports the documented known-macro source, not arbitrary anonymous
programs. Unsupported sources are rejected rather than claimed externally covered.
"""
from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
import talib
from anchor_reference import features,portfolio
from verify_reference import ledger
from datetime import datetime,timezone

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',required=True);p.add_argument('--run',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();clock=time.perf_counter();run=Path(a.run);meta=json.loads((run/'domain.json').read_text());d=meta['request_domain']
    if d['source']!='periods':raise ValueError('external coverage here is period macros only')
    if talib.__version__!='0.6.8':raise ValueError('requires pinned TA-Lib wrapper 0.6.8')
    talib.set_compatibility(0)
    for name in ('EMA','RSI','ATR'):talib.set_unstable_period(name,0)
    if hashlib.sha256(Path(a.data).read_bytes()).hexdigest()!=d['data_sha256']:raise ValueError('source digest mismatch')
    frame=np.loadtxt(a.data,delimiter=',',skiprows=1);ts=frame[:,0].astype(np.int64);cols={k:frame[:,i+1]for i,k in enumerate(('open','high','low','close','volume'))}
    lo,hi=np.searchsorted(ts,[d['start'],d['end']]);allowed=np.ones(hi-lo-2,dtype=bool)
    for date in filter(None,d['gaps'].split(',')):
        index=int(np.searchsorted(ts,int(datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())))
        allowed[index-lo-2:index-lo]=False
    prices=cols['open'][lo+1:hi];step=int(ts[1]-ts[0]);args=d['source_arguments'];kind=args['--kind'];profile=args.get('--profile','talib')
    summary=json.loads((run/'summary.json').read_text());count=summary['page_work']['program_requests'];size=count*len(ts)*8
    if(run/'features.bin').stat().st_size!=size:raise ValueError('incomplete numeric capture')
    xx=np.memmap(run/'features.bin',mode='r',dtype='<f8',shape=(count,len(ts)));mm=np.memmap(run/'metrics.bin',mode='r',dtype='<f8',shape=(summary['full_metric_queries'],10))
    errors=[];at=0;mask_diff=0;max_x=0.;max_m=0.;cash_checks=0;seen=0
    for index,line in enumerate((run/'requests.jsonl').open()):
        spec=json.loads(line);period=int(args.get('--period-start','2'))+int(spec['address'])*int(args.get('--period-step','1'))
        periods=[period,int(args.get('--slow','96')),int(args.get('--signal','9'))]if kind in ('ema_cross','macd')else[period]*3
        x=features({'kind':kind,'periods':periods,'profile':profile,'expression':spec['expression']},cols,{})
        valid=np.isfinite(x);y=np.asarray(xx[index]);seen+=1
        if not np.array_equal(valid,np.isfinite(y)):errors.append((index,'validity'))
        max_x=max(max_x,float(np.max(abs(x[valid]-y[valid]),initial=0.)))
        if not np.allclose(x[valid],y[valid],rtol=1e-9,atol=1e-8):errors.append((index,'values'))
        for rule in spec['rules']:
            px=valid & ((x>rule['threshold'])if rule['greater']else(x<rule['threshold']));py=np.isfinite(y)&((y>rule['threshold'])if rule['greater']else(y<rule['threshold']))
            delta=int(np.count_nonzero(px!=py));mask_diff+=delta
            if delta:errors.append((index,'mask',delta))
            pos=px[lo:hi-2]&allowed
            for fee,slip in d['scenarios']:
                ref=portfolio(prices,pos,fee/10000,slip/10000,step);got=mm[at];valid_m=np.isfinite(ref)&np.isfinite(got)
                max_m=max(max_m,float(np.max(abs(ref[valid_m]-got[valid_m]),initial=0.)))
                if not np.allclose(ref,got,atol=1e-7,rtol=1e-9,equal_nan=True):errors.append((index,'metrics',at))
                if not np.array_equal(ref[[5,9]],got[[5,9]]):errors.append((index,'counts',at))
                if index%128==0:
                    independent=ledger(prices,pos,fee/10000,slip/10000,step)
                    vals=np.array([np.nan if independent[k]is None else independent[k]for k in ['net_return_pct','gross_return_pct','cagr_pct','max_drawdown_pct','sharpe_annualized_naive','trades','exposure_pct','mean_bps_per_bar','mean_trade_bps','periods']])
                    if not np.allclose(vals,got,atol=1e-7,rtol=1e-9,equal_nan=True):errors.append((index,'cash_share'))
                    cash_checks+=1
                at+=1
    if seen!=count or at!=len(mm):errors.append(('incomplete_coverage',seen,at))
    result={'status':'PASS'if not errors else'FAIL','role':'external_known_family_verification','programs':seen,'full_metric_sets':at,'all_values_and_validity_checked':True,'all_rule_masks_checked':True,'mask_disagreements':mask_diff,'max_feature_absolute_error':max_x,'max_metric_absolute_error':max_m,'cash_share_replays_at_every_128th_program':cash_checks,'talib_wrapper':talib.__version__,'talib_c':talib.__ta_version__.decode(),'data_sha256':d['data_sha256'],'domain_sha256':hashlib.sha256((run/'domain.json').read_bytes()).hexdigest(),'elapsed_seconds':time.perf_counter()-clock,'errors':errors[:50],'error_count':len(errors)}
    out=Path(a.out)
    with out.open('x')as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
