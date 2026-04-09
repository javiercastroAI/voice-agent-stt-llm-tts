# Spec-Driven Workflow

This repository treats `specs/` as the starting point for behavior, interface, UI, and governance changes.

## What Changes First

1. Add or update a change brief in `specs/changes/`.
2. Update the machine-readable specs that match the change.
3. If `contracts/` changed, run `python3 scripts/generate-contract-artifacts.py`.
4. Implement code changes against the generated contract layer.
5. Run `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh` before broader project checks.

## Why This Helps

- Teams review intent before implementation details.
- Contracts and tests can evolve from shared generated artifacts.
- Governance drift becomes visible earlier.
- Parallel agent work is safer because it is isolated and contract-aware.
- Pull-request evidence becomes executable instead of purely template-driven.
