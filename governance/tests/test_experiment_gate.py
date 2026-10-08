"""The law's negative cases are tests, not scientific/performance observations."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from governance import experiment_gate as gate

ROOT = Path(__file__).resolve().parents[2]
POLICY = gate.load_policy(ROOT / "governance/experiment-policy.json")


def record(kind="results", ident="A1", outcome="supported"):
    values = {
        "Claim": "The candidate improves the declared direction prediction over its frozen baseline.",
        "Decision criterion": "Held-out log loss is below the baseline under the recorded grouping.",
        "Method": "Use the frozen dataset and grouped protocol, preserving all failed outcomes.",
        "Evidence": "https://github.com/mikkokotila/Filang/pull/22",
        "Outcome": outcome,
        "Observation": "The measured score is compared with the baseline in the linked evidence.",
        "Residue": "Cross-market generalization remains untested by this experiment.",
        "Next steps": "Test a separately reserved period in a future PR before making transfer claims.",
    }
    text = f"## Experiment: {ident}\n\nType: {kind}\n"
    for heading, fields in POLICY["sections"].items():
        text += f"\n### {heading}\n\n" + "\n".join(f"{k}: {values[k]}" for k in fields) + "\n"
    text += "\n### Completion checklist\n\n" + "\n".join(f"- [x] {c}" for c in POLICY["checks"])
    return text + "\n"


def maintenance():
    return ("## Maintenance declaration\n\nReason: Editorial change only; no measurements, "
            "models or experimental conclusions change.\n\n- [x] " + POLICY["maintenance_check"] + "\n")


def check(body, title="feat: evaluate a documented change", paths=None):
    return gate.validate(body, title, paths or ["README.md"], POLICY, ROOT)


class RecordTests(unittest.TestCase):
    def test_results_and_performance_accept_all_three_outcomes(self):
        for kind in ["results", "performance"]:
            for outcome in ["supported", "not-supported", "inconclusive"]:
                with self.subTest(kind=kind, outcome=outcome):
                    self.assertTrue(check(record(kind, outcome=outcome))["passed"])

    def test_multiple_separate_attempts(self):
        result = check(record() + "\n" + record("performance", "P1", "not-supported"))
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["attempts"]), 2)

    def test_each_confirmation_is_required_checked_for_each_type(self):
        for kind in ["results", "performance"]:
            for confirmation in POLICY["checks"]:
                body = record(kind).replace(f"- [x] {confirmation}", f"- [ ] {confirmation}")
                with self.subTest(kind=kind, confirmation=confirmation):
                    self.assertFalse(check(body)["passed"])

    def test_missing_or_renamed_confirmation(self):
        for confirmation in POLICY["checks"]:
            with self.subTest(confirmation=confirmation):
                self.assertFalse(check(record().replace(f"- [x] {confirmation}", ""))["passed"])
                self.assertFalse(check(record().replace(confirmation, "Reviewed everything."))["passed"])

    def test_case_and_bullet_variants_are_checked(self):
        for bullet in ["-", "*", "+"]:
            self.assertTrue(check(record().replace("- [x]", f"{bullet} [X]"))["passed"])
            self.assertFalse(check(record().replace("- [x]", f"{bullet} [ ]"))["passed"])

    def test_every_field_is_required(self):
        for fields in POLICY["sections"].values():
            for field in fields:
                with self.subTest(field=field):
                    body = re.sub(rf"^{field}:.*$", "", record(), flags=re.MULTILINE)
                    self.assertFalse(check(body)["passed"])

    def test_each_section_required_exactly_once_in_order(self):
        for heading in list(POLICY["sections"]) + ["Completion checklist"]:
            with self.subTest(heading=heading):
                self.assertFalse(check(record().replace(f"### {heading}", "### Wrong heading"))["passed"])
                self.assertFalse(check(record().replace(f"### {heading}", f"### {heading}\n### {heading}"))["passed"])

    def test_placeholder_and_empty_values_fail(self):
        for placeholder in ["", "TODO", "TBD after the run", "<actual observation>", "not applicable", "..."]:
            with self.subTest(placeholder=placeholder):
                body = re.sub(r"^Observation:.*$", f"Observation: {placeholder}", record(), flags=re.MULTILINE)
                self.assertFalse(check(body)["passed"])

    def test_pending_is_not_a_completed_outcome(self):
        for outcome in ["pending", "success", "failed", "supported or inconclusive", "N/A"]:
            self.assertFalse(check(record(outcome=outcome))["passed"])

    def test_duplicates_cannot_shadow_the_actual_record(self):
        for body in [record() + record(), record() + record(ident="a1"),
                     record().replace("Type: results", "Type: results\nType: results"),
                     record().replace("Claim:", "Claim: Duplicate hypothesis.\nClaim:")]:
            self.assertFalse(check(body)["passed"])

    def test_unchecked_extra_box_and_overrule_are_not_exemptions(self):
        self.assertFalse(check(record() + "- [ ] an extra requirement\n")["passed"])
        self.assertFalse(check(record().replace("- [x]", "- [ ]", 1) + "OVERRULED: maintainer exception\n")["passed"])

    def test_hidden_examples_cannot_supply_record(self):
        for wrap in [lambda s: f"<!--\n{s}\n-->", lambda s: f"```md\n{s}\n```",
                     lambda s: f"~~~~\n{s}\n~~~~", lambda s: "\n".join("> " + v for v in s.splitlines()),
                     lambda s: "\n".join("    " + v for v in s.splitlines())]:
            self.assertFalse(check(wrap(record()))["passed"])
            self.assertTrue(check(record() + "\n" + wrap(record()))["passed"])

    def test_hidden_checked_copy_cannot_rescue_unchecked_record(self):
        body = record().replace("- [x]", "- [ ]") + "\n```md\n" + record() + "\n```"
        self.assertFalse(check(body)["passed"])

    def test_raw_html_examples_cannot_supply_record(self):
        for tag in ["pre", "code", "script", "style", "textarea", "PRE", "CoDe"]:
            with self.subTest(tag=tag):
                wrapped = f'<{tag} class="example">\n{record()}\n</{tag}>'
                self.assertFalse(check(wrapped)["passed"])
                self.assertTrue(check(record() + "\n" + wrapped)["passed"])
                self.assertFalse(check(record().replace("- [x]", "- [ ]")
                                       + "\n" + wrapped)["passed"])

    def test_unclosed_and_multiline_html_examples_fail_closed(self):
        for prefix in ["<pre>\n", "<code>\n", "<SCRIPT src='example'>\n",
                       "<textarea\nclass='example'>\n", "<pre\n"]:
            with self.subTest(prefix=prefix):
                self.assertFalse(check(prefix + record())["passed"])

    def test_html_inside_fenced_or_quoted_example_does_not_hide_real_record(self):
        for prefix in ["```html\n<pre>\n```\n", "> <pre>\n", "    <pre>\n"]:
            self.assertTrue(check(prefix + record())["passed"])

    def test_literal_comment_in_example_does_not_hide_real_record(self):
        for prefix in ['```python\nprint("<!--")\n```\n', "> <!--\n",
                       "    <!--\n", "\t<!--\n", "<pre>\n<!--\n</pre>\n"]:
            with self.subTest(prefix=prefix):
                self.assertTrue(check(prefix + record())["passed"])

    def test_operative_comments_hide_inline_and_multiline_records(self):
        self.assertFalse(check("<!--" + record() + "-->")["passed"])
        self.assertTrue(check("<!--\n> -->\n" + record())["passed"])
        self.assertTrue(check("<!-- hidden -->\n" + record())["passed"])
        self.assertFalse(check(record().replace("- [x]", "- <!--x-->[ ]"))["passed"])

    def test_unclosed_comment_or_fence_fails_closed(self):
        for prefix in ["<!--\n", "```md\n", "~~~\n"]:
            self.assertFalse(check(prefix + record())["passed"])

    def test_bad_id_and_type(self):
        for ident in ["", "../a", "A B", "a" * 65]:
            self.assertFalse(check(record(ident=ident))["passed"])
        self.assertFalse(check(record(kind="unknown"))["passed"])

    def test_evidence_must_resolve_or_be_https(self):
        original = "https://github.com/mikkokotila/Filang/pull/22"
        for good in ["governance/README.md", "[law](CLAUDE.md)", "<https://github.com/mikkokotila/Filang/pull/22>"]:
            self.assertTrue(check(record().replace(original, good))["passed"])
        for bad in ["not-a-real-file.json", "http://example.com/report", "javascript:alert(1)", "../outside.md", "none"]:
            self.assertFalse(check(record().replace(original, bad))["passed"])

    def test_title_hints_require_matching_type(self):
        self.assertFalse(check(record(), "perf(core): reduce runtime")["passed"])
        self.assertTrue(check(record("performance"), "perf(core)!: reduce runtime")["passed"])
        self.assertFalse(check(record("performance"), "results: improve direction forecasts")["passed"])
        self.assertTrue(check(record(), "Any ordinary title is allowed")["passed"])


class MaintenanceTests(unittest.TestCase):
    def test_explicit_non_experiment_passes(self):
        self.assertTrue(check(maintenance())["passed"])

    def test_unchecked_and_unexplained_do_not_pass(self):
        self.assertFalse(check(maintenance().replace("[x]", "[ ]"))["passed"])
        self.assertFalse(check(re.sub(r"Reason:.*", "Reason: TODO", maintenance()))["passed"])
        self.assertFalse(check("")["passed"])

    def test_duplicate_or_mixed_declaration_fails(self):
        self.assertFalse(check(maintenance() + maintenance())["passed"])
        self.assertFalse(check(maintenance() + record())["passed"])

    def test_formal_artifacts_and_perf_title_cannot_be_maintenance(self):
        for path in ["models/frozen.json", "benchmarks/reports/run/README.md"]:
            self.assertFalse(check(maintenance(), paths=[path])["passed"])
        self.assertFalse(check(maintenance(), title="perf: faster core")["passed"])


class InputTests(unittest.TestCase):
    def pr(self, body=None):
        return {"number": 3, "title": "ci: experiment gate", "body": maintenance() if body is None else body,
                "head": {"sha": "a" * 40}, "changed_files": 1}

    def test_flat_and_paginated_files(self):
        for files in [[{"filename": "README.md"}], [[{"filename": "README.md"}]]]:
            self.assertEqual(gate.metadata(self.pr(), files)[2], ["README.md"])

    def test_page_101_and_renamed_old_path_are_checked(self):
        pr = self.pr(); pr["changed_files"] = 101
        pages = [[{"filename": f"docs/{i}.md"} for i in range(100)],
                 [{"filename": "docs/moved.json", "previous_filename": "models/old.json"}]]
        body, title, paths = gate.metadata(pr, pages)
        self.assertIn("models/old.json", paths)
        self.assertFalse(gate.validate(body, title, paths, POLICY)["passed"])
        with self.assertRaises(ValueError):
            gate.metadata(pr, pages[:1])

    def test_missing_and_duplicate_metadata_fail(self):
        for key in ["number", "title", "head", "changed_files"]:
            pr = self.pr(); del pr[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.metadata(pr, [{"filename": "README.md"}])
        pr = self.pr(); pr["changed_files"] = 2
        with self.assertRaises(ValueError):
            gate.metadata(pr, [{"filename": "README.md"}] * 2)

    def test_null_body_is_noncompliant_not_skipped(self):
        pr = self.pr(); pr["body"] = None
        body, title, paths = gate.metadata(pr, [{"filename": "README.md"}])
        self.assertFalse(gate.validate(body, title, paths, POLICY)["passed"])

    def test_cli_exit_codes_hashes_and_stale_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pr.json").write_text(json.dumps(self.pr()))
            (root / "files.json").write_text('[{"filename":"README.md"}]')
            args = [sys.executable, str(ROOT / "governance/experiment_gate.py"),
                    "--pr-json", str(root / "pr.json"), "--files-json", str(root / "files.json"),
                    "--report", str(root / "report.json")]
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["body_sha256"], gate.digest(maintenance().encode()))
            self.assertEqual(report["head_sha"], "a" * 40)
            self.assertEqual(report["schema"], "filang-experiment-gate-v1")
            self.assertEqual(subprocess.run(args + ["--expected-head", "b" * 40], capture_output=True).returncode, 2)
            (root / "pr.json").write_text(json.dumps(self.pr("")))
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
            (root / "pr.json").write_text("{")
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
            self.assertEqual(subprocess.run(args + ["--policy", str(root / "missing")], capture_output=True).returncode, 2)

    def test_malformed_policy_fails_closed(self):
        for bad in [{}, [], {**POLICY, "schema_version": 99}, {**POLICY, "checks": []}]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policy.json"; path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    gate.load_policy(path)


class ContractTests(unittest.TestCase):
    def test_template_requires_completion_not_just_copying(self):
        template = (ROOT / POLICY["template"]).read_text()
        self.assertFalse(check(template)["passed"])
        self.assertFalse(check(template.replace("[ ]", "[x]"))["passed"])
        for heading in list(POLICY["sections"]) + [POLICY["checklist_heading"]]:
            self.assertEqual(template.count(f"### {heading}\n"), 1)
        self.assertEqual([m[2] for m in gate.CHECK.finditer(template)], POLICY["checks"])
        for fields in POLICY["sections"].values():
            for field in fields:
                self.assertEqual(len(re.findall(rf"^{field}:", template, flags=re.MULTILINE)), 1)

    def test_law_policy_and_proposed_check_agree(self):
        law = (ROOT / POLICY["law"]).read_text()
        self.assertIn(f"*({POLICY['check_name']})*", law)
        self.assertIn("Law 1", law); self.assertNotIn("Law 2", law)
        ruleset = json.loads((ROOT / ".github/rulesets/experiment-record.json").read_text())
        self.assertEqual(ruleset["bypass_actors"], [])
        self.assertEqual(ruleset["enforcement"], "disabled")
        self.assertIn("proposed", ruleset["name"].lower())
        readme = (ROOT / "governance/README.md").read_text()
        self.assertIn("not deployed", readme)
        self.assertIn("cannot attest", readme)
        self.assertEqual(ruleset["conditions"]["ref_name"], {"include": ["refs/heads/main"], "exclude": []})
        self.assertEqual(len(ruleset["rules"]), 1)
        rule = ruleset["rules"][0]
        self.assertEqual(rule["type"], "required_status_checks")
        self.assertTrue(rule["parameters"]["strict_required_status_checks_policy"])
        self.assertEqual(rule["parameters"]["required_status_checks"],
                         [{"context": POLICY["check_name"], "integration_id": 15368}])
        self.assertEqual(POLICY["experiment_types"], ["results", "performance"])
        self.assertEqual(POLICY["outcomes"], ["supported", "not-supported", "inconclusive"])
        self.assertEqual(list(POLICY["sections"]), ["Hypothesis", "Experiment", "Result", "Residue and next steps"])

    def test_workflow_is_live_scoped_and_nonprivileged(self):
        workflow = (ROOT / ".github/workflows/pr_checks_experiment.yml").read_text()
        self.assertIn(f"    name: {POLICY['check_name']}\n", workflow)
        for event in ["opened", "edited", "synchronize", "reopened", "ready_for_review", "converted_to_draft"]:
            self.assertIn(event, workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotRegex(workflow, r"(?:paths|paths-ignore):")
        self.assertNotIn("write", workflow)
        for fragment in ["--paginate --slurp", "--expected-head", "python governance/experiment_gate.py",
                         "python -m unittest discover -s governance/tests -v", "persist-credentials: false"]:
            self.assertIn(fragment, workflow)
        self.assertNotIn("github.event.pull_request.body", workflow)
        self.assertNotIn("github.event.pull_request.title", workflow)
        self.assertEqual(re.findall(r"^\s+if: (.*)$", workflow, flags=re.MULTILINE), ["always()"])
        actions = re.findall(r"uses: (\S+)", workflow)
        self.assertEqual(len(actions), 3)
        for action in actions:
            self.assertRegex(action, r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
