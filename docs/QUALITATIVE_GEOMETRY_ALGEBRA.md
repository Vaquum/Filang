# Qualitative geometry algebra — optional Phase 1 layer

This document specifies an **additive library module**, not a change to the
existing geometry language or execution machinery. The sole library entrypoint
is the new `filang::geometry_algebra` module, exported from `src/lib.rs`.
All operations accept and return existing validated
`geometry::GeometryPattern` objects. No execution rules, serialization
formats, source adapters, scoring kernels, transaction costs, or inference
methods change. The layer has no third-party dependencies, supports Rust 1.63,
and never reads training labels or prices.

## Input semantics and API

A complete n-candle pattern is the canonical **global weak order** of its
four endpoint labels per candle, plus (in oriented mode) body direction.
Ordinal ranks are relative to the entire input window. Removing candles
therefore requires dense re-ranking, not slicing the serialized rank bytes.

The public operations are:

| API | Meaning |
|---|---|
| `project(g, indices)` | Restrict to increasing candle indices and re-rank surviving endpoints |
| `forget_orientation(g)` | Drop body direction while keeping endpoint order |
| `overlap_compatible(a,b,s)` | Test whether last s rows of a and first s rows of b have identical induced geometry |
| `composition_count(a,b,s)` | Count all global weak orders compatible with both windows, with their s shared candles |
| `compose_overlap(a,b,s,max_results)` | Materialize all such complete patterns, or fail before output when the cap is too small |
| `append_one(prefix,candle,max_results)` | Complete every positioning of one prescribed candle at the end of caller row order |
| `prepend_one(candle,suffix,max_results)` | Symmetric extension at the beginning of caller row order |
| `aggregate_partition(g,group_lengths,order)` | Exact OHLC aggregation for consecutive groups of arbitrary positive sizes |
| `aggregate_blocks(g,block_size,order)` | Exact OHLC aggregation for uniform consecutive groups |

`CandleOrder::{OldestFirst,NewestFirst}` is **explicit** for aggregation.
Filang's direction experiment uses newest-first windows. No layer operation
guesses chronology from rank values or presumes a canonical dataset order.

Unoriented patterns cannot, in general, recover aggregated OHLC bodies,
because the first open and last close are unknown. The API rejects an
unoriented input rather than choosing an arbitrary answer.

## Laws and correctness arguments

### Projection

Let `P_I(g)` retain the candle indices `I` in strictly increasing order,
and reassign the surviving endpoints' global ranks densely. Then:

- **Restriction:** every surviving endpoint comparison (less, equal, greater)
  is unchanged, including comparisons between nonadjacent surviving candles.
- **Identity:** `P_[0,...,n-1](g) = g`.
- **Composition:** `P_J(P_I(g)) = P_(I[J])(g)`.
- **Mode preservation:** direction tokens of surviving candles are unchanged.
- **Forgetful compatibility:** `P_I(forget(g)) = forget(P_I(g))`.

Empty projection yields the native zero-candle geometry in the same mode.
Repeated, reordered, or out-of-range indices are rejected; projection is
not an arbitrary row-permutation operator.

### Overlap and exact relational composition

For patterns `a` and `b` in the same mode, with `s` shared candles,
compatibility requires their respective overlapping projections to agree.
The output sequence contains all of `a`, then the last `len(b)-s`
candles from `b`, retaining the caller's ordering.

Compatibility **does not** determine how endpoints appearing only in
`a` compare with endpoints appearing only in `b`. Those comparisons
must be completed explicitly rather than discarded or assumed independent.

For the proof of completeness, collapse each operand's equal endpoint levels
to ordered chains `L_0 < ... < L_(p-1)` and
`R_0 < ... < R_(q-1)`. The shared endpoints give compatible one-to-one
**anchors** between levels in the two chains. A candidate global weak order
is then a path from `(0,0)` to `(p,q)` whose steps consume the next:

1. left level alone,
2. right level alone, or
3. left and right levels as one tied global level.

An anchored level must be consumed in the third kind of step, simultaneously
with its declared partner. Non-anchored levels may be interleaved or tied.
Every valid global completion yields exactly one such path, and every
permitted path yields a realizable, canonical Filang geometry. The
algorithm never invents an inconsistent shared price relationship.

Let `C(i,j)` be the number of valid suffix paths from those chain offsets.
The terminal count is `C(p,q)=1`; elsewhere it is the sum of the permitted
`C(i+1,j)`, `C(i,j+1)`, and `C(i+1,j+1)`. Without anchors, this is
the Delannoy recurrence. Two one-candle shapes with four distinct endpoints
each have `D(4,4)=321` completions, not just one. A zero count means the
overlap is incompatible. A zero-overlap composition combines disjoint
windows without adding chronology-dependent price assumptions.

