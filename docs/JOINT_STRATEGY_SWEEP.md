# Joint strategy families — Filang 0.7

This adds joint rule search, not ten independent indicator sweeps. A candidate
chooses one predicate alternative per slot, the parameters of each alternative,
and a compound rule template. No individual-profitability shortlist is applied.
The runtime is native Rust; numerical graphs and the full-risk execution context
are the same APIs used by the preceding paged/micro implementations. Limen and
Terasweep remain optional capability/performance references, not dependencies.

## Two languages with an explicit boundary

Numerical inputs are ordinary Filang expressions. Predicates support:

- `threshold:gt/ge/lt/le/eq/ne`: one numeric input and a rational constant grid.
- `relative:gt/ge/lt/le/eq/ne`: two inputs of equal units.
- `cross:above/below`: current strict comparison and previous inclusive opposite.
- `slope:rising:N` or `slope:falling:N`: current value versus N bars earlier.

Relative, crossover and slope predicates have no constant parameter and must use
`0:1:1:1`, not an inactive grid counted as diversity. Each alternative can apply
`plain`, `onset`, `persist:N`, `recent:N`, or a bounded `+`-separated chain.
N is an integer 1..100000. All inputs must be finite for a comparison to be valid.
No relative comparison is lowered to subtraction, avoiding overflow semantics.

A compound rule is a prefix expression over slots:

```
(and s0 s1)
(or s0 s1)
(and s0 (not s1))
(and s0 (or s1 s2))
(recent 3 (and s0 (persist 2 s1)))
```

The rule IR interns repeated nodes, checks depth/arity, and supports AND, OR, NOT,
persistence, recency and onset on arbitrary subexpressions. Every sweep template
must consume every declared slot; unused slots cannot inflate candidate counts.
Up to eight slots and 128 templates are currently supported. SQL, Python callbacks,
position-latched entry/exit state machines, stops and cooldowns are not silently
accepted. Hold-while-true maps final valid decisions to existing long/flat execution.
This is not an unchanged Limen SFD importer or a claim of complete Limen parity.

### Validity contract

Truth and validity are separate packed planes. AND and OR require **both** inputs
valid. NOT complements only within validity. This conservative rule is explicit;
it is not three-valued short-circuit OR. For persistence/recency, a full chronological
window must exist and every input in it must be valid; otherwise output is invalid.
Onset requires valid current and previous rows. A final invalid value is flat.

Numerical and temporal Boolean preparation uses the full causal input history.
Only after preparation is the scored interval selected. Input ends exactly at its
exclusive bound; appended future rows are rejected by the CLI. No row is dropped
because another feature has a longer lookback. Execution retains close decision /
next open, terminal exit, fixed costs and all ten original metrics.

## Factorized execution

1. Intern and prepare numerical roots once in a bounded graph/data-scoped bank.
2. Prepare exact threshold cells per predicate, including its temporal qualifiers.
   Comparator cutpoints distinguish strict, inclusive and equality behavior. No
   grid-sized array is needed in native preparation, even for an enormous grid.
3. Share identical predicate plans across slots. Retain independent alternative
   identities and explicit family tags; a tag is a domain constraint, not a kernel.
4. Enumerate valid alternative tuples and their predicate cells, not individual
   threshold coordinates. Multi-dimensional result boxes contain half-open index
   ranges; their volume is exact logical coverage.
5. For pointwise Boolean templates, construct two cofactors for the final slot.
   `F = (F0 AND NOT B) OR (F1 AND B)` then requires a wordwise mux rather than
   interpreting the whole rule again for each final-slot cell. NEON and AVX2
   intrinsics operate on packed individual bits, with checked scalar/tail paths.
6. Coalesce adjacent final-slot cells with exactly identical final positions.
   Constant cofactors resolve the complete final-slot domain directly.
7. An optional bounded FIFO cache indexes complete position words; equality is
   checked before reuse, including hash-collision tests. Cache misses reach the
   existing reversible full-risk Executor. Dense changes retain its replay fallback.

Compound temporal rule templates cannot use a pointwise cofactor certificate;
they use the declared full rule path. Qualifiers applied within leaf predicates
can still use cofactors because their prepared outputs are the Boolean variables.
Plans `expanded`, `cells`, and `cofactor` expose matched reference/optimization
paths. Expanded explicitly replays every logical address and is capped at one
million requests. All paths retain the same ten metrics, precision and costs.

No approximation, heuristic exclusion or per-address cost-scenario trick creates
coverage. `different_tags=true` is an explicit structural constraint on the requested
domain. Its exact cardinality is computed by slot-partition inclusion-exclusion,
not by enumerating a huge product of threshold grids. Overflow is rejected.

This first executor still visits valid alternative tuples and outer predicate-cell
products. It is not a sublinear algorithm for every arbitrary program domain.
Its trillions-sized examples obtain much of their compression from threshold
regions; they must not be called trillions of independent indicator inventions.

