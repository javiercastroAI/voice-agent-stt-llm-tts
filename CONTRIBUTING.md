# Contributing

## Scope Model

This repository uses delivery roles plus governance roles. Follow each spec in `agents/*.md` and keep ownership boundaries clear.

## Spec-First Rule

If behavior, protocol, UI, or governance changes, update the relevant files under `specs/` before or alongside code.

## Worktree Isolation Rule

Parallel delivery work runs from git worktrees by default. `./scripts/run-agents.sh` is worktree-first; root execution requires the explicit `--root` override.

## Generated Contract Rule

If `contracts/interface.schema.json` changes, run `python3 scripts/generate-contract-artifacts.py` and commit the resulting shared artifacts.

## Human Approval Rule

The PR must explicitly note human approval for:
- architecture changes
- schema/protocol changes
- security changes
- release decisions

The PR must also record:
- required approval categories or `_none_`
- the approval record for governed changes
- residual risk after the change

## Pull Request Checklist

- [ ] I followed ownership boundaries from `agents/*.md`.
- [ ] I updated `specs/changes/` and any affected machine-readable specs.
- [ ] I regenerated shared contract artifacts after any contract change.
- [ ] I assessed whether contracts or shared behavior changed.
- [ ] If shared behavior changed, I updated implementation plans, specs, and tests together.
- [ ] I ran `python3 scripts/generate-contract-artifacts.py --check && python3 scripts/validate-specs.py && ./scripts/check-scaffold.sh`.
- [ ] I ran the repo build command: `python3 -m compileall voice_agent backend shared tests`.
- [ ] I ran the repo test command: `python3 -m unittest discover -s tests -p 'test_*.py'`.
- [ ] I documented required human approvals and residual risk.
