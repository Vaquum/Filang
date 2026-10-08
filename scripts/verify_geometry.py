#!/usr/bin/env python3
"""Independent canonical geometry, symbolic coverage and full-risk verification.

The pattern counter uses occupied-level inclusion/exclusion, not the native
chain-merging recurrence. Predicates are rebuilt from CSV endpoint ranks and
occurrence lists. Captured rectangles are checked for constant final positions,
disjoint complete coverage, full u128 weights and sequential cash/share metrics.
Summary runs permit only retained task-winner metric replay; the JSON says so.
The standard-library Python ledger can optionally be accelerated by the existing
independent joint_ledger.c reference. Neither uses the native geometry engine.
"""
from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left
from collections import Counter, OrderedDict
import csv
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
from itertools import combinations_with_replacement, product
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time


U64 = (1 << 64) - 1
WEIGHTS = {"unoriented": (1, 3, 3, 1), "oriented": (1, 4, 5, 2)}
KNOWN_COUNTS = {
    "unoriented": (8, 2568, 5592968, 44418808968, 936239675880968,
                   43216321851028552968, 3840691551111678501624968,
                   599170270107067142441692696968),
    "oriented": (12, 7452, 32160252, 508608936252, 21386422752715452,
                 1971122519237375505852, 349946534568771563626027452,
                 109093488682843434702978214200252),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sealed(path):
    """Validate the appended 64-byte ASCII SHA-256, returning body size/hash."""
    path = Path(path)
    size = path.stat().st_size
    require(size >= 64, "short sealed artifact: " + str(path))
    remaining = size - 64
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while remaining:
            block = source.read(min(1 << 20, remaining))
            require(bool(block), "truncated artifact: " + str(path))
            digest.update(block)
            remaining -= len(block)
        require(source.read(64) == digest.hexdigest().encode("ascii"),
                "artifact checksum mismatch: " + str(path))
        require(not source.read(1), "trailing artifact data")
    return size - 64, digest.hexdigest()


def sealed_body(path):
    size, digest = sealed(path)
    with Path(path).open("rb") as source:
        return source.read(size), digest


def settings(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        require(key not in out, "duplicate configuration key")
        out[key] = value
    return out


def count_by_levels(n, mode):
    """Count surjections onto r rank levels; Python integers never truncate."""
    require(n >= 0 and mode in WEIGHTS, "invalid geometry count domain")
    if n == 0:
        return [1]
    occupied = [0] * (4 * n + 1)
    for r in range(1, 4 * n + 1):
        assignments = sum(weight * math.comb(r, k)
                          for k, weight in enumerate(WEIGHTS[mode], 1) if k <= r)
        occupied[r] = assignments ** n - sum(
            math.comb(r, j) * occupied[j] for j in range(1, r))
        require(occupied[r] >= 0, "negative occupied-level count")
    return occupied


def domain_count(n, mode):
    return sum(count_by_levels(n, mode))


def pattern_text(ranks, directions=None):
    code = "g1:o:" if directions is not None else "g1:u:"
    rows = []
    for i, rank in enumerate(ranks):
        row = ",".join(map(str, rank))
        if directions is not None:
            row += "," + directions[i]
        rows.append(row)
    return code + ";".join(rows)


def parse_pattern(text):
    require(text.startswith(("g1:u:", "g1:o:")), "geometry pattern version/mode")
    oriented = text.startswith("g1:o:")
    ranks, directions = [], [] if oriented else None
    for row in text[5:].split(";") if text[5:] else []:
        fields = row.split(",")
        require(len(fields) == (5 if oriented else 4), "geometry row arity")
        require(all(re.fullmatch(r"0|[1-9][0-9]*", x) for x in fields[:4]),
                "noncanonical rank decimal")
        rank = tuple(map(int, fields[:4]))
        require(all(a <= b for a, b in zip(rank, rank[1:])), "unordered body/wick")
        if oriented:
            direction = fields[4]
            require(direction in ("u", "d", "z"), "body direction")
            require((rank[1] == rank[2]) == (direction == "z"),
                    "body height/direction disagreement")
            directions.append(direction)
        ranks.append(rank)
    values = {v for row in ranks for v in row}
    require(values == set(range(len(values))), "ranks must be dense from zero")
    require(pattern_text(ranks, directions) == text, "noncanonical pattern string")
    return "oriented" if oriented else "unoriented", tuple(ranks), directions


def canonical_pattern(candles, mode):
    """Independent sorting of labeled OHLC prices, retaining exact equality."""
    require(mode in WEIGHTS, "invalid geometry mode")
    endpoints, directions = [], []
    for candle in candles:
        open_, high, low, close = candle[:4]
        require(all(math.isfinite(v) for v in (open_, high, low, close)),
                "nonfinite candle")
        bottom, top = min(open_, close), max(open_, close)
        require(low <= bottom <= top <= high, "invalid OHLC order")
        endpoints.append((low, bottom, top, high))
        directions.append("u" if close > open_ else "d" if close < open_ else "z")
    levels = sorted({v for row in endpoints for v in row})
    lookup = {value: rank for rank, value in enumerate(levels)}
    ranks = [tuple(lookup[value] for value in row) for row in endpoints]
    return pattern_text(ranks, directions if mode == "oriented" else None)


def read_data(path, interval):
    timestamps, candles = [], []
    with Path(path).open(newline="") as source:
        reader = csv.reader(source)
        require(next(reader, None) == ["timestamp", "open", "high", "low", "close", "volume"],
                "CSV schema")
        for row in reader:
            require(len(row) == 6, "CSV row arity")
            timestamp = int(row[0])
            values = tuple(map(float, row[1:]))
            require(all(math.isfinite(v) for v in values), "nonfinite OHLCV")
            require(all(v > 0 for v in values[:4]) and values[4] >= 0,
                    "CSV price/volume domain")
            open_, high, low, close = values[:4]
            require(low <= min(open_, close) <= max(open_, close) <= high,
                    "invalid CSV OHLC order")
            if timestamps:
                require(timestamp - timestamps[-1] == interval,
                        "missing, duplicate or unordered CSV timestamp")
            timestamps.append(timestamp)
            candles.append(values)
    require(interval > 0 and len(candles) >= 4, "invalid market timeline")
    return timestamps, candles


def utc_date(text):
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def interval_bits(start, end):
    return ((1 << (end - start)) - 1) << start if end > start else 0


def qualify_occurrences(times, length, warmup, qualifier):
    """Reference qualifiers from occurrence positions and contiguous validity.

    Recent occurrences paint future intervals; persistence retains sufficiently
    long consecutive runs. This does not use the native word-doubling algorithm.
    """
    bits = 0
    if qualifier == "plain":
        start = warmup
        for t in times:
            bits |= 1 << t
    elif qualifier == "onset":
        start = warmup + 1
        previous = -2
        for t in times:
            if previous != t - 1:
                bits |= 1 << t
            previous = t
    else:
        name, count = qualifier.split(":")
        count = int(count)
        require(name in ("persist", "recent") and 1 <= count <= 100000,
                "unsupported qualifier")
        start = warmup + count - 1
        if name == "recent":
            begin = end = 0
            for t in times:
                if t > end:
                    bits |= interval_bits(begin, end)
                    begin = t
                end = min(length, t + count)
            bits |= interval_bits(begin, end)
        else:
            begin, previous = 0, -2
            for t in times:
                if previous != t - 1:
                    begin = t
                if t - begin + 1 >= count:
                    bits |= 1 << t
                previous = t
    valid = interval_bits(min(start, length), length)
    return bits & valid, valid


@dataclass(frozen=True)
class State:
    count: int
    first: tuple
    truth: int
    valid: int
    truth_words: tuple
    valid_words: tuple


def load_bank(path):
    raw, digest = sealed_body(path)
    require(raw[:8] == b"FDBANK01" and len(raw) >= 88, "bank format")
    context = raw[8:72].decode("ascii")
    rows, count = struct.unpack_from("<2Q", raw, 72)
    require(rows > 0 and count > 0, "empty bank")
    words = (rows + 63) // 64
    width = 40 + 16 * words
    require(len(raw) == 88 + count * width, "bank size")
    states, row_mask = [], (1 << rows) - 1
    for i in range(count):
        offset = 88 + i * width
        weight = int.from_bytes(raw[offset:offset + 16], "little")
        first = struct.unpack_from("<3Q", raw, offset + 16)
        truth_words = struct.unpack_from("<" + str(words) + "Q", raw, offset + 40)
        valid_words = struct.unpack_from("<" + str(words) + "Q", raw,
                                         offset + 40 + 8 * words)
        truth = int.from_bytes(raw[offset + 40:offset + 40 + 8 * words], "little")
        valid = int.from_bytes(raw[offset + 40 + 8 * words:offset + width], "little")
        require(weight > 0 and truth & ~valid == 0 and (truth | valid) & ~row_mask == 0,
                "invalid bank weight/truth/validity/tail")
        states.append(State(weight, first, truth, valid, truth_words, valid_words))
    require(len({(s.truth, s.valid) for s in states}) == len(states),
            "duplicate predicate dictionary states")
    return states, rows, context, digest


def read_tsv(path, header):
    raw, digest = sealed_body(path)
    text = raw.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    require(bool(rows) and rows[0] == header, "TSV header: " + str(path))
    require(all(len(row) == len(header) for row in rows[1:]), "TSV row arity")
    return rows[1:], digest


def verify_bank(root, index, cfg, candles, start, end, run_context):
    windows = [tuple(map(int, entry.split(","))) for entry in cfg["windows"].split(";")]
    lags = windows[index]
    require(lags and lags[0] == 0 and tuple(sorted(set(lags))) == lags,
            "invalid geometry window lags")
    mode = cfg["mode"]
    full_length, rows = end - 2, end - start - 2
    occurrences = OrderedDict()
    for t in range(max(lags), full_length):
        pattern = canonical_pattern([candles[t - lag] for lag in lags], mode)
        occurrences.setdefault(pattern, []).append(t)
    expected_patterns = list(occurrences)
    total = domain_count(len(lags), mode)
    absent = total - len(occurrences)
    require(absent >= 0, "observed patterns exceed full domain")
    bank_dir = root / "banks"
    states, bank_rows, context, bank_hash = load_bank(bank_dir / f"bank-{index:02}.bin")
    require(bank_rows == rows, "bank scored timeline")
    require(context == hashlib.sha256(f"{run_context}|family|{index}".encode()).hexdigest(),
            "bank context")
    catalogue, catalogue_hash = read_tsv(bank_dir / f"patterns-{index:02}.tsv",
                                        ["id", "kind", "multiplicity", "pattern"])
    require(len(catalogue) == len(occurrences) + int(absent > 0), "catalogue coverage")
    weights = []
    for i, (identity, kind, count, pattern) in enumerate(catalogue):
        require(int(identity) == i, "catalogue identity order")
        parsed_mode, rank_rows, _ = parse_pattern(pattern)
        require(parsed_mode == mode and len(rank_rows) == len(lags), "catalogue pattern domain")
        if i < len(occurrences):
            require(kind == "observed" and int(count) == 1 and pattern == expected_patterns[i],
                    "observed catalogue identity/order/weight")
            weights.append(1)
        else:
            require(kind == "unobserved" and int(count) == absent and pattern not in occurrences,
                    "symbolic unobserved complement/representative")
            weights.append(absent)
    members, member_hash = read_tsv(bank_dir / f"members-{index:02}.tsv",
                                    ["pattern_id", "qualifier", "state_id", "multiplicity"])
    qualifiers = [text.strip() for text in cfg["qualifiers"].split(",")]
    require(len(members) == len(catalogue) * len(qualifiers), "membership cardinality")
    totals, first = [0] * len(states), [None] * len(states)
    row_mask = (1 << rows) - 1
    cursor, one_hot_union, one_hot_count = 0, 0, 0
    for pattern_id, row in enumerate(catalogue):
        times = occurrences.get(row[3], [])
        raw_truth, raw_valid = qualify_occurrences(times, full_length, max(lags), "plain")
        if row[1] == "observed":
            require(one_hot_union & raw_truth == 0, "overlapping full pattern occurrences")
            one_hot_union |= raw_truth
            one_hot_count += len(times)
        for qi, qualifier in enumerate(qualifiers):
            member = tuple(map(int, members[cursor]))
            cursor += 1
            pid, qid, sid, weight = member
            require((pid, qid, weight) == (pattern_id, qi, weights[pattern_id])
                    and 0 <= sid < len(states), "membership identity/order/weight")
            truth, valid = qualify_occurrences(times, full_length, max(lags), qualifier)
            truth, valid = (truth >> start) & row_mask, (valid >> start) & row_mask
            require((states[sid].truth, states[sid].valid) == (truth, valid),
                    f"predicate mismatch bank {index} pattern {pattern_id} qualifier {qualifier}")
            totals[sid] += weight
            coordinate = (pattern_id, qi, 0)
            first[sid] = coordinate if first[sid] is None else min(first[sid], coordinate)
    expected_raw_valid = interval_bits(min(max(lags), full_length), full_length)
    require(one_hot_union == expected_raw_valid
            and one_hot_count == max(0, full_length - max(lags)), "raw window partition")
    require(all((s.count, s.first) == (totals[i], first[i]) for i, s in enumerate(states)),
            "state alias weights/representatives")
    require(sum(totals) == total * len(qualifiers), "full per-bank logical coverage")
    stats_path = bank_dir / f"preparation-{index:02}.json"
    stats = json.loads(stats_path.read_text())
    marker, marker_hash = sealed_body(bank_dir / f"prepared-{index:02}.chk")
    require(len(marker) == 472 and marker[:8] == b"FGPREP01"
            and marker[8:72].decode() == context, "preparation marker format/context")
    hashes = [marker[72 + i * 64:136 + i * 64].decode() for i in range(4)]
    require(hashes == [bank_hash, catalogue_hash, member_hash, sha(stats_path)],
            "preparation marker payload binding")
    integers = struct.unpack_from("<12Q", marker, 328)
    require(integers[:11] == (len(lags), max(lags), full_length, start, rows,
                            max(0, full_length - max(lags)), len(occurrences), len(catalogue),
                            len(qualifiers), len(members), len(states)),
            "preparation marker counters")
    require(integers[11] <= int(cfg["prepare_mib"]) * (1 << 20), "preparation charge/budget")
    marker_counts = tuple(int.from_bytes(marker[424 + i * 16:440 + i * 16], "little")
                          for i in range(3))
    require(marker_counts == (total, absent, total * len(qualifiers)), "preparation marker u128 counts")
    expected_stats = {
        "bank": index, "window_lags": list(lags), "mode": mode,
        "scored_rows": rows, "scored_start_index": start, "decision_rows": full_length,
        "windows_encoded": max(0, full_length - max(lags)),
        "observed_patterns": len(occurrences), "total_patterns": str(total),
        "unobserved_patterns": str(absent), "qualifiers": qualifiers,
        "logical_conditions": str(total * len(qualifiers)), "catalogue_records": len(catalogue),
        "physical_memberships": len(members), "states": len(states),
        "prepare_payload_charge_bytes": integers[11],
    }
    require(all(stats.get(key) == value for key, value in expected_stats.items()),
            "preparation JSON counters")
    require(stats["catalogue_bytes"] == sealed(bank_dir / f"patterns-{index:02}.tsv")[0]
            and stats["member_bytes"] == sealed(bank_dir / f"members-{index:02}.tsv")[0]
            and stats["bank_payload_bytes"] <= int(cfg["bank_mib"]) * (1 << 20),
            "preparation byte counters/budgets")
    result = {
        "bank": index, "window_lags": list(lags), "mode": mode,
        "scored_rows": rows, "windows_encoded": one_hot_count,
        "observed_patterns": len(occurrences), "total_patterns": str(total),
        "unobserved_patterns": str(absent), "physical_memberships": len(members),
        "distinct_states": len(states), "logical_conditions": str(sum(totals)),
        "bank_body_sha256": bank_hash, "catalogue_body_sha256": catalogue_hash,
        "members_body_sha256": member_hash,
        "preparation_marker_body_sha256": marker_hash,
        "all_catalogue_membership_masks_validity_weights_and_representatives_checked": True,
    }
    print(f"geometry bank {index}: {len(occurrences)} observed patterns, "
          f"{len(states)} states, {sum(totals)} logical conditions verified", flush=True)
    return states, result, catalogue


def frontier_ranges(count, block):
    result = []
    def split(lo, hi):
        if hi - lo <= block:
            result.append((lo, hi))
        else:
            mid = lo + (hi - lo) // 2
            split(lo, mid)
            split(mid, hi)
    split(0, count)
    return result


def parse_rule(text):
    tokens = re.findall(r"\(|\)|[^\s()]+", text)
    cursor = 0
    def read():
        nonlocal cursor
        require(cursor < len(tokens), "truncated Boolean rule")
        token = tokens[cursor]
        cursor += 1
        if token in ("s0", "s1"):
            return token
        require(token == "(" and cursor < len(tokens), "Boolean syntax")
        op = tokens[cursor]
        cursor += 1
        require(op in ("and", "or", "not"), "nonpointwise/unsupported Boolean opcode")
        first = read()
        node = (op, first) if op == "not" else (op, first, read())
        require(cursor < len(tokens) and tokens[cursor] == ")", "unclosed Boolean rule")
        cursor += 1
        return node
    expression = read()
    require(cursor == len(tokens), "trailing Boolean rule tokens")
    return expression


def truth_table(text):
    expression = parse_rule(text)
    def evaluate(node, a, b):
        if isinstance(node, str):
            return a if node == "s0" else b
        if node[0] == "not":
            return not evaluate(node[1], a, b)
        left, right = evaluate(node[1], a, b), evaluate(node[2], a, b)
        return left and right if node[0] == "and" else left or right
    return tuple(evaluate(expression, bool(i & 2), bool(i & 1)) for i in range(4))


def pair_mask(table, a, b, row_mask):
    truth = 0
    for ai, bi in product(range(2), repeat=2):
        if table[2 * ai + bi]:
            truth |= (a.truth if ai else ~a.truth) & (b.truth if bi else ~b.truth)
    return truth & a.valid & b.valid & row_mask


def state_summary(states, lo, hi, row_mask):
    """Possible valid-true, valid-false and invalid statuses, independently."""
    yes = no = invalid = 0
    for state in states[lo:hi]:
        yes |= state.truth
        no |= state.valid & ~state.truth
        invalid |= row_mask & ~state.valid
    return yes, no, invalid


def constant_product_mask(table, left, right, row_mask):
    yes = 0
    no = left[2] | right[2]
    for ai, bi in product(range(2), repeat=2):
        possible = left[0 if ai else 1] & right[0 if bi else 1]
        if table[2 * ai + bi]:
            yes |= possible
        else:
            no |= possible
    require((yes | no) == row_mask and yes & no == 0, "nonconstant captured product positions")
    return yes


def task_record(path, context):
    raw, digest = sealed_body(path)
    require(len(raw) == 376 and raw[:8] == b"FDTASK01"
            and raw[8:72].decode() == context, "task checkpoint format/context")
    keys = ("id", "node_pairs", "proved", "leaves", "bound_words", "regions")
    record = dict(zip(keys, struct.unpack_from("<6Q", raw, 72)))
    record["signature_pairs"] = int.from_bytes(raw[120:136], "little")
    record["logical"] = int.from_bytes(raw[136:152], "little")
    record["digest"] = raw[152:216].decode()
    record["families"] = struct.unpack_from("<2Q", raw, 216)
    record["template"] = struct.unpack_from("<Q", raw, 232)[0]
    coordinates = struct.unpack_from("<6Q", raw, 240)
    record["coordinates"] = (coordinates[:3], coordinates[3:])
    record["score"] = struct.unpack_from("<d", raw, 288)[0]
    record["metrics"] = struct.unpack_from("<10d", raw, 296)
    require(record["regions"] == record["proved"] + record["leaves"]
            and math.isfinite(record["score"]), "task counters/score")
    return record, raw


def python_ledger(mask, prices, fee_bps, slip_bps, interval):
    fee, slip = fee_bps / 10000.0, slip_bps / 10000.0
    count = len(prices) - 1
    cash, shares, previous, peak, gross, entry_equity = 1., 0., 1., 1., 1., 1.
    returns, trades, active_count, drawdown = [], [], 0, 0.
    prior = False
    for t in range(count):
        active = bool((mask >> t) & 1)
        following = t + 1 < count and bool((mask >> (t + 1)) & 1)
        if active and not prior:
            entry_equity = cash
            shares = cash / (prices[t] * (1. + slip) * (1. + fee))
            cash = 0.
        equity = cash + shares * prices[t + 1]
        if active and not following:
            cash = shares * prices[t + 1] * (1. - slip) * (1. - fee)
            shares, equity = 0., cash
            trades.append(equity / entry_equity - 1.)
        returns.append(equity / previous - 1.)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1. - equity / peak)
        if active:
            gross *= prices[t + 1] / prices[t]
            active_count += 1
        previous, prior = equity, active
    mean = sum(returns) / count
    variance = max(0., (sum(r * r for r in returns) - count * mean * mean) / (count - 1))
    sharpe = mean / math.sqrt(variance) * math.sqrt(31557600. / interval) if variance > 1e-24 else math.nan
    try:
        cagr = math.expm1(math.log(previous) * 31557600. / (count * interval)) * 100.
    except OverflowError:
        cagr = math.inf
    return ((previous - 1.) * 100., (gross - 1.) * 100., cagr, drawdown * 100.,
            sharpe, float(len(trades)), 100. * active_count / count, mean * 10000.,
            10000. * sum(trades) / len(trades) if trades else math.nan, float(count))


class Ledger:
    def __init__(self, directory, prices, fee, slip, interval, backend="auto", cache_limit=4096):
        self.prices, self.fee, self.slip, self.interval = prices, fee, slip, interval
        self.rows, self.cache_limit, self.cache = len(prices) - 1, cache_limit, OrderedDict()
        self.calls, self.reference_checks = 0, 0
        self.backend = "c" if backend == "auto" and shutil.which("cc") else backend
        if self.backend == "auto":
            self.backend = "python"
        self.source_sha256 = None
        if self.backend == "c":
            directory.mkdir(parents=True, exist_ok=True)
            source = Path(__file__).with_name("joint_ledger.c")
            target = directory / ("geometry-ledger.dylib" if sys.platform == "darwin" else "geometry-ledger.so")
            subprocess.run(["cc", "-O3", "-std=c11", "-ffp-contract=off", "-shared", "-fPIC",
                            str(source), "-lm", "-o", str(target)], check=True)
            self.source_sha256 = sha(source)
            self.lib = ctypes.CDLL(str(target.resolve()))
            self.function = self.lib.joint_ledger
            self.function.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_double), ctypes.c_size_t,
                                      ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                      ctypes.POINTER(ctypes.c_double)]
            self.function.restype = ctypes.c_int
            self.price_buffer = (ctypes.c_double * len(prices))(*prices)
        require(self.backend in ("python", "c"), "ledger backend")

    def score(self, mask):
        if mask in self.cache:
            self.cache.move_to_end(mask)
            return self.cache[mask]
        if self.backend == "python":
            result = python_ledger(mask, self.prices, self.fee, self.slip, self.interval)
        else:
            words = (self.rows + 63) // 64
            packed = (ctypes.c_uint64 * words)(*((mask >> (64 * i)) & U64 for i in range(words)))
            output = (ctypes.c_double * 10)()
            require(self.function(packed, self.rows, self.price_buffer, 1, self.fee / 10000.,
                                  self.slip / 10000., float(self.interval), output) == 0,
                    "independent C cash/share ledger failed")
            result = tuple(output)
            if self.reference_checks < 16:
                compare_metrics(result, python_ledger(mask, self.prices, self.fee,
                                                     self.slip, self.interval), "C/Python cash ledger")
                self.reference_checks += 1
        self.calls += 1
        self.cache[mask] = result
        if len(self.cache) > self.cache_limit:
            self.cache.popitem(last=False)
        return result


