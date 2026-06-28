# Change: Outbound Collections System Prompt

## Goal

Set the default voice-agent behavior for an outbound unpaid-balance contact
center flow in Spain Spanish while preserving the stable low-latency speaking
constraints.

## Scope

- Default agent instructions.
- Local and example environment `AGENT_INSTRUCTIONS`.
- README description of the default prompt profile.
- Deterministic config tests for the new prompt domain and safety boundaries.

## Acceptance Criteria

- The default prompt identifies the assistant as an outbound unpaid-balance
  agent.
- The prompt requires respectful, professional, non-threatening language.
- The prompt avoids disclosing debt details until the caller identity is
  confirmed.
- The prompt avoids inventing debt amounts, due dates, legal status, fees, or
  payment links when the runtime has not provided account data.
- The prompt supports practical outcomes: explain the reason for contact,
  listen to the customer, offer payment or callback paths, and escalate disputed
  or vulnerable-customer cases.
- The stable latency handoff remains: first sentence at most eight words, normal
  responses under fourteen words, and interruption replies eight to fourteen
  words.
