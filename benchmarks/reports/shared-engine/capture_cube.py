"""Read a frozen, fully archived Cube bridge window and emit its compressed blocks."""

from datetime import datetime
import json
import urllib.parse
import urllib.request


def get(path, **parameters):
    origin = "http://127.0.0.1:8487"
    url = origin + "/cube/" + path + "?" + urllib.parse.urlencode(parameters)
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def main():
    latest = get("pack", proto="2", since="")
    pack = latest["pack"] if latest["status"] == "pack" else latest
    step = 16
    if pack["base_seconds"] * step != 900:
        raise ValueError("Cube's level 4 is not fifteen minutes")
    base = pack["base_seconds"]
    origin = pack["t0"]
    canonical = datetime.fromisoformat(pack["canonical_through"].replace("Z", "+00:00"))
    canonical_edge = int((canonical.timestamp() - origin) // base)
    last = min(pack["cutoffBase"], canonical_edge) // step * step
    first = last - 66000 * step
    if first < 0:
        raise ValueError("Cube does not cover the recorded workload")
    token = pack["state_token"]
    blocks = []
    for start in range(first, last, 4096 * step):
        end = min(start + 4096 * step, last)
        block = get("bars", proto="2", n=4, b0=start, b1=end, pack=token)
        if block["n"] != 4 or block["b0"] != start or block["end"] != end or block["state_token"] != token:
            raise ValueError(f"Cube pack changed or block is incomplete at {start}")
        blocks.append(block["bars"]["gzip_base64"])
    print(json.dumps({
        "origin_seconds": origin, "base_seconds": base, "width": step,
        "first": first, "last": last, "canonical_through": pack["canonical_through"],
        "blocks": blocks,
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
