# Change: Smooth Effective Collections Prompt

## Goal

Make the outbound collections prompt smoother and more effective for live voice
testing by giving the assistant a concrete conversational path and removing
empty call-center filler.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for the revised customer-experience constraints.

## Acceptance Criteria

- The prompt explicitly states MacroHard is the calling company and Al Corriente
  S.L. is the company being called.
- The prompt provides a recommended outbound opening.
- The assistant must not ask empty questions such as whether it can help the
  customer when the assistant initiated the call.
- The assistant must use every turn to verify, explain, clarify, resolve, or
  close.
- Before verification, the assistant must avoid revealing debt, CloudX,
  amount, product, or dates.
- After verification, the assistant has a sample direct explanation that names
  CloudX and the 1.527 euro amount.
- The assistant handles recognition, dispute, cancellation, and missing-detail
  paths inside the current call.
- The assistant can use one or two short sentences when needed and must not
  leave spoken phrases unfinished.
- Scheduling and manager handoff remain last-resort paths.

## Rationale

Live testing showed the assistant still sounded reactive and generic, including
asking how it could help after placing the call. This prompt revision gives it a
clean outbound flow, example utterances, and clearer recovery paths for common
customer objections.
