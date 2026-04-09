#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys

errors: list[str] = []
pr_body = os.environ.get("PR_BODY", "")
changed_files = [line.strip() for line in os.environ.get("CHANGED_FILES", "").splitlines() if line.strip()]

required_sections = [
    "Summary",
    "Agent Scope",
    "Contract Impact",
    "Spec Impact",
    "Validation",
    "Human Approval",
    "Risk Notes",
]
required_prompts = [
    "What changed",
    "Why",
    "Required approvals",
    "Approval record",
    "Residual risk",
]

def fail(message: str) -> None:
    errors.append(message)

def extract_prompt_value(label: str) -> str:
    pattern = re.compile(rf"^- {re.escape(label)}:\s*(.*)$", re.MULTILINE)
    match = pattern.search(pr_body)
    return match.group(1).strip() if match else ""

def requires_approvals(files: list[str]) -> dict[str, bool]:
    return {
        "architecture": any(
            re.search(
                r"^(agentic-repo\.toml|specs/governance/|scripts/(check-scaffold\.sh|run-agents\.sh|setup-worktrees\.sh|validate-specs\.(mjs|py))|agents/(planner-agent|review-agent)\.md|\.github/(CODEOWNERS|pull_request_template\.md|workflows/governance\.yml))",
                file,
            )
            for file in files
        ),
        "schema": any(re.search(r"^(contracts/|shared/|specs/api/)", file) for file in files),
        "security": any(re.search(r"^(SECURITY\.md|\.github/workflows/(security|codeql)\.yml)", file) for file in files),
        "release": any(re.search(r"^(docs/release|\.github/workflows/release)", file) for file in files),
    }

if not pr_body.strip():
    fail("PR body is empty. The governance template must be completed.")

for section in required_sections:
    if f"## {section}" not in pr_body:
        fail(f"PR body is missing required section: {section}")

for prompt in required_prompts:
    if not extract_prompt_value(prompt):
        fail(f"PR body is missing required prompt value: {prompt}")

required_approvals = [label for label, needed in requires_approvals(changed_files).items() if needed]
required_approvals_value = extract_prompt_value("Required approvals")
approval_record_value = extract_prompt_value("Approval record")

if not required_approvals:
    if not re.fullmatch(r"_?none_?", required_approvals_value, re.IGNORECASE):
        fail("Required approvals must be `_none_` when no governed approval category is triggered.")
else:
    for label in required_approvals:
        if not re.search(rf"\b{re.escape(label)}\b", required_approvals_value, re.IGNORECASE):
            fail(f"Required approvals must list `{label}` for this PR.")
    if re.fullmatch(r"_?(none|n/a|tbd)_?", approval_record_value, re.IGNORECASE):
        fail("Approval record must name the reviewer or approval source for governed changes.")

if errors:
    print("PR governance validation failed:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PR governance validation passed.")
