"""Synthetic receipt tests; no market data or model fitting is performed."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments.geometry_information import collect_round1 as collector


PROTOCOL = Path(collector.__file__).with_name("round1_protocol.json")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(collector.json_bytes(value))


def fixture(run):
    """Build a clearly synthetic complete-shape producer/audit receipt set."""
    run.mkdir()
    (run / "protocol.json").write_bytes(PROTOCOL.read_bytes())
    save(run / "provenance.json", {"synthetic": True})
    keys_root = run.parent / "synthetic-keys"
    feature_frames = []
    for minutes in collector.TIMEFRAMES:
        root = keys_root / f"{minutes}m"
        save(root / "context.json", {"engine_sha256": "e" * 64, "source_sha256": "d" * 64})
        save(root / "timings.json", {"synthetic": True})
        (root / "keys.bin").write_bytes(b"SYNTHETIC NATIVE KEY PAYLOAD")
        native_manifest = {"status": "COMPLETE", "context_sha256": collector.digest(root / "context.json"),
                           "timings_sha256": collector.digest(root / "timings.json"),
                           "keys_file_sha256": collector.digest(root / "keys.bin"),
                           "keys_file_bytes": (root / "keys.bin").stat().st_size}
        save(root / "manifest.json", native_manifest)
        (root / "manifest.sha256").write_text(collector.digest(root / "manifest.json") + "\n")
        feature_frames.append({"minutes": minutes, "source_sha256": "d" * 64,
                               "native": {"manifest_sha256": collector.digest(root / "manifest.json"),
                                          "context_sha256": native_manifest["context_sha256"],
                                          "engine_sha256": "e" * 64, "keys_sha256": native_manifest["keys_file_sha256"]}})
    save(run / "features.json", {"timeframes": feature_frames})
    identity = {"freeze_commit": collector.FREEZE_COMMIT,
                "amendments": [], "deviations": [],
                "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "protocol_sha256": collector.PROTOCOL_SHA256,
                "source_provenance_sha256": collector.digest(run / "provenance.json"),
                "input_paths": {"keys_dir": str(keys_root), "data_dir": "/synthetic data/pinned-csv", "out": str(run)},
                "command": ["synthetic-only-no-fitting"], "implementation": {"synthetic": True},
                "runtime": {"synthetic": True}, "settings": {"workers": 1, "blas_threads": 1}}
    save(run / "run.json", identity)
    (run / "fits.jsonl").write_text("".join(json.dumps({"synthetic_fit": i}) + "\n" for i in range(680)))
    with (run / "candidates.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["synthetic_candidate"])
        writer.writerows([[i] for i in range(640)])
    save(run / "selected.json", {"selections": [{"synthetic_selection": i} for i in range(40)]})
    (run / "classification_daily.csv").write_text("synthetic\n1\n")
    metrics = {"net_return": .1, "net_log_return": .0953101798043249, "exposure_fraction": .5,
               "one_way_turnover": 10, "break_even_symmetric_cost_bps_per_side": 3.0}
    economic = {scenario: {policy: dict(metrics) for policy in ("B", "G", "unconditional", "lag1", "cash", "buy_hold")}
                for scenario in ("zero", "reduced", "primary", "stress")}
    score = {"binary_count": 100, "flat_count": 2, "binary_log_loss": .69, "brier": .25,
             "accuracy": .5, "balanced_accuracy": .5}
    frames = []
    for minutes in collector.TIMEFRAMES:
        gain = .01 if minutes == 15 else -.01
        yes = gain > 0
        choices = {family: {"n": 2, "lambda": .1} for family in ("B", "G")}
        folds = [{"year": year, "gain": gain, "selected": choices, "economics": economic}
                 for year in collector.YEARS]
        bs = {"gain": gain, "ci95_low": gain / 2 if yes else gain * 2,
              "ci95_high": gain * 2 if yes else gain / 2, "p_one_sided": .001 if yes else .9}
        frames.append({"minutes": minutes, "folds": folds,
                       "bootstrap": {str(b): dict(bs) for b in (1, 7, 28)},
                       "positive_years": 4 if yes else 0, "p_holm": .005 if yes else 1.,
                       "conditions": {"positive_gain": yes, "ci_above_zero": yes,
                                      "holm_below_005": yes, "three_positive_years": yes},
                       "criterion_met": yes, "outcome": "inconclusive",
                       "outcome_if_verified": "supported" if yes else "not-supported",
                       "pooled_scores": {p: dict(score) for p in ("B", "G", "unconditional", "lag1")},
                       "economics": {"all_outer": economic, "continuous_2024_plus": economic}})
        for year in collector.YEARS:
            for phase in ("validation", "outer"):
                (run / f"{minutes}m/{year}").mkdir(parents=True, exist_ok=True)
                (run / f"{minutes}m/{year}/{phase}.npz").write_bytes(b"SYNTHETIC PREDICTION PAYLOAD")
                save(run / f"{minutes}m/{year}/{phase}.json", {"synthetic": True})
                for scenario, policies in economic.items():
                    for policy, value in policies.items():
                        save(run / f"{minutes}m/{year}/economics/{phase}/{scenario}/{policy}/metrics.json", value)
    analysis = {"protocol_sha256": collector.PROTOCOL_SHA256, "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "timeframes": frames}
    save(run / "analysis.json", analysis)
    (run / "synthetic-rows.npz").write_bytes(b"SYNTHETIC OMITTED BINARY PAYLOAD")
    manifest = {"schema": "synthetic", "files": {
        p.relative_to(run).as_posix(): collector.file_record(p) for p in sorted(run.rglob("*")) if p.is_file()}}
    save(run / "manifest.json", manifest)
    (run / "manifest.sha256").write_text(collector.digest(run / "manifest.json") + "\n")
    audit = {"schema": "filang-geometry-information-verification-v1", "stage": "full", "status": "PASS",
             "protocol_sha256": collector.PROTOCOL_SHA256,
             "producer_manifest_sha256": collector.digest(run / "manifest.json"),
             "analysis_sha256": collector.digest(run / "analysis.json"),
             "audited_timeframes": list(collector.TIMEFRAMES), "audited_outer_years": list(collector.YEARS),
             "coverage": {"native_keys": 458972, "candidate_fits": 640, "refit_fits": 40,
                          "outer_predictions": 20, "validation_predictions": 20, "ledger_replays": 960,
                          "all_records": True, "sampled": False}}
    save(run / "verification.json", audit)
    return manifest, audit


class CollectorTests(unittest.TestCase):
    def test_external_receipts_preserve_run_ownership_and_bind_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, out = root / "run", root / "report"
            fixture(run)
            identity = collector.load_json(run / "run.json")
            launcher, execution_log, audit_log = root / "launcher.json", root / "execution.log", root / "audit.log"
            execution_log.write_text("synthetic successful execution\n")
            audit_log.write_text("synthetic independent audit\n")
            payload = {"command": identity["command"], "exit_code": 0, "elapsed_seconds": 106.97,
                       "log": str(execution_log)}
            save(launcher, payload)
            before = {p.relative_to(run).as_posix(): collector.file_record(p) for p in run.rglob("*") if p.is_file()}
            collector.collect(run, out, launcher=launcher, audit_receipts=[audit_log])
            after = {p.relative_to(run).as_posix(): collector.file_record(p) for p in run.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(launcher.read_bytes(), (out / "operational/launcher.json").read_bytes())
            self.assertEqual(execution_log.read_bytes(), (out / "operational/execution.log").read_bytes())
            self.assertEqual(audit_log.read_bytes(), (out / "operational/audit/audit.log").read_bytes())
            retained = collector.load_json(out / "retained-artifacts.json")["external_operational_receipts"]
            self.assertTrue(all(r["included_in_producer_manifest"] is False for r in retained.values()))
            self.assertNotIn("operational/launcher.json", collector.load_json(run / "manifest.json")["files"])
            for key, value in (("command", ["wrong-command"]), ("exit_code", 1), ("elapsed_seconds", 0)):
                bad = {**payload, key: value}
                save(launcher, bad)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    collector.collect(run, root / "rejected-report", launcher=launcher)
                self.assertFalse((root / "rejected-report").exists())
            with self.assertRaisesRegex(ValueError, "outside the sealed run"):
                collector.operational_receipts(run, identity, None, [run / "verification.json"])
            # macOS temporary roots may use /var while resolve() returns
            # /private/var. Model this alias explicitly on every platform.
            alias = root / "run-alias"
            alias.symlink_to(run.resolve(), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside the sealed run"):
                collector.operational_receipts(alias, identity, None, [run / "verification.json"])
            with self.assertRaisesRegex(ValueError, "outside the sealed run"):
                collector.operational_receipts(run, identity, None, [alias / "verification.json"])

    def test_amendment_registry_is_exact_and_fails_closed(self):
        original = (collector.FREEZE_COMMIT, collector.PROTOCOL_SHA256)
        proto_path = PROTOCOL.with_name("round1a_protocol.json")
        protocol = collector.load_json(proto_path)
        checksum = collector.digest(proto_path)
        registered = collector.PROTOCOL_REGISTRY[checksum]
        identity = {"freeze_commit": registered["freeze_commit"], "protocol_sha256": checksum,
                    "amendments": [protocol["amendment"]], "deviations": []}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "protocol.json").write_bytes(proto_path.read_bytes())
            profile, _ = collector.admitted_protocol(run, identity)
            self.assertEqual(profile["attempt_id"], "R1a")
            changes = [("freeze_commit", collector.FREEZE_COMMIT), ("amendments", []),
                       ("deviations", ["different optimizer"]), ("protocol_sha256", collector.PROTOCOL_SHA256)]
            for key, value in changes:
                bad = copy.deepcopy(identity); bad[key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    collector.admitted_protocol(run, bad)
            unpublished = {**registered, "freeze_commit": None}
            with mock.patch.dict(collector.PROTOCOL_REGISTRY, {checksum: unpublished}), self.assertRaises(ValueError):
                collector.admitted_protocol(run, identity)
            (run / "protocol.json").write_bytes(proto_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "not admitted"):
                collector.admitted_protocol(run, identity)
        self.assertEqual(original, ("b1ac3bc49b8a616cc9e7b84112eb0a0934a8affd",
                                   "abf7a0424302160a951c90fe9be23391209e4007cb8f7b51a6462ca04cc1524a"))

    def test_r1a_collection_uses_new_identity_and_recorded_reproduction_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, out = root / "run", root / "report"
            fixture(run)
            protocol_path = PROTOCOL.with_name("round1a_protocol.json")
            protocol = collector.load_json(protocol_path)
            checksum = collector.digest(protocol_path)
            profile = collector.PROTOCOL_REGISTRY[checksum]
            (run / "protocol.json").write_bytes(protocol_path.read_bytes())
            identity = collector.load_json(run / "run.json")
            identity.update(protocol_sha256=checksum, freeze_commit=profile["freeze_commit"],
                            amendments=[protocol["amendment"]], deviations=[])
            save(run / "run.json", identity)
            analysis = collector.load_json(run / "analysis.json")
            analysis["protocol_sha256"] = checksum
            save(run / "analysis.json", analysis)
            manifest = collector.load_json(run / "manifest.json")
            for name in ("protocol.json", "run.json", "analysis.json"):
                manifest["files"][name] = collector.file_record(run / name)
            save(run / "manifest.json", manifest)
            (run / "manifest.sha256").write_text(collector.digest(run / "manifest.json") + "\n")
            audit = collector.load_json(run / "verification.json")
            audit.update(protocol_sha256=checksum, producer_manifest_sha256=collector.digest(run / "manifest.json"),
                         analysis_sha256=collector.digest(run / "analysis.json"))
            save(run / "verification.json", audit)
            collector.collect(run, out)
            package = collector.load_json(out / "manifest.json")
            self.assertEqual(package["protocol_sha256"], checksum)
            self.assertEqual(package["freeze_commit"], profile["freeze_commit"])
            readme = (out / "README.md").read_text()
            self.assertIn("Round 1a", readme)
            self.assertIn("completed PR #25 tree", readme)
            self.assertIn("--data-dir '/synthetic data/pinned-csv'", readme)
            self.assertIn("round1a_protocol.json", readme)
            self.assertIn("20261008-geometry-information-r1a", readme)
            reproduction = collector.load_json(out / "reproduction.json")
            self.assertEqual(reproduction["amendments"], [protocol["amendment"]])
            self.assertIn(str(run), reproduction["independent_audit_argv"])
            for native_command in reproduction["native_export_argv"]:
                self.assertEqual(native_command[-2:], ["--resume", "true"])
            self.assertIn("without executing native preparation again", readme)

    def test_full_shape_collection_preserves_bytes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, out = root / "run", root / "report"
            fixture(run)
            result = collector.collect(run, out)
            self.assertEqual(result["outcomes"]["15"], "supported")
            self.assertEqual(result["outcomes"]["30"], "not-supported")
            self.assertEqual((run / "analysis.json").read_bytes(), (out / "analysis.json").read_bytes())
            self.assertFalse((out / "synthetic-rows.npz").exists())
            external = collector.load_json(out / "retained-artifacts.json")["external_files"]
            self.assertIn("synthetic-rows.npz", external)
            self.assertEqual(collector.digest(out / "manifest.json"), (out / "manifest.sha256").read_text().strip())
            before = collector.digest(out / "manifest.json")
            collector.collect(run, out)
            self.assertEqual(before, collector.digest(out / "manifest.json"))
            (out / "README.md").write_text("deliberately edited")
            with self.assertRaisesRegex(ValueError, "existing report artifact differs"):
                collector.collect(run, out)

    def test_source_mutation_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root / "run")
            (root / "run/fits.jsonl").write_text("changed after audit")
            with self.assertRaisesRegex(ValueError, "checksum differs"):
                collector.collect(root / "run", root / "report")
            self.assertFalse((root / "report").exists())

    def test_audit_cannot_be_partial_sampled_stale_or_omit_ledgers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, audit = fixture(root / "run")
            variants = []
            for key, value in (("stage", "features"), ("producer_manifest_sha256", "0" * 64),
                               ("analysis_sha256", "0" * 64), ("audited_timeframes", [15])):
                changed = copy.deepcopy(audit)
                changed[key] = value
                variants.append(changed)
            for key, value in (("sampled", True), ("all_records", False), ("candidate_fits", 639), ("ledger_replays", 479)):
                changed = copy.deepcopy(audit)
                changed["coverage"][key] = value
                variants.append(changed)
            for changed in variants:
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    collector.check_audit(root / "run", changed, manifest)

    def test_paths_and_criterion_boundaries_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for relative in ("../escape", str(root / "absolute"), ".", ""):
                with self.assertRaises(ValueError):
                    collector.bounded(root, relative)
        self.assertEqual(collector.outcome(.01, .001, .049, 3), "supported")
        for values in ((0, .001, .01, 4), (.01, 0, .01, 4), (.01, .001, .05, 4), (.01, .001, .01, 2)):
            self.assertEqual(collector.outcome(*values), "not-supported")


if __name__ == "__main__":
    unittest.main()
