# Change: Static FSM Monitor and Warm Farewell

## Goal

Keep the live FSM inspector visually stable between real state changes and make
successful-call farewells sound warm, natural, and outcome-aware rather than
abrupt.

## Scope

- Stop rebuilding FSM monitor markup on every 350 ms dashboard poll.
- Re-render the inspector only when `fsm_state` or `fsm_transitions` changes.
- Remove phase-pulse and transition-entry animations from the FSM inspector.
- Keep transcript live-state animation unchanged.
- Ask the terminal tool response to confirm the agreed outcome once, thank the
  caller, and wish them well in two short natural sentences.
- Forbid new questions, invented details, and repeated negotiation at farewell.

## Human Approval

The user explicitly requested a static FSM panel and warmer farewell on
2026-07-10.

## Acceptance Criteria

- Identical FSM snapshots do not mutate the inspector DOM.
- The inspector has no pulse, slide, or transition-entry animation.
- Real phase and response-evidence changes still render within the next poll.
- Terminal farewell instructions confirm the agreed outcome once and include a
  courteous thank-you without asking another question.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Freezing the transcript, agent-state, or user-state indicators.
- Extending the call after the terminal farewell.
