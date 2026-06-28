# Change: Consultation Return And Retention

## Goal

Prevent the assistant from going quiet or losing the customer when it says it
will review something during the collections call.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for simulated consultation and retention behavior.

## Acceptance Criteria

- If the assistant says it will consult or review, it must simulate the check
  and return in the same turn.
- The prompt includes the pattern `Lo reviso un momento... ya lo tengo.`
- After a simulated check, the assistant must give a result, a clear limitation,
  or the next concrete step.
- The assistant must not leave silence, a vague promise, or an unresolved
  handoff after saying it will review.
- When the customer shows doubt, anger, or tries to end the call, the assistant
  offers one useful reason to continue and a simple choice.
- Retention must remain non-coercive: after two rejections or an explicit
  request to finish, the assistant closes respectfully.

## Rationale

Live testing showed the assistant could say it was going to review the case and
then fail to return with a useful result. This change makes the "consultation"
behavior a voice-friendly simulation and gives the agent a clear retention move
without ignoring explicit customer refusal.
