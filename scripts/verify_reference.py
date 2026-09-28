#!/usr/bin/env python3
"""Independent NumPy feature arithmetic and cash/share ledger for a frozen report.

This is an optional correctness oracle, not part of the native runtime. Rolling
statistics use materialized windows, not the Rust sliding-moment algorithm.
Execution holds explicit shares and cash, not the native category statistics.
"""
from __future__ import annotations
import argparse
if not __debug__:
    raise RuntimeError("verification must not run with Python assertions disabled")
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import numpy as np


def parse_expr(text: str):
    tokens = iter(re.findall(r'\(|\)|[^\s()]+', text))
    def expression(first=None):
        token = next(tokens) if first is None else first
        if token != '(':
            if token not in ('open','high','low','close','volume'):
                raise ValueError(f'unknown source {token}')
            return (token,)
        op = next(tokens)
        if op == 'constant':
            answer = (op, int(next(tokens), 16))
        elif op in ('lag','skip','diff','mean','mean_sum','std_sum','std','min','max','ema','wilder'):
            answer = (op, int(next(tokens)), expression())
        elif op in ('abs','neg'):
            answer = (op, expression())
        elif op in ('add','sub','mul','div','div0','min2','max2'):
            answer = (op, expression(), expression())
        else:
            raise ValueError(op)
        if next(tokens) != ')':
            raise ValueError('unclosed expression')
        return answer
    result = expression()
    if next(tokens, None) is not None:
        raise ValueError('trailing tokens')
    return result


def feature(expr, columns, cache):
    if expr in cache:
        return cache[expr]
    n = len(columns['close'])
    op = expr[0]
    if op in columns:
        out = columns[op]
    elif op == 'constant':
        out = np.full(n, struct.unpack('>d', expr[1].to_bytes(8, 'big'))[0])
    elif op in ('abs','neg'):
        a = feature(expr[1], columns, cache)
        out = np.abs(a) if op == 'abs' else -a
    elif op in ('add','sub','mul','div','div0','min2','max2'):
        a, b = (feature(e, columns, cache) for e in expr[1:])
        with np.errstate(invalid='ignore', divide='ignore', over='ignore'):
            if op == 'add': out = a + b
            elif op == 'sub': out = a - b
            elif op == 'mul': out = a * b
            elif op == 'div0': out = np.where(np.abs(b) > 1e-12, a / b, 0.0)
            elif op == 'div': out = np.where(np.abs(b) > 1e-12, a / b, np.nan)
            elif op == 'min2': out = np.minimum(a, b)
            else: out = np.maximum(a, b)
    else:
        w, child = expr[1:]
        a = feature(child, columns, cache)
        out = np.full(n, np.nan)
        if op == 'skip':
            out[w:] = a[w:]
        elif op in ('lag','diff'):
            if w < n:
                out[w:] = a[:-w] if op == 'lag' else a[w:] - a[:-w]
        elif op in ('mean_sum','std_sum'):
            total = squares = 0.0
            run = 0
            for t,value in enumerate(a):
                if not np.isfinite(value):
                    total = squares = 0.0; run = 0; continue
                run += 1; total += value; squares += value*value
                if run >= w:
                    mean = total/w; variance = squares/w - mean*mean
                    total -= a[t+1-w]; squares -= a[t+1-w]*a[t+1-w]
                    out[t] = mean if op == 'mean_sum' else (0.0 if variance < 1e-14 else np.sqrt(variance))
        elif op in ('mean','std','min','max'):
            if w <= n:
                windows = np.lib.stride_tricks.sliding_window_view(a, w)
                with np.errstate(invalid='ignore', over='ignore'):
                    reducer = {'mean': np.mean, 'std': np.std, 'min': np.min, 'max': np.max}[op]
                    out[w-1:] = reducer(windows, axis=1)
        elif op in ('ema','wilder'):
            alpha = 2 / (w + 1) if op == 'ema' else 1 / w
            run = 0
            state = 0.0
            for t, value in enumerate(a):
                if not np.isfinite(value):
                    run = 0
                    continue
                run += 1
                if run == w:
                    state = float(np.mean(a[t+1-w:t+1]))
                    out[t] = state
                elif run > w:
                    state = alpha * value + (1-alpha) * state
                    out[t] = state
        else:
            raise ValueError(op)
    out = np.where(np.isfinite(out), out, np.nan)
    cache[expr] = out
    return out