## Files, budgets and reproducibility

A configuration is key=value. `parameters` points to a tab-separated text file:

```
# slot label tag predicate qualifiers grid x y
```

Those are eight TAB-separated fields. The last two contain complete ordinary
numerical expressions; y is `-` for unary predicates. Example:

```
0	rsi	momentum	threshold:gt	persist:2	998:1:5:1000	(div0 (wilder 14 (add (abs (diff 1 close)) (diff 1 close))) (wilder 14 (abs (diff 1 close))))	-
1	trend	trend	relative:gt	plain	0:1:1:1	(ema 24 close)	(ema 96 close)
```

Source options, grids, comparison direction, qualifier windows and rule-template
choice are all parameters. The authoring example expands the ten existing cohort
macros; the numerical/predicate/scoring engine never dispatches on their names.

The fixed alternative catalog and its dependency graph are bounded (up to 4096
rows, 4 MiB text). Numerical preparation and retained predicate cells have declared
budgets; the behavior cache has a separate bounded byte charge. Executor market/
risk state also has a separate payload. These are not a total process RSS cap.
The first implementation rejects an oversized bank rather than silently sampling
or allocating all trillion candidates. Paging/eviction of arbitrarily large
predicate-alternative catalogs and distributed/checkpointed controller state remain
follow-up work. An explicit physical box budget fails an incomplete campaign.

`boxes.bin` has one fixed-size record per output box: template u64, then
(choice-id,lo,hi) u64 triples for every slot, then ten f64 metrics per scenario.
The manifest defines byte size, contexts and metric order. `predicate-cells.bin`
contains exact truth/validity planes and threshold ranges for optional reference
verification. Summary mode computes/hashes the same box records but does not write
them. It does not expand a box into one record per represented address.

`best.json` is a descriptive discovery winner under the first declared cost
scenario, ranking log return rounded to 1e-9 then stable coordinates. This is not
an eligibility test, independent validation or a profitability guarantee. The exact
chosen predicates and template are exported as `best-parameters.tsv` and
`best-rule.txt`; they can be used as a singleton replay domain. No live trading
or later-period promotion is performed by a systems sweep.

## Run

```
cargo test --locked --offline
cargo build --release --locked --offline
./target/release/filang cohort-parity --data data/btc4h/discovery.csv \
  --start 2024-01-01 --end 2025-01-01 --out runs/joint-parity
.venv/bin/python scripts/cohort_reference.py --run runs/joint-parity \
  --data data/btc4h/discovery.csv
./target/release/filang strategy-example --out runs/joint-domain \
  --grid-count 20001 --neighbors true --qualifiers true --slots 2
./target/release/filang strategy-inspect --config runs/joint-domain/sweep.cfg
./target/release/filang strategy-sweep --config runs/joint-domain/sweep.cfg \
  --gate runs/joint-parity/gate.txt --out runs/joint-result
.venv/bin/python scripts/verify_joint.py --run runs/joint-result \
  --out runs/joint-result/verification.json
```

All output paths must be new. The example selects three predeclared atom variants
per family (baseline, period-1/source-.005/component.05, period+1/source+.005/component.05)
and plain/persist2/recent3 predicates. The two slots use different family tags.
AND, OR and AND-NOT are jointly swept; no individual indicator winner is filtered.
The cutoff ranges are exactly the previous micro cohort's ranges, refined to the
requested odd grid count. Costs default to 10bps fees +10bps slippage per side.

Use `--grid-count 3` for a small full neighborhood, `--neighbors false --qualifiers
false` for baseline-only alternatives, or `--slots 3` for a nested/compound-temporal
example. `--plan cells --cache-mib 0` exposes unspecialized and no-cache work.
Backend `scalar`, `neon`, `avx2` and `auto` use the same declared contracts.

## Evidence requirements

Independent tests compare truth/validity at every bar, inclusive/strict/equality
cutpoints, relative comparisons, crossovers, slopes, temporal windows, bit tails,
compound nesting, future append, collision checking and exact domain counts.
All small joint boxes are expanded and compared against an independent scalar rule
interpreter plus chronological full-risk ledger. Synthetic trillion-domain tests
execute small physical region families, not a trillion independent ledger scans.

The optional verifier reconstructs numerical expressions with independent formulas
and TA-Lib rolling means, compares every predicate cell, then traverses the requested
joint domain at physical-cell granularity. It verifies that output boxes have complete,
disjoint coverage and constant final positions; every reported box is checked with
independent sequential cash/share accounting. Verification-only C is not linked
into Filang and is never used as a performance denominator. Its single-grid cap is
100000 coordinates; Cartesian products may represent trillions of addresses.

No unchanged arbitrary Limen/SFD compatibility, universal trillion-program throughput,
robust financial edge, or untouched confirmation follows from these tests. Source,
protocol, logical/physical counts, output policy, full-risk parity, timings and
negative results must be reported separately.
