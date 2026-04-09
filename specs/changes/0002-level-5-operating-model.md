# Change: Level 5 Operating Model

## Goal

Turn the repository into a reusable example of spec-native, agent-ready delivery.

## Scope

- Governance controls
- Shared contract generation
- Planner and review roles
- Human approval gates
- Executable worktree, workflow, and PR governance enforcement

## Acceptance Criteria

- The contract schema is canonical and generates a shared artifact.
- Governance controls define approval gates and required evidence.
- Planner and review roles are documented alongside delivery roles.
- Spec validation fails if generated artifacts drift from the schema.
- Worktree isolation is the default parallel execution mode.
- Pull requests carry a structured approval and residual-risk record.
