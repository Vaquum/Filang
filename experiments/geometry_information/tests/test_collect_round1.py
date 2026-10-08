"""Synthetic receipt tests; no market data or model fitting is performed."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

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
                "status": "COMPLETE_PENDING_INDEPENDENT_AUDIT",
                "protocol_sha256": collector.PROTOCOL_SHA256,
                "source_provenance_sha256": collector.digest(run / "provenance.json"),
                "input_paths": {"keys_dir": str(keys_root)},
                "command": ["synthetic-only-no-fitting"], "implementation": {"synthetic": True},
                "runtime": {"synthetic": True}, "settings": {"workers": 1}}
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
            for scenario, policies in economic.items():
                for policy, value in policies.items():
                    save(run / f"{minutes}m/{year}/economics/outer/{scenario}/{policy}/metrics.json", value)
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
                          "outer_predictions": 20, "validation_predictions": 20, "ledger_replays": 480,
                          "all_records": True, "sampled": False}}
    save(run / "verification.json", audit)
    return manifest, audit


class CollectorTests(unittest.TestCase):
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
