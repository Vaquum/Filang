#!/usr/bin/env python3
"""Package exact compact evidence from an explicitly admitted audited R1-family run.

This module uses only the standard library. It never fits a model, reruns an
economic strategy, changes a scientific outcome, or edits the source run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


FREEZE_COMMIT = "b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd"
PROTOCOL_SHA256 = "abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a"
TIMEFRAMES = (15, 30, 60, 120, 240)
YEARS = (2023, 2024, 2025, 2026)

# These original constants and default profile remain unchanged: collect_failed
# imports them to preserve the historical R1 failure and its package identity.
ORIGINAL_PROFILE = {
    "attempt_id": "R1", "experiment_id": "btc-geometry-information-r1-additive",
    "label": "Round 1", "protocol_sha256": PROTOCOL_SHA256, "freeze_commit": FREEZE_COMMIT,
    "protocol_filename": "round1_protocol.json", "run_name": "geometry-information-r1",
    "report_name": "20261008-geometry-information-r1", "final_pr": 24,
}
PROTOCOL_REGISTRY = {
    PROTOCOL_SHA256: ORIGINAL_PROFILE,
    "cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34": {
        "attempt_id": "R1a", "experiment_id": "btc-geometry-information-r1a-newton",
        "label": "Round 1a — numerical amendment",
        "protocol_sha256": "cc13e36a818323d1ca488ca4c2af48775b47b267120a55c1011a6bf484191d34",
        # Published protocol freeze; no CLI/env bypass of this registry.
        "freeze_commit": "3df6416a2de59ac396617be49326a834c94aca92",
        "protocol_filename": "round1a_protocol.json", "run_name": "geometry-information-r1a",
        "report_name": "20261008-geometry-information-r1a", "final_pr": 25,
    },
}


def admitted_protocol(run: Path, identity: dict) -> tuple[dict, dict]:
    checksum = digest(run / "protocol.json")
    require(checksum in PROTOCOL_REGISTRY, "protocol hash is not admitted by the explicit registry")
    profile = dict(PROTOCOL_REGISTRY[checksum])
    freeze = profile["freeze_commit"]
    require(isinstance(freeze, str) and len(freeze) == 40 and all(c in "0123456789abcdef" for c in freeze),
            "protocol freeze commit has not been published in the registry")
    require(identity["protocol_sha256"] == checksum and identity["freeze_commit"] == freeze,
            "run does not bind the exact registered protocol and freeze commit")
    protocol = load_json(run / "protocol.json")
    require(protocol["attempt_id"] == profile["attempt_id"] and protocol["experiment_id"] == profile["experiment_id"],
            "protocol attempt identity differs from registry")
    expected = [protocol["amendment"]] if "amendment" in protocol else []
    require(identity["amendments"] == expected, "run amendment must equal the declared frozen protocol amendment")
    require(identity["deviations"] == [], "undeclared deviations cannot be collected as the frozen experiment")
    return profile, protocol


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def load_json(path: Path) -> object:
    def invalid(value: str) -> None:
        raise ValueError(f"non-finite JSON number {value} in {path}")
    return json.loads(path.read_text(), parse_constant=invalid)


def bounded(root: Path, relative: str) -> Path:
    raw = Path(relative)
    require(not raw.is_absolute() and relative not in ("", "."), f"invalid artifact path: {relative}")
    path = (root / raw).resolve()
    require(root in path.parents, f"artifact escapes run directory: {relative}")
    return path


def file_record(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |",
                       "| " + " | ".join("---" for _ in headers) + " |",
                       *("| " + " | ".join(cell(c) for c in row) + " |" for row in rows)])


def number(value: object, digits: int = 6) -> str:
    if value is None:
        return "—"
    val = float(value)
    require(math.isfinite(val), "non-finite report metric")
    return f"{val:.{digits}f}"


def percentage(value: object, digits: int = 2) -> str:
    return "—" if value is None else number(float(value) * 100, digits) + "%"


def outcome(gain: float, lower: float, holm_p: float, positive_years: int) -> str:
    """A completed audited result has only the frozen four-condition route."""
    return "supported" if gain > 0 and lower > 0 and holm_p < .05 and positive_years >= 3 else "not-supported"


def write_package(out: Path, copies: dict[str, Path], generated: dict[str, bytes], profile: dict | None = None) -> dict:
    """Validate destinations before writing; never replace differing evidence.

    Byte-preserved source records and newly generated files receive a separate
    package manifest. The manifest itself is sealed separately, avoiding a
    circular digest or rewriting the original producer manifest.
    """
    profile = ORIGINAL_PROFILE if profile is None else profile
    require(not set(copies).intersection(generated), "duplicate package destination")
    records = {name: {**file_record(source), "source_path": str(source)}
               for name, source in sorted(copies.items())}
    records.update({name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "generated": True}
                    for name, data in sorted(generated.items())})
    manifest = {"schema": "filang-geometry-information-report-package-v1",
                "freeze_commit": profile["freeze_commit"], "protocol_sha256": profile["protocol_sha256"],
                "files": records}
    manifest_bytes = json_bytes(manifest)
    generated = {**generated, "manifest.json": manifest_bytes,
                 "manifest.sha256": (hashlib.sha256(manifest_bytes).hexdigest() + "\n").encode()}
    expected = {**{name: row["sha256"] for name, row in records.items()},
                **{name: hashlib.sha256(data).hexdigest() for name, data in generated.items()}}
    for relative, checksum in expected.items():
        target = bounded(out, relative)
        require(not target.exists() or (target.is_file() and digest(target) == checksum),
                f"existing report artifact differs: {target}")
    out.mkdir(parents=True, exist_ok=True)
    ordered = sorted(set(expected) - {"manifest.json", "manifest.sha256"})
    ordered += ["manifest.json", "manifest.sha256"]
    for relative in ordered:
        target = bounded(out, relative)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".collect-", delete=False) as stream:
                temporary = Path(stream.name)
                if relative in copies:
                    with copies[relative].open("rb") as source:
                        shutil.copyfileobj(source, stream, 1024 * 1024)
                else:
                    stream.write(generated[relative])
                stream.flush()
                os.fsync(stream.fileno())
            require(digest(temporary) == expected[relative], f"source changed during collection: {relative}")
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return manifest


def check_run_manifest(run: Path) -> tuple[dict, dict[str, Path]]:
    manifest_path = run / "manifest.json"
    expected = (run / "manifest.sha256").read_text().strip()
    require(digest(manifest_path) == expected, "producer manifest seal mismatch")
    manifest = load_json(manifest_path)
    files = manifest["files"]
    require(isinstance(files, dict) and files, "empty producer manifest")
    required = {"protocol.json", "provenance.json", "run.json", "features.json", "fits.jsonl",
                "candidates.csv", "selected.json", "classification_daily.csv", "analysis.json"}
    require(required <= set(files), "producer manifest lacks required compact evidence")
    sources = {}
    for relative, record in sorted(files.items()):
        require(relative not in ("manifest.json", "manifest.sha256", "verification.json"),
                "producer manifest contains a self-reference or later independent audit")
        path = bounded(run, relative)
        require(path.is_file(), f"missing sealed artifact: {relative}")
        require(path.stat().st_size == record["bytes"] and digest(path) == record["sha256"],
                f"producer artifact checksum differs: {relative}")
        sources[relative] = path
    return manifest, sources


def check_design(run: Path, analysis: dict, profile: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    profile = ORIGINAL_PROFILE if profile is None else profile
    require(digest(run / "protocol.json") == profile["protocol_sha256"], "protocol differs from registered frozen bytes")
    require(analysis["protocol_sha256"] == profile["protocol_sha256"], "analysis protocol identity differs")
    require(analysis["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT", "analysis is incomplete")
    frames = sorted(analysis["timeframes"], key=lambda x: x["minutes"])
    require([x["minutes"] for x in frames] == list(TIMEFRAMES), "primary timeframe coverage differs")
    for frame in frames:
        folds = sorted(frame["folds"], key=lambda x: x["year"])
        require([x["year"] for x in folds] == list(YEARS), "outer-year coverage differs")
        primary = frame["bootstrap"]["7"]
        positive_years = sum(x["gain"] > 0 for x in folds)
        require(positive_years == frame["positive_years"], "positive-year count differs")
        conditions = {"positive_gain": primary["gain"] > 0,
                      "ci_above_zero": primary["ci95_low"] > 0,
                      "holm_below_005": frame["p_holm"] < .05,
                      "three_positive_years": positive_years >= 3}
        require(frame["conditions"] == conditions and frame["criterion_met"] == all(conditions.values()),
                "recorded primary criterion differs from frozen conditions")
        expected_outcome = outcome(primary["gain"], primary["ci95_low"], frame["p_holm"], positive_years)
        require(frame["outcome"] == "inconclusive" and frame["outcome_if_verified"] == expected_outcome,
                "producer asserted an unaudited outcome or conditional outcome differs")
        require(set(frame["bootstrap"]) == {"1", "7", "28"}, "bootstrap sensitivity coverage differs")
    selected = load_json(run / "selected.json")["selections"]
    require(len(selected) == 40, "selected pipeline coverage must be 40")
    fits = [json.loads(line) for line in (run / "fits.jsonl").read_text().splitlines() if line.strip()]
    require(len(fits) == 680, "fit record coverage must retain 640 candidates and 40 refits")
    with (run / "candidates.csv").open(newline="") as stream:
        candidates = list(csv.DictReader(stream))
    require(len(candidates) == 640, "candidate score coverage must be 640")
    return frames, selected, fits


def economic_row(minutes: int, period: str, policy: str, metrics: dict) -> list[object]:
    return [minutes, period, policy, percentage(metrics["net_return"]),
            number(metrics["net_log_return"], 4), percentage(metrics["exposure_fraction"]),
            metrics["one_way_turnover"], number(metrics["break_even_symmetric_cost_bps_per_side"], 3)]


def economic_tables(frames: list[dict]) -> tuple[str, str]:
    main_rows, sensitivity_rows = [], []
    for frame in frames:
        m = frame["minutes"]
        periods = [("2023", next(x for x in frame["folds"] if x["year"] == 2023)["economics"]),
                   ("2024+", frame["economics"]["continuous_2024_plus"]),
                   ("all outer", frame["economics"]["all_outer"])]
        for period, scenarios in periods:
            for policy in ("B", "G", "unconditional", "lag1", "cash", "buy_hold"):
                main_rows.append(economic_row(m, period, policy, scenarios["primary"][policy]))
            for policy in ("B", "G"):
                sensitivity_rows.append([m, period, policy, *(
                    percentage(scenarios[s][policy]["net_return"])
                    for s in ("zero", "reduced", "primary", "stress"))])
    main = table(["Minutes", "Period", "Policy", "Net return", "Net log return", "Exposure",
                  "One-way turns", "Break-even bps/side"], main_rows)
    sensitivity = table(["Minutes", "Period", "Policy", "0+0 bps", "5+1 bps", "10+2 bps", "20+4 bps"], sensitivity_rows)
    return main, sensitivity


def make_readme(frames: list[dict], verification: dict, identity: dict, profile: dict | None = None) -> str:
    profile = ORIGINAL_PROFILE if profile is None else profile
    primary_rows, annual_rows, sensitivity_rows, score_rows = [], [], [], []
    supported = []
    for frame in frames:
        m, b = frame["minutes"], frame["bootstrap"]["7"]
        state = frame["outcome_if_verified"]
        if state == "supported":
            supported.append(m)
        primary_rows.append([m, number(b["gain"], 8),
                             f'[{number(b["ci95_low"], 8)}, {number(b["ci95_high"], 8)}]',
                             number(b["p_one_sided"], 5), number(frame["p_holm"], 5),
                             "yes" if b["gain"] > 0 else "no", "yes" if b["ci95_low"] > 0 else "no",
                             "yes" if frame["p_holm"] < .05 else "no",
                             f'{frame["positive_years"]}/4', state])
        for fold in sorted(frame["folds"], key=lambda x: x["year"]):
            choices = fold["selected"]
            annual_rows.append([m, fold["year"], number(fold["gain"], 8),
                                f'{choices["B"]["n"]} / {choices["B"]["lambda"]:g}',
                                f'{choices["G"]["n"]} / {choices["G"]["lambda"]:g}'])
        for days in (1, 7, 28):
            bs = frame["bootstrap"][str(days)]
            sensitivity_rows.append([m, days, f'[{number(bs["ci95_low"], 8)}, {number(bs["ci95_high"], 8)}]',
                                     number(bs["p_one_sided"], 5)])
        for policy in ("B", "G", "unconditional", "lag1"):
            score = frame["pooled_scores"][policy]
            score_rows.append([m, policy, score["binary_count"], score["flat_count"],
                               number(score["binary_log_loss"], 8), number(score["brier"], 6),
                               percentage(score["accuracy"]), percentage(score["balanced_accuracy"])])
    claim = ("The frozen information criterion is supported retrospectively at " +
             ", ".join(f"{m}-minute" for m in supported) + " resolution."
             if supported else "None of the five timeframes meets the complete frozen information criterion.")
    economic_main, economic_sensitivity = economic_tables(frames)
    primary_table = table(["Minutes", "Gain (nats/bar)", "7-day 95% CI", "Raw p", "Holm p", "Gain >0",
                           "CI >0", "Holm <.05", "Positive years", "Audited outcome"], primary_rows)
    annual_table = table(["Minutes", "Outer year", "Gain (nats/bar)", "B n / lambda", "G n / lambda"], annual_rows)
    bootstrap_table = table(["Minutes", "Block days", "95% CI (nats/bar)", "Raw one-sided p"], sensitivity_rows)
    score_table = table(["Minutes", "Policy", "Binary bars", "Flat bars", "Log loss", "Brier", "Accuracy", "Balanced accuracy"], score_rows)
    positive_net, above_B, above_hold, cost_reversals = 0, 0, 0, 0
    for frame in frames:
        policies = frame["economics"]["all_outer"]["primary"]
        g = policies["G"]["net_log_return"]
        positive_net += g > 0
        above_B += g > policies["B"]["net_log_return"]
        above_hold += g > policies["buy_hold"]["net_log_return"]
        cost_reversals += frame["economics"]["all_outer"]["zero"]["G"]["net_log_return"] > 0 >= g
    empirical_economics = (
        f"Across all independently reset outer years, G has a positive primary-cost net log return at "
        f"{positive_net}/5 timeframes, exceeds B at {above_B}/5, and exceeds the buy-and-hold control at "
        f"{above_hold}/5. At {cost_reversals}/5 timeframes its zero-cost net log return is positive but "
        "its primary-cost net log return is nonpositive. These are descriptive fixed-policy comparisons, "
        "without an economic selection or significance claim.")
    recorded_command = shlex.join(identity["command"]) if isinstance(identity["command"], list) else str(identity["command"])
    amendment_note = (
        "This is the separately frozen R1a numerical amendment. The [original R1 failure](../20261008-geometry-information-r1-failed/README.md) "
        "remains scientifically inconclusive. R1a changes the frozen numerical solver only; its objective, candidate grid, "
        "selection, inference and economic criteria remain unchanged. All R1 partial inner scores were already exposed. "
        "The complete amendment and exact solver are preserved in [protocol.json](protocol.json)."
        if profile["attempt_id"] == "R1a" else "")
    return f"""# Bitcoin geometry information — {profile['label']} measured report

