# Change: Coalesced Turn Response Evidence

## Goal

Model STT-split user utterances correctly so multiple FSM transitions produced
before one assistant reply do not create permanently missing response evidence.

## Scope

- Emit a `turn_superseded` trace event when a new FSM transition arrives before
  an older pending transition receives an assistant response.
- Treat superseded transitions as coalesced context, not missing responses.
- Correlate the next response only to the latest active transition.
- Exclude coalesced transitions from the response-coverage denominator while
  retaining them in FSM transition history and evaluated-turn counts.
- Show coalesced-turn count alongside response coverage on the dashboard.

## Human Approval

The user explicitly requested a definitive solution after repeated terminal
assessments remained pending. The latest durable trace contained ten transitions
and eight responses because STT split natural answers into multiple turns before
the agent produced a single reply.

## Acceptance Criteria

- A new transition supersedes every older unreplied transition deterministically.
- Superseded transitions remain auditable and are not assigned fabricated text.
- The next assistant response correlates to the latest transition.
- Missing-response failures apply only to non-superseded transitions.
- Terminal speech evidence reaches the terminal transition without queue drift.
- Dashboard coverage reports recorded/required plus coalesced count.
- Full regression, adherence, schema, spec, and scaffold checks pass.

## Non-Goals

- Dropping FSM transitions caused by split STT input.
- Inventing assistant responses for silent intermediate turns.
- Hiding genuine missing responses when no later turn superseded them.
