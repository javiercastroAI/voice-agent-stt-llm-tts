# Change: Immediate Payment Destination Guard

## Goal

Prevent the outbound agent from asking the caller which creditor account to pay
or from inventing destination banking details during immediate-payment flows.

## Scope

- Add a mandatory runtime payment-destination rule for every case.
- Treat the creditor's destination as system-owned, never caller-supplied.
- Prohibit requests for payer bank-account or card credentials.
- Permit payment instructions only when explicitly present in the validated case.
- Without validated instructions, confirm the immediate-payment commitment and
  avoid inventing execution details. The caller-facing wording for this condition
  is superseded by change 0049, which removes unsolicited availability disclaimers.
- Apply the same rule in the durable collections prompt.

## Human Approval

The user explicitly reported that asking which bank account they wanted to pay
was illogical and requested it be removed on 2026-07-10.

## Acceptance Criteria

- Runtime control forbids asking the caller for the payment destination.
- Runtime control forbids collecting payer banking credentials.
- Missing payment instructions cannot be invented or represented as placeholders.
- Immediate payment can still be confirmed as an outcome and closed normally.
- Spanish and non-Spanish runtime instructions express the same policy.
- Controller and prompt tests cover the guard.
- Full regression, adherence, spec, and scaffold checks pass.

## Non-Goals

- Processing a real payment or collecting regulated payment credentials.
- Adding fictional banking details to the demo case.
- Hard-coding Al Corriente-specific behavior into the generic FSM.
