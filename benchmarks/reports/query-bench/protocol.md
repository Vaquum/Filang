# Query benchmark contract protocol

## A1. One worker request for suggestion counts

On the pinned Query recording, the Rust engine must return the same
matching-close counts as existing Query evaluation for all four bench
presets, the extra supported clause forms in #80 and the bench's offer
list applied to a starting question. Invalid questions have individual
diagnostics. Existing Study replies retain their legacy bytes.

Compare one count-only batch through the browser binding with the same
number of existing individual WASM Study calls on the same release and
recording. The working benchmark has 16 uncached questions per simulated
keystroke. Also time the four presets through existing Study. Measure
warm compute plus binding serialization, with source load and calendar
setup excluded. Run five alternating pairs in fresh processes. Require
identical counts, at least a 20% lower median elapsed time for the
batch, and report preset timing independently. Record the exact input
digest, runtime and samples. Use the JS study oracle separately for
semantic parity.
