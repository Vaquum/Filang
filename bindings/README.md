# Filang engine bindings

Install the engine from PyPI, or fetch the browser package from a versioned
[GitHub release](https://github.com/Vaquum/Filang/releases). Both packages
report the same release version and binding ABI through `version()`.

## Published packages

Every push to `main`, including each PR merge, runs
[`publish-engine.yml`](../.github/workflows/publish-engine.yml). It builds and
verifies Linux x86_64 (`manylinux_2_28`) and macOS Apple silicon wheels on
Python 3.10 and 3.13, then publishes `filang` to PyPI using trusted publishing.
The Python import remains `filang_engine`.

Versions are the Cargo version plus `.postN`, where `N` is the publishing
workflow's run number: for example, `0.10.0.post123`. This gives every merge
a unique stable version within `>=0.10,<0.11` without a version-bump commit.
The same run creates tag `v0.10.0.post123` at its source commit and publishes
`filang-browser-0.10.0.post123.tar.gz` and `SHA256SUMS`. Reruns use the same
version. PR runs build and verify packages without publishing.

Pin a published version in Limen and regenerate its hash locks against PyPI:

```sh
python -m pip install --only-binary=:all: 'filang==0.10.0.post123'
uv pip compile --generate-hashes requirements.in -o requirements.txt
```

Use `filang>=0.10,<0.11` in Limen's input requirements (replacing the original
`filang-engine` distribution name), or pin an exact release. The generated
lock identifies the exact wheel and its index-provided hash.

Query and Composer can download the four browser files before building their
images, without Rust or registry credentials:

```sh
python3 bindings/fetch_browser.py 0.10.0.post123 --out engine
```

The downloader requires an exact version, checks the archive against the
release's published `SHA256SUMS`, and writes only `index.mjs`,
`worker-client.mjs`, `worker.mjs` and `filang_engine.wasm`. The standalone
script uses only Python's standard library and can be vendored by consumers.
Keep the chosen version in the consumer repository; do not download `latest`.

PyPI must have the `filang` trusted publisher configured for repository
`Vaquum/Filang`, workflow `publish-engine.yml`, environment `pypi`. No PyPI
API token is needed. The workflow finishes by installing from the public index,
generating a hash lock, and downloading and verifying the public browser release.

## Local build

Build a browser package and an offline Python wheel from this checkout.

```sh
rustup target add wasm32-unknown-unknown --toolchain stable
python3 bindings/build.py
cargo build --release --locked --offline
```

The Python wheel is for the build host's OS and architecture. Use
`--native-toolchain` and `--wasm-toolchain` to pin Rust versions. The
release outputs are in `target/engine-dist`. The Filang version and binding
ABI are available through `version()`.

## Query and Composer

Serve the four files in `target/engine-dist/browser` from one origin. Serve
the WASM file as `application/wasm`. The module worker owns the recording
and prepared widths.

```js
import {openFilangWorker} from "./engine/worker-client.mjs";

const filang = openFilangWorker();
await filang.ask("loadCsv", recordingCsv, 900_000);
await filang.ask("prepare", 2, {reading: "chained", dimensions: ["volume"]});
const result = await filang.ask("drawCounts", [
  [20, 50, 15, 40],
  [40, 85, 30, 60],
], {reading: "chained", axes: {volume: [1, 2]}});
const {shape, counts} = result;
```

Drawings use OHLC and mark coordinates. Signed marks use zero as their
reference. Use `drawCounts` for live changes, `at` for the identity of a
recorded window, and `positions` for a bounded page of matching slots.
`decodeDrawing(packetText, expectedCode)` returns the validated packet,
its canonical shape and its optional pinned expression. `encodeDrawing`
selects the packet revision from the supplied parts. `drawingProtocol`
returns both compatible revisions. `distance` returns comparison
differences in half-flips for a pair of complete patterns.
Pass `radius` to `counts`, `positions` or `classify` to include
patterns within that many half-flips over their selected axes and
orientations. `neighbourhood` returns counts plus observed window counts
by distance. The default radius is zero. Study's `exact_g1` and
`chained_g1` accept an optional `radius` and sweep lists.

