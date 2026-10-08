# Bar geometry — language and execution contract (0.9)

This language describes the relative vertical order of candle bodies and wicks.
Its complete pattern is the global weak order of all endpoint prices in a
declared window. Body direction is an explicit optional part of the domain.
The input vocabulary contains only candles, their body boundaries and their
wick endpoints. Numerical indicators, volume, distance thresholds and named
chart patterns are not geometry primitives.

The distinction between a primitive, a complete pattern and a strategy address
is essential. A comparison is a primitive. A complete pattern fixes every
endpoint comparison in the window. A strategy address chooses complete patterns
for its condition slots and combines their predicates with a declared rule.
Counts of these three objects must not be presented interchangeably.

## 1. Semantic scope

For candle `i`, write:

```text
L_i = low_i
b_i = min(open_i, close_i)
t_i = max(open_i, close_i)
H_i = high_i
L_i <= b_i <= t_i <= H_i
```

The body is `[b_i,t_i]`, the lower wick is `[L_i,b_i]`, and the upper wick is
`[t_i,H_i]`. A zero-length wick is absent. A zero-length body is a doji, including
the entirely flat candle. The endpoint labels remain meaningful when some or
all of their prices coincide.

Two windows have the same **unoriented geometry** exactly when every comparison
between their corresponding endpoint prices has the same result: lower, equal
or higher. In **oriented geometry**, the open/close direction of each candle must
also agree. A strictly increasing change of the price scale preserves geometry.
The next candle's open is independent of the previous candle's close in the
legal domain: opening gaps and cross-candle exact ties are both permitted.

This equivalence preserves containment, overlap, separation, contact, exact
alignment, wick existence and all nonadjacent endpoint relationships. It does
not preserve numerical prices, price distances, body or wick lengths, ratios,
slopes, the size of a gap, volume, or the intrabar price path. For example,
whether one body's length is twice another's is outside this language, even
when that relationship might be visually meaningful. Exactness always refers
to the declared endpoint-order equivalence.

## 2. The actual comparison primitives

A price comparison has three mutually exclusive outcomes:

```text
endpoint < endpoint
endpoint = endpoint
endpoint > endpoint
```

The higher-than relation is the inverse of lower-than. Equality is a shared
price level. An implementation can store an ordered collection of equality
classes and derive all three outcomes; it need not store every comparison.

For two candles there are sixteen choices of a first-candle endpoint and a
second-candle endpoint. Writing all three outcomes for every choice produces
**48 comparison literals**. Those are a convenient generated vocabulary, not
48 mutually exclusive complete two-candle states. The full state is a consistent
combination of comparisons. Many syntactic combinations contradict transitivity
or the required order inside a candle.

This is a minimal semantic vocabulary in the following precise sense: the
objects are body/wick endpoints and the relation is their order or coincidence.
Additional categories such as engulfing or inside are derived expressions.
There is no claim that one text encoding uses the fewest possible characters or
bits, or that every listed comparison is independently necessary in a full
state. Transitivity deliberately removes that redundancy.

## 3. All eight local forms

The three bits below mean positive lower wick, positive body and positive upper
wick, in that order. A zero denotes coincident adjacent endpoints.

| Mask | Endpoint form | Interpretation | Distinct levels |
|---|---|---|---:|
| `000` | `L=b=t=H` | Entirely flat candle | 1 |
| `001` | `L=b=t<H` | Doji at low, upper wick only | 2 |
| `010` | `L=b<t=H` | Body with neither wick | 2 |
| `011` | `L=b<t<H` | Body and upper wick | 3 |
| `100` | `L<b=t=H` | Doji at high, lower wick only | 2 |
| `101` | `L<b=t<H` | Doji with both wicks | 3 |
| `110` | `L<b<t=H` | Body and lower wick | 3 |
| `111` | `L<b<t<H` | Body with both wicks | 4 |

For a nonzero body, the optional direction is `u` when close is above open or
`d` when close is below open. For a zero body it must be `z`. The unoriented mode
therefore has eight local forms. The oriented mode has twelve: four doji forms
and two directions for each of four nonzero-body forms.

Grouping forms by their number of distinct local levels `k=1,2,3,4` gives the
multiplicities used in the exact domain count:

| Mode | `k=1` | `k=2` | `k=3` | `k=4` |
|---|---:|---:|---:|---:|
| Unoriented | 1 | 3 | 3 | 1 |
| Oriented | 1 | 4 | 5 | 2 |

## 4. The thirteen relations between nondegenerate intervals

The familiar interval vocabulary is a useful projection of endpoint order.
For positive-height intervals `A=[a,b]` and `B=[c,d]`, with `a<b` and `c<d`,
exactly one row below applies. “Before” and “after” refer to low-to-high price
order here, not to the chronological order of the candles.

| Relation of A to B | Required order |
|---|---|
| Before / strictly below | `a<b<c<d` |
| Meets / touches from below | `a<b=c<d` |
| Overlaps from below | `a<c<b<d` |
| Starts / same low, shorter | `a=c<b<d` |
| During / strictly inside | `c<a<b<d` |
| Finishes / same high, shorter | `c<a<b=d` |
| Equal | `a=c<b=d` |
| Finished by / same high, longer | `a<c<b=d` |
| Contains | `a<c<d<b` |
| Started by / same low, longer | `a=c<d<b` |
| Overlapped from above | `c<a<d<b` |
| Met by / touches from above | `c<d=a<b` |
| After / strictly above | `c<d<a<b` |

This table can describe two bodies or two total ranges. It does not replace the
full candle description: body-to-wick and wick-to-wick positions can differ even
when both the body relation and the total-range relation agree. In the case of
two candles with nonzero bodies and both wicks, those two interval relations
give 121 admissible projected pairs but the full geometry has 321 states.

The thirteen-relation partition assumes nondegenerate intervals. A doji or a
zero-length wick is handled directly by the endpoint representation; no arbitrary
assignment to an overlapping interval category is needed.

## 5. Complete two-candle states

Collapse each candle's local equalities into its strictly ordered list of `k`
or `l` distinct levels. To merge the two lists, each successive global level
comes from the next first-candle level, the next second-candle level, or both
next levels at the same price. These exhaustive and disjoint choices give:

```text
D(k,l) = D(k-1,l) + D(k,l-1) + D(k-1,l-1)
D(k,0) = D(0,l) = 1
```

Equivalently, for `j` cross-candle shared levels, the number of merges is
`(k+l-j)! / ((k-j)! (l-j)! j!)`. Summing over `j=0..min(k,l)` gives `D(k,l)`.

| First candle levels / second candle levels | 1 | 2 | 3 | 4 |
|---|---:|---:|---:|---:|
| 1 | 3 | 5 | 7 | 9 |
| 2 | 5 | 13 | 25 | 41 |
| 3 | 7 | 25 | 63 | 129 |
| 4 | 9 | 41 | 129 | 321 |

Consequently the full two-candle domain is:

| Allowed forms | Unoriented states | Oriented states |
|---|---:|---:|
| Both candles have a body and both wicks | 321 | 1,284 |
| Both bodies nonzero; either wick may be absent | 1,284 | 5,136 |
| All legal forms, including doji and flat candles | 2,568 | 7,452 |

Even two full candles with no cross-candle equalities have `C(8,4)=70`
configurations. Thus about fifty labels cannot partition every complete
two-candle geometry under this equivalence. This does not prevent a small
compositional alphabet from describing every state.

## 6. Canonical global order and textual grammar

For a window of `n` candles, sort the `4n` endpoints by price and assign dense
ranks starting at zero. Equal prices receive the same rank. Store the four ranks
in the order `L,b,t,H` for each candle. Candle order is preserved; the geometry
core does not reverse, sort or infer the caller's chronological order.

The stable text format is:

```text
pattern       = "g1:u:" [unorient-row (";" unorient-row)*]
              | "g1:o:" [orient-row   (";" orient-row)*]
unorient-row  = rank "," rank "," rank "," rank
orient-row    = unorient-row "," direction
direction     = "u" | "d" | "z"
rank          = nonnegative decimal integer
```

Ranks must form a dense set `0..r-1`, and each candle's four ranks must be
nondecreasing. In oriented mode `z` is required exactly when the middle two
ranks agree; otherwise the direction is `u` or `d`. A malformed or noncanonical
pattern is rejected rather than silently interpreted as another pattern.
The empty patterns `g1:u:` and `g1:o:` are the algebra's zero-candle constructions.
Executable sweep windows are nonempty. Decimal ranks have no leading zeros
except the single digit `0`; signs and whitespace inside a pattern are rejected.

