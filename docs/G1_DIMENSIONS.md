# g1 dimensions — revision to the bar geometry contract (0.9 → 0.10)

**Status: contract revision, being implemented in stages.** The study engine and the Query language read
dimensions as written here. The Query bench, Composer and the Rust core follow in their own changes; until the
Rust core lands, sections 6 to 8 describe what it will do, and the native study worker refuses a code with a
dimension part. With the Rust core this text is folded into `BAR_GEOMETRY.md` and
`QUALITATIVE_GEOMETRY_ALGEBRA.md`, and this file is removed. Section 11 records the decisions taken on it.

## 1. What changes, in three sentences

g1 stays the global weak order of labelled points in a window, but the points now sit on separate **axes**,
and order is recorded only within an axis. Price is the axis g1 has today, with four points per candle; each
further axis is a **dimension** that can be switched on, with one point per candle. With every dimension off,
g1 is exactly what it is in 0.9: the same text, keys, counts, catalogues and results, at the same cost.

There is no second language and no new prefix. A 0.9 pattern is a 0.10 pattern.

## 2. The first dimensions

Cube already defines them. g1 takes Cube's keys and formulas unchanged, computed from the per-bar counters
Cube's bridge serves (`vol` USDT traded, `tbvol` taker-buy USDT, `cnt` trades).

| Key | Cube's label | Value of one candle | Unit | Reference point |
|---|---|---|---|---|
| `volume` | Volume | `vol` | USDT | none |
| `trades` | Trades | `cnt` | trades | none |
| `delta` | Delta | `2·tbvol − vol` (taker buys minus taker sells) | USDT | zero |
| `size` | Trade size | `vol / cnt` | USDT a trade | none |
| `imbalance` | Net taker imbalance | `(2·tbvol − vol) / vol` | −1 to +1 | zero |

Cube's *Taker flow* (`tbvol / vol`, midpoint 0.5) is the same dimension as `imbalance` on another scale:
`imbalance = 2·flow − 1` is strictly increasing, and g1 does not see a strictly increasing change of scale.
It is therefore not a sixth dimension.

Not in this first set, because bars do not carry what they need: taker trades and buyer/seller trade size
(need the taker-buy trade count, which only Cube's cells hold), path, dwell and choppiness (need the
within-bar path). They join by the same rule when the bars carry their counters.

## 3. Meaning

For a window of `n` candles and a dimension `d` that is on, let `x_1 … x_n` be the candles' values. The
dimension's part of the pattern is the weak order of those values: for every pair of candles, lower, equal
or higher. Where the dimension has a reference point, the reference takes part in the order as one more
point, so each candle is also below, at or above it. For `delta` and `imbalance` that is the side of the
tape: net selling, balanced or net buying.

- **No order across axes.** A volume is never compared with a price, a delta or a count. Nothing in the
  text, key or algebra can express such a comparison.
- **Invariance.** A strictly increasing change of one axis's scale leaves the pattern unchanged; with a
  reference point the change must keep the reference fixed.
- **One candle.** A dimension without a reference says nothing about a single candle (one state). With a
  reference it has three states.
- **Chained reading.** Reading later opens as the previous close changes price points only. A candle's
  dimension values are its own.
- **Exactness.** As for prices, equality is exact equality of the delivered values, with no tolerance.
  The counters are the 64-bit floats Cube's bridge delivers. A candle's value is the 64-bit float that the
  formula in section 2 gives when evaluated exactly as written: `2·tbvol − vol`, then the division where
  there is one, each operation rounded once and none fused. Order and equality are those of the resulting
  floats. Cube computes the same expressions the same way, so every implementation reaches the same bits.
- **Validity.** A value that does not exist (no counters in the recording; `size` with no trades;
  `imbalance` with no volume) makes the window invalid for every pattern that has that dimension on,
  whatever its price part says. Invalid is kept apart from false, as today. The same window stays valid
  for patterns that leave the dimension off. A recording whose counters are not finite and nonnegative,
  whose taker-buy amount exceeds its volume, or whose trade count is not whole is refused.

