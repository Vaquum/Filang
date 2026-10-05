#!/usr/bin/env python3
"""Independent dense predicate memberships and checkpoint-winner accounting.
All memberships are checked. Large-run checkpoint-winner metrics are a subset
of resolved regions, never described as an exhaustive large metric replay.
"""
from __future__ import annotations
import argparse, ctypes, hashlib, json, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
from cohort_reference import stripe, output, columns, setup, check_values
from verify_joint import qualified, packed, logic, parse, Oracle, sha
from anchor_reference import portfolio

def settings(path):
    return dict(l.split('=',1) for l in Path(path).read_text().splitlines() if l and not l.startswith('#'))

def sealed(path):
    path=Path(path);size=path.stat().st_size
    if size<64:raise ValueError('short sealed file')
    h=hashlib.sha256();remaining=size-64
    with path.open('rb') as f:
        while remaining:
            b=f.read(min(1<<20,remaining))
            if not b:raise ValueError('truncated artifact')
            h.update(b);remaining-=len(b)
        if f.read(64)!=h.hexdigest().encode():raise ValueError('artifact checksum mismatch: '+str(path))
    return h.hexdigest(),size-64

def load_bank(path):
    digest,size=sealed(path)
    with Path(path).open('rb') as f:header=f.read(88)
    if header[:8]!=b'FDBANK01':raise ValueError('bank version')
    rows,count=struct.unpack('<2Q',header[72:88]);words=(rows+63)//64
    dt=np.dtype([('count','<u8',(2,)),('first','<u8',(3,)),('bits','<u8',(words,)),('valid','<u8',(words,))])
    if size!=88+count*dt.itemsize:raise ValueError('bank size')
    states=np.memmap(path,mode='r',offset=88,dtype=dt,shape=(count,))
    if np.any(states['count'][:,1]):raise ValueError('verifier per-family multiplicity cap')
    return states,rows,header[8:72].decode(),digest

DEFAULTS={'sma':(200,999000,1,1000000),'ema':(24,999000,1,1000000),'rsi':(14,998000,2,1000000),'macd':(12,-1000,1,10000000),'bollinger':(20,198000,2,100000),'stochastic':(14,-1000,1,1000000),'atr':(14,99000,1,10000000),'roc':(14,999000,1,1000000),'cci':(20,99000,1,100000),'vwap':(20,999000,1,1000000)}
def cutoff_grid(kind,count):
    _,start,step,den=DEFAULTS[kind];scale=count-1
    return np.array([float(start*scale+i*step*2000)/float(den*scale) for i in range(count)])
def parameters(cfg,kind,atom):
    width=int(cfg['coefficients']);stride=40//(width-1)
    return DEFAULTS[kind][0]-1+atom//(width*width),((atom//width)%width*stride-20)/2000.,(atom%width*stride)/400.
def numeric_qualifier(x,q):
    if q=='plain':return x
    name,n=q.split(':');n=int(n);out=np.full(len(x),np.nan)
    if n<=len(x):
        windows=np.lib.stride_tricks.sliding_window_view(x,n)
        values=np.min(windows,axis=1) if name=='persist' else np.max(windows,axis=1)
        out[n-1:]=np.where(np.isfinite(windows).all(axis=1),values,np.nan)
    return out

