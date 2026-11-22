# CHAIN-G1: reading a shape's later opens as the previous close

Status: **run on 2026-11-22.** Everything from "Why" to "Prior exposure" is the protocol as it was committed before
the event existed and before anything was run (commit `9f2d5a1`). The result and the deviations follow it.

## Why

A drawn shape is a chain: every bar after the first opens where the previous bar closed. `exact_g1` reads recorded
opens and compares ties exactly, so a recorded window matches a chained shape only if each later open equals the
previous close to the cent. On the pinned recording that holds for about half of adjacent bars; the rest differ by a
cent of tick noise. The decision taken on 2026-11-22 is that a shape reads later opens as the previous close. This
experiment adds that reading as a new event, `chained_g1`, beside `exact_g1`, and asks whether the windows the old
reading kept were a fair sample of the ones the new reading finds.

## The reading (`chained_g1`)

For a window of n bars ending at the anchor close, all present and consecutive:

- The first bar is read as recorded: open, high, low, close.
- Every later bar opens at the close of the recorded bar just before it. Its body runs from that open to its own close.
  Its low is the lower of its recorded low and that open; its high is the higher of its recorded high and that open.
  Its direction is up when it closes above that open, down when below, and a doji (`z`) when equal.
- The window's g1 code is the dense ranking of all its endpoints read this way, with equal prices sharing a rank,
  exactly as `exact_g1` ranks them. An incomplete window is unknown, as for `exact_g1`.
- A one-bar shape has no later bar, so `chained_g1` and `exact_g1` agree on every one-bar code.

The recording is not changed. `exact_g1` is not changed.

## Hypothesis

On the pinned BTCUSDT 15m recording, the windows that match a chained two-bar shape as recorded are not
outcome-selected among the windows that match it under the chained reading: the share of matches whose close one hour
after the anchor close is above the anchor close is the same among the as-recorded matches (`exact_g1`) and among the
matches that only the chained reading adds (`chained_g1` and not `exact_g1`).

## Scope, data and endpoint

- **Data.** `data/study/recorded-bars.csv` as recreated by `study/prepare_recording.py`: BTCUSDT 15m, 2025-01-01 to
  2025-05-31 UTC, 14,496 closes, SHA-256 `21df2ed15f787479b3e871be0048b5721cd18e7e085881e4175975c8d056889a`.
- **Splits.** None. The two groups are disjoint sets of windows of the same recording, and nothing is fitted or tuned.
- **Shapes.** Oriented two-bar g1 codes. Windows are coded under the chained reading and the 20 codes with the most
  matches are taken, ties broken by code text. A code is tested only if each group has at least 100 matches with a
  known one-hour outcome.
- **Endpoint.** `close_return(after: 1h)` at the anchor close, as the engine computes it. A match is "up" when the
  return is above zero; a zero return is not up; a match with an unknown outcome is left out of both groups.

## Decision criterion (fixed before the run)

- Per tested code: a two-sided two-proportion z-test of the up share, added-only against as-recorded, at 0.05,
  with no correction for the number of codes.
- Pooled: the inverse-variance weighted mean of the per-code differences in up share (added-only minus as-recorded),
  with its 95% interval (mean ± 1.96 standard errors).
- **Supported** if the pooled interval includes zero and at most 2 tested codes differ at 0.05.
- **Not supported** if the pooled interval excludes zero.
- **Inconclusive** otherwise, and also if fewer than 5 codes meet the size requirement.

## Method (planned)

1. Add `chained_g1` to the study engine in JavaScript and, if it fits the native evaluator without changing
   `src/geometry.rs`, natively with parity entries in `study/verify/native.mjs`. If it does not fit, the native
   compiler refuses it as it refuses other browser-only events, and that refusal is asserted.
2. `study/verify/chained-g1.mjs` codes every two-bar window under the chained reading with its own implementation,
   independent of the engine's, and ranks the codes.
3. For each of the 20 codes it asks the engine for `exact_g1(code)` and `chained_g1(code)`, and requires that the
   engine's chained matches equal its own, and that every as-recorded match is also a chained match.
4. It reads each match's one-hour outcome from the engine, applies the criterion above, and writes `results.json`
   beside this file. The table and the conclusion are then added here.

Not part of the hypothesis, reported as description: the number of matches of each tested code under both readings,
and the share of n-bar windows whose code is the same under both readings for n from 2 to 5.

## Prior exposure