**{claim}** The full independent audit passed before this report was generated.
This is an informational comparison of two finite, selected logistic model
families on previously examined historical data. It is not a demonstrated
tradeability result or an estimate of the true conditional mutual information.

The primary quantity is selected sign-history baseline **B log loss minus
selected geometry model G log loss**, measured in nats per eligible binary bar.
Positive values favor geometry. These labels concern the subsequent executable
reference interval, `O[t+2]/O[t+1]-1`, after information from candle `t` closes.
Exactly flat targets are retained in counts and excluded from binary scoring.

{amendment_note}

## Primary results and every success condition

{primary_table}

A timeframe requires all four conditions: positive pooled gain, positive lower
endpoint of the seven-day 95% interval, Holm-adjusted one-sided p below .05
across all five timeframes, and at least three positive annual effects. Complete
fit and independent-audit coverage are prerequisites. The producer's exact
[analysis.json](analysis.json) deliberately retains
`COMPLETE_PENDING_INDEPENDENT_AUDIT` and conditional outcomes; this report joins
that unchanged artifact with the subsequent [verification.json](verification.json).
No candidate, timeframe, year or unfavorable cost scenario is removed.

## Design, selection and annual effects

The five pinned Vaquum BTCUSDT sources contain 459,503 actual candles at 15, 30,
60, 120 and 240 minutes, spanning 2020-01-01 to the exclusive end 2026-10-08.
Their exact Hub revisions, raw and prepared hashes are in
[protocol.json](protocol.json) and [provenance.json](provenance.json).
Missing grid bars remain missing. Classification shares ten-candle causal
history plus two consecutive subsequent bars for every candidate, and requires
the target exit opening strictly before the relevant phase cutoff.

