# Experiment records

[Law 1](../CLAUDE.md) is the only governance law added here. Existing native
and direction-experiment CI is unchanged. The gate records whether a PR contains
a complete experiment or maintenance declaration; it does not certify a trading
edge or a performance improvement.

## One record per attempt

Use [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md).
Keep its exact headings, field names and four confirmation texts. Choose
`Type: results` for scientific/predictive results or `Type: performance` for
runtime, memory, throughput or eliminated computational work. Copy the entire
`## Experiment: A1` block for another attempt and give it a unique ID. Mixed
results/performance PRs need separate blocks, not a blended conclusion that
hides an unsuccessful experiment.

Each field can continue on subsequent lines. Supply prose outside quoted,
indented or fenced code; commands may accompany the prose in code blocks.
Every ordinary prose field needs at least 12 characters and no TODO/TBD/FIXME
or angle placeholder. `Outcome` is exactly `supported`, `not-supported` or
`inconclusive`. `Evidence` names an existing repository-relative file or HTTPS
artifact; Markdown links are accepted. CI does not fetch URLs or judge evidence's
scientific adequacy. Review verifies accessibility, provenance and interpretation.

All four boxes must be checked. Missing/altered confirmations, duplicate
IDs/sections/fields, placeholders, hidden examples and pending outcomes fail.
Negative and inconclusive results are valid. No `OVERRULED`, bot, label or draft
exemption exists. A draft may stay red until the record is complete.

`Next steps` names a concrete next hypothesis or task for a future PR, linking
an issue/PR when available. `None` alone is insufficient; explain why no follow-up
is warranted. Link predecessor PRs and evidence; do not erase failed attempts.
For a historical replay, retain the earlier test exposure. A new model does not
make previously examined market outcomes fresh evidence.

## Maintenance without fictional science

For genuinely non-experimental changes, replace the experiment block with:

```markdown
## Maintenance declaration

Reason: This change adds experiment-record enforcement only. It changes no
geometry computation, forecasting model, evaluation protocol or measured result.

- [x] This PR contains no results or performance attempt.
```

Maintenance cannot coexist with an experiment. Changes under `models/` or
`benchmarks/reports/` require a formal record, including deletion or renaming
out of those paths. A `perf:` title requires a performance block; `results:`
requires a results block. No universal title format is imposed.
For other paths authors declare intent and reviewers check it: paths cannot
reliably infer every scientific/performance claim. Editorial reinterpretation
of measured results is results work, not maintenance.

## Local gate

Python 3.11+; no additional dependencies. These commands run from the repository
root. Replace `N` with the PR number and `EXPECTED_HEAD` with its current full
commit SHA. The GitHub commands fetch metadata; they do not modify the PR.

```sh
python -m unittest discover -s governance/tests -v
mkdir -p /tmp/filang-experiment-record
gh api repos/mikkokotila/Filang/pulls/N > /tmp/filang-experiment-record/pr.json
gh api --paginate --slurp 'repos/mikkokotila/Filang/pulls/N/files?per_page=100' > /tmp/filang-experiment-record/files.json
python governance/experiment_gate.py \
  --pr-json /tmp/filang-experiment-record/pr.json \
  --files-json /tmp/filang-experiment-record/files.json \
  --expected-head EXPECTED_HEAD \
  --report /tmp/filang-experiment-record/gate.json
```

Exit 0 means compliance, 1 means an invalid/incomplete record, and 2 means the
gate could not validate its inputs/policy. Missing inputs and truncated changed
file lists fail closed. Renames include old and new paths. A stale head fails
rather than certifying a different revision. PR text is data, never executed.
Reports use schema `filang-experiment-gate-v1` and retain PR number, head SHA,
body/gate/policy hashes, changed-file count, classification and attempt outcomes.

## CI and current merge checks

`pr_checks_experiment` runs on PR opening, body/title edits, pushes, reopening,
and draft/ready transitions. It fetches current metadata and all changed files,
checks count completeness, and records the body hash and head SHA. The workflow
uses a read-only token, pinned actions, non-persisted checkout credentials and
ordinary `pull_request`, not privileged `pull_request_target` execution.

Each run retains the evaluated metadata, paths and verdict as an Actions artifact
for 90 days (or the platform's lower retention limit). Permanent evidence belongs
in committed reports and PR history. This is not an immutable ledger or proof of
preregistration, classification, scientific validity or complete disclosure.

Before an authorized merge, the operator verifies passing current-head native CI
and `pr_checks_experiment`, a complete live PR record, and independent agent review
with blocking findings resolved. Recheck the head and use that expected SHA in
the normal merge request; verify the resulting merge. A substantive push receives
current-content review and fresh checks. Agent review is not represented as a
GitHub approving review, and the procedure does not bypass effective protection.

### Hosted enforcement status: proposed, not deployed

The file [.github/rulesets/experiment-record.json](../.github/rulesets/experiment-record.json)
is a **proposed, disabled configuration**, not a live protection snapshot.
On 2026-10-08 the ruleset API returned HTTP 403 with a plan limitation for this
private repository. The separate branch-protection read returned HTTP 403 because
the integration could not access it. We therefore cannot attest to effective
server-side branch protection or claim `pr_checks_experiment` is a hosted required
check. No remote ruleset or branch-protection setting was changed by this adoption.

The current private-repository plan did not provide the requested server-enforced
ruleset capability. Until deployment is available and explicitly verified, the
operator performs the merge checks above. The disabled proposal describes the
future scope: only `main`, only this additional check from GitHub Actions, no
bypass actors, and branch-up-to-date strictness. Enabling it would require a
separate permitted configuration change followed by verification of live settings;
committing this JSON alone has no server-side effect.

The workflow must be present in the tested PR tree. Open PRs need the governance
files from `main` before this new check can run. Missing checks do not satisfy
the operator's merge procedure. Existing checks and any other effective controls
continue to apply.

## Pattern provenance and adaptations

Reference inspected at
[`velocinbio/VLPLang@11320f167db3ab1649f3740a1ef6719a398e90e7`](https://github.com/velocinbio/VLPLang/tree/11320f167db3ab1649f3740a1ef6719a398e90e7):
`CLAUDE.md`, `AGENTS.md`, `governance/README.md`, `experiment-policy.json`,
`experiment_gate.py`, `tests/test_experiment_gate.py`, the PR template,
`pr_checks_experiment.yml` and scoped ruleset snapshot. VLPLang in turn credited
`Vaquum/new-repository-template@fa7bf92caab5bb8d7f73120d4dc3526fd86c0348` for the
law → deterministic gate → template/tests → required-check pattern.

Filang retains the exact experiment fields and confirmation texts. Adaptations
are repository names and examples, the report schema name, explicit independent
agent review/current-head merge procedure, and the disabled undeployed ruleset
status with matching contract tests. VLPLang's live organization approval rules
and other repository laws are not copied or implied to be active here.

`governance/experiment-policy.json` is the control surface. Contract tests bind
the law, policy, template, workflow events/check name and proposed ruleset.
No geometry-engine source, dataset, frozen-model identity or measured result
depends on this directory. This adoption is maintenance, not a new scientific
or computational-performance attempt.
