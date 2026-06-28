# Change: Preemptive Generation Experiment

## Goal

Keep preemptive generation available as an explicit experiment while preserving
the stable endpointing-only runtime as the default.

## Scope

- Preemptive generation default and override behavior.
- Local example/runtime environment values used for console telemetry tests.
- Documentation and deterministic configuration/session option tests.

## Acceptance Criteria

- `BARGE_IN_PREEMPTIVE_GENERATION` defaults to `false`.
- Local console runs use `BARGE_IN_PREEMPTIVE_GENERATION=false` unless explicitly
  overridden.
- Tests assert the disabled default and preserve override behavior.
- Operators can still set `BARGE_IN_PREEMPTIVE_GENERATION=true` for measured
  experiments.
- The runtime does not use a realtime audio pipeline.
