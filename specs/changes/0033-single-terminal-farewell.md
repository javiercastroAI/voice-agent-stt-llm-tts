# Single terminal farewell

## Goal

Natural agreement and sign-off language in the confirmation phase can be
classified as `unknown` or as an unrelated intent. The FSM then remains in
`confirmation` and repeatedly asks the caller to confirm an outcome that has
already been agreed. Rapid caller turns can also queue multiple responses after
the call has logically ended. Ensure an agreed call ends with one farewell.

## Scope

- Treat narrow, locale-independent Spanish and English agreement/sign-off
  phrases as `outcome_confirmed` only while the FSM is in `confirmation`.
- Keep explicit termination as a global deterministic safety guard.
- Once `should_end` is set, reject every later or concurrently queued user turn
  before intent interpretation and response generation.
- End the session only after speech for the terminal turn has started and its
  single farewell has finished; speech that was already active when the FSM
  ended must not trigger premature shutdown.
- Record exactly one terminal transition and generate at most one terminal
  response per call.

## Human Approval

The user explicitly requested this repeated post-agreement confirmation fix on
2026-07-10.

## Acceptance Criteria

- `Todo correcto`, `de acuerdo`, `gracias`, `buen dia`, and equivalent narrow
  English phrases close a call from `confirmation`.
- The same phrases do not confirm identity or alter earlier FSM phases through
  the deterministic contextual guard.
- A second user turn after the terminal transition raises the runtime stop
  signal and does not invoke the intent interpreter.
- An existing speaking-to-listening transition cannot close the session before
  the terminal farewell starts.
- Unit and scripted adherence scenarios cover agreement, sign-off, and queued
  post-terminal turns.
