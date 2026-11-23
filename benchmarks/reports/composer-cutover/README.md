# Composer cutover proof

The engine covers all four API gaps and the hold-search regression in [issue #94](https://github.com/Vaquum/Filang/issues/94). The 18 replay scenarios use 468,059 BTCUSDT bars across 15m, 30m, 1h, 2h and 4h, with the original activity series. Every final run reproduced counts, next-bar split and base rate, displayed windows with scores and picks, one-away rows, and all cohort panes, including the seven closest cohorts missing from the baseline. See the [preregistered protocol](protocol.md) and [measurements](measurements.jsonl).

| Scenario | Old Composer | Base engine with pages | Packed API only | A2 with packed API | Final | Base → final position read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2-bars-pin | 257.1 | 326.5 | 192.7 | 122.1 | 132.2 | 141.84 → 1.52 |
| 2-bars-pin-stretch-4 | 915.6 | 1329.5 | 715.5 | 927.1 | 425.0 | 666.29 → 9.30 |
| 5-bars-cross-pin | 905.6 | 1627.3 | 1250.0 | 1457.4 | 542.3 | 459.91 → 3.86 |
| 10-bars-17-pins | 1015.3 | 1585.1 | 1587.4 | 1231.6 | 371.3 | 2.33 → 0.07 |
| 10-bars-17-pins-filter | 234.7 | 362.9 | 351.9 | 79.4 | 69.0 | 0.21 → 0.04 |

Times are milliseconds, median of three fresh Node 23.10.0 processes per build on an Apple M1 Max with 64 GiB RAM and macOS 26.6.2. WASM used Rust 1.63.0. Each process loaded the fixture once before timing. The replay measures the original matcher followed by the cutover worker for every scenario. The old Composer column comes from the final runs. Input loading is reported separately. Large typed reads run in-process in Node. Browser transfer correctness and step latency are verified separately.

- **A1 supported.** The 235,963-window read dropped from 141.81 to 1.51 ms in the API-only build. The 1,179,515-window read dropped from 666.3 to 7.0 ms. Both exceed the 80% reduction threshold. Final packed reads took 1.5 and 9.3 ms.
- **A2 not supported.** At `e08db263`, fixed-end feasibility and direct contiguous evaluation improved the filtered 17-pin case from 316.1 to 43.7 ms of engine work. The stretched cross-pin and 17-pin cases still exceeded the old matcher end to end. Two-bar stretch regressed with the placement setup.
- **A3 supported.** At `9a2db046`, retaining traversal state until the step budget is spent and directly evaluating unique placements removed the remaining measured regressions. Final search medians were 228.9 ms for the cross pin, 325.5 ms for stretched 17 pins, and 35.7 ms for filtered 17 pins. Final end-to-end medians beat the old matcher in all 18 cases.

The measured workload covers one instrument and one host. Timings vary across fresh processes and include consumer statistics and JavaScript allocation. The full ordered results remain independent of step size, and the compact result holds only position columns. Limit changes, new timeframes, and the downstream release cutover are outside this proof.

The independent [engine parity replay](engine-parity.jsonl) checked 16 cases, including all ordered JSON and packed positions and the old drawing metadata. In [headless Chrome](browser.json), the binding passed 720 geometry and 53 radius vectors, the nine-rule ledger, named ranges, and transferred typed arrays. The [real-bar worker replay](composer-browser.json) completed 11 scenarios with an 8.7 ms worst progress gap and two cancellations within 11.3 ms.

## Reproduction

Use [the pinned data sources from #85](../composer-search/sources.json). The `bars` SHA-256 is `b71f8bc0ce4f2bd01a75a7c7b1f17b862167f8fd56718ed9ba5c3a0559b5507c` and the `activity` SHA-256 is `499107439cbb69d65922655145d3a3fe239d727cce19233500c9d97947199b84`. The matcher baseline is Composer `bd6a0ba32e18548b641267418491bfb5f011a274`. The cutover checkout used locally is Composer `c0330e1c1b2ee8eb1530e0bfa1f9837886f5e1b6`. The replay applies the browser API changes to that checkout in memory.

Build Filang `e5a3fbd`, `e08db263` and the candidate with `python3 bindings/build.py --only browser` in separate checkouts. Use the cutover checkout for the replay and the baseline Composer checkout for the independent raw contract check.

```sh
git -C "$COMPOSER_CUTOVER" show bd6a0ba:matcher.js > "$OLD_MATCHER"
python3 bindings/verify/prepare_composer.py "$COMPOSER_BASE" "$FIXTURES"

node benchmarks/reports/composer-cutover/replay.mjs "$FILANG_BASE" "$COMPOSER_CUTOVER" "$FIXTURES" "$OLD_MATCHER" baseline
node benchmarks/reports/composer-cutover/replay.mjs "$FILANG_A2" "$COMPOSER_CUTOVER" "$FIXTURES" "$OLD_MATCHER" packed
node benchmarks/reports/composer-cutover/replay.mjs "$PWD" "$COMPOSER_CUTOVER" "$FIXTURES" "$OLD_MATCHER" packed
node bindings/verify/composer.mjs "$COMPOSER_BASE" "$FIXTURES"
```
