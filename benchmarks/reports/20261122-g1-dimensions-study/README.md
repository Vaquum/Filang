# STUDY-DIM-OFF: the study engine's speed with every g1 dimension off

The study engine learned to read g1 dimensions (`docs/G1_DIMENSIONS.md`). This report asks one thing: is a
question that switches no dimension on answered as fast as before?

## Protocol

Written before the run it is judged on. The criterion comes from section 10 of the contract, which was written
before the code: with every dimension off, the change is no slower than the commit it branches from. That
section names the Rust core's workloads; the study engine's workload below was chosen after the code was written
and before this measurement.

- **Hypothesis.** With no dimension part in a code, `exact_g1` and `chained_g1` are answered no slower than at
  the base commit `d01a251`.
- **Workload.** 400 questions on the pinned recording (BTCUSDT 15m, 14,496 bars): the 120 most frequent chained
  two-bar codes, the 120 most frequent chained three-bar codes, the 120 most frequent two-bar codes as recorded
  and the 40 most frequent four-bar codes as recorded, each asked with `measure close_return(after: 1h)`. One
  pass checks and runs all 400 on a fresh environment, so nothing is cached from the pass before.
- **Runs.** `bench_g1.mjs` makes two warm-up passes and nine timed ones in one process. Five rounds, each one
  process on the base commit and then one on this change, alternating: 45 timed passes a side.
- **Parity.** Both sides must report the same number of matches over the 400 questions.
- **Metric and criterion.** The median of the 45 timed passes on each side. Supported when the change's median
  is at or below the 75th percentile of the base's 45 passes. Not supported when it is above the base's slowest
  pass. Otherwise inconclusive.
- **Machine.** One Apple-silicon Mac with 10 cores, Node 23.10. The load average is recorded beside each run,
  because a run on a busy machine cannot be read.

```sh
export FILANG_STUDY_DATA=<a directory holding the pinned recorded-bars.csv, bars and activity>
node benchmarks/reports/20261122-g1-dimensions-study/bench_g1.mjs <checkout at d01a251>
node benchmarks/reports/20261122-g1-dimensions-study/bench_g1.mjs <this checkout>
```

## Runs that cannot be read

Two runs were made while the machine was heavily loaded by unrelated work. They are kept here and not used.
Both sides found 29,812 matches in each.

Three rounds, load average 15 to 19, before the Query-language additions of this change were written:

```text
before {"questions":400,"matches":29812,"ms":[398.6,416.4,496.8,674,475,638.6,424.5,551,407.5]}
after {"questions":400,"matches":29812,"ms":[491.7,492.6,800.8,1010.3,382.8,372.8,408.6,374.9,402.4]}
before {"questions":400,"matches":29812,"ms":[372.1,401.7,376.3,388.4,481.5,381,390.1,391.5,700.6]}
after {"questions":400,"matches":29812,"ms":[354,355.7,381.6,675.3,505.2,406.6,365.6,346,379.6]}
before {"questions":400,"matches":29812,"ms":[376.8,345.7,350.7,330.7,414.5,418.4,434.4,378.9,365.6]}
after {"questions":400,"matches":29812,"ms":[503.5,588.5,330.8,335.9,446.8,362.3,349.4,337.3,351.7]}
```

Five rounds, load average 118 to 122, on this change as committed:

```text
before {"questions":400,"matches":29812,"ms":[1767.4,1062.9,686,476.6,417.6,476.6,720.6,767.2,753.4]}
after {"questions":400,"matches":29812,"ms":[1798.3,2457.8,2229.9,2545.8,1687.3,1165,2321,1773.5,1746.4]}
before {"questions":400,"matches":29812,"ms":[482.9,758.7,1063.2,857.1,634.1,461,648.6,574.2,558.3]}
after {"questions":400,"matches":29812,"ms":[782.4,1259.3,634.5,1383.5,571.5,479.8,602.9,1645.2,611]}
before {"questions":400,"matches":29812,"ms":[459.9,576.4,470.9,458.1,545.6,1023.1,530.1,499.3,849.8]}
after {"questions":400,"matches":29812,"ms":[691.9,492.7,741.8,738.7,525,568.8,781.6,650.2,487.4]}
before {"questions":400,"matches":29812,"ms":[427.8,407.9,383.1,404.8,453.5,441,470.8,385,469.4]}
after {"questions":400,"matches":29812,"ms":[461.6,459.1,417.4,420.6,429.1,442.2,597.8,534.2,452.5]}
before {"questions":400,"matches":29812,"ms":[634.7,527.2,408.2,495,885.4,530,518.7,646.7,548.6]}
after {"questions":400,"matches":29812,"ms":[1898,1095.7,661.3,805.8,1827.2,2095.8,1270.7,721.6,756.3]}
```

The quietest of those rounds puts the change's median about 6% above the base's; the others scatter by a factor
of five. That is a reason to measure properly, not a result.

## Result

Not measured yet on a quiet machine. This section is completed before the pull request leaves draft.
