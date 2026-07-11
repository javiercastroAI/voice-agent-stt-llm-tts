# Change: Explicit Terminal Consent and Adaptive STT Margin

## Goal

Prevent ambiguous caller language from closing a call, and reduce speaker-mode
cutoffs by holding paused audio for an STT recovery interval that adapts to
recent final-transcript delay.

## Scope

- Require deterministic explicit acceptance before emitting `outcome_confirmed`
  from a terminal-capable confirmation state.
- Fail closed when structured intent output proposes an unverified terminal
  confirmation.
- Use a bounded adaptive pause recovery interval based on observed STT delay.

## Acceptance Criteria

- Ambiguous acknowledgements such as “básicamente”, fragments, thanks, or
  farewells cannot end a call.
- A confirmed outcome remains possible with explicit acceptance language.
- The recovery hold starts at `1.50s`, learns from recent pending-STT delay,
  and remains capped at `2.50s`.

## Non-Goals

- Changing valid FSM terminal transitions.
- Treating arbitrary natural language as consent.
