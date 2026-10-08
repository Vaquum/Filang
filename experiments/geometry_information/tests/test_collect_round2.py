"""Synthetic collector admission tests; no market data, fitting, or audit claims.

The fake auditor receipts exercise package admission and identity contracts.
Their payloads explicitly are synthetic placeholders, not scientific fixtures.
The independent verifier has its own numerical integration tests.
"""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments.geometry_information import collect_round2 as c


PROTOCOL = Path(c.__file__).with_name("round2_protocol.json")
SHA = c.shared.digest(PROTOCOL)
FREEZE = c.SUPPORTED_PROTOCOLS[SHA]["freeze_commit"]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(c.shared.json_bytes(value))


def save_lines(path, rows):
    path.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))


def reseal(run):
    files = {p.relative_to(run).as_posix(): c.shared.file_record(p) for p in sorted(run.rglob("*"))
             if p.is_file() and p.name not in ("manifest.json", "manifest.sha256", "verification.json")}
    save(run / "manifest.json", {"schema": "filang-payoff-run-manifest-v1", "files": files})
    (run / "manifest.sha256").write_text(c.shared.digest(run / "manifest.json") + "\n")
    if (run / "verification.json").exists():
        audit = c.shared.load_json(run / "verification.json")
        audit["producer_manifest_sha256"] = c.shared.digest(run / "manifest.json")
        audit["analysis_sha256"] = c.shared.digest(run / "analysis.json")
        save(run / "verification.json", audit)


def metrics(net, trades=10, scale=1):
    return {"net_log_return": net * scale, "net_return": math.expm1(net * scale),
            "gross_log_return": net * scale, "gross_return": math.expm1(net * scale),
            "max_drawdown": .01, "exposure_fraction": .5 if trades else 0,
            "one_way_turnover": trades * 2 * scale, "completed_trades": trades * scale,
            "gap_count": 1 if scale == 1 else 0, "gap_gross_log_return": 0., "delayed_exposure_changes": 0,
            "break_even_symmetric_cost_bps_per_side": 1. if trades else None}


def synthetic_bootstrap_audit(frames):
    rows = []
    for frame in frames:
        for block, bs in frame["bootstrap"].items():
            for name, values in bs["comparisons"].items():
                p, observed = values["p_one_sided"], values["mean_daily_net_log_gain"]
                count = round(p * 2001 - 1)
                rows.append({"minutes": frame["minutes"], "block_days": int(block), "comparison": name,
                    "replicates": 2000, "independent_oracle_observed": observed, "retained_input_observed": observed,
                    "independent_oracle_p_one_sided": p, "retained_p_one_sided": p,
                    "independent_oracle_tail_count": count, "retained_tail_count": count,
                    "predicate_disagreement_count": 0, "literal_equal_margin_count": 0,
                    "minimum_absolute_tail_margin": 1e-8, "nearest_negative_tail_margin": -1e-8,
                    "nearest_positive_tail_margin": 1e-8, "ordinary_max_abs_oracle_error": 1e-13,
                    "centered_max_abs_oracle_error": 1e-13, "observed_abs_oracle_error": 0.,
                    "ordinary_max_abs_retained_arithmetic_error": 0., "centered_max_abs_retained_arithmetic_error": 0.,
                    "retained_arithmetic_ordinary_exact": True, "retained_arithmetic_centered_exact": True,
                    "nonzero_daily_effects": 4, "single_atom_exact_algebraic_p": None,
                    "single_atom_sample_multiplicity_histogram": None})
    return {"bootstrap_audit_method": {"continuous_replay": "synthetic independent continuous replica comparison",
        "discrete_tail": "synthetic literal retained-array tail comparison", "uniform_cases": 30,
        "predicate_epsilon": None, "producer_or_protocol_changed": False,
        "alternate_oracle_p_agreement_claimed": False, "diagnostics": "synthetic distinct arithmetic diagnostics"},
        "bootstrap_tail_diagnostics": rows}


