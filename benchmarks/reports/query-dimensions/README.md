# Query dimension switches

## Protocol

Measure the parent Query bench and the dimension UI on one local Chrome instance at 1440 × 900 with the inspector open. Both pages use the same WASM bundle and the same pinned BTCUSDT 15m prices and synthetic Cube counters. Serve byte-identical counter-bearing recordings to both pages for the window switch so the comparison isolates the UI. Keep all five dimension lanes off.

Alternate the two pages for nine cycles and drop the first cycle per page. Use a fresh page for each cycle. Measure navigation to the first answer, the window switch to the first answer, opening all four starting questions, stepping to the first and next two inspector closes, and opening the list of conditions. Use the median for comparisons. Require matching answer counts and formal text throughout, and no material change in any off-switch latency. A baseline difference over 10% and at least 2 ms is a material change for this local headless benchmark. Independently verify nine-column serialization and refusals against the Cube bridge fixture.

In the candidate browser, switch lanes individually and all off, reload a link and check its lanes, inspect a single close, and open a dimensioned drawing. Switch to the pinned recording with a dimension condition and require the engine's refusal to appear beside that condition.

## First attempt

Cold dimension facts and the new condition counts ran inside the shared interaction handlers. With all switches off, nine alternating Chrome 157.0.8103.79 cycles on the M1 Max (first pair dropped) gave the following medians in ms.

| Action | Parent | First candidate |
| --- | ---: | ---: |
| First answer | 171.55 | 174.40 |
| Window switch | 97.20 | 107.75 |
| Four questions | 66.25 | 66.05 |
| First inspector close | 138.45 | 210.30 |
| Each next close | 41.25 | 44.70 |
| Open conditions | 26.15 | 31.65 |

The first inspector close and opening Conditions failed the latency criterion. The window-switch difference also crossed the criterion. Answers and formal text were identical in the paired samples.

## Second attempt protocol

Defer dimension-only inspector facts until opened, and fill the extra condition counts after showing the list. Skip lane drawing work when all lanes are off. Repeat the original nine-cycle protocol. Keep the same criterion and report any remaining overhead. In the browser verification, confirm the new stage opens the full set of dimension facts and asynchronously fills the additional condition counts.

## Second result

| Action | Parent | Candidate |
| --- | ---: | ---: |
| First answer | 167.40 | 182.10 |
| Window switch | 98.55 | 107.05 |
| Four questions | 69.15 | 68.90 |
| First inspector close | 139.30 | 141.80 |
| Each next close | 40.25 | 39.30 |
| Open conditions | 26.30 | 26.75 |

All latencies were within the preregistered equivalence threshold. Initial load and window switch retained 8.8% and 8.6% median differences respectively. The comparison controls the recording payload and excludes the cost of transporting a larger nine-column response over a real network. It also measures opening the condition list, while the additional counts finish asynchronously. Local Chrome verified both the eventual counts and the opened dimension facts.

The Cube bridge regression compares the nine columns bar for bar over 14,496 fixture bars, checks float round-trips, and exercises taker-buy and trade-count refusals. A read-only probe against the actual 180-day Cube window received 17,280 bars ending 2026-11-23 17:15 UTC. Its CSV SHA-256 was `b5b777b470f265577f59a08f44075aa08e52e16efb83518d46f3353be890cf59`. The shared engine returned 8,327 higher-volume closes, 8,567 positive-delta closes, 1,144 new four-hour delta lows, 818 refined chained g1 matches, and 181 hammers with volume at least 1.5 times the preceding four-hour median.

```sh
node query/verify/cube-source.mjs
node query/verify/dimensions.mjs
node query/verify/parity.mjs
node query/verify/handoff.mjs
node benchmarks/reports/query-dimensions/measure.mjs "$BASELINE_WORKTREE" --smoke
node benchmarks/reports/query-dimensions/measure.mjs "$BASELINE_WORKTREE"
```

Set `PLAYWRIGHT_MODULE` to the local Playwright `index.mjs`, `CHROME` to the Chrome executable, and `FILANG_QUERY_ENGINE_DIR` to the same browser package for both worktrees. Set `FILANG_STUDY_DATA` if the pinned recording lives outside `data/study`. The timed comparison used the Query receipt parent `269d97f` and the local build of its engine.

## Third attempt protocol

The chart reads only the first five CSV fields while switches are off. Allocate only those fields in its price pass. Show window-loading feedback in the existing control while the window is in flight and rebuild the controls when the answer changes. Repeat the same Chrome comparison. The first-load and window-switch medians should move closer to the parent and the other actions should stay within the original margin.

The third attempt yielded parent/candidate medians of 171.65/199.95 ms on navigation and 101.30/110.65 ms on window switch. Other actions stayed within the criterion. These edits were discarded.

## Fourth attempt protocol

Keep the empty-lane canvas layout unchanged and reuse the existing canvas module and its quantile helper. Create dimension lane markup only when the first lane is shown. Repeat the nine-cycle browser comparison and off-switch parity, including toggling every lane back off.

## Final result

| Action | Parent | Candidate |
| --- | ---: | ---: |
| First answer | 160.85 | 164.40 |
| Window switch | 95.60 | 102.80 |
| Four questions | 69.80 | 66.10 |
| First inspector close | 139.50 | 139.95 |
| Each next close | 38.90 | 40.30 |
| Open conditions | 25.95 | 26.65 |

All six medians met the original margin. The remaining window-switch difference was 7.5% on the identical-payload test. The answers at the first load, after switching windows and for each starting question matched. The browser smoke check passed after turning every lane back off.
