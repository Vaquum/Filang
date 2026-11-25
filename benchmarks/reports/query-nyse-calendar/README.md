# Query's NYSE calendar from field-data-api

Results record for the change that asks Query's cube windows with a `nyse_regular`
table from Vaquum's field-data-api instead of the engine's pinned table. Two
attempts, both measured on 2026-11-25:

- **A1** built the table in Query from field-data-api's NYSE closures and early
  closes, with a weekday and 16:00 rule of Query's own. It resolved recent
  windows but lost Jan–May 2025 and everything before 2026-10-23. Its hypothesis
  was written before the code and the runs.
- **A2** reads the sessions field-data-api now publishes itself, `nyse_sessions`
  (Vaquum/field-data-api#23, merged in #24 as `a93386e`). Query keeps no rule.
  Its criteria were set in that issue before the dataset existed. The A2 record
  was written after the measurement. See [A2](#a2-sessions-published-by-field-data-api).

## A1: exceptions from `/v1/calendar`, rule in Query

### What field-data-api holds

field-data-api (Vaquum/field-data-api, the service Cube reads its calendar from)
serves one supplied calendar at `/v1/calendar`. Its NYSE content is exceptions
only: category `market_holiday`, `context.source_id` `NYSE`, 12 full-day
closures ("NYSE markets closed — …", date records) and 3 early closes ("NYSE
early close — …", instants at 13:00 New York). Its declared civil-date scope is
2026-10-23 through 2027-12-31 (`meta.input_metadata.source_scope_*`), imported
from a research handoff whose file SHA-256 is `7b10dd35…9b5f69`. It holds no
NYSE days before 2026-10-23 and no session table.

Query therefore builds the engine's table (`query/calendar.mjs`) inside that scope
only: a New York weekday the service does not list as closed is a regular
session, closing at 16:00 New York unless it lists an early close. Days outside
the scope stay outside the table, so the engine answers `unknown` there with its
own reason. No date is written in Query.

### Protocol

1. **The table.** A local field-data-api at its current checkout
   (`bcfe9ee`, SQLite backend, every provider disabled, `config/calendar.supplied.json`,
   the file production's `config/server.json` selects) was published once
   (`worker --once`) and served. `node query/verify/calendar.mjs --print http://127.0.0.1:8591`
   gave table `field-data-api.nyse.ce29cc35640c72e4`: calendar revision
   `ce29cc35640c72e4…`, 299 sessions, coverage 2026-10-23T04:00Z to 2028-01-01T05:00Z
   (end exclusive), text SHA-256 `9ec40366a6fdf6cf…98401f`.
2. **Independent check of the days.** The table's closures and early closes were
   compared with NYSE's own page, nyse.com/trade/hours-calendars, read the same
   day. NYSE lists for the scope: closed 2026-11-26, 2026-12-25, 2027-01-01,
   2027-01-18, 2027-02-15, 2027-03-26, 2027-05-31, 2027-06-18, 2027-07-05,
   2027-09-06, 2027-11-25, 2027-12-24; early close at 1:00 p.m. ET on 2026-11-27,
   2026-12-24 and 2027-11-26; core session 9:30 a.m. to 4:00 p.m. ET.
3. **Production bars and engine.** In the signed-in Query page at
   query.vaquum.fi (engine 0.10.0.post32), [`measure.js`](measure.js) loaded each
   window's bars from production `/bars` into a fresh engine and counted
   `[true, false, unknown]` closes for `weekday(nyse_regular) = fri` and
   `session_tail(nyse_regular, last: 1h)` on every close (event
   `candle_relation(price(high), is: at_or_above, right: price(low))`), first with
   the pinned table (the production baseline), then with the table from step 1.
   The page rebuilt the table's text from a compact copy and its SHA-256 matched
   step 1 before use.
4. **Unchanged answers.** `query/verify/{handoff,cube-source,calendar,dimensions,parity}.mjs`
   on the pinned recording, on 0.10.0.post32 and on the local build.

No outcome or return was measured. The quantities are which closes the
calendar conditions can decide, so no market outcome was exposed by this test.

### Results

The NYSE check (step 2) agrees on every day: the same 12 closures and 3 early
closes, and 16:00/09:30 as the regular close and open.

Production bars, `[true, false, unknown]` closes:

| Window | Bars | Closes before 2026-10-23 NY | Pinned table: Friday | field-data-api: Friday | Pinned table: last 1h | field-data-api: last 1h |
| --- | --- | ---: | --- | --- | --- | --- |
| Last 30 days | 2026-10-26 08:30 → 2026-11-25 08:30, 2,880 rows, sha256 `e323f720802bf0bf…` | 0 | 0 · 0 · 2,880 | 384 · 2,496 · **0** | 0 · 0 · 2,880 | 88 · 2,792 · **0** |
| Last 180 days | 2026-05-29 08:30 → 2026-11-25 08:30, 17,280 rows, sha256 `9da9df2c0e995dac…` | 14,093 | 0 · 0 · 17,280 | 480 · 2,707 · 14,093 | 0 · 0 · 17,280 | 92 · 3,095 · 14,093 |
| Last 12 months | 2025-11-25 08:45 → 2026-11-25 08:45, 35,040 rows | 31,852 | 0 · 0 · 35,040 | 480 · 2,708 · 31,852 | 0 · 0 · 35,040 | 92 · 3,096 · 31,852 |
| This year | 2026-01-01 → 2026-11-25 08:45, 31,523 rows | 28,335 | 0 · 0 · 31,523 | 480 · 2,708 · 28,335 | 0 · 0 · 31,523 | 92 · 3,096 · 28,335 |
| Last year | 2025-01-01 → 2026-01-01, 35,040 rows | 35,040 | 2,016 · 12,476 · 20,548 | 0 · 0 · **35,040** | 408 · 14,081 · 20,551 | 0 · 0 · **35,040** |
| All history | 2021-01-01 → 2026-11-25 08:30, 206,738 rows, sha256 `64e8f3beca6c8092…` | 203,551 | 2,016 · 12,476 · 192,246 | 480 · 2,707 · 203,551 | 408 · 14,081 · 192,249 | 92 · 3,095 · 203,551 |

The Last 12 months and This year rows were read about 15 minutes after the
others, one bar later; their "before" count is the unknown count, not separately
tallied.

- Inside the table every close is decided. Last 30 days goes from 2,880 unknown
  to none. In Last 180 days the unknowns are exactly the 14,093 closes before the
  scope starts.
- The counts are what the calendar predicts: four Fridays in Last 30 days times
  96 closes is 384, and 22 sessions times the four 15-minute closes of the last
  hour is 88. Last 180 days adds Friday 23 October: 480 and 92.
- **Negative finding.** The pinned table covers New York dates 2025-01-01 to
  2025-06-01. On Last year and All history it decided 14,492 closes that
  field-data-api cannot decide, because it holds nothing before 2026-10-23. Those
  windows lose them: Last year goes from 20,548 unknown to all 35,040.
- `query/verify/*.mjs` pass on 0.10.0.post32 and on the local build. The pinned recording
  keeps the pinned table and its answers (`2,016 · 12,461 · 19` for Friday).

### Reproduce

A1's reader is the one at commit `e62e81a` (`git show e62e81a:query/calendar.mjs`,
and its check `git show e62e81a:query/verify/calendar.mjs`); A2 replaced both.

```sh
# field-data-api, locally, with its supplied calendar and no providers (see its docs/operations.md)
python3 -m field_data_api --config <config with every source disabled> init-store
python3 -m field_data_api --config <same> worker --once
python3 -m field_data_api --config <same> serve
# the table Query builds from it
node query/verify/calendar.mjs --print http://127.0.0.1:<port>
# the contract checks
node query/verify/calendar.mjs
```

Then paste [`measure.js`](measure.js) into the Query page and call
`measure(tsv, table)`.

## A2: sessions published by field-data-api

### What changed

field-data-api publishes `GET /v1/data/nyse_sessions` (projection
`market_sessions/1`): one record per NYSE session day with its New York date,
weekday, open and close, complete over New York dates 2021-01-01 to 2028-01-01
(end exclusive). Its 69 closures and 13 early closes are dated assertions with
NYSE or ICE sources. Its tests check every year against `exchange_calendars`
4.13.3 XNYS, the 2025 rows against Filang's pinned table, and late 2026–2027
against the supplied calendar. A disagreement fails publication.

`query/calendar.mjs` pins one publication, reads every page under it and
rewrites each record into the engine's row: New York midnight of the date, the
record's close, the record's weekday. It refuses records outside coverage, out
of order, on a weekday other than their date's, or closing outside their day.

### Protocol

1. **The table.** field-data-api at the merged head (PR #24 head `a036a6d`, the
   same tree as `a93386e`) ran locally: SQLite, every provider disabled,
   `worker --once`, `serve`. `node query/verify/calendar.mjs --print` gave table
   `field-data-api.nyse_sessions.18f5b91391ce4ed4`: 1,757 sessions, 13 early
   closes, 69 closures, revision `18f5b913…`, text SHA-256 `018cea35…eeafb0`.
2. **Against the pinned table.** All 102 rows of `nyse-core-2025-01-05-v1`
   (`study/catalogue/nyse.tsv`) appear byte for byte in the new text.
3. **Production bars and engine.** Same as A1 step 3: the signed-in Query page,
   engine 0.10.0.post32, production `/bars`, a fresh engine, the pinned table and
   then the new one. The page rebuilt the text and its SHA-256 matched step 1.
4. **Unchanged answers.** `query/verify/*.mjs` on the local build and on
   0.10.0.post32. The calendar check covers the new contract against a stand-in.

### Results

`[true, false, unknown]` closes; "before" counts closes before 2021-01-01 00:00 New York.

| Window | Bars | Before | Pinned table: Friday | nyse_sessions: Friday | Pinned table: last 1h | nyse_sessions: last 1h |
| --- | --- | ---: | --- | --- | --- | --- |
| Last 30 days | 2026-10-26 09:00 → 2026-11-25 09:00, 2,880 rows, sha256 `c697d82186d885d5…` | 0 | 0 · 0 · 2,880 | 384 · 2,496 · **0** | 0 · 0 · 2,880 | 88 · 2,792 · **0** |
| Last 180 days | 2026-05-29 09:00 → 2026-11-25 09:00, 17,280 rows, sha256 `7ed3493535e3e3f0…` | 0 | 0 · 0 · 17,280 | 2,283 · 14,997 · **0** | 0 · 0 · 17,280 | 500 · 16,780 · **0** |
| Last 12 months | 2025-11-25 09:00 → 2026-11-25 09:00, 35,040 rows | 0 | 0 · 0 · 35,040 | 4,704 · 30,336 · **0** | 0 · 0 · 35,040 | 1,004 · 34,036 · **0** |
| This year | 2026-01-01 → 2026-11-25 09:00, 31,524 rows | 0 | 0 · 0 · 31,524 | 4,224 · 27,300 · **0** | 0 · 0 · 31,524 | 904 · 30,620 · **0** |
| Last year | 2025-01-01 → 2026-01-01, 35,040 rows, sha256 `3ba3076031d29cf5…` | 0 | 2,016 · 12,476 · 20,548 | 4,800 · 30,240 · **0** | 408 · 14,081 · 20,551 | 1,000 · 34,040 · **0** |
| All history | 2021-01-01 → 2026-11-25 09:00, 206,740 rows, sha256 `4be1656e5d7836a8…` | 19 | 2,016 · 12,476 · 192,248 | 28,485 · 178,236 · **19** | 408 · 14,081 · 192,251 | 5,924 · 200,797 · **19** |

- Every window is decided at every close except All history's first 19, which
  close before New York's 2021-01-01 begins, where the service declares nothing.
- The counts follow the calendar: Last year has 50 Friday sessions × 96 closes
  (4,800) and 250 sessions × 4 last-hour closes (1,000). Good Friday and 4 July
  2025 fell on Fridays. Last 180 days starts at 09:00 UTC on a Friday, so that
  day contributes 75 closes: 23 × 96 + 75 = 2,283.
- On the stand-in cube (the pinned recording's bars) the new table decides all
  14,496 closes. The pinned table left 19 unknown; both give 2,016 Friday closes.
- `query/verify/*.mjs` pass on both engines.

### Reproduce

As for A1, with field-data-api at `a93386e` or later and `measure(tsv, table)`
on the text `node query/verify/calendar.mjs --print` gives.

