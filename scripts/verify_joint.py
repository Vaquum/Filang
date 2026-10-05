#!/usr/bin/env python3
"""Independent expressions, conservative-validity Boolean logic, exact box coverage,
and explicit cash/share accounting. No native tree/cofactor implementation used.
The optional C file only accelerates independent sequential ledger verification.
"""
from __future__ import annotations
import argparse, ctypes, hashlib, itertools, json, re, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
import talib
from anchor_reference import portfolio
from cohort_reference import CashOracle, check_values, setup

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def parse(text):
    tokens=iter(re.findall(r'\(|\)|[^\s()]+',text))
    def read(token=None):
        token=next(tokens) if token is None else token
        if token!='(':return (token,)
        op=next(tokens)
        if op=='constant':node=(op,int(next(tokens),16))
        elif op in ('abs','neg','not','onset'):node=(op,read())
        elif op in ('lag','skip','diff','mean','mean_sum','std_sum','std','mad_mean','min','max','ema','wilder','persist','recent'):node=(op,int(next(tokens)),read())
        else:node=(op,read(),read())
        if next(tokens)!=')':raise ValueError('unclosed expression')
        return node
    x=read()
    if next(tokens,None) is not None:raise ValueError('trailing tokens')
    return x

def atom(e,cols,cache):
    if e in cache:return cache[e]
    op=e[0];n=len(cols['close'])
    if op in cols:z=cols[op]
    elif op=='constant':z=np.full(n,struct.unpack('>d',e[1].to_bytes(8,'big'))[0])
    elif op in ('abs','neg'):
        a=atom(e[1],cols,cache);z=abs(a) if op=='abs' else -a
    elif op in ('add','sub','mul','div','div0','min2','max2'):
        a,b=(atom(x,cols,cache) for x in e[1:]);valid=np.isfinite(a)&np.isfinite(b)
        with np.errstate(all='ignore'):
            if op=='add':z=a+b
            elif op=='sub':z=a-b
            elif op=='mul':z=a*b
            elif op=='min2':z=np.minimum(a,b)
            elif op=='max2':z=np.maximum(a,b)
            else:z=np.where(abs(b)>1e-12,a/b,0. if op=='div0' else np.nan)
        z=np.where(valid,z,np.nan)
    else:
        w=e[1];a=atom(e[2],cols,cache);z=np.full(n,np.nan)
        if op=='skip':z[w:]=a[w:]
        elif op in ('lag','diff'):
            if w<n:z[w:]=a[:-w] if op=='lag' else a[w:]-a[:-w]
        elif op in ('mean_sum','std_sum'):
            # Raw-profile output order is explicit. TA-Lib supplies the mean on
            # each finite run, avoiding an independent rolling-state imitation.
            if op=='mean_sum':
                finite=np.isfinite(a);starts=np.flatnonzero(finite&~np.r_[False,finite[:-1]]);ends=np.flatnonzero(finite&~np.r_[finite[1:],False])+1
                for lo,hi in zip(starts,ends):z[lo:hi]=a[lo:hi] if w==1 else talib.SMA(a[lo:hi],w)
            else:
                total=square=0.;run=0
                for t,v in enumerate(a):
                    if not np.isfinite(v):total=square=0.;run=0;continue
                    run+=1;total+=v;square+=v*v
                    if run>=w:
                        mu=total/w;var=square/w-mu*mu;total-=a[t+1-w];square-=a[t+1-w]*a[t+1-w];z[t]=0. if var<1e-14 else np.sqrt(var)
        elif op in ('mean','std','min','max','mad_mean'):
            if w<=n:
                windows=np.lib.stride_tricks.sliding_window_view(a,w);valid=np.isfinite(windows).all(axis=1)
                if op=='mad_mean':
                    # Mathematical full-window oracle, not the native stream state.
                    mu=np.mean(windows,axis=1);values=np.mean(abs(windows-mu[:,None]),axis=1)
                else:values={'mean':np.mean,'std':np.std,'min':np.min,'max':np.max}[op](windows,axis=1)
                z[w-1:]=np.where(valid,values,np.nan)
        elif op in ('ema','wilder'):
            alpha=2./(w+1) if op=='ema' else 1./w;run=0;seed=state=0.
            for t,v in enumerate(a):
                if not np.isfinite(v):run=0;seed=state=0.;continue
                if run<w:
                    seed+=v;run+=1
                    if run==w:state=seed/w;z[t]=state
                else:state=alpha*v+(1.-alpha)*state;z[t]=state
        else:raise ValueError('unsupported numerical oracle '+op)
    z=np.where(np.isfinite(z),z,np.nan);cache[e]=z;return z

