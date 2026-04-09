#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
errors: list[str] = []

def fail(message: str) -> None:
    errors.append(message)

def read_json(relative_path: str):
    try:
        return json.loads((root / relative_path).read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{relative_path}: invalid JSON ({exc})")
        return None

repo_toml = (root / "agentic-repo.toml").read_text(encoding="utf-8")
for fragment in [
    '[repo]',
    'maturity_target = "level-5"',
    '[ownership]',
    'default_codeowners = [',
    '[agents]',
    'governance = ["planner", "review"]',
    '[policies]',
    'require_generated_contract_sync = true',
    '[parallelism]',
    'default_execution = "worktrees"',
    'root_override_flag = "--root"',
    'run_script = "./scripts/run-agents.sh"',
]:
    if fragment not in repo_toml:
        fail(f"agentic-repo.toml: missing {fragment}")

rules = read_json("specs/system/rules.json")
if isinstance(rules, dict):
    if rules.get("version") != 1:
        fail("specs/system/rules.json: version must be 1")
    if not isinstance(rules.get("invariants"), list) or not rules["invariants"]:
        fail("specs/system/rules.json: invariants must be a non-empty array")

governance = read_json("specs/governance/controls.json")
if isinstance(governance, dict):
    if governance.get("version") != 2:
        fail("specs/governance/controls.json: version must be 2")
    if governance.get("maturityTarget") != "level-5":
        fail("specs/governance/controls.json: maturityTarget must be level-5")
    if governance.get("parallelExecution", {}).get("defaultMode") != "worktrees":
        fail("specs/governance/controls.json: parallelExecution.defaultMode must be worktrees")
    if governance.get("auditTrail", {}).get("placeholderOwnersForbidden") is not True:
        fail("specs/governance/controls.json: auditTrail.placeholderOwnersForbidden must be true")

contract = read_json("contracts/interface.schema.json")
if isinstance(contract, dict):
    required = contract.get("required", [])
    if contract.get("type") != "object":
        fail("contracts/interface.schema.json: top-level type must be object")
    if not isinstance(required, list) or "type" not in required or "payload" not in required:
        fail("contracts/interface.schema.json: required must include type and payload")

examples = read_json("specs/api/examples.json")
if isinstance(examples, dict) and (not isinstance(examples.get("validExamples"), list) or not examples["validExamples"]):
    fail("specs/api/examples.json: validExamples must be a non-empty array")

ui_contract_path = root / "specs" / "ui" / "contract.json"
if ui_contract_path.exists():
    ui_contract = read_json("specs/ui/contract.json")
    if isinstance(ui_contract, dict) and not isinstance(ui_contract.get("requiredElementIds"), list):
        fail("specs/ui/contract.json: requiredElementIds must be an array")

codeowners = (root / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
if "@your-gh-handle" in codeowners or "Replace " in codeowners:
    fail(".github/CODEOWNERS: placeholder owners must be replaced")
if "* @" not in codeowners:
    fail(".github/CODEOWNERS: a global owner rule is required")

pr_template = (root / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
for section in ["Summary", "Agent Scope", "Contract Impact", "Spec Impact", "Validation", "Human Approval", "Risk Notes"]:
    if f"## {section}" not in pr_template:
        fail(f".github/pull_request_template.md: missing section {section}")
for prompt in ["What changed", "Why", "Required approvals", "Approval record", "Residual risk"]:
    if f"- {prompt}:" not in pr_template:
        fail(f".github/pull_request_template.md: missing prompt {prompt}")
if f"- [ ] `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`" not in pr_template:
    fail(".github/pull_request_template.md: validation checklist must include the scaffold/spec check command")

ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
if "python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh" not in ci:
    fail(".github/workflows/ci.yml: missing scaffold/spec check command")
if True and "Install dependencies" not in ci:
    fail(".github/workflows/ci.yml: dependency installation must be explicit")

security_workflow = (root / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
if "actions/dependency-review-action@v4" not in security_workflow:
    fail(".github/workflows/security.yml: dependency review must be enabled")
if "pip-audit:" not in security_workflow:
    fail(".github/workflows/security.yml: pip-audit job must be enabled")

codeql_workflow = (root / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
if "github/codeql-action/init@v3" not in codeql_workflow:
    fail(".github/workflows/codeql.yml: CodeQL must be enabled")

governance_workflow = (root / ".github" / "workflows" / "governance.yml").read_text(encoding="utf-8")
if "python3 scripts/check-pr-governance.py" not in governance_workflow:
    fail(".github/workflows/governance.yml: PR governance validation must be enabled")

run_agents = (root / "scripts" / "run-agents.sh").read_text(encoding="utf-8")
if 'RUN_MODE="worktrees"' not in run_agents or "--root" not in run_agents:
    fail("scripts/run-agents.sh: worktree-first execution must be enforced")

setup_worktrees = (root / "scripts" / "setup-worktrees.sh").read_text(encoding="utf-8")
if "default_base_branch()" not in setup_worktrees or "BASE_BRANCH" not in setup_worktrees:
    fail("scripts/setup-worktrees.sh: base branch must be derived dynamically")

for change_spec in ["specs/changes/0001-baseline-scope.md", "specs/changes/0002-level-5-operating-model.md"]:
    content = (root / change_spec).read_text(encoding="utf-8")
    for section in ["## Goal", "## Scope", "## Acceptance Criteria"]:
        if section not in content:
            fail(f"{change_spec}: missing section {section}")

if errors:
    print("Spec validation failed:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("Spec validation passed.")
