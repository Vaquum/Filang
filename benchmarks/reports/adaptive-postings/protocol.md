# Adaptive postings performance protocol

## A1. Dense postings as packed bitmaps

**Claim.** Adaptive postings preserve exact g1 output and substantially
reduce dense count time while retaining the sparse workload budget.

**Baseline.** Filang main at `9ae049d1d56f3e41a046192f1afbdb8050ae05ac`.
Use matched Rust 1.100.0 release builds on the same Apple-silicon host.
Run five fresh-process pairs in alternating order.

**Workloads.** Use one million mostly identical bars with gaps and all
five axes in a width-24 chained match. Exercise one absent match as a
correctness control. On the held 66,000-slot Cube archive from #77, use
widths 2, 4 and 24 with chained readings. Measure preparation and a
repeatable corpus of present and absent counts with all five axes.
Record bounded chronological position pages and ternary classifications
as well as counts. Compare exact receipts at each width across every
pair. Time from loaded recording to prepared width separately from warm
count work. Record process peak RSS and the theoretical posting payload
for the measured Cube keys separately.

**Decision.** Require exact parity and at least 20x lower median dense
warm count time. On Cube require median preparation and warm corpus time
at every width to stay within 15% of the corresponding base p75.
Measure the released worker on the same archived Cube data in five
fresh Chromium profiles with the #77 varied-arrival trace. Verify
exact oracle counts and report input-to-frame and worker-plus-DOM p95s
separately. The frame target stays at 16.7 ms.