def qualified(pair,name):
    x,v=pair
    if name=='plain':return x,v
    if name=='onset':return np.r_[False,x[1:]&~x[:-1]]&np.r_[False,v[1:]&v[:-1]],np.r_[False,v[1:]&v[:-1]]
    name,n=name.split(':');n=int(n);a=np.r_[0,np.cumsum(x,dtype=np.int64)];b=np.r_[0,np.cumsum(v,dtype=np.int64)];out=np.zeros(len(x),bool);valid=out.copy()
    if n<=len(x):valid[n-1:]=(b[n:]-b[:-n])==n;counts=a[n:]-a[:-n];out[n-1:]=((counts==n) if name=='persist' else (counts>0))&valid[n-1:]
    return out,valid

def compare(a,b,name):return {'gt':np.greater,'ge':np.greater_equal,'lt':np.less,'le':np.less_equal,'eq':np.equal,'ne':np.not_equal}[name](a,b)
def predicate(spec,x,y,cut):
    parts=spec['predicate'].split(':');v=np.isfinite(x)
    if parts[0]=='threshold':b=compare(x,cut,parts[1])&v
    elif parts[0]=='relative':v&=np.isfinite(y);b=compare(x,y,parts[1])&v
    elif parts[0]=='cross':
        v&=np.isfinite(y);v&=np.r_[False,v[:-1]];b=np.r_[False,((x[1:]>y[1:])&(x[:-1]<=y[:-1])) if parts[1]=='above' else ((x[1:]<y[1:])&(x[:-1]>=y[:-1]))]&v
    elif parts[0]=='slope':
        k=int(parts[2]);old=np.r_[np.full(k,np.nan),x[:-k]] if k<len(x) else np.full(len(x),np.nan);v&=np.isfinite(old);b=compare(x,old,'gt' if parts[1]=='rising' else 'lt')&v
    else:raise ValueError('predicate oracle')
    for q in spec['qualifiers'].split('+'):b,v=qualified((b,v),q)
    return b,v

def logic(e,inputs):
    op=e[0]
    if op.startswith('s'):return inputs[int(op[1:])]
    if op=='not':x,v=logic(e[1],inputs);return (~x)&v,v
    if op=='onset':return qualified(logic(e[1],inputs),'onset')
    if op in ('persist','recent'):return qualified(logic(e[2],inputs),op+':'+str(e[1]))
    x,v=logic(e[1],inputs);y,w=logic(e[2],inputs);valid=v&w
    if op=='and':return (x&y)&valid,valid
    if op=='or':return (x|y)&valid,valid
    raise ValueError('Boolean opcode')

def packed(bits):
    padded=np.zeros((len(bits)+63)//64*64,dtype=np.uint8);padded[:len(bits)]=bits
    return np.packbits(padded,bitorder='little').view('<u8')
class Oracle:
    def __init__(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);self.src=Path(__file__).with_name('joint_ledger.c');self.path=root/('joint.dylib' if sys.platform=='darwin' else 'joint.so')
        subprocess.run(['cc','-O3','-std=c11','-ffp-contract=off','-shared','-fPIC',str(self.src),'-lm','-o',str(self.path)],check=True)
        self.lib=ctypes.CDLL(str(self.path.resolve()));self.f=self.lib.joint_ledger
        self.f.argtypes=[np.ctypeslib.ndpointer(dtype=np.uint64,flags='C_CONTIGUOUS'),ctypes.c_size_t,np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS'),ctypes.c_size_t,ctypes.c_double,ctypes.c_double,ctypes.c_double,np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')];self.f.restype=ctypes.c_int
    def score(self,masks,n,prices,fee,slip,interval):
        masks=np.ascontiguousarray(masks,dtype=np.uint64);out=np.empty((len(masks),10));prices=np.ascontiguousarray(prices,dtype=np.float64)
        if self.f(masks,n,prices,len(masks),fee/10000,slip/10000,interval,out):raise ValueError('cash/share oracle failure')
        return out

