# Change: Diplomatic Payment Issue Opening

## Goal

Make the opening clearer and more customer-friendly by diplomatically stating
that the call concerns a payment issue without disclosing sensitive case details
before verification.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for opening language.

## Acceptance Criteria

- The recommended opening says MacroHard is calling about an administrative
  issue with a payment for Al Corriente S.L.
- Before identity verification, the assistant may say there is an
  administrative payment issue.
- Before identity verification, the assistant must still avoid debt labels,
  CloudX, amount, product, and dates.
- If asked for the reason before verification, the assistant uses the same
  diplomatic payment-issue framing and explains the privacy need.
- The rest of the in-call resolution, consultation-return, and non-coercive
  retention behavior remains unchanged.

## Rationale

Live testing showed that a generic "administrative account matter" was too vague
and made the customer ask what the call was about. A diplomatic payment-issue
opening is clearer while still protecting sensitive details until verification.
