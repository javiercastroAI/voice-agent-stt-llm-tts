# Change: Repeated-Concept Terminal Guard

## Goal

Turn repeated conversational loops into a deterministic terminal FSM outcome
instead of merely reporting them as an end-of-call quality failure.

## Scope

- Define a conversational concept as the current FSM phase plus its response
  directive.
- Count consecutive user turns that leave that concept unchanged.
- End the call on the third unresolved repetition, with the registered
  `repetition_limit` transition, `repetition_limit_reached` guard reason, and
  `close_after_repetition_limit` directive.
- Preserve the counter and concept in runtime state and durable trace evidence.
- Treat this directive as a terminal closing directive for spoken-response
  compliance and provide a short deterministic farewell.
- Align retrospective stalled-loop detection with the same three-turn limit.

## Human Approval

The user requested this terminal rule on 2026-07-11 after reviewing an
unsatisfactory completed call whose FSM adherence passed but whose conversation
quality failed because it repeated the same phase and directive.

## Acceptance Criteria

- Three consecutive user turns with the same unresolved phase/directive concept
  end the call on the third turn.
- A phase change resets the repetition counter.
- The terminal transition is present in `TRANSITION_REGISTRY`, the generated
  business graph, transition history, and durable evidence.
- The final farewell asks no question and does not continue persuasion.
- Replaying an externally supplied three-turn stalled loop produces the
  deterministic conversational-quality finding.

## Non-Goals

- Semantic similarity scoring of arbitrary natural-language utterances.
- Altering the configured refusal limit or identity-verification requirements.
- Rewriting prior call traces or reassessing an already-completed call as if
  this future runtime guard had been active.