def verify(root,out):
    setup();root=Path(root);out=Path(out);clock=time.perf_counter();m=json.loads((root/'manifest.json').read_text());summary=json.loads((root/'summary.json').read_text())
    if not m['capture'] or m['output']!='boxes' or m['plan']=='Expanded':raise ValueError('requires captured cells/cofactor box output')
    if sha(m['data'])!=m['data_sha256']:raise ValueError('input changed')
    a=np.loadtxt(m['data'],delimiter=',',skiprows=1);cols=dict(zip(['open','high','low','close','volume'],a[:,1:].T));cache={};lo=m['start_index'];hi=m['end_index'];length=hi-lo-2;options={};refcache={};option_order=[]
    with (root/'predicate-cells.bin').open('rb') as f:
        for spec in sorted(m['options'],key=lambda o:(o['slot'],o['id'])):
            name=(spec['x'],spec['y'],spec['predicate'],spec['qualifiers'],spec['grid'])
            if name not in refcache:
                x=atom(parse(spec['x']),cols,cache);y=atom(parse(spec['y']),cols,cache) if spec['y'] else None
                start,step,count,den=map(int,spec['grid'].split(':'))
                if count>100000:raise ValueError('independent verifier caps an individual grid at 100000; product may be trillions')
                values=np.array([float(start+i*step)/float(den) for i in range(count)])
                if spec['predicate'].startswith('threshold:'):
                    finite=x[np.isfinite(x)];left=np.searchsorted(values,finite,side='left');right=np.searchsorted(values,finite,side='right');cmp=spec['predicate'].split(':')[1];edges=np.unique(np.r_[0,count,left if cmp in ('gt','le') else right if cmp in ('ge','lt') else np.r_[left,right]])
                else:edges=np.array([0,1])
                cells=[]
                for begin,end in zip(edges[:-1],edges[1:]):
                    b,v=predicate(spec,x,y,values[begin]);
                    if not m['full_predicate_timeline']:b=b[lo:hi-2];v=v[lo:hi-2]
                    if cells and np.array_equal(cells[-1][2][0],b) and np.array_equal(cells[-1][2][1],v):cells[-1]=(cells[-1][0],int(end),(b,v))
                    else:cells.append((int(begin),int(end),(b,v)))
                refcache[name]=cells
            cells=refcache[name];head=f.read(40)
            if len(head)!=40:raise ValueError('truncated predicate proof')
            oid,nc,n,count,nw=struct.unpack('<5Q',head)
            if (oid,nc,n,count,nw)!=(spec['id'],len(cells),len(cells[0][2][0]),int(spec['grid'].split(':')[2]),len(packed(cells[0][2][0]))):raise ValueError('predicate proof header')
            for begin,end,pair in cells:
                if struct.unpack('<2Q',f.read(16))!=(begin,end):raise ValueError('predicate range mismatch')
                for v in pair:
                    words=np.frombuffer(f.read(8*nw),dtype='<u8')
                    if not np.array_equal(words,packed(v)):raise ValueError('predicate truth/validity mismatch '+spec['label'])
            options[oid]=(spec,cells);option_order.append(oid)
        if f.read(1):raise ValueError('trailing predicate evidence')
    dtype=np.dtype([('template','<u8'),('axes','<u8',(m['slots'],3)),('metrics','<f8',(len(m['costs']),10))]);assert dtype.itemsize==m['binary_record_bytes']
    rows=np.memmap(root/'boxes.bin',mode='r',dtype=dtype);programs=[parse(t) for t in m['templates']];slots=[[o['id'] for o in m['options'] if o['slot']==s] for s in range(m['slots'])];oracle=Oracle(root/'reference-build');cursor=covered=tuples=metric_count=checked_cells=numpy_checks=0;error=0.;pending_masks=[];pending_rows=[];prices=cols['open'][lo+1:hi]
    def flush():
        nonlocal error,metric_count,numpy_checks
        if not pending_rows:return
        block=np.asarray(pending_rows)
        for ci,(fee,slip) in enumerate(m['costs']):
            expected=oracle.score(pending_masks,length,prices,fee,slip,m['interval']);got=block[:,ci,:];error=max(error,check_values(expected,got,'compound cash/share metrics',1e-7))
            if not np.array_equal(expected[:,[5,9]],got[:,[5,9]]):raise ValueError('trade/period count mismatch')
            if metric_count%100000<1024:
                pos=np.unpackbits(np.asarray(pending_masks[0],dtype='<u8').view(np.uint8),bitorder='little')[:length].astype(bool);other=portfolio(prices,pos,fee/10000,slip/10000,m['interval']);error=max(error,check_values(other,got[0],'NumPy ledger crosscheck',1e-7));numpy_checks+=1
            metric_count+=len(block)
        pending_masks.clear();pending_rows.clear()
    for ti,program in enumerate(programs):
        for choices in itertools.product(*slots):
            if m['different_tags'] and len({options[i][0]['tag'] for i in choices})!=len(choices):continue
            tuples+=1;last=options[choices[-1]][1];last_count=int(options[choices[-1]][0]['grid'].split(':')[2]);last_starts=np.array([c[0] for c in last])
            outer=[options[i][1] for i in choices[:-1]]
            for prefix in itertools.product(*outer):
                at=0
                while at<last_count:
                    if cursor>=len(rows):raise ValueError('missing result boxes')
                    row=rows[cursor];axes=row['axes'];end=int(axes[-1,2])
                    if int(row['template'])!=ti or tuple(map(int,axes[:,0]))!=choices or int(axes[-1,1])!=at or not at<end<=last_count:raise ValueError('result ordering/coverage')
                    if [tuple(map(int,p)) for p in axes[:-1,1:]]!=[(c[0],c[1]) for c in prefix]:raise ValueError('outer parameter ranges')
                    first=int(np.searchsorted(last_starts,at));stop=int(np.searchsorted(last_starts,end));
                    if first>=len(last) or last[first][0]!=at or (end!=last_count and (stop>=len(last) or last[stop][0]!=end)):raise ValueError('last-axis partition')
                    expected=None
                    for cell in last[first:stop]:
                        b,v=logic(program,[c[2] for c in prefix]+[cell[2]]);pos=b&v
                        if m['full_predicate_timeline']:pos=pos[lo:hi-2]
                        if expected is None:expected=pos
                        elif not np.array_equal(pos,expected):raise ValueError('a box groups different compound positions')
                        checked_cells+=1
                    if expected is None:raise ValueError('empty box')
                    width=end-at
                    for c in prefix:width*=c[1]-c[0]
                    covered+=width;pending_masks.append(packed(expected));pending_rows.append(np.array(row['metrics']));cursor+=1;at=end
                    if len(pending_rows)>=512:flush()
    flush()
    if cursor!=len(rows) or covered!=m['logical_addresses'] or covered!=summary['logical_strategy_addresses']:raise ValueError('final exact coverage mismatch')
    result={'status':'PASS','logical_addresses_verified':covered,'boxes_verified':cursor,'cartesian_predicate_cells_verified':checked_cells,'alternative_tuples_verified':tuples,'predicate_options_verified':len(options),'unique_predicate_plans_verified':len(refcache),'all_compound_positions_verified':True,'all_box_metrics_verified':True,'cash_share_metric_sets':metric_count,'numpy_crosschecks':numpy_checks,'mask_disagreements':0,'max_metric_absolute_error':error,'data_sha256':m['data_sha256'],'engine_sha256':m['engine_sha256'],'boxes_sha256':sha(root/'boxes.bin'),'predicate_cells_sha256':sha(root/'predicate-cells.bin'),'oracle_source_sha256':sha(oracle.src),'seconds':time.perf_counter()-clock}
    if out.exists():raise ValueError('verification output already exists')
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True);return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--out',required=True);a=p.parse_args();verify(a.run,a.out)
