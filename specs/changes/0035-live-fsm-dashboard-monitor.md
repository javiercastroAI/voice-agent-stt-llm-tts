# Change: Live FSM Dashboard Monitor

## Goal

Make the external FSM observable during local voice calls without requiring an
operator to read JSONL evidence or run a CLI evaluator.

## Scope

- Stream the existing minimized FSM trace events into the console web store.
- Show the current phase, latest interpreted intent, active response directive,
  guard reason, identity status, refusal count, selected resolution, and
  terminal status.
- Show a chronological, bounded transition trail with response-evidence status.
- Keep JSONL recording optional while enabling the live console monitor whenever
  the local dashboard is running.
- Use the existing `/api/state` polling channel; add no new service dependency.
- Preserve the current transcript, models, technology, barge-in, and metric UI.

## Human Approval

The user explicitly requested a live FSM monitor in the dashboard on
2026-07-10.

## Acceptance Criteria

- The transcript store accepts minimized `fsm_transition` and
  `assistant_response` events safely under its existing lock.
- `/api/state` exposes `fsm_state` and a maximum of 100 `fsm_transitions`.
- A matching assistant response marks its transition as having response
  evidence without creating another transition row.
- The dashboard renders the active phase as the dominant FSM value.
- Guarded and terminal states have distinct, accessible visual treatment.
- New transitions animate once and the transition trail remains readable on
  desktop and mobile.
- Console monitoring works when `FSM_TRACE_PATH` is unset.
- Existing JSONL adherence evidence continues to work when configured.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Editing FSM state from the browser.
- Displaying sensitive case payloads or internal metadata.
- Replacing deterministic offline adherence evaluation.
