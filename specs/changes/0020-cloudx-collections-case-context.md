# Change: CloudX Collections Case Context

## Goal

Add a concrete collections case so the assistant can explain the payment issue
after verifying identity.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for the concrete case context.

## Acceptance Criteria

- The prompt includes a case detail for one pending CloudX monthly charge.
- The prompt identifies the calling company as `MacroHard`.
- The prompt identifies the called company as `Al Corriente S.L.`.
- The amount is `1.527 euros`.
- The assistant must still avoid mentioning debt, product, amount, or dates
  before verifying identity.
- The assistant must still avoid inventing extra balances, due dates, legal
  status, fees, payment links, or account data.
- Existing latency, barge-in, and utterance-length settings remain unchanged.

## Rationale

The previous prompt had only a generic payment-pending reason. Adding a concrete
case lets the assistant answer natural follow-up questions such as what the
payment is about without asking the customer to provide the missing detail.