def compare_metrics(actual, expected, label, atol=1e-7):
    maximum = 0.
    for i, (a, b) in enumerate(zip(actual, expected)):
        if a is None:
            a = math.nan
        if b is None:
            b = math.nan
        if math.isnan(a) or math.isnan(b):
            require(math.isnan(a) and math.isnan(b), f"metric validity {label} field {i}")
        elif not math.isfinite(a) or not math.isfinite(b):
            require(a == b, f"metric infinity {label} field {i}")
        else:
            difference = abs(a - b)
            require(difference <= atol + 1e-9 * abs(b),
                    f"metric mismatch {label} field {i}: {a!r} vs {b!r}")
            maximum = max(maximum, difference)
    require(actual[5] == expected[5] and actual[9] == expected[9], "exact trade/period counts")
    return maximum


def verify_tasks(root, cfg, summary, raw_banks, candles, start, end, ledger_backend,
                 max_state_pairs, metric_cache):
    banks = [sorted(enumerate(bank), key=lambda x: (x[1].truth_words, x[1].valid_words, x[0]))
             for bank in raw_banks]
    banks = [[state for _, state in bank] for bank in banks]
    rows, row_mask = end - start - 2, (1 << (end - start - 2)) - 1
    rules = cfg["rules"].split(";")
    tables = [truth_table(rule) for rule in rules]
    expected_total = sum(sum(s.count for s in a) * sum(s.count for s in b)
                         for ai, a in enumerate(banks) for bi, b in enumerate(banks)
                         if ai != bi or cfg.get("allow_same_bank", "false") == "true") * len(rules)
    require(int(summary["requested_strategy_addresses"]) == expected_total, "requested strategy domain")
    capture = bool(summary["capture"])
    ledger = Ledger(root / "verification" / "ledger-build", [c[0] for c in candles[start + 1:end]],
                    float(cfg["fee_bps"]), float(cfg["slip_bps"]), int(cfg["interval_seconds"]),
                    ledger_backend, metric_cache)
    task_id = task_count = regions = signatures = logical = visits = proved = leaves = 0
    winner_checks = captured_checks = 0
    error = 0.
    result_hash = hashlib.sha256()
    best_task = None
    finished = int(summary["completed_tasks"])
    summaries = [{} for _ in banks]
    by_first = [{state.first: state for state in bank} for bank in banks]
    def aggregate(bank_id, lo, hi):
        cache = summaries[bank_id]
        key = (lo, hi)
        if key not in cache:
            cache[key] = state_summary(banks[bank_id], lo, hi, row_mask)
        return cache[key]
    for ai, left in enumerate(banks):
        left_prefix = [0]
        for state in left:
            left_prefix.append(left_prefix[-1] + state.count)
        for bi, right in enumerate(banks):
            if ai == bi and cfg.get("allow_same_bank", "false") != "true":
                continue
            right_prefix = [0]
            for state in right:
                right_prefix.append(right_prefix[-1] + state.count)
            for ti, table in enumerate(tables):
                for al, ah in frontier_ranges(len(left), int(cfg["task_states"])):
                    if task_id >= finished:
                        task_id += 1
                        continue
                    path = root / "tasks" / f"task-{task_id:08}.chk"
                    checkpoint, raw = task_record(path, summary["context_sha256"])
                    task_weight = (left_prefix[ah] - left_prefix[al]) * right_prefix[-1]
                    task_pairs = (ah - al) * len(right)
                    require((checkpoint["id"], checkpoint["families"], checkpoint["template"])
                            == (task_id, (ai, bi), ti), "task domain/order")
                    require(checkpoint["logical"] == task_weight
                            and checkpoint["signature_pairs"] == task_pairs, "task full weighted coverage")
                    ca, cb = checkpoint["coordinates"]
                    require(ca in by_first[ai] and cb in by_first[bi], "task winner coordinates")
                    require(any(state.first == ca for state in left[al:ah]), "winner outside task")
                    winner_mask = pair_mask(table, by_first[ai][ca], by_first[bi][cb], row_mask)
                    error = max(error, compare_metrics(checkpoint["metrics"], ledger.score(winner_mask),
                                                       f"task {task_id} winner"))
                    require(abs(math.expm1(checkpoint["score"]) * 100. - checkpoint["metrics"][0])
                            <= 1e-7 + 1e-9 * abs(checkpoint["metrics"][0]), "task winner log-return score")
                    winner_checks += 1
                    score = checkpoint["score"] * 1e9
                    rounded = math.floor(score + 0.5) if score >= 0 else math.ceil(score - 0.5)
                    selection_key = (-rounded, ti, (ai, bi), checkpoint["coordinates"])
                    if best_task is None or selection_key < best_task[0]:
                        best_task = (selection_key, checkpoint)
                    if capture:
                        require(task_pairs <= max_state_pairs, "capture verifier task state-pair budget exceeded")
                        box_path = root / "tasks" / f"task-{task_id:08}.boxes"
                        size, digest = sealed(box_path)
                        require(size == checkpoint["regions"] * 128 and digest == checkpoint["digest"],
                                "captured task size/digest")
                        width, height = len(right) + 1, ah - al + 1
                        difference = array("q", [0]) * (width * height)
                        task_regions = task_logical = task_signatures = task_leaves = 0
                        best_return = -math.inf
                        with box_path.open("rb") as source:
                            for _ in range(checkpoint["regions"]):
                                record = source.read(128)
                                lo, hi, bl, bh = struct.unpack_from("<4Q", record)
                                weight = int.from_bytes(record[32:48], "little")
                                metrics = struct.unpack_from("<10d", record, 48)
                                require(al <= lo < hi <= ah and 0 <= bl < bh <= len(right),
                                        "captured rectangle outside task")
                                leaf = hi - lo == 1 and bh - bl == 1
                                require(bool(summary["proof"]) or leaf,
                                        "leaf-only control emitted a nonleaf product")
                                want_weight = (left_prefix[hi] - left_prefix[lo]) * (right_prefix[bh] - right_prefix[bl])
                                require(weight == want_weight, "captured u128 product weight")
                                mask = constant_product_mask(table, aggregate(ai, lo, hi),
                                                             aggregate(bi, bl, bh), row_mask)
                                error = max(error, compare_metrics(metrics, ledger.score(mask),
                                                                   f"task {task_id} region {task_regions}"))
                                best_return = max(best_return, metrics[0])
                                x0, x1 = lo - al, hi - al
                                difference[x0 * width + bl] += 1
                                difference[x0 * width + bh] -= 1
                                difference[x1 * width + bl] -= 1
                                difference[x1 * width + bh] += 1
                                task_regions += 1
                                task_leaves += int(leaf)
                                task_logical += weight
                                task_signatures += (hi - lo) * (bh - bl)
                        # A two-dimensional prefix sum certifies every physical
                        # state pair is covered exactly once, including overlap.
                        for x in range(ah - al):
                            running = 0
                            for y in range(len(right)):
                                at = x * width + y
                                if x:
                                    difference[at] += difference[(x - 1) * width + y]
                                running += difference[at]
                                require(running == 1, "overlapping or incomplete captured state-pair coverage")
                        require(task_regions == checkpoint["regions"] and task_logical == task_weight
                                and task_signatures == task_pairs, "captured checkpoint coverage totals")
                        require(task_leaves == checkpoint["leaves"]
                                and task_regions - task_leaves == checkpoint["proved"],
                                "captured physical leaf/certificate counters")
                        require(checkpoint["metrics"][0] + 1e-7 + 1e-9 * abs(best_return) >= best_return,
                                "retained winner is worse than a captured region")
                        captured_checks += task_regions
                    result_hash.update(raw)
                    task_count += 1
                    regions += checkpoint["regions"]
                    logical += task_weight
                    signatures += task_pairs
                    visits += checkpoint["node_pairs"]
                    proved += checkpoint["proved"]
                    leaves += checkpoint["leaves"]
                    task_id += 1
    require(task_count == finished, "missing completed checkpoint")
    require(sorted(p.name for p in (root / "tasks").glob("*.chk"))
            == [f"task-{i:08}.chk" for i in range(finished)], "unexpected task checkpoint domain")
    require(logical == int(summary["resolved_strategy_addresses"])
            and signatures == int(summary["signature_pair_products_resolved"])
            and regions == int(summary["metric_regions_evaluated"])
            and visits == int(summary["tree_node_pairs_visited"])
            and proved == int(summary["certified_nonleaf_products"]), "aggregate task coverage/counters")
    require(result_hash.hexdigest() == summary["result_digest"], "aggregate result digest")
    complete = task_count == task_id and logical == expected_total
    require(bool(summary["coverage_complete"]) == complete, "completion claim")
    if best_task is not None:
        verify_best_export(root, cfg, summary, best_task[1])
    else:
        require(summary["best"] is None, "best candidate without a completed task")
    return {
        "coverage_complete": complete, "logical_addresses_verified": str(logical),
        "requested_logical_addresses": str(expected_total), "completed_tasks": task_count,
        "physical_signature_pairs_verified": str(signatures), "metric_regions": regions,
        "tree_node_pairs_reported": str(visits), "certified_nonleaf_products_verified": str(proved),
        "leaf_regions_verified": leaves, "frozen_export_verified": best_task is not None,
        "all_captured_region_masks_metrics_and_coverage_checked": capture,
        "captured_regions_replayed": captured_checks, "task_winners_replayed": winner_checks,
        "summary_metrics_scope": "all captured regions" if capture else "retained task winners only",
        "max_metric_absolute_error": error, "ledger_backend": ledger.backend,
        "ledger_source_sha256": ledger.source_sha256, "independent_ledger_replays": ledger.calls,
        "c_vs_python_ledger_crosschecks": ledger.reference_checks,
        "result_digest": result_hash.hexdigest(),
    }


