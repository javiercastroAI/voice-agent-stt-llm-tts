# Specs

This directory stores the source-of-truth artifacts for behavior, interfaces, UI expectations, and governance.

## Layout

- `changes/`: human-readable change briefs
- `system/`: machine-readable rules and invariants
- `api/`: interface or protocol examples
- `ui/`: UI contract artifacts
- `governance/`: approval and evidence controls

## Canonical Policy

The machine-readable policy sources in this repo are:

- `agentic-repo.toml`
- `specs/governance/controls.json`

Run `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh` to validate both the scaffold and the spec/governance contract.
