# Change: Immediate System-check Response

## Goal

Prevent the speaking agent from simulating an asynchronous system check or
leaving the caller waiting when no real lookup tool is being executed.

## Scope

- Add a mandatory runtime rule to every FSM-controlled response.
- For Spanish calls, when a conversational check is useful, say briefly
  `Estoy comprobando el sistema. Ah, de acuerdo.` and immediately continue with
  the available result, limitation, or next step in the same response.
- Never ask the caller to wait or claim that a background review is in progress
  unless an actual lookup tool has been called.
- Keep the rule locale-aware and case-agnostic.

## Human Approval

The user explicitly requested immediate system-check acknowledgements on
2026-07-10.

## Acceptance Criteria

- Spanish runtime control contains the requested brief acknowledgement.
- Runtime control forbids artificial pauses and simulated background checks.
- English and other locales receive an equivalent locale-neutral instruction.
- Existing FSM directives remain authoritative.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Pretending that a real external lookup occurred.
- Adding a payment, CRM, or case-management connector.
