# Change: Short First Response Handoff Tune

## Goal

Reduce perceived response latency without realtime audio by making the first
LLM response segment shorter, so text-to-speech receives less text and starts
audio generation sooner.

## Scope

- LLM max completion token default.
- Default agent instruction style for first response segments.
- Local example/runtime environment values.
- Documentation and deterministic configuration tests.

## Acceptance Criteria

- `OPENAI_MAX_COMPLETION_TOKENS` defaults to `20`.
- The default instructions require the first spoken sentence to be short and
  direct.
- Preemptive generation remains disabled by default.
- Endpointing remains on the stable `150ms` / `0.55s` tune.
- Tests assert the new defaults and preserve override behavior.
