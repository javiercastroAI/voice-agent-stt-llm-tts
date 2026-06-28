# Change: Contact Center Barge-in Management

## Goal

Make barge-in behavior explicit, configurable, observable, and tuned for
customer-service contact centers where callers must be able to interrupt
without accidental coughs, background audio, or short backchannels derailing
the agent.

## Scope

- LiveKit `AgentSession` interruption and endpointing configuration.
- Runtime barge-in policy derived from environment configuration.
- Explicit speech-to-text language configuration for monolingual
  contact-center deployments.
- Controlled pipeline mode selection between a fast runtime STT path and the
  diarized analysis path.
- Speech style configuration for Spain Spanish customer-service calls.
- LLM short-turn configuration so agent responses stay interruptible and
  recovery utterances remain concise.
- Fast STT realtime transcription mode for the controlled pipeline, without
  moving LLM/TTS orchestration to a server-to-server realtime session.
- TTS response format and speed configuration for lower first-audio latency
  experiments.
- Console transcript web UI state and metrics for detected, confirmed,
  ignored, false, and resumed false interruptions.
- Barge-in event history and optional JSONL telemetry for post-session
  analysis.
- Optional SQLite telemetry for queryable production analysis and dashboarding.
- Optional JSONL/SQLite voice-metric telemetry for STT, LLM, TTS, end-of-
  utterance, VAD, and transcript stability events.
- Immediate agent audio interruption using LiveKit `session.interrupt(force=True)`
  when VAD detects caller speech during agent speech.
- Derived KPI monitoring for event-level and turn-level confirmation rate,
  false-candidate rate, ghost interruption rate, STT confirmation delay,
  pending transcript delay, late STT after candidate expiry, agent overtalk,
  immediate mute success rate, mute latency, recovery time, backchannel rate,
  command interruption rate, language mismatch rate, per-turn outcomes, and
  unavailable interrupted-TTS duration.
- Deterministic unit tests for policy defaults, session option mapping, and
  interruption state transitions.

## Acceptance Criteria

- The runtime enables LiveKit turn handling by default with VAD interruption
  mode, dynamic endpointing, contact-center thresholds, false interruption
  timeout, and automatic false-interruption resume. VAD is the default because
  the current diarized STT and non-streaming TTS stack disables adaptive
  interruption detection at runtime.
- Operators can disable or tune barge-in behavior via documented environment
  variables without changing code.
- Operators can set `OPENAI_STT_LANGUAGE`; the Spain Spanish profile pins it to
  `es` so transcription metadata and interruption classification do not drift
  to English.
- Operators can set `VOICE_PIPELINE_MODE`; the production-oriented default is
  `controlled_fast`, which uses `OPENAI_FAST_STT_MODEL` for the live runtime
  path and keeps the diarized model available for analytics mode.
- Operators can set `OPENAI_FAST_STT_REALTIME`; the production-oriented default
  enables realtime transcription/interim results for the runtime STT path while
  keeping conversation flow, LLM, and TTS under app control.
- Operators can set `OPENAI_MAX_COMPLETION_TOKENS`; the contact-center profile
  caps completions at 32 tokens to reduce TTS duration and improve recovery
  after interruptions.
- Operators can set `OPENAI_LLM_TEMPERATURE`; the contact-center profile uses a
  low value for more predictable, concise turns.
- Operators can set `OPENAI_TTS_RESPONSE_FORMAT` and `OPENAI_TTS_SPEED`; the
  contact-center profile uses PCM and a slight speed-up so operators can measure
  whether TTFB and recovery improve without hurting naturalness.
- Operators can steer OpenAI TTS style with `OPENAI_TTS_INSTRUCTIONS`; the
  contact-center profile uses Spain Spanish speech instructions.
- Operators can disable immediate mute with `BARGE_IN_IMMEDIATE_MUTE_ENABLED`;
  it is enabled by default and requests LiveKit speech interruption at the
  candidate-detection edge, before waiting for delayed transcript confirmation.
- `/api/state` includes `barge_in_state` with the current barge-in state,
  latest reason, counters, and configured thresholds.
- `/api/state` includes recent `barge_in_events`, and the runtime can append
  JSONL telemetry when `BARGE_IN_TELEMETRY_PATH` is configured.
- The runtime can persist the same barge-in event stream to SQLite when
  `BARGE_IN_SQLITE_PATH` is configured.
- The runtime can persist the general voice metrics shown in the panel to JSONL
  and SQLite when `VOICE_METRICS_TELEMETRY_PATH` or `VOICE_METRICS_SQLITE_PATH`
  are configured.
- Voice-metric telemetry records user transcript stability signals, including
  short fragments, rapid transcript gaps, and non-Latin text in the pinned
  Spanish runtime, so realtime STT fragmentation can be analyzed post-session.
- `/api/state` includes `barge_in_kpis`, and each JSONL event includes a KPI
  snapshot so post-session analysis does not need to replay every event.
- `/api/state` includes turn-level barge-in KPIs so duplicate candidate events
  within one agent turn do not make successful interruptions look like
  unconfirmed failures.
- KPI snapshots include immediate mute attempt, success, failure, method, and
  latency fields. When LiveKit accepts immediate interruption, overtalk and mute
  latency are cut at the mute request timestamp; when it does not, telemetry
  keeps the previous agent-speech-stop based measurement and records the error.
- The web UI includes a visible Barge-in status and a Barge-in Metrics panel.
- A candidate interruption is counted when the caller starts speaking while the
  agent is speaking; it is confirmed only when qualified transcript text is
  observed.
- Candidate interruptions remain pending for a configurable grace window so
  delayed STT can confirm real speech after VAD has already returned to
  listening.
- If a qualified transcript arrives immediately after a pending candidate has
  expired, telemetry records a `late_transcript_after_ignored_candidate` event
  and KPI so operators can distinguish background noise from insufficient STT
  grace.
- False-interruption events are counted separately and record whether LiveKit
  resumed the interrupted speech.
- KPI values that cannot be measured from current LiveKit session events are
  explicit `null`/`N/A` rather than inferred. Interrupted TTS duration remains
  unavailable until audio playout or speech-handle truncation telemetry is
  exposed.
- Existing transcript, diarization, and latency metrics behavior remains
  intact.

## Non-Goals

- Replacing LiveKit's native audio interruption engine.
- Persisting long-term interruption analytics.
- Agent prompt changes for every possible recovery phrase.
- Moving to a server-to-server realtime LLM/TTS conversation loop; realtime STT
  is allowed only as a transcription optimization in the controlled pipeline.
