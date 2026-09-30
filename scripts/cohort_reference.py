#!/usr/bin/env python3
"""Independent indicator components and reference accounting; not native runtime."""
from __future__ import annotations
import argparse, ctypes, hashlib, json, subprocess, sys, time
from pathlib import Path
import numpy as np
import talib
from anchor_reference import portfolio, cash_trace
KINDS=['sma','ema','rsi','macd','bollinger','stochastic','atr','roc','cci','vwap']
NAMES='net_return_pct,gross_return_pct,cagr_pct,max_drawdown_pct,sharpe_annualized_naive,trades,exposure_pct,mean_bps_per_bar,mean_trade_bps,periods'.split(',')
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def columns(data):return {k:data[:,i+1] for i,k in enumerate(('open','high','low','close','volume'))}
def safe(a,b,zero=False):
    with np.errstate(divide='ignore',invalid='ignore',over='ignore'):
        return np.where(np.isfinite(a)&np.isfinite(b),np.where(abs(b)>1e-12,a/b,0. if zero else np.nan),np.nan)
def wilder(x,n):
    out=np.full(len(x),np.nan);run=0;seed=0.;state=0.
    for t,v in enumerate(x):
        if not np.isfinite(v):run=0;seed=0.;state=0.;continue
        if run<n:
            seed+=v;run+=1
            if run==n:state=seed/n;out[t]=state
        else:state=(1/n)*v+(1-1/n)*state;out[t]=state
    return out
def mad(x,n):
    out=np.full(len(x),np.nan)
    if len(x)>=n:
        w=np.lib.stride_tricks.sliding_window_view(x,n)
        m=w.mean(axis=1);out[n-1:]=abs(w-m[:,None]).mean(axis=1)
    return out
def stripe(kind,n,a,cols):
    c=cols['close'];h=cols['high'];l=cols['low'];v=cols['volume']
    p=c if a==0 else c+a*(cols['open']-c)
    if kind=='sma':return p,talib.SMA(p,n),talib.SMA(p,n+1),p
    if kind=='ema':return p,talib.EMA(p,n),talib.EMA(p,n+1),p
    if kind=='rsi':
        d=np.r_[np.nan,np.diff(p)];z=abs(d);u=z+d
        return wilder(u,n),wilder(z,n),wilder(u,n+1),wilder(z,n+1)
    if kind=='macd':
        shifted=np.r_[np.full(26-n,np.nan),talib.EMA(p[26-n:],n)]
        line=shifted-talib.EMA(p,26)
        return p,line,talib.EMA(line,9),talib.EMA(line,10)
    if kind=='bollinger':return p,talib.SMA(p,n),talib.STDDEV(p,n,1.),talib.STDDEV(p,n+1,1.)
    if kind=='stochastic':
        low=talib.MIN(l,n);high=talib.MAX(h,n)
        fast=safe(p-low,(high-low)/100.,True);k=talib.SMA(fast,3)
        return k,talib.SMA(k,3),talib.SMA(k,4),p
    if kind=='atr':return p,talib.ATR(h,l,p,n),talib.ATR(h,l,p,n+1),p
    if kind=='roc':return p,np.r_[np.full(n,np.nan),p[:-n]],np.r_[np.full(n+1,np.nan),p[:-n-1]],p
    tp=(h+l+p)/3
    if kind=='cci':return tp,talib.SMA(tp,n),mad(tp,n),mad(tp,n+1)
    if kind=='vwap':return p,safe(talib.SMA(tp*v,n),talib.SMA(v,n)),safe(talib.SMA(tp*v,n+1),talib.SMA(v,n+1)),p
    raise ValueError(kind)
def output(kind,ids,b):
    p,x,y,z=ids
    mix=lambda a,c: a if b==0 else a+b*(c-a)
    if kind in ('sma','ema','roc','vwap'):return safe(p,mix(x,y))
    if kind=='rsi':return safe(mix(p,y),mix(x,z),True)
    if kind=='macd':return safe(x-mix(y,z),p)
    if kind=='bollinger':return safe(x-p,mix(y,z))
    if kind=='stochastic':return (p-mix(x,y))/100
    if kind=='atr':return safe(mix(x,y),p)
    if kind=='cci':return safe(p-x,mix(y,z)*.015,True)/100
    raise ValueError(kind)

def raw_anchor(kind,n,cols):
    c=cols['close'];h=cols['high'];l=cols['low'];v=cols['volume']
    if kind=='sma':return c/talib.SMA(c,n)
    if kind=='ema':return c/talib.EMA(c,n)
    if kind=='rsi':return talib.RSI(c,n)/50
    if kind=='macd':return talib.MACD(c,n,26,9)[2]/c
    if kind=='bollinger':
        up,m,low=talib.BBANDS(c,n,2.,2.,0);return safe(m-c,(up-m)/2)
    if kind=='stochastic':
        k,d=talib.STOCH(h,l,c,n,3,0,3,0);return (k-d)/100
    if kind=='atr':return talib.ATR(h,l,c,n)/c
    if kind=='roc':return talib.ROC(c,n)/100+1
    if kind=='cci':return talib.CCI(h,l,c,n)/100
    if kind=='vwap':return safe(c,safe(talib.SUM(((h+l+c)/3)*v,n),talib.SUM(v,n)))
    raise ValueError(kind)