def fixture(run):
    run.mkdir()
    (run / "protocol.json").write_bytes(PROTOCOL.read_bytes())
    protocol = c.shared.load_json(PROTOCOL)
    save(run / "provenance.json", {"synthetic": True, "description": "not a market provenance"})
    keys_root = run.parent / "synthetic keys"
    feature_frames = []
    for index, spec in enumerate(protocol["data"]["sources"]):
        minutes = spec["minutes"]
        keyroot = keys_root / f"{minutes}m"
        save(keyroot / "context.json", {"engine_sha256": "e" * 64, "source_sha256": spec["prepared_csv_sha256"]})
        save(keyroot / "timings.json", {"synthetic": True})
        (keyroot / "keys.bin").write_bytes(b"SYNTHETIC KEY PLACEHOLDER; NOT DECODED BY COLLECTOR")
        native = {"status": "COMPLETE", "context_sha256": c.shared.digest(keyroot / "context.json"),
                  "timings_sha256": c.shared.digest(keyroot / "timings.json"),
                  "keys_file_sha256": c.shared.digest(keyroot / "keys.bin"),
                  "keys_file_bytes": (keyroot / "keys.bin").stat().st_size}
        save(keyroot / "manifest.json", native)
        (keyroot / "manifest.sha256").write_text(c.shared.digest(keyroot / "manifest.json") + "\n")
        feature_frames.append({"minutes": minutes, "source_sha256": spec["prepared_csv_sha256"],
            "record_count": 90000 if index < 4 else 98972,
            "native": {"engine_sha256": "e" * 64, "context_sha256": native["context_sha256"],
                       "manifest_sha256": c.shared.digest(keyroot / "manifest.json"), "keys_sha256": native["keys_file_sha256"]}})
    save(run / "features.json", {"timeframes": feature_frames})
    identity = {"schema": "filang-payoff-run-v1", "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
        "freeze_commit": FREEZE, "protocol_sha256": SHA, "amendments": [], "deviations": [],
        "source_provenance_sha256": c.shared.digest(run / "provenance.json"),
        "input_paths": {"out": str(run), "keys_dir": str(keys_root), "data_dir": "/synthetic data/pinned csv"},
        "implementation": {"sha256": "i" * 64, "synthetic": True}, "runtime": {"synthetic": True},
        "settings": {"workers": 1, "blas_threads": 1}, "command": ["synthetic-python", "synthetic-no-fitting"]}
    save(run / "run.json", identity)
    frames, member_count = [], 0
    for feature in feature_frames:
        minutes = feature["minutes"]
        root = run / f"{minutes}m"
        save(root / "features.json", feature)
        row_identity = {"minutes": minutes, "source_sha256": feature["source_sha256"], "protocol_sha256": SHA,
                        "native_keys_sha256": feature["native"]["keys_sha256"], "implementation_sha256": "i" * 64}
        fits, choices, ledgers, folds, statistics = [], [], [], [], []
        bundles = {f"year{year}.npz": {"arrays": {}} for year in c.YEARS}
        bundles["bootstrap.npz"] = {"arrays": {"synthetic_bootstrap": {"dtype": "<f8", "shape": [2000, 2], "sha256": "a" * 64}}}
        member = {"dtype": "<f8", "shape": [1], "sha256": "a" * 64}
        for i in range(5):
            names = {name: f"statistics{i}__{name}" for name in ("x_mean", "gram_mean", "xy_mean", "y_mean", "y2_mean")}
            bundles["year2023.npz"]["arrays"].update({name: dict(member) for name in names.values()})
            statistics.append({**row_identity, "statistics_id": f"{minutes}-statistics-{i}",
                "arrays_file": f"{minutes}m/year2023.npz", "arrays": names,
                "array_identities": {name: dict(member) for name in names}})
        gvalue = .02 if minutes == 15 else 0 if minutes == 30 else -.01
        family_values = {"B": .01, "G": gvalue, "U": .002, "cash": 0., "buy_hold": .1}
        def costs(scale):
            return {cost: {family: metrics(value, 0 if family == "cash" or (family == "G" and minutes == 30) else 10, scale)
                           for family, value in family_values.items()} for cost in c.SCENARIOS}
        for year in c.YEARS:
            model_choices = {}
            for family in ("B", "G"):
                for n in (2, 3, 5, 10):
                    for penalty in (.1, .01, .001, .0001):
                        fits.append({**row_identity, "outer_year": year, "family": family, "n": n, "lambda": penalty,
                            "stage": "inner", "accepted": True, "fit_id": f"{minutes}-{year}-{family}-{n}-{penalty}",
                            "synthetic": True})
                inner_id = f"{minutes}-{year}-{family}-2-0.1"
                refit_id = f"{minutes}-{year}-{family}-refit"
                fits.append({**row_identity, "outer_year": year, "family": family, "n": 2, "lambda": .1,
                             "stage": "refit", "accepted": True, "fit_id": refit_id, "synthetic": True})
                model_choices[family] = {"minutes": minutes, "outer_year": year, "family": family, "n": 2, "lambda": .1,
                    "inner_fit_id": inner_id, "refit_fit_id": refit_id,
                    "validation_minimum_mse": .001, "validation_selected_mse": .001}
            model_choices["U"] = {"minutes": minutes, "outer_year": year, "family": "U", "n": None, "lambda": None}
            for stage in ("inner", "refit"):
                fit_id = f"{minutes}-{year}-U-{stage}"
                model_choices["U"].update({stage + "_fit_id": fit_id,
                    stage + "_mean": {"fit_id": fit_id, "stage": stage, "mean": .001}})
            def ledger(phase, cost, family, policy):
                ledger_id = f"{minutes}-{year}-{phase}-{cost}-{family}-{policy['id']}"
                array_name = ledger_id + "__daily_net_log"
                bundles[f"year{year}.npz"]["arrays"][array_name] = dict(member)
                row = {**row_identity, "outer_year": year, "phase": phase, "scenario": cost, "family": family,
                    "ledger_id": ledger_id, "policy": policy,
                    "metrics": costs(1)[cost][family], "arrays_file": f"{minutes}m/year{year}.npz",
                    "arrays": {"daily_net_log": array_name}, "synthetic": True}
                ledgers.append(row)
                return row
            for family, choice in model_choices.items():
                chosen_id = "cash" if family == "G" and minutes == 30 else "e0_x0"
                trials = []
                for pid in c.POLICIES:
                    trial = ledger("validation", "primary", family, {"id": pid})
                    trials.append({"policy_id": pid, "ledger_id": trial["ledger_id"],
                                   "net_log_return": trial["metrics"]["net_log_return"],
                                   "one_way_turnover": trial["metrics"]["one_way_turnover"]})
                chosen = next(t for t in trials if t["policy_id"] == chosen_id)
                choice.update(policy={"id": chosen_id}, policy_trials=trials,
                              selected_validation_ledger_id=chosen["ledger_id"],
                              validation_maximum_net_log_return=chosen["net_log_return"],
                              validation_selected_net_log_return=chosen["net_log_return"])
                choices.append(choice)
            for cost in c.SCENARIOS:
                for family in c.FAMILIES:
                    policy = model_choices[family]["policy"] if family in model_choices else {"id": family}
                    ledger("outer", cost, family, policy)
            predictions = {}
            for phase in ("validation", "outer"):
                names = ("row_index", "timestamp", "entry_row", "exit_row", "causal_feature_valid", "phase_mask", "target_valid",
                         "direction", "target_log_return", "target_simple_return", "mu_B", "mu_G", "mu_U")
                bundles[f"year{year}.npz"]["arrays"].update({phase + "__" + name: dict(member) for name in names})
                predictions[phase] = {"arrays_file": f"{minutes}m/year{year}.npz", "array_prefix": phase,
                    "scores": {family: {"target_count": 100, "zero_count": 2, "mse": .001} for family in ("B", "G", "U")}}
            folds.append({"year": year, "selected": model_choices, "predictions": predictions, "economics": costs(1),
                          "effects": {"G_minus_B": gvalue - .01, "G_minus_cash": gvalue}})
        positive = minutes == 15
        p_value = (1 + (1 if positive else 1800)) / 2001
        bootstrap = {}
        for block in (1, 7, 28):
            comparisons = {name: {"mean_daily_net_log_gain": .0001 if positive else -.0001,
                "total_net_log_gain": .1 if positive else -.1, "calendar_days": 1000,
                "ci95_low": .00001 if positive else -.001, "ci95_high": .001,
                "p_one_sided": p_value} for name in c.COMPARISONS}
            bootstrap[str(block)] = {"comparisons": comparisons, "block_days": block, "replicates": 2000,
                "seed": 20261008 + 1000 * minutes + block, "intersection_union_p": p_value}
        frame = {"minutes": minutes, "folds": folds, "bootstrap": bootstrap, "p_holm": 5 * p_value if positive else 1.,
                 "economics": {"all_outer": costs(4), "continuous_2024_plus": costs(3)}}
        conditions, years, trades = c.criterion(frame)
        frame.update(conditions=conditions, joint_positive_years=years, completed_G_trades=trades,
                     criterion_met=all(conditions.values()), outcome="inconclusive",
                     outcome_if_verified="supported" if all(conditions.values()) else "not-supported")
        frames.append(frame)
        save_lines(root / "fits.jsonl", fits)
        save_lines(root / "selections.jsonl", choices)
        save_lines(root / "ledgers.jsonl", ledgers)
        save_lines(root / "statistics.jsonl", statistics)
        save(root / "summary.json", frame)
        save(root / "timings.json", {"synthetic": True})
        for name, record in bundles.items():
            (root / name).write_bytes(b"SYNTHETIC ARRAY PLACEHOLDER; NOT A SCIENTIFIC RUN")
            record.update(c.shared.file_record(root / name))
            member_count += len(record["arrays"])
        save(root / "arrays.json", {"schema": "filang-payoff-arrays-v1", "files": bundles})
    save(run / "analysis.json", {"schema": "filang-payoff-analysis-v1", "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
        "protocol_sha256": SHA, "coverage": c.PRODUCER_COVERAGE, "timeframes": frames})
    reseal(run)
    audit = {"schema": "filang-geometry-payoff-verification-v1", "stage": "full", "status": "PASS",
        "synthetic": True, "protocol_sha256": SHA, "freeze_commit": FREEZE,
        "producer_manifest_sha256": c.shared.digest(run / "manifest.json"), "analysis_sha256": c.shared.digest(run / "analysis.json"),
        "audited_timeframes": list(c.TIMEFRAMES), "audited_outer_years": list(c.YEARS), "coverage": c.COVERAGE,
        "checks": {name: True for name in c.CHECKS}, "max_numeric_error": 1e-13,
        "max_independent_fit_gradient": 1e-14, "audited_array_members": member_count,
        "all_array_members_checked": True, "scientific_models_checked": True, "no_model_fitting_by_verifier": True,
        **synthetic_bootstrap_audit(frames)}
    save(run / "verification.json", audit)
    return frames, audit


