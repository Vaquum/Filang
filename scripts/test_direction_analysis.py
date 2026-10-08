#!/usr/bin/env python3
"""Synthetic checks for chronological fitting, independent scoring and inference."""
from __future__ import annotations

import contextlib
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import analyze_direction as analysis
import verify_direction as verify


def fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    step = 14400
    bounds = {"history_start": "2020-01-01", "validation_start": "2020-02-10",
              "test_start": "2020-03-20", "end": "2020-05-01"}
    times = np.arange(verify.epoch(bounds["history_start"]), verify.epoch(bounds["end"]), step)
    # Known holes in each phase exercise n-dependent native eligibility and the
    # common ten-bar future comparison sample.
    keep = np.ones(len(times), dtype=bool)
    keep[[35, 36, 255, 490]] = False
    times = times[keep]
    random = np.random.default_rng(7721)
    closes = 1000 + np.cumsum(random.integers(-3, 4, size=len(times)))
    opens = closes + random.integers(-2, 3, size=len(times))
    high = np.maximum(opens, closes) + random.integers(0, 3, size=len(times))
    low = np.minimum(opens, closes) - random.integers(0, 3, size=len(times))
    prices = np.column_stack((opens, high, low, closes)).astype(float)
    source_path = root / "candles.csv"
    with source_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for timestamp, row in zip(times, prices):
            writer.writerow([int(timestamp), *map(int, row), 1])
    source = {"times": times, "prices": prices, "interval_seconds": step,
              "path": str(source_path), "sha256": verify.sha256(source_path)}
    protocol = {"version": 1, **bounds,
                "analysis": {"alpha_grid": list(analysis.ALPHAS),
                             "bootstrap": {"unit": "UTC_day", "block_days": [7, 1, 28],
                                           "replicates": 2000, "seed": 20261008}}}
    analysis.dump_json(root / "protocol.json", protocol)
    tasks = []
    for n in (2, 10):
        for mode in ("oriented", "unoriented"):
            directory = root / "240m" / "tasks" / f"n{n:02d}-{mode}"
            directory.mkdir(parents=True)
            task = {"version": 1, "status": "COMPLETE", "bars": n, "mode": mode,
                    "interval_seconds": step, **bounds, "source_csv": str(source_path),
                    "source_sha256": verify.sha256(source_path), "source_bytes": source_path.stat().st_size,
                    "input_rows": len(times), "first_timestamp": int(times[0]), "last_timestamp": int(times[-1]),
                    "gap_count": int((np.diff(times) > step).sum()),
                    "missing_grid_bars": int((np.diff(times) // step - 1).sum())}
            indices, splits, counters = verify.eligible_indices(source, task)
            identities, patterns, counts, rows = {}, [], [], []
            for t, si in zip(indices, splits):
                t, si = int(t), int(si)
                canonical = verify.canonical_pattern(prices[t - np.arange(n)], mode)
                if canonical not in identities:
                    identities[canonical] = len(patterns)
                    patterns.append(canonical)
                    counts.append(np.zeros(18, dtype=np.int64))
                pid = identities[canonical]
                labels = [int(np.sign(prices[t + 1, 3] - prices[t, 3])),
                          int(np.sign(prices[t + 1, 3] - prices[t + 1, 0])),
                          int(np.sign(prices[t, 3] - prices[t - 1, 3])),
                          int(np.sign(prices[t, 3] - prices[t, 0]))]
                counts[pid][si * 6 + labels[0] + 1] += 1
                counts[pid][si * 6 + 3 + labels[1] + 1] += 1
                rows.append([int(times[t]), int(times[t + 1]), verify.SPLITS[si], pid, *labels])
            matrix = np.asarray(counts)
            totals = matrix.sum(axis=0).reshape((3, 2, 3))
            training = int((matrix[:, :6].sum(axis=1) > 0).sum())
            universe = verify.domain_count(n, mode)
            task.update({**counters, "universe_patterns": str(universe), "observed_patterns": len(patterns),
                         "unobserved_patterns": str(universe - len(patterns)), "training_observed_patterns": training,
                         "training_unobserved_patterns": str(universe - training),
                         "split_counts": {split: {target: {sign: int(totals[si, ti, yi])
                                                         for yi, sign in enumerate(verify.SIGNS)}
                                                  for ti, target in enumerate(verify.TARGETS)}
                                          for si, split in enumerate(verify.SPLITS)}})
            with (directory / "events.tsv").open("w", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t")
                writer.writerow(verify.EVENT_FIELDS)
                writer.writerows(rows)
            with (directory / "patterns.tsv").open("w", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t")
                writer.writerow(verify.PATTERN_FIELDS)
                for pid, (pattern, count) in enumerate(zip(patterns, counts)):
                    writer.writerow([pid, pattern, *map(int, count)])
            analysis.dump_json(directory / "summary.json", task)
            (directory / "task.identity").write_text("synthetic-only\n")
            analysis.dump_json(directory / "timing.json", {"task_seconds": 0})
            with (directory / "artifacts.tsv").open("w", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                writer.writerow(["file", "bytes", "sha256"])
                for name in ("events.tsv", "patterns.tsv", "summary.json", "task.identity", "timing.json"):
                    path = directory / name
                    writer.writerow([name, path.stat().st_size, verify.sha256(path)])
            (directory / "artifacts.tsv.sha256").write_text(verify.sha256(directory / "artifacts.tsv") + "\n")
            task["path"] = directory
            tasks.append(task)
    return tasks, source


class DirectionAnalysisTests(unittest.TestCase):
    def test_exact_counter_beyond_u128(self):
        self.assertEqual(verify.domain_count(2, "unoriented"), 2568)
        self.assertEqual(verify.domain_count(2, "oriented"), 7452)
        self.assertEqual(verify.domain_count(3, "oriented"), 32160252)
        self.assertGreater(verify.domain_count(10, "oriented"), 2 ** 128 - 1)

    def test_geometry_equalities_and_direction(self):
        candles = [(1, 3, 0, 2), (6, 7, 4, 5)]
        self.assertEqual(verify.canonical_pattern(candles, "oriented"),
                         "g1:o:0,1,2,3,u;4,5,6,7,d")
        self.assertEqual(verify.canonical_pattern([(2, 2, 2, 2)], "oriented"), "g1:o:0,0,0,0,z")

    def test_binary_flat_and_jeffreys(self):
        counts = np.array([[3, 7, 1], [0, 2, 0], [1, 0, 3]])
        p, prior = analysis.geometry_probability(counts, 10)
        self.assertEqual(prior, 0.5)
        self.assertEqual(p[1], prior)
        scored = analysis.metrics(counts, p)
        independently = verify.score_labels(np.array([-1] * 3 + [0] * 7 + [1] + [0] * 2 + [-1] + [1] * 3),
                                            np.array([p[0]] * 11 + [p[1]] * 2 + [p[2]] * 4))
        self.assertEqual(scored["n_flat"], 9)
        self.assertLess(verify.compare_metrics(scored, independently, "synthetic"), 1e-14)

    def test_roundoff_tie_break(self):
        rows = [{"bars": 10, "mode": "oriented", "alpha": 1, "validation": {"log_loss": .69}},
                {"bars": 2, "mode": "unoriented", "alpha": 1000, "validation": {"log_loss": .69 + 3e-16}}]
        self.assertEqual(analysis.select_candidate(rows)["bars"], 2)

    def test_holm_family(self):
        self.assertEqual(analysis.holm_adjust([.01, .03, .04, .2, .8]), [.05, .12, .12, .4, .8])

    def test_paired_block_bootstrap_independent_and_deterministic(self):
        random = np.random.default_rng(91)
        n = random.integers(80, 100, size=120)
        effect = .005 + random.normal(0, .002, size=120)
        accuracy = .01 + random.normal(0, .004, size=120)
        daily = {"n_binary": n, "lag1_loss_improvement_sum": n * effect,
                 "lag1_accuracy_change_sum": n * accuracy}
        for block in (7, 1, 28):
            first = analysis.paired_bootstrap(daily, "lag1", block, 200, 20261008)
            second = analysis.paired_bootstrap(daily, "lag1", block, 200, 20261008)
            self.assertEqual(first, second)
            reference = verify.independent_bootstrap(np.column_stack((n, n * effect, n * accuracy)), block, 200)
            for statistic in ("log_loss_improvement", "accuracy_change"):
                self.assertAlmostEqual(first[statistic]["estimate"], reference[statistic]["estimate"], places=13)
                np.testing.assert_allclose(first[statistic]["percentile_95_ci"], reference[statistic]["percentile_95_ci"], atol=1e-13)
                self.assertEqual(first[statistic]["one_sided_p"], reference[statistic]["one_sided_p"])
                self.assertGreater(first[statistic]["percentile_95_ci"][0], 0)
        zero = {"n_binary": n, "lag1_loss_improvement_sum": n * 0., "lag1_accuracy_change_sum": n * 0.}
        self.assertEqual(analysis.paired_bootstrap(zero, "lag1", 7, 200)["log_loss_improvement"]["one_sided_p"], 1.0)

    def test_end_to_end_and_no_test_label_leakage(self):
        with tempfile.TemporaryDirectory(prefix="filang-direction-analysis-") as temporary:
            base = Path(temporary)
            root = base / "native"
            tasks, source = fixture(root)
            for task in tasks:
                receipt = verify.audit_task(task, source)
                self.assertTrue(receipt["all_canonical_events_checked"])
                self.assertGreater(receipt["gap_purged"], 0)
                self.assertEqual(receipt["boundary_purged"], 2)
                sample = verify.audit_task(task, source, 7)
                self.assertFalse(sample["all_canonical_events_checked"])
                self.assertEqual(sample["canonical_events_checked"], 7)
            first_out = base / "first"
            with contextlib.redirect_stdout(io.StringIO()):
                analysis.main(["--runs", str(root), "--out", str(first_out), "--allow-partial"])
            first = json.loads((first_out / "analysis.json").read_text())
            audit = verify.audit_analysis(root, first_out, tasks, root / "protocol.json")
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["selected_models_checked"], 2)
            self.assertLess(audit["max_absolute_metric_error"], 1e-10)
            # Mutate only supplied test labels and their table totals. These are
            # intentionally no longer authentic source labels; this isolates the
            # analysis leakage property from source/feature reconstruction.
            for task in tasks:
                path = task["path"] / "events.tsv"
                with path.open(newline="") as stream:
                    rows = list(csv.reader(stream, delimiter="\t"))
                for row in rows[1:]:
                    if row[2] == "test":
                        row[4], row[5] = str(-int(row[4])), str(-int(row[5]))
                with path.open("w", newline="") as stream:
                    csv.writer(stream, delimiter="\t").writerows(rows)
                path = task["path"] / "patterns.tsv"
                with path.open(newline="") as stream:
                    rows = list(csv.reader(stream, delimiter="\t"))
                for row in rows[1:]:
                    row[14], row[16] = row[16], row[14]
                    row[17], row[19] = row[19], row[17]
                with path.open("w", newline="") as stream:
                    csv.writer(stream, delimiter="\t").writerows(rows)
            second_out = base / "second"
            with contextlib.redirect_stdout(io.StringIO()):
                analysis.main(["--runs", str(root), "--out", str(second_out), "--allow-partial"])
            second = json.loads((second_out / "analysis.json").read_text())
            for left, right in zip(first["selected"], second["selected"]):
                for key in ("bars", "mode", "alpha", "validation", "global_fit_probability", "baseline_model"):
                    self.assertEqual(left[key], right[key], key)
                self.assertEqual((first_out / left["probabilities_file"]).read_bytes(),
                                 (second_out / right["probabilities_file"]).read_bytes())
            self.assertNotEqual(first["selected"][0]["test"], second["selected"][0]["test"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
