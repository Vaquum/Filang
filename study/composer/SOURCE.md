# Composer in the study

The editor, Web Worker matcher, continuation views and motion system are from [Vaquum/Composer at 133e301](https://github.com/Vaquum/Composer/tree/133e3017ba9143f7dc255df7218ff7bfe46d9d06). Its MIT license is in this directory.

The local edition enables one-candle drawings, limits history to the lab’s BTCUSDT spot 15-minute recording, and adds the recorded-candle selector and exact G1 handoff. A saved drawing retains its endpoint values, orientation, manual pins, skeleton, stretch, result limit and next-bar exploration settings. The drawing handoff imports its exact G1 as an event detector. The named-rule handoff is described below. Composer uses its original workers for the held-window and nearest-shape views. G1 transfers in oldest-first order.

The binary files `bars` and `activity` come from running the pinned Composer `bars.frame`, `encode` and `encode_activity` on the Limen Parquet identified in [the recording provenance](../data-provenance.json). The study CSV and the Composer OHLC tape agree at all 14,496 opens and closes. The original Parquet also supplies the observed volume, quote volume, maker volume and trade count required by the activity panes.

Run `node verify/composer.js` from the lab directory to check the tapes and the drawing codec.

## Named profiles

The named-rule browser, compiled catalog and matcher are byte-for-byte copies of the Composer revision recorded in [patterns-lock.json](patterns-lock.json). The paper and drawing packet retain the base version described above. The independent named-rule route accepts `?pattern=hammer` and returns its stable profile ID to the study. It scans the same 15-minute integer-cent tape; gaps reset multi-bar windows. A named scan includes price ratios when its rule specifies them. Its observed sample windows never stand in for the named rule.

Run `node composer/sync-patterns.mjs` to verify the three local assets offline. To update them together, run `node composer/sync-patterns.mjs --update /path/to/Composer FULL_COMMIT_SHA` and rerun the Composer, named-pattern and native parity checks before publishing.
