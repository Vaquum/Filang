# CHAIN-G1: reading a shape's later opens as the previous close

Status: **protocol only. Nothing below has been run.** The result is added to this file when the experiment is done; the
protocol section is not edited afterwards except to record deviations under their own heading.

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
