#!/usr/bin/env python3
"""Build the local WASM package and Python wheel with Cargo and the standard library."""

import argparse
import base64
import csv
import hashlib
import io
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
BINDINGS = ROOT / "bindings"
MANIFEST = BINDINGS / "native" / "Cargo.toml"
MODULE = "filang_engine"


def version():
    return re.search(r'^version = "([^"]+)"$', (ROOT / "Cargo.toml").read_text(), re.M)[1]


def cargo_build(target_dir, *, toolchain=None, target=None):
    cmd = ["cargo"]
    if toolchain:
        cmd.append("+" + toolchain)
    cmd += [
        "build", "--release", "--locked", "--offline", "--manifest-path", str(MANIFEST),
        "--target-dir", str(target_dir),
    ]
    if target:
        cmd += ["--target", target]
    env = dict(os.environ)
    if sys.platform == "darwin":
        env["MACOSX_DEPLOYMENT_TARGET"] = "11.0"
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)
    return target_dir / (target or "") / "release"


def browser(out, target_dir, toolchain):
    wasm = cargo_build(target_dir, toolchain=toolchain, target="wasm32-unknown-unknown")
    browser_dir = out / "browser"
    browser_dir.mkdir(exist_ok=True)
    for name in ("index.mjs", "worker.mjs"):
        shutil.copyfile(BINDINGS / "browser" / name, browser_dir / name)
    shutil.copyfile(wasm / "filang_engine_binding.wasm", browser_dir / "filang_engine.wasm")
    print(browser_dir)


def host_platform():
    arch = platform.machine().lower()
    if sys.platform == "darwin":
        return f"macosx_11_0_{arch}", "libfilang_engine_binding.dylib"
    if sys.platform == "linux":
        return f"linux_{arch}", "libfilang_engine_binding.so"
    if sys.platform == "win32" and arch == "amd64":
        return "win_amd64", "filang_engine_binding.dll"
    raise SystemExit(f"unsupported wheel platform {sys.platform} {arch}")


def wheel(out, target_dir, toolchain):
    platform_tag, libname = host_platform()
    release = cargo_build(target_dir, toolchain=toolchain)
    release_version = version()
    tag = f"py3-none-{platform_tag}"
    info = f"{MODULE}-{release_version}.dist-info"
    path = out / f"{MODULE}-{release_version}-{tag}.whl"
    files = {
        f"{MODULE}/__init__.py": (BINDINGS / "python" / MODULE / "__init__.py").read_bytes(),
        f"{MODULE}/_filang_engine{Path(libname).suffix}": (release / libname).read_bytes(),
        f"{info}/METADATA": (
            "Metadata-Version: 2.1\nName: filang-engine\n"
            f"Version: {release_version}\n"
            "Summary: Filang exact geometry and study engine\nRequires-Python: >=3.10\n"
        ).encode(),
        f"{info}/WHEEL": (
            f"Wheel-Version: 1.0\nGenerator: Filang\nRoot-Is-Purelib: false\nTag: {tag}\n"
        ).encode(),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((f"{info}/RECORD", "", ""))
    files[f"{info}/RECORD"] = record.getvalue().encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "target" / "engine-dist")
    parser.add_argument("--wasm-toolchain", default="stable")
    parser.add_argument("--native-toolchain")
    parser.add_argument("--only", choices=("browser", "wheel"))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build_dir = ROOT / "target" / "bindings"
    if args.only != "wheel":
        browser(out, build_dir, args.wasm_toolchain)
    if args.only != "browser":
        wheel(out, build_dir, args.native_toolchain)


if __name__ == "__main__":
    main()
