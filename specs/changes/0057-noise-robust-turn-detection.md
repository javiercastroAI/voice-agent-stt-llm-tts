# Change: Noise-Robust Turn Detection

## Goal

Prevent steady background noise, short acoustic impulses, and speaker echo from
interrupting the agent or creating user turns, while preserving deliberate
caller barge-in.

## Root Cause

The previous contact-center profile called `session.interrupt(force=True)` at
the first VAD speaking edge. That application-level force mute bypassed
LiveKit's configured minimum speech duration, minimum word count, and false
interruption recovery. The default Silero and realtime STT thresholds were also
too permissive for an always-noisy environment, and the two-second FSM intent
timeout failed closed during otherwise recoverable provider latency.

## Scope

- Configure Silero speech probability, hysteresis, minimum speech duration,
  minimum silence duration, and prefix padding explicitly.
- Use a conservative, multi-signal interruption policy: qualified VAD speech,
  sustained duration, and STT word evidence.
- Disable application-level force mute by default so LiveKit remains the single
  interruption authority.
- Keep automatic false-interruption resume enabled.
- Harden realtime STT server VAD and endpointing defaults for persistent noise.
- Increase the FSM intent-classifier timeout without changing its fail-closed
  semantics.
- Preserve operator overrides through environment configuration.

## Acceptance Criteria

- Silero defaults to an activation threshold of `0.70`, deactivation threshold
  of `0.50`, minimum speech duration of `0.40s`, minimum silence duration of
  `0.65s`, and prefix padding of `0.30s`.
- Realtime STT server VAD defaults to threshold `0.70` and requires `400ms` of
  silence before closing a turn.
- LiveKit requires at least `0.60s` of speech and two recognized words before
  interrupting agent speech.
- `BARGE_IN_IMMEDIATE_MUTE_ENABLED` defaults to `false`; no
  `session.interrupt(force=True)` request is made merely because VAD reports a
  speaking edge.
- False interruptions resume automatically after a `1.5s` timeout.
- Endpointing defaults to a `0.40s` minimum and `1.20s` maximum delay, avoiding
  premature turns from short noise gaps while remaining conversational.
- The FSM intent interpreter timeout defaults to `5.0s` and still maps failures
  to the deterministic `unknown` fallback.
- The local runtime profile and `.env.example` use the same noise-robust values.
- Tests prove the defaults reach Silero and LiveKit, immediate force mute is
  disabled by default, and every value remains operator-configurable.

## Operational Notes

- A single amplitude/SNR threshold is not treated as proof of human speech.
  Speech-model confidence, duration, transcript evidence, AEC, and false-positive
  recovery are combined because background voices and acoustic echo can have a
  high electrical SNR.
- Console tests should keep AEC enabled and use separate input/output devices or
  headphones when possible. Room and telephony deployments should add a
  supported upstream noise/voice-isolation model before VAD and STT.

## Non-Goals

- Replacing LiveKit's interruption engine with a custom DSP pipeline.
- Claiming that VAD tuning alone provides acoustic echo cancellation.
- Enabling a paid or cloud-specific noise-cancellation provider implicitly.
