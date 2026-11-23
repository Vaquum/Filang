# Query occurrence receipts and the browser package

[Protocol](protocol.md). On an Apple M1 Max with Node 23.10.0 and the 14,496-bar pinned BTCUSDT recording, one fresh engine process per sample read the first occurrence page, unknown count, line text and columns for each of the four starting questions. The benchmark starts after loading the same recording through the same adapter. A1 used release 0.10.0.post21 and the stripped candidate, alternating order between five pairs.

| Four questions | Published post21 | Candidate |
| --- | ---: | ---: |
| Median elapsed | 36.05 ms | 24.83 ms |
| Describe calls | 8 | 4 |
| Occurrence page calls | 4 | 4 |
| Full study calls | 4 | 0 |

Baseline samples in ms were 36.05, 66.67, 56.30, 35.27, 30.28. Candidate samples were 24.83, 24.71, 31.34, 22.57, 25.02. All ten receipt digests were `a2475abb3a07461f6f99fb938eb4a163e06793d0e5a49ae411a4823eb9d5f5d4`. This boundary excludes network, recording load and painting. Exact checks cover rows, outcome truth, mixed formal clauses and reattaching a drawing to held relations.

For A2, building identical sources with and without `-C strip=symbols` yielded 912,999 versus 1,230,356 raw WASM bytes and 321,911 versus 422,156 deterministic gzip bytes (23.7% fewer). The old post21 release was 944,551 raw bytes and 306,306 gzip bytes. The paired trial isolates the strip flag, while the end-to-end bundle also carries code added since post21. Native wheel builds use their existing flags.

```sh
python3 bindings/fetch_browser.py 0.10.0.post21 --out /tmp/filang-receipt-base
RUSTFLAGS='' python3 bindings/build.py --only browser --out /tmp/filang-receipt-unstripped
python3 bindings/build.py --only browser
FILANG_QUERY_ENGINE_DIR=/tmp/filang-receipt-base node benchmarks/reports/query-receipts/measure.mjs
node benchmarks/reports/query-receipts/measure.mjs
node bindings/verify/query-contract.mjs
node query/verify/parity.mjs
node query/verify/handoff.mjs
```

Both builds can be compared with Python's `gzip.compress(data, mtime=0)`. Run after preparing the pinned recording and Composer fixtures per the CI workflow, or set `FILANG_STUDY_DATA` to their directory.
