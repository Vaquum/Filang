# Repository law

This is the canonical law for every contributor, human or automated.

## Law 1 — Every results or performance attempt is a recorded hypothesis test

Every PR that attempts or reports a change to scientific/predictive **results**
or computational **performance** must describe each attempt in its PR body:

1. **Hypothesis:** a falsifiable claim, scope, baseline, metric and decision criterion.
2. **Experiment:** what was actually done, reproducible evidence, and deviations
   from the plan. Results experiments identify dataset/endpoint/splits and prior
   test exposure. Performance experiments identify workload, hardware, repetitions,
   timing/memory boundary and correctness/parity checks.
3. **Result:** observations against the criterion, with an explicit `supported`,
   `not-supported`, or `inconclusive` conclusion. Retain negative findings and
   uncertainty; successful execution alone is not a supported hypothesis.
4. **Residue and next steps:** unresolved questions, failures and limits, followed
   by concrete follow-up tests/changes for future PRs, or a justified decision to stop.

Each attempt has a unique ID, a `results` or `performance` type, all four
sections, and all four completion checkboxes checked. Multiple attempts,
including mixed results/performance work, need separate complete blocks.
The PR is not complete until the record is complete. No author, bot, label or
`OVERRULED` marker exempts an experimental PR. *(pr_checks_experiment)*

Write the hypothesis and planned method before running the experiment. Leave
completion boxes unchecked while incomplete; a draft can therefore have a red
gate. Afterwards, record what was actually done, observations, and deviations.
Do not rewrite a failed hypothesis into a success or hide abandoned attempts.
Link predecessor PRs and retained commit/report artifacts so later PRs continue
the record. Older experiments may be transcribed retrospectively, but must link
the original protocol and must not claim new preregistration.

A genuinely non-experimental PR may instead use an explicit checked maintenance
declaration with a substantive reason. It cannot also contain an experiment,
change `models/` or `benchmarks/reports/`, or use a `perf:`/`results:` title.
Reviewers must reject false maintenance classifications even when a path-based
check cannot infer intent. Documentation-only performance claims are still
performance attempts. See [the format and enforcement](governance/README.md).

The deterministic gate fails on incomplete records and fails closed when its
inputs or policy cannot be read. Tests bind the written law, policy, template,
workflow and proposed check configuration. Existing numerical CI is unchanged.
The workflow adds `pr_checks_experiment`; it is not currently established as a
server-required status check. The proposed ruleset is disabled and not deployed.

CI checks structure, checked attestations and evidence references. It cannot
prove scientific truth, statistical power, truthful classification,
preregistration timing or complete disclosure. Those are review responsibilities.
Negative results may pass. PR edit history, committed evidence and gate snapshots
preserve provenance; editable Markdown is not a cryptographically immutable ledger.

## Current merge procedure

For an authorized merge, require a complete current-head experiment or maintenance
record, passing existing CI and `pr_checks_experiment`, and independent agent
review with blocking findings resolved. Verify the PR head has not changed and
pass that expected head to the normal merge operation. Verify the resulting merge
before starting the next round. A new push requires review and checks for its
current content; neither a previous verdict nor this local procedure bypasses
any effective GitHub protection. This procedure does not create a GitHub approval.

The ruleset API reported a plan limitation for this private repository during
adoption, and the branch-protection read was denied to the integration. We cannot
attest to server-side branch protection. These limits and the proposed future
check configuration are recorded in [governance/README.md](governance/README.md).

## Scope and source of this pattern

Adapted from `velocinbio/VLPLang@11320f167db3ab1649f3740a1ef6719a398e90e7`:
`CLAUDE.md`, `AGENTS.md`, the PR template, policy, deterministic gate, contract
tests, workflow and scoped ruleset. Its design reference was
`Vaquum/new-repository-template@fa7bf92caab5bb8d7f73120d4dc3526fd86c0348`.
The adopted pattern is one canonical law, a deterministic gate, contract tests,
and explicit merge checks. No issue-label, versioning, named review-authority,
lint, coverage or release laws from those repositories are imported.
