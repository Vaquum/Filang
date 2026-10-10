# Qualitative geometry abstraction — optional Phase 2 layer

## Role and dependency boundary

This module is a **separate, opt-in** Rust namespace,
`filang::geometry_abstraction`, built on Filang's existing
`geometry::GeometryPattern` and the Phase 1 algebra. It provides an exact
way to ask which distinctions in a complete candle geometry are being
retained. It does **not** change the encoding, geometry sweep, trading
engine, rule semantics, portfolio accounting, CLI, or data provenance.
No new numerical indicators, price thresholds, statistics, learned
weights, hidden pattern vocabulary, or subjective "importance" rules
are introduced.

It adds a mathematical layer: caller-defined partial descriptions,
their equivalence classes, refinement/coarsening, and optional lossless
reconstruction certificates.

## Definitions

For a fixed width `n` and mode `m`, let `G(n,m)` be the set of all legal
complete Filang geometries. Each geometry specifies the global weak
order of its `4n` endpoint labels, and each body's direction if oriented.

A **schema** `S` selects an arbitrary finite set of *unordered labeled
endpoint pairs* (canonically ordered by candle index then boundary role),
plus an optional set of candle indices whose body directions are retained
in oriented mode. Comparison outcomes are precisely `<`, `=`, and `>`.
A schema has no model-selected or empirically fitted parameters.

Its **signature** `alpha_S(g)` is the tuple of those exact comparison
outcomes and selected directions, stored together with the **full schema
identity**. Even if two distinct schemas happen to generate the same
outcome vector, their signatures cannot collide as objects.

This defines a true equivalence relation over *complete* geometries:

    g ~_S h  iff  alpha_S(g) == alpha_S(h).

Every equivalence class is a partial qualitative description: the
conjunction of the retained comparisons and selected directions, with
other distinctions unspecified. Because signatures are generated from
legal native patterns, their conjunctions are always realizable.

If schema `T` contains every comparison and selected direction in
`S`, then `T` is a refinement of `S`. There is an exact forgetful map:

    alpha_S(g) = coarsen_S(alpha_T(g)).

Hence refining a schema **can split classes but cannot merge them**.
This law does not require trading data and does not assert that finer
classes predict anything better.
Selections form a distributive **syntactic** lattice under union (join)
and intersection (meet). Distinct schemas can induce the same semantic
partition when some comparisons follow from others or from candle validity;
no semantic irredundancy is claimed.

**Phase 1 compatibility:** for increasing source indices `I`, a schema `S`
on `|I|` candles can be lifted to the source's indexed endpoint labels,
`lift_I(S)`. Evaluating `S` after the Phase 1 `project_I(g)` and evaluating
`lift_I(S)` directly on `g` give **identical selected value vectors**.
Their full signatures deliberately differ because the schema domains differ.
The `signature_on_projection` method calls Phase 1's existing projection;
no second projection implementation or change to its rules is introduced.

The **complete schema** selects every endpoint pair plus every oriented
direction and has singleton classes: it determines the original
complete geometry. The **empty schema** has one class for every fixed
width/mode. Between them lie caller-chosen partial descriptions,
not a prescribed learning strategy.

## Public API

| Function or type | Contract |
|---|---|
| `Endpoint`, `EndpointPair` | Endpoint labels and normalized distinct-pair identity |
| `Schema::new(bars, mode, pairs, directions)` | Canonical selection (sorted/deduplicated), with input and scope checks |
| `Schema::empty`, `Schema::complete` | Coarsest and finest comparison basis |
| `Schema::with_comparison`, `with_direction` | Monotone syntactic refinement |
| `Schema::join`, `Schema::meet` | Union and intersection of selected observations, forming the distributive syntactic selection lattice |
| `Schema::signature(g)` | Exact value vector tied to its complete schema |
| `Schema::coarsen(fine_signature)` | Exact projection from a syntactic refinement without the original geometry |
| `Schema::signature_on_projection(g,indices)` | Apply Phase 1 window projection, then this schema's signature |
| `Schema::lift_to(source_bars,indices)` | Relabel this schema onto selected source candles; retains the projected signature's values |
| `Schema::is_refinement_of(coarse)` | Set inclusion over selected comparison and direction coordinates |
| `Signature::matches(g)` | Evaluate the partial description against any same-domain complete geometry |
| `partition_input(schema, patterns)` | Deterministic grouping of an explicitly supplied finite collection |
| `ExactFactorization::from_pattern(schema,g)` | Exact signature plus a linear-size weak-order residual |
| `ExactFactorization::reconstruct()` | Recover the unique original native geometry, or error if inconsistent/incomplete |

### Finite collection versus full universe

`partition_input` returns input indices, including repeated observations,
for each observed signature. Counts mean **only** how many items in the
provided slice have that signature. They are *not* counts of all legal
members of that abstract class, probabilities, forbidden-pattern counts,
or estimates of unseen support. A user can classify observed history or
a separately enumerated complete domain; the API does not confuse them.

