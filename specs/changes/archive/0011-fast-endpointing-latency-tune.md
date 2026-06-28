# Change: Fast Endpointing Latency Tune

## Goal

Reduce the time from caller speech stop to agent response start by making the
contact-center endpointing profile more aggressive before changing the TTS
architecture.

## Scope

- Fast STT turn-silence default.
- Barge-in endpointing delay defaults.
- Consecutive speech delay default.
- Local example/runtime environment values used for console telemetry tests.
- Documentation and deterministic configuration tests.

## Acceptance Criteria

- The default fast STT turn-silence window is `150ms`.
- The default dynamic endpointing delay window is `0.20s` minimum and `0.55s`
  maximum.
- The default minimum consecutive speech delay is `0.10s`.
- Local console runs use the same tuned values unless explicitly overridden.
- Tests assert the tuned defaults and preserve the override behavior.
- The next telemetry comparison measures whether end-of-utterance delay falls
  below `0.5s` before attempting streaming TTS changes.
