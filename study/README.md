# Filang query workspace

Compose a question from the typed builder or the formal editor. Choose a named
candle pattern in English or Japanese, combine same-close events, add filters
or a grouping, compare parameter values, and inspect the recorded closes and
outcomes. **Explore in Composer** opens the matching named rule or drawing.
Drawings return to the builder as oldest-first exact G1. **Agent definitions**
accepts versioned, tested compositions. Saved links pin the input data, exact
definitions and evidence. Reopening a question rechecks its evidence.

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

## Example

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
```

With a running service, Playwright available, and a Chrome binary, run
`node study/verify/journey.mjs` and `node study/verify/builder-browser.mjs`.
Set `PLAYWRIGHT_MODULE` and `CHROME_PATH` to use an existing installation.
