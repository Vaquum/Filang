#!/usr/bin/env python3
"""Verify disjoint template partitions, then reconcile complete campaign coverage."""
import argparse,json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from verify_joint import verify,sha

def job(arg):
    root,i=arg
    return verify(root,Path(root)/f'verification-template-{i}.json',i)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--workers',type=int,default=3);a=p.parse_args()
    if not 1<=a.workers<=8:raise ValueError('workers 1..8')
    root=Path(a.run);manifest=json.loads((root/'manifest.json').read_text());out=root/'verification.json'
    if out.exists():raise ValueError('verification already exists')
    with ProcessPoolExecutor(max_workers=a.workers) as pool:parts=list(pool.map(job,[(str(root),i) for i in range(len(manifest['templates']))]))
    if [p['templates_verified'] for p in parts]!=[[i] for i in range(len(parts))]:raise ValueError('template partition mismatch')
    logical=sum(p['logical_addresses_verified'] for p in parts);boxes=sum(p['boxes_verified'] for p in parts)
    if logical!=manifest['logical_addresses'] or boxes*manifest['binary_record_bytes']!=(root/'boxes.bin').stat().st_size:raise ValueError('incomplete aggregate coverage')
    result={'status':'PASS','all_compound_positions_verified':True,'all_box_metrics_verified':True,'all_predicate_cells_verified':True,'logical_addresses_verified':logical,'boxes_verified':boxes,'cash_share_metric_sets':sum(p['cash_share_metric_sets'] for p in parts),'numpy_crosschecks':sum(p['numpy_crosschecks'] for p in parts),'mask_disagreements':sum(p['mask_disagreements'] for p in parts),'max_metric_absolute_error':max(p['max_metric_absolute_error'] for p in parts),'engine_sha256':manifest['engine_sha256'],'data_sha256':manifest['data_sha256'],'boxes_sha256':sha(root/'boxes.bin'),'external_reference_workers':a.workers,'parts':parts}
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='parts'},indent=2))
if __name__=='__main__':main()
