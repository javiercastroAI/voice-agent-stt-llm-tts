# Live FSM graph visualization

## Goal

Show the canonical conversational FSM as a live graph in the local dashboard,
with the active phase and most recently executed transition visibly highlighted.

## Scope

- Derive a serializable graph projection from the executable transition registry;
  do not duplicate topology in the dashboard.
- Add that immutable graph projection to the local dashboard state payload.
- Render phase nodes and declared business transitions in the FSM monitor.
- Highlight the current node from `fsm_state.phase` and the most recently
  matched transition from trace evidence.
- Preserve the existing state facts and chronological transition trail as the
  detailed evidence view.
- Make the graph responsive and distinguish inactive, active, guarded, and
  terminal paths without relying on color alone.

## Acceptance Criteria

- The dashboard state exposes `fsm_graph`, `fsm_state`, and
  `fsm_transitions` together.
- Every rendered node and business edge is derived from the canonical FSM
  registry.
- A live transition highlights its source and target nodes and its exact
  transition identifier when available.
- Before the first live transition, the graph still renders the complete
  canonical topology with an awaiting-state indicator.
- Existing dashboard state, assessment, transition evidence, polling, and FSM
  behavior remain intact.
- Focused web and FSM tests, the full regression suite, and spec validation
  pass.

## Non-goals

- Changing the business FSM, transition order, guards, or call behavior.
- Adding graph editing, filtering, or new call controls.
- Persisting dashboard state after the local console session ends.
