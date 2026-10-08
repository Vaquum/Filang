# Geometry information campaign

This is a finite, retrospective research campaign on the five immutable Vaquum
BTCUSDT snapshots ending on 2026-10-07. Its objective is to discover whether
qualitative candle geometry adds directional information and, in separately
specified work, whether that information can support an executable policy after
costs. Information gain and tradeability are different claims.

The historical data and earlier results have already been inspected. Nested
chronological evaluation limits fitting and selection leakage; it does not make
these observations fresh. Every results or performance attempt follows
[Law 1](../../CLAUDE.md): record the claim, criterion and method before the
attempt, then retain the complete result and the remaining scientific question.

| Record | Purpose | Evidence |
|---|---|---|
| [PR #22](https://github.com/mikkokotila/Filang/pull/22) | Predecessor complete-pattern direction experiment | [Protocol](../geometry_direction/protocol.json), [measured report](../../benchmarks/reports/20261008-bitcoin-direction/README.md) |
| [PR #23](https://github.com/mikkokotila/Filang/pull/23) | Campaign governance and experiment records | [Law and gate](../../governance/README.md) |
| [PR #24](https://github.com/mikkokotila/Filang/pull/24) | Round 1 additive geometry: numerical failure, inconclusive | [Frozen protocol](round1_protocol.json), [failure report](../../benchmarks/reports/20261008-geometry-information-r1-failed/README.md) |
| [PR #25](https://github.com/mikkokotila/Filang/pull/25) | R1a: full audited completion; directional information supported at 30m only | [Protocol](round1a_protocol.json), [method and replay](ROUND1A.md), [complete report](../../benchmarks/reports/20261008-geometry-information-r1a/README.md) |
| [PR #26](https://github.com/mikkokotila/Filang/pull/26) | R2: conditional payoff and cost-aware policy selection | [Frozen protocol](round2_protocol.json), [method and replay](ROUND2.md); no completed R2 outcome asserted here |

The Round 1 protocol was frozen at commit
[`b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd`](https://github.com/mikkokotila/Filang/commit/b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd),
with SHA-256
`abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a`.
Native causal feature preparation preceded that freeze. Real-data fitting and
predictive outcome evaluation must use the frozen specification and preserve
their implementation identities.

The first R1 attempt used clean implementation commit
`17457a99ce3d5b25cd6ff33deefd6ed3fec60bca`. All five timeframe workers reached
the original L-BFGS-B 1,000-iteration limit at a required weakly regularized G
candidate. The scientific outcome is **inconclusive**: 151 accepted/scored inner
candidates, five rejected inner candidates and five accepted B refits were
retained; no outer predictions or economic ledgers were produced. The full
failed-stage forensic audit passed, including all 161 fits and five rejected
parameter attachments. Audit PASS certifies those records, not the predictive
hypothesis. The launcher recorded 77.74459174997173 seconds to failed exit;
this is an operational receipt, not a performance comparison.

The numerical residue motivates a separately declared solver amendment, with
no retrospective relaxation of R1 acceptance and no removal of this attempt.
The frozen `outer_use` restriction is fold-relative, as its explicit schedule
specifies: a year's outer labels cannot fit/select that year's pipeline, but
may become already-past training/validation data for later chronological folds.
This explains the existing schedule without changing the frozen JSON.

R1a completed all 680 fits using the separately frozen exact Newton amendment.
Its full independent audit passed all 458,972 native keys, all fits and selected
predictions, paired inference, and 960 ledger replays. At 30m, pooled B-minus-G
log-loss gain was 0.0005687511 nats per binary observation, with 95% interval
[0.0002508591, 0.0008935404], Holm-adjusted p=0.00249875 and three of four
positive outer years. The 2026 effect was negative. None of the other four
timeframes passed every frozen information condition.

Every selected G fixed-threshold annual policy lost money at primary costs, and
all five G aggregates also lost at the reduced-cost scenario. At 30m, G's gross
log return was 0.47553 below B; its smaller net loss came from 7,984 fewer
one-way exposure changes. Buy-and-hold and unconditional controls were positive.
The resulting question is whether geometry can estimate conditional payoff
magnitudes well enough to select persistent, cost-aware exposure, with the same
opportunity and policy search available to B. The complete losses, annual
instability and prior exposure remain part of that next test's motivation.

1. **R1 — additive pooling.** Compare additive body/close-sign history against
   that history plus current-to-prior endpoint comparisons and wick-presence
   indicators. Use four nested calendar folds and five primary timeframe tests.
   The fixed probability-threshold long/cash ledger is an economic diagnostic;
   its outcomes do not select the R1 model or establish tradeability.
2. **R2 — limited economic selection.** The separately frozen protocol tests
   direct conditional log-return ridge models and six fixed hysteresis policies
   plus cash. Models select by earlier validation MSE; their policies select by
   earlier primary-cost net log return. Both choices then remain fixed through
   each outer year. The criterion requires improvement over B and cash, annual
   consistency, trading activity and complete independent audit. R2 cannot
   retroactively change R1 or select whichever outer result looks best.
3. **R3 — limited interpretable interactions, only if justified.** A separately
   frozen hypothesis may test a finite low-order interaction family motivated
   by the recorded R1/R2 residue. No unbounded architecture or threshold search
   is implied.

Stop when the three-round budget is exhausted or no concrete next hypothesis is
justified. Retain unsupported and inconclusive attempts. A positive historical
result still requires genuinely later, uninspected observations for fresh
confirmation and additional execution evidence before a tradeability claim.

`collect_round1.py` packages a complete, independently verified run into a
measured report, preserving exact compact evidence and the manifest identities
of larger prediction and ledger artifacts. The report must include every primary
timeframe, annual effects, selected models, cost scenarios, administrative
controls, limitations and the empirical residue; it must not present an
unaudited result as supported.
