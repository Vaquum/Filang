# The Query bench on the shared engine

The Query bench used to run the JavaScript reference engine of `study/src`
in the page. With this change it asks the shared Filang engine everything
and carries no engine of its own. This report records two attempts: that
the bench's answers did not change, and that the bench did not get slower.

Baseline: `main` at `9671214d129f3265a3ecfa17260bafd0e9475247`. Engine:
release `0.10.0.post21`, cut from that same commit, and a local build of
it (`python3 bindings/build.py --only browser`). Recording: the pinned
BTCUSDT 15m recording, 14,496 bars, SHA-256
`21df2ed15f787479b3e871be0048b5721cd18e7e085881e4175975c8d056889a`.

Nothing was recorded in a pull request before the runs. The criteria were
fixed before measuring: every figure the same, and no action slower.

## A1: the answers

`query/verify/parity.mjs` writes every question the bench's vocabulary can
write, asks it of both engines, and requires each figure the bench draws
from the answer to be equal.

```sh
python3 bindings/build.py --only browser
node query/verify/parity.mjs --timing --reasons
python3 bindings/fetch_browser.py 0.10.0.post21 --out /tmp/filang-engine
FILANG_QUERY_ENGINE_DIR=/tmp/filang-engine node query/verify/parity.mjs
```

| | Local build | Release 0.10.0.post21 |
| --- | ---: | ---: |
| Questions | 164 | 164 |
| Runs (compared values included) | 172 | 172 |
| Rows, each with its slot, time and first failing line | 1,406,176 | 1,406,176 |
| Line verdicts | 1,342,476 | 1,342,476 |
| Outcomes, status and value | 2,813,735 | 2,813,735 |
| Differences | 0 | 0 |

Also equal, for every run: pattern closes and unknowns, closes left after
each line, verdict totals per line, columns, groups with their labels and
members, the summary of the answer (observed, positive, median, mean to the
last bit), the count the bench shows for a change, the reclaim level and
breach, a line's verdict and a group's key at sampled closes outside the
answer, every named candle at every slot, and the New York clock. Six
questions that do not check are refused by both. The bar arrays the charts
draw are equal to the reference recording slot for slot.

The corpus: the four starting questions; all 24 named candles; reclaims,
breakouts, candle relations and the wick rejection across their values; 44
conditions each affirmed and negated on every close; several lines at once,
a muted line, both joins, three groups, compared values on one and two
axes, seven horizons, no measure, drawn shapes in both readings, held
relations, and a `let`.

Explanations are text, and wording is the engine's. Of 4,263 sampled
explanations 2,261 read the same. The rest state the same figures in other
words: a lower-case first letter, `1d` for `24h`, a trend without the
expression's own text, and a named candle's observed prices without its
rule. `--reasons` lists each kind once.

`query/verify/handoff.mjs` (324, 1,463, 772 and 4,828, and 1,200 recorded
windows drawn as chains) and `query/verify/cube-source.mjs` (16 checks)
pass on both packages.

## A2: speed

Both benches were served from this machine and driven in the same browser,
one tab each, 1440 by 900, the inspector open, each tab in front while it
was measured. One cycle: switch the window (fetch the bars, load them, and
answer the question on screen), open the four starting questions, step the
inspector to three closes, and open the list of conditions to add. Every
cycle starts from another window, so nothing is answered from a cache.
Nine cycles a round, the first dropped, medians of the rest. Times are the
synchronous cost of the action in the page, drawing included; the window
switch is timed to the first answer. Page load is timed in a fresh frame
to the first answer, eight loads, the first dropped.

Machine: Apple M1 Max, 10 cores, macOS 26.6.2, Chromium 156 (the Claude
desktop browser). Other work was running: load averages 7 to 13. The
rounds alternate so that drift falls on both.

| Action, ms | `main` round A | `main` round B | This change, local build, round 1 | round 2 | This change, release 0.10.0.post21 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Window switch to first answer | 102.6 | 103.6 | 64.9 | 64.4 | 63.4 |
| Four cold questions | 59.5 | 71.8 | 51.9 | 57.5 | 52.2 |
| Inspector, first close | 670.5 | 715.4 | 130.6 | 129.5 | 123.1 |
| Inspector, each next close | 130.7 | 133.0 | 42.8 | 43.6 | 40.2 |
| Conditions to add | 29.4 | 34.9 | 26.2 | 26.3 | 23.8 |
| Page load to first answer | | 227 | 132 | | 115 |

Order of the runs: the first version described below, `main` A, the fix,
local 1, `main` B, local 2, release.

Samples, in cycle order (ms):

- `main` A: window 119 117 85 97 80 95 128 103 116; questions 67 59 58 59
  63 58 65 59 91; first close 728 658 660 671 655 652 703 728 929; next
  close 119 119 122 169 123 138 117 196 131; conditions 40 29 29 29 29 33
  25 54 30.
- `main` B: window 222 101 127 138 152 82 99 81 104; questions 75 75 66 71
  75 74 67 72 68; first close 886 747 715 693 749 696 677 717 674; next
  close 206 128 134 155 131 132 135 133 132; conditions 25 28 29 33 27 36
  35 35 35; page load 489 205 211 227 217 235 358 387.