What this does and does not preserve: which candle traded most, whether volume rose through the window,
which side was the aggressor on each candle, whether the largest volume came with selling. Not how much
more, nor any ratio between candles. "Volume at least 1.5 times its recent median" is a threshold, and
thresholds stay where they are today, in the study language above g1 (section 9).

## 4. Text

```text
pattern        = price-part *( "|" dimension-part )
price-part     = the 0.9 grammar, unchanged ("g1:u:…" or "g1:o:…")
dimension-part = dimension ":" rank *( "," rank ) [ "/" rank ]
dimension      = "volume" | "trades" | "delta" | "size" | "imbalance"
```

- One rank per candle, in the candle order of the price part.
- `/rank` is the reference point's rank. It is present exactly when the dimension has a reference point.
- Ranks are dense from zero within the part, the reference included. They are not shared between parts.
- Parts appear in the order of the table in section 2, each at most once.
- Anything else is rejected, as malformed 0.9 text is.

A pattern with no dimension part is byte for byte a 0.9 pattern. Examples:

```text
g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1
g1:o:4,5,6,7,d;0,1,2,3,d|volume:0,1|delta:0,2/1
g1:o:0,1,2,3,u|delta:1/0
g1:u:0,1,2,3;0,1,2,3;0,1,2,3|volume:0,0,1|delta:2,0,1/1
```

The first is a down candle followed by a down candle wholly below it, on higher volume. The second adds
that the first candle was net selling and the second net buying (`0` is below the reference at `1`, `2` is
above it). The third is one up candle with net buying. The fourth is three candles with identical price
points whose first two volumes tie below the third, with net buying, net selling, then an exact balance.

## 5. On and off

A dimension is on in three places, and off means the same thing in each.

- **In a pattern.** A dimension is on when its part is present. A pattern says nothing about a dimension
  that is off: it matches every window that matches its other parts.
- **In a declared domain.** A bank declares its dimensions beside its mode (`dimensions=volume,delta`).
  The complete patterns of that bank fix the order on every declared axis. With the key absent or empty the
  bank is a 0.9 bank.
- **In the tools.** Composer and Query each show one switch per dimension. All off is today's Composer and
  today's Query.

Turning a dimension off is a projection (`forget_dimension`, section 8). So every pattern with dimensions
on is a refinement of its price-only pattern: its matches are a subset of that pattern's matches, and the
refinements of one price pattern on a declared set of dimensions partition its matches exactly. That gives
a search its control for free: the effect of a switch is measured against the same pattern with the switch
off, on the same windows.

A sweep may range over the switches themselves. Each set of switches over a window is its own bank, so the
32 sets of the five dimensions are 32 banks whose patterns nest: a pattern of one bank is the union of the
patterns that refine it in any bank with more switches on.

## 6. Counts

A dimension without a reference adds the weak orders of `n` points; with a reference, of `n + 1` points.
Both are the ordered Bell numbers `a(m)`, with `a(m) = Σ_{k=1..m} C(m,k)·a(m−k)` and `a(0) = 1`.

| Candles | No reference (`volume`, `trades`, `size`) | With reference (`delta`, `imbalance`) |
|---:|---:|---:|
| 1 | 1 | 3 |
| 2 | 3 | 13 |
| 3 | 13 | 75 |
| 4 | 75 | 541 |
| 5 | 541 | 4,683 |
| 6 | 4,683 | 47,293 |
| 7 | 47,293 | 545,835 |
| 8 | 545,835 | 7,087,261 |
| 9 | 7,087,261 | 102,247,563 |
| 10 | 102,247,563 | 1,622,632,573 |

The declared domain of a window is the 0.9 price count times one factor per dimension that is on. For two
oriented candles: 7,452 with none on; 22,356 with `volume`; 96,876 with `delta`; 290,628 with both.

**Dependence.** The five values come from three counters, so they are not all free. `imbalance` is `delta`
over `volume`, and `size` is `volume` over `trades`. Enumerating every two-candle window over small whole
counters, for all 31 sets of dimensions, shows exactly two dependent cores: `delta` with `imbalance` (25 of 169 combinations can occur, since the sides
must agree), and `volume` with `trades` and `size` (13 of 27). Every set that contains neither core reaches
its full product, which caps an independent set at three dimensions. With all five on, 209 of 4,563
combinations can occur. Three candles agree: `volume` with `trades` and either `delta` or `imbalance`
reaches all 12,675 combinations, and `delta` with `imbalance` reaches 459 of 5,625. The enumeration scripts land
with the Rust core's counts.

