# Change: Ignore Ordered-List Numbers in Claim Checks

## Goal

Prevent deterministic adherence failures when the assistant numbers approved
menu options, while continuing to reject unsupported numeric claims contained
inside those options.

## Scope

- Remove leading ordered-list markers such as `1.`, `2)`, and `3:` before
  extracting numeric claims from an assistant response.
- Continue evaluating every other numeric token against validated case data.
- Preserve all privacy, transition, response-correlation, and closing checks.

## Human Approval

The user asked to inspect an `Unsatisfactory` call on 2026-07-10. Its exact
report showed that the only unsupported numbers were the approved option labels
`1, 2, 3, 4`.

## Acceptance Criteria

- A numbered list of options does not produce `unsupported_numeric_claim`.
- An unsupported amount, date, count, or duration inside a numbered option still
  produces `unsupported_numeric_claim`.
- The real seven-turn trace re-evaluates without the list-number false positive.
- Full regression, scenario, spec, and scaffold checks pass.

## Non-Goals

- Allowing arbitrary numbers merely because they occur on a list line.
- Weakening case grounding for amounts or payment-plan terms.
- Changing the speaking model's option wording.