For outer years 2023–2026, the immediately preceding calendar year is inner
validation and earlier years from 2020 are training. B and G independently
select n in {{2,3,5,10}} and lambda in {{.1,.01,.001,.0001}} by validation log
loss, then refit all allowed earlier labels. A loss tie within 1e-12 prefers
shorter history, then stronger regularization. The partial 2026 fold ends on
October 7. There are 640 inner candidate records and 40 selected refits.

{annual_table}

B contains body and close-return sign indicators. G adds additive
current-to-prior endpoint comparisons and wick-presence indicators, all decoded
from the native oriented ten-candle geometry key. G has more columns; this is
not an equal-capacity comparison. Full coefficients, fitting identities,
convergence receipts and scores are retained in [fits.jsonl](fits.jsonl),
[candidates.csv](candidates.csv), [selected.json](selected.json) and the individual
model records listed in the package manifest.

The unconditional and lag-one models are descriptive controls with the frozen
Beta(1,1) smoothing. Accuracy above 50% alone is not incremental evidence beyond
these controls, and an accuracy difference is not the primary success test.

{score_table}

## Dependence and block sensitivity

The paired bootstrap resamples complete UTC target-exit dates, including
zero-count days, within each outer year. It pools observations with equal
per-bar weight, uses 2,000 replicas, and centers the null by the global observed
gain times each day's count. The frozen seed and draw order are in the protocol.
Only the seven-day test and its five-way Holm adjustment determine success.