def verify_best_export(root, cfg, summary, checkpoint):
    """Bind the stable best reduction to its concrete, replayable pattern files."""
    best = summary["best"]
    require(best == json.loads((root / "best.json").read_text()), "best JSON/summary disagreement")
    windows = [tuple(map(int, text.split(","))) for text in cfg["windows"].split(";")]
    qualifiers = [text.strip() for text in cfg["qualifiers"].split(",")]
    rules = [text.strip() for text in cfg["rules"].split(";")]
    expected_families = ["lags:" + ",".join(map(str, windows[i])) for i in checkpoint["families"]]
    require(best["families"] == expected_families and best["template"] == rules[checkpoint["template"]]
            and best["coordinates"] == [list(c) for c in checkpoint["coordinates"]]
            and abs(best["log_return"] - checkpoint["score"]) <= 1e-16,
            "stable task winner reduction")
    compare_metrics(best["metrics"], checkpoint["metrics"], "best exported metrics")
    expected_rows = [["slot", "lags", "qualifier", "pattern"]]
    for slot, (bank, coordinate) in enumerate(zip(checkpoint["families"], checkpoint["coordinates"])):
        catalogue, _ = read_tsv(root / "banks" / f"patterns-{bank:02}.tsv",
                                ["id", "kind", "multiplicity", "pattern"])
        identity, kind, multiplicity, pattern = catalogue[coordinate[0]]
        require(int(identity) == coordinate[0], "selected catalogue identity")
        expected_predicate = {"lags": list(windows[bank]), "qualifier": qualifiers[coordinate[1]],
                              "pattern": pattern, "catalogue_kind": kind,
                              "sample_alias_multiplicity": multiplicity}
        require(best["predicates"][slot] == expected_predicate, "concrete selected predicate")
        expected_rows.append([str(slot), ",".join(map(str, windows[bank])),
                              qualifiers[coordinate[1]], pattern])
    for name in ("best-geometry.tsv", "best-rule.txt"):
        require((root / (name + ".sha256")).read_text().strip() == sha(root / name),
                "frozen export checksum")
    rows = list(csv.reader(io.StringIO((root / "best-geometry.tsv").read_text()), delimiter="\t"))
    require(rows == expected_rows and (root / "best-rule.txt").read_text() == best["template"] + "\n",
            "frozen pattern/rule export semantics")


