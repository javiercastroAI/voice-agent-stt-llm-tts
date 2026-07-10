# Change: Deterministic Terminal Speech and Hangup

## Goal

Guarantee that a terminal FSM transition produces one recorded farewell and
releases call resources without depending on the speaking LLM to select a tool.

## Scope

- Generate the terminal farewell from deterministic FSM state and locale.
- Speak the farewell directly through the voice session.
- Suppress the ordinary post-turn LLM response for terminal turns.
- Record the direct speech as terminal response evidence.
- Shut down the session when the deterministic farewell finishes.
- Validate model-reported verification fields against literal transcript evidence.
- For case review, prohibit payment persuasion and claims that a review is running.

## Human Approval

The user reported on 2026-07-10 that a terminal call remained live with microphone
resources active and an 8/9 pending dashboard assessment, and requested review.

## Acceptance Criteria

- A terminal user turn schedules exactly one non-interruptible deterministic farewell.
- Ordinary LLM generation is stopped for that terminal turn.
- The terminal speech is correlated with the terminal FSM transition.
- Speech completion requests session shutdown exactly once.
- "Sí, soy yo" cannot satisfy name or role even if the intent model reports those fields.
- A literal name and role can satisfy the default verification policy.
- Case-review confirmation does not offer payment options or imply review execution.
- The full regression and adherence suites pass.

## Non-Goals

- Replacing LiveKit session shutdown internals.
- Performing a real case review.
- Generating terminal wording probabilistically.
