# Change: Live Metrics in Transcript Web UI

## Goal

Expose the latest voice-agent timing metrics in the local transcript web UI so
latency and turn-taking behavior are visible without reading terminal logs.

## Scope

- Console transcript web UI
- Transcript state snapshot served by `/api/state`
- Runtime metrics capture and serialization
- UI contract for required live metrics elements

## Acceptance Criteria

- The transcript webpage renders a dedicated live metrics panel.
- The state payload served by `/api/state` includes the latest LLM, STT, TTS,
  and end-of-utterance metric blocks.
- The metrics panel refreshes live alongside the rest of the transcript state.
- Existing console metrics logging remains intact.

## Non-Goals

- Historical metrics charts
- Long-term metrics persistence
- Alerting or SLO enforcement
