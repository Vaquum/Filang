# Query first answer on the live site

One cache-disabled Chrome reload of [query.vaquum.fi](https://query.vaquum.fi/) behind the Portal login on 2026-11-23 reached the first visible answer in **3,743.3 ms**. The first ledger rows began appearing in the next frame at 3,744.2 ms. The default question was the failed break of the prior low, using the 180-day BTCUSDT 15-minute window. It returned 177 closes. See the [sanitized trace timings](cold.json).

| Request | Start | End | Trace encoded data | Decoded body |
| --- | ---: | ---: | ---: | ---: |
| Engine JavaScript | 825.7 ms | 879.9 ms | 2,874 B | 8,013 B |
| Engine WASM | 911.6 ms | 1,279.7 ms | 323,971 B | 944,551 B |
| Available recording windows | 1,286.4 ms | 1,333.2 ms | 560 B | 663 B |
| Cube bars | 1,333.5 ms | 3,624.3 ms | 385,126 B | 1,046,062 B |

Timestamps are relative to the main navigation start. The production edge was already compressing both engine responses. The bars request took 2,290.8 ms, including 2,076.5 ms before the response, and the first answer was visible 119.0 ms after the recording arrived.

The [preregistered plan](protocol.md) called for repeated cold and warm loads. Chrome foreground interruptions limited reliable capture to one complete cold trace. This is one sample on an Apple M1 Max using an unthrottled network connection and an already authenticated session. The filmstrip timestamps bound when the answer was observed. A pre-#92 deployment or production trace was unavailable. The [localhost comparison](../20261123-query-on-engine/README.md) cannot establish a production regression, so the comparison outcome is inconclusive. The server's caching policy was outside the change because the issue made it conditional on that comparison.

## Reproduction

Open the production Query bench in Chrome with the Portal session authenticated. In DevTools Network, select Disable cache and No throttling. In Performance, enable Screenshots, record and reload, and export the trace locally. Locate the main frame's navigation start and the first filmstrip frame displaying the answer. Compare ResourceSendRequest, ResourceReceiveResponse and ResourceFinish timestamps for the engine and recording paths.
