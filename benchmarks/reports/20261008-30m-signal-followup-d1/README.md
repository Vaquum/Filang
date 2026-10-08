# F30-D1 — 30-minute signal follow-up

**Final scientific outcome: not-supported.** Full independent audit: PASS.

This is a retrospective diagnosis of the already selected R1a 30-minute lead. The complete stability claim requires the matched affine-score gain, primary uncertainty conditions, annual consistency, and a positive partial-2026 effect. It is not a prospective confirmation, isolated wick effect, mutual-information estimate, or trading result.

## Primary result

| Quantity | Result |
|---|---:|
| Adapted B−G log-loss gain, nats per binary observation | 0.0004321658981 |
| Individual 95% interval, seven-day bootstrap | [7.614851823e-05, 0.0008019818147] |
| Exact one-sided p-value | 0.01299350325 |
| Exact tail hits / replicas | 25 / 2000 |
| Scored binary observations | 66002 |
| Positive annual adapted gains | 2 / 4 |

| Required condition | Passed |
|---|---|
| ci above zero | true |
| latest 2026 positive | false |
| One-sided p < 0.05 | true |
| positive pooled gain | true |
| three positive years | false |
| Eight accepted fits and full independent audit | true |

A failure of the latest-year gate does not erase pooled evidence. The original unaudited producer outcome remains byte-preserved; this report joins it to the later full audit.

## Annual and pooled attribution

| Period | Binary count | Raw B−G gain | Adapted B−G gain | Raw payoff alignment | Adapted payoff alignment |
|---|---:|---:|---:|---:|---:|
| 2023 | 17496 | 0.001586663019 | 0.001657179466 | -2.726777337e-07 | -3.898630054e-07 |
| 2024 | 17561 | 0.000768797864 | 0.0003839775588 | -9.675241628e-07 | -5.999593277e-07 |
| 2025 | 17514 | 0.0002030977583 | -0.0001849171005 | -2.487697677e-08 | 1.768531794e-07 |
| 2026 | 13431 | -0.0005419895019 | -0.0002959265985 | -2.91225967e-07 | -3.174717272e-07 |
| pooled | 66002 | 0.0005687510774 | 0.0004321658981 | -3.955716794e-07 | -2.806606529e-07 |

Alignment is mean((pG−pB) × (log return−past validation mean)) over all target-valid rows, including flats. It is an association statistic, not strategy P&L. The 2026 period ends at the pinned exclusive 2026-10-08 boundary.

## Magnitude attribution

Every bin is defined by the realized next open-to-open log return. These are ex-post diagnostic partitions and cannot act as entry filters.

| Pooled outcome bin | Valid count | Raw gain | Adapted gain | Mean log return | One-bar break-even up frequency |
|---|---:|---:|---:|---:|---:|
| flat | 22 | unavailable | unavailable | 0 | unavailable |
| nonflat_lt1 | 2651 | -0.0005554222588 | -0.001420043449 | 2.214851358e-07 | 24.65017853 |
| 1_to5 | 10547 | 0.001340678991 | 0.0009458620545 | 3.970373631e-06 | 4.537170809 |
| 5_to12 | 15815 | 0.0009593456453 | 0.001178099536 | 1.847178743e-06 | 1.939394 |
| 12_to24 | 17176 | 0.0008204153241 | 0.001389176646 | 3.520727023e-05 | 1.191728575 |
| ge24 | 19813 | -0.000221698546 | -0.001018513124 | 4.766898297e-05 | 0.7420451077 |

The break-even calculation uses realized conditional magnitudes and the declared isolated one-bar round-trip cost of 10 bps fee plus 2 bps slippage per side. It is not a fitted threshold for persistent exposure. Undefined conditional quantities remain unavailable.

| Period | Variant | Absolute-return-weighted log-loss gain |
|---|---|---:|
| 2023 | raw | -0.0007678078479 |
| 2023 | adapted | -0.003299246613 |
| 2024 | raw | -0.001463877684 |
| 2024 | adapted | -0.003131813852 |
| 2025 | raw | 0.0002591627552 |
| 2025 | adapted | -0.0004524389676 |
| 2026 | raw | -0.0007601439205 |
| 2026 | adapted | -0.0003602921115 |
| pooled | raw | -0.0007193227408 |
| pooled | adapted | -0.001933623572 |

