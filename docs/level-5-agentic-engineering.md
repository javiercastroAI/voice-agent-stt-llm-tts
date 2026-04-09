# Level 5 Agentic Engineering

This scaffold treats Level 5 as an executable operating model, not as marketing language.

## Level 5 Means

1. Specs change before code for behavior, protocol, UI, and governance.
2. Contracts are canonical and generate shared runtime artifacts.
3. Backend, UI, and tests coordinate around the same shared contract layer.
4. Parallel work is isolated by worktree and domain by default, with explicit overrides only.
5. CI, security checks, PR governance checks, and static analysis create an audit trail.
6. Human approval is required for architecture, schema, security, and release decisions.

## Canonical Flow

1. Update `specs/changes/` and any affected machine-readable specs.
2. Regenerate shared contract artifacts from `contracts/`.
3. Implement code changes against the generated contract layer.
4. Run `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`, `python3 -m compileall voice_agent backend shared tests`, and `python3 -m unittest discover -s tests -p 'test_*.py'`.
5. Record approval and residual-risk notes in the PR template.