For example:

```text
g1:u:0,1,2,3;4,5,6,7
g1:o:0,1,2,3,u;4,5,6,7,d
g1:u:0,0,1,1;0,1,1,2
```

The first pattern places a complete second candle strictly above a complete
first candle. The second adds an upward first body and a downward second body.
The third includes wick absence, a doji and exact cross-candle equality without
adding special-purpose candle categories.

Native enumeration uses a deterministic order of local shape masks and
old/new/tied merge steps. Its enumeration index is not promised to be the
lexicographic position of the displayed string. The canonical rank string is
the reconstructible pattern identity.
Precisely, integer masks run from 0 through 7 with lower wick in bit 0, body in
bit 1 and upper wick in bit 2; downward direction precedes upward direction.
The earlier table displays the semantic bits in lower/body/upper order, so its
displayed `100` is integer mask 1 in that enumeration.

### Completeness and realizability

Every legal finite candle window maps to exactly one canonical pattern: sorting
finite endpoint values induces a total order of their equality classes. Two
windows map to the same pattern if and only if all labeled endpoint comparisons
agree, and their directions agree when direction is enabled.

Conversely, every pattern satisfying the constraints is realizable. Assign
price `rank+1` to each rank. Read each candle's low, body bounds and high from
those prices; choose open and close according to its direction, or any consistent
direction for a nonzero body in unoriented mode. This produces legal positive
OHLC values with exactly the encoded comparisons. No invalid cycles or impossible
local orders are admitted.

### Why adjacent relations alone are insufficient

Consider the endpoint tuples below in chronological order:

```text
A = (10,11,12,13)
B = (20,21,22,23)
C1 = (14,15,16,17)
C2 = ( 6, 7, 8, 9)
```

In both sequences `A,B,C1` and `A,B,C2`, B is wholly above A and the third candle
is wholly below B. Their two adjacent pair descriptions are identical, including
all wick/body comparisons. Yet C1 is above A and C2 is below A. The global
three-candle geometries therefore differ.

For three complete candles with all twelve endpoints distinct, there are
`12!/(4!)^3 = 34,650` global states but only `70^2 = 4,900` strings of two adjacent
pair codes. Complete arbitrary-length geometry needs nonadjacent comparisons,
which the global endpoint order retains directly.

## 7. Exact n-candle domain counts

The counter does not enumerate the pattern domain. Let `F_n(r)` count canonical
patterns of `n` candles with exactly `r` distinct global levels. Start with the
empty construction `F_0(0)=1`. Insert a candle with `k` local levels and local
multiplicity `w_k`. Sharing `j` of them with old levels creates
`s=r+k-j` levels and contributes:

```text
F_(n+1)(s) += F_n(r) * w_k * C(s,j) * C(s-j,k-j)
```

Sum over `k=1..4` and `j=0..min(r,k)`. The required domain size is
`sum_r F_n(r)`. The native implementation checks every integer addition and
multiplication in `u128`; it rejects unsupported overflow instead of truncating,
wrapping or saturating a reported count. A product of valid individual bank
counts can still overflow the strategy-address count and is checked separately.

| Window length | Unoriented full patterns | Oriented full patterns |
|---:|---:|---:|
| 1 | 8 | 12 |
| 2 | 2,568 | 7,452 |
| 3 | 5,592,968 | 32,160,252 |
| 4 | 44,418,808,968 | 508,608,936,252 |
| 5 | 936,239,675,880,968 | 21,386,422,752,715,452 |
| 6 | 43,216,321,851,028,552,968 | 1,971,122,519,237,375,505,852 |
| 7 | 3,840,691,551,111,678,501,624,968 | 349,946,534,568,771,563,626,027,452 |
| 8 | 599,170,270,107,067,142,441,692,696,968 | 109,093,488,682,843,434,702,978,214,200,252 |
| 9 | 153,066,871,555,466,967,822,330,084,645,768,968 | 55,702,085,623,739,099,432,122,993,642,929,144,252 |

Both modes exceed `u128` at ten candles. The sweep accepts at most nine candles
per window and also checks the complete strategy product; an individually
countable window can still make that product too large.

The independent Python verifier obtains these counts differently. With `q`
available levels, one candle has `A(q)=sum_k w_k*C(q,k)` assignments. For fixed
`n`, inclusion and exclusion over unused levels gives:

```text
F_n(r) = A(r)^n - sum_(j<r) C(r,j)*F_n(j)
```

Summing `r=1..4n` produces the same domain size using arbitrary-precision Python
integers. This is independent of the native chain-insertion recurrence.

## 8. Data validity and causal matching

The standalone geometry encoder accepts finite OHLC values satisfying the
candle inequalities. Abstract geometry permits any finite price sign. The
market CSV execution path retains Filang's stricter existing contract: positive
finite OHLC, finite nonnegative volume, a declared positive interval, and exactly
contiguous increasing timestamps. A gap or duplicate is rejected; missing bars
are never silently compressed or manufactured.

Equality is exact equality of the parsed floating-point values. There is no
epsilon, tick-size guess, rounding grid or approximate tie. Positive and negative
zero compare equal in the standalone algebra. Approximate pairwise equality
could fail transitivity and is not a valid substitute for the equivalence classes
used here. If a source needs explicit tick normalization, that must be declared
and performed before geometry encoding.

Each full pattern defines a predicate over a declared causal window. On every
valid window, exactly one pattern in that window's full domain is true. A window
without sufficient earlier bars is invalid. Invalidity is stored separately from
falsehood and remains part of predicate identity and compound-rule execution.

All window endpoints are known at the signal candle's close. Execution uses the
existing next-open long/flat ledger: a decision at `t` first acts at `open[t+1]`
and earns the interval through `open[t+2]`. The last two input candles are not
scored decisions. Prefix history can supply causal geometry dependencies before
the scored interval; it cannot supply future data to a signal.
The execution CSV must end exactly at the configured end-exclusive boundary and
contain the configured start at an exact bar boundary. Future rows are rejected,
even if a caller intended to leave them unscored.

## 9. Exhaustive domain, observed states and symbolic complement

The exhaustive geometry domain consists of every complete legal pattern for a
declared window and mode. A partial description such as “the second body is
inside the first body” is a union of complete patterns. The existence of that
union does not mean every possible partial-description syntax is another searched
address. The run's declared condition and rule domain defines what is counted.

Preparation encodes the windows that can affect the scored predicates and groups
matching canonical pattern identities. It materializes only these observed
identities. Every other complete pattern has an all-false truth plane over that
sample and the same window-validity plane. Those absent identities are represented
by a symbolic set difference:

```text
absent domain = all legal complete patterns minus explicitly observed patterns
absent multiplicity = exact total domain size - observed identity count
```

That symbolic complement is **not** the Boolean negation of an observed pattern.
It is a set of distinct unobserved programs that happen to have identical false
predicates on the declared sample. Its multiplicity is a `u128`; it can be vastly
larger than the number of rows. Absence is sample-scoped: a member can occur on
another dataset or in a later interval. The canonical domain and observed
exclusion set preserve its membership without listing every absent program.

Preparation scans the entire causal decision prefix, from the maximum declared
lag through `data.len()-3` inclusive. A catalogue can consequently include a
pattern observed only before the scored interval. A full-prefix predicate is
qualified first and sliced to the scored interval afterwards. Looking only at
unqualified scored timestamps would be insufficient for, for example, a
recent-occurrence qualifier whose input occurred just before scoring.

`plain` retains the raw pattern predicate. `persist:N` requires the pattern on
all N consecutive decisions ending now. `recent:N` requires at least one such
occurrence. Both require validity throughout the entire N-decision window.
`onset` requires the pattern now and its absence one decision earlier, with both
decisions valid. These are general predicate composition operators above the
geometry language. They do not add a numerical indicator or a new geometry atom.

Exact truth **and** validity words are interned into the existing predicate-state
dictionary. Hashes locate candidate states; full words are compared before
reuse. Each dictionary entry retains its logical multiplicity and a concrete,
reconstructible representative. Observed identities and the symbolic complement
retain membership even when several programs share one dictionary state.

The sum of state multiplicities must equal the entire declared per-bank domain.
For each valid unqualified window, observed one-hot truth masks must partition
the valid rows exactly once; no absent pattern may be true. These are independently
checkable invariants, not performance assumptions.

## 10. Shared physical execution

