# Change: Telemetry Quality Self-Evaluation

## Goal

Add a deterministic quality gate for voice-agent telemetry so runtime health can
be evaluated from observed barge-in, latency, overtalk, mute, and transcript
stability signals without relying on manual dashboard inspection.

## Scope

- Transcript stability telemetry semantics for interim and final user
  transcripts.
- Reusable quality evaluation for voice-metric and barge-in telemetry events.
- SQLite telemetry loading for local post-session quality checks.
- Command-line self-evaluation script for local logs.
- Deterministic unit tests covering pass, warning, failure, and insufficient
  data outcomes.

## Acceptance Criteria

- Final transcript quality is not marked fragmented only because a one-word
  interim transcript arrived immediately before it.
- Interim transcript rapid-update behavior remains observable in telemetry
  payloads for realtime STT tuning.
- The evaluator reports an overall status of `pass`, `warn`, `fail`, or
  `insufficient_data`.
- The evaluator reports separate component status and reasons for barge-in
  confirmation, false candidates, immediate mute, overtalk, LLM latency, TTS
  latency, and final transcript stability.
- The evaluator uses explicit thresholds rather than dashboard-only visual
  judgment.
- The local script can evaluate the configured JSONL/SQLite telemetry outputs
  and exits nonzero only when the overall result is `fail`.
- Unit tests include synthetic telemetry fixtures for a good run, noisy interim
  transcripts, genuinely fragmented final transcripts, high overtalk, high TTS
  tail latency, false-candidate spikes, and insufficient data.
