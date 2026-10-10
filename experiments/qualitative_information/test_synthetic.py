#!/usr/bin/env python3
"""Synthetic contract tests; no inspected Bitcoin outcome data required."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import random
import subprocess
import tempfile
import sys

HERE = Path(__file__).resolve().parent


def generate(path, rows, seed):
    rng = random.Random(seed)
    price = 2000.0
    tick = 1800
    output = []
    for i in range(rows):
        if i > 0 and i % 47 == 0:
            tick += 1800
        open_ = price
        close = open_ + rng.choice([-3, -2, -1, 0, 1, 2, 3])
        high = max(open_,close) + rng.choice([0,1,2])
        low = min(open_,close) - rng.choice([0,1,2])
        row = [1577836800+tick-1800, open_, high, low, close, rng.randint(0,25)]
        output.append(row)
        tick+=1800
        price=close
    with path.open("w", newline="") as f:
        w=csv.writer(f)
        w.writerow(["timestamp","open","high","low","close","volume"])
        w.writerows(output)
    return output


def invoke(binary, source, output):
    return subprocess.run(
        [str(binary),"--data",str(source),"--out",str(output),"--minutes","30"],
        capture_output=True,text=True
    )


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--binary",type=Path,required=True)
    args=parser.parse_args()
    binary=args.binary.resolve()
    with tempfile.TemporaryDirectory() as directory:
        folder=Path(directory)
        input_=folder/"synthetic.csv"
        prefix=folder/"prefix.csv"
        native=folder/"features.tsv"
        prefix_native=folder/"prefix-features.tsv"
        invalid=folder/"invalid.csv"
        invalid_native=folder/"invalid-features.tsv"
        rows=generate(input_,250,20261010)
        with prefix.open("w",newline="") as f:
            writer=csv.writer(f)
            writer.writerow(["timestamp","open","high","low","close","volume"])
            writer.writerows(rows[:180])
        first=invoke(binary,prefix,prefix_native)
        second=invoke(binary,input_,native)
        assert first.returncode==0,first.stderr
        assert second.returncode==0,second.stderr
        prefix_rows=prefix_native.read_text().splitlines()
        full_rows=native.read_text().splitlines()
        assert prefix_rows==full_rows[:len(prefix_rows)], "future append changed past features"
        assert len(full_rows)==251
        assert full_rows[-1].split("\t")[2]=="1", "last row wrongly purged for missing target"
        assert full_rows[1].split("\t")[2]=="0"
        assert full_rows[47+1].split("\t")[2]=="0", "time gap should invalidate immediate successor"
        from verify import independent_geometry
        for i, row in enumerate(rows):
            fields=full_rows[i+1].split("\t")
            is_valid = i>0 and row[0]-rows[i-1][0]==1800
            assert int(fields[2])==int(is_valid)
            if is_valid:
                # verify() expects timestamp OHLC, no volume.
                expected=independent_geometry(tuple(row[:5]),tuple(rows[i-1][:5]))
                assert expected==tuple(map(int,fields[3:])),(i,expected,fields)
            else:
                assert fields[3:]==["-"]*4
        assert invoke(binary,input_,native).returncode!=0, "overwrite must fail"
        broken=[r[:] for r in rows]
        broken[12][2]=broken[12][1]-1.
        with invalid.open("w",newline="") as f:
            w=csv.writer(f)
            w.writerow(["timestamp","open","high","low","close","volume"])
            w.writerows(broken)
        failure=invoke(binary,invalid,invalid_native)
        assert failure.returncode!=0
        assert not invalid_native.exists() and not invalid_native.with_suffix(".pending").exists()

        # Independent sequence of innovations is a synthetic independence
        # control for pipeline behavior, *not* a market generative null.
        assert rows[-1][0]>rows[0][0]
        print("SYNTHETIC_QINF_CONTRACT_PASS: 250 OHLCV bars, gaps, exact native/oracle parity, source prefix invariance, final feature causal availability, fail-closed invalid input")


if __name__=="__main__":
    main()