For constant schemas, the grouping algorithm keys on selected answer
vectors rather than cloning the schema per input occurrence. Full schema
identity is restored **once per returned class**.

## Exact decomposition without keeping a full pattern copy

A signature alone is intentionally many-to-one. To preserve all information
when required, `ExactFactorization` records an additional residual:

1. Partition the native pattern's `4n` labeled endpoints into their global
   equality levels, already supplied by its canonical dense ranks.
2. Inside each level, connect its endpoint labels through equality edges,
   using one representative plus a spanning star.
3. Link the representatives of consecutive levels with a strict
   low-to-high inequality.
4. Omit every such comparison already carried by the selected schema;
   store any body directions not retained by the schema.

Exactly `4n - 1` comparison edges are sufficient in the original
certificate (for `n > 0`), so **at most** that many comparison edges are
stored in the residual. This is independent of the size of the total
valid-pattern universe; it is *not* a claim of optimum bit compression
or a minimal grammar.

Reconstruction unions equality edges from the signature and residual,
builds the directed graph of strict comparisons between equality classes,
and accepts only a **unique topological ordering**. It assigns dense ranks
from that unique order, supplies all body directions, and delegates final
semantic validity to Filang's existing `GeometryPattern::new`.
Contradictory, cyclic, incomplete, or invalid descriptions fail closed.
The original rank vector is not stored inside the factorization.

The exact law is

    reconstruct(factorize_S(g)) = g.

For the complete schema, the residual is empty. For a partial schema,
the omitted comparisons carry precisely the information needed to
reconstruct the original; no hypothesis about market dynamics is required.

## Example

~~~rust
use filang::geometry::{Boundary, GeometryMode, GeometryPattern};
use filang::geometry_abstraction::{Endpoint, EndpointPair, Schema, ExactFactorization};

fn main() -> Result<(), String> {
    let g: GeometryPattern = "g1:o:0,1,2,3,u;4,5,6,7,d".parse()?;
    let relation = EndpointPair::new(
        Endpoint::new(0, Boundary::High),
        Endpoint::new(1, Boundary::Low),
    )?;

    // Preserve only the cross-candle relationship and the first direction.
    let basis = Schema::new(2, GeometryMode::Oriented, vec![relation], vec![0])?;
    let description = basis.signature(&g)?;
    assert!(description.matches(&g)?);

    // An exact optional residual keeps the distinctions the basis discards.
    let representation = ExactFactorization::from_pattern(&basis, &g)?;
    assert_eq!(representation.reconstruct()?, g);
    Ok(())
}
~~~

The schema is supplied by the **caller**, not selected by Filang. Later
research may choose or optimize a basis under a separately frozen
experimental protocol, but that is *not* Phase 2's job.

## Proof boundaries, computational limits, and verification

- Normalized endpoint pairs always use canonical *label* ordering, never
  numerical price ordering. Comparisons and body directions are exact.
- Schemas have an independent explicit **256-endpoint** budget (64 candles).
  No core Filang width limit or encoder behavior is changed by this bound.
- `Schema::complete` intentionally stores all `(4n choose 2)` comparisons.
  It is a reference extreme, not a strategy to enumerate enormous spaces.
- Residual reconstruction uses a bounded union-find and a finite DAG. It
  requires a unique order rather than selecting an arbitrary total
  ordering of underconstrained classes.
- No arbitrary malformed partial description parser or symbolic constraint
  solver is claimed: signatures are produced from **valid patterns** only.
- Exact factorization is not a claim of algorithmic compression; the
  representation includes its schema and any omitted distinguishing edges.
- The layer cannot determine which chosen comparison basis carries
  predictive information; likelihoods, causal states, information loss in
  bits, trading costs, and market data remain outside this module.
- This change is additive: no modification to Phase 1 algebra, the old
  geometry language, output identities, search, execution, or benchmarks.

The integration test `tests/geometry_abstraction.rs` enumerates **all
2,568 unoriented and 7,452 oriented legal two-candle patterns**, verifies
lossless factorization and reconstruction under empty, partial and complete
schemas, and checks quotient partition refinement over both complete
domains. Further tests check orientation masking, adjacent-only
nonadjacent ambiguity, invalid inputs, zero-candle geometry, and thousands
of reproducibly generated 4-candle geometries with price ties,
doji, missing wicks and gaps.

Run:

~~~sh
cargo +1.63.0 test --locked --offline --test geometry_abstraction
cargo +1.63.0 test --locked --offline
cargo +1.63.0 clippy --locked --offline --all-targets -- -D warnings
~~~

This is a **correctness-only** implementation. No prediction, backtest,
market-data experiment, empirical performance comparison, new alpha, or
scientific claim about compression has been conducted or established.
