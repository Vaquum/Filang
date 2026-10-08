# R2 — conditional payoff and cost-aware policy selection

[PR #26](https://github.com/mikkokotila/Filang/pull/26) continues the
[audited R1a result](../../benchmarks/reports/20261008-geometry-information-r1a/README.md).
The complete [protocol](round2_protocol.json) was published before market fitting
at commit `9489c22556898603268fbad9124e0268f0d99852`, with SHA-256
`40162d6e1a6ced930bb8c8cfb578f6d9eb4935b7f2ef4ae37a363dc75e52d11d`.
An independent review cleared its scientific contract before publication.
Implementation drafts and synthetic checks preceded publication; market fitting
and outcome evaluation did not.

## Why this experiment follows R1a

R1a supported its direction log-loss criterion at 30 minutes only. That selected
geometry policy nevertheless had a lower gross log return than the sign-history
baseline, and every one of its 20 annual primary-cost ledgers lost money.
Fewer exposure changes reduced its net losses at several timeframes. These
observations leave a specific question: does geometry predict payoff magnitude
well enough to choose useful exposure after transaction costs?

R2 changes the response variable and policy selection procedure. The inputs
remain the exact qualitative geometry projections, with no price scale, return
magnitude, volatility, volume, indicator or learned encoding added as a feature.
It retains every timeframe, including those that failed R1a's information test.

## Conditional return model

After candle t closes, the target reference interval is the following complete
executable bar:

\[
y_t=\log\!\left(\frac{O_{t+2}}{O_{t+1}}\right),\qquad
\widehat\mu_t=a+X_t\beta.
\]

Every target must have the same ten consecutive past candles and two consecutive
subsequent bars as the earlier experiment. The target exit open must be strictly
before the applicable phase boundary. Exactly zero targets are included in
fitting and mean squared error. Future target validity never suppresses an
otherwise available causal forecast in the economic ledger.

B contains the unchanged body and close-return sign indicators. G adds the
unchanged current-to-prior endpoint comparisons and wick-presence indicators.
The candidate histories are n=2, 3, 5 and 10, with penalties 0.1, 0.01, 0.001
and 0.0001. All candidates use common ten-candle eligibility. G contains B but
has more columns, so the comparison does not match parameter capacity.

Each fit minimizes

\[
\frac{1}{2N}\lVert y-a-X\beta\rVert_2^2+
\frac{\lambda}{2}\lVert\beta\rVert_2^2.
\]

The intercept is unpenalized. Fixed binary columns remain unscaled, including
constant and zero-support columns. The implementation solves centered normal
equations with Cholesky, without jitter, a pseudoinverse, a substitute solver or
extra regularization. It then recomputes the objective and analytic gradient
directly from the fitting data. Acceptance requires finite quantities, successful
factorization and maximum absolute gradient at most 1e-10.

The full G10 Gram matrix and target cross-products can be reused for an exact
same fitting sample. Smaller systems are projected by feature names, because
shorter G histories are not contiguous prefixes of the full design. Statistics
reuse binds the source, columns, ordered rows, targets, count and phase bounds.
No coefficients or return statistics from an earlier experiment are reused.

## Chronological model and policy selection

The five pinned Vaquum BTCUSDT sources span 2020-01-01 through the exclusive
2026-10-08 endpoint, at 15, 30, 60, 120 and 240 minutes. For each outer year
2023, 2024, 2025 and partial 2026, the preceding calendar year is validation and
all earlier permitted years are inner training. The selected model is refitted
on all permitted data before its outer year. A later fold can use an earlier
outer year once that year is in its past; a fold cannot select on its own outer
outcomes.

B and G separately choose history and penalty by validation MSE. A tie within
1e-12 of the minimum prefers shorter history, then stronger regularization.
There are 640 required inner fits and 40 selected B/G refits. Every refit runs,
including when the subsequently selected trading policy is cash.

Policy selection uses forecasts from the selected **inner-training model** on
validation. It never uses a model refitted on those validation targets. The
unconditional control U uses its fitting sample's mean log return and receives
the same policy selection procedure; both its inner and pre-outer means are
retained.

Let f=0.001 and s=0.0002 denote the primary per-side fee and slippage. The exact
round-trip log-cost hurdle is

\[
k=-\log\!\left((1-f)^2\frac{1-s}{1+s}\right).
\]

The active policies are the Cartesian product of these thresholds:

| Entry threshold | Exit threshold |
|---|---|
| 0 | -0.5k |
| 0 | 0 |
| 0.5k | -0.5k |
| 0.5k | 0 |
| k | -0.5k |
| k | 0 |

Cash is a seventh candidate. While cash, enter when a finite signed forecast is
at least the entry threshold. While long, stay long when it is at least the exit
threshold. A forecast between the thresholds preserves the existing state. A
missing causal forecast requests cash after that missing history is known.

Select the largest primary-cost validation net log return. Within 1e-12 of that
maximum, prefer cash, then lower one-way turnover, higher entry, lower exit and
finally the stable policy identifier. The selected policy and refitted model
remain fixed through the outer year. Thresholds always use the primary k, even
when evaluating alternative cost scenarios. There is no re-selection under
zero, reduced or stress costs.

## Execution and economic controls

R2 retains the earlier long/cash spot accounting: no leverage, shorting,
borrowing, funding or cash yield. A closed-candle request executes at the next
observed opening. Missing bars delay the assumed fill; holdings carry the actual
opening-price change across the gap. Each phase begins in cash, imports no
pending prior-phase signal, and ends with the prescribed terminal liquidation.

A new signed-score adapter produces explicit exposure requests for the unchanged
audited ledger. Its 0/1 input is labelled `signal_request`; the original signed
forecast is retained separately. These values are not probability forecasts.
The independent audit reconstructs the state transitions directly from signed
forecasts using a cash/share account.

All 420 validation trials are retained: three forecasters, seven policies and
20 timeframe/year combinations. Outer evaluation retains 400 ledgers: selected
B/G/U, cash and buy-and-hold, four cost scenarios and the same 20 combinations.
The primary cost is 10 bps fee plus 2 bps slippage per side. The other scenarios
are 0/0, 5/1 and 20/4 bps. These are fixed scenarios, not a reconstruction of an
account's historical fees or actual market fills.

## Primary criterion and interpretation

The two effects are mean daily G-minus-B and G-minus-cash net log return. They
use every calendar day, including inactive days, with equal daily weight. A
paired circular block bootstrap preserves the four outer-year lengths and uses
the same indices for both comparisons. Seven-day blocks and 2,000 replicas are
primary; one- and 28-day blocks are sensitivity descriptions. Null centering
uses each comparison's global pooled daily mean, never separate annual means.

The per-timeframe p-value is the maximum of the two one-sided p-values, because
the claim requires both improvements. Holm adjustment then covers all five
timeframes. A timeframe passes only if:

1. Both pooled effects are positive.
2. Both individual seven-day 95% interval lower endpoints exceed zero.
3. The Holm-adjusted composite p-value is below 0.05.
4. At least three of the **same** four years have both positive annual effects.
5. G completes at least 20 outer round trips, including terminal liquidations.
6. Every required fit, prediction, selection, ledger and artifact audit passes.

The two intervals are individual intervals, not a simultaneous confidence
region. The trading-activity requirement is not an effective sample size or a
proof that a policy is unlike passive exposure. Buy-and-hold and U are mandatory
controls; the primary criterion does not establish that G beats either one.

All historical observations and prior outcomes have already been examined. A
supported criterion would be retrospective evidence for this selected pipeline
under the declared opening-price proxy. Fresh confirmation and real execution
evidence remain separate requirements for live tradeability.

## Reproduction and evidence layout

The producer accepts the same operational data/key roots and bounded worker/thread
settings as R1a. Run it only from the published, clean implementation tree:

```sh
.venv/bin/python experiments/geometry_information/run_round2.py \
  --data-dir /Users/mikkokotila/dev/Filang-direction/data/geometry-direction \
  --keys-dir /Users/mikkokotila/dev/Filang-research/runs/geometry-information-keys-v1 \
  --out runs/geometry-payoff-r2 \
  --protocol experiments/geometry_information/round2_protocol.json \
  --freeze-commit 9489c22556898603268fbad9124e0268f0d99852 \
  --workers 5 --blas-threads 2
```

The output directory must be fresh. Source files and native keys can be relocated
only while preserving their pinned identities. The execution receipt records
the actual command, clean implementation commit, imported source hashes, runtime,
thread controls, stage timings and peak memory. Timings are operational evidence;
R2 makes no matched speedup claim.

Each timeframe stores complete fit, choice and ledger JSONL records plus four
yearly numeric-array bundles and a member index. Large predictions and complete
ledger arrays remain sealed by file and array hashes. Compact reports retain all
coefficients, choices, metrics, source/native/runtime identities and the full
audit, with exact identities and replay instructions for the external bundles.
The original producer status stays unchanged after the audit. A report can join
those bytes to a successful independent audit; it cannot promote a partial or
failed run into a supported result.

The [campaign](CAMPAIGN.md) permits a final, separately frozen interaction family
only if the retained R2 residue justifies it. Unsupported and inconclusive
attempts remain part of the record.