Geometry prepares predicate banks for the same generic exact pair engine used
by dense numerical atoms. It does not introduce a separate profit calculation.
Two independently chosen condition slots feed declared pointwise Boolean rules.
The engine retains existing validity semantics, fees, slippage, terminal
liquidation and all ten full-risk metrics.

Signature trees aggregate all/any truth and validity over groups of states. A
Boolean envelope can certify that every member of a product of two groups has
the same final position mask. The engine scores that product once and attaches
the exact sum of member multiplicity products. Otherwise it subdivides until a
constant product or a leaf pair is reached. A certificate proves equality of
positions, not a PnL upper bound, an approximate resemblance or a reason to skip
an unprofitable program.

`certificates=false` is a matched physical control: it visits every pair of
prepared dictionary states through the same scorer. It does not expand the
symbolic absent-pattern complement into its logical members. Both modes cover
the identical logical strategy domain.

The first implementation uses declared budgets for geometry preparation,
predicate-bank payloads and signature trees. At most the required bank pair and
its trees are active during pairing. A budget failure is reported; it is not
silently converted into approximate sampling. Budgets constrain their named
payloads, not total process RSS. Input data, language metadata, runtime overhead
and operating-system allocations must be reported separately when measuring
memory. Physical work still increases with distinct observed geometry and truth
states, and a per-task node limit prevents an incomplete task from being committed
as complete. There is no automatic distributed execution or adaptive disk spill.
Preparation can run on several banks concurrently, with a separate declared
budget for each active preparation. Task workers also own separate scorer state.
Increasing workers can therefore increase total memory even when each component
stays within its individual budget. Native worker count is explicit in output;
the CLI defaults to available logical CPUs and accepts 1 through 1,024.

## 11. Durability, coverage and representatives

The generic executor uses a single-writer advisory run lock. Immutable banks,
membership artifacts and preparation markers are checksum-bound to their run
context. A preparation marker is committed only after its payloads are complete.
Completed task records bind data, engine, raw configuration, backend, execution
plan and output policy. Files use the existing appended SHA-256 format with
flush, file synchronization, same-filesystem rename and directory synchronization.
Checksums detect accidental or conflicting edits; they are not authenticated
signatures.

Pair tasks own disjoint state-range products. Each task begins with its own
execution state, and completed tasks reduce in canonical order. Changing the
number of native workers on resume does not change that order. Interrupted,
uncommitted artifacts are recomputed; committed artifacts with changed context
or checksum fail closed. No filesystem-independent hardware power-loss guarantee
is claimed.

Coverage is the checked sum of logical multiplicities of disjoint completed
products. Completion requires equality with the checked requested strategy
domain. Captured output retains the products and metrics. Summary output still
computes and hashes every resolved region while retaining aggregate coverage,
task records and exact best representatives. A retained representative denotes
one concrete pattern address; its metric equivalence to other covered addresses
is sample-scoped.
Winner ordering uses log return rounded to a `1e-9` resolution, then template,
ordered bank IDs and representative coordinates. A frozen export identifies
one explicit pattern per slot. It never carries the all-unobserved alias set
forward as a single new-data predicate.

## 12. Reporting and verification boundary

A report must distinguish at least:

* Legal complete patterns per bank and requested logical strategy addresses.
* Windows encoded and explicit observed pattern identities.
* Symbolic absent identities and their multiplicity.
* Distinct truth/validity states and state-pair products covered.
* Tree-node products visited, certified products and scored metric regions.
* Actual preparation/scoring time, workers, measured memory and output bytes.
* Whether every captured metric or only retained representatives received an
  independent chronological replay.

Dividing a vast logical count by runtime measures logical coverage throughput.
It is not the rate of independently materialized patterns, distinct trading
signals or independent chronological backtests. Most full high-order patterns
can be absent from a finite dataset, making the symbolic complement large. A
trillion-address completed domain therefore needs both an exact coverage proof
and transparent physical-work counts.

The independent verifier reconstructs canonical window patterns from the source
OHLC, recomputes domain counts with arbitrary-precision arithmetic, checks each
catalogue and membership record against bank masks and weights, validates the
symbolic complement, and checks captured product masks and disjoint weighted
coverage. Captured full-risk metrics are compared with an independent sequential
cash/share ledger. Summary-only verification must explicitly identify the
smaller retained metric set it can replay.

