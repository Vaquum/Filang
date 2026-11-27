# Filang study execution

The browser engine and native study worker compile Filang source with the same
Rust checker. The older builder also uses the JavaScript checker under
`study/src` for editor diagnostics and candidate labels. The executable plan
carries distinct references for events, states, other predicates, prices,
activity axes and categories. Outcome horizons have their own type and enter
the plan only through `measure`. The compiler resolves scalars, vectors and
finite choices before execution.

Custom definitions use the same compiler. An artifact declares its event or
condition role, parameter types and domains. Its body must compile as a
Boolean predicate. The declared role applies at calls to the definition.
Filang checks default values at installation and supplied values at each call.
Pinned dependencies and recorded acceptance cases apply to each version.

`POST /api/filang/evaluate` accepts a JSON object with `query`, source and
calendar SHA-256s in `source` and `calendar`, optional `candidate` (the
zero-based candidate index), and optional `extensions` of `{text,sha256}`
objects. Without a candidate index it evaluates the batch. A single result
exposes `anchors`, `eligible`, `unknown`, `counts`, and `rows` with UTC
close timestamps, group keys and per-horizon outcomes. A batch wraps the
results and candidate labels. A direct `breach_reclaim` detector adds
`reclaim: {breach, reclaim, level}` to each match row, using UTC close
milliseconds and exact integer price ticks. `work` declares the number of
candidates, unique compiled nodes, rolling windows prepared, and ordinal window
scans. `medianWindows` counts distinct prior-median preparations.

The Node process sends source over the private, bounded
`filang-study-source-v1` protocol. One worker loads its exact integer-cent
recording and session table for the lifetime of the process. Request-local
definitions apply only to the current request. The worker validates the DAG,
reference order, types and operator arguments. It reuses packed masks across
the batch's identical nodes, shares the rolling high and low for a fixed lookback, and
uses Filang's ordinal geometry encoder and compact keys to share complete
price windows of up to ten bars. For larger price windows it uses the native
encoder directly. `exact_g1` and `chained_g1` also accept selected
[activity dimensions](../../docs/G1_DIMENSIONS.md) when the recording supplies
their counters.

- A present candle is available at its close. A missing candle retains its
  grid slot. An incomplete pattern window is unknown.
- Studies use strong Kleene Boolean logic. Known false decides conjunction,
  and known true decides disjunction. A known false anywhere in an elapsed
  persistence window disproves it. Only true context admits an eligible
  close. A qualifying close appears once, including overlapping patterns.
- Candles and ratio thresholds compare exact ticks. Sessions use the pinned
  calendar. A completed higher-timeframe bar requires every constituent
  bar in that UTC-aligned frame.
- Prior range levels and median ranges use a complete window ending one
  candle before the assessed candle. A breach opens on or inside the
  boundary and pierces it strictly. Its reference stays fixed until the
  first close strictly back inside. Offset zero includes the breach candle.
  An earlier recovery disqualifies the breach even when it fell before the
  selected minimum offset. Missing coverage can make the result unknown.
  When several breaches prove a reclaim at one close, the row keeps the
  nearest proven breach.
- Outcomes are observed from close to close at exact grid horizons. An
  absent interior endpoint is unknown. An endpoint past the recording is
  censored. Outcomes may never enter a detector or context clause.
- The browser's deterministic preview also provides per-clause explanations.
  The service checks all selected matches, eligible closes, unknowns,
  groups, outcome cells and direct reclaim evidence before saving.

Interactive requests are bounded at 64 candidates, 2,048 plan nodes and a
64 MiB budget for retained native series. The service bounds the input tape
and materialized output. This runner covers declared studies with row output.
Large research domains continue to use the existing native factorized
discovery commands and their exact coverage contracts. The study validity
policy and observational returns are separate from research rule validity
and the next-open backtest ledger. A successful study or batch gives no new
large-scale performance result.

## Type preservation checks

[Shared vectors](../verify/typing-vectors.json) exercise the same built-in and
custom queries across the native worker and browser engine. They also compare
the match count for a Composer drawing as a Filang query. Run
`node bindings/verify/type-preservation.mjs` after preparing the pinned study
inputs and building both engines. Set `FILANG_BASELINE_ENGINE_DIR` to the
browser package from an earlier checkout to compare study results, receipts
and explanations directly. The same setting enables a comparison across the
full Query verification corpus in `node query/verify/parity.mjs`.

`FILANG_BASELINE_NATIVE_ROOT` enables the direct comparison in
`node study/verify/native.mjs`. It points to the earlier checkout containing
its own compiler, worker and native executable. The baseline executable
defaults to `target/release/filang` within that checkout, or can be set with
`FILANG_BASELINE_NATIVE_BIN`. Both versions receive the same pinned data and
queries.
