# Repository Agents

> Pre-production operating model. Replace placeholders before claiming delivery readiness.

This repository uses two delivery agents plus two governance agents.

## 1) Backend Agent
- Scope: `voice_agent/`, `backend/`, `contracts/`, `shared/`
- Goal: implement and maintain service logic, workflows, and external contracts.
- Start command: `python3 -m backend.app`
- Spec: `agents/backend-agent.md`

## 2) Test Agent
- Scope: `tests/`
- Goal: maintain deterministic regression, contract, and end-to-end validation.
- Start command: `python3 -m unittest discover -s tests -p 'test_*.py'`
- Spec: `agents/test-agent.md`

## 3) Planner Agent
- Scope: `specs/`
- Goal: convert requests into spec deltas before implementation starts.
- Start command: `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`
- Spec: `agents/planner-agent.md`

## 4) Review Agent
- Scope: `.github/`, `docs/`, governance policy
- Goal: verify traceability, approvals, and validation evidence.
- Start command: `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`
- Spec: `agents/review-agent.md`

## Spec-First Rule
- Behavior, protocol, UI, and governance changes start in `specs/` before code changes are finalized.
- If `contracts/` changes, regenerate shared runtime artifacts before changing backend, UI, or tests.
- Canonical repo policy lives in `agentic-repo.toml` and `specs/governance/controls.json`; prose docs must agree with those files.

## Coordination Rule
- Changes that alter interfaces, payloads, shared behavior, or governance must update implementation plans, specs, and tests in the same change set.
- Architecture, schema, security, and release changes require explicit human approval notes in the PR.
- Parallel delivery work runs from isolated git worktrees by default; root execution is an explicit override.
