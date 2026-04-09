# Security Policy

## Scope

This scaffold is a starting point for an executable Level-5 operating model. It is not automatically production-ready.

## Baseline Controls

- Use least-privilege access for tools, repos, and environments.
- Keep secrets out of prompts, specs, and committed files.
- Require human approval for architecture, schema, security, and release decisions.
- Regenerate shared contract artifacts whenever the canonical schema changes.
- Enforce scaffold, governance, and spec validation in CI.
- Run dependency review and static analysis in GitHub Actions.
- Require a structured PR governance record for risky changes.
