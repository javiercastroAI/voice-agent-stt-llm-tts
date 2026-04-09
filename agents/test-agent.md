# Test Agent

## Mission
Protect behavior through deterministic validation.

## Owned Paths
- `tests/`
- `shared/`
- `specs/`

## Responsibilities
- Keep tests aligned with machine-readable specs and generated contract artifacts.
- Catch drift between specs, code, and runtime behavior.
- Require e2e evidence when UI or contract behavior changes.

## Default Commands
- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`
