#!/usr/bin/env python3
"""Independent R3 payoff and signed-score account verifier.

Draft admission is deliberately closed until a published protocol SHA and freeze
commit are registered. This verifier never estimates model parameters. It may
reuse the prior independent raw-OHLC/key oracle, never producer computations.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
from fractions import Fraction
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import subprocess
import time

try:
    from . import verify_round1 as independent
except ImportError:
    import verify_round1 as independent

np = independent.np
require, compare = independent.require, independent.compare
digest, array_digest = independent.digest, independent.array_digest
json_file, json_digest = independent.json_file, independent.json_digest
epoch, read_npz = independent.epoch, independent.read_npz
HERE = Path(__file__).resolve().parent
TIMES, YEARS, HISTORIES = independent.TIMES, independent.YEARS, independent.HISTORIES
FAMILIES = ("A", "I")
FORECASTERS = ("A", "I", "U")
PROTOCOL_SHA256 = "486fd2b2f1bfa0e4e2ce19b77485386cef833c8b6341d5eca2403556dcdf67a7"
SUPPORTED_PROTOCOLS: dict[str, dict] = {
    PROTOCOL_SHA256: {"freeze_commit": "bcc49b113c59f2a2c72524605d26b2dedca98353",
                      "attempt_id": "R3", "experiment_id": "btc-geometry-interaction-payoff-r3"},
}
DIRECT_GRADIENT_LIMIT = 1e-10
TIE_TOLERANCE = 1e-12
CATALOGUE_SHA256='dca090d73c32419bc525b71101f6cf0b584b1c8b91cf79808d4ed2f5d710bcdb'
CATALOGUE_PATH='experiments/geometry_information/round3_catalogue.json'


@lru_cache(maxsize=1)
def oriented_pair_states():
    """Enumerate complete OHLC chains, independently of interval catalogues."""
    states=[]
    for levels in range(1,9):
        chains=list(itertools.combinations_with_replacement(range(levels),4))
        occupied=set(range(levels))
        for first in chains:
            for second in chains:
                if set(first+second)!=occupied:continue
                colors0=(0,) if first[1]==first[2] else (-1,1)
                colors1=(0,) if second[1]==second[2] else (-1,1)
                states.extend((first,second,a,b) for a in colors0 for b in colors1)
    require(len(states)==len(set(states))==7452,'R3 exhaustive oriented pair count')
    return tuple(states)


def projected_key(first,second,d0,d1,endpoints):
    values=tuple(first[index] for index in endpoints)+tuple(second[index] for index in endpoints)
    levels=sorted(set(values))
    return (int(d0),int(d1),*(levels.index(value) for value in values))


@lru_cache(maxsize=1)
def catalogue_oracle():
    states=oriented_pair_states();groups=[];records=[]
    for block,endpoints in (('body',(1,2)),('range',(0,3))):
        keys=sorted({projected_key(*state,endpoints) for state in states});groups.append(tuple(keys))
        for local,key in enumerate(keys):
            name=f"interaction.{block}[0,1].directions({key[0]},{key[1]}).ranks({','.join(map(str,key[2:]))})"
            records.append({'index':len(records),'block':block,'local_index':local,
                'directions':list(key[:2]),'ranks':list(key[2:]),'name':name})
    require(tuple(map(len,groups))==(75,150) and all(len({key[2:] for key in group})==26 for group in groups),
            'R3 complete conditioned interval counts')
    payload={'version':'filang-interval-interactions-v1','records':records}
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    require(len(encoded)==33202 and hashlib.sha256(encoded).hexdigest()==CATALOGUE_SHA256,'R3 independent catalogue identity')
    return payload,encoded,tuple(groups)


def catalogue_contract(protocol,run_root=None):
    payload,encoded,_=catalogue_oracle();spec=protocol['features']['catalogue']
    require(spec['catalogue_file']==CATALOGUE_PATH and spec['catalogue_sha256']==CATALOGUE_SHA256,'R3 pinned catalogue path/hash')
    local=HERE.parents[1]/CATALOGUE_PATH
    require(local.read_bytes()==encoded,'R3 source catalogue differs from independent complete grammar')
    if run_root is not None:require((Path(run_root)/'catalogue.json').read_bytes()==encoded,'R3 run catalogue differs')
    for name,value in [('interval_weak_orders',26),('body_conditioned_entries',75),('range_conditioned_entries',150),
                       ('total_entries',225),('synthetic_oriented_two_bar_states',7452)]:
        require(spec[name]==value,'R3 catalogue protocol count')
    return {'sha256':CATALOGUE_SHA256,'bytes':len(encoded),'oriented_states':7452,'body_columns':75,'range_columns':150,
            'all_columns_reachable':True,'source_and_run_bytes_checked':run_root is not None}


def interval_indices(values,directions):
    values,directions=np.asarray(values),np.asarray(directions)
    require(values.ndim==3 and values.shape[1:]==(2,4) and directions.shape==(len(values),2),'R3 interval projection shape')
    require(np.all(values[:,:,1:]>=values[:,:,:-1]),'R3 ordered candle endpoints')
    require(np.isin(directions,(-1,0,1)).all() and np.array_equal(directions==0,values[:,:,1]==values[:,:,2]),
            'R3 body direction/width')
    _,_,groups=catalogue_oracle()
    lookups=({key:index for index,key in enumerate(groups[0])},{key:75+index for index,key in enumerate(groups[1])})
    result=np.empty((len(values),2),dtype=np.int16)
    for row,(pair,colors) in enumerate(zip(values,directions)):
        for column,endpoints in enumerate(((1,2),(0,3))):
            key=projected_key(pair[0],pair[1],colors[0],colors[1],endpoints)
            require(key in lookups[column],'R3 reachable interaction key')
            result[row,column]=lookups[column][key]
    return result


def raw_interaction_indices(prices,rows):
    rows=np.asarray(rows,dtype=np.int64)
    selected=rows[:,None]-np.arange(2)
    values=independent.endpoints(prices)[selected]
    directions=np.sign(prices[selected,3]-prices[selected,0]).astype(np.int8)
    return interval_indices(values,directions)


def key_interaction_indices(ranks,up):
    ranks,up=np.asarray(ranks),np.asarray(up)
    pair=ranks[:,:2];flags=up[:,:2]
    flat=pair[:,:,1]==pair[:,:,2]
    require(not np.any(flat&flags),'R3 native flat body up bit')
    return interval_indices(pair,np.where(flat,0,np.where(flags,1,-1)))


def feature_names(n,family):
    require(n in HISTORIES and family in FAMILIES,'R3 feature family/history')
    names=independent.feature_names(n,'G')
    return names if family=='A' else names+[record['name'] for record in catalogue_oracle()[0]['records']]


def raw_features(prices,rows,n,family):
    require(family in FAMILIES,'R3 raw feature family')
    additive=independent.raw_features(prices,rows,n,'G')
    if family=='A':return additive
    ids=raw_interaction_indices(prices,rows)
    block=np.zeros((len(ids),225),dtype=np.uint8)
    block[np.arange(len(ids))[:,None],ids]=1
    return np.ascontiguousarray(np.column_stack((additive,block)),dtype=np.uint8)


def admitted_protocol(path):
    checksum = digest(path)
    require(checksum in SUPPORTED_PROTOCOLS, "unrecognized R3 frozen protocol; drafts cannot run")
    entry = SUPPORTED_PROTOCOLS[checksum]
    require(entry.get("freeze_commit") is not None and
            re.fullmatch(r"[0-9a-f]{40}", entry["freeze_commit"]), "R3 protocol has no published freeze")
    return entry


def target_oracle(source, causal_rows, start, end):
    """Same causal 10-bar history, two consecutive future opens, true zeros kept."""
    old = independent.phase_oracle(source, causal_rows, start, end)
    valid = old.pop("classification_valid")
    old.pop("binary_mask")
    simple = old.pop("target_return")
    rows = np.flatnonzero(valid)
    target = np.full(len(valid), np.nan, dtype=np.float64)
    opens = source["prices"][:, 0]
    target[rows] = np.log(opens[rows + 2] / opens[rows + 1])
    old.update(target_valid=valid, target_log_return=target, target_simple_return=simple)
    return old


def ridge_objective_gradient(features, labels, intercept, coefficients, penalty):
    x, y = np.asarray(features, dtype=np.float64), np.asarray(labels, dtype=np.float64)
    beta = np.asarray(coefficients, dtype=np.float64)
    require(x.ndim == 2 and y.shape == (len(x),) and beta.shape == (x.shape[1],) and len(x),
            "ridge sample/parameter shape")
    require(np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(beta).all() and
            math.isfinite(intercept) and math.isfinite(penalty) and penalty > 0, "ridge finite domain")
    residual = (x @ beta + intercept) - y
    objective = float(residual @ residual / (2 * len(y)) + penalty * (beta @ beta) / 2)
    gradient = np.concatenate(([float(residual.sum() / len(y))], x.T @ residual / len(y) + penalty * beta))
    return objective, gradient


def squared_error_scores(target, prediction):
    y, mu = np.asarray(target, dtype=np.float64), np.asarray(prediction, dtype=np.float64)
    require(y.ndim == 1 and y.shape == mu.shape and len(y) and np.isfinite(y).all() and np.isfinite(mu).all(),
            "payoff score vectors")
    residual = mu - y
    return {"target_count": len(y), "zero_count": int(np.sum(y == 0)),
            "squared_error_sum": float(residual @ residual), "mse": float(np.mean(residual * residual)),
            "target_sum": float(np.sum(y)), "prediction_sum": float(np.sum(mu)),
            "absolute_error_sum": float(np.sum(np.abs(residual))),
            "nonzero_direction_correct": int(np.sum(np.sign(mu[y != 0]) == np.sign(y[y != 0])))}


def select_model(candidates):
    require(bool(candidates), "empty candidate family")
    minimum = min(float(candidate["validation_mse"]) for candidate in candidates)
    tied = [candidate for candidate in candidates if candidate["validation_mse"] <= minimum + TIE_TOLERANCE]
    return min(tied, key=lambda candidate: (candidate["n"], -candidate["lambda"]))


def roundtrip_log_cost(fee_bps=10, slippage_bps=2):
    fee, slip = fee_bps / 10000.0, slippage_bps / 10000.0
    require(0 <= fee < 1 and 0 <= slip < 1, "policy cost domain")
    return -math.log((1-fee)**2*(1-slip)/(1+slip))


def select_policy(candidates):
    """All seven candidates compete; absolute net-log ties use frozen rules."""
    require(bool(candidates), "empty policy family")
    maximum = max(float(candidate["metrics"]["net_log_return"]) for candidate in candidates)
    tied = [candidate for candidate in candidates
            if candidate["metrics"]["net_log_return"] >= maximum-TIE_TOLERANCE]
    def order(candidate):
        policy, metrics = candidate["policy"], candidate["metrics"]
        return (policy["kind"] != "cash", metrics["one_way_turnover"],
                -float(policy["entry_threshold"] or 0), float(policy["exit_threshold"] or 0), policy["id"])
    return min(tied, key=order)


def paired_daily_bootstrap(folds, minutes, block, replicas=2000, seed=20261008):
    """Two economic contrasts share each exact circular, year-stratified draw."""
    require(folds and all(set(fold) >= {"I_minus_A", "I_minus_cash"} for fold in folds), "bootstrap contrasts")
    length = sum(len(fold["I_minus_A"]) for fold in folds)
    require(length > 0 and block > 0 and replicas > 0, "bootstrap size")
    names = ("I_minus_A", "I_minus_cash")
    observed = {name: sum(float(np.sum(fold[name])) for fold in folds)/length for name in names}
    ordinary = {name: np.empty(replicas) for name in names}
    centered = {name: np.empty(replicas) for name in names}
    generator = np.random.default_rng(seed+1000*minutes+block)
    for replica in range(replicas):
        totals = {name: 0.0 for name in names}
        null_totals = {name: 0.0 for name in names}
        for fold in folds:
            days = len(fold[names[0]])
            require(days > 0 and len(fold[names[1]]) == days, "paired daily coverage")
            starts = generator.integers(0, days, size=math.ceil(days/block), dtype=np.int64)
            chosen = np.concatenate([np.arange(int(start), int(start)+block) % days for start in starts])[:days]
            for name in names:
                values = np.asarray(fold[name], dtype=np.float64)
                require(np.isfinite(values).all(), "bootstrap finite daily contrast")
                totals[name] += float(np.sum(values[chosen]))
                null_totals[name] += float(np.sum((values-observed[name])[chosen]))
        for name in names:
            ordinary[name][replica], centered[name][replica] = totals[name]/length, null_totals[name]/length
    summaries = {}
    for name in names:
        ordered = np.sort(ordinary[name])
        def percentile(p):
            offset = (replicas-1)*p
            i = int(math.floor(offset)); j = min(i+1, replicas-1)
            return float(ordered[i]+(ordered[j]-ordered[i])*(offset-i))
        summaries[name] = {"mean_daily_net_log_gain": observed[name], "ci95_low": percentile(.025),
                           "ci95_high": percentile(.975)}
    return {"block_days": block, "replicates": replicas, "seed": seed+1000*minutes+block,
            "contrasts": summaries}, {
                name+"__ordinary": ordinary[name] for name in names} | {
                name+"__centered": centered[name] for name in names}


EXACT_TAIL_METHOD='exact_binary64_rational_weighted_sum_ge_twice_original_sum'


def exact_encoding_oracle(folds):
    """Independent Fraction conversion of already audited executed daily values."""
    names=('I_minus_A','I_minus_cash')
    parts=[np.column_stack([fold[name] for name in names]).astype(np.float64) for fold in folds]
    require(parts and all(len(p)>0 and np.isfinite(p).all() for p in parts),'R3 exact daily inputs')
    lengths=[len(part) for part in parts];joined=np.concatenate(parts)
    columns={};integer_columns=[];totals=[]
    for index,name in enumerate(names):
        values=[Fraction.from_float(float(value)) for value in joined[:,index]]
        exponent=max(value.denominator.bit_length()-1 for value in values)
        numerators=[value.numerator*(2**exponent//value.denominator) for value in values]
        pooled=sum(numerators);integer_columns.append(numerators);totals.append(pooled)
        encoded=''.join(str(value)+'\n' for value in numerators).encode('ascii')
        columns[name]={'denominator_exponent':exponent,'pooled_numerator_decimal':str(pooled),
            'numerators_decimal':[str(value) for value in numerators],'numerators_sha256':hashlib.sha256(encoded).hexdigest(),
            'binary64_contrasts_sha256':array_digest(joined[:,index],'<f8'),'nonzero_days':int(np.count_nonzero(joined[:,index]))}
    metadata={'schema':'filang-exact-bootstrap-input-v1','comparison_order':list(names),'fold_lengths':lengths,
        'calendar_days':sum(lengths),'fold_binary64_sha256':[array_digest(part,'<f8') for part in parts],
        'integer_encoding':'signed decimal integer plus LF per day; concatenated fold order',
        'value_definition':'numerator / 2**denominator_exponent; supplied binary64 contrasts interpreted exactly',
        'tail_event':'resampled_numerator_sum >= 2 * pooled_numerator_sum','contrasts':columns}
    metadata['encoding_sha256']=json_digest(metadata)
    integer_folds=[];offset=0
    for size in lengths:
        integer_folds.append(tuple(column[offset:offset+size] for column in integer_columns));offset+=size
    observed=np.zeros(2,dtype=np.float64)
    for part in parts:observed+=np.sum(part,axis=0)
    observed/=sum(lengths)
    return {'metadata':metadata,'integers':integer_folds,'pooled_sums':totals,'observed':observed}


def exact_tail_oracle(prepared,minutes,block,replicas=2000,seed=20261008):
    """Sum selected arbitrary-precision numerators directly, without a float predicate."""
    result=np.empty((replicas,2),dtype=bool)
    generator=np.random.default_rng(seed+1000*minutes+block)
    cutoffs=[2*value for value in prepared['pooled_sums']]
    lengths=prepared['metadata']['fold_lengths']
    for replica in range(replicas):
        totals=[0,0]
        for size,columns in zip(lengths,prepared['integers']):
            starts=generator.integers(0,size,size=math.ceil(size/block),dtype=np.int64)
            indices=[(int(start)+offset)%size for start in starts for offset in range(block)][:size]
            for column in range(2):totals[column]+=sum(columns[column][index] for index in indices)
        for column in range(2):result[replica,column]=totals[column]>=cutoffs[column]
    return result


def exact_bootstrap_summary(prepared,hits,saved_ordinary,saved_centered,minutes,block,replicas,seed):
    require(hits.dtype==np.bool_ and hits.shape==(replicas,2),'R3 exact hit-array shape/dtype')
    ordered=np.sort(saved_ordinary,axis=0);comparisons={}
    for column,name in enumerate(('I_minus_A','I_minus_cash')):
        def percentile(q):
            index=(replicas-1)*q;left=int(math.floor(index));right=min(left+1,replicas-1)
            return float(ordered[left,column]+(ordered[right,column]-ordered[left,column])*(index-left))
        observed=float(prepared['observed'][column]);count=int(np.count_nonzero(hits[:,column]))
        comparisons[name]={'mean_daily_net_log_gain':observed,'total_net_log_gain':observed*prepared['metadata']['calendar_days'],
            'calendar_days':prepared['metadata']['calendar_days'],'ci95_low':percentile(.025),'ci95_high':percentile(.975),
            'exact_tail_count':count,'p_one_sided':(1+count)/(replicas+1)}
    return {'block_days':block,'replicates':replicas,'seed':seed+1000*minutes+block,'comparisons':comparisons,
        'intersection_union_p':max(row['p_one_sided'] for row in comparisons.values()),
        'ordinary_sha256':array_digest(saved_ordinary,'<f8'),'centered_sha256':array_digest(saved_centered,'<f8'),
        'exact_hits_sha256':array_digest(hits,np.bool_),'exact_encoding_sha256':prepared['metadata']['encoding_sha256'],
        'tail_method':EXACT_TAIL_METHOD}


def holm_and_conditions(results):
    ordered = sorted(results, key=lambda result: (result["p_composite"], result["minutes"]))
    previous = 0.0
    for rank, result in enumerate(ordered):
        previous = max(previous, min(1.0, (len(ordered)-rank)*result["p_composite"]))
        result["p_holm"] = previous
    for result in results:
        contrasts = result["contrasts"]
        result["conditions"] = {
            "both_mean_gains_positive": all(contrasts[name]["mean_daily_net_log_gain"] > 0 for name in contrasts),
            "both_ci_above_zero": all(contrasts[name]["ci95_low"] > 0 for name in contrasts),
            "holm_below_005": result["p_holm"] < .05,
            "three_joint_positive_years": result["joint_positive_years"] >= 3,
            "twenty_completed_I_trades": result["completed_I_trades"] >= 20}
        result["criterion_met"] = all(result["conditions"].values())
    return results


def signed_cash_share_oracle(timestamps, opens, score, *, start, end, interval_seconds,
                      fee_bps, slippage_bps, policy="threshold", entry_threshold=0.0, exit_threshold=0.0):
    """Independent quantity account, normalized after every marked opening.

    Normalizing cash and coin together preserves all return ratios while avoiding
    underflow. A separate frictionless account follows the same exposure path.
    No producer logarithmic cost factors or ledger helpers are imported.
    """
    timestamps = np.asarray(timestamps, dtype=np.int64)
    opens, score = np.asarray(opens, dtype=float), np.asarray(score, dtype=float)
    require(timestamps.ndim == 1 and opens.shape == score.shape == timestamps.shape, "ledger vectors")
    require(len(timestamps) >= 2 and np.all(np.diff(timestamps) > 0) and np.all(np.isfinite(opens)) and np.all(opens > 0), "ledger source")
    require(interval_seconds > 0 and end > start and math.isfinite(entry_threshold) and math.isfinite(exit_threshold) and exit_threshold <= entry_threshold, "ledger period/thresholds")
    require(not np.isinf(score).any(), "ledger signed forecast")
    require(policy in ("threshold", "cash", "buy_hold"), "ledger policy")
    fee, slip = fee_bps / 10000.0, slippage_bps / 10000.0
    require(0 <= fee < 1 and 0 <= slip < 1, "ledger costs")
    indices = np.flatnonzero((timestamps >= start) & (timestamps < end))
    require(len(indices) >= 2, "ledger requires two period openings")
    cash, coin, free_cash, free_coin = 1.0, 0.0, 1.0, 0.0
    exposure, seconds, entry = 0, 0, None
    cumulative_net, cumulative_gross = 0.0, 0.0
    rows, trades, gaps = [], [], []
    for ordinal, original in enumerate(indices):
        i, price = int(original), float(opens[original])
        before = exposure
        marked, free_marked = cash + coin * price, free_cash + free_coin * price
        gross_mark = math.log(free_marked)
        if ordinal:
            seconds += before * int(timestamps[i] - timestamps[indices[ordinal - 1]])
        signal, close, delay, used, want = -1, -1, 0, float("nan"), 0
        if ordinal and timestamps[i - 1] >= start:
            signal, close = i - 1, int(timestamps[i - 1] + interval_seconds)
            delay, used = max(0, int(timestamps[i] - close)), float(score[i - 1])
            if policy == "buy_hold":
                want = 1
            elif policy == "threshold" and math.isfinite(used):
                want = int(used >= (exit_threshold if before else entry_threshold))
        request = float(want) if signal >= 0 else float("nan")
        terminal = ordinal == len(indices) - 1
        if terminal:
            want = 0
        cost = 0.0
        if want != before:
            if want:
                coin = marked * (1 - fee) / (price * (1 + slip))
                cash, free_coin, free_cash = 0.0, free_marked / price, 0.0
                cost = math.log((cash + coin * price) / marked)
                entry = {"entry_row": i, "entry_timestamp": int(timestamps[i]), "entry_open": price,
                         "entry_log_cost": cost, "signal_row": signal, "signal_close": close,
                         "entry_delay_seconds": delay, "net_before_entry": cumulative_net}
            else:
                cash = coin * price * (1 - slip) * (1 - fee)
                coin, free_cash, free_coin = 0.0, free_marked, 0.0
                cost = math.log(cash / marked)
        wealth, free_wealth = cash + coin * price, free_cash + free_coin * price
        net_change = math.log(wealth)
        cumulative_net += net_change
        cumulative_gross += gross_mark
        if before and not want:
            require(entry is not None, "oracle sale without entry")
            # Reconstruct the completed trade from one unit of entry cash.
            # This also preserves exactly flat zero-cost trades: cancellation
            # across thousands of normalized log marks must not create wins.
            purchased = (1-fee)/(entry["entry_open"]*(1+slip))
            trade_wealth = purchased*price*(1-slip)*(1-fee)
            if fee == 0 and slip == 0 and price == entry["entry_open"]:
                trade_wealth = 1.0
            trade_net = math.log(trade_wealth)
            require(math.isclose(trade_net, cumulative_net-entry["net_before_entry"], abs_tol=1e-10, rel_tol=1e-10),
                    "oracle trade/marked account reconciliation")
            trade = {k: v for k, v in entry.items() if k != "net_before_entry"}
            trade.update(exit_row=i, exit_timestamp=int(timestamps[i]), exit_open=price, exit_log_cost=cost,
                         gross_log_return=math.log(price / entry["entry_open"]), net_log_return=trade_net,
                         net_return=math.expm1(trade_net), holding_seconds=int(timestamps[i] - entry["entry_timestamp"]),
                         terminal_liquidation=terminal)
            trades.append(trade)
            entry = None
        exposure = want
        rows.append((i, int(timestamps[i]), price, signal, close, used, delay, before, want, exposure,
                     gross_mark, cost, net_change, request))
        if ordinal and timestamps[i] - timestamps[i - 1] != interval_seconds:
            gaps.append({"previous_row": i - 1, "row": i, "previous_open": int(timestamps[i - 1]),
                         "open_timestamp": int(timestamps[i]), "missing_seconds": int(timestamps[i] - timestamps[i - 1] - interval_seconds),
                         "signal_close": close, "delay_seconds": delay, "position_before": before,
                         "position_after": exposure, "gap_gross_log_return": gross_mark, "net_log_return": net_change})
        cash, coin = cash / wealth, coin / wealth
        free_cash, free_coin = free_cash / free_wealth, free_coin / free_wealth
    require(exposure == 0 and entry is None, "oracle terminal position")
    names = ("row", "timestamp", "open", "signal_row", "signal_close", "signal_score", "delay_seconds",
             "position_before", "desired", "position_after", "gross_log_return", "log_cost", "net_log_return", "signal_request")
    integers = {"row", "timestamp", "signal_row", "signal_close", "delay_seconds", "position_before", "desired", "position_after"}
    trace = {name: np.asarray([row[k] for row in rows], dtype=np.int64 if name in integers else np.float64)
             for k, name in enumerate(names)}
    days = np.arange(start // 86400, (end - 1) // 86400 + 1, dtype=np.int64)
    daily_net, daily_gross = np.zeros(len(days)), np.zeros(len(days))
    for row in rows:
        day = row[1] // 86400 - int(days[0])
        daily_net[day] += row[12]
        daily_gross[day] += row[10]
    net_total, gross_total = float(trace["net_log_return"].sum()), float(trace["gross_log_return"].sum())
    sides = int(np.count_nonzero(trace["position_before"] != trace["position_after"]))
    running, high, drawdown = 0.0, 0.0, 0.0
    for change in trace["net_log_return"]:
        running += float(change)
        high = max(high, running)
        drawdown = max(drawdown, 1 - math.exp(running - high))
    daily_mean = float(daily_net.sum() / len(days))
    daily_sd = math.sqrt(float(np.square(daily_net - daily_mean).sum()) / (len(days) - 1)) if len(days) > 1 else 0.0
    active = {row[1] // 86400 for row in rows if row[7] or row[9]}
    metrics = {"start": int(start), "end_exclusive": int(end), "observed_openings": len(indices),
               "calendar_days": len(days), "terminal_open": int(timestamps[indices[-1]]), "policy": policy,
               "entry_threshold": entry_threshold, "exit_threshold": exit_threshold,
               "fee_bps_per_side": fee_bps, "slippage_bps_per_side": slippage_bps,
               "net_log_return": net_total, "gross_log_return": gross_total,
               "net_return": math.expm1(net_total), "gross_return": math.expm1(gross_total),
               "log_cost_drag": -float(trace["log_cost"].sum()), "max_drawdown": drawdown,
               "annualized_daily_log_sharpe": daily_mean / daily_sd * math.sqrt(365.25) if daily_sd else None,
               "annualized_return": math.expm1(net_total * 365.25 / len(days)),
               "one_way_turnover": sides, "completed_trades": len(trades),
               "trade_win_rate": sum(t["net_return"] > 0 for t in trades) / len(trades) if trades else None,
               "mean_trade_net_return": sum(t["net_return"] for t in trades) / len(trades) if trades else None,
               "seconds_long": seconds, "exposure_fraction": seconds / int(timestamps[indices[-1]] - timestamps[indices[0]]),
               "active_days": len(active), "gap_count": len(gaps),
               "gap_gross_log_return": sum(g["gap_gross_log_return"] for g in gaps),
               "delayed_exposure_changes": sum(row[6] > 0 and row[7] != row[9] for row in rows),
               "break_even_symmetric_cost_bps_per_side": -math.expm1(-gross_total / sides) * 10000 if sides else None}
    return {"metrics": metrics, "daily_days": days, "daily_net_log": daily_net, "daily_gross_log": daily_gross,
            "trades": trades, "gaps": gaps, "trace": trace}


def policy_grid():
    hurdle = roundtrip_log_cost()
    choices = [{"id": "cash", "kind": "cash", "entry_multiple": None, "exit_multiple": None,
                "entry_threshold": None, "exit_threshold": None, "roundtrip_log_cost": hurdle}]
    for entry, entry_name in ((0., "0"), (.5, "05"), (1., "1")):
        for exit_, exit_name in ((-.5, "m05"), (0., "0")):
            choices.append({"id": "e"+entry_name+"_x"+exit_name, "kind": "threshold",
                "entry_multiple": entry, "exit_multiple": exit_, "entry_threshold": entry*hurdle,
                "exit_threshold": exit_*hurdle, "roundtrip_log_cost": hurdle})
    return choices


def ledger_oracle(source, scores, start, end, cost, policy):
    result = signed_cash_share_oracle(source["timestamp"], source["prices"][:, 0], scores,
        start=start, end=end, interval_seconds=source["interval_seconds"],
        fee_bps=cost["fee"], slippage_bps=cost["slippage"], policy=policy["kind"],
        entry_threshold=policy.get("entry_threshold") or 0., exit_threshold=policy.get("exit_threshold") or 0.)
    # The producer passes explicit state requests to its old .5/.5 execution
    # interface. These metadata and trace names describe that transport only;
    # the independent account above made its own decisions from raw scores.
    result["metrics"].update(entry_threshold=.5, exit_threshold=.5,
        signal_kind="binary_position_request_from_signed_conditional_log_return",
        score_policy_id=policy["id"], score_entry_threshold=policy.get("entry_threshold"),
        score_exit_threshold=policy.get("exit_threshold"))
    if policy["kind"] == "buy_hold":
        result["trace"]["signal_request"][:] = np.nan
    for field in ("position_before", "desired", "position_after"):
        result["trace"][field] = result["trace"][field].astype(np.int8)
    return result


def json_lines(path):
    def invalid(value):
        raise ValueError("nonfinite JSONL literal: "+value)
    return [json.loads(line, parse_constant=invalid) for line in Path(path).read_text().splitlines() if line.strip()]


def committed_implementation(run, protocol_path, repository=None):
    """Bind retained code bytes to the reported commit and published ancestor."""
    repo=Path(repository) if repository is not None else HERE.parents[1]
    expected_path='experiments/geometry_information/round3_protocol.json'
    require(run['protocol_repository_path']==expected_path,'R3 protocol repository path')
    impl=run['implementation'];head=impl['git_head'];freeze=run['freeze_commit']
    require(re.fullmatch(r'[0-9a-f]{40}',head) and re.fullmatch(r'[0-9a-f]{40}',freeze),'R3 commit identity syntax')
    def git(arguments):
        try:
            return subprocess.run(['git',*arguments],cwd=repo,check=True,capture_output=True).stdout
        except subprocess.CalledProcessError as error:
            raise ValueError('R3 retained commit/ancestry unavailable or invalid') from error
    require(git(['show',freeze+':'+expected_path])==Path(protocol_path).read_bytes(),'R3 published frozen protocol bytes')
    git(['merge-base','--is-ancestor',freeze,head])
    for relative,checksum in impl['files'].items():
        committed=git(['show',head+':'+relative])
        require(hashlib.sha256(committed).hexdigest()==checksum,'R3 reported commit does not bind producer bytes: '+relative)


def checked_manifest(args, protocol):
    root = args.run.resolve()
    manifest = json_file(root/"manifest.json")
    require(manifest["schema"] == "filang-interaction-payoff-run-manifest-v1", "R3 manifest schema")
    require((root/"manifest.sha256").read_text() == digest(root/"manifest.json")+"\n", "R3 manifest seal")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and p not in (root/"manifest.json", root/"manifest.sha256") and p.resolve() != args.out.resolve()}
    require(actual == set(manifest["files"]), "unsealed/missing R3 artifacts")
    for relative, record in manifest["files"].items():
        path = (root/relative).resolve()
        require(not Path(relative).is_absolute() and root in path.parents and path.is_file(), "R3 artifact path escape")
        require(path.stat().st_size == record["bytes"] and digest(path) == record["sha256"], "R3 artifact identity: "+relative)
    require((root/"protocol.json").read_bytes() == args.protocol.read_bytes(), "R3 frozen protocol bytes")
    profile = admitted_protocol(args.protocol)
    run = json_file(root/"run.json")
    require(run["schema"] == "filang-interaction-payoff-run-v1" and run["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT",
            "R3 run incomplete")
    require(run["protocol_sha256"] == digest(args.protocol) and run["freeze_commit"] == profile["freeze_commit"] and
            run["attempt_id"] == "R3" and run["experiment_id"] == protocol["experiment_id"], "R3 protocol/freeze identity")
    require(run["amendments"] == [] and run["deviations"] == [], "undeclared R3 amendment/deviation")
    catalogue_contract(protocol,root)
    require(run['catalogue_repository_path']==CATALOGUE_PATH and run['catalogue_sha256']==CATALOGUE_SHA256,
            'R3 run catalogue identity')
    implementation = run["implementation"]
    require(implementation["worktree_status_porcelain"] == "" and re.fullmatch(r"[0-9a-f]{40}", implementation["git_head"]),
            "R3 execution implementation commit/worktree")
    names = {"experiments/geometry_information/"+name for name in ("run_round3.py", "interaction_returns.py", "interactions.py", "exact_bootstrap.py", "returns.py", "common.py", "economics.py", "round3_catalogue.json")}
    require(set(implementation["files"]) == names and json_digest(implementation["files"]) == implementation["sha256"],
            "R3 implementation coverage/identity")
    for relative, checksum in implementation["files"].items():
        require(digest(HERE.parents[1]/relative) == checksum, "R3 retained/current implementation: "+relative)
    committed_implementation(run,args.protocol)
    provenance = json_file(root/"provenance.json")
    require(digest(root/"provenance.json") == run["source_provenance_sha256"] == digest(args.data_dir/"provenance.json"),
            "R3 source provenance identity")
    require(provenance["protocol_sha256"] == protocol["predecessor"]["protocol_sha256"] and len(provenance["sources"]) == 5,
            "R3 predecessor source provenance")
    for spec in protocol["data"]["sources"]:
        matches = [entry for entry in provenance["sources"] if entry["minutes"] == spec["minutes"]]
        require(len(matches) == 1, "R3 source timeframe uniqueness")
        entry = matches[0]
        for name in ("repo", "revision", "filename", "sha256", "expected_source_rows", "expected_source_bytes", "minutes"):
            require(entry["source"][name] == spec[name], "R3 raw pin "+name)
        raw = args.data_dir/"raw"/spec["filename"]
        require(raw.stat().st_size == spec["expected_source_bytes"] and digest(raw) == spec["sha256"] == entry["source_sha256"],
                "R3 raw pinned bytes")
        require(entry["csv_sha256"] == spec["prepared_csv_sha256"] and entry["missing_grid_bars"] == spec["missing_grid_bars"],
                "R3 prepared-source metadata")
    return manifest, run


def feature_stage(args, protocol):
    catalogue_contract(protocol,args.run)
    receipts=[];full_names=feature_names(10,'I')
    for spec in protocol['data']['sources']:
        minutes=spec['minutes']
        source=independent.load_source(args.data_dir/f'{minutes}m/ohlcv.csv',minutes*60,spec['prepared_csv_sha256'])
        require(len(source['timestamp'])==spec['expected_source_rows'] and source['missing_grid_bars']==spec['missing_grid_bars'],
                'R3 source row/gap counts')
        receipt,rows=independent.audit_native_keys(args.keys_root/f'{minutes}m',source,protocol)
        records=np.memmap(args.keys_root/f'{minutes}m/keys.bin',mode='r',dtype='<u8',offset=168,shape=(len(rows),5))
        hashes={(n,f):hashlib.sha256() for n in HISTORIES for f in FAMILIES};index_hash=hashlib.sha256()
        for start in range(0,len(rows),4096):
            selected=rows[start:start+4096]
            ranks,up=independent.decode_words(records[start:start+len(selected),1:])
            raw_ids=raw_interaction_indices(source['prices'],selected)
            require(np.array_equal(raw_ids,key_interaction_indices(ranks,up)),'R3 raw/native interaction indices')
            index_hash.update(np.ascontiguousarray(raw_ids,dtype='<i2').tobytes())
            block=np.zeros((len(selected),225),dtype=np.uint8);block[np.arange(len(selected))[:,None],raw_ids]=1
            for n in HISTORIES:
                raw_additive=independent.raw_features(source['prices'],selected,n,'G')
                require(np.array_equal(raw_additive,independent.key_features(ranks,up,n,'G')),'R3 additive raw/native feature parity')
                hashes[n,'A'].update(raw_additive.tobytes())
                hashes[n,'I'].update(np.ascontiguousarray(np.column_stack((raw_additive,block)),dtype=np.uint8).tobytes())
        receipt['features']={family+str(n):{'n':n,'family':family,'columns':feature_names(n,family),
            'shape':[len(rows),len(feature_names(n,family))],'sha256':hashes[n,family].hexdigest()} for n in HISTORIES for family in FAMILIES}
        receipt['catalogue_sha256']=CATALOGUE_SHA256
        receipt['interaction_indices']={'dtype':'<i2','shape':[len(rows),2],'sha256':index_hash.hexdigest()}
        receipt['all_interaction_indices_and_columns_checked']=True
        receipt['minutes']=minutes
        if args.run is not None:
            expected={'schema':'filang-interaction-payoff-features-v1','minutes':minutes,
                'source_sha256':source['sha256'],'source_rows':len(source['timestamp']),
                'native':{'context_sha256':receipt['context_sha256'],'manifest_sha256':receipt['native_manifest_sha256'],
                    'keys_sha256':receipt['keys_file_sha256'],'engine_sha256':receipt['engine_sha256']},
                'record_count':len(rows),'record_indices_sha256':receipt['record_indices_sha256'],
                'ranks_sha256':receipt['ranks_sha256'],'up_sha256':receipt['up_flags_sha256'],
                'catalogue_sha256':CATALOGUE_SHA256,'interaction_indices':receipt['interaction_indices'],
                'features':{str(n):{family:{'shape':receipt['features'][family+str(n)]['shape'],'dtype':'uint8',
                    'sha256':receipt['features'][family+str(n)]['sha256'],'columns_sha256':json_digest(feature_names(n,family)),
                    'full_I10_projection':[full_names.index(name) for name in feature_names(n,family)]} for family in FAMILIES} for n in HISTORIES}}
            compare(json_file(args.run/f'{minutes}m/features.json'),expected,'R3 complete feature source/catalogue/projection manifest')
            receipt['producer_feature_digests_checked']=True
        receipts.append(receipt)
        print(json.dumps({'features_verified':minutes,'records':len(rows),'interaction_columns':225}),flush=True)
    return receipts


def round_predecessor_binding(protocol):
    """Retain the exact admitted R2 evidence identity when locally available."""
    reference=protocol['round_predecessor']
    folder=(HERE.parents[1]/reference['report_path']).parent
    if not (folder/'manifest.json').exists():
        return {'status':'UNAVAILABLE','report_path':str(folder),
                'expected_manifest_sha256':reference['report_manifest_sha256'],
                'scope':'Published R2 report is absent locally; it is not used to fit or select R3.'}
    checksum=digest(folder/'manifest.json')
    require(checksum==reference['report_manifest_sha256']==(folder/'manifest.sha256').read_text().strip(),
            'R3 round predecessor report seal')
    manifest=json_file(folder/'manifest.json')
    for name in ('protocol.json','analysis.json','verification.json'):
        record=manifest['files'][name];path=folder/name
        require(path.stat().st_size==record['bytes'] and digest(path)==record['sha256'],'R3 predecessor evidence artifact')
    require(digest(folder/'protocol.json')==reference['protocol_sha256'],'R3 predecessor frozen protocol')
    return {'status':'PASS','manifest_sha256':checksum,'report_path':str(folder),
            'protocol_sha256':reference['protocol_sha256'],'verified_merge_commit':reference['verified_merge_commit'],
            'scope':'Exact published R2 protocol/analysis/audit binding checked; R2 computations are not repeated.'}


class Arrays:
    """Strict named-member census; inspect one annual bundle at a time."""
    def __init__(self, root, minutes):
        self.root, self.minutes = Path(root), minutes
        index = json_file(self.root/f"{minutes}m/arrays.json")
        require(index["schema"] == "filang-interaction-payoff-arrays-v1", "R3 array index schema")
        self.files = index["files"]
        require(set(self.files) == {f"year{year}.npz" for year in YEARS}|{"bootstrap.npz"}, "R3 array bundle census")
        self.cache, self.seen, self.current, self.max_error = {}, set(), None, 0.

    def load(self, filename):
        require(filename in self.files, "R3 unindexed bundle")
        if self.current != filename:
            path = self.root/f"{self.minutes}m"/filename
            record = self.files[filename]
            require(path.stat().st_size == record["bytes"] and digest(path) == record["sha256"], "R3 bundle identity")
            self.cache = read_npz(path)
            require(set(self.cache) == set(record["arrays"]), "R3 exact array-member census")
            for name, value in self.cache.items():
                compare(record["arrays"][name], {"dtype": value.dtype.str, "shape": list(value.shape), "sha256": array_digest(value)},
                        "R3 array byte identity")
            self.current = filename
        return self.cache

    def get(self, filename, member, expected=None):
        require(not Path(filename).is_absolute() and filename == f"{self.minutes}m/"+Path(filename).name,
                "R3 array-reference timeframe/path")
        basename = Path(filename).name
        values = self.load(basename)
        require(member in values, "R3 missing referenced array")
        self.seen.add((basename, member))
        value = values[member]
        if expected is not None:
            require(value.dtype == np.asarray(expected).dtype, "R3 expected array dtype: "+member)
            self.max_error = max(self.max_error, compare(value, expected, "R3 array values: "+member))
        return value

    def finish(self):
        wanted = {(filename, member) for filename, record in self.files.items() for member in record["arrays"]}
        require(self.seen == wanted, "R3 unaudited binary members: "+str(sorted(wanted-self.seen)[:8]))
        return len(wanted)


def statistics_identity(source, receipt, labels, start, end, protocol_sha, implementation_sha):
    rows = np.flatnonzero(labels["target_valid"])
    value = {"source_sha256": source["sha256"], "native_keys_sha256": receipt["keys_file_sha256"],
        "full_feature_sha256": receipt["features"]["I10"]["sha256"],
        "full_feature_columns_sha256": json_digest(feature_names(10, "I")),
        "fit_rows_sha256": array_digest(rows, "<i8"),
        "fit_targets_sha256": array_digest(labels["target_log_return"][rows], "<f8"), "fit_count": len(rows),
        "fit_start": start, "fit_end_exclusive": end, "protocol_sha256": protocol_sha,
        "implementation_sha256": implementation_sha,"catalogue_sha256":CATALOGUE_SHA256,
        "interaction_indices_sha256":array_digest(raw_interaction_indices(source['prices'],rows),'<i2')}
    value["statistics_id"] = json_digest(value)
    return value


def audit_statistics(record, identity, source, labels, year, arrays):
    rows = np.flatnonzero(labels["target_valid"])
    x = raw_features(source["prices"], rows, 10, "I").astype(np.float64)
    y = labels["target_log_return"][rows]
    # This direct reconstruction does not solve any normal equation.
    statistics = {"x_mean": np.mean(x, axis=0), "gram_mean": x.T@x/len(y),
                  "xy_mean": x.T@y/len(y), "y_mean": np.asarray(np.mean(y)),
                  "y2_mean": np.asarray(np.dot(y,y)/len(y))}
    del x
    names = {name: "statistics__"+identity["statistics_id"]+"__"+name for name in statistics}
    path = f"{source['interval_seconds']//60}m/year{year}.npz"
    identities = {}
    for name, value in statistics.items():
        actual = arrays.get(path, names[name], np.asarray(value, dtype=np.float64))
        identities[name] = {"dtype": actual.dtype.str, "shape": list(actual.shape), "sha256": array_digest(actual)}
    compare(record, {"schema": "filang-interaction-payoff-statistics-v1", **identity, "first_outer_year": year,
        "arrays_file": path, "arrays": names, "array_identities": identities,
        "reuse_scope": "within_attempt_exact_sample_only",
        "construction_method":"float64_additive_gram_sparse_cross_and_int64_interaction_counts"}, "R3 statistics provenance")
    return statistics


def audit_fit(model, source, receipt, labels, family, n, penalty, stage, fold, identity,
              statistics, cache_hit, validation=None, fitting_features=None, validation_features=None):
    rows = np.flatnonzero(labels["target_valid"])
    y = labels["target_log_return"][rows]
    x = raw_features(source["prices"], rows, n, family).astype(np.float64) if fitting_features is None else fitting_features
    full_names = feature_names(10, "I")
    projection = [full_names.index(name) for name in feature_names(n, family)]
    expected = {"schema": "filang-interaction-payoff-fit-v1", "minutes": source["interval_seconds"]//60,
        "outer_year": fold["year"], "family": family, "n": n, "lambda": penalty, "stage": stage,
        "fit_start": identity["fit_start"], "fit_end_exclusive": identity["fit_end_exclusive"],
        "fit_count": len(rows), "fit_zero_count": int(np.sum(y == 0)),
        "fit_rows_sha256": array_digest(rows,"<i8"), "fit_targets_sha256": array_digest(y,"<f8"),
        "source_sha256": source["sha256"], "native_keys_sha256": receipt["keys_file_sha256"],
        "protocol_sha256": identity["protocol_sha256"], "implementation_sha256": identity["implementation_sha256"],
        "feature_sha256": receipt["features"][family+str(n)]["sha256"],
        "feature_columns_sha256": json_digest(feature_names(n,family)),
        "statistics_id": identity["statistics_id"], "statistics_cache_hit": cache_hit,
        "statistics_projection": projection, "fit_cache_hit": False}
    expected["fit_id"] = json_digest(expected)
    compare({key:model[key] for key in expected},expected,"R3 fitting identities")
    beta = np.asarray(model["coefficients"],dtype=np.float64)
    theta = np.concatenate(([model["intercept"]],beta))
    require(np.isfinite(theta).all() and model["coefficient_sha256"] == array_digest(theta,"<f8"), "R3 coefficients identity")
    objective, gradient = ridge_objective_gradient(x,y,model["intercept"],beta,penalty)
    maximum = float(np.max(np.abs(gradient)))
    require(maximum <= DIRECT_GRADIENT_LIMIT, "R3 direct gradient exceeds frozen acceptance")
    require(model["accepted"] is True, "R3 required fit rejected")
    solver = model["solver"]
    require(solver["method"] == "centered-normal-equations-Cholesky" and solver["success"] is True and
            solver["status"] == "direct_gradient_tolerance" and solver["factorizations"] == 1 and
            solver["direct_gradient_tolerance"] == DIRECT_GRADIENT_LIMIT and solver["jitter"] == 0 and solver["fallback"] is None,
            "R3 solver acceptance/constraints")
    error = max(compare(model["objective"],objective,"R3 direct objective"),
                compare(np.asarray(model["gradient"]),gradient,"R3 direct gradient"),
                compare(model["max_abs_gradient"],maximum,"R3 direct gradient maximum"))
    center = statistics["x_mean"][projection]
    matrix = statistics["gram_mean"][np.ix_(projection,projection)] - np.outer(center,center) + penalty*np.eye(len(beta))
    rhs = statistics["xy_mean"][projection] - center*statistics["y_mean"]
    residual = matrix@beta-rhs
    error = max(error,compare(np.asarray(model["normal_residual"]),residual,"R3 normal residual diagnostic"),
                compare(model["max_abs_normal_residual"],float(np.max(np.abs(residual))),"R3 normal maximum"))
    for name in ("wall_seconds","cpu_seconds"):
        require(math.isfinite(model[name]) and model[name] >= 0, "R3 fit timing")
    metrics = None
    if validation is not None:
        selected = validation["target_valid"]
        features = raw_features(source["prices"],np.flatnonzero(selected),n,family).astype(np.float64) if validation_features is None else validation_features
        metrics = squared_error_scores(validation["target_log_return"][selected],features@beta+model["intercept"])
        error = max(error,compare(model["validation_scores"],metrics,"R3 candidate validation scores"))
        require(model["validation_mask_sha256"] == array_digest(selected,np.uint8), "R3 validation sample identity")
    else:
        require("validation_scores" not in model and "validation_mask_sha256" not in model, "R3 refit must not evaluate outer for selection")
    return error, maximum, metrics


CHECKS = {name: True for name in (
    "raw_source_provenance", "all_native_keys", "all_feature_columns_and_projections",
    "all_targets_zeros_masks_boundaries", "all_statistics_samples_values_and_cache_identities",
    "all_fit_rows_targets_direct_objectives_gradients", "all_candidate_mse_and_model_choices",
    "all_unconditional_inner_and_refit_means", "all_full_row_causal_predictions",
    "all_validation_trials_and_policy_choices", "all_signed_score_cash_share_ledgers",
    "all_daily_trade_gap_trace_and_aggregate_metrics", "all_shared_bootstrap_replicas",
    "composite_holm_joint_year_and_activity_criteria", "all_binary_array_members",
    "all_retained_artifact_identities", "no_model_fitting_by_verifier",
    "all_catalogue_states_and_columns", "all_exact_integer_metadata_and_tail_events")}
COVERAGE = {"native_keys":458972,"candidate_fits":640,"refit_fits":40,"policy_choices":60,
    "validation_ledgers":420,"outer_ledgers":400,"ledger_replays":820,"prediction_phases":40,
    "all_records":True,"sampled":False}


def audit_timeframe(args, protocol, receipt, run, tail_diagnostics=None):
    """Audit one complete timeframe; separable for synthetic contract tests."""
    minutes,root = receipt["minutes"],args.run
    folder=root/f"{minutes}m"
    spec=next(spec for spec in protocol["data"]["sources"] if spec["minutes"]==minutes)
    source=independent.load_source(args.data_dir/f"{minutes}m/ohlcv.csv",minutes*60,spec["prepared_csv_sha256"])
    ts=source["timestamp"]
    possible=np.arange(9,len(ts),dtype=np.int64)
    causal=possible[(ts[possible]-ts[possible-9]==9*minutes*60)&
        (ts[possible-9]>=epoch(protocol["data"]["history_start"]))&(ts[possible]<epoch(protocol["data"]["end_exclusive"]))]
    protocol_sha=digest(args.protocol);implementation_sha=run["implementation"]["sha256"]
    arrays=Arrays(root,minutes)
    fits=json_lines(folder/"fits.jsonl");stats_records=json_lines(folder/"statistics.jsonl")
    selections=json_lines(folder/"selections.jsonl");ledger_records=json_lines(folder/"ledgers.jsonl")
    require((len(fits),len(stats_records),len(selections),len(ledger_records))==(136,5,12,164),"R3 timeframe record census")
    fit_map={(m['outer_year'],m['family'],m['stage'],m['n'],m['lambda']):m for m in fits}
    stats_map={m['statistics_id']:m for m in stats_records}
    selection_map={(m['outer_year'],m['family']):m for m in selections}
    ledger_map={(m['outer_year'],m['phase'],m['scenario'],m['family'],m['policy']['id']):m for m in ledger_records}
    require(len(fit_map)==136 and len(stats_map)==5 and len(selection_map)==12 and len(ledger_map)==164,"R3 duplicate records")
    used_fits,used_stats,used_selections,used_ledgers=[],[],[],[]
    coverage={k:0 for k in COVERAGE if k not in ('native_keys','all_records','sampled')}
    error=gradient_max=0.
    stats_cache={};folds=[];daily_folds=[];retained_daily_folds=[]
    if tail_diagnostics is None:
        tail_diagnostics=[]
    costs=protocol['economics']['cost_scenarios_bps_per_side'];primary=next(x for x in costs if x['name']=='primary')
    policies=policy_grid()
    ledger_parts={cost['name']:{family:{} for family in (*FORECASTERS,'cash','buy_hold')} for cost in costs}
    for fold in protocol['target_and_phases']['outer_folds']:
        year=fold['year'];path=f'{minutes}m/year{year}.npz'
        labels={phase:target_oracle(source,causal,epoch(fold[phase+'_start']),epoch(fold[phase+'_end_exclusive']))
                for phase in ('inner_train','validation','refit','outer')}
        stats={}
        for phase in ('inner_train','refit'):
            identity=statistics_identity(source,receipt,labels[phase],epoch(fold[phase+'_start']),
                epoch(fold[phase+'_end_exclusive']),protocol_sha,implementation_sha)
            sid=identity['statistics_id'];hit=sid in stats_cache
            require(sid in stats_map,'R3 missing exact-sample statistics')
            if not hit:
                stats_cache[sid]=audit_statistics(stats_map[sid],identity,source,labels[phase],year,arrays)
                used_stats.append(stats_map[sid])
            stats[phase]=(identity,stats_cache[sid],hit)
        inner,refit,choices={},{},{}
        for family in FAMILIES:
            candidates=[]
            for n in HISTORIES:
                fitting_features=raw_features(source['prices'],np.flatnonzero(labels['inner_train']['target_valid']),n,family).astype(np.float64)
                validation_features=raw_features(source['prices'],np.flatnonzero(labels['validation']['target_valid']),n,family).astype(np.float64)
                for penalty in protocol['estimation']['lambda_grid_descending']:
                    model=fit_map[year,family,'inner',n,penalty]
                    discrepancy,maximum,metrics=audit_fit(model,source,receipt,labels['inner_train'],family,n,penalty,
                        'inner',fold,*stats['inner_train'],validation=labels['validation'],
                        fitting_features=fitting_features,validation_features=validation_features)
                    error=max(error,discrepancy);gradient_max=max(gradient_max,maximum)
                    candidates.append({**model,'validation_mse':metrics['mse'],'oracle_validation_scores':metrics})
                    used_fits.append(model);coverage['candidate_fits']+=1
            del fitting_features,validation_features
            best=select_model(candidates)
            chosen=fit_map[year,family,'refit',best['n'],best['lambda']]
            discrepancy,maximum,_=audit_fit(chosen,source,receipt,labels['refit'],family,best['n'],best['lambda'],
                'refit',fold,*stats['refit'])
            error=max(error,discrepancy);gradient_max=max(gradient_max,maximum)
            used_fits.append(chosen);coverage['refit_fits']+=1
            inner[family],refit[family]=best,chosen
            choices[family]={'schema':'filang-interaction-payoff-selection-v1','minutes':minutes,'outer_year':year,'family':family,
                'n':best['n'],'lambda':best['lambda'],'validation_minimum_mse':min(m['validation_mse'] for m in candidates),
                'validation_selected_mse':best['validation_mse'],'inner_fit_id':best['fit_id'],'refit_fit_id':chosen['fit_id'],
                'inner_coefficient_sha256':best['coefficient_sha256'],'refit_coefficient_sha256':chosen['coefficient_sha256']}
        means={stage:unconditional_mean(labels[phase],stage,stats[phase][0]['statistics_id'])
               for stage,phase in (('inner','inner_train'),('refit','refit'))}
        choices['U']={'schema':'filang-interaction-payoff-selection-v1','minutes':minutes,'outer_year':year,'family':'U','n':None,'lambda':None,
            'inner_mean':means['inner'],'refit_mean':means['refit'],'inner_fit_id':means['inner']['fit_id'],
            'refit_fit_id':means['refit']['fit_id']}
        phases,predictions,refs={},{},{}
        for phase,models,mean_stage in (('validation',inner,'inner'),('outer',refit,'refit')):
            expected=labels[phase]
            prediction_mask=expected['causal_feature_valid']&expected['phase_mask']
            model_refs={}
            for family in FAMILIES:
                model=models[family]
                x=raw_features(source['prices'],np.flatnonzero(prediction_mask),model['n'],family).astype(np.float64)
                mu=np.full(len(ts),np.nan)
                mu[prediction_mask]=x@np.asarray(model['coefficients'])+model['intercept']
                expected['mu_'+family]=mu
                model_refs[family]={'fit_id':model['fit_id'],'coefficient_sha256':model['coefficient_sha256']}
            expected['mu_U']=np.full(len(ts),np.nan);expected['mu_U'][prediction_mask]=means[mean_stage]['mean']
            model_refs['U']={'fit_id':means[mean_stage]['fit_id'],'mean':means[mean_stage]['mean']}
            for name,value in expected.items():arrays.get(path,phase+'__'+name,value)
            mask=expected['target_valid']
            scores={family:squared_error_scores(expected['target_log_return'][mask],expected['mu_'+family][mask]) for family in FORECASTERS}
            predictions[phase]={'phase_start':epoch(fold[phase+'_start']),'phase_end_exclusive':epoch(fold[phase+'_end_exclusive']),
                'arrays_file':path,'array_prefix':phase,'prediction_count':int(prediction_mask.sum()),'models':model_refs,'scores':scores}
            phases[phase],refs[phase]=expected,model_refs;coverage['prediction_phases']+=1

        def replay(phase,cost,family,policy,model,score):
            nonlocal error
            ledger=ledger_oracle(source,score,epoch(fold[phase+'_start']),epoch(fold[phase+'_end_exclusive']),cost,policy)
            record=ledger_map[year,phase,cost['name'],family,policy['id']]
            error=max(error,audit_ledger(record,ledger,source,receipt,fold,phase,cost['name'],family,policy,model,
                protocol_sha,implementation_sha,arrays))
            used_ledgers.append(record);coverage[phase+'_ledgers']+=1;coverage['ledger_replays']+=1
            return ledger,record

        for family in FORECASTERS:
            trials=[]
            for policy in policies:
                ledger,record=replay('validation',primary,family,policy,refs['validation'][family],phases['validation']['mu_'+family])
                trials.append({**record,'metrics':ledger['metrics']})
            best=select_policy(trials)
            choices[family].update(policy=best['policy'],selected_validation_ledger_id=best['ledger_id'],
                validation_maximum_net_log_return=max(t['metrics']['net_log_return'] for t in trials),
                validation_selected_net_log_return=best['metrics']['net_log_return'],
                policy_trials=[{'policy_id':t['policy']['id'],'ledger_id':t['ledger_id'],
                    'net_log_return':t['metrics']['net_log_return'],'one_way_turnover':t['metrics']['one_way_turnover']} for t in trials])
            error=max(error,compare(selection_map[year,family],choices[family],'R3 model/mean/policy selection'))
            used_selections.append(selection_map[year,family]);coverage['policy_choices']+=1
        result={'year':year,'selected':choices,'predictions':predictions,'economics':{}}
        for cost in costs:
            result['economics'][cost['name']]={}
            for family in (*FORECASTERS,'cash','buy_hold'):
                if family in FORECASTERS:
                    policy,model,score=choices[family]['policy'],refs['outer'][family],phases['outer']['mu_'+family]
                else:
                    policy=policies[0] if family=='cash' else {'id':'buy_hold','kind':'buy_hold'}
                    model,score=None,np.full(len(ts),np.nan)
                ledger,_=replay('outer',cost,family,policy,model,score)
                result['economics'][cost['name']][family]=ledger['metrics']
                ledger['trace']={k:ledger['trace'][k] for k in ('timestamp','net_log_return')}
                ledger.pop('gaps')
                ledger_parts[cost['name']][family][year]=ledger
        g,b=ledger_parts['primary']['I'][year],ledger_parts['primary']['A'][year]
        require(np.array_equal(g['daily_days'],b['daily_days']),'R3 shared complete daily axes')
        daily_folds.append({'I_minus_A':g['daily_net_log']-b['daily_net_log'],'I_minus_cash':g['daily_net_log']})
        retained_daily={}
        for family in ('A','I'):
            record=ledger_map[year,'outer','primary',family,choices[family]['policy']['id']]
            # These exact-byte intermediates have already passed complete
            # cash/share, trace and daily reconstruction in audit_ledger.
            retained_daily[family]=arrays.get(path,record['arrays']['daily_net_log'])
        retained_daily_folds.append({'I_minus_A':retained_daily['I']-retained_daily['A'],
                                     'I_minus_cash':retained_daily['I']})
        result['effects']={'I_minus_A':g['metrics']['net_log_return']-b['metrics']['net_log_return'],
                           'I_minus_cash':g['metrics']['net_log_return']}
        folds.append(result)
        print(json.dumps({'verified_minutes':minutes,'verified_year':year,'candidate_fits':coverage['candidate_fits'],
                          'ledger_replays':coverage['ledger_replays']}),flush=True)
    compare(fits,used_fits,'R3 complete ordered fit journal')
    compare(stats_records,used_stats,'R3 complete ordered statistics journal')
    compare(selections,used_selections,'R3 complete ordered selection journal')
    compare(ledger_records,used_ledgers,'R3 complete ordered ledger journal')
    economics={label:{cost:{family:independent.aggregate_ledger_oracle(parts,years) for family,parts in by_family.items()}
        for cost,by_family in ledger_parts.items()} for label,years in
        (('all_outer',list(YEARS)),('continuous_2024_plus',[2024,2025,2026]))}
    prepared=exact_encoding_oracle(retained_daily_folds)
    metadata=json_file(folder/'bootstrap-exact.json')
    require(json_digest(metadata)==json_digest(prepared['metadata']),'R3 complete exact integer metadata')
    compare(metadata,prepared['metadata'],'R3 exact decimal numerator vectors and encoding')
    bootstrap={}
    for block in (7,1,28):
        settings=protocol['inference']['bootstrap']
        _,draws=paired_daily_bootstrap(daily_folds,minutes,block,settings['replicates'],settings['base_seed'])
        ordinary=np.column_stack([draws[name+'__ordinary'] for name in ('I_minus_A','I_minus_cash')])
        centered=np.column_stack([draws[name+'__centered'] for name in ('I_minus_A','I_minus_cash')])
        saved_ordinary=arrays.get(f'{minutes}m/bootstrap.npz',f'block{block}__ordinary',ordinary)
        saved_centered=arrays.get(f'{minutes}m/bootstrap.npz',f'block{block}__centered',centered)
        expected_hits=exact_tail_oracle(prepared,minutes,block,settings['replicates'],settings['base_seed'])
        hits=arrays.get(f'{minutes}m/bootstrap.npz',f'block{block}__exact_hits',expected_hits)
        summary=exact_bootstrap_summary(prepared,hits,saved_ordinary,saved_centered,minutes,block,
            settings['replicates'],settings['base_seed'])
        bootstrap[str(block)]=summary
        for name,values in summary['comparisons'].items():
            tail_diagnostics.append({'minutes':minutes,'block_days':block,'comparison':name,'replicates':settings['replicates'],
                'exact_tail_count':values['exact_tail_count'],'p_one_sided':values['p_one_sided'],
                'encoding_sha256':summary['exact_encoding_sha256'],'exact_hits_sha256':summary['exact_hits_sha256'],
                'integer_metadata_match':True,'exact_tail_bits_match':True})
    result={'minutes':minutes,'folds':folds,'bootstrap':bootstrap,'economics':economics,
        'joint_positive_years':sum(all(value>0 for value in f['effects'].values()) for f in folds),
        'completed_I_trades':economics['all_outer']['primary']['I']['completed_trades']}
    error=max(error,compare(json_file(folder/'summary.json'),result,'R3 complete timeframe summary'),arrays.max_error)
    members=arrays.finish()
    timings=json_file(folder/'timings.json')
    expected_counts={'minutes':minutes,'inner_fits':128,'refits':8,'statistics_built':5,'policy_choices':12,
                     'validation_ledgers':84,'outer_ledgers':80,'prediction_phases':8}
    compare({key:timings[key] for key in expected_counts},expected_counts,'R3 timing coverage')
    require(isinstance(timings['stage_timing_note'],str),'R3 timing overlap disclosure')
    require(all(math.isfinite(value) and value>=0 for key,value in timings.items() if key not in expected_counts and key!='stage_timing_note'),'R3 timings finite')
    return result,coverage,error,gradient_max,members


def full_stage(args, protocol, receipts, manifest, run):
    root=args.run;error=gradient_max=0.;results=[];members=0;tail_diagnostics=[]
    require(all(r['producer_feature_digests_checked'] for r in receipts),'R3 complete feature matrix audit required')
    features=json_file(root/'features.json')
    compare(features,{'schema':'filang-interaction-payoff-features-v1','protocol_sha256':digest(args.protocol),'catalogue_sha256':CATALOGUE_SHA256,
        'column_names':{str(n):{family:feature_names(n,family) for family in FAMILIES} for n in HISTORIES},
        'timeframes':[json_file(root/f'{minutes}m/features.json') for minutes in TIMES]},'R3 global feature manifest')
    coverage={key:0 for key in COVERAGE if key not in ('all_records','sampled')}
    coverage.update(native_keys=sum(r['records_checked'] for r in receipts),all_records=True,sampled=False)
    for receipt in receipts:
        result,counts,discrepancy,maximum,array_count=audit_timeframe(args,protocol,receipt,run,tail_diagnostics)
        results.append(result);error=max(error,discrepancy);gradient_max=max(gradient_max,maximum);members+=array_count
        for key,value in counts.items():coverage[key]+=value
    ranked=sorted(results,key=lambda r:(r['bootstrap']['7']['intersection_union_p'],r['minutes']))
    previous=0.
    for rank,result in enumerate(ranked):
        previous=max(previous,min(1.,(len(ranked)-rank)*result['bootstrap']['7']['intersection_union_p']))
        result['p_holm']=previous
    for result in results:
        c=result['bootstrap']['7']['comparisons']
        conditions={'both_positive_gain':all(value['mean_daily_net_log_gain']>0 for value in c.values()),
            'both_ci_above_zero':all(value['ci95_low']>0 for value in c.values()),'holm_below_005':result['p_holm']<.05,
            'three_same_positive_years':result['joint_positive_years']>=3,'twenty_I_completed_trades':result['completed_I_trades']>=20}
        result.update(conditions=conditions,criterion_met=all(conditions.values()),outcome='inconclusive',
                      outcome_if_verified='supported' if all(conditions.values()) else 'not-supported')
    analysis=json_file(root/'analysis.json')
    require(analysis['schema']=='filang-interaction-payoff-analysis-v1' and analysis['experiment_id']==protocol['experiment_id'] and
            analysis['protocol_sha256']==digest(args.protocol) and analysis['status']=='COMPLETE_PENDING_INDEPENDENT_AUDIT',
            'R3 analysis status/identity')
    require(analysis['prior_exposure']==protocol['round_predecessor']['prior_exposure'] and
            analysis['primary_scope']==protocol['primary_scope'],'R3 reported scope and prior exposure')
    compare(analysis['coverage'],{'inner_fits':640,'refits':40,'statistics_built':25,'policy_choices':60,
        'validation_ledgers':420,'outer_ledgers':400,'prediction_phases':40},'R3 analysis census')
    error=max(error,compare(analysis['timeframes'],results,'R3 complete pooled inference/Holm/criteria'))
    compare(coverage,COVERAGE,'R3 full required coverage')
    expected_files={'protocol.json','provenance.json','run.json','features.json','analysis.json','catalogue.json'}
    for minutes in TIMES:
        expected_files.update(f'{minutes}m/'+name for name in ('features.json','fits.jsonl','statistics.jsonl','selections.jsonl',
            'ledgers.jsonl','arrays.json','summary.json','timings.json','bootstrap.npz','bootstrap-exact.json',*(f'year{year}.npz' for year in YEARS)))
    require(set(manifest['files'])==expected_files,'R3 exact producer artifact census')
    require(len(tail_diagnostics)==30 and {(row['minutes'],row['block_days'],row['comparison']) for row in tail_diagnostics}==
            {(minutes,block,name) for minutes in TIMES for block in (7,1,28) for name in ('I_minus_A','I_minus_cash')},
            'R3 complete numerical/tail diagnostic census')
    return {'coverage':coverage,'max_numeric_error':error,'max_independent_fit_gradient':gradient_max,
        'audited_array_members':members,'all_array_members_checked':True,'scientific_models_checked':True,
        'no_model_fitting_by_verifier':True,'checks':CHECKS,'audited_timeframes':list(TIMES),'audited_outer_years':list(YEARS),
        'producer_manifest_sha256':digest(root/'manifest.json'),'analysis_sha256':digest(root/'analysis.json'),
        'catalogue_sha256':CATALOGUE_SHA256,
        'catalogue':{'oriented_two_bar_states':7452,'body_entries':75,'range_entries':150,'all_columns_reachable':True},
        'tail_method':EXACT_TAIL_METHOD,'all_exact_metadata_and_tail_events_checked':True,
        'exact_bootstrap_metadata_checked':5,'exact_tail_event_count':60000,'exact_tail_audit':tail_diagnostics}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('features','full'),default='full')
    parser.add_argument('--run',type=Path)
    parser.add_argument('--keys-root',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,default=HERE/'round3_protocol.json')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv);began=time.perf_counter()
    profile=admitted_protocol(args.protocol);protocol=json_file(args.protocol)
    require(protocol['schema']=='filang-geometry-interaction-payoff-protocol-v1' and protocol['attempt_id']=='R3','R3 protocol schema')
    full=args.stage=='full'
    require(not full or args.run is not None,'R3 full audit requires --run')
    manifest,run=checked_manifest(args,protocol) if full else (None,None)
    receipts=feature_stage(args,protocol)
    result={'schema':'filang-geometry-interaction-payoff-verification-v1','status':'PASS','stage':args.stage,
        'protocol_sha256':digest(args.protocol),'freeze_commit':profile['freeze_commit'],
        'verifier_sha256':digest(__file__),'independent_helpers_sha256':digest(independent.__file__),
        'scientific_models_checked':False,'native_records_checked':sum(r['records_checked'] for r in receipts),
        'features':receipts,'predecessor_binding':independent.predecessor_binding(args,protocol),
        'round_predecessor_binding':round_predecessor_binding(protocol)}
    if full:
        result.update(full_stage(args,protocol,receipts,manifest,run))
        checked_manifest(args,protocol)
        require(result['producer_manifest_sha256']==digest(args.run/'manifest.json') and
                result['analysis_sha256']==digest(args.run/'analysis.json'),'R3 artifact changed during audit')
    result['elapsed_seconds']=time.perf_counter()-began
    independent.save_json(args.out,result)
    print(json.dumps({'status':'PASS','stage':args.stage,'receipt':str(args.out)}),flush=True)


def unconditional_mean(labels, stage, statistics_id):
    rows = np.flatnonzero(labels["target_valid"])
    y = labels["target_log_return"][rows]
    record = {"stage":stage,"mean":float(np.mean(y)),"fit_count":len(y),"fit_zero_count":int(np.sum(y==0)),
        "fit_rows_sha256":array_digest(rows,"<i8"),"fit_targets_sha256":array_digest(y,"<f8"),"statistics_id":statistics_id}
    record["fit_id"] = json_digest(record)
    return record


TRADE_TYPES = {"entry_row":"<i8","entry_timestamp":"<i8","entry_open":"<f8","entry_log_cost":"<f8",
    "signal_row":"<i8","signal_close":"<i8","entry_delay_seconds":"<i8","exit_row":"<i8","exit_timestamp":"<i8",
    "exit_open":"<f8","exit_log_cost":"<f8","gross_log_return":"<f8","net_log_return":"<f8","net_return":"<f8",
    "holding_seconds":"<i8","terminal_liquidation":"?"}
GAP_TYPES = {"previous_row":"<i8","row":"<i8","previous_open":"<i8","open_timestamp":"<i8",
    "missing_seconds":"<i8","signal_close":"<i8","delay_seconds":"<i8","position_before":"i1","position_after":"i1",
    "gap_gross_log_return":"<f8","net_log_return":"<f8"}


def audit_ledger(record, ledger, source, receipt, fold, phase, scenario, family, policy, model_ref,
                 protocol_sha, implementation_sha, arrays):
    minutes,year = source["interval_seconds"]//60,fold["year"]
    identity = {"schema":"filang-interaction-payoff-ledger-v1","minutes":minutes,"outer_year":year,"phase":phase,
        "phase_start":epoch(fold[phase+"_start"]),"phase_end_exclusive":epoch(fold[phase+"_end_exclusive"]),
        "scenario":scenario,"family":family,"policy":policy,"model":model_ref,
        "source_sha256":source["sha256"],"native_keys_sha256":receipt["keys_file_sha256"],
        "protocol_sha256":protocol_sha,"implementation_sha256":implementation_sha}
    identity["ledger_id"] = json_digest(identity)
    path=f"{minutes}m/year{year}.npz"
    prefix=f"ledger__{phase}__{scenario}__{family}__{policy['id']}"
    names={}
    for name in ("daily_days","daily_net_log","daily_gross_log"):
        member=prefix+"__"+name;names[name]=member
        arrays.get(path,member,ledger[name])
    groups={"trace":ledger["trace"],"trades":{name:np.asarray([row[name] for row in ledger["trades"]],dtype=dtype)
        for name,dtype in TRADE_TYPES.items()},"gaps":{name:np.asarray([row[name] for row in ledger["gaps"]],dtype=dtype)
        for name,dtype in GAP_TYPES.items()}}
    for group,fields in groups.items():
        names[group]={}
        for name,value in fields.items():
            member=prefix+"__"+group+"__"+name;names[group][name]=member
            arrays.get(path,member,value)
    expected={**identity,"metrics":ledger["metrics"],"arrays_file":path,"array_prefix":prefix,"arrays":names,
              "trade_count":len(ledger["trades"]),"gap_count":len(ledger["gaps"])}
    return compare(record,expected,"R3 full ledger record")


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,KeyError,TypeError) as error:
        print('independent R3 audit: '+str(error),file=__import__('sys').stderr)
        raise SystemExit(2)