The resulting maximum is a retrospective systems/discovery result. Exact
enumeration, exact predicate equivalence and a correct ledger do not establish
out-of-sample profitability. Data periods, costs, selection protocol and any
independent later replay remain separate research choices.

## 13. Native interfaces

`src/geometry.rs` owns the standalone algebra: mode parsing, canonical patterns,
reusable endpoint encoding, exact domain counts and bounded exhaustive small
catalogues. `src/geometry_run.rs` owns geometry preparation and fast qualifiers.
`src/geometry_cli.rs` owns command routing and frozen chronological replay.
`src/dense_run.rs` owns the shared prepared-bank execution path. Existing dense,
joint and numerical commands retain their existing contracts.

`GeometryPattern::from_ohlc` accepts rows in `[open,high,low,close]` order;
`from_endpoints` accepts `[low,body_low,body_high,high]`. `GeometryEncoder` reuses
storage over equal-width windows. `boundary_cmp` reads any labeled endpoint
comparison, including nonadjacent candles. `count_domain` returns the checked
full count, while `count_domain_by_levels` exposes its distribution.
`enumerate_patterns` supports a caller-supplied output limit and
`first_unobserved_by` finds a legal missing representative after inspecting at
most the number of observed identities plus one. Full large-domain enumeration
is not a preparation step.

## 14. Configuration and logical address grammar

A configuration is UTF-8 `key=value` text with blank lines and `#` comment lines.
Unknown or duplicate keys are rejected. This is a complete example:

```ini
version=1
data=data/btc4h/discovery.csv
interval_seconds=14400
start=2024-01-01
end=2025-01-01
mode=oriented
windows=0,1,2;0,2,4
qualifiers=plain,persist:2,recent:3
rules=(and s0 s1);(or s0 s1);(and s0 (not s1))
allow_same_bank=false
numeric_mib=64
bank_mib=128
tree_mib=256
prepare_mib=128
task_states=128
max_task_nodes=100000000
fee_bps=10
slip_bps=10
```

Dates are Gregorian UTC midnights. Each semicolon-separated window is one bank;
its comma-separated offsets are nonnegative bar lags in strictly increasing
order beginning with zero. Thus `0,1,2` encodes current, previous and two bars ago
in that order; `0,2,4` selects current, two bars ago and four bars ago. Intermediate
candles still exist in the input timeline. Sparse selection does not compress
time or assert anything about their geometry.

Duplicate windows are rejected. A window has at most nine candles and maximum
lag 100,000. A configuration has at most 128 banks, sixteen distinct qualifiers
and 128 rule templates. At least two banks are required when same-bank pairing
is disabled. The qualifier window is in `1..100000`. Rule templates use `s0`,
`s1`, `(and X Y)`, `(or X Y)` and `(not X)`, must reference both slots, and must
be pointwise above the qualified leaves. Temporal operators above a compound
rule remain outside this certificate path.

`numeric_mib` bounds each scorer's existing executor workspace even though this
source has no numerical feature DAG. It is at least sixteen MiB. `bank_mib`,
`tree_mib` and `prepare_mib` are each at least one MiB. `task_states` is in
`1..4096`; `max_task_nodes` is positive. These are explicit failure limits, not
a claim that every accepted domain finishes within a fixed elapsed time.

For bank `a`, let `P_a` be the complete pattern count and let `Q` be the number
of declared qualifiers. Its logical condition count is `P_a*Q`. If there are `R`
rule templates, the full strategy count is:

```text
R * sum over allowed ordered bank pairs (a,b) of (P_a*Q)*(P_b*Q)
```

When `allow_same_bank=false`, only `a!=b` pairs are included. When it is true,
same-bank choices are also independent and include choosing the same complete
pattern in both slots. Slot identity and rule-template identity are retained
even when two addresses compute the same positions.

The default `smoke` example uses oriented two-candle windows `0,1` and `0,2`,
the plain qualifier and the three displayed rules: **333,193,824** logical
addresses. The default `trillion` example above has
**55,851,217,669,989,216** logical addresses. These are exact declared-domain
counts; inspection alone does not execute either domain.

## 15. Commands

The native package remains dependency-free and builds with Rust 1.63 or later.
Exact domain counting needs no market data:

```sh
cargo build --release --locked --offline
./target/release/filang geometry-count --bars 2 --mode unoriented
./target/release/filang geometry-count --bars 5 --mode oriented
python3 scripts/verify_geometry.py --self-test
python3 scripts/verify_geometry.py --counts 9
```

