# Change: Echo-Safe Turn and TTS Control

## Goal

Stop agent playback leaking through the microphone from becoming a caller turn,
changing the FSM, or cutting the agent's own response. Keep valid, explicit
caller selections such as `pago inmediato` deterministic.

## Evidence

The recorded console session contained agent-language echoes interpreted as
caller utterances (`Tiene bellezas`, `Hay dos opciones para resolverlo`, and
`Il compromet`). They caused valid-but-wrong FSM transitions because the FSM
received false STT input. The non-streaming OpenAI TTS adapter also synthesized
multiple sentence-sized chunks, creating audible gaps and additional echo
opportunities.

## Scope

- Add a deterministic echo/input guard before FSM interpretation.
- Suppress short non-safety fragments and active-playback phrase echoes, while
  preserving explicit termination and recognized resolution selections.
- Raise barge-in confirmation to three words and `0.80s` sustained speech.
- Extend console AEC warm-up to eight seconds.
- Batch sentence synthesis for non-streaming TTS to avoid response fragmentation.
- Add deterministic payment-selection recognition so `pago inmediato` cannot be
  mapped to an unrelated resolution type.
- Correlate barge-in and voice-metric telemetry with the same call ID used by
  FSM traces.

## Acceptance Criteria

- A transcript during agent playback with fewer than three words is suppressed
  before it can advance the FSM, unless it is an explicit termination or an
  allowed resolution selection.
- A transcript overlapping the current agent phrase is suppressed while the
  agent is speaking or within a short post-playback guard window.
- Suppressed input is observable in the call telemetry with its reason and call
  ID; it creates no FSM transition.
- `pago inmediato` deterministically selects the `payment` resolution when it
  is allowed by the current case.
- The default barge-in threshold is `0.80s` and three words; force mute remains
  disabled.
- The OpenAI TTS stream adapter uses sentence pacing, reducing separate TTS
  requests for one logical response.
- The speaking model is capped at 40 completion tokens and receives a
  deterministic one-sentence, 8-to-24-word output constraint.
- Existing safety termination and ordinary, deliberate caller turns remain
  covered by tests.

## Non-Goals

- Claiming application logic replaces hardware/client acoustic echo
  cancellation.
- Disabling barge-in globally.
- Accepting unverified echo-prone input as evidence for a terminal FSM action.
