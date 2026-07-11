# Change: Conversational Progress and Split Verdict

## Goal

Prevent case-review confirmation loops and distinguish structural FSM compliance
from human-facing conversational quality in the live assessment.

## Scope

- Treat contextual affirmative phrases in objection handling as acceptance of the
  proposed case review.
- Complete the case-review outcome directly when that acceptance is unambiguous.
- Accept contextual confirmation variants such as "es correcto", "claro", and
  expanded "sí, claro" phrases.
- Handle `outcome_confirmed` defensively in objection handling when `case_review`
  is approved.
- Prohibit claims that a review request was recorded before selection.
- Prohibit payment options during case-review confirmation.
- Detect duplicate responses and lack of phase/directive progress deterministically.
- Display separate FSM adherence and conversational-quality verdicts, with the
  overall verdict reflecting the worse result.

## Human Approval

The user reported on 2026-07-10 that a call assessed as satisfactory repeated the
same complaint-registration question in a loop and approved the proposed fix.

## Acceptance Criteria

- "Es correcto, correctísimo", "claro", and "sí, claro, ya se lo he dicho" cannot
  remain indefinitely in objection handling after a case-review proposal.
- Accepted case review records the outcome once and closes without another
  confirmation loop.
- Repeated identical assistant responses produce a conversational-quality failure.
- A case-review directive that offers payment options produces a quality failure.
- A pre-selection response that claims a review request is recorded produces a
  quality failure.
- Structural FSM status can pass while conversational quality fails.
- Overall dashboard status is not satisfactory when either dimension fails.
- The observed call re-scores as conversationally unsatisfactory.

## Non-Goals

- Using an LLM judge for deterministic loop detection.
- Performing a real case review.
- Changing creditor-specific case data.
