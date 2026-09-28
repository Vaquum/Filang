#!/usr/bin/env python3
"""Pinned TA-Lib + NumPy full-backtest reference and strict parity gate.

TA-Lib is used only here, never by the native engine. Legacy rows are separately
checked by direct-window formulas and the original cash/share oracle. Comparisons
cover every input row and every requested threshold; no warm-up trimming or
parameter-dependent exclusions are used to make a comparison pass.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from pathlib import Path
import numpy as np
import talib
from verify_reference import feature, parse_expr, ledger

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def features(row,cols,cache):
    kind=row['kind']; w,s,k=row['periods']; c=cols['close']
    if row['profile']=='filang_v1': return feature(parse_expr(row['expression']),cols,cache)
    def get(name,*args):
        key=(name,args)
        if key not in cache:
            if name in ('ATR','WILLR'): cache[key]=getattr(talib,name)(cols['high'],cols['low'],c,*args)
            else: cache[key]=getattr(talib,name)(c,*args)
        return cache[key]
    with np.errstate(invalid='ignore',divide='ignore'):
        if kind=='sma': return c/get('SMA',w)-1
        if kind=='ema': return c/get('EMA',w)-1
        if kind=='ema_cross': return get('EMA',w)/get('EMA',s)-1
        if kind=='rsi': return get('RSI',w)/50-1
        if kind=='bollinger':
            upper,middle,lower=get('BBANDS',w,2.,2.,0)
            sd=(upper-middle)/2
            return np.where(abs(sd)>1e-12,(c-middle)/sd,np.nan)
        if kind=='macd': return get('MACD',w,s,k)[2]/c
        if kind=='roc': return get('ROC',w)/100
        if kind=='channel': return get('WILLR',w)/100+1
        if kind=='atr': return get('ATR',w)/c
    raise ValueError(kind)

def portfolio(open_px,p,fee,slip,step):
    """Vectorized chronological ledger; all ten native metrics, including drawdown."""
    entry=p & ~np.r_[False,p[:-1]]; exit_=p & ~np.r_[p[1:],False]
    a=np.where(p,open_px[1:]/open_px[:-1],1.)
    gross_log=np.log(a)
    factors=a.copy();factors[entry]/=(1+fee)*(1+slip);factors[exit_]*=(1-fee)*(1-slip)
    r=factors-1.;log=np.log1p(r);growth=np.cumsum(log);peak=np.maximum.accumulate(np.r_[0.,growth])[1:]
    n=len(p);trades=int(entry.sum());mean=float(np.mean(r));sd=float(np.std(r,ddof=1));
    tlogs=np.add.reduceat(log,np.flatnonzero(entry)) if trades else np.array([])
    return np.array([np.expm1(log.sum())*100,np.expm1(gross_log.sum())*100,np.expm1(log.sum()*31557600/(n*step))*100,
        -np.expm1(-np.max(peak-growth))*100,mean/sd*np.sqrt(31557600/step) if sd>1e-12 else np.nan,
        trades,p.mean()*100,mean*10000,np.expm1(tlogs).mean()*10000 if trades else np.nan,n],dtype='<f8')

def cash_trace(open_px,p,fee,slip):
    out=np.empty((len(p),7));cash=1.;shares=0.;previous=1.;entry_equity=1.
    for i,active in enumerate(p):
        entry=bool(active and (i==0 or not p[i-1]));exit_=bool(active and (i+1==len(p) or not p[i+1]))
        if entry:entry_equity=cash;shares=cash/(open_px[i]*(1+slip)*(1+fee));cash=0.
        eq=cash+shares*open_px[i+1];gain=np.nan
        if exit_:cash=shares*open_px[i+1]*(1-slip)*(1-fee);shares=0.;eq=cash;gain=eq/entry_equity-1
        out[i]=[active,entry,exit_,open_px[i+1]/open_px[i]-1 if active else 0.,eq/previous-1,eq,gain];previous=eq
    return out

def load(data,manifest):
    if digest(data)!=manifest['data_sha256']: raise ValueError('data fingerprint mismatch')
    a=np.loadtxt(data,delimiter=',',skiprows=1)
    cols={name:a[:,i+1] for i,name in enumerate(('open','high','low','close','volume'))}
    lo,hi=manifest['start_index'],manifest['end_index']
    allowed=np.ones(hi-lo-2,dtype=bool)
    for j in manifest['gap_signal_indices']: allowed[j-lo]=False
    return cols,cols['open'][lo+1:hi],allowed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',required=True);p.add_argument('--manifest',required=True)
    p.add_argument('--out',required=True);p.add_argument('--native');p.add_argument('--gate',action='store_true')
    args=p.parse_args();clock=time.perf_counter();manifest=json.loads(Path(args.manifest).read_text())
    out=Path(args.out)
    if out.exists():raise ValueError('reference output already exists')
    out.mkdir(parents=True)
    if talib.__version__!='0.6.8':raise ValueError('reference requires pinned TA-Lib 0.6.8')
    talib.set_compatibility(0)
    for name in ('EMA','RSI','ATR'):talib.set_unstable_period(name,0)
    cols,prices,allowed=load(args.data,manifest);lo,hi=manifest['start_index'],manifest['end_index'];cache={}
    capture=bool(manifest['capture']);native=None;native_features=None;native_traces=None
    if args.native:
        native=np.fromfile(Path(args.native)/'metrics.bin',dtype='<f8').reshape(-1,10)
        if capture:
            native_features=np.memmap(Path(args.native)/'features.bin',dtype='<f8',mode='r',shape=(len(manifest['requests']),manifest['rows']))
            if args.gate:native_traces=np.memmap(Path(args.native)/'traces.bin',dtype='<f8',mode='r',shape=(len(native),hi-lo-2,7))
    errors=[];max_feature_error=0.;mask_disagreements=0;numeric_metrics=0.;at=0;checked_cash=0;event_disagreements=0;trace_error=0.
    feature_out=open(out/'features.bin','wb') if capture else None
    with open(out/'metrics.bin','wb') as output:
        for index,row in enumerate(manifest['requests']):
            x=features(row,cols,cache)
            if capture:np.asarray(x,dtype='<f8').tofile(feature_out)
            if native_features is not None:
                y=np.asarray(native_features[index]);valid=np.isfinite(x)
                if not np.array_equal(valid,np.isfinite(y)):errors.append((row['key'],'validity'))
                delta=float(np.max(np.abs(x[valid]-y[valid]),initial=0.));max_feature_error=max(max_feature_error,delta)
                if not np.allclose(x[valid],y[valid],rtol=1e-9,atol=1e-8):errors.append((row['key'],'feature_values',delta))
            for rule in row['rules']:
                comp=x[lo:hi-2]>rule['threshold'] if rule['greater'] else x[lo:hi-2]<rule['threshold']
                pos=np.isfinite(x[lo:hi-2]) & comp & allowed
                if native_features is not None:
                    y=np.asarray(native_features[index]);fullx=np.isfinite(x)&((x>rule['threshold']) if rule['greater'] else (x<rule['threshold']))
                    fully=np.isfinite(y)&((y>rule['threshold']) if rule['greater'] else (y<rule['threshold']))
                    n=int(np.count_nonzero(fullx!=fully));mask_disagreements+=n
                    if n:errors.append((row['key'],'mask',n))
                for fee,slip in manifest['scenarios']:
                    m=portfolio(prices,pos,fee/10000,slip/10000,manifest['interval']);m.tofile(output)
                    if native is not None:
                        ref=native[at];good=np.isfinite(m)&np.isfinite(ref)
                        err=float(np.max(abs(m[good]-ref[good]),initial=0.));numeric_metrics=max(numeric_metrics,err)
                        if not np.allclose(m,ref,rtol=1e-9,atol=1e-7,equal_nan=True):errors.append((row['key'],'metrics',at,err))
                        if m[5]!=ref[5] or m[9]!=ref[9]:errors.append((row['key'],'exact_counts',at))
                    if args.gate:
                        independent=ledger(prices,pos,fee/10000,slip/10000,manifest['interval'])
                        oracle=np.array([np.nan if independent[k] is None else independent[k] for k in manifest['metric_columns'].split(',')])
                        if not np.allclose(m,oracle,rtol=1e-9,atol=1e-7,equal_nan=True):errors.append((row['key'],'cash_share_oracle'))
                        independent_trace=cash_trace(prices,pos,fee/10000,slip/10000)
                        n=int(np.count_nonzero(independent_trace[:,:3]!=native_traces[at,:,:3]));event_disagreements+=n
                        good=np.isfinite(independent_trace)&np.isfinite(native_traces[at])
                        err=float(np.max(abs(independent_trace[good]-native_traces[at][good]),initial=0.));trace_error=max(trace_error,err)
                        if n or not np.allclose(independent_trace,native_traces[at],rtol=1e-9,atol=1e-8,equal_nan=True):errors.append((row['key'],'trade_equity_trace',err,n))
                        checked_cash+=1
                    at+=1
    if feature_out:feature_out.close()
    if native is not None and at!=len(native):errors.append(('result_count',at,len(native)))
    summary={'status':'PASS' if not errors else 'FAIL','talib_wrapper':talib.__version__,'talib_c':talib.__ta_version__.decode(),
      'numpy':np.__version__,'data_sha256':manifest['data_sha256'],'manifest_sha256':digest(args.manifest),'programs':len(manifest['requests']),
      'full_metric_queries':at,'all_features_captured':capture,'all_threshold_masks_compared':native_features is not None,
      'position_disagreements':mask_disagreements if native_features is not None else None,'max_feature_absolute_error':max_feature_error,
      'max_metric_absolute_error':numeric_metrics,'independent_cash_share_replays':checked_cash,'trade_event_disagreements':event_disagreements,'max_equity_trade_trace_error':trace_error,'errors':errors[:50],
      'error_count':len(errors),'total_internal_seconds':time.perf_counter()-clock,'metric_columns':manifest['metric_columns']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
    if errors:raise SystemExit(1)
    if args.gate:
        if not args.native or not capture:raise ValueError('gate requires full native value and mask evidence')
        # Reproduce the stored fixed-control metrics, not just a fresh reference.
        gold_dir=Path('benchmarks/reports/20260928-walkforward');legacy=0;cursor=0;cols_metric=manifest['metric_columns'].split(',')
        gold=[json.loads((gold_dir/f).read_text()) for f in ('evaluation.json','stress.json')]
        for row in manifest['requests']:
            if row['profile']=='filang_v1':
                for ci in range(2):
                    expected=next(p['metrics'] for p in gold[ci]['portfolios'] if p['portfolio']==row['parent'])
                    v=np.array([np.nan if expected[k] is None else expected[k] for k in cols_metric])
                    if not np.allclose(native[cursor+ci],v,rtol=1e-9,atol=1e-7,equal_nan=True):raise ValueError('stored regression mismatch '+row['key'])
                    legacy+=1
            cursor+=2*len(row['rules'])
        summary['stored_control_regressions']=legacy
        base=Path(args.native);(base/'verification.json').write_text(json.dumps(summary,indent=2)+'\n')
        gate='\n'.join(f'{k}={v}' for k,v in {'version':1,'status':'PASS','data_sha256':manifest['data_sha256'],'engine_sha256':manifest['engine_sha256'],'catalog_sha256':manifest['catalog_sha256'],'manifest_sha256':digest(base/'manifest.json'),'metrics_sha256':digest(base/'metrics.bin'),'verification_sha256':digest(base/'verification.json')}.items())+'\n'
        (base/'gate.txt').write_text(gate);(base/'gate.txt.sha256').write_text(hashlib.sha256(gate.encode()).hexdigest()+'\n')
        print('Parity gate created:',base/'gate.txt')

if __name__=='__main__':main()
