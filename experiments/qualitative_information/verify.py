#!/usr/bin/env python3
"""Independent QINF-R0 audit. Deliberately never imports the producer.

Reconstructs every geometry feature directly from source OHLC, then every
annual count table, held-out prediction, log-loss, placebo, bootstrap, and
the frozen decision. A passing receipt is required for any outcome claim.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
PROTOCOL_SHA = "3f84a6331f1f6c07f3924dfefa9ede739efaa597c98448e382accc45cb2e56ea"
MODELS = ("body", "range", "joint")
PRED = ("year", "index", "timestamp", "exit_day", "lag", "y", "body",
        "range", "joint", "baseline", "p_body", "p_range", "p_joint")
NATIVE = ("index", "timestamp", "valid", "lag", "body", "range", "joint")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sec(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def read_market(path, minutes, count):
    values = []
    prev = None
    with path.open(newline="") as stream:
        rdr = csv.reader(stream)
        assert next(rdr) == ["timestamp","open","high","low","close","volume"]
        for row in rdr:
            assert len(row) == 6
            t = int(row[0])
            x = [float(s) for s in row[1:]]
            o, h, l, c, v = x
            assert t % (minutes*60) == 0 and (prev is None or t > prev)
            assert all(math.isfinite(z) for z in x)
            assert min(o,h,l,c)>0 and v>=0 and h>=max(o,c) and l<=min(o,c)
            values.append((t, o, h, l, c))
            prev=t
    assert len(values) == count
    return values


BODY = tuple((a,b) for a in (1,2) for b in (1,2))
RANGE = tuple((a,b) for a in (0,3) for b in (0,3))
JOINT = tuple(sorted(set(BODY+RANGE)))


def sign(a, b):
    return 1 if a>b else -1 if a<b else 0


def code(rank, pairs, dirs):
    output = 0
    for a, b in pairs:
        output = 3 * output + sign(rank[0][a], rank[1][b]) + 1
    for direction in dirs:
        output = 3 * output + direction + 1
    return output


def independent_geometry(new, old):
    # Absolutely no native geometry conversion or signature code is imported.
    o0, h0, l0, c0 = new[1:]
    o1, h1, l1, c1 = old[1:]
    endpoints = (
        (l0, min(o0,c0), max(o0,c0), h0),
        (l1, min(o1,c1), max(o1,c1), h1)
    )
    unique = sorted(set(endpoints[0]+endpoints[1]))
    lookup = {price:i for i,price in enumerate(unique)}
    ranks = [[lookup[price] for price in endpoints[j]] for j in (0,1)]
    dirs = [sign(c0,o0),sign(c1,o1)]
    return (
        sign(c0,c1),
        code(ranks, BODY, dirs),
        code(ranks, RANGE, []),
        code(ranks, JOINT, dirs),
    )


def check_native(path, market, minutes):
    feature = []
    valid = 0
    with path.open(newline="") as stream:
        rdr = csv.DictReader(stream, delimiter="\t")
        assert tuple(rdr.fieldnames) == NATIVE
        for i, row in enumerate(rdr):
            assert i<len(market)
            assert int(row["index"]) == i and int(row["timestamp"]) == market[i][0]
            is_valid = i>0 and market[i][0]-market[i-1][0]==minutes*60
            assert row["valid"] == ("1" if is_valid else "0")
            if is_valid:
                expected = independent_geometry(market[i], market[i-1])
                actual = tuple(int(row[x]) for x in ("lag","body","range","joint"))
                assert expected == actual, (minutes,i,expected,actual)
                feature.append(expected)
                valid+=1
            else:
                assert all(row[k]=="-" for k in ("lag",*MODELS))
                feature.append(None)
    assert len(feature) == len(market)
    return feature, valid


def events(market, feature, minutes):
    step = minutes*60
    result=[]
    for i in range(1,len(market)-1):
        if feature[i] is None or market[i+1][0] != market[i][0]+step:
            continue
        (lag,body,ran,joint) = feature[i]
        next_close = market[i+1][4]
        now_close = market[i][4]
        up = 1 if next_close>now_close else 0 if next_close<now_close else -1
        result.append((i,market[i][0],market[i+1][0]+step,
                       (market[i+1][0]+step)//86400,lag,up,body,ran,joint))
    return result


def fit(events, alpha, override=None):
    n=len(events); overall=(sum(row[5] for row in events)+.5)/(n+1)
    by_lag=defaultdict(lambda:[0,0])
    cells={name:defaultdict(lambda:[0,0]) for name in MODELS}
    for i, row in enumerate(events):
        lag,y=row[4],row[5]
        by_lag[lag][0]+=y
        by_lag[lag][1]+=1
        for j,name in enumerate(MODELS):
            key=override[i] if name=="joint" and override is not None else row[6+j]
            slot=cells[name][(lag,key)]
            slot[0]+=y
            slot[1]+=1
    prior = {k:(v[0]+.5)/(v[1]+1) for k,v in by_lag.items()}
    return overall,prior,cells


def prob(fit_result,row,alpha,replace_joint=None):
    overall, by_lag,cells=fit_result
    lag=row[4]
    base=by_lag.get(lag,overall)
    result={"baseline":base}
    for j,name in enumerate(MODELS):
        key=replace_joint if name=="joint" and replace_joint is not None else row[6+j]
        x=cells[name].get((lag,key),(0,0))
        result[name]=(x[0]+alpha*base)/(x[1]+alpha)
    return result


def loss(p,y):
    assert 0<p<1
    return -math.log(p) if y==1 else -math.log1p(-p)


def near(a,b,label):
    if not math.isclose(a,b,abs_tol=2e-10,rel_tol=2e-10):
        raise AssertionError((label,a,b))
    return abs(a-b)


def shifted(events,offset):
    n=len(events)
    if n==0:
        raise AssertionError("empty rotation domain")
    return [events[(i-offset)%n][8] for i in range(n)]


def check_predictions(path, all_events, protocol, minute, producer_folds, alpha):
    with path.open(newline="") as stream:
        reader=csv.DictReader(stream,delimiter="\t")
        assert tuple(reader.fieldnames)==PRED
        annual={}
        daily={}
        scores=[]
        max_err=0.0
        for fold in protocol["period"]["outer_folds"]:
            year=fold["year"]
            start,end=sec(fold["start"]),sec(fold["end"])
            tr=[x for x in all_events if x[2]<start and x[5]>=0]
            section=[x for x in all_events if start<=x[1]<end and x[2]<end]
            ev=[x for x in section if x[5]>=0]
            flat=sum(x[5]<0 for x in section)
            assert tr and ev
            m=fit(tr,alpha)
            total=defaultdict(float)
            support={name:0 for name in MODELS}
            day_diffs=defaultdict(lambda:[0.,0])
            for row in ev:
                exported=next(reader,None)
                if exported is None: raise AssertionError("missing predicted event")
                target=(year,row[0],row[1],row[3],row[4],row[5],row[6],row[7],row[8])
                recorded=tuple(int(exported[k]) for k in PRED[:9])
                assert recorded == target, (minute,target,recorded)
                pp=prob(m,row,alpha)
                for key,field in zip(("baseline",*MODELS),PRED[9:]):
                    max_err=max(max_err,near(pp[key],float(exported[field]),f"prediction {minute} {year} {key}"))
                    total[key]+=loss(pp[key],row[5])
                for j,name in enumerate(MODELS):
                    if (row[4],row[6+j]) not in m[2][name]:
                        support[name]+=1
                d=day_diffs[row[3]]
                d[0]+=loss(pp["baseline"],row[5])-loss(pp["joint"],row[5])
                d[1]+=1
            observed=producer_folds[str(year)]
            assert observed["score_binary"]==len(ev)
            assert observed["train_binary"]==len(tr)
            assert observed["score_flat_excluded"]==flat
            assert observed["classes_train"]=={name:len(m[2][name]) for name in MODELS}
            assert observed["unseen_test"]==support
            assert observed["train_lag_strata"]=={
                str(k):sum(x[4]==k for x in tr) for k in (-1,0,1)
            }
            for name in ("baseline",*MODELS):
                max_err=max(max_err,near(total[name],observed["sums"][name],f"fold sum {minute} {year} {name}"))
                max_err=max(max_err,near(total[name]/len(ev),observed["mean_losses"][name],f"fold mean {minute} {year} {name}"))
            gain=(total["baseline"]-total["joint"])/len(ev)
            max_err=max(max_err,near(gain,observed["gain_joint"],f"fold gain {minute} {year}"))
            max_err=max(max_err,near(
                (total["baseline"]-total["joint"])/math.log(2),observed["bits_joint"],"bits"
            ))
            annual[year]=(tr,ev)
            daily[year]=[day_diffs.get(day,[0.,0]) for day in range(start//86400,end//86400)]
            scores.append((len(ev),total))
        assert next(reader,None) is None, "unexpected prediction rows"
    return annual,daily,scores,max_err


def recompute_bootstrap(daily,p):
    conf=p["uncertainty"]
    rng=random.Random(conf["seed"])
    diff=sum(sum(x[0] for x in rows) for _,rows in sorted(daily.items()))
    count=sum(sum(x[1] for x in rows) for _,rows in sorted(daily.items()))
    observed=diff/count
    distribution=[]
    hits=0
    for _ in range(conf["replicates"]):
        total=0.0
        central=0.0
        denom=0
        for _,rows in sorted(daily.items()):
            days=len(rows); used=0
            while used<days:
                begin=rng.randrange(days)
                length=min(conf["block_days"],days-used)
                for i in range(length):
                    x,n=rows[(begin+i)%days]
                    total+=x
                    central+=x-observed*n
                    denom+=n
                used+=length
        assert denom
        distribution.append(total/denom)
        if central/denom>=observed:
            hits+=1
    distribution.sort()
    return observed,[
        distribution[int(.025*conf["replicates"])],
        distribution[int(.975*conf["replicates"])]
    ],(hits+1)/(conf["replicates"]+1),hits


def recompute_placebo(annual,p):
    alpha=p["estimator"]["alpha"]
    minute=p["primary"]["timeframe_minutes"]
    result=[]
    for days in p["placebo"]["shifts_days"]:
        shift=days*1440//minute
        total=0.; n=0
        for _,(tr,ev) in sorted(annual.items()):
            m=fit(tr,alpha,override=shifted(tr,shift))
            for row,key in zip(ev,shifted(ev,shift)):
                preds=prob(m,row,alpha,replace_joint=key)
                total+=loss(preds["baseline"],row[5])-loss(preds["joint"],row[5])
                n+=1
        result.append((days,total/n))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--protocol",type=Path,default=HERE/"protocol_r0a.json")
    parser.add_argument("--data-dir",type=Path,required=True)
    parser.add_argument("--run-dir",type=Path,required=True)
    args=parser.parse_args()
    if sha(args.protocol)!=PROTOCOL_SHA:
        raise ValueError("unexpected protocol SHA; no experiment audit")
    p=json.loads(args.protocol.read_text())
    run=args.run_dir
    producer_path=run/"producer.json"
    saved=json.loads(producer_path.read_text())
    assert saved["frozen_protocol_sha256"]==PROTOCOL_SHA
    assert saved["frozen_protocol_commit"]=="c2eecc24103b049866de2881ca8141ac194a0927"
    assert saved["runner_sha256"]==sha(HERE/"run.py")
    assert saved["schema"]=="qinf-r0-producer-v1"
    assert saved["status"]=="PRELIMINARY_PENDING_INDEPENDENT_AUDIT"
    all_audit={}
    primary=None
    max_error=0.0
    for src in sorted(p["source_policy"]["sources"],key=lambda s:s["minutes"]):
        minute=src["minutes"]
        path=args.data_dir/f"{minute}m"/"ohlcv.csv"
        assert sha(path)==src["csv_sha256"]
        market=read_market(path,minute,src["expected_rows"])
        native=run/"native"/f"{minute}m.tsv"
        predictions=run/"predictions"/f"{minute}m.tsv"
        record=saved["timeframes"][str(minute)]
        assert record["source_sha256"]==src["csv_sha256"]
        assert record["source_rows"]==len(market)
        assert sha(native)==record["features_sha256"]
        assert sha(predictions)==record["predictions_sha256"]
        fs,nvalid=check_native(native,market,minute)
        assert record["native"]["rows"]==len(market)
        assert record["native"]["valid"]==nvalid
        ev=events(market,fs,minute)
        annual,daily,scores,err=check_predictions(
            predictions,ev,p,minute,record["folds"],p["estimator"]["alpha"]
        )
        max_error=max(max_error,err)
        n=sum(count for count,_ in scores)
        assert record["eligible_binary"]==n
        sums={name:sum(row[name] for _,row in scores) for name in ("baseline",*MODELS)}
        for name in ("baseline",*MODELS):
            max_error=max(max_error,near(sums[name]/n,record["pooled_mean_losses"][name],f"pooled mean {minute} {name}"))
        max_error=max(max_error,near((sums["baseline"]-sums["joint"])/n,
                     record["pooled_gain_joint_nats"],f"pooled gain {minute}"))
        max_error=max(max_error,near((sums["baseline"]-sums["joint"])/math.log(2),
                     record["pooled_bits_joint"],f"pooled bits {minute}"))
        all_audit[str(minute)]={
            "source_rows":len(market), "native_feature_valid":nvalid,
            "audited_predictions":n, "years":[2023,2024,2025,2026],
            "max_prediction_discrepancy":err,
        }
        if minute==p["primary"]["timeframe_minutes"]:
            primary=(annual,daily)
    assert primary is not None
    gain,ci,pvalue,hits=recompute_bootstrap(primary[1],p)
    prod=saved["primary"]
    max_error=max(max_error,near(gain,prod["bootstrap"]["observed_gain_nats"],"bootstrap gain"))
    assert hits==prod["bootstrap"]["exceedances"]
    for a,b in zip(ci,prod["bootstrap"]["ci95"]):
        max_error=max(max_error,near(a,b,"bootstrap interval"))
    max_error=max(max_error,near(pvalue,prod["bootstrap"]["one_sided_centered_null_p"],"p"))
    placebo=recompute_placebo(primary[0],p)
    for (days,gain_shift),item in zip(placebo,prod["placebo_shifts"]):
        assert days==item["nominal_shift_days"]
        max_error=max(max_error,near(gain_shift,item["gain_nats"],"placebo"))
    assert len(placebo)==len(p["placebo"]["shifts_days"])
    assert max_error<=2e-10

    primary_years=[saved["timeframes"][str(p["primary"]["timeframe_minutes"])]
                     ["folds"][str(f["year"])]["gain_joint"] for f in p["period"]["outer_folds"]]
    checks={
        "positive_pooled":gain>0,
        "ci_lower_positive":ci[0]>0,
        "one_sided_p_below_0.05":pvalue<.05,
        "at_least_three_positive_years":sum(x>0 for x in primary_years)>=3,
        "latest_2026_positive":primary_years[-1]>0,
        "independent_audit":True,
    }
    assert {k:prod["checks"][k] for k in checks if k!="independent_audit"}=={
        k:v for k,v in checks.items() if k!="independent_audit"
    }
    outcome="supported" if all(checks.values()) else "not-supported"
    audit={
        "schema":"qinf-r0-independent-audit-v1",
        "status":"PASS", "outcome":outcome,
        "retrospective_only":True,
        "prior_timeframe_selection":True,
        "protocol_sha256":PROTOCOL_SHA,
        "producer_sha256":sha(producer_path),
        "verifier_sha256":sha(Path(__file__)),
        "max_abs_numerical_discrepancy":max_error,
        "timeframes":all_audit,
        "primary":{"gain_nats":gain,"ci95":ci,"p":pvalue,"null_hits":hits,"checks":checks}
    }
    audit_path=run/"verification.json"
    if audit_path.exists():
        raise ValueError("verification already exists; no overwrite")
    audit_path.write_text(json.dumps(audit,sort_keys=True,indent=2)+"\n")
    result={
        "schema":"qinf-r0-final-v1", "outcome":outcome,
        "claim":"Retrospective fixed-abstraction next-bar log-loss criterion; not a fresh confirmation or trading result",
        "protocol_sha256":PROTOCOL_SHA,
        "audit_sha256":sha(audit_path), "producer_sha256":sha(producer_path),
        "primary":audit["primary"], "timeframes":saved["timeframes"],
        "placebo_shifts":saved["primary"]["placebo_shifts"],
        "limitations":[
            "30m was selected due to earlier positive BTC research; nominal CI/p-values do not correct prior research selection",
            "All five BTC data histories including 2026 were previously inspected",
            "No money-making edge tested; prediction log loss and transaction costs are distinct",
            "Time-shift controls are noncausal alignment placebos, not a realistic generative OHLC null",
            "True fresh confirmation requires a separately frozen future-data protocol"
        ]
    }
    result_path=run/"result.json"
    if result_path.exists():
        raise ValueError("result already exists; no overwrite")
    result_path.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":"PASS","outcome":outcome,"primary":audit["primary"],
                      "max_abs_error":max_error,"by_timeframe":all_audit},indent=2,sort_keys=True))


if __name__=="__main__":
    main()