def self_test():
    for mode, expected in KNOWN_COUNTS.items():
        require(tuple(domain_count(n, mode) for n in range(1, 9)) == expected,
                "independent domain count fixture")
    require(count_by_levels(2, "unoriented") == [0, 1, 23, 153, 471, 780, 720, 350, 70],
            "two-candle occupied-level distribution")
    shapes, cases = Counter(), set()
    for levels in range(1, 9):
        chains = list(combinations_with_replacement(range(levels), 4))
        for a in chains:
            for b in chains:
                if set(a) | set(b) != set(range(levels)):
                    continue
                code = pattern_text((a, b))
                require(parse_pattern(code)[1] == (a, b), "rank grammar round trip")
                cases.add(code)
                shapes[tuple(int(x < y) for x, y in zip(a, a[1:])),
                       tuple(int(x < y) for x, y in zip(b, b[1:]))] += 1
    require(len(cases) == 2568 and shapes[(1, 1, 1), (1, 1, 1)] == 321,
            "independent exhaustive normalized-rank enumeration")
    require(sum(count for (a, b), count in shapes.items() if a[1] and b[1]) == 1284,
            "positive-body two-candle subdomain")
    require(sum(count * (1 + a[1]) * (1 + b[1]) for (a, b), count in shapes.items()) == 7452,
            "oriented two-candle domain")
    qualifier_checks = 0
    for length in (1, 7, 11):
        for warmup in range(min(length, 4)):
            for raw in range(1 << min(length - warmup, 7)):
                times = [t for t in range(warmup, length) if (raw >> (t - warmup)) & 1]
                values = [t in times for t in range(length)]
                valid = [t >= warmup for t in range(length)]
                for qualifier in ("plain", "onset", "persist:1", "persist:3", "recent:3", "recent:16"):
                    want_truth = want_valid = 0
                    for t in range(length):
                        if qualifier == "plain":
                            truth, good = values[t], valid[t]
                        elif qualifier == "onset":
                            truth = t > 0 and values[t] and not values[t - 1]
                            good = t > 0 and valid[t] and valid[t - 1]
                        else:
                            name, n = qualifier.split(":")
                            n = int(n)
                            good = t + 1 >= n and all(valid[t + 1 - n:t + 1])
                            truth = (all if name == "persist" else any)(values[max(0, t + 1 - n):t + 1])
                        if good:
                            want_valid |= 1 << t
                            if truth:
                                want_truth |= 1 << t
                    require(qualify_occurrences(times, length, warmup, qualifier)
                            == (want_truth, want_valid), "occurrence/scalar qualifier parity")
                    qualifier_checks += 1
    return {"status": "PASS", "unoriented_pair_rank_orders": len(cases),
            "strict_pair_rank_orders": 321, "oriented_pair_rank_orders": 7452,
            "qualifier_scalar_crosschecks": qualifier_checks,
            "counts_1_through_8": {mode: list(map(str, values)) for mode, values in KNOWN_COUNTS.items()}}