class Round2CollectorTests(unittest.TestCase):
    def test_complete_compact_package_preserves_all_text_and_external_bundle_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run, out = root / "run", root / "report"
            fixture(run)
            before = {p.relative_to(run).as_posix(): c.shared.file_record(p) for p in run.rglob("*") if p.is_file()}
            package = c.collect(run, out)
            after = {p.relative_to(run).as_posix(): c.shared.file_record(p) for p in run.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertLess(len(package["files"]) + 2, 100)
            self.assertEqual(77, len(package["files"]) + 2)
            self.assertFalse(list(out.rglob("*.npz")))
            retained = c.shared.load_json(out / "retained-artifacts.json")
            self.assertEqual(len(retained["external_numerical_bundles"]), 25)
            self.assertEqual(retained["outcomes_after_full_audit"]["15"], "supported")
            self.assertEqual(retained["outcomes_after_full_audit"]["30"], "not-supported")
            for name in retained["copied_producer_artifacts"]:
                self.assertEqual((run / name).read_bytes(), (out / name).read_bytes())
            for name, record in retained["external_numerical_bundles"].items():
                self.assertEqual(c.shared.file_record(run / name), {k: record[k] for k in ("bytes", "sha256")})
            report = (out / "README.md").read_text()
            for text in ("supported for 15m", "not** a joint simultaneous", "mean;", "cash", "77 files",
                         "'/synthetic data/pinned csv'", FREEZE, "completed PR26 tree", "No optimizer is run by the collector"):
                self.assertIn(text, report)
            c.collect(run, out)  # Exact repeat is idempotent.

    def test_external_receipts_are_bound_and_never_mutate_source_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; fixture(run)
            identity = c.shared.load_json(run / "run.json")
            launcher, log, auditlog = root / "launcher.json", root / "execution.log", root / "audit.log"
            log.write_text("synthetic execution\n"); auditlog.write_text("synthetic audit\n")
            save(launcher, {"command": identity["command"], "exit_code": 0, "elapsed_seconds": 2., "log": str(log)})
            out = root / "out"
            c.collect(run, out, launcher=launcher, audit_receipts=[auditlog])
            self.assertEqual(log.read_bytes(), (out / "operational/execution.log").read_bytes())
            self.assertEqual(auditlog.read_bytes(), (out / "operational/audit/audit.log").read_bytes())
            self.assertFalse((run / "operational").exists())
            save(launcher, {"command": ["wrong-command"], "exit_code": 0, "elapsed_seconds": 2.})
            with self.assertRaisesRegex(ValueError, "command differs"):
                c.collect(run, root / "bad", launcher=launcher)
            self.assertFalse((root / "bad").exists())
            alias = root / "alias"; alias.symlink_to(run.resolve(), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside the sealed run"):
                c.collect(alias, root / "bad", audit_receipts=[run / "verification.json"])

    def test_stale_sampled_partial_or_unasserted_audit_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; _, original = fixture(run)
            variants = []
            for key, value in (("stage", "features"), ("status", "FAIL"), ("analysis_sha256", "0" * 64),
                               ("freeze_commit", "0" * 40), ("all_array_members_checked", False),
                               ("max_independent_fit_gradient", 1e-9), ("audited_array_members", 1),
                               ("no_model_fitting_by_verifier", False)):
                variants.append({**original, key: value})
            for key, value in (("sampled", True), ("ledger_replays", 819), ("policy_choices", 59), ("prediction_phases", 39)):
                variants.append({**original, "coverage": {**original["coverage"], key: value}})
            variants.append({**original, "checks": {name: True for name in c.CHECKS if name != "all_binary_array_members"}})
            for i, audit in enumerate(variants):
                save(run / "verification.json", audit)
                with self.subTest(i=i), self.assertRaises(ValueError):
                    c.collect(run, root / "bad")
                self.assertFalse((root / "bad").exists())

    def test_bootstrap_tail_audit_is_complete_bound_and_distinguishes_discrete_arithmetic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; _, original = fixture(run)
            variants = []
            bad = copy.deepcopy(original); bad["bootstrap_tail_diagnostics"].pop(); variants.append(bad)
            bad = copy.deepcopy(original); bad["bootstrap_tail_diagnostics"][0]["retained_p_one_sided"] += 1 / 2001; variants.append(bad)
            bad = copy.deepcopy(original); bad["bootstrap_tail_diagnostics"][0]["retained_tail_count"] += 1; variants.append(bad)
            bad = copy.deepcopy(original); bad["bootstrap_tail_diagnostics"][0] = copy.deepcopy(bad["bootstrap_tail_diagnostics"][1]); variants.append(bad)
            for key, value in (("predicate_epsilon", 1e-12), ("producer_or_protocol_changed", True),
                               ("alternate_oracle_p_agreement_claimed", True), ("uniform_cases", 29)):
                bad = copy.deepcopy(original); bad["bootstrap_audit_method"][key] = value; variants.append(bad)
            bad = copy.deepcopy(original); del bad["bootstrap_audit_method"]; variants.append(bad)
            for index, audit in enumerate(variants):
                save(run / "verification.json", audit)
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, "bootstrap|tail"):
                    c.collect(run, root / "bad")
                self.assertFalse((root / "bad").exists())
            amended = copy.deepcopy(original)
            row = next(r for r in amended["bootstrap_tail_diagnostics"]
                       if (r["minutes"], r["block_days"], r["comparison"]) == (30, 7, "G_minus_B"))
            row.update(independent_oracle_tail_count=1799, independent_oracle_p_one_sided=1800 / 2001,
                       predicate_disagreement_count=1, literal_equal_margin_count=200,
                       minimum_absolute_tail_margin=0., nonzero_daily_effects=1,
                       single_atom_exact_algebraic_p=1801 / 2001,
                       single_atom_sample_multiplicity_histogram={"0": 800, "1": 800, "2": 200, "3": 200})
            save(run / "verification.json", amended)
            log = root / "first-audit-failed.log"; log.write_text("synthetic preserved audit failure\n")
            c.collect(run, root / "report", audit_receipts=[log])
            report = (root / "report/README.md").read_text()
            section = report.split("## Bootstrap arithmetic audit", 1)[1].split("## Annual effects", 1)[0]
            self.assertIn("all thirty cases", section)
            self.assertIn("| 30 | 7 | G_minus_B |", section)
            self.assertNotIn("| 15 |", section)
            self.assertIn("0.899550225", section)
            self.assertIn("0.900049975", section)
            self.assertIn("1 nonzero days", section)
            self.assertIn("not replacement or corrected mathematical p-values", section)
            self.assertIn("first-audit-failed.log", section)
            self.assertEqual(log.read_bytes(), (root / "report/operational/audit/first-audit-failed.log").read_bytes())

    def test_missing_records_and_array_binding_rejected_even_if_receipt_claims_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; fixture(run)
            for name in ("fits.jsonl", "selections.jsonl", "ledgers.jsonl"):
                path = run / "15m" / name; original = path.read_bytes()
                path.write_bytes(b"\n".join(original.splitlines()[1:]) + b"\n"); reseal(run)
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "coverage"):
                    c.collect(run, root / "bad")
                self.assertFalse((root / "bad").exists())
                path.write_bytes(original); reseal(run)
            path = run / "15m/arrays.json"; original_index = c.shared.load_json(path)
            index = copy.deepcopy(original_index)
            index["files"]["year2023.npz"]["sha256"] = "0" * 64
            save(path, index); reseal(run)
            with self.assertRaisesRegex(ValueError, "index/manifest"):
                c.collect(run, root / "bad")
            index = copy.deepcopy(original_index)
            del index["files"]["year2023.npz"]["arrays"]["outer__mu_G"]
            save(path, index); reseal(run)
            with self.assertRaisesRegex(ValueError, "prediction member omitted"):
                c.collect(run, root / "bad")

    def test_same_year_intersection_and_trade_floor_cannot_be_replaced_by_marginals(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"; frames, _ = fixture(run)
            frame = copy.deepcopy(frames[0])
            frame["folds"][2]["effects"]["G_minus_B"] = -.01
            frame["folds"][3]["effects"]["G_minus_cash"] = -.01
            conditions, years, _ = c.criterion(frame)
            self.assertEqual(years, 2)  # Each comparison separately has three positive years.
            self.assertFalse(conditions["three_same_positive_years"])
            frame = copy.deepcopy(frames[0]); frame["economics"]["all_outer"]["primary"]["G"]["completed_trades"] = 19
            self.assertFalse(c.criterion(frame)[0]["twenty_G_completed_trades"])
            frame["economics"]["all_outer"]["primary"]["G"]["completed_trades"] = 20
            self.assertTrue(c.criterion(frame)[0]["twenty_G_completed_trades"])
            for comparison in c.COMPARISONS:
                frame["bootstrap"]["7"]["comparisons"][comparison]["mean_daily_net_log_gain"] = 0
            self.assertFalse(c.criterion(frame)[0]["both_positive_gain"])

    def test_wrong_conditions_holm_and_outer_promotion_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; fixture(run)
            path = run / "analysis.json"; original = c.shared.load_json(path)
            variants = []
            bad = copy.deepcopy(original); bad["timeframes"][0]["conditions"]["three_same_positive_years"] = False; variants.append(bad)
            bad = copy.deepcopy(original); bad["timeframes"][0]["p_holm"] = .006; variants.append(bad)
            bad = copy.deepcopy(original); bad["timeframes"][0]["outcome"] = "supported"; variants.append(bad)
            bad = copy.deepcopy(original); bad["timeframes"][0]["bootstrap"]["7"]["intersection_union_p"] = 0.; variants.append(bad)
            for i, analysis in enumerate(variants):
                save(path, analysis); reseal(run)
                with self.subTest(i=i), self.assertRaises(ValueError):
                    c.collect(run, root / "bad")
                self.assertFalse((root / "bad").exists())

    def test_protocol_registry_is_exact_closed_and_does_not_admit_amendments(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"; fixture(run)
            identity = c.shared.load_json(run / "run.json")
            for key, value in (("freeze_commit", "0" * 40), ("protocol_sha256", "0" * 64),
                               ("amendments", ["different model"]), ("deviations", ["ignore costs"])):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    c.admitted_protocol(run, {**identity, key: value})
            with mock.patch.dict(c.SUPPORTED_PROTOCOLS, {SHA: {**c.SUPPORTED_PROTOCOLS[SHA], "freeze_commit": None}}):
                with self.assertRaisesRegex(ValueError, "unpublished"):
                    c.admitted_protocol(run, identity)
            (run / "protocol.json").write_bytes(PROTOCOL.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not explicitly admitted"):
                c.admitted_protocol(run, identity)

    def test_unsealed_receipt_and_sealed_array_corruption_are_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root / "run"; fixture(run)
            extra = run / "unsealed-execution.log"; extra.write_text("extra")
            with self.assertRaisesRegex(ValueError, "unsealed file"):
                c.collect(run, root / "bad")
            extra.unlink()
            (run / "15m/year2023.npz").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum differs"):
                c.collect(run, root / "bad")
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
