# Composer numeric frame loading

The [issue #96 protocol](protocol.md) measures the five-timeframe Composer cutover with 468,059 observed BTCUSDT bars. Both cutover variants use the same candidate WASM package and Composer at `7688883e07458cdd8e04a53506a57eaede8eff84`. The only page variant difference is the frame load call. The separate compressed-page reference uses the original matcher at `9b5c2c0638575ec89ff810f4c7a788bb114c501d` from [Composer #55](https://github.com/Vaquum/Composer/pull/55).

**A1 supported.** Median frame preparation fell from 489.6 to 42.7 ms, including packing and loading all five frames after Composer had decoded its arrays. That is a 91.3% reduction. CSV formatting and engine loading separately took 294.4 and 198.4 ms as medians. Decode is timed separately. The ten runs yielded identical grid dimensions and byte digests of the two sampled search replies and packed cohorts. See [all ingestion runs](ingest.jsonl).

**A2 supported.** In the same cutover page, median first matches improved by 365 ms cold and 323 ms warm. First results with typed input were 40 ms behind the compressed prior matcher cold and 359 ms behind it warm. All nine runs passed Composer's load, cache revalidation, complete readings, layout and cancellation checks. See [browser runs](page.jsonl).

| Page milestone, median ms | Compressed prior matcher | Cutover via CSV | Cutover via typed columns |
| --- | ---: | ---: | ---: |
| Cold first matches | 3307 | 3712 | 3347 |
| Cold with readings | 6675 | 6618 | 6653 |
| Warm first matches | 601 | 1284 | 960 |
| Warm with readings | 1309 | 1284 | 960 |

The [Composer parity check](composer-parity.txt) compared every displayed figure in 18 questions and 120 named-candle counts with the original matcher. Direct and worker binding tests cover millisecond and second columns, exact large cents, gaps, malformed data and atomic frame replacement.

## Reproduction

Apple M1 Max, 64 GiB RAM, macOS 26.6.2, Node 23.10.0, Rust 1.63.0 WASM. Browser runs used Playwright 1.63.0 with Chromium 153.0.8010.12 and the check's 80 ms latency and 10 Mbit/s download. Each variant ran in its own fresh process or browser profile. Timing covers one host and instrument. The browser comparison measures the complete page, including cache, engine startup and search.

Use the [pinned five histories](../composer-search/sources.json) and the fixture builder from Filang #85. Verify SHA-256 `b71f8bc0ce4f2bd01a75a7c7b1f17b862167f8fd56718ed9ba5c3a0559b5507c` for `bars` and `499107439cbb69d65922655145d3a3fe239d727cce19233500c9d97947199b84` for `activity`.

```sh
python3 bindings/build.py --only browser
node benchmarks/reports/composer-frame/ingest.mjs "$ENGINE_DIR" "$COMPOSER_CUTOVER/matcher.js" "$FIXTURES/bars" csv
node benchmarks/reports/composer-frame/ingest.mjs "$ENGINE_DIR" "$COMPOSER_CUTOVER/matcher.js" "$FIXTURES/bars" ticks
```

For the numeric page, change just the `give` frame-load call in a copy of the cutover checkout. Its decoded `T.ts` uses seconds.

```js
filang.loadComposerFrameTicks(T.sec * 1000, {
  times: T.ts, open: T.O, high: T.H, low: T.L, close: T.C, timeUnit: "s",
})
```

Run the following from each Composer checkout with its Playwright dependencies installed. Use the same absolute candidate `ENGINE_DIR` for both cutover variants.

```sh
COMPOSER_ENGINE_DIR="$ENGINE_DIR" node checks/loading-performance.mjs matcher.js "$FIXTURES/bars" "$FIXTURES/activity" "$(command -v python3)"
COMPOSER_ENGINE_DIR="$ENGINE_DIR" node checks/engine-parity.mjs "$PWD/matcher.js" "$FIXTURES/bars" "$FIXTURES/activity" "$(command -v python3)"
```
