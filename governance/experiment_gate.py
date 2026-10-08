#!/usr/bin/env python3
"""Mechanical enforcement of Law 1; no model fitting and no network access.

0: compliant PR, 1: incomplete/invalid record, 2: gate setup/input failure.
The policy is read on every invocation; missing policy never means 'skip'.
PR text is data only. Fenced/indented code, quotes and HTML comments cannot
supply required headings, fields or checked attestations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "governance/experiment-policy.json"
HEADING = re.compile(r"^## ([^\n]+?)\s*$", re.MULTILINE)
SUBHEADING = re.compile(r"^### ([^\n]+?)\s*$", re.MULTILINE)
FIELD = re.compile(r"^([A-Za-z][A-Za-z ]*):[ \t]*(.*)$", re.MULTILINE)
CHECK = re.compile(r"^\s*[-*+] +\[([ xX])\]\s*(.*?)\s*$", re.MULTILINE)
ATTEMPT = re.compile(r"Experiment: ([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\Z")
PLACEHOLDER = re.compile(r"<[^<>\n]+>|\b(?:TODO|TBD|FIXME)\b", re.IGNORECASE)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "check_name", "template", "law", "experiment_types",
        "sections", "checklist_heading", "checks", "outcomes", "maintenance_heading",
        "maintenance_check", "formal_path_prefixes", "title_type_hints",
    }
    if not isinstance(policy, dict) or set(policy) != required or policy["schema_version"] != 1:
        raise ValueError("policy has missing/unknown keys or an unsupported schema")
    for key in ("experiment_types", "checks", "outcomes", "formal_path_prefixes"):
        values = policy[key]
        if (not isinstance(values, list) or not values
                or not all(isinstance(v, str) and v for v in values)
                or len(set(values)) != len(values)):
            raise ValueError(f"policy {key} must be a nonempty unique string list")
    for key in ("check_name", "template", "law", "checklist_heading", "maintenance_heading", "maintenance_check"):
        if not isinstance(policy[key], str) or not policy[key]:
            raise ValueError(f"invalid policy {key}")
    if (not isinstance(policy["sections"], dict) or len(policy["sections"]) != 4
            or len(policy["checks"]) != 4):
        raise ValueError("the experiment law requires four sections and confirmations")
    for heading, fields in policy["sections"].items():
        if (not isinstance(heading, str) or not isinstance(fields, list) or not fields
                or not all(isinstance(f, str) and f for f in fields)
                or len(set(fields)) != len(fields)):
            raise ValueError("invalid section field configuration")
    hints = policy["title_type_hints"]
    if not isinstance(hints, dict) or any(v not in policy["experiment_types"] for v in hints.values()):
        raise ValueError("invalid title classification configuration")
    return policy


def visible(text: str) -> str:
    output: list[str] = []
    fence: tuple[str, int] | None = None
    html_close: re.Pattern | None = None
    comment = False
    html_open = re.compile(r"<(pre|code|script|style|textarea)(?=[\s/>]|$)", re.IGNORECASE)
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if html_close:
            if html_close.search(line):
                html_close = None
            output.append("")
            continue
        elif fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            output.append("")
            continue
        # Comment delimiters in an existing comment are literal, even when a
        # line looks like a quote or code. Delimiters inside actual examples
        # are ignored below and cannot swallow a later operative record.
        if comment:
            end = line.find("-->")
            if end < 0:
                output.append("")
                continue
            comment = False
            line = line[end + 3:]
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            fence = (marker[1][0], len(marker[1]))
            output.append("")
        elif line.startswith(("    ", "\t")) or re.match(r"^ {0,3}>", line):
            output.append("")
        else:
            pieces: list[str] = []
            while "<!--" in line:
                start = line.index("<!--")
                html = html_open.search(line)
                if html and html.start() < start:
                    break
                pieces.append(line[:start])
                end = line.find("-->", start + 4)
                if end < 0:
                    comment = True
                    line = ""
                    break
                line = line[end + 3:]
            line = "".join(pieces) + line
            # Raw HTML example containers do not make Markdown headings or
            # checkboxes operative. An unclosed container stays hidden to EOF.
            html = html_open.search(line)
            if html:
                closing = re.compile(rf"</\s*{html[1]}\s*>", re.IGNORECASE)
                if not closing.search(line, html.end()):
                    html_close = closing
                output.append("")
            else:
                output.append(line)
    return "\n".join(output)


def split_sections(text: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(text))
    return [(m[1], text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)])
            for i, m in enumerate(matches)]


def substantive(text: str) -> bool:
    clean = text.strip().strip("`*_")
    clean = re.sub(r"<https://[^\s>]+>", "reference", clean)
    return (len(clean) >= 12 and not PLACEHOLDER.search(clean)
            and clean.lower().rstrip(".! ") not in {
                "not applicable", "to be determined", "coming soon", "fill this in",
            })


def fields(text: str, expected: list[str], label: str, errors: list[str]) -> dict[str, str]:
    matches = list(FIELD.finditer(text))
    result: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match[1]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = (match[2] + text[match.end():end]).strip()
        if name in result:
            errors.append(f"{label}: duplicate field {name!r}")
        result[name] = value
    if set(result) != set(expected):
        errors.append(f"{label}: expected exactly the fields {', '.join(expected)}")
    return result


def evidence_exists(value: str, root: Path) -> bool:
    refs = re.findall(r"\[[^\]]+\]\(([^)]+)\)", value)
    if not refs:
        refs = [v.strip("`<>,;") for v in value.split()]
    for ref in refs:
        parsed = urlparse(ref)
        if parsed.scheme == "https" and parsed.netloc and parsed.hostname:
            return True
        name = ref.split("#", 1)[0]
        candidate = Path(name)
        if not name or candidate.is_absolute() or ".." in candidate.parts or parsed.scheme:
            continue
        resolved = (root / candidate).resolve()
        if resolved.is_relative_to(root.resolve()) and resolved.is_file():
            return True
    return False


def confirmations(text: str, expected: list[str], label: str, errors: list[str]) -> None:
    matches = list(CHECK.finditer(text))
    descriptions = [m[2] for m in matches]
    if sorted(descriptions) != sorted(expected):
        errors.append(f"{label}: missing, duplicate or altered completion checkboxes")
    if any(m[1].lower() != "x" for m in matches):
        errors.append(f"{label}: every completion checkbox must be checked")


def validate(body: str, title: str, changed_paths: list[str], policy: dict, root: Path = ROOT) -> dict:
    errors: list[str] = []
    records: list[dict] = []
    sections = split_sections(visible(body), HEADING)
    attempts = [(heading, text) for heading, text in sections if heading.startswith("Experiment:")]
    maintenance = [text for heading, text in sections if heading == policy["maintenance_heading"]]
    if maintenance:
        if len(maintenance) != 1 or attempts:
            errors.append("use either experiment records or one maintenance declaration, not both")
        text = maintenance[0]
        reason_text = CHECK.sub("", text)
        reason = fields(reason_text, ["Reason"], "Maintenance", errors).get("Reason", "")
        if not substantive(reason):
            errors.append("Maintenance: provide a substantive non-placeholder reason")
        confirmations(text, [policy["maintenance_check"]], "Maintenance", errors)
        if any(p.startswith(tuple(policy["formal_path_prefixes"])) for p in changed_paths):
            errors.append("changes to models or experiment reports require a formal attempt record")
    elif not attempts:
        errors.append("include at least one '## Experiment: ID' record or an explicit maintenance declaration")
    ids: set[str] = set()
    for heading, text in attempts:
        match = ATTEMPT.fullmatch(heading)
        if not match:
            errors.append("experiment IDs must be 1..64 ASCII letters/digits/dots/hyphens/underscores")
            continue
        ident = match[1]
        if ident.lower() in ids:
            errors.append(f"duplicate experiment ID: {ident!r}")
        ids.add(ident.lower())
        subsections = split_sections(text, SUBHEADING)
        expected = list(policy["sections"]) + [policy["checklist_heading"]]
        if [name for name, _ in subsections] != expected:
            errors.append(f"{ident}: require each prescribed section once, in template order")
        first = SUBHEADING.search(text)
        preamble = text[:first.start()] if first else text
        type_fields = fields(preamble, ["Type"], ident, errors)
        kind = type_fields.get("Type", "")
        if kind not in policy["experiment_types"]:
            errors.append(f"{ident}: Type must be results or performance")
        outcome = ""
        for name, section in subsections:
            if name == policy["checklist_heading"]:
                confirmations(section, policy["checks"], ident, errors)
            elif name in policy["sections"]:
                values = fields(section, policy["sections"][name], f"{ident}/{name}", errors)
                for key in policy["sections"][name]:
                    value = values.get(key, "")
                    if key == "Outcome":
                        outcome = value
                        if value not in policy["outcomes"]:
                            errors.append(f"{ident}: Outcome must be supported, not-supported or inconclusive")
                    elif key == "Evidence":
                        if PLACEHOLDER.search(re.sub(r"<(https://[^\s>]+)>", r"\1", value)) or not evidence_exists(value, root):
                            errors.append(f"{ident}: Evidence needs an existing repository file or HTTPS artifact")
                    elif not substantive(value):
                        errors.append(f"{ident}/{name}: fill {key} with substantive, non-placeholder text")
        records.append({"id": ident, "type": kind, "outcome": outcome})
    title_prefix = re.match(r"^([A-Za-z]+)(?:\([^\n)]*\))?!?:", title)
    hint = policy["title_type_hints"].get(title_prefix[1].lower()) if title_prefix else None
    if hint and hint not in {r["type"] for r in records}:
        errors.append(f"PR title declares {hint}; include a matching formal record")
    return {"passed": not errors, "errors": errors, "attempts": records,
            "classification": "maintenance" if maintenance else "experiment"}


def metadata(pr: dict, file_pages: list) -> tuple[str, str, list[str]]:
    if not isinstance(pr, dict) or not isinstance(pr.get("title"), str):
        raise ValueError("PR metadata must include a title")
    if not isinstance(pr.get("number"), int) or pr["number"] <= 0:
        raise ValueError("PR metadata must include its positive number")
    if not isinstance(pr.get("body"), (str, type(None))):
        raise ValueError("PR body must be text or null")
    if not re.fullmatch(r"[0-9a-f]{40}", pr.get("head", {}).get("sha", "")):
        raise ValueError("PR metadata must include its full head SHA")
    if not isinstance(file_pages, list):
        raise ValueError("changed files must be a JSON list")
    items = []
    for page in file_pages:
        if isinstance(page, list):
            items.extend(page)
        elif isinstance(page, dict):
            items.append(page)
        else:
            raise ValueError("invalid changed-file page")
    names, paths = [], []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            raise ValueError("invalid changed-file record")
        names.append(item["filename"])
        for key in ["filename", "previous_filename"]:
            if key in item:
                name = item[key]
                if not isinstance(name, str) or not name or any(c in name for c in "\r\n\x00"):
                    raise ValueError("invalid changed path")
                paths.append(name)
    count = pr.get("changed_files")
    if type(count) is not int or len(names) != count or len(set(names)) != count:
        raise ValueError("changed-file pagination/count mismatch; refusing a partial scope check")
    return pr["body"] or "", pr["title"], paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--files-json", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-head")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report: dict = {"schema": "filang-experiment-gate-v1", "passed": False}
    code = 2
    try:
        policy = load_policy(args.policy)
        pr = json.loads(args.pr_json.read_text(encoding="utf-8"))
        pages = json.loads(args.files_json.read_text(encoding="utf-8"))
        body, title, paths = metadata(pr, pages)
        if args.expected_head and pr["head"]["sha"] != args.expected_head:
            raise ValueError("PR head changed during this run; a current-head check is required")
        report.update(validate(body, title, paths, policy, args.root))
        report.update(pull_request=pr["number"], head_sha=pr["head"]["sha"],
                      body_sha256=digest(body.encode()), policy_sha256=digest(args.policy.read_bytes()),
                      gate_sha256=digest(Path(__file__).read_bytes()), changed_files=pr["changed_files"])
        code = 0 if report["passed"] else 1
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["errors"] = [f"gate setup failed: {error}"]
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
