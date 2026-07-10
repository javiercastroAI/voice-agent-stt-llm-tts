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
    '[legal]',
    'license = "MIT"',
    'license_file = "LICENSE"',
    '[agents]',
    'governance = ["planner", "review"]',
    '[policies]',
    'require_generated_contract_sync = true',
    'require_license_file = true',
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

conversation_fsm = read_json("specs/system/conversation-fsm.json")
if isinstance(conversation_fsm, dict):
    if conversation_fsm.get("version") != 1:
        fail("specs/system/conversation-fsm.json: version must be 1")
    if conversation_fsm.get("orchestrator") != "langgraph-stategraph":
        fail("specs/system/conversation-fsm.json: orchestrator must be langgraph-stategraph")
    phases = conversation_fsm.get("phases")
    if not isinstance(phases, list) or "identity_verification" not in phases or "ended" not in phases:
        fail("specs/system/conversation-fsm.json: required phases are missing")

case_context_schema = read_json("specs/system/case-context.schema.json")
if isinstance(case_context_schema, dict):
    if case_context_schema.get("type") != "object":
        fail("specs/system/case-context.schema.json: top-level type must be object")
    if case_context_schema.get("additionalProperties") is not False:
        fail("specs/system/case-context.schema.json: additional properties must be forbidden")
    required_case_fields = case_context_schema.get("required", [])
    for field in ["case_id", "creditor_name", "customer_name", "disclosure_summary"]:
        if field not in required_case_fields:
            fail(f"specs/system/case-context.schema.json: required must include {field}")

fsm_trace_schema = read_json("specs/system/fsm-trace.schema.json")
if isinstance(fsm_trace_schema, dict):
    if fsm_trace_schema.get("type") != "object":
        fail("specs/system/fsm-trace.schema.json: top-level type must be object")
    if fsm_trace_schema.get("additionalProperties") is not False:
        fail("specs/system/fsm-trace.schema.json: additional properties must be forbidden")
    trace_types = fsm_trace_schema.get("properties", {}).get("type", {}).get("enum", [])
    for event_type in ["fsm_transition", "assistant_response"]:
        if event_type not in trace_types:
            fail(f"specs/system/fsm-trace.schema.json: type enum must include {event_type}")

fsm_scenarios = read_json("specs/scenarios/fsm-adherence.json")
if isinstance(fsm_scenarios, dict):
    if fsm_scenarios.get("version") != 1:
        fail("specs/scenarios/fsm-adherence.json: version must be 1")
    if not fsm_scenarios.get("scenarios"):
        fail("specs/scenarios/fsm-adherence.json: scenarios must not be empty")
    if not fsm_scenarios.get("requiredPhaseCoverage"):
        fail("specs/scenarios/fsm-adherence.json: phase coverage must be declared")
    if not fsm_scenarios.get("requiredGlobalGuardCoverage"):
        fail("specs/scenarios/fsm-adherence.json: guard coverage must be declared")

audio_scenarios = read_json("specs/scenarios/fsm-audio-adherence.json")
if isinstance(audio_scenarios, dict):
    if audio_scenarios.get("version") != 1:
        fail("specs/scenarios/fsm-audio-adherence.json: version must be 1")
    if not audio_scenarios.get("scenarios"):
        fail("specs/scenarios/fsm-audio-adherence.json: scenarios must not be empty")

governance = read_json("specs/governance/controls.json")
if isinstance(governance, dict):
    if governance.get("version") != 2:
        fail("specs/governance/controls.json: version must be 2")
    if governance.get("maturityTarget") != "level-5":
        fail("specs/governance/controls.json: maturityTarget must be level-5")
    if governance.get("repositoryLicense", {}).get("spdx") != "MIT":
        fail("specs/governance/controls.json: repositoryLicense.spdx must be MIT")
    if governance.get("repositoryLicense", {}).get("file") != "LICENSE":
        fail("specs/governance/controls.json: repositoryLicense.file must be LICENSE")
    if governance.get("parallelExecution", {}).get("defaultMode") != "worktrees":
        fail("specs/governance/controls.json: parallelExecution.defaultMode must be worktrees")
    if governance.get("auditTrail", {}).get("placeholderOwnersForbidden") is not True:
        fail("specs/governance/controls.json: auditTrail.placeholderOwnersForbidden must be true")

pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
if 'license = {file = "LICENSE"}' not in pyproject:
    fail('pyproject.toml: project license must point to "LICENSE"')

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
if "python3 scripts/evaluate-fsm-adherence.py --scenario-only" not in ci:
    fail(".github/workflows/ci.yml: deterministic FSM adherence replay must be enabled")

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

for change_path in sorted((root / "specs" / "changes").glob("*.md")):
    content = change_path.read_text(encoding="utf-8")
    for section in ["## Goal", "## Scope", "## Acceptance Criteria"]:
        if section not in content:
            fail(f"{change_path.relative_to(root)}: missing section {section}")

if errors:
    print("Spec validation failed:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("Spec validation passed.")
