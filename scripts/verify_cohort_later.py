#!/usr/bin/env python3
"""Verify frozen later replay, without selecting or altering any program."""
import argparse,json,time
from pathlib import Path
import numpy as np
from cohort_reference import setup,digest,columns,stripe,output,raw_anchor,CashOracle,portfolio,check_values,NAMES

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--discovery',required=True);p.add_argument('--later',required=True);p.add_argument('--data',default='data/btc4h/evaluation.csv');a=p.parse_args();setup();clock=time.perf_counter()
    discovery=Path(a.discovery);root=Path(a.later);index=json.loads((discovery/'discovery_index.json').read_text());data=np.loadtxt(a.data,delimiter=',',skiprows=1);cols=columns(data)
    oracle=CashOracle(root/'oracle');results=[];error=0.;feature_error=0.;count=0
    for row in index['families']:
        kind=row['family'];summary=row['summary']
        if digest(discovery/kind/'frozen.tsv')!=row['frozen_sha256']:raise ValueError('frozen file changed')
        for scenario in ['primary','stress']:
            dest=root/(kind+'-'+scenario);report=json.loads((dest/'evaluation.json').read_text())
            if report['frozen_sha256']!=row['frozen_sha256'] or report['data_sha256']!=digest(a.data):raise ValueError('replay identity mismatch')
            lo=int(np.searchsorted(data[:,0],report['evaluation_start']));hi=int(np.searchsorted(data[:,0],report['evaluation_end']));prices=cols['open'][lo+1:hi]
            fee=report['fee_bps']/10000;slip=report['slip_bps']/10000
            for candidate in report['candidates']:
                params=summary[candidate['group']]
                if params is None:raise ValueError('candidate was not selected')
                q=output(kind,stripe(kind,params['window'],params['source_weight'],cols),params['mean_weight']);x=q-params['offset']
                if candidate['group']=='anchor':check_values(raw_anchor(kind,params['window'],cols)-params['offset'],x,'raw later anchor')
                trace=np.genfromtxt(dest/(candidate['id']+'.csv'),delimiter=',',skip_header=1)
                if not np.array_equal(trace[:,0],data[lo:hi-2,0]) or not np.array_equal(trace[:,3],data[lo+1:hi-1,0]) or not np.array_equal(trace[:,4],data[lo+2:hi,0]):raise ValueError('timeline disagreement')
                f=x[lo:hi-2];pos=np.isfinite(f)&(f>0)
                feature_error=max(feature_error,check_values(f,trace[:,1],kind+' later feature'))
                if not np.array_equal(pos,trace[:,2].astype(bool)):raise ValueError('later signal disagreement')
                reference=portfolio(prices,pos,fee,slip,report['interval_seconds']);cash=oracle.score(q[lo:hi-2],prices,[params['offset']],fee,slip,report['interval_seconds'])[0]
                got=np.array([np.nan if candidate['metrics'][k] is None else candidate['metrics'][k] for k in NAMES])
                error=max(error,check_values(reference,got,kind+' later metrics',1e-7),check_values(cash,got,kind+' later cash shares',1e-7))
                if not np.array_equal(got[[5,9]],reference[[5,9]]) or not np.array_equal(got[[5,9]],cash[[5,9]]):raise ValueError('later counts')
                results.append({'family':kind,'scenario':scenario,'group':candidate['group'],'metrics':candidate['metrics'],'frozen_sha256':row['frozen_sha256']});count+=1
    result={'status':'PASS','role':'retrospective_frozen_replay_not_selection_or_untouched_confirmation','replays_verified':count,'all_recorded_timestamps_features_signals_and_metrics_checked':True,'signal_disagreements':0,'max_feature_error':feature_error,'max_metric_error':error,'seconds':time.perf_counter()-clock,'results':results}
    target=root/'verification.json'
    if target.exists():raise ValueError('verification exists')
    target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
if __name__=='__main__':main()