{bootstrap_table}

The one- and 28-day rows are sensitivity descriptions, not alternative paths to
success. These intervals describe the frozen pipelines conditionally on the
retrospective research design; they do not erase prior exposure or repeated
research selection. [classification_daily.csv](classification_daily.csv)
contains the paired daily receipts.

## Fixed-policy economic diagnostic

Selected B and G, unconditional and lag-one probabilities use the frozen
`p>=0.5` long/cash policy, without economic model or threshold selection.
The primary cost scenario is **10 bps fee plus 2 bps slippage per side**.
Cash and buy-and-hold follow the same annual reset and terminal liquidation
conventions; buy-and-hold does not stop for unavailable geometry history.

The table separates gap-affected 2023 from continuous 2024+ and also reports all
outer years. Aggregates compound independently reset annual ledgers; they do
not imply positions were carried across year boundaries. Exposure is elapsed
time spent long; one-way turnover counts position changes. Break-even is the
equivalent symmetric wealth haircut per side on the fixed gross trading path,
not a newly selected fee assumption or a guarantee about actual execution.

{economic_main}

All returns use normalized spot long/cash equity, with no leverage, shorting,
borrowing, funding or cash yield. A signal can first execute at the next observed
opening after its source candle closes. Existing positions carry across missing
bars, with delayed assumed fills and gap marks recorded; future missing data
cannot trigger an anticipatory exit. Each year starts in cash and liquidates at
its last observed opening strictly before its end. Openings are execution
reference prices, not guaranteed obtainable fills.