Create and inspect an explicit experiment:

```sh
./target/release/filang geometry-example --out runs/geometry.cfg \
  --profile trillion --data data/btc4h/discovery.csv \
  --start 2024-01-01 --end 2025-01-01
./target/release/filang geometry-inspect --config runs/geometry.cfg
```

`geometry-example` creates a new configuration file and refuses to overwrite
one. Its optional `--profile` is `smoke` or `trillion`. Data, dates, interval,
mode, windows, qualifiers and rules can be overridden with `--data`, `--start`,
`--end`, `--interval-seconds`, `--mode`, `--windows`, `--qualifiers` and `--rules`.
Values containing semicolons, spaces or parentheses must be shell-quoted.
`geometry-inspect` reports `PLAN_ONLY` and explicitly leaves physical work
data-dependent.

Preparation can be inspected before the sweep. Keep backend, certificate and
capture settings the same between preparation and resume:

```sh
./target/release/filang geometry-prepare --config runs/geometry.cfg \
  --out runs/geometry --workers 4 --backend auto \
  --certificates true --capture true
./target/release/filang geometry-sweep --config runs/geometry.cfg \
  --out runs/geometry --resume true --workers 4 --backend auto \
  --certificates true --capture true
python3 scripts/verify_geometry.py --run runs/geometry
```

Alternatively run `geometry-sweep` directly into a fresh directory. Its other
options are `--max-tasks N` to pause after N newly committed tasks and
`--resume true` to continue. Zero is the default unlimited task count.
`--certificates false` runs the dictionary leaf-pair control. `--capture false`
is the default summary policy. Changing worker count is permitted on resume;
changing context-bound data, engine, raw configuration, backend, certificate
mode or capture policy is not.

The verifier needs only the Python standard library. `--ledger auto` uses the
existing independent C cash/share reference when a C compiler is available;
`--ledger python` performs the chronological reference directly in Python.
`--ledger c` explicitly requires the C reference. Compilation and verification
are outside native benchmark timing. The reference compares finite metrics
with absolute tolerance `1e-7` and relative tolerance `1e-9`, matches undefined
metric status, and requires exact trade and period counts. This is numerical
parity, not a claim of bit-identical floating-point arithmetic across engines.

Captured verification checks every emitted metric region. It bounds a task's
physical state-pair coverage table at 4,000,000 pairs by default; use
`--max-task-state-pairs N` to set an explicit alternative. `--metric-cache N`
bounds retained reference metric cache entries. `--out PATH` writes an additional
JSON report, and `--data CSV` permits a relocated source only when its digest
still matches. The normal report is `verification/geometry.json` inside the run.

For matched timings with all verification outside the timer:

```sh
python3 scripts/benchmark_geometry.py --config runs/geometry.cfg \
  --out runs/geometry-benchmark --repeats 3 --workers 4 --capture
```

The benchmark runs scalar leaf pairs, scalar certificates, native-backend
certificates and native parallel certificates on the identical domain. Omit
`--capture` only when a summary-only metric audit is intended. Reports retain
each command, engine/configuration identities, verification receipts and
physical-work counts. Timing includes setup, hashing and durable native output.

Replay the frozen winner as two concrete patterns on a separate, explicitly
declared period. The evaluation CSV must include causal history and end exactly
at the new end-exclusive boundary:

```sh
./target/release/filang geometry-evaluate \
  --data data/btc4h/evaluation.csv \
  --selection runs/geometry/best-geometry.tsv \
  --start 2025-01-01 --end 2026-09-28 \
  --interval-seconds 14400 --fee-bps 10 --slip-bps 10 \
  --out runs/geometry-later
python3 scripts/verify_geometry.py --evaluation runs/geometry-later \
  --data data/btc4h/evaluation.csv
```

The dates in these commands identify example datasets; they do not establish
that a new experiment has been completed or that its later period was untouched.
`geometry-evaluate` reads the adjacent `best-rule.txt` and verifies both selection
sidecar checksums. It reconstructs fresh pattern predicates from the new OHLC
and uses the ordinary chronological `Market` ledger. It never reuses sample
aliases from the discovery banks.

## 16. Emitted artifacts and decoding

