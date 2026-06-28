# Change: EOU Latency Split Telemetry

## Goal

Expose the observed end-of-utterance latency boundaries needed to diagnose why
the agent does not begin responding immediately after caller speech ends.

## Scope

- Derived telemetry fields for the LiveKit end-of-utterance metrics boundary.
- SQLite columns for post-session latency analysis.
- Console and web metric panels that show the split without requiring raw JSON
  inspection.
- VAD aggregate timing visibility so local VAD inference pressure can be
  correlated with EOU delay.

## Acceptance Criteria

- EOU metric payloads include the observed speech-end to final-transcript delay,
  the final-transcript to user-turn-completed delay, and the total observed
  speech-end to turn-completed delay.
- EOU metric payloads clearly mark the split source as derived from LiveKit EOU
  metrics, because the runtime does not emit a separate local VAD speech-end
  timestamp.
- SQLite telemetry stores the derived EOU split fields in queryable columns and
  remains compatible with existing telemetry databases.
- The EOU metric panel displays the observed split fields.
- VAD metrics are visible in console/web panels with average inference duration
  per VAD inference.
- Unit tests cover payload serialization, SQLite persistence, and formatting for
  the new latency split fields.
