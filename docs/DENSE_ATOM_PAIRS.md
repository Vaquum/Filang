# Dense independent atom pairs — implementation contract

This continues issue #18. The two condition slots independently choose every
period/source/component setting from the existing ten-family neighborhoods.
This is not the three coupled variants of 0.7 and does not enlarge thresholds to
inflate the density comparison. Numerical output and full-risk execution retain
the existing atom, warmup, validity, next-open, cost and metric contracts.

## Exact domain and source

Each family has three principal periods and nested 3, 11 or 41-point source and
component coefficient grids. The full grid is a=-0.01..0.01 by0.0005 and
b=0..0.1 by0.0025; the smaller grids are exact subsets of those ticks. Both
conditions have independent coordinates. Qualifiers default to plain/persist2/
recent3. Templates default to AND, OR and AND-NOT; family tags must differ.
Threshold ranges are unchanged, with 20,001 points at every density.

The authoring source generates one bounded source/window stripe, sharing its
numerical dependencies across component coefficients through paged::Executor.
It does not commute affine arithmetic through rolling statistics. There is no
standalone-profitability shortlist. Every numerical parameter construction is
visited; equality is subsequently scoped to the scored data and qualifier.
The full domain exceeds u64: checked u128 counts are exported as decimal strings.

## Cross-atom factorization

Generic dense_cells preparation lowers monotone temporal threshold qualifiers
to rolling extrema with exact full-window validity. The extrema select input
values rather than reassociate arithmetic. Warmup uses the entire causal prefix,
then only the declared scored interval is retained. General Eq/Ne/onset cell
preparation has an explicit reference fallback; the first dense authoring front
end deliberately permits only monotone leaf qualifiers.

A predicate-state dictionary interns exact truth AND validity words across
atom coordinates, qualifiers and threshold cells. Hashes index candidates;
full words are checked before reuse. A streamed membership file maps each
(atom,qualifier,[cutoff_lo,cutoff_hi)) to its state. Program identity is not erased.
Counts, first representative coordinates and disjoint per-program coverage are
retained. One family is prepared at a time, with a declared dictionary budget.
This is bounded family partitioning, not arbitrary automatic disk spill/eviction.

Generic signature trees aggregate all/any truth and validity over state sets.
A two-slot pointwise rule compiles to its four-entry truth table. Bounds determine
whether an entire product of two signature sets has exactly one final position
path. Such a product is scored once; otherwise it is subdivided until exact.
These are exact Boolean envelopes, not PnL bounds, approximation or pruning.
Leaf-only and envelope modes use the same original full-risk scoring backend.
The certificate does not apply to temporal operators ABOVE a compound rule;
those remain supported by the existing general strategy-sweep path instead.

## Restart and output

A single-writer OS advisory lock guards each run. Bank membership and dictionaries
are immutable, checksum-bound artifacts. A family commit marker is written only
after its files are flushed and renamed. Pair tasks partition the left signature
tree into bounded blocks and visit the whole right tree. Each task starts its own
execution state, making successful task outputs deterministic across restart.
Completed task records bind data, code, raw domain config, backend, plan and output
policy. Reuse verifies checksums; modified contexts or committed data fail closed.
Uncommitted staging artifacts are recomputed, never counted as completed work.
This is a sequential resumable controller, not a distributed or adaptive one.

Every file uses an appended SHA-256 of the preceding bytes. The native writer
flushes, calls File::sync_all, renames on the same filesystem and syncs the parent
directory. Linux/macOS process-interruption behavior is tested; no claim is made
about all filesystems, hardware power-loss guarantees or authenticated integrity.
Summary mode computes and hashes every metric region, retaining coverage and the
best exact representative, without materializing every result. Capture mode also
writes task .boxes files. Member-set products can be nonrectangular in the original
atom coordinates; dictionary membership plus tree ranges defines their coverage.

Banks have independently bounded payloads; at most two family dictionaries and
trees are needed for pairing. They fail if the declared budgets cannot fit them.
The numeric, bank and tree budgets are not total-process RSS caps. Runtime and
output can still grow with genuinely different predicate states. A per-task
physical-node budget fails without committing incomplete work.

## Research boundary

The first scaling workload uses the already-inspected BTCUSDT4h 2024 interval,
with causal history,10bps fees+10bps slippage per side, and all ten metrics.
The best return is an in-sample descriptive maximum, not a promoted strategy.
No walk-forward or unseen-data improvement is established by this systems run.
Independent-vs-joint tuning inside chronological boundaries is a separate study.

## Commands

```
filang dense-example --out runs/dense41.cfg --coefficients 41
filang dense-inspect --config runs/dense41.cfg
filang dense-prepare --config runs/dense41.cfg --gate GATE --out runs/dense41
filang dense-sweep --config runs/dense41.cfg --gate GATE --out runs/dense41 --resume true
```

`--max-tasks N` pauses after N new committed tasks; repeating with `--resume true`
continues. Default zero means no task-count limit. `--certificates false` performs
leaf-pair enumeration over the SAME exact predicate dictionary. `--capture true`
retains all product-region metric records and must be fixed at run creation.
The current predicate dictionary source supports the ten authoring families;
dense_cells, dense_bank, dense_tree and the existing numerical/rule/ledger engine
are generic and tested on anonymous inputs. All old commands remain available.

## Binary layout

A bank body starts FDBANK01,64-byte context hash,u64 row count,u64 state count.
Each state is u128 multiplicity,three u64 representative coordinates,truth words,
validity words. A membership body starts FDALIAS1,64-byte context,four u64 fields
(atom count,qualifier count,cutoff count,scored rows),then five-u64 records
(atom,qualifier,lo,hi,state_id). All integers and floats are little endian.

A captured product body consists of128-byte records: four u64 endpoints selecting
sorted state ranges in the left/right banks,u128 logical multiplicity,ten f64
metrics. State ordering is lexicographic truth words,then validity,then original
state ID. Task checkpoints specify its family pair/template and retain the best
coordinates,complete weighted coverage,work counters and result digest.
