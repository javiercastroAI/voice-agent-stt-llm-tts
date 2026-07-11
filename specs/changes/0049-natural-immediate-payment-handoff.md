# Change: Natural Immediate-Payment Handoff

## Goal

Keep immediate-payment confirmations natural when the validated case does not
contain payment instructions, without weakening the payment-destination guard.

## Scope

- Do not volunteer that payment data or execution details are unavailable.
- Confirm the caller's immediate-payment commitment and continue to confirmation
  or closure without an internal-sounding disclaimer.
- If the caller explicitly asks how or where to pay and the case has no validated
  instructions, direct them briefly to the creditor's official channels.
- Continue to prohibit invented payment details and requests for payer banking or
  card credentials.
- Apply the behavior in both Spanish and non-Spanish runtime instructions and in
  the durable Spanish collections prompt.

## Human Approval

The user reported on 2026-07-10 that announcing missing banking execution data
was unnatural and explicitly requested an improvement.

## Acceptance Criteria

- Missing payment instructions do not cause an unsolicited availability disclaimer.
- Immediate-payment commitments can be confirmed in plain, natural language.
- A direct request for missing payment instructions receives a brief safe handoff
  to the named creditor's official channels.
- No destination account or payer credential is invented or requested.
- Controller and prompt regression tests cover the behavior.

## Non-Goals

- Processing a payment.
- Adding fictional payment details to a case.
- Assuming that the caller has received a particular letter, link, or message.