Weighted gain scores a return-magnitude-tilted outcome distribution. It is neither an additional primary test nor a realized economic return.

## Primary block sensitivity

| Block days | Gain | Individual 95% interval | Exact one-sided p |
|---|---:|---|---:|
| 1 | 0.0004321658981 | [3.865857686e-05, 0.0008275146273] | 0.0139930035 |
| 7 | 0.0004321658981 | [7.614851823e-05, 0.0008019818147] | 0.01299350325 |
| 28 | 0.0004321658981 | [5.511500143e-05, 0.0007978389999] | 0.008495752124 |

Only seven-day blocks provide the primary decision. Every replicate resamples paired daily loss sums and observation counts. Exact tails use N×T >= 2×S×N*, with equality included, not R3's fixed-denominator predicate. All 6,000 decisions and executed integer encodings are retained.

## Continuation decision

**The declared F30-M1 continuation gate fails.**

| Required gate condition | Passed |
|---|---|
| latest 2026 alignment positive | false |
| pooled alignment positive | false |
| primary supported if verified | false |
| three positive alignment years | false |

This bounded follow-up closes with its full diagnostic findings. Favorable bins, months, or magnitude-weighted scores cannot rescue the failed gate. A later fresh-data study would require a separate frozen specification and execution evidence.

## Audit, provenance and runtime

- Published freeze: `ed7e0b9bccedebc6bda75d7ab701829a6a708c5f`.
- Protocol SHA-256: `4099e7a6620387d0fbe2267819ca0d37dff0f52da3e6bf8689705e979adf497b`.
- Producer implementation: `d26ca231d9af7963bd016aec1a90385c1d1661be`.
- All 118,432 native keys, eight original and eight adapted prediction phases, eight new fits, 55 aggregate periods and every declared detailed cell were checked.
- Maximum adapter gradient: 9.065468682131024e-11.
- Maximum continuous numerical discrepancy: 1.173816599475686e-11; acceptance uses absolute 1e−10 plus relative 1e−10, with exact discrete checks on validated executed inputs.
- Independent audit wall time: 11.160271 seconds.
- Runtime/package/thread/memory settings and operational receipts are retained; no matched speedup claim is made.

The pinned original full R1a audit covers its original unconsumed candidate fits and other timeframes. This audit reconstructs every consumed 30m selected prediction and every new computation. It does not claim to rerun the entire earlier five-timeframe search.

## Complete retained record

All sealed producer artifacts, including every selected predecessor forecast, coefficient/selection record and exact native artifact, are copied with their original bytes. `report.json` binds the producer, audit, source copies, collector and final decision. `manifest.json` and `manifest.sha256` seal this report.

[run/diagnostics.json](run/diagnostics.json) contains the complete fixed panel. The `tables/` directory presents every declared table as CSV, preserving empty cells and undefined values. Original and adapted full-row arrays, sidecars, fit records, daily arrays, bootstrap replicas and exact integer encodings remain in the copied run.

Raw Parquet and prepared OHLC CSV inputs remain external with the original immutable dataset revision and exact byte identities. The scoped source bundle intentionally contains the consumed R1a evidence, not every original five-timeframe run file. Refer to [FOLLOWUP30.md](../../../experiments/geometry_information/FOLLOWUP30.md) for the scientific contract and reproduction commands.

## Retained audit attempts

Earlier failed full audits are inconclusive validation attempts. Their original receipts remain visible alongside the successful full audit.

- Retained FAIL: [geometry-followup30-d1-verification-first-failed.json](receipts/geometry-followup30-d1-verification-first-failed.json); error `"'minutes'"`; verifier `876fcfde2896e0c3c77157e09adc9895b611cc8b9f7cd63ec06d31e9a98e0e89`.
  The retention and successful retry receipts bind this failure to a re-audit of the same sealed producer. The producer, fitted adapters, forecasts and scientific results were not rerun or replaced.
  The verifier had passed a native-key receipt without the timeframe context expected by the inherited prediction oracle. The reviewed verifier-only repair restored that context with source/interval/key checks and an unmocked integration regression.
