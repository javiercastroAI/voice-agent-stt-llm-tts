## Summary

- What changed:
- Why:

## Agent Scope

- [ ] Planner (`specs/`)
- [ ] Backend (`voice_agent/`, `backend/`)
- [ ] Tests (`tests/`)
- [ ] Review (`docs/`, `.github/`)

## Contract Impact

- [ ] No shared contract or interface changes
- [ ] Contract changed and I updated the affected implementation and tests in the same PR

## Spec Impact

- [ ] No behavior/spec changes
- [ ] I updated `specs/changes/` and any affected machine-readable specs
- [ ] I regenerated the shared contract artifact after contract changes

## Validation

- [ ] `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`
- [ ] `python3 -m compileall voice_agent backend shared tests`
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'`

## Human Approval

- Required approvals: _none_
- Approval record: _none_
- [ ] Architecture reviewed by a human
- [ ] Schema/protocol reviewed by a human
- [ ] Security impact reviewed by a human
- [ ] Release decision reviewed by a human

## Risk Notes

- Residual risk: _none_
- Known limitations or skipped checks:
