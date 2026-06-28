# Change: Aggressive STT VAD Latency Tune Experiment

## Goal

Document the rejected smaller STT turn-silence window and tighter dynamic
endpointing cap experiment so the stable endpointing tune remains the runtime
default.

## Scope

- Fast STT turn-silence experiment result.
- Barge-in maximum endpointing delay experiment result.
- Local example/runtime environment values used for console telemetry tests.
- Documentation and deterministic configuration/session option tests.

## Acceptance Criteria

- The stable fast STT turn-silence window is restored to `150ms`.
- The stable dynamic endpointing window remains `0.20s` minimum and `0.55s`
  maximum.
- Preemptive generation remains disabled by default.
- Tests assert the restored stable defaults and preserve override behavior.
- The rejected `100ms` / `0.40s` experiment is not left active because it
  increased measured EOU delay.