def verify(root, ledger_backend="auto", max_state_pairs=4000000, metric_cache=4096,
           data_override=None, output=None):
    root = Path(root)
    clock = time.perf_counter()
    cfg = settings(root / "experiment.cfg")
    summary = json.loads((root / "summary.json").read_text())
    require(cfg.get("mode") in WEIGHTS and "windows" in cfg, "geometry run required")
    data_path = data_override or cfg["data"]
    require(sha(data_path) == summary["data_sha256"], "source data changed")
    raw_config = (root / "experiment.cfg").read_text()
    context_text = (f"filang-geometry-v1|{raw_config}|{summary['data_sha256']}|"
                    f"{summary['engine_sha256']}|{summary['backend']}|"
                    f"{str(summary['proof']).lower()}|{str(summary['capture']).lower()}")
    require(hashlib.sha256(context_text.encode()).hexdigest() == summary["context_sha256"],
            "configuration/data/engine/backend/output context")
    context_body, _ = sealed_body(root / "context.chk")
    require(context_body.decode() == summary["context_sha256"], "committed run context")
    timestamps, candles = read_data(data_path, int(cfg["interval_seconds"]))
    start, end = bisect_left(timestamps, utc_date(cfg["start"])), bisect_left(timestamps, utc_date(cfg["end"]))
    require(end - start >= 4, "scored interval too short")
    require(timestamps[0] <= utc_date(cfg["start"])
            and timestamps[start] == utc_date(cfg["start"])
            and end == len(candles)
            and timestamps[-1] + int(cfg["interval_seconds"]) == utc_date(cfg["end"]),
            "exact scored boundaries and causal input end")
    banks, reports, catalogues = [], [], []
    for index in range(len(cfg["windows"].split(";"))):
        bank, report, catalogue = verify_bank(root, index, cfg, candles, start, end,
                                             summary["context_sha256"])
        banks.append(bank)
        reports.append(report)
        catalogues.append(catalogue)
    expected_windows = [{"bank": report["bank"], "lags": report["window_lags"],
                         "total_patterns": report["total_patterns"],
                         "observed_patterns": report["observed_patterns"],
                         "unobserved_patterns": report["unobserved_patterns"],
                         "physical_pattern_representatives": len(catalogue),
                         "states": report["distinct_states"],
                         "logical_conditions": report["logical_conditions"]}
                        for report, catalogue in zip(reports, catalogues)]
    require(summary["source"] == "geometry" and summary["mode"] == cfg["mode"]
            and summary["window_banks"] == expected_windows
            and int(summary["total_raw_pattern_universe"]) == sum(int(r["total_patterns"]) for r in reports)
            and int(summary["observed_encoded_rows"]) == sum(r["windows_encoded"] for r in reports)
            and int(summary["observed_pattern_instances"]) == sum(r["observed_patterns"] for r in reports)
            and int(summary["physical_pattern_representatives"]) == sum(map(len, catalogues)),
            "geometry source physical/logical summary counters")
    task_report = verify_tasks(root, cfg, summary, banks, candles, start, end,
                               ledger_backend, max_state_pairs, metric_cache)
    result = {"status": "PASS", "data_sha256": sha(data_path),
              "context_sha256": summary["context_sha256"], "banks": reports,
              "count_method": "occupied-level inclusion/exclusion with Python integers",
              "predicate_method": "independent endpoint ranks and occurrence-based qualifiers",
              "certificate_method": "three input statuses and exact output possibilities",
              "mask_disagreements": 0, **task_report, "seconds": time.perf_counter() - clock}
    destination = root / "verification"
    destination.mkdir(exist_ok=True)
    (destination / "geometry.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if output:
        Path(output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "banks"}, indent=2))
    return result


