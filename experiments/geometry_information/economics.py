"""Causal spot long/cash ledger for the frozen geometry information campaign.

Inputs are original observed rows, never a compressed classification timeline.
All signal values refer to information at that row's scheduled candle close.
Missing bars imply delayed assumed fills, not a claim that the venue was closed.
"""
from __future__ import annotations

import math
import numpy as np


def run_ledger(timestamps, opens, probabilities, *, start: int, end: int,
               interval_seconds: int, fee_bps: float, slippage_bps: float,
               entry_threshold: float = 0.5, exit_threshold: float = 0.5,
               policy: str = "threshold") -> dict:
    """Replay one administratively independent period; liquidate at its last open.

    A buy spends cash with mid-mark factor (1-f)/(1+s); a sell realizes
    factor (1-s)*(1-f). Holdings mark from each observed open to the next.
    A probability of NaN means the feature history is unavailable and requests
    cash after that fact is known. ``buy_hold`` is an administrative benchmark,
    independent of feature availability. Threshold equality remains long.
    """
    ts = np.asarray(timestamps, dtype=np.int64)
    prices = np.asarray(opens, dtype=np.float64)
    p = np.asarray(probabilities, dtype=np.float64)
    if ts.ndim != 1 or prices.shape != ts.shape or p.shape != ts.shape:
        raise ValueError("timestamps, opens and probabilities must be aligned vectors")
    if (len(ts) < 2 or np.any(np.diff(ts) <= 0) or not np.isfinite(prices).all()
            or np.any(prices <= 0) or interval_seconds <= 0 or end <= start):
        raise ValueError("invalid chronological price source or period")
    if np.any(np.diff(ts) % interval_seconds):
        raise ValueError("opening timestamps must preserve the declared interval grid")
    if np.isinf(p).any() or np.any((p[np.isfinite(p)] < 0) | (p[np.isfinite(p)] > 1)):
        raise ValueError("probabilities must be NaN or in [0,1]")
    if not (0 <= exit_threshold <= entry_threshold <= 1):
        raise ValueError("require 0 <= exit threshold <= entry threshold <= 1")
    if policy not in {"threshold", "cash", "buy_hold"}:
        raise ValueError("unknown policy")
    f, s = fee_bps / 10000.0, slippage_bps / 10000.0
    if not (0 <= f < 1 and 0 <= s < 1):
        raise ValueError("costs must be nonnegative and below 100 percent per side")
    rows = np.flatnonzero((ts >= start) & (ts < end))
    if len(rows) < 2:
        raise ValueError("a ledger period needs at least two observed openings")
    m = len(rows)
    net = np.zeros(m)
    gross = np.zeros(m)
    costs = np.zeros(m)
    before = np.zeros(m, dtype=np.int8)
    after = np.zeros(m, dtype=np.int8)
    signal_rows = np.full(m, -1, dtype=np.int64)
    signal_close = np.full(m, -1, dtype=np.int64)
    delay = np.zeros(m, dtype=np.int64)
    desired = np.zeros(m, dtype=np.int8)
    used_p = np.full(m, np.nan)
    trades, gaps = [], []
    position = 0
    entry = None
    seconds_long = 0
    buy_cost = math.log1p(-f) - math.log1p(s)
    sell_cost = math.log1p(-f) + math.log1p(-s)
    for k, j in enumerate(rows):
        j = int(j)
        before[k] = position
        if k:
            previous = int(rows[k - 1])
            delta = int(ts[j] - ts[previous])
            seconds_long += position * delta
            gross[k] = position * math.log(prices[j] / prices[previous])
        # Clear pending decisions on every outer reset. Even a valid feature at
        # a prior-fold close cannot enter this fold's first opening.
        if k and ts[j - 1] >= start:
            signal_rows[k] = j - 1
            signal_close[k] = int(ts[j - 1] + interval_seconds)
            delay[k] = max(0, int(ts[j] - signal_close[k]))
            used_p[k] = p[j - 1]
            if policy == "buy_hold":
                desired[k] = 1
            elif policy == "threshold" and np.isfinite(p[j - 1]):
                threshold = exit_threshold if position else entry_threshold
                desired[k] = int(p[j - 1] >= threshold)
        terminal = k == m - 1
        if terminal:
            desired[k] = 0
        if desired[k] != position:
            if desired[k]:
                costs[k] = buy_cost
                entry = {"entry_row": j, "entry_timestamp": int(ts[j]),
                         "entry_open": float(prices[j]), "entry_log_cost": buy_cost,
                         "signal_row": int(signal_rows[k]),
                         "signal_close": int(signal_close[k]), "entry_delay_seconds": int(delay[k])}
            else:
                costs[k] = sell_cost
                if entry is None:
                    raise AssertionError("exit without an entry")
                trade_gross = math.log(prices[j] / entry["entry_open"])
                trade_net = trade_gross + entry["entry_log_cost"] + sell_cost
                trades.append({**entry, "exit_row": j, "exit_timestamp": int(ts[j]),
                               "exit_open": float(prices[j]), "exit_log_cost": sell_cost,
                               "gross_log_return": trade_gross, "net_log_return": trade_net,
                               "net_return": math.expm1(trade_net),
                               "holding_seconds": int(ts[j] - entry["entry_timestamp"]),
                               "terminal_liquidation": terminal})
                entry = None
            position = int(desired[k])
        after[k] = position
        net[k] = gross[k] + costs[k]
        if k and ts[j] - ts[j - 1] != interval_seconds:
            gaps.append({"previous_row": j - 1, "row": j,
                         "previous_open": int(ts[j - 1]), "open_timestamp": int(ts[j]),
                         "missing_seconds": int(ts[j] - ts[j - 1] - interval_seconds),
                         "signal_close": int(signal_close[k]), "delay_seconds": int(delay[k]),
                         "position_before": int(before[k]), "position_after": position,
                         "gap_gross_log_return": float(gross[k]), "net_log_return": float(net[k])})
    if position or entry is not None:
        raise AssertionError("period must end flat")
    day0, day1 = start // 86400, (end - 1) // 86400
    days = np.arange(day0, day1 + 1, dtype=np.int64)
    day_index = ts[rows] // 86400 - day0
    daily_net = np.bincount(day_index, weights=net, minlength=len(days))
    daily_gross = np.bincount(day_index, weights=gross, minlength=len(days))
    cumulative = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = -np.expm1(cumulative - np.maximum.accumulate(cumulative))
    sides = int(np.count_nonzero(after != before))
    trade_net_sum = sum(t["net_log_return"] for t in trades)
    if not math.isclose(trade_net_sum, float(net.sum()), rel_tol=1e-10, abs_tol=1e-10):
        raise AssertionError("trade accounting does not reconcile to marked equity")
    daily_std = float(np.std(daily_net, ddof=1)) if len(days) > 1 else 0.0
    metrics = {
        "start": int(start), "end_exclusive": int(end), "observed_openings": m,
        "calendar_days": len(days), "terminal_open": int(ts[rows[-1]]),
        "policy": policy, "entry_threshold": entry_threshold, "exit_threshold": exit_threshold,
        "fee_bps_per_side": fee_bps, "slippage_bps_per_side": slippage_bps,
        "net_log_return": float(net.sum()), "gross_log_return": float(gross.sum()),
        "net_return": math.expm1(float(net.sum())), "gross_return": math.expm1(float(gross.sum())),
        "log_cost_drag": float(-costs.sum()), "max_drawdown": float(drawdown.max()),
        "annualized_daily_log_sharpe": float(daily_net.mean() / daily_std * math.sqrt(365.25)) if daily_std else None,
        "annualized_return": math.expm1(float(net.sum()) * 365.25 / len(days)),
        "one_way_turnover": sides, "completed_trades": len(trades),
        "trade_win_rate": float(np.mean([t["net_return"] > 0 for t in trades])) if trades else None,
        "mean_trade_net_return": float(np.mean([t["net_return"] for t in trades])) if trades else None,
        "seconds_long": seconds_long,
        "exposure_fraction": seconds_long / int(ts[rows[-1]] - ts[rows[0]]),
        "active_days": int(np.unique(ts[rows][(before != 0) | (after != 0)] // 86400).size),
        "gap_count": len(gaps), "gap_gross_log_return": sum(g["gap_gross_log_return"] for g in gaps),
        "delayed_exposure_changes": int(np.count_nonzero((delay > 0) & (before != after))),
        # Equivalent symmetric wealth haircut per side, holding the path fixed.
        "break_even_symmetric_cost_bps_per_side": float(-math.expm1(-gross.sum() / sides) * 10000) if sides else None,
    }
    return {"metrics": metrics, "daily_days": days, "daily_net_log": daily_net,
            "daily_gross_log": daily_gross, "trades": trades, "gaps": gaps,
            "trace": {"row": rows, "timestamp": ts[rows], "open": prices[rows],
                      "signal_row": signal_rows, "signal_close": signal_close,
                      "signal_probability": used_p, "delay_seconds": delay,
                      "position_before": before, "desired": desired, "position_after": after,
                      "gross_log_return": gross, "log_cost": costs, "net_log_return": net}}

