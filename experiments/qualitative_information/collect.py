#!/usr/bin/env python3
"""Collect only independently audited compact R0a evidence without rewriting it."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil


EXPECTED_PROTOCOL = "3f84a6331f1f6c07f3924dfefa9ede739efaa597c98448e382accc45cb2e56ea"


def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--run-dir",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    a.add_argument("--protocol",type=Path,default=Path(__file__).with_name("protocol_r0a.json"))
    args=a.parse_args()
    if args.out.exists():
        raise ValueError("immutable report directory already exists")
    if sha(args.protocol)!=EXPECTED_PROTOCOL:
        raise ValueError("wrong frozen amendment")
    result=json.loads((args.run_dir/"result.json").read_text())
    verification=json.loads((args.run_dir/"verification.json").read_text())
    producer=json.loads((args.run_dir/"producer.json").read_text())
    if verification["status"]!="PASS" or result["outcome"]!=verification["outcome"]:
        raise ValueError("refusing to collect an incomplete or failed audit")
    if producer["frozen_protocol_sha256"]!=EXPECTED_PROTOCOL:
        raise ValueError("source report uses wrong protocol")
    if sha(args.run_dir/"producer.json") != verification["producer_sha256"]:
        raise ValueError("audit not bound to this producer")
    if sha(args.run_dir/"verification.json") != result["audit_sha256"]:
        raise ValueError("result not bound to audit")
    if sha(args.run_dir/"producer.json") != result["producer_sha256"]:
        raise ValueError("result not bound to producer")
    # Complete giant row artifacts are left in the local ignored run. Verify
    # their byte hashes before collecting compact, checked evidence.
    for minutes, info in producer["timeframes"].items():
        native = args.run_dir/"native"/f"{minutes}m.tsv"
        predictions = args.run_dir/"predictions"/f"{minutes}m.tsv"
        if sha(native)!=info["features_sha256"] or sha(predictions)!=info["predictions_sha256"]:
            raise ValueError(f"row-level artifacts corrupted for {minutes}m")
    args.out.mkdir(parents=True)
    for name in ("producer.json","verification.json","result.json"):
        shutil.copyfile(args.run_dir/name,args.out/name)
    entries = {}
    for name in ("producer.json","verification.json","result.json"):
        path=args.out/name
        entries[name]={"sha256":sha(path),"bytes":path.stat().st_size}
    for minutes, info in producer["timeframes"].items():
        entries[f"external-full-input-native/{minutes}m.tsv"]={
            "sha256":info["features_sha256"],
            "bytes":(args.run_dir/"native"/f"{minutes}m.tsv").stat().st_size,
            "retention":"local ignored run directory"
        }
        entries[f"external-full-input-predictions/{minutes}m.tsv"]={
            "sha256":info["predictions_sha256"],
            "bytes":(args.run_dir/"predictions"/f"{minutes}m.tsv").stat().st_size,
            "retention":"local ignored run directory"
        }
    manifest={
        "schema":"qinf-r0a-compact-manifest-v1",
        "frozen_commit":"c2eecc24103b049866de2881ca8141ac194a0927",
        "frozen_sha256":EXPECTED_PROTOCOL,
        "outcome":result["outcome"],
        "audit":"PASS",
        "files":dict(sorted(entries.items()))
    }
    (args.out/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"result":manifest["outcome"],"audit":"PASS","report":str(args.out)},indent=2))


if __name__=="__main__":
    main()