- Local 1: window 75 65 75 59 65 59 65 68 100; questions 85 51 50 47 48 52
  54 54 59; first close 137 133 129 131 127 130 134 140 129; next close 47
  43 41 43 41 43 45 46 43; conditions 27 26 26 26 26 26 27 27 26; page
  load 292 242 155 114 132 138 117 124.
- Local 2: window 114 64 61 73 58 69 66 63 62; questions 135 60 56 55 54
  58 56 58 58; first close 197 138 134 127 130 126 129 128 133; next close
  50 47 42 43 44 43 44 43 45; conditions 26 26 26 26 27 26 26 26 26.
- Release: window 94 62 68 97 58 62 146 63 63; questions 89 51 51 59 46 51
  57 52 55; first close 139 120 132 123 121 121 123 119 123; next close 41
  44 43 40 39 40 40 39 40; conditions 25 25 24 24 23 24 23 24 23; page
  load 136 145 113 115 113 113 128 143.

### What was slower first

The first version of this change measured 86.5 ms for the four cold
questions against 59.5 ms on `main` (samples 88 86 83 81 85 87 93 87 91),
with every other action already faster. The cause was in the bench, not the
engine: it sorted the outcomes of all 14,496 closes again on every redraw
to compare a row with all closes, where the reference engine kept that
summary with its answer. The summary is now kept with the answer, and the
answer and its groups are kept once computed. The table above is after
that fix.

An earlier round is discarded and not in the table: the `main` tab was
measured in the background on its first runs, which gave 373 ms for the
four questions and 1,252 ms for the first close.

### What the page downloads

| | `main` | This change |
| --- | ---: | ---: |
| Requests to the first answer | 34 | 20 |
| Engine files | 17 | 2 |
| Engine bytes | 191,388 | 952,564 |
| Engine bytes, gzip -9 | about 110,500 | about 309,000 |

The engine is 761 KB larger to download, about 198 KB larger compressed,
and the server sends every response with `Cache-Control: no-store`, so it
is fetched on every page load. On this machine the page still reaches its
first answer sooner. A cold load over the network to `query.vaquum.fi` was
not measured.

### In Node

One pass of the whole corpus with every row read, as a side measurement of
the engines without the page: reference 4.9 to 5.2 s, shared engine 2.7 to
3.1 s (`node query/verify/parity.mjs --timing`, four runs).

### The timing script

Run in each bench's page, with the bench served beside a cube stand-in
(`node query/verify/cube-source.mjs --serve 8798`, then
`CUBE_URL=http://127.0.0.1:8798 node query/serve.mjs`):

```js
async function cycles() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const key = (k) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  const enc = (name) => [...document.querySelectorAll('#encbar .enc')].find((b) => b.innerText.toUpperCase().startsWith(name.toUpperCase()));
  const option = async (name, text) => { enc(name).click(); await sleep(20); return [...document.querySelectorAll('.pop [role=menuitemradio]')].find((b) => b.innerText.includes(text)); };
  const timed = (fn) => { const t = performance.now(); fn(); return performance.now() - t; };
  const QUESTIONS = ['Hammers by 4h trend', 'Quiet Friday close', 'Breakout with the trend', 'Failed break of the prior low'];
  const out = { window: [], questions: [], first: [], next: [], conditions: [] };
  for (let c = 0; c < 9; c++) {
    const pinned = document.getElementById('chip').textContent.includes('pinned recording');
    const o = await option('Window', pinned ? 'Last 180 days' : 'Pinned recording'); const t0 = performance.now(); o.click();
    const want = pinned ? 'cube, through' : 'pinned recording';
    while (!(document.getElementById('chip').textContent.includes(want) && /ms ·/.test(document.getElementById('status').textContent))) await sleep(2);
    out.window.push(performance.now() - t0);
    let sum = 0; for (const q of QUESTIONS) { const b = await option('Question', q); sum += timed(() => b.click()); await sleep(30); }
    out.questions.push(sum);
    out.first.push(timed(() => key('.'))); await sleep(30);
    out.next.push((timed(() => key('.')) + timed(() => key('.'))) / 2); await sleep(30);
    key('Escape'); await sleep(30);
    const add = document.getElementById('add'); out.conditions.push(timed(() => add.dispatchEvent(new Event('focus')))); await sleep(30); add.dispatchEvent(new Event('blur')); await sleep(30);
  }
  return out;
}
async function loads() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms)); const times = [];
  for (let i = 0; i < 8; i++) {
    const f = document.createElement('iframe'); f.style.cssText = 'position:fixed;left:0;top:0;width:1440px;height:900px;opacity:0.01;pointer-events:none;border:0'; f.src = '/#w=pinned';
    const t0 = performance.now(); document.body.append(f);
    while (!/ms ·/.test(f.contentDocument?.getElementById('status')?.textContent || '')) await sleep(2);
    times.push(performance.now() - t0); f.remove(); await sleep(150);
  }
  return times;
}
```
