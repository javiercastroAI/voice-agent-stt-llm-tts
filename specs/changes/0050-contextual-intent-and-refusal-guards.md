# Change: Contextual Intent and Refusal Guards

## Goal

Prevent repetitive persuasion and premature identity disclosure by making the
generic FSM enforce verification-field completion, contextual acknowledgements,
and repeated payment refusals deterministically.

## Scope

- Track which configured identity-verification fields have been confirmed.
- Keep the identity gate closed until every configured field is confirmed.
- Interpret concise agreement in objection handling as acceptance of `case_review`
  when that resolution is available.
- Detect explicit payment refusal phrases before probabilistic interpretation and
  count them toward the existing refusal limit.
- Normalize common Spanish STT distortions of "no voy a pagar" conservatively.
- Treat concise case rejection such as "no puede ser" as a deterministic dispute.
- Allow `case_review` to be selected directly from objection handling.
- Define case review as a request being recorded, never a simulated completed review.
- Detect continued persuasion after repeated refusal evidence in runtime traces.

## Human Approval

The user reviewed a live call on 2026-07-10 and explicitly approved the proposed
improvements after the agent repeatedly pushed case review despite clear refusals.

## Acceptance Criteria

- "Sí, soy yo" alone cannot unlock case disclosure when name and role are required.
- Confirmed verification fields accumulate across turns and unlock disclosure only
  when the configured set is complete.
- "Pero no puede ser" routes to dispute handling without an interpreter fallback.
- A contextual "sí" or "revísalo" in objection handling can select `case_review`.
- Two explicit payment refusals end the call through `refusal_limit_reached`.
- Case-review responses confirm that the request is recorded and do not claim a
  system review is running or complete.
- Runtime adherence fails when repeated payment refusals are followed by continued
  non-terminal persuasion.
- Specs, scenarios, focused tests, the full suite, and scaffold checks pass.

## Non-Goals

- Performing an actual account or service review.
- Replacing STT with a different provider.
- Encoding creditor-specific business logic in the FSM.
