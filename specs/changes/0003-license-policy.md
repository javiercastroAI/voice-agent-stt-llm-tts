# Change: Repository License Policy

## Goal

Make the repository license explicit and enforce it as part of the scaffold's
governance contract.

## Scope

- Root `LICENSE` document
- Package metadata in `pyproject.toml`
- Canonical governance policy in `agentic-repo.toml`
- Machine-readable governance controls
- Scaffold validation rules

## Acceptance Criteria

- The repository root contains an MIT `LICENSE` file.
- Packaging metadata points to the root `LICENSE` file.
- Canonical policy sources declare the repository license as MIT.
- Scaffold validation fails when the root `LICENSE` file is missing.

## Non-Goals

- Dual licensing
- Contributor license agreements
- Commercial support or warranty terms
