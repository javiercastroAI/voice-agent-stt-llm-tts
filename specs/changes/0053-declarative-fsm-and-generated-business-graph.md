# Declarative FSM and generated business graph

## Goal

Make the executable FSM transition table a first-class, typed source of truth and
derive the stakeholder-facing business graph from that same registry.

## Scope

- Declare global and phase transitions as immutable typed records.
- Select transitions deterministically by ordered priority, source phase, intent,
  and named guard.
- Keep complex guards and state mutations in typed Python callables referenced by
  the declarations.
- Preserve all existing phases, directives, guards, invariants, and terminal
  behaviour.
- Generate a Mermaid business graph from the executable registry.
- Record the matched transition identifier in runtime state, transition history,
  and durable FSM trace evidence.
- Commit the generated graph and provide a check mode that fails on drift.
- Validate unique transition identifiers, one fallback per phase, valid targets,
  and complete phase coverage.
- Test that the runtime registry, machine specification, and generated graph agree.

## Non-goals

- Moving executable guard expressions into JSON.
- Adding production identity-provider integration.
- Replacing the speaking LLM with response templates.
- Changing the current business journey or call behaviour.

## Acceptance Criteria

- The existing FSM, controller, adherence, dashboard, and agent tests pass.
- Every phase has a declarative fallback.
- The graph generator is deterministic and passes in check mode.
- The generated graph contains all declared phase-changing business transitions
  and global terminal/escalation guards.