- On 2026-11-22, before this protocol was written, an exploratory script counted matches under both readings on this
  same recording. It found that a later open equals the previous close in 52.5% of adjacent bars and differs by one
  cent in 45.2%; that one two-bar code had 772 matches as recorded (the engine's own count) and 1,463 chained, and
  another 49 and 91; that the most common three-bar chained code had 95 as recorded and 287 chained; and that 8.0% of
  five-bar windows keep their code. These counts motivated the change. They are not evidence for the hypothesis and
  are not preregistered.
- Outcomes after the anchor close were not looked at for any of these groups before this protocol was written.
- The recording itself has been used by the workspace's verification scripts throughout, so it is not untouched data.

## Result

**Supported.** The pooled interval includes zero and no tested code differs at 0.05.

- **Tested.** 14 of the 20 codes met the size requirement. The other six had a group with fewer than 100 observed outcomes and were not tested, as the protocol says.
- **Per code.** 0 of 14 differ at 0.05. The smallest p-value is 0.092; the largest difference in either direction is 9.0 points.
- **Pooled.** The added-only matches closed higher after one hour +0.46 points more often than the as-recorded matches, with a 95% interval from -1.79 to +2.71 points (standard error 1.15).
- **By the criterion:** supported needs an interval that includes zero and at most 2 differing codes; both hold.

| # | Code | Chained | As recorded | Up, added only | Up, as recorded | Difference, points | p |
|---|---|---|---|---|---|---|---|
| 1 | `g1:o:0,1,3,4,u;2,3,5,6,u` | 1,463 | 772 | 45.9% of 691 | 48.2% of 772 | -2.3 | 0.377 |
| 2 | `g1:o:2,3,5,6,d;0,1,3,4,d` | 1,440 | 765 | 55.9% of 675 | 53.3% of 765 | +2.5 | 0.338 |
| 3 | `g1:o:0,1,4,5,u;2,3,4,6,d` | 633 | 349 | 54.1% of 283 | 47.9% of 349 | +6.2 | 0.120 |
| 4 | `g1:o:1,2,5,6,d;0,2,3,4,u` | 597 | 325 | 47.2% of 271 | 54.2% of 325 | -6.9 | 0.092 |
| 5 | `g1:o:2,3,4,6,u;0,1,4,5,d` | 562 | 290 | 51.5% of 272 | 54.7% of 289 | -3.2 | 0.448 |
| 6 | `g1:o:0,2,3,4,d;1,2,5,6,u` | 503 | 269 | 51.3% of 234 | 49.4% of 269 | +1.8 | 0.681 |
| 7 | `g1:o:1,3,5,6,d;0,2,3,4,d` | 341 | 186 | 58.1% of 155 | 49.5% of 186 | +8.6 | 0.113 |
| 8 | `g1:o:0,1,3,5,u;2,3,4,6,u` | 338 | 155 | 47.5% of 183 | 48.4% of 155 | -0.8 | 0.877 |
| 9 | `g1:o:2,3,4,6,d;0,1,3,5,d` | 326 | 178 | 50.0% of 148 | 59.0% of 178 | -9.0 | 0.104 |
| 10 | `g1:o:0,2,3,4,u;1,3,5,6,u` | 308 | 153 | 40.6% of 155 | 48.4% of 153 | -7.7 | 0.173 |
| 11 | `g1:o:0,1,4,6,u;2,3,4,5,d` | 302 | 144 | 53.8% of 158 | 45.8% of 144 | +8.0 | 0.167 |
| 12 | `g1:o:0,2,5,6,d;1,2,3,4,u` | 284 | 150 | 54.5% of 134 | 48.0% of 150 | +6.5 | 0.276 |
| 13 | `g1:o:1,2,3,4,d;0,2,5,6,u` | 249 | 127 | 47.1% of 121 | 40.9% of 127 | +6.2 | 0.328 |
| 14 | `g1:o:0,1,2,3,u;2,2,4,5,u` | 222 | 108 | 50.9% of 114 | 45.4% of 108 | +5.5 | 0.412 |
| 15 | `g1:o:2,3,4,5,u;0,1,4,6,d` | 211 | 118 | 48.4% of 93 | 44.1% of 118 | not tested | group of 93 |
| 16 | `g1:o:1,2,3,6,d;0,2,4,5,u` | 201 | 121 | 52.5% of 80 | 60.3% of 121 | not tested | group of 80 |
| 17 | `g1:o:2,3,4,5,d;0,1,3,3,d` | 199 | 99 | 42.0% of 100 | 46.5% of 99 | not tested | group of 99 |
| 18 | `g1:o:0,2,4,5,u;1,3,4,6,d` | 185 | 100 | 60.0% of 85 | 52.0% of 100 | not tested | group of 85 |
| 19 | `g1:o:1,2,4,6,d;0,2,3,5,u` | 172 | 78 | 52.1% of 94 | 48.7% of 78 | not tested | group of 78 |
| 20 | `g1:o:1,3,4,6,u;0,2,4,5,d` | 163 | 79 | 50.0% of 84 | 49.4% of 79 | not tested | group of 79 |

"Added only" is the chained matches that are not as-recorded matches. Shares are of matches with an observed
one-hour outcome; four matches in all were left out because the hour ran past the end of the recording.

### What the test could and could not have detected

- A per-code test here has a standard error of about 5.5 points on the difference (median over the tested codes), so one
  code alone could only have shown a difference of roughly 11 points or more. No code came near that being significant.
- The pooled estimate is tighter: it rules out the as-recorded matches being outcome-selected by more than about
  2 to 3 points in either direction on this recording. A smaller selection than that would not have been seen.
- It is one instrument, one timeframe, five months, one horizon, two-bar shapes, and the most common codes only.
  It says nothing about rarer shapes, longer shapes, other horizons or other periods.
- "Supported" here means no evidence of selection at this resolution. It does not show the two groups are the same.

### Description (not part of the hypothesis)

Matches of each tested code under both readings are in the table above. Across the 20 chosen codes the chained
reading finds 8,699 matches. The share of windows whose code is the same under both readings:

| Bars | Windows | Same code | Share |
|---|---|---|---|
| 2 | 14,495 | 7,607 | 52.5% |
| 3 | 14,494 | 3,994 | 27.6% |
| 4 | 14,493 | 2,143 | 14.8% |
| 5 | 14,492 | 1,155 | 8.0% |

These repeat the exploratory counts listed under "Prior exposure" (52.5% for two bars, 8.0% for five; 772 and 1,463
for code 1) and are not new evidence.

Beyond the protocol's list, about the reading itself and not about outcomes:

- Of 14,495 adjacent pairs, the later open equals the previous close in 7,607; the previous close lies outside
  the later bar's recorded low to high in 189 (1.3%), which is where the low or high widens; and the bar's
  direction differs between the two readings in 6.
- Among the 8,699 chained matches of the 20 chosen codes, the second bar is widened in 76 (0.9%). None
  of the 20 codes has a doji bar.

### What was implemented and checked

- `chained_g1@1` in the JavaScript evaluator (`study/src/g1.js`, `engine.js`, `registry.js`) and in the native
  evaluator (`src/study/plan.rs`, `compute.rs`, wire op `g1c`), without changing `src/geometry.rs`. The two readings
  keep separate native keys. `exact_g1` and every count pinned on it are unchanged.
- `study/verify/geometry-study.js`: the two readings agree on all nine one-bar codes the recording holds (324 for
  `g1:o:0,1,2,2,u`); the engine's chained matches equal a separate scan written in the test, oriented and unoriented;
  an absent bar gives unknown; 772 as recorded and 1,463 chained for code 1.
- `study/verify/native.mjs`: 51 plans agree between the native and browser evaluators on timestamps, unknowns,
  cohorts, groups and outcomes, six of them chained, including a twelve-bar window and both readings in one plan.
- Found while verifying, outside this experiment's scope: with directions kept, every as-recorded match of a chained
  code is also a chained match, and the script requires it for all 20 codes. Without directions that does not hold:
  a recorded window can make the same tie between other body edges, and read as a chain it is a different shape.

## Deviations

None from the protocol's hypothesis, shape selection, endpoint, tests or thresholds. Three notes on how it was carried out:

- The protocol names a two-proportion z-test and an inverse-variance mean without their variance forms. The script,
  written before any outcome was read, uses the pooled-share variance for each code's test and each share's own
  variance for the weights. Both are in `results.json`.
- The native evaluator was implemented, so the refusal path the protocol allowed for was not needed.
- The experiment was run twice. The first run was made on the implementation before it was committed, and the result
  above was written from it. The script was then run again at the implementation's commit, `f695e32`, and produced
  the same file apart from the commit it names; `results.json` is from that second run. It records the working tree
  as changed because this report and `results.json` itself were not yet committed; no code differed from `f695e32`.

## Reproduce

The recording is recreated from its two pinned public sources exactly as the CI step "Filang query workspace and
native parity on recorded BTCUSDT" in `.github/workflows/ci.yml` does it, with `study/prepare_recording.py`. Then:

```sh
node study/verify/chained-g1.mjs      # writes results.json beside this file
node study/verify/geometry-study.js   # the reading, without outcomes
node study/verify/native.mjs          # native and browser evaluators agree
```