**Any set may be on, in a pattern and in a declared domain.** A domain that declares a dependent core
contains patterns no data can produce. They cost no work: preparation materialises only the patterns it
observes, and every other pattern, possible or not, sits in the symbolic complement. Coverage arithmetic
stays exact, because it counts declared patterns. Only the headline count is affected, so a report on such
a domain gives the declared count and says that it includes patterns that cannot occur. For `delta` with
`imbalance` the count that can occur is known: the sum, over the ways to split `n` candles into `p` net
buying, `q` net selling and `z` balanced, of `n!/(p!·q!·z!) · a(p)² · a(q)²`. That is 25 and 459 for two
and three candles, matching the enumeration. No closed form is claimed for the other dependent sets.

**What limits an open sweep is occurrences.** Two oriented candles with all five dimensions on have
7,452 × 209 = 1,557,468 states that can occur. Twenty-three months of 15m bars hold about 66,000 windows,
so most patterns observed at that depth occur once. A sweep therefore ranges over the switches as well
(section 5) and reads each pattern at the finest depth that still has enough occurrences.

## 7. Keys and execution

- **Price key.** Unchanged: four `u64` words, the same bits, the same ordering.
- **Dimension words.** Each dimension that is on appends one `u64`, in the order of section 2: four bits
  per candle rank, four bits for the reference's rank, eight bits naming the dimension, the rest zero. Ten
  candles use 52 bits. A key with no dimension on has no such word and is a 0.9 key.
- **Encoding.** One sort of at most eleven values per dimension per window, with no allocation.
- **Everything after the key.** The observed-state dictionary, predicate banks, signature trees,
  certificates, the symbolic complement, coverage accounting, the ledger and the verifier work on keys,
  truth words and exact counts. They are not changed.
- **Where cost appears.** Physical work grows with the number of distinct observed states, and a domain
  with a dimension on observes more of them. That cost is paid by the domains that switch a dimension on,
  and by no other.

## 8. Algebra

- `project(g, indices)` re-ranks each dimension part over the surviving candles; a reference stays.
- `forget_dimension(g, d)` drops one part. It commutes with `project` and with `forget_orientation`.
- Overlap composition treats each axis separately; `composition_count` is the product over axes.
- `aggregate_partition` and `aggregate_blocks` reject a pattern with a dimension on. A merged candle's
  volume is a sum, which an order does not determine. Aggregation from data sums the counters first and
  derives the values afterwards, as Cube does.

## 9. One change across the system

| Where | What changes |
|---|---|
| Geometry contract and Rust core | Sections 3 to 8 above: values, text, counts, key words, `dimensions=` in a bank, the algebra laws, the verifier's independent recomputation. |
| Recording | A nine-column form beside today's six: `open_ms,open,high,low,close,base_volume,volume,taker_buy_volume,trade_count`, with Cube's names and `volume` in USDT. Counters are written so that reading them back gives the same float. A pattern with a dimension on is refused, not weakened, on a recording without counters. The pinned six-column recording stays valid, its `volume` stays BTC, and it supports no dimension. |
| Study engine | `parseG1`, `g1FromRecording`, `chainedG1FromRecording` and the two matchers read and write dimension parts. |
| Query language | A reading per dimension beside `price(…)`: `volume()`, `trades()`, `delta()`, `size()`, `imbalance()`, each with `bars_ago:`. `candle_relation` compares two readings of one dimension, or a `delta` or `imbalance` reading with `0`, and refuses a mix of axes. `prior_high` and `prior_low` take `of:` a dimension. `dimension_multiple` measures volume, trades or size against the median of the candles before. `exact_g1` and `chained_g1` accept dimension parts. On a recording without counters all of these are refused and none is offered. |
| Composer | One switch per dimension and, for each one on, a track under the drawn candles with a mark per candle and a zero line where there is a reference; only order is read. The drawn bar, the address (`dim=`) and the encoder carry the ranks. A drawing with a dimension on is written in a later revision of the drawing packet, with one more field, `dimensions`, holding the parts of its g1 code; with every dimension off the packet is the first revision to the letter. Recorded counters come from a new exact payload, `/counters`, fetched only when a dimension is on. Its existing recorded tracks (volume and maker share against recent medians) are other measures and keep their names. |
| Cube | No change. It is the source of the definitions. Its bridge already serves the three counters. |
| Query bench | Its cube reader (`query/cube.mjs`) writes the three counters into the recording. The vocabulary gains the dimension clauses; a lane per dimension in use shows each candle's value under the canvas, with a switch each and a place in the address (`ln=`). The drawing reader takes both packet revisions, so a shape with dimensions crosses between Composer and Query in either direction. |
| Limen feature | Hands the evaluator the three counters from Limen's bars (section 11). Nothing else of its own: the switches arrive as slots of the pattern template, so a search can turn each one on and off as a parameter. |
| Shared vectors | The vectors Filang and Composer both check (`study/verify/chained-vectors.json` here, `checks/chained-vectors.json` there) gain windows with dimensions on, and the Rust core checks the same file. One set of answers binds all three. |