### Cost sensitivity for the selected models

Cells show net compounded returns. Each column is a fixed fee+slippage scenario
in basis points per side. Every model, administrative control and scenario has
its exact metrics retained in the corresponding `economics` records; the
following table is a compact B/G comparison.

{economic_sensitivity}

Annualized daily-log Sharpe, open-marked drawdown, gross return, trade summaries,
active days, cost drag, gaps and delayed changes remain in the retained metric
records. Full daily arrays, trades and observed-open traces are identified by
[retained-artifacts.json](retained-artifacts.json). Classification labels with
unavailable future rows never suppress an otherwise causal economic signal.

## Evidence, operational receipts and limitations

The collector checked all files against the producer manifest and required a
complete independent PASS before combining any outcome. The audit's own
coverage, numerical discrepancies and identities are preserved unchanged in
[verification.json](verification.json). [run.json](run.json) contains source,
code, runtime, command, process/thread and operational timing identities;
[features.json](features.json) binds the native feature input. These are
single-run operational receipts, not a matched benchmark or a speedup claim.

The producer command recorded for this run was:

```sh
{recorded_command}
```

The five source histories and earlier results were already examined before this
round, including the predecessor [PR #22](https://github.com/mikkokotila/Filang/pull/22).
Nested temporal fitting prevents the declared inner/outer fitting leakage;
it does not create a fresh external holdout. The protocol was frozen at
`{profile['freeze_commit']}` before fitting or predictive evaluation. Native causal feature
preparation occurred earlier. This report follows the finite
[campaign](../../../experiments/geometry_information/CAMPAIGN.md) and retains
the frozen [protocol SHA-256](protocol.json): `{profile['protocol_sha256']}`.

The modeled projection uses additive current-to-prior endpoint relations. A
negative result does not rule out every possible geometry function, interaction
or conditional regime; a positive result is restricted to this finite family,
target and historical record. Predictive log-loss improvement is not a claim
about the exact information content of geometry. The p>=.5 diagnostic also
does not establish an optimal return policy: directional probabilities and
profit after transaction costs are different quantities.

The candles do not reconstruct spreads, order-book depth, market impact,
size-dependent capacity, sub-bar latency or intrabar drawdown. In particular,
2023's delayed-fill convention is a disclosed proxy for missing observations,
not evidence that trading was unavailable. Fixed costs are scenarios rather
than account-specific or historical fee claims.

## Empirical residue and next decision

{claim} This outcome fixes the scope of what this attempt established; it does
not authorize a revised criterion after seeing the tables. Compare the recorded
annual signs, uncertainty and primary-cost ledgers when deciding whether any
specific next hypothesis is justified. A favorable sensitivity alone cannot
promote an unsuccessful primary result.

{empirical_economics}

Any R2 must be separately frozen and remain inside the small economic-selection
budget recorded in the campaign. Retained inner-validation predictions allow
past-only policy selection; their own labels must never enter a model producing
those probabilities. R3 is limited to justified interpretable interactions.
Stop if no concrete residue supports a next hypothesis or the finite campaign
budget is exhausted. Fresh confirmation requires later, genuinely uninspected
observations, and a tradeability claim additionally requires execution evidence.

{reproduction(identity, profile)}

{bibliography()}"""


def bibliography() -> str:
    return """## Bibliography

- [Binance official trading-fee schedule](https://www.binance.com/en/fee/trading).
  The experiment's fee/slippage values are fixed scenarios, not a claim about
  an account's effective or historical fees.
- [Bailey et al., *The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
  Background reading on repeated historical research; this report makes no new
  empirical claim from that paper.
"""


def reproduction_commands(identity: dict, profile: dict) -> dict:
    data = str(identity["input_paths"]["data_dir"])
    keys = str(identity["input_paths"]["keys_dir"])
    run = str(identity["input_paths"]["out"])
    protocol = "experiments/geometry_information/" + profile["protocol_filename"]
    python = ".venv-information/bin/python"
    return {
        "producer_command_as_recorded": identity["command"],
        "native_export_argv": [["target/release/filang", "geometry-key-export", "--data",
                                str(Path(data) / f"{m}m/ohlcv.csv"), "--out", str(Path(keys) / f"{m}m"),
                                "--interval-seconds", str(m * 60), "--history-start", "2020-01-01",
                                "--end", "2026-10-08", "--bars", "10", "--memory-mib", "256",
                                "--max-rows", "2000000", "--resume", "true"] for m in TIMEFRAMES],
        "fresh_run_argv": [python, "experiments/geometry_information/run_round1.py", "--data-dir", data,
                           "--keys-dir", keys, "--out", "runs/" + profile["run_name"], "--protocol", protocol,
                           "--freeze-commit", profile["freeze_commit"], "--workers", str(identity["settings"]["workers"]),
                           "--blas-threads", str(identity["settings"]["blas_threads"])],
        "independent_audit_argv": [python, "experiments/geometry_information/verify_round1.py", "--stage", "full",
                                   "--run", run, "--keys-root", keys, "--data-dir", data,
                                   "--protocol", protocol, "--out", str(Path(run) / "verification.json")],
        "collection_argv": [python, "experiments/geometry_information/collect_round1.py", "--run", run,
                            "--out", "benchmarks/reports/" + profile["report_name"]],
    }


def reproduction(identity: dict, profile: dict) -> str:
    commands = reproduction_commands(identity, profile)
    native = "\n".join(shlex.join(argv) for argv in commands["native_export_argv"])
    fresh = shlex.join(commands["fresh_run_argv"])
    audit = shlex.join(commands["independent_audit_argv"])
    collect_command = shlex.join(commands["collection_argv"])
    return f"""## Reproduction

Run from the repository root using Python 3.13.2 and the recorded implementation
identity. The freeze commit binds the scientific protocol; the run's code hashes
identify its implementation. A forensic replay of retained outputs requires the
completed PR #{profile['final_pr']} tree containing the final verifier and the
unchanged producer files whose hashes are in [run.json](run.json). A protocol
freeze commit alone may predate that implementation. A later campaign checkout
with modified producer files must not audit this run under different code.

The commands below use the recorded data and key roots, preserving paths that
may be outside this research checkout. The data themselves must match the
source and prepared-CSV hashes in [protocol.json](protocol.json). Paths can be
relocated only while retaining those exact input identities. These commands
reproduce work; do not execute them into an existing sealed run directory.
Native preparation uses `--resume true`: an existing completed key cache is
verified only when its source, context and executable identities match. The
exporter rejects mismatches instead of overwriting a sealed cache. Use the
recorded native executable for that check; if generating a new key cache,
choose an unused key root and pass that same root to the fresh runner. The
already sealed, matching key cache can also be reused directly by the runner
without executing native preparation again.

```sh
python3.13 -m venv .venv-information
.venv-information/bin/python -m pip install -r requirements-information.txt
export VECLIB_MAXIMUM_THREADS={identity['settings']['blas_threads']}
export OPENBLAS_NUM_THREADS={identity['settings']['blas_threads']}
export OMP_NUM_THREADS={identity['settings']['blas_threads']}
export MKL_NUM_THREADS={identity['settings']['blas_threads']}
cargo build --release
{native}
{fresh}
```

The original recorded command is preserved above and in
[reproduction.json](reproduction.json). The fresh-run example uses the registered
`{profile['run_name']}` directory; choose an unused output location when repeating
the computation. Match the recorded native engine identity when reproducing
feature artifacts. Thread/process controls are operational receipts, not
scientific selection axes.

Audit and collect the retained original run without refitting:

```sh
{audit}
{collect_command}
```

The exact scientific identity is
`{profile['protocol_filename']}@{profile['freeze_commit']}`, protocol SHA-256
`{profile['protocol_sha256']}`. The collector admits only its pinned registry
entry, requires its exact declared amendment record and no deviations, and
cannot promote a partial or failed-stage audit to full scientific PASS.

Large source-row predictions and complete economic traces remain in the sealed
run. [Retained-artifact identities](retained-artifacts.json) bind their relative
paths, lengths and digests. This package preserves compact files byte for byte;
its separate [manifest](manifest.json) seals the copies and generated report
without changing the original producer manifest.
"""


def check_audit(run: Path, verification: dict, manifest: dict, profile: dict | None = None) -> None:
    """Require scientific replay, not a feature-only or checksum-only PASS."""
    profile = ORIGINAL_PROFILE if profile is None else profile
    require(verification["schema"] == "filang-geometry-information-verification-v1" and
            verification["status"] == "PASS" and verification["stage"] == "full",
            "collection requires a complete independent scientific audit")
    require(verification["protocol_sha256"] == profile["protocol_sha256"], "audit protocol identity differs")
    require(verification["producer_manifest_sha256"] == digest(run / "manifest.json"),
            "audit does not bind the current producer manifest")
    require(verification["analysis_sha256"] == digest(run / "analysis.json"),
            "audit does not bind the current analysis")
    require(verification["audited_timeframes"] == list(TIMEFRAMES) and
            verification["audited_outer_years"] == list(YEARS), "independent audit omits a timeframe or outer year")
    coverage = verification["coverage"]
    expected = {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40,
                "outer_predictions": 20, "validation_predictions": 20}
    require(all(coverage[k] == v for k, v in expected.items()) and
            coverage["all_records"] is True and coverage["sampled"] is False,
            "independent audit is sampled or has incomplete scientific coverage")
    ledger_files = [path for path in manifest["files"] if "/economics/" in path and path.endswith("/metrics.json")]
    require(len(ledger_files) == coverage["ledger_replays"] == 960,
            "independent audit has not replayed every retained economic ledger")
    for minutes in TIMEFRAMES:
        for year in YEARS:
            for phase in ("validation", "outer"):
                require(f"{minutes}m/{year}/{phase}.npz" in manifest["files"] and
                        f"{minutes}m/{year}/{phase}.json" in manifest["files"],
                        "complete full-row prediction files and sidecars are required")


def native_receipts(identity: dict, features: dict, override: Path | None) -> tuple[dict[str, Path], dict]:
    """Retain small native preparation receipts; leave sealed key payloads out."""
    keys = (override or Path(identity["input_paths"]["keys_dir"])).resolve()
    copies, retained = {}, {}
    feature_frames = sorted(features["timeframes"], key=lambda x: x["minutes"])
    require([f["minutes"] for f in feature_frames] == list(TIMEFRAMES), "native feature timeframe coverage differs")
    for feature in feature_frames:
        minutes = feature["minutes"]
        root = bounded(keys, f"{minutes}m")
        manifest = load_json(root / "manifest.json")
        native = feature["native"]
        require(digest(root / "manifest.json") == native["manifest_sha256"] ==
                (root / "manifest.sha256").read_text().strip(), "native manifest identity differs")
        require(manifest["status"] == "COMPLETE" and digest(root / "context.json") == native["context_sha256"] ==
                manifest["context_sha256"], "native context/completeness differs")
        require(digest(root / "timings.json") == manifest["timings_sha256"], "native timing receipt differs")
        context = load_json(root / "context.json")
        require(context["engine_sha256"] == native["engine_sha256"] and
                context["source_sha256"] == feature["source_sha256"], "native engine/source binding differs")
        payload = root / "keys.bin"
        require(digest(payload) == native["keys_sha256"] == manifest["keys_file_sha256"] and
                payload.stat().st_size == manifest["keys_file_bytes"], "native key payload differs")
        for name in ("context.json", "manifest.json", "manifest.sha256", "timings.json"):
            copies[f"native/{minutes}m/{name}"] = root / name
        retained[f"{minutes}m/keys.bin"] = {**file_record(payload), "source_path": str(payload)}
    return copies, retained


def operational_receipts(run: Path, identity: dict, launcher: Path | None,
                         audit_receipts: tuple[Path, ...] | list[Path]) -> tuple[dict[str, Path], dict]:
    """Read explicitly supplied external receipts without modifying the run."""
    run = run.resolve()
    copies, records = {}, {}

    def include(path: Path, relative: str, role: str) -> None:
        path = path.resolve()
        require(path.is_file() and run not in path.parents,
                "operational receipt must be an existing file outside the sealed run")
        require(relative not in copies, "duplicate operational receipt destination: " + relative)
        copies[relative] = path
        records[relative] = {**file_record(path), "source_path": str(path), "role": role,
                             "included_in_producer_manifest": False}

    if launcher is not None:
        launch = load_json(launcher)
        require(launch["command"] == identity["command"], "launcher command differs from recorded producer command")
        require(type(launch["exit_code"]) is int and launch["exit_code"] == 0,
                "launcher must record a successful exit")
        elapsed = launch["elapsed_seconds"]
        require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed > 0,
                "launcher duration must be finite and positive")
        include(launcher, "operational/launcher.json", "successful producer launcher")
        execution_log = Path(launch["log"]) if launch.get("log") else None
        if execution_log is not None and execution_log.is_file():
            include(execution_log, "operational/execution.log", "producer execution log")
    for path in audit_receipts:
        include(path, "operational/audit/" + path.name, "external audit-development or execution receipt")
    return copies, records


def collect(run: Path, out: Path, keys_dir: Path | None = None, launcher: Path | None = None,
            audit_receipts: tuple[Path, ...] | list[Path] = ()) -> dict:
    run, out = run.resolve(), out.resolve()
    require(run != out and run not in out.parents and out not in run.parents,
            "report and source run must be separate directories")
    manifest, sources = check_run_manifest(run)
    analysis, identity = load_json(run / "analysis.json"), load_json(run / "run.json")
    verification = load_json(run / "verification.json")
    profile, protocol = admitted_protocol(run, identity)
    require(identity["status"] == "COMPLETE_PENDING_INDEPENDENT_AUDIT", "producer run is incomplete")
    require(identity["source_provenance_sha256"] == digest(run / "provenance.json"),
            "run source provenance identity differs")
    check_audit(run, verification, manifest, profile)
    frames, selected, fits = check_design(run, analysis, profile)
    copies = {}
    omitted = {}
    for relative, source in sources.items():
        # Predictions, dense traces, trade-by-trade lists and binary daily
        # arrays remain sealed in the full run. Scalar ledgers, gaps, model
        # coefficients, sidecars, identity/configuration and text receipts stay.
        if source.suffix == ".npz" or source.name == "trades.json":
            omitted[relative] = manifest["files"][relative]
        else:
            copies[relative] = source
    copies.update({"producer-manifest.json": run / "manifest.json",
                   "producer-manifest.sha256": run / "manifest.sha256",
                   "verification.json": run / "verification.json"})
    native_copies, native_external = native_receipts(identity, load_json(run / "features.json"), keys_dir)
    require(not set(copies).intersection(native_copies), "native report destinations overlap producer artifacts")
    copies.update(native_copies)
    operational_copies, operational_records = operational_receipts(run, identity, launcher, audit_receipts)
    require(not set(copies).intersection(operational_copies), "operational receipts overlap producer artifacts")
    copies.update(operational_copies)
    # Operational wrappers may write receipts after the sealed scientific run.
    # Preserve their exact bytes, label their provenance separately, and never
    # imply that a later receipt was included in the producer's original seal.
    later = {}
    for directory in ("receipts", "timings"):
        if (run / directory).is_dir():
            for path in sorted((run / directory).rglob("*")):
                if path.is_file() and path.suffix in (".json", ".txt", ".log"):
                    relative = path.relative_to(run).as_posix()
                    if relative not in sources:
                        bounded(run, relative)
                        copies[relative] = path
                        later[relative] = file_record(path)
    retained = {"schema": "filang-r1-external-artifact-identities-v1", "source_run": str(run),
                "producer_manifest_sha256": digest(run / "manifest.json"),
                "verification_sha256": digest(run / "verification.json"),
                "collection_streamed_and_checked_all_producer_files": True,
                "external_files": omitted, "external_native_keys": native_external,
                "external_operational_receipts": operational_records,
                "later_operational_receipts": later,
                "note": "Full independent scope is stated by verification.json; hashes alone are not scientific replay."}
    reproduction_record = {
        "schema": "filang-r1-report-reproduction-v1", "freeze_commit": profile["freeze_commit"],
        "protocol_sha256": profile["protocol_sha256"], "attempt_id": profile["attempt_id"],
        "protocol_filename": profile["protocol_filename"], "amendments": identity["amendments"],
        "deviations": identity["deviations"], "implementation": identity["implementation"],
        "runtime": identity["runtime"], "settings": identity["settings"],
        **reproduction_commands(identity, profile)}
    if launcher is not None:
        reproduction_record["collection_argv"].extend(["--launcher", str(launcher.resolve())])
    for path in audit_receipts:
        reproduction_record["collection_argv"].extend(["--audit-receipt", str(path.resolve())])
    collector_receipt = {"schema": "filang-r1-report-collection-v1", "status": "PASS",
                         "attempt_id": profile["attempt_id"], "protocol_sha256": profile["protocol_sha256"],
                         "freeze_commit": profile["freeze_commit"],
                         "collector_sha256": digest(Path(__file__).resolve()),
                         "producer_manifest_sha256": digest(run / "manifest.json"),
                         "verification_sha256": digest(run / "verification.json"),
                         "producer_files_checked": len(sources), "candidates": 640,
                         "fit_records": len(fits), "selected_refits": len(selected),
                         "external_operational_receipts": operational_records,
                         "outcomes": {str(f["minutes"]): f["outcome_if_verified"] for f in frames}}
    readme = make_readme(frames, verification, identity, profile)
    if operational_records:
        links = "\n".join(f"- [{relative}]({relative}) — {record['role']}."
                          for relative, record in operational_records.items())
        readme += ("\n## External operational receipts\n\n" + links +
                   "\n\nThese exact-byte receipts are archived only in this report package. "
                   "The launcher, when supplied, matches the recorded producer command, successful exit and positive duration. "
                   "They are not added to the sealed run or represented as files in its original producer manifest. "
                   "Scientific audit coverage remains defined by verification.json.\n")
    generated = {"README.md": readme.encode(),
                 "retained-artifacts.json": json_bytes(retained),
                 "reproduction.json": json_bytes(reproduction_record),
                 "collection.json": json_bytes(collector_receipt)}
    package = write_package(out, copies, generated, profile)
    return {"status": "PASS", "out": str(out), "collected_files": len(package["files"]),
            "externally_retained_files": len(omitted), "outcomes": collector_receipt["outcomes"]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keys-dir", type=Path, help="Relocated native keys root; defaults to run.json's recorded input path")
    parser.add_argument("--launcher", type=Path, help="External successful launcher JSON; its existing execution log is also retained")
    parser.add_argument("--audit-receipt", type=Path, action="append", default=[],
                        help="External audit log/receipt to preserve in the report only; repeatable")
    args = parser.parse_args(argv)
    print(json.dumps(collect(args.run, args.out, args.keys_dir, args.launcher, args.audit_receipt),
                     sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("R1 report collection: " + str(error), file=sys.stderr)
        raise SystemExit(2)
