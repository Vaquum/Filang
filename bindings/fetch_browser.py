#!/usr/bin/env python3
"""Download a pinned browser release and verify its published SHA-256 checksum."""

import argparse
import hashlib
import io
from pathlib import Path
import re
import tarfile
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="exact published version, without the v prefix")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.post[1-9][0-9]*)?", args.version):
        parser.error("expected a Filang release version")
    name = f"filang-browser-{args.version}.tar.gz"
    base = f"https://github.com/Vaquum/Filang/releases/download/v{args.version}"
    with urlopen(f"{base}/SHA256SUMS", timeout=60) as response:
        sums = dict(line.split()[::-1] for line in response.read().decode().splitlines())
    expected = sums.get(name)
    if expected is None or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise SystemExit(f"missing or invalid checksum for {name}")
    with urlopen(f"{base}/{name}", timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"checksum mismatch for {name}")
    files = ("index.mjs", "worker-client.mjs", "worker.mjs", "filang_engine.wasm")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        contents = {}
        for file in files:
            member = archive.getmember(f"browser/{file}")
            if not member.isfile():
                raise SystemExit(f"invalid browser asset: {file}")
            contents[file] = archive.extractfile(member).read()
    args.out.mkdir(parents=True, exist_ok=True)
    for file, content in contents.items():
        (args.out / file).write_bytes(content)
    print(f"Verified Filang {args.version}: {expected}")


if __name__ == "__main__":
    main()
