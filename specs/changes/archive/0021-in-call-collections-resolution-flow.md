# Change: In-Call Collections Resolution Flow

## Goal

Keep the collections agent managing the case in the current call instead of
quickly sending the customer to another appointment or a manager.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for in-call resolution behavior.

## Acceptance Criteria

- After identity verification, the prompt tells the assistant to manage the case
  in the current call.
- The assistant explains the charge, amount, and company using the available
  case data.
- If the customer recognizes the charge, the assistant offers immediate next
  steps: payment, a concrete payment date, or a regularization plan.
- If the customer disputes the charge, the assistant asks why, summarizes the
  objection, and offers to review the issue in the same call.
- The assistant must not offer another call or manager handoff as the first
  resolution path.
- Scheduling or handoff is allowed only if the customer asks, refuses to
  continue, shows vulnerability, or the assistant cannot resolve after trying to
  clarify the case.
- Privacy and non-coercive collections guardrails remain unchanged.

## Rationale

Live testing showed the prompt allowed the assistant to escape too early into
appointment-setting or manager handoff. For this demo, the assistant should use
the concrete MacroHard / Al Corriente S.L. / CloudX case data and drive the
collections flow itself.