## 10. Criteria, written before the work

Under the repository law this is a performance attempt and a results attempt. Both are stated here so they
exist before any code.

**Parity (all dimensions off).** Every existing artefact is byte-identical: the pattern text and keys of
every window in the pinned recordings, `geometry-count` for one to ten candles in both modes, the catalogue
and coverage digests of the `smoke` domain, the study verification counts, and the shared chained vectors.
Any difference fails the change.

**Performance (all dimensions off).** Hypothesis: geometry preparation and pair scoring on the existing
benchmark workloads are no slower and use no more memory than the commit this branches from, on the same
machine and worker count. Criterion: over the declared repetitions, the median elapsed time and the peak
memory are within the baseline's own run-to-run spread. Otherwise `not-supported`, and the change does not
merge.

**Cost (dimensions on).** Reported, not gated: windows encoded per second, distinct observed states, and
scored regions for the same windows with `volume`, with `delta`, and with both.

**Results.** Hypothesis: on 15m and 30m bars, at least one switch separates a searched pattern space from
its time-shifted noise searches where the price-only space did not. The protocol is the one the price-only
searches used (time-shifted noise searches of the same points, a held-back third, perturbation against
noise leaders), with the final read on bars after 2026-11-21, since every earlier bar has been read.
`not-supported` is a result and is kept.

## 11. Decisions

Taken by the owner on 2026-11-22.

| # | Question | Decision |
|---|---|---|
| 1 | `volume` in USDT, as in Cube, or in BTC, as in today's recording? | USDT. It is the common currency the readings are coordinated in. |
| 2 | May a declared domain switch on dependent dimensions? | Yes, any set. Sweeps stay open-ended; the report says when a count includes patterns that cannot occur (section 6). |
| 3 | The separators `|` and `/`. | Accepted. |
| 4 | Counters arrive from the bridge as 64-bit floats. | Accepted as the delivered values. |
| 5 | Limen's bars must be shown to carry the same counters before a search uses them. | Agreed. First check below. |

**The check for decision 5, so far.** Limen's bars carry the three counters under other names: USDT traded is
`liquidity_sum`, taker-buy USDT is `liquidity_sum − maker_liquidity`, trades is `no_of_trades`. Its `volume`
is BTC, and its `maker_ratio` is a share of trades, not of volume, so neither is used. Against the
exchange's own published 15m bars for 2026-06-01 to 2026-06-21 (2,000 bars): trades are equal on every
bar; USDT traded differs by at most 0.05 and taker-buy USDT by at most 0.10, because Limen's amounts are
kept to one decimal; and every reading g1 would take agrees on every bar (the order of adjacent bars'
`volume`, `delta`, `size` and `imbalance`, and the side of `delta`).

Still owed: the same comparison against the cube's own counters. They are reachable only through the
bridge on the host, and Query's reader does not pass them through until this change is built.
