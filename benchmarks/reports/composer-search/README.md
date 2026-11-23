# Composer engine search proof

The [recording pins](sources.json) identify 468,059 BTCUSDT bars on the five
Composer timeframes. Prices are integer cents throughout matching. We
verified that all five parquet schemas carry `maker_liquidity`. Their
quote counters can therefore be formed as
`taker_buy_volume = liquidity_sum - maker_liquidity`.

The [unpruned candidate](unpruned.jsonl) matched the checked outputs but
missed the latency goal. The five-bar stretch search took 5.20 s and the
ten-bar stretch search hit the 30 s stop. The initial run samples are
retained. Its exact source tree was superseded during local development.
The optimized build retains the
same search and prunes placements using remaining colour cost and rules
against a span's fixed last candle.

The [pinned oracle run](oracle.jsonl) checked 16 cases on identical real
bars in Node 23.10.0. It compared exact and held counts, optional end
eligibility, one-away frequencies, fallback broken rules, the displayed
windows and picks, and scores within 1e-12. It also verified bounded
position pages. Cases include the pinned search workload, skeleton,
cross-endpoint and double-bottom holds. The few slower cases appear in
the same log.

The [Chrome worker run](chromium.json) passed all eleven scenarios on
macOS arm64. Its longest search was 1.466 s and the largest gap between
progress messages was 34.4 ms. Replacement searches cancelled their
predecessors in 10.9 and 11.2 ms, with no stale result. Loading the five
tapes took 335 ms separately. The Chrome report includes its version and
every scenario. The workbench's next-bar logic remains in Composer, which
can pass an end mask to include its criterion in ranking and positions.
Dimension-aware ranking is tracked in #72.

From the Filang root, with Composer at `bd6a0ba` and its Python
requirements available:

```sh
python3 bindings/verify/prepare_composer.py /path/to/Composer /tmp/composer-fixtures
python3 bindings/build.py --only browser
node bindings/verify/composer.mjs /path/to/Composer /tmp/composer-fixtures
FILANG_COMPOSER_FIXTURES=/tmp/composer-fixtures node bindings/verify/chromium.mjs \
  /path/to/chrome /path/to/price.csv /path/to/counters.csv composer-browser.html
```

The other two fixture arguments belong to the shared Chrome runner and
are unused by the Composer page. See the prior [protocol](protocol.md).