**Set-valued associativity:** composing successive overlapping windows
in either bracketing gives the same set of complete global completions,
after aligning the shared-candle positions. Individual completions must not
be arbitrarily selected as if the operation were single-valued.

The native counter uses checked u128 arithmetic, does not enumerate output,
and fails on overflow or a declared one-million-cell DP matrix limit.
The enumerator checks the exact count against `max_results` *before*
allocating output. It either produces all completions or returns an error;
there is no silent sample, ranking, pruning, or partial result. It remains
an intentionally bounded Phase 1 operation, not a solver for astronomical
fully expanded domains.

### Extension

`append_one(g,c,max_results)` and `prepend_one(c,g,max_results)`
are zero-overlap compositions with a one-candle pattern `c`. They
exhaustively position the prescribed candle at the end or beginning of
the caller's row ordering, respectively. This matters for newest-first
windows. Neither operation infers a future price or a next-candle probability.

### Exact aggregation and multiscale composition

For a consecutive block, derive OHLC from **oriented endpoint ranks**:

- low is the minimum constituent low;
- high is the maximum constituent high;
- open is the chronologically earliest constituent open;
- close is the chronologically latest constituent close.

Each constituent open and close is recoverable from its body rank pair
and direction token, including doji. Aggregate body bottom/top are
`min(open,close)` and `max(open,close)`; aggregate direction comes from
their ordering. Recanonicalization uses the original *global* endpoint
rank values, so it retains relationships across the aggregated bars as well.

Because a canonical pattern preserves precisely all relevant order and
equality relations, the resulting aggregate equals the canonical geometry
of any numerical OHLC realization of that input pattern. No intermediate
numerical OHLC prices are selected, and no ratios or tick assumptions occur.

Uniform block aggregation is compositional under aligned partitions:

`A_m(A_k(g)) = A_(mk)(g)`.

For arbitrary partitions, merging adjacent groups after aggregation equals
aggregating their concatenated input blocks. Both statements assume the
same declared CandleOrder at every stage. These are **symbolic equalities**,
not claims that the actual 15m, 30m, etc. market datasets have matching
timestamps or aggregation policies.

## Integration: caller owns decisions

Example Rust usage:

~~~rust
use filang::geometry::GeometryPattern;
use filang::geometry_algebra::{
    aggregate_blocks, compose_overlap, composition_count, project, CandleOrder,
};

fn main() -> Result<(), String> {
    let g: GeometryPattern = "g1:o:0,1,2,3,u;4,5,6,7,d".parse()?;
    let one = project(&g, &[0])?;
    let other = project(&g, &[1])?;
    let count = composition_count(&one, &other, 0)?;
    let completions = compose_overlap(&one, &other, 0, 321)?;
    assert_eq!(count, 321);
    assert!(completions.contains(&g));

    let coarser = aggregate_blocks(&g, 2, CandleOrder::OldestFirst)?;
    assert_eq!(coarser.len(), 1);
    Ok(())
}
~~~

- This is an optional dependency from the *new* module to the preexisting
  native geometry API; there are **no engine calls into this module**.
- It is accessible from any future Rust research tool, strategy authoring
  extension, or standalone application using the existing Filang crate.
- `GeometryKey::to_pattern()` allows consumers of the compact key representation
  to opt in without altering key serialization or lookup.
- Nothing about search address multiplicities, predicate-state interning,
  causal validity, fees, trade ledgers, or scoring changes.

## Verification and deliberate limitations

`cargo test --offline --locked --test geometry_algebra` exercises projection
composition, mode and index errors, Delannoy counts, exhaustive flat-candle
three-way numeric-oracle equivalence, overlap incompatibility, preservation
of nonadjacent comparisons, set-valued associativity, and aggregation equality
against independent OHLC numerical calculations in **both** chronological
orders. The deterministic generation includes exact price ties, missing
wicks, doji, gaps, and positive/negative bodies.

This delivers **exact finite qualitative operators**. It does not deliver
the Phase 2 abstraction search, a fitted predictive equivalence relation,
a stochastic transition model, a speedup measurement, a claim of market
information, or a trading edge. It does not modify the finite empirical
universe represented by Filang's existing sweep tools.

Important limitation: overlap compatibility presumes that the caller selected
actual corresponding window positions. Geometry does not carry timestamps
or sample provenance. Aggregation similarly assumes consecutive,
appropriately aligned candles; it does not validate market-data resampling.
