# Filang query workspace

Compose a question from the typed builder or the formal editor. Choose a named
candle pattern in English or Japanese, combine same-close events, add filters
or a grouping, compare parameter values, and inspect the recorded closes and
outcomes. **Explore in Composer** opens the matching named rule or drawing.
Drawings return to the builder as exact G1 or as pinned relationships on fixed
consecutive candles. **Agent definitions** accepts versioned, tested event and
condition compositions. Saved links pin the data, definitions and evidence.
Reopening a question rechecks its evidence.

## Run locally

Prerequisites are Node 20+ and Filang's Rust toolchain. From the checkout root:

```sh
node study/prepare.mjs /path/to/sfd-language-lab
cargo build --release --locked --offline
node study/serve.mjs
```

Open [the query workspace](http://127.0.0.1:8764/). An optional port argument
sets a different local origin. `FILANG_STUDY_DATA` and `FILANG_STUDY_BIN` select
a data directory and Filang binary. The prior lab's URLs and saved library work
with this service on the same origin. The preparation command checks the
recorded assets against their SHA-256s before installing them under the ignored
`data/study/` directory. It does not copy code from the prior lab.

To rebuild the assets without the original lab, use Limen and Composer
checkouts containing the commits in [provenance](data-provenance.json) and
[Composer source](composer/SOURCE.md). In a Python environment with Polars
1.42.1 and PyArrow 23.0.1, run:

```sh
python study/prepare_recording.py --limen /path/to/Limen --composer /path/to/Composer
```

Both preparation methods install the same observed January–May 2025 Binance
BTCUSDT 15-minute recording and the Composer encodings of that tape.

## Study a failed break

Choose **New question → Prior range reclaim** in the builder. This finds 842
same-candle reclaims of the prior four-hour low on the recorded 15-minute tape.
Add **Wick or body share** to keep the 312 with a lower wick of at least half
the range. Add **Range versus recent median** to see the 126 whose range is at
least 1.5 times the prior median. **Close return** adds an outcome column.

```text
on BTCUSDT 15m
find breach_reclaim(prior_low(over: 4h))
where candle_share(lower_wick, min: 50%)
where range_multiple(over: 4h, min: 1.5)
measure close_return(after: 1h)
```

Select a case to see the breach close, first reclaim close, and the frozen
level on its chart. Setting `within_min: 1, within_max: 3` and removing the
two filters gives 432 reclaims at the next one to three closes. Switching to
`prior_high(over: 4h)` gives 454. The first delayed low reclaim pierced
93,578.77 on the candle ending at 05:00 UTC and recovered at 05:15 UTC on
2025-01-01.

**Compare candle prices** lets you choose endpoints and candle offsets. For
example, a close above the previous high and within 0.25% of the preceding
four-hour high gives 1,682 cases.

```text
on BTCUSDT 15m
find candle_relation(price(close), right: price(high, bars_ago: 1))
where near_level(prior_high(over: 4h), point: price(close), within: 0.25%)
```

In the bundled Composer, mark endpoint relationships or candle directions in
**Pins**, then choose **Use pins on fixed candles**. Filang compares the
explicitly pinned endpoints and directions over consecutive recorded candles
ending at each candidate close. Other relationships may vary. The draw search
retains its skeleton and stretch settings. **Use exact G1** queries the
complete ordinal geometry.

Upload [the example event](examples/long_wick_reclaim.v1.json) under **Agent
definitions** to add the 126-case composition to **New question**. Each custom
event has typed parameters, versioned dependencies, and recorded conformance
cases. The definition travels with saved links that use it.

## Named patterns

```text
on BTCUSDT 15m
find hammer or engulfing
where weekday(nyse_regular) = fri
group by completed_trend(frame: 4h)
measure close_return(after: [1h, 4h])
```

Running `node study/cli.mjs question.filang` evaluates the same text from a file
and returns the resolved candidates, cohorts, occurrences, and outcome cells
as JSON. The browser also supports the Friday-close study, custom wick ratios,
range comparisons, pattern conjunctions, and saved question replay.

The [execution contract](native/README.md) describes the checked plan,
close-time semantics, and the boundary between studies and discovery sweeps.

## Verify

```sh
npm --prefix study run verify
node study/verify/native.mjs
node study/verify/candle-native.mjs
```

With a running service, Playwright available, and a Chrome binary, run
`node study/verify/journey.mjs`, `node study/verify/builder-browser.mjs`, and
`node study/verify/candle-browser.mjs`.
Set `PLAYWRIGHT_MODULE` and `CHROME_PATH` to use an existing installation.