class CashOracle:
    def __init__(self,build):
        build=Path(build);build.mkdir(parents=True,exist_ok=True)
        self.source=Path(__file__).with_name('cohort_ledger.c')
        self.library=build/('ledger.dylib' if sys.platform=='darwin' else 'ledger.so')
        subprocess.run(['cc','-O3','-std=c11','-ffp-contract=off','-fPIC','-shared',str(self.source),'-lm','-o',str(self.library)],check=True)
        self.lib=ctypes.CDLL(str(self.library.resolve()));self.fn=self.lib.cohort_ledger
        arr=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        self.fn.argtypes=[arr,ctypes.c_size_t,arr,arr,ctypes.c_size_t,ctypes.c_double,ctypes.c_double,ctypes.c_double,arr]
        self.fn.restype=ctypes.c_int
    def score(self,x,prices,cuts,fee,slip,interval):
        x=np.ascontiguousarray(x,dtype='float64');prices=np.ascontiguousarray(prices,dtype='float64');cuts=np.ascontiguousarray(cuts,dtype='float64')
        if len(prices)!=len(x)+1:raise ValueError('price/decision alignment')
        result=np.empty((len(cuts),10),dtype='float64')
        if self.fn(x,len(x),prices,cuts,len(cuts),fee,slip,interval,result):raise ValueError('oracle failure')
        return result

def check_values(a,b,label,atol=1e-8):
    if not np.array_equal(np.isfinite(a),np.isfinite(b)):raise ValueError('validity: '+label)
    if not np.allclose(a,b,rtol=1e-9,atol=atol,equal_nan=True):raise ValueError('numeric: '+label)
    good=np.isfinite(a)&np.isfinite(b)
    return float(np.max(np.abs(a[good]-b[good]),initial=0.))
def setup():
    if talib.__version__!='0.6.8':raise ValueError('reference requires pinned wrapper0.6.8')
    talib.set_compatibility(0)
    for name in ('EMA','RSI','ATR'):talib.set_unstable_period(name,0)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--data',required=True);args=p.parse_args();setup()
    root=Path(args.run);m=json.loads((root/'manifest.json').read_text());clock=time.perf_counter()
    if digest(args.data)!=m['data_sha256']:raise ValueError('data fingerprint')
    d=np.loadtxt(args.data,delimiter=',',skiprows=1);cols=columns(d);lo=m['start_index'];hi=m['end_index'];prices=cols['open'][lo+1:hi]
    native=np.fromfile(root/'features.bin',dtype='<f8').reshape(len(m['requests']),m['rows'])
    metrics=np.fromfile(root/'metrics.bin',dtype='<f8').reshape(-1,2,10)
    traces=np.memmap(root/'traces.bin',mode='r',dtype='<f8',shape=(len(m['requests']),2,hi-lo-2,7))
    oracle=CashOracle(root/'oracle');feature_error=metric_error=trace_error=0.;rows=[]
    for i,r in enumerate(m['requests']):
        q=output(r['family'],stripe(r['family'],r['n'],r['a'],cols),r['b']);x=q-r['c']
        feature_error=max(feature_error,check_values(x,native[i],r['family']))
        if not np.array_equal(np.isfinite(x)&(x>0),np.isfinite(native[i])&(native[i]>0)):raise ValueError('mask mismatch')
        if r['case']=='anchor':
            raw=raw_anchor(r['family'],r['n'],cols)-r['c']
            feature_error=max(feature_error,check_values(raw,x,r['family']+' raw reference'))
            if not np.array_equal(np.isfinite(raw)&(raw>0),np.isfinite(x)&(x>0)):raise ValueError('raw anchor mask mismatch')
        pos=np.isfinite(x[lo:hi-2])&(x[lo:hi-2]>0)
        for ci,(fee,slip) in enumerate([(0.0005,0.0005),(.001,.001)]):
            direct=portfolio(prices,pos,fee,slip,m['interval']);c_ref=oracle.score(q[lo:hi-2],prices,[r['c']],fee,slip,m['interval'])[0]
            metric_error=max(metric_error,check_values(direct,metrics[i,ci],r['family']+' metrics',1e-7),check_values(c_ref,direct,'C vs NumPy',1e-7))
            if not np.array_equal(direct[[5,9]],metrics[i,ci,[5,9]]) or not np.array_equal(c_ref[[5,9]],direct[[5,9]]):raise ValueError('counts')
            independent=cash_trace(prices,pos,fee,slip)
            trace_error=max(trace_error,check_values(independent,traces[i,ci],r['family']+' trace'))
            if not np.array_equal(independent[:,:3],traces[i,ci,:,:3]):raise ValueError('trade events')
        rows.append({'family':r['family'],'case':r['case'],'status':'PASS'})
    result={'status':'PASS','families':10,'programs':len(rows),'metric_sets':len(rows)*2,'all_values_validity_masks_and_traces_checked':True,'mask_disagreements':0,'trade_event_disagreements':0,'max_feature_error':feature_error,'max_metric_error':metric_error,'max_trace_error':trace_error,'oracle_c_sha256':digest(oracle.source),'talib_wrapper':talib.__version__,'talib_c':talib.__ta_version__.decode(),'seconds':time.perf_counter()-clock,'cases':rows}
    evidence=root/'verification.json'
    if evidence.exists():raise ValueError('verification already exists')
    evidence.write_text(json.dumps(result,indent=2)+'\n')
    fields={'version':'cohort-v1','status':'PASS','data_sha256':m['data_sha256'],'engine_sha256':m['engine_sha256'],'catalog_sha256':m['catalog_sha256']}
    for f in ['manifest.json','verification.json','metrics.bin','features.bin','traces.bin']:fields[f+'_sha256']=digest(root/f)
    text='\n'.join(k+'='+v for k,v in fields.items())+'\n';(root/'gate.txt').write_text(text);(root/'gate.txt.sha256').write_text(hashlib.sha256(text.encode()).hexdigest()+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
