# Query bench engine proof

## A1. Batch suggestion counts

Using the frozen Query CSV, the 24-question vocabulary corpus agreed with
the JavaScript oracle, including the four starting questions and all 16
offers appended to the breakout question. Across five fresh Node V8
processes, the 16 uncached counts took 14.543 ms at the pooled median
in a single batch and 21.064 ms using individual Study calls. The
decrease was 31%. The four full Study presets took 8.023 ms at the
median. The benchmark measures WASM computation and serialization on
a loaded tape. These times exclude worker transport and rendering.

Build the browser binding, set the pinned data directory, and run the
[Query contract check](../../../bindings/verify/query-contract.mjs).
The [protocol](protocol.md) and [raw samples](count-batch-a1.jsonl)
record the workload. For five fresh performance runs, pass
`base-first` and `candidate-first` to the script in alternating order.

## A2. Full workbench contract

With the complete Query contract, all 16 answers remained identical.
The pooled median was 17.247 ms for one count batch and 23.658 ms for
individual Study calls, a decrease of 27.1%. All four full presets ran
in a median of 8.747 ms. Each of five fresh Node 23.10.0 processes ran
five alternating pairs on this macOS arm64 host. The timings include
WASM computation and binding serialization on the loaded, pinned tape.
See [all A2 samples](count-batch-a2.jsonl).

The semantic check compared all 28 questions with the JavaScript
oracle, including retained reclaim evidence after filtering and the
manifest's calendar, candle and extension pins. Close explanations
report the same evaluator facts. Outcome and frozen reclaim
explanations were also checked for exact text. Chrome exercised the
actual module worker. The Query handoff and the Cube protocol stand-in
reproduced the pinned counts through the built binding.
