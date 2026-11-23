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
