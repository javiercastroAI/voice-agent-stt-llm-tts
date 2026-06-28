# Change: Completion Budget Anti-Truncation Tune

## Goal

Prevent short contact-center replies from being cut off before the spoken
sentence finishes.

## Scope

- LLM maximum completion token default.
- Local example/runtime environment values.
- README runtime configuration.
- Deterministic config and metadata tests.

## Acceptance Criteria

- `OPENAI_MAX_COMPLETION_TOKENS` defaults to `60`.
- Operators can still set `OPENAI_MAX_COMPLETION_TOKENS=none` to remove the cap.
- The concise-response prompt remains unchanged.
- Endpointing, VAD, barge-in, and realtime STT timing settings remain unchanged.
- Tests assert the new default while preserving explicit override behavior.

## Rationale

The previous `20` token cap reduced latency but can force the LLM to stop
mid-utterance when a reply needs a complete Spanish sentence. Raising the cap
keeps replies brief through instructions while giving the model enough budget to
finish the utterance cleanly.
