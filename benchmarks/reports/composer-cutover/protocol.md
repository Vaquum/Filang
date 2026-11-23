# Composer cutover protocol

Issue [#94](https://github.com/Vaquum/Filang/issues/94) follows [#85](https://github.com/Vaquum/Filang/pull/85). Baseline Filang is `e5a3fbd` and the previous Composer matcher is `bd6a0ba`. Use Composer's local cutover at `c0330e1` and the same 468,059 BTCUSDT bars, five timeframes, and activity fixture as #94. Record fixture digest, Rust and Node versions, machine, and warm timings. Run three fresh processes per revision, all 18 scenarios, on the same host. Time search steps, position reads, and complete consumer calls separately, excluding fixture loading. Compare medians by scenario. Keep the old matcher in each comparison and retain all observations.

## A1 — Position transfer

Replacing object pages with copied, transferable typed columns will cut median position read time by at least 80% in the two 2-bar colour-pin scenarios, including stretch 4. Compare packed and paged ordered positions, all kinds, both browser bindings, and complete panes against the old matcher. Closest cohorts must consume the full global ranking in its original order, including overlaps. Use catalogue and drawing-rule parity vectors to check the other additions.

## A2 — Held search

Directly test the only placement of an un-stretched window and discard impossible stretched end constraints before enumerating placements. This should bring the complete packed consumer under the old matcher in the cross-pin and two 17-pin cases in #94. Compare each median to both the old matcher and the baseline engine. Exact counts, ranks, first admitted picks, fallback indices and consumer panes must agree. Retain any regressions or missed thresholds.

## A3 — Placement traversal

The first A2 run passed all correctness cases but still exceeded the predecessor on the stretched cross-pin and 17-pin cases, and the two-bar stretch search regressed. Keep the placement state in the work loop until its node budget is spent and handle two-bar stretch as one placement. Skip forming price endpoints for contiguous windows whose colours rule out exact, one-away, and within results and which do not enter ranking. This should bring the median complete time below the old matcher for cross-pin, both 17-pin cases and two-bar stretch, with unchanged full panes and ordered positions. Compare three runs against A2 and the old matcher, and check browser step cadence and cancellation separately.
