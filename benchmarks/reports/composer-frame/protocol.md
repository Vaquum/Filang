# Composer numeric frame ingestion protocol

[Issue #96](https://github.com/Vaquum/Filang/issues/96) identifies a load-time round trip through CSV after [#95](https://github.com/Vaquum/Filang/pull/95). Use the same 468,059 BTCUSDT bars on five timeframes and matching activity data from Composer. The Filang baseline is release 0.10.0.post26 at 5bff87e. The Composer cutover checkout is 7688883. Include the compressed-page variant from Composer #55 as an external page-loading reference when its check can run with the same fixture and network settings.

## A1. Frame ingestion

Giving Filang the decoder's typed columns directly will reduce the median time from decoded arrays to five ready engine frames by at least 80% against CSV. Measure five fresh Node 23.10 processes per path on Apple M1 Max, alternating order. Compile and decode before measuring ingest, use the same candidate engine for both paths, and record decode separately. On CSV, time construction and all five loads separately. Time the complete typed ingestion including packing. Verify identical grid sizes, all 18 Composer answer cases, and packed positions against CSV. Exercise timestamp units, gaps, exact integer cents and rejection of malformed inputs separately.

## A2. Composer page

At identical browser and network settings, using typed input in the same cutover checkout will improve median first matches by at least 200 ms on both cold and warm page loads. Use Composer's loading check with 80 ms latency and 10 Mbit/s bandwidth, and run three fresh profiles per implementation in alternating order. Use the same candidate WASM build in both versions of the cutover to isolate the loader and apply the change in a scratch checkout. Record timings against the compressed prior matcher when the same check is usable. Preserve complete readings, request caching, and worker cancellation checks. Retain deviations and any measured gap to the earlier matcher.
