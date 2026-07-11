# Change: Qualified Turn Gating and Playout Margin

## Goal

Prevent fragmented or echoed STT from superseding an agent response or advancing
the FSM unless it passed the same qualification decision used for barge-in.
Make the recovery margin and resumed-audio overlap measurable.

## Scope

- Hold a soft-paused response for a bounded STT recovery interval before audio
  can resume.
- Share accepted and rejected barge-in decisions with the FSM turn hook.
- Record recovery and resumed-audio overlap in barge-in telemetry.

## Acceptance Criteria

- A rejected candidate cannot create an FSM transition, supersede a pending
  response, or close the call.
- The response stays paused for up to `1.35s` after speech end while final STT
  is expected; it resumes deterministically if no decision arrives.
- Overtalk records audio played after a recovery resume, rather than reporting
  a false zero from the original pause timestamp.

## Non-Goals

- Changing the FSM's business transitions.
- Removing caller-initiated interruptions that have qualified speech evidence.
