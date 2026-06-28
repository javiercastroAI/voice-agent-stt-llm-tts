# Change: Natural Collections Prompt

## Goal

Make the outbound collections assistant sound natural and useful while keeping
privacy, data-minimization, and non-coercive collections guardrails.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- Deterministic config tests for prompt intent and safety constraints.

## Acceptance Criteria

- The default prompt describes the assistant as an outbound friendly-collections
  agent for a Spain contact-center setting.
- The prompt requires natural, brief, conversational Spanish instead of
  form-like verification language.
- The opening stays neutral until the recipient identity is confirmed.
- Verification uses the least personal data necessary and avoids DNI, date of
  birth, address, bank data, and documents unless approved context requires it.
- After verification, the assistant gets to the point in one sentence and asks
  one practical next-step question.
- The prompt forbids invented balances, dates, legal status, fees, payment
  links, and account details.
- The prompt forbids pressure, shame, threats, and legal consequences not
  provided by context.
- Existing latency and utterance-length constraints remain unchanged.

## Rationale

The previous prompt was compliant but too procedural: it encouraged repeated
identity collection and unnatural wording before explaining the purpose of the
call. This revision keeps third-party disclosure controls and data minimization
while giving the model a concrete, human call flow.