def ledger(open_px, positions, fee, slip, step):
    cash = 1.0
    shares = 0.0
    previous = 1.0
    equity = [1.0]
    returns, trade_returns = [], []
    entry_equity = 1.0
    for i, active in enumerate(positions):
        if active and (i == 0 or not positions[i-1]):
            entry_equity = cash
            shares = cash / (open_px[i] * (1+slip) * (1+fee))
            cash = 0.0
        end_equity = cash + shares * open_px[i+1]
        if active and (i+1 == len(positions) or not positions[i+1]):
            cash = shares * open_px[i+1] * (1-slip) * (1-fee)
            shares = 0.0
            end_equity = cash
            trade_returns.append(end_equity / entry_equity - 1)
        returns.append(end_equity / previous - 1)
        equity.append(end_equity)
        previous = end_equity
    returns, equity = np.asarray(returns), np.asarray(equity)
    sd = np.std(returns, ddof=1)
    gross = np.prod(np.where(positions, open_px[1:] / open_px[:-1], 1.0))
    return {
        'net_return_pct': (equity[-1]-1)*100,
        'gross_return_pct': (gross-1)*100,
        'max_drawdown_pct': np.max(1-equity / np.maximum.accumulate(equity))*100,
        'cagr_pct': np.expm1(np.log(equity[-1])*31557600/(len(positions)*step))*100,
        'sharpe_annualized_naive': float(np.mean(returns)/sd*np.sqrt(31557600/step)) if sd > 1e-12 else None,
        'trades': len(trade_returns),
        'exposure_pct': float(np.mean(positions)*100),
        'mean_bps_per_bar': float(np.mean(returns)*10000),
        'mean_trade_bps': float(np.mean(trade_returns)*10000) if trade_returns else None,
        'periods': len(positions),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--from-date')
    p.add_argument('--to-date')
    p.add_argument('--fee-bps', type=float, default=5)
    p.add_argument('--slip-bps', type=float, default=5)
    p.add_argument('--trace-dir')
    p.add_argument('--out')
    a = p.parse_args()
    frame = np.loadtxt(a.data, delimiter=',', skiprows=1)
    ts = frame[:,0].astype(np.int64)
    columns = {k: frame[:, i+1] for i,k in enumerate(('open','high','low','close','volume'))}
    report = json.loads(Path(a.report).read_text())
    epoch = lambda s: int(datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    start = report.get('evaluation_start') or epoch(a.from_date)
    end = report.get('evaluation_end') or epoch(a.to_date)
    step = int(ts[1] - ts[0])
    fee = report.get('fee_bps', a.fee_bps)/10000
    slip = report.get('slip_bps', a.slip_bps)/10000
    lo, hi = np.searchsorted(ts, [start,end])
    end_signals = hi - 2
    cache = {}
    maximum_error = 0.0
    mask_disagreements = 0
    for row in report['candidates']:
        x = feature(parse_expr(row['expression']), columns, cache)
        signal = np.isfinite(x) & ((x > row['threshold']) if row['greater'] else (x < row['threshold']))
        target = row.get('metrics', row.get('validation'))
        result = ledger(columns['open'][lo+1:hi], signal[lo:end_signals], fee, slip, step)
        for name, actual in result.items():
            expected = target[name]
            if actual is None or expected is None:
                if actual is not None or expected is not None:
                    raise AssertionError((row['id'], name, expected, actual))
                continue
            error = abs(actual - expected)
            maximum_error = max(maximum_error, error)
            if name in ('trades','periods'):
                assert actual == expected, (name, actual, expected)
            else:
                assert np.isclose(actual, expected, rtol=1e-8, atol=1e-7), (row['id'], name, expected, actual)
        if a.trace_dir:
            trace = np.genfromtxt(Path(a.trace_dir) / f"{row['id']}.csv", delimiter=',', skip_header=1)
            mismatch = int(np.count_nonzero(trace[:,2].astype(bool) != signal[lo:end_signals]))
            mask_disagreements += mismatch
            assert mismatch == 0, (row['id'], mismatch)
            assert np.array_equal(np.isfinite(trace[:,1]), np.isfinite(x[lo:end_signals]))
            assert np.allclose(trace[:,1],x[lo:end_signals],rtol=1e-7,atol=1e-8,equal_nan=True)
    evidence = {'status':'PASS','reference':'independent window arithmetic and explicit cash/share ledger',
                'candidates_checked':len(report['candidates']),'numeric_max_absolute_error':maximum_error,
                'position_disagreements':mask_disagreements if a.trace_dir else None,
                'data':a.data,'report':a.report,'numpy_version':np.__version__}
    text = json.dumps(evidence, indent=2)+'\n'
    if a.out: Path(a.out).write_text(text)
    print(text)


if __name__ == '__main__': main()
