# Filang study execution

The builder and CLI share the lexer, grammar, type checker, signature registry,
versioned definitions and extension tests under `study/src`. They resolve
scalars, vectors and finite choices before compiling checked expressions to a
bounded DAG. Composer's pinned comparison trees supply the candle names and
rules. Agents add compositions by authoring artifacts with typed parameters
and recorded acceptance cases. The runtime performs deterministic lookup,
checking and execution.

`POST /api/filang/evaluate` accepts a JSON object with `query`, source and
calendar SHA-256s in `source` and `calendar`, optional `candidate` (the
zero-based candidate index), and optional `extensions` of `{text,sha256}`
objects. Without a candidate index it evaluates the batch. A single result
exposes `anchors`, `eligible`, `unknown`, `counts`, and `rows` with UTC
close timestamps, group keys and per-horizon outcomes. A batch wraps the
results and candidate labels. `work` declares the number of candidates,
unique compiled nodes, rolling windows prepared, and G1 window scans.

The Node process compiles to a private, bounded `filang-study-v1` protocol.
One worker loads its exact integer-cent source and session table for the
lifetime of the process. The worker validates the DAG, reference order,
types and operator arguments. It reuses packed masks across the batch's
identical nodes, shares the rolling high and low for a fixed lookback, and
uses Filang's existing G1 encoder and compact key to share complete
windows of up to ten bars. For larger G1 windows it uses the native
encoder directly.

- A present candle is available at its close. A missing candle retains its
  grid slot. An incomplete G1 or named pattern window is unknown.
- Studies use strong Kleene Boolean logic. Known false decides conjunction,
  and known true decides disjunction. A known false anywhere in an elapsed
  persistence window disproves it. Only true context admits an eligible
  close. A qualifying close appears once, including overlapping patterns.
- Candles and ratio thresholds compare exact ticks. Sessions use the pinned
  calendar. A completed higher-timeframe bar requires every constituent
  bar in that UTC-aligned frame.
- Outcomes are observed from close to close at exact grid horizons. An
  absent interior endpoint is unknown. An endpoint past the recording is
  censored. Outcomes may never enter a detector or context clause.
- The browser's deterministic preview also provides per-clause explanations.
  The service checks all selected matches, eligible closes, unknowns,
  groups and outcome cells against native evidence before saving.

Interactive requests are bounded at 64 candidates, 2,048 plan nodes and a
64 MiB budget for retained native series. The service bounds the input tape
and materialized output. This runner covers declared studies with row output.
Large research domains continue to use the existing native factorized
discovery commands and their exact coverage contracts. The study validity
policy and observational returns are separate from research rule validity
and the next-open backtest ledger. A successful study or batch gives no new
large-scale performance result.
