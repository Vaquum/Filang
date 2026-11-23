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

## A2. Replication with the full workbench contract

Repeat A1 on the full Query engine candidate. Use the same fixture, the
same four presets, the same 16 offers, and the same alternating calls.
Warm the same 25-question corpus before timing. Run five fresh processes
and compare the pooled medians. Require identical answers and a median at
least 20% lower for the single suggestion batch. Report both the full
preset median and the run boundary. These timings exclude browser-worker
transport, DOM and recording load.