def verify_bank(root,f):
    root=Path(root);cfg=settings(root/'experiment.cfg');setup();clock=time.perf_counter()
    kinds=cfg['families'].split(',');kind=kinds[f];width=int(cfg['coefficients']);cutoffs=int(cfg['cutoffs']);quals=cfg['qualifiers'].split(',')
    raw=Path(cfg['data']).read_bytes();data=np.loadtxt(cfg['data'],delimiter=',',skiprows=1);cols=columns(data)
    lo=int(np.searchsorted(data[:,0],int(np.datetime64(cfg['start'],'s').astype('int64'))));length=len(data)-lo-2
    states,rows,context,bhash=load_bank(root/'banks'/f'bank-{f:02}.bin')
    if rows!=length:raise ValueError('bank timeline')
    mpath=root/'banks'/f'members-{f:02}.bin';mhash,size=sealed(mpath)
    with mpath.open('rb') as fobj:head=fobj.read(104)
    if head[:8]!=b'FDALIAS1' or head[8:72].decode()!=context or struct.unpack('<4Q',head[72:])!=(3*width*width,len(quals),cutoffs,length):raise ValueError('membership context')
    members=np.memmap(mpath,mode='r',offset=104,dtype='<u8',shape=((size-104)//40,5))
    if (size-104)%40:raise ValueError('member size')
    cc=cutoff_grid(kind,cutoffs);totals=np.zeros(len(states),dtype=np.uint64);first=np.zeros((len(states),3),dtype=np.uint64)
    seen=np.zeros(len(states),dtype=bool);cursor=0;direct_checks=0;cell_checks=0;previous=None
    for atom in range(3*width*width):
        n,a,b=parameters(cfg,kind,atom)
        if previous!=(n,a):ids=stripe(kind,n,a,cols);previous=(n,a)
        x=output(kind,ids,b)
        for qi,qual in enumerate(quals):
            z=numeric_qualifier(x,qual)[lo:-2];valid=np.isfinite(z);words=packed(valid&(z>cc[0]));vwords=packed(valid)
            ix=np.flatnonzero(valid&(z>cc[0])&(z<=cc[-1]));qs=np.searchsorted(cc,z[ix],side='left');order=np.lexsort((ix,qs));ix=ix[order];qs=qs[order]
            cuts=np.r_[0,np.unique(qs),cutoffs];block=members[cursor:cursor+len(cuts)-1]
            if len(block)!=len(cuts)-1 or np.any(block[:,0]!=atom) or np.any(block[:,1]!=qi) or not np.array_equal(block[:,2],cuts[:-1]) or not np.array_equal(block[:,3],cuts[1:]):raise ValueError(f'membership partition {kind} {atom} {qual}')
            event=0
            for j,row in enumerate(block):
                sid=int(row[4]);begin=int(row[2]);end=int(row[3])
                while event<len(qs) and qs[event]<=begin:
                    t=int(ix[event]);words[t//64]&=~np.uint64(1<< (t%64));event+=1
                if not np.array_equal(words,states['bits'][sid]) or not np.array_equal(vwords,states['valid'][sid]):raise ValueError(f'predicate mismatch {kind} atom{atom} q{qi} cutoff{begin}')
                if not seen[sid]:first[sid]=[atom,qi,begin];seen[sid]=True
                totals[sid]+=np.uint64(end-begin);cell_checks+=1
                if atom%128==0 and j in [0,len(block)//2,len(block)-1]:
                    reference=qualified((np.isfinite(x)&(x>cc[begin]),np.isfinite(x)),qual)
                    if not np.array_equal(packed(reference[0][lo:-2]),words) or not np.array_equal(packed(reference[1][lo:-2]),vwords):raise ValueError('unsimplified temporal oracle mismatch')
                    direct_checks+=1
            cursor+=len(block)
    if cursor!=len(members) or not seen.all() or not np.array_equal(totals,states['count'][:,0]) or not np.array_equal(first,states['first']):raise ValueError('state weights/identity/coverage mismatch')
    keys={(s['bits'].tobytes(),s['valid'].tobytes()) for s in states}
    if len(keys)!=len(states):raise ValueError('duplicate state identities')
    result={'status':'PASS','family':kind,'numerical_parameter_constructions':3*width*width,'predicate_regions_verified':cell_checks,'distinct_states_verified':len(states),'logical_condition_addresses':str(sum(map(int,totals))),'all_membership_masks_validity_and_counts_checked':True,'mask_disagreements':0,'unsimplified_temporal_crosschecks':direct_checks,'bank_body_sha256':bhash,'members_body_sha256':mhash,'data_sha256':hashlib.sha256(raw).hexdigest(),'seconds':time.perf_counter()-clock}
    dest=root/'verification';dest.mkdir(exist_ok=True);(dest/f'bank-{f:02}.json').write_text(json.dumps(result,indent=2)+'\n')
    print(kind,'verified',cell_checks,'predicate regions',flush=True);return result


def ordered(states):
    return np.asarray(sorted(range(len(states)), key=lambda i: (tuple(states[i]['bits']), tuple(states[i]['valid']), i)), dtype=np.int64)


def frontier_ranges(count,block):
    result=[]
    def split(lo,hi):
        if hi-lo<=block:result.append((lo,hi))
        else:
            mid=lo+(hi-lo)//2;split(lo,mid);split(mid,hi)
    split(0,count)
    return result


def task_record(path,context):
    digest,size=sealed(path)
    if size!=376:raise ValueError('checkpoint byte size')
    raw=Path(path).read_bytes()[:size]
    if raw[:8]!=b'FDTASK01' or raw[8:72].decode()!=context:raise ValueError('checkpoint context')
    keys=['id','node_pairs','proved','leaves','bound_words','regions']
    r=dict(zip(keys,struct.unpack_from('<6Q',raw,72)))
    r['signature_pairs']=int.from_bytes(raw[120:136],'little');r['logical']=int.from_bytes(raw[136:152],'little')
    r['digest']=raw[152:216].decode();r['families']=struct.unpack_from('<2Q',raw,216);r['template']=struct.unpack_from('<Q',raw,232)[0]
    r['coordinates']=np.asarray(struct.unpack_from('<6Q',raw,240),dtype=np.uint64).reshape(2,3)
    r['score']=struct.unpack_from('<d',raw,288)[0];r['metrics']=np.frombuffer(raw,dtype='<f8',offset=296,count=10).copy()
    if r['regions']!=r['proved']+r['leaves'] or not np.isfinite(r['score']):raise ValueError('checkpoint counts/score')
    return r,raw


class CoverageOracle:
    def __init__(self,build,compile=False):
        build=Path(build);build.mkdir(exist_ok=True,parents=True)
        self.source=Path(__file__).with_name('dense_coverage.c')
        self.path=build/('coverage.dylib' if sys.platform=='darwin' else 'coverage.so')
        if compile:subprocess.run(['cc','-O3','-std=c11','-fPIC','-shared',str(self.source),'-o',str(self.path)],check=True)
        self.lib=ctypes.CDLL(str(self.path.resolve()));self.fn=self.lib.dense_coverage
        arr=np.ctypeslib.ndpointer(dtype=np.uint64,flags='C_CONTIGUOUS');z=ctypes.c_size_t
        self.fn.argtypes=[arr,arr,arr,z,arr,arr,arr,z,z,z,ctypes.c_uint,ctypes.c_int,arr,z,ctypes.POINTER(z)];self.fn.restype=ctypes.c_int
    def replay(self,a,b,block,truth,proof):
        arrays=[np.ascontiguousarray(s[name],dtype=np.uint64) for s in (a,b) for name in ('bits','valid')]
        ac=np.ascontiguousarray(a['count'][:,0]);bc=np.ascontiguousarray(b['count'][:,0])
        out=np.empty((len(a),11),dtype=np.uint64);used=ctypes.c_size_t()
        err=self.fn(arrays[0],arrays[1],ac,len(a),arrays[2],arrays[3],bc,len(b),arrays[0].shape[1],block,truth,int(proof),out,len(a),ctypes.byref(used))
        if err:raise ValueError(f'coverage oracle error {err}')
        return out[:used.value]


def truth_table(text):
    e=parse(text);return sum(int(logic(e,[(bool(i&2),True),(bool(i&1),True)])[0])<<i for i in range(4))


def word_logic(text,a,b):
    return logic(parse(text),[(a['bits'],a['valid']),(b['bits'],b['valid'])])[0]


def pair_job(args):
    root,fa,fb,offset,replay_products=args;root=Path(root);clock=time.perf_counter();cfg=settings(root/'experiment.cfg')
    s=json.loads((root/'summary.json').read_text());rules=cfg['rules'].split(';');kinds=cfg['families'].split(',');block=int(cfg['task_states'])
    aa,rows,_,_=load_bank(root/'banks'/f'bank-{fa:02}.bin');bb,rows_b,_,_=load_bank(root/'banks'/f'bank-{fb:02}.bin')
    if rows_b!=rows:raise ValueError('pair timeline')
    a=aa[ordered(aa)];b=bb[ordered(bb)];front=frontier_ranges(len(a),block)
    byfirsta={tuple(map(int,e['first'])):i for i,e in enumerate(aa)};byfirstb={tuple(map(int,e['first'])):i for i,e in enumerate(bb)}
    sorted_a={tuple(map(int,e['first'])):i for i,e in enumerate(a)}
    data=np.loadtxt(cfg['data'],delimiter=',',skiprows=1);lo=len(data)-rows-2;prices=np.ascontiguousarray(data[lo+1:,1])
    oracle=Oracle(root/'verification'/f'cash-{fa:02}-{fb:02}');coverage=CoverageOracle(root/'verification'/'coverage-build')
    masks=[];want=[];keys=[];max_error=0.;checked=0;logical=signatures=regions=0
    for template,text in enumerate(rules):
        replay=coverage.replay(a,b,block,truth_table(text),s['proof']) if replay_products else None
        if replay is not None and len(replay)!=len(front):raise ValueError('independent task partition')
        for j,(leftlo,lefthi) in enumerate(front):
            tid=offset+template*len(front)+j;r,_=task_record(root/'tasks'/f'task-{tid:08}.chk',s['context_sha256'])
            expected=int(sum(map(int,a['count'][leftlo:lefthi,0])))*int(sum(map(int,b['count'][:,0])))
            if (r['id'],r['families'],r['template'],r['logical'],r['signature_pairs'])!=(tid,(fa,fb),template,expected,(lefthi-leftlo)*len(b)):raise ValueError('task domain or weighted coverage mismatch')
            if replay is not None:
                got=list(map(int,replay[j]));wantcounts=[leftlo,lefthi,r['node_pairs'],r['proved'],r['leaves'],r['bound_words'],r['regions'],r['signature_pairs']&((1<<64)-1),r['signature_pairs']>>64,r['logical']&((1<<64)-1),r['logical']>>64]
                if got!=wantcounts:raise ValueError(f'independent product certificate/count mismatch task {tid}')
            coa=tuple(map(int,r['coordinates'][0]));cob=tuple(map(int,r['coordinates'][1]))
            if coa not in byfirsta or cob not in byfirstb or not leftlo<=sorted_a[coa]<lefthi:raise ValueError('checkpoint representative outside task')
            masks.append(word_logic(text,aa[byfirsta[coa]],bb[byfirstb[cob]]));want.append(r['metrics']);keys.append(tid)
            logical+=r['logical'];signatures+=r['signature_pairs'];regions+=r['regions'];checked+=1
    expected=oracle.score(np.asarray(masks),rows,prices,float(cfg['fee_bps']),float(cfg['slip_bps']),14400)
    want=np.asarray(want);max_error=check_values(expected,want,'all checkpoint representatives',1e-7)
    if not np.array_equal(expected[:,[5,9]],want[:,[5,9]]):raise ValueError('checkpoint count mismatch')
    # Separate Python chronological arithmetic for systematic first/last representatives.
    for j in sorted(set([0,len(masks)-1])):
        pos=np.unpackbits(np.asarray(masks[j],dtype='<u8').view('u1'),bitorder='little')[:rows].astype(bool)
        reference=portfolio(prices,pos,float(cfg['fee_bps'])/10000,float(cfg['slip_bps'])/10000,14400)
        max_error=max(max_error,check_values(reference,want[j],'NumPy task representative',1e-7))
    result={'families':[kinds[fa],kinds[fb]],'status':'PASS','checkpoints_checked':checked,'product_partition_replayed':bool(replay_products),'logical_coverage':str(logical),'signature_pairs':str(signatures),'metric_regions_in_domain':regions,'independently_replayed_metrics':len(masks),'all_large_region_metrics_replayed':False,'max_metric_absolute_error':max_error,'seconds':time.perf_counter()-clock}
    (root/'verification'/f'pair-{fa:02}-{fb:02}.json').write_text(json.dumps(result,indent=2)+'\n')
    print('verified pair',kinds[fa],kinds[fb],checked,'checkpoints',flush=True);return result


def verify_tasks(root,workers=4,replay_products=True):
    from concurrent.futures import ProcessPoolExecutor
    root=Path(root);cfg=settings(root/'experiment.cfg');s=json.loads((root/'summary.json').read_text())
    if s['status']!='PASS' or not s['coverage_complete']:raise ValueError('incomplete run')
    if sha(cfg['data'])!=s['data_sha256']:raise ValueError('dataset changed')
    raw=(root/'experiment.cfg').read_text();ct=hashlib.sha256(f"filang-dense-v1|{raw}|{s['data_sha256']}|{s['engine_sha256']}|{s['backend']}|{str(s['proof']).lower()}|{str(s['capture']).lower()}".encode()).hexdigest()
    sealed(root/'context.chk')
    if ct!=s['context_sha256'] or (root/'context.chk').read_bytes()[:64].decode()!=ct:raise ValueError('whole context mismatch')
    CoverageOracle(root/'verification'/'coverage-build',compile=True)
    kinds=cfg['families'].split(',');counts=[];offset=0;requests=[]
    for f in range(len(kinds)):
        states,_,bcontext,_=load_bank(root/'banks'/f'bank-{f:02}.bin')
        if bcontext!=hashlib.sha256(f'{ct}|family|{f}'.encode()).hexdigest():raise ValueError('bank context mismatch')
        counts.append(len(frontier_ranges(len(states),int(cfg['task_states']))))
    for fa in range(len(kinds)):
        for fb in range(len(kinds)):
            if fa==fb:continue
            requests.append((str(root),fa,fb,offset,replay_products));offset+=counts[fa]*len(cfg['rules'].split(';'))
    if offset!=s['completed_tasks'] or len(list((root/'tasks').glob('*.chk')))!=offset:raise ValueError('missing/extra checkpoint')
    h=hashlib.sha256()
    for i in range(offset):_,r=task_record(root/'tasks'/f'task-{i:08}.chk',ct);h.update(r)
    if h.hexdigest()!=s['result_digest']:raise ValueError('canonical task digest mismatch')
    with ProcessPoolExecutor(max_workers=workers) as pool:results=list(pool.map(pair_job,requests))
    if sum(int(r['logical_coverage']) for r in results)!=int(s['requested_strategy_addresses']):raise ValueError('whole logical coverage mismatch')
    if sum(r['metric_regions_in_domain'] for r in results)!=s['metric_regions_evaluated']:raise ValueError('region total mismatch')
    result={'status':'PASS','role':'independent_all_product_coverage_and_checkpoint_representatives','all_task_checksums_and_coverage_checked':True,'all_product_partitions_replayed':bool(replay_products),'checkpoint_metric_replays':offset,'large_region_metric_replays_exhaustive':False,'max_metric_absolute_error':max(r['max_metric_absolute_error'] for r in results),'logical_addresses':s['requested_strategy_addresses'],'source_sha256':sha(__file__),'coverage_oracle_sha256':sha(Path(__file__).with_name('dense_coverage.c')),'pairs':results}
    (root/'verification'/'tasks.json').write_text(json.dumps(result,indent=2)+'\n');return result


def bank_job(args):
    return verify_bank(*args)


def main():
    from concurrent.futures import ProcessPoolExecutor
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True);p.add_argument('--stage',choices=['banks','tasks','all'],default='all')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--skip-product-replay',action='store_true')
    a=p.parse_args()
    if not 1<=a.workers<=8:raise ValueError('verification workers must be 1..8')
    root=Path(a.run);cfg=settings(root/'experiment.cfg');dest=root/'verification';dest.mkdir(exist_ok=True)
    if a.stage in ('banks','all'):
        with ProcessPoolExecutor(max_workers=a.workers) as pool:rows=list(pool.map(bank_job,[(str(root),f) for f in range(len(cfg['families'].split(',')))]))
        (dest/'banks.json').write_text(json.dumps({'status':'PASS','all_memberships_checked':True,'families':rows},indent=2)+'\n')
    if a.stage in ('tasks','all'):
        r=verify_tasks(root,a.workers,not a.skip_product_replay)
        print(json.dumps({k:v for k,v in r.items() if k!='pairs'},indent=2))


if __name__=='__main__':main()