Unless explicitly described as plain text, an artifact consists of its body
followed immediately by a 64-byte lowercase ASCII SHA-256 of that body. There is
no extra newline before or after this checksum footer. Binary integers and
floats are little endian. Decimal `u128` counts in JSON and TSV are strings or
text digits and must not be parsed through a floating-point number.

| Artifact | Meaning |
|---|---|
| `experiment.cfg` | Plain exact raw configuration; part of context identity |
| `context.chk` | Sealed 64-byte ASCII context digest |
| `banks/patterns-XX.tsv` | Sealed explicit observed identities and symbolic complement representative |
| `banks/members-XX.tsv` | Sealed pattern/qualifier-to-state memberships and multiplicities |
| `banks/bank-XX.bin` | Sealed truth/validity state dictionary, format `FDBANK01` |
| `banks/preparation-XX.json` | Plain preparation statistics, hash-bound by its marker |
| `banks/prepared-XX.chk` | Sealed `FGPREP01` preparation commit and domain metadata |
| `tasks/task-NNNNNNNN.chk` | Sealed `FDTASK01` task coverage, work, digest and winner |
| `tasks/task-NNNNNNNN.boxes` | Sealed 128-byte region records, only with capture enabled |
| `summary.json` | Plain completion, logical/physical counters and current best |
| `best-geometry.tsv`, `best-rule.txt` | Plain concrete frozen candidate with `.sha256` sidecars |
| `best.json` | Plain selected coordinates, explicit patterns, metrics and sample alias context |
| `verification/geometry.json` | Independent verification scope, counts and discrepancies |

The pattern catalogue has columns `id`, `kind`, `multiplicity`, `pattern`.
Observed IDs are assigned by first chronological occurrence in the full causal
decision prefix, beginning at zero. Each has kind `observed` and multiplicity
one. If the full domain is not observed, the final row has kind `unobserved`,
multiplicity `total_patterns-observed_patterns`, and a canonical representative
outside the explicit observed set. This physical row represents the set
difference, not just that one representative's multiplicity in the domain.

The membership table has columns `pattern_id`, `qualifier`, `state_id`,
`multiplicity`. `qualifier` is its zero-based configuration index. There is one
row for each physical catalogue row and each qualifier, in that order. A bank's
representative coordinate is `(pattern_id,qualifier_index,0)`. The last
coordinate remains zero because this source has no numerical cutoff dimension.

The `FDBANK01` body starts with eight magic bytes, 64 context-digest bytes,
`u64` scored-row count and `u64` state count. Each state stores `u128`
multiplicity, three `u64` representative coordinates, then its truth and validity
word arrays. Each array has `ceil(scored_rows/64)` words. Bit `t%64` of word
`t/64` represents scored decision t. Truth is a subset of validity and unused
tail bits are zero. Entries are physically interned in preparation order.

The `FGPREP01` body contains eight magic bytes, 64 bank-context bytes, then four
64-byte hashes in bank/catalogue/membership/plain-statistics order. Twelve `u64`
fields follow: window size, maximum lag, decision-prefix rows, scored start
index, scored rows, windows encoded, observed patterns, catalogue records,
qualifier count, physical memberships, states and preparation payload charge.
The final three `u128` fields are total patterns, unobserved patterns and logical
conditions. The body is 472 bytes before its checksum footer.

Before pairing, state IDs are sorted lexicographically by their truth-word
tuples, then validity-word tuples, then original state ID. Region ranges refer
to this sorted order. A captured 128-byte region has four `u64` half-open range
endpoints `(left_lo,left_hi,right_lo,right_hi)`, one `u128` logical multiplicity
and ten `f64` metrics. The range denotes a complete state-set product; membership
and multiplicity map it back to the full logical pattern domain.

The metric order is net return percent, gross return percent, CAGR percent,
maximum drawdown percent, annualized Sharpe, entries, exposure percent, mean
period basis points, mean trade basis points and scored periods. JSON uses
`null` for undefined metrics; binary metric records retain nonfinite floating
values. A metric-region hash covers every region even in summary output.

Frozen evaluation emits plain `evaluation.json`, copies of the exact
`selection.tsv` and `rule.txt`, and `decisions.csv` with timestamp, validity and
active state for every scored decision. Its independent verification reconstructs
all those decisions and all ten metrics. This is distinct from the discovery
report's symbolic address coverage.