Use `study(query, {candidate})` for Query's Filang text and its close-anchored
counts, eligible closes, unknowns, groups and outcomes. Candidate indices
are zero-based. Omit the index to run all candidates. `check(query)` validates
the same text and returns its candidate count. `setCalendar()` loads the
bundled NYSE table. Pass TSV and `{table: id}` for a different pinned table.
`installDefinition(text, sha256)` checks the bytes, dependency pins and
recorded conformance cases before adding the definition to the recording's registry. `catalogue()`
returns the generated named candle definitions.

`release(width)` releases that width's preparation. `close()` terminates
the browser worker. Direct calls in a browser test or single-threaded
application can use the same methods on `await FilangEngine.create()` from
`index.mjs`.

## Limen

```sh
python -m pip install --no-index --find-links target/engine-dist filang
```

```python
from filang_engine import Engine

with Engine() as engine:
    # Rows are OHLC plus quote volume, taker-buy quote volume and trade count.
    engine.load(rows)
    engine.prepare(2, reading="chained", dimensions=("volume",))
    values = engine.classify(code, reading="chained", start=0, limit=4096)
```

Load bars once per recording. Iterate `start` by the page size for a full
feature. Classification emits `True`, `False` or `None` on the original bar
grid. A gap is one `None` row on that grid. Copy venue counters as recorded.
For Limen's stored spot klines the fields are `liquidity_sum`,
`liquidity_sum - maker_liquidity` and `no_of_trades`. Counter precision is
part of the source identity. Import and evaluation use the bundled
library in process on Python 3.10–3.13.

Python also exposes `load_csv`, `at`, `counts`, `positions`, `draw_counts`,
`study`, `check` and the packet methods with snake-case names. Arrays of
compact key words and exact cardinalities use decimal strings to preserve
their full integer precision across bindings.

## Command line

Keep `filang` and `filang-engine` in the same directory.

```sh
target/release/filang engine --operation domain --width 24 \
  --mode oriented --dimensions volume,delta
target/release/filang engine --operation counts --bars recording.csv \
  --interval-ms 900000 --reading chained --pattern 'g1:o:0,1,2,2,u'
target/release/filang engine --operation study --bars recording.csv \
  --interval-ms 900000 --calendar pinned --query study.filang
```

The recording header and units are in [the dimensions contract](../docs/G1_DIMENSIONS.md).
A six-column recording carries price data and base volume. A nine-column
recording also carries quote volume, taker-buy quote volume and trade
count. A CSV window uses zero-based inclusive end slots. A pattern's
price axis and selected counter dimensions have independent orders.

### Exact exploration

A prepared width indexes observed keys on each axis separately. Exact
counts intersect sparse offset lists or packed bitmaps. A separate
validity count covers the requested axis set. Costs depend on the
recording's observed keys and matching positions. Repeated drawing edits
reuse one preparation. A new width or axis prepares in the worker.

Interactive windows support 1–256 contiguous bars and recordings up to one
million slots. Compact keys retain their existing four price words and
optional dimension words through ten bars. Wider patterns carry their
canonical g1 text. Domain counting uses exact arithmetic independent of the
recording. For dependent axes the declared count includes unrealizable
combinations.

## Reproduction

With the inputs from the existing pinned study fixture workflow:

```sh
node study/catalogue/generate.mjs --check
python3 study/verify/dimension-vectors.py
python3 bindings/verify/vectors.py --cli target/release/filang
FILANG_STUDY_DATA=/path/to/pinned/data node bindings/verify/query.mjs
python3 bindings/verify/prepare_limen.py spot_15m_20250101_20250531.parquet counters.csv
python3 bindings/verify/limen.py counters.csv
node bindings/verify/chromium.mjs /path/to/chromium recorded-bars.csv counters.csv
```

Run the Python verification scripts inside an environment with the wheel
installed. The retained benchmark protocols and results live under
[the benchmark report](../benchmarks/reports/shared-engine/).

To compare data sources on overlapping closes, install the wheel and run
`python bindings/verify/compare_sources.py left.csv right.csv --width 4 --dimensions volume,delta`.
The command records both file digests, compares the requested canonical
identities and reports the first differences. Omit `--dimensions` for
price-only comparisons.