def verify_evaluation(root, data_path, ledger_backend="auto", output=None):
    """Replay a frozen concrete pattern selection on its declared new timeline."""
    root = Path(root)
    clock = time.perf_counter()
    report = json.loads((root / "evaluation.json").read_text())
    require(report.get("role") == "frozen_geometry_replay", "frozen geometry evaluation required")
    require(sha(data_path) == report["data_sha256"], "evaluation source data changed")
    require(sha(root / "selection.tsv") == report["selection_sha256"]
            and sha(root / "rule.txt") == report["rule_sha256"], "frozen selection/rule binding")
    timestamps, candles = read_data(data_path, int(report["interval_seconds"]))
    start = bisect_left(timestamps, utc_date(report["start"]))
    end = len(candles)
    require(end - start >= 4 and timestamps[0] <= utc_date(report["start"])
            and timestamps[-1] + int(report["interval_seconds"]) == utc_date(report["end"]),
            "evaluation causal history/end")
    selected = list(csv.reader(io.StringIO((root / "selection.tsv").read_text()), delimiter="\t"))
    require(len(selected) == 3 and selected[0] == ["slot", "lags", "qualifier", "pattern"],
            "frozen selection schema")
    masks = []
    full_length, length = end - 2, end - start - 2
    row_mask = (1 << length) - 1
    for slot, row in enumerate(selected[1:]):
        require(len(row) == 4 and int(row[0]) == slot, "frozen selection slot")
        lags = tuple(map(int, row[1].split(",")))
        require(lags and lags[0] == 0 and lags == tuple(sorted(set(lags))), "frozen selection lags")
        mode, ranks, _ = parse_pattern(row[3])
        require(len(ranks) == len(lags), "frozen pattern/window arity")
        times = [t for t in range(max(lags), full_length)
                 if canonical_pattern([candles[t - lag] for lag in lags], mode) == row[3]]
        truth, valid = qualify_occurrences(times, full_length, max(lags), row[2])
        truth, valid = (truth >> start) & row_mask, (valid >> start) & row_mask
        masks.append(State(1, (slot, 0, 0), truth, valid, (), ()))
    table = truth_table((root / "rule.txt").read_text().strip())
    positions = pair_mask(table, masks[0], masks[1], row_mask)
    valid = masks[0].valid & masks[1].valid
    with (root / "decisions.csv").open(newline="") as source:
        reader = csv.reader(source)
        require(next(reader, None) == ["timestamp", "valid", "active"], "evaluation decision schema")
        for t in range(length):
            row = next(reader, None)
            require(row is not None and tuple(map(int, row)) ==
                    (timestamps[start + t], (valid >> t) & 1, (positions >> t) & 1),
                    "frozen evaluation decision truth/validity")
        require(next(reader, None) is None, "trailing evaluation decisions")
    ledger = Ledger(root / "verification" / "ledger-build", [c[0] for c in candles[start + 1:end]],
                    float(report["fee_bps"]), float(report["slip_bps"]),
                    int(report["interval_seconds"]), ledger_backend)
    metrics = ledger.score(positions)
    error = compare_metrics(report["metrics"], metrics, "frozen evaluation full metrics")
    require(report["valid_decisions"] == valid.bit_count()
            and report["active_decisions"] == positions.bit_count(), "evaluation decision counts")
    require(abs(math.expm1(report["log_return"]) * 100. - metrics[0])
            <= 1e-7 + 1e-9 * abs(metrics[0]), "evaluation log return")
    result = {"status": "PASS", "role": "independent_frozen_geometry_verification",
              "all_frozen_decision_masks_validity_and_ten_metrics_checked": True,
              "decision_rows_checked": length, "mask_disagreements": 0,
              "max_metric_absolute_error": error, "ledger_backend": ledger.backend,
              "data_sha256": report["data_sha256"], "selection_sha256": report["selection_sha256"],
              "rule_sha256": report["rule_sha256"], "seconds": time.perf_counter() - clock}
    destination = root / "verification"
    destination.mkdir(exist_ok=True)
    (destination / "geometry.json").write_text(json.dumps(result, indent=2) + "\n")
    if output:
        Path(output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run")
    parser.add_argument("--evaluation", help="verify a geometry-evaluate output directory")
    parser.add_argument("--data", help="source CSV override, required with --evaluation")
    parser.add_argument("--out", help="also write verification JSON to this exact path")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--counts", type=int, help="print exact full-domain counts through N candles")
    parser.add_argument("--ledger", choices=("auto", "python", "c"), default="auto")
    parser.add_argument("--max-task-state-pairs", type=int, default=4000000)
    parser.add_argument("--metric-cache", type=int, default=4096)
    args = parser.parse_args()
    require(bool(args.run or args.evaluation or args.self_test or args.counts is not None),
            "choose --run, --evaluation, --self-test or --counts")
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    if args.counts is not None:
        require(0 <= args.counts <= 32, "reference count display supports 0..32")
        print(json.dumps({mode: [str(domain_count(n, mode)) for n in range(args.counts + 1)]
                          for mode in WEIGHTS}, indent=2))
    if args.run:
        verify(args.run, args.ledger, args.max_task_state_pairs, args.metric_cache, args.data, args.out)
    if args.evaluation:
        require(bool(args.data), "--evaluation requires --data")
        verify_evaluation(args.evaluation, args.data, args.ledger, args.out)


if __name__ == "__main__":
    main()
