# Change: Barge-in and Latency Engineering Guide

## Goal

Provide a generic operational playbook for engineers who need to diagnose,
tune, and validate barge-in behavior and perceived latency in the voice-agent
runtime.

## Scope

- Step-by-step local measurement workflow for console voice runs.
- Explanation of the runtime latency budget across STT, end-of-utterance, LLM,
  TTS, and audio playout.
- Explanation of barge-in detection, immediate mute, STT confirmation, false
  interruptions, and recovery behavior.
- Recommended tuning order for the existing environment variables and
  telemetry outputs.
- Reusable manual test scenes for normal turns, command interruptions,
  backchannels, false positives, long objections, recovery, and consultation
  flows.
- Practical symptom-to-metric-to-adjustment examples.
- Prompt recovery examples for interruptions, backchannels, objections, and
  simulated consultation.
- Validation commands that preserve the repository's spec-first operating
  model.

## Acceptance Criteria

- The guide names the current repo entry points, configuration variables, and
  telemetry files used for barge-in and latency work.
- The guide separates latency tuning from barge-in tuning and explains the
  tradeoff between faster endpointing and clipped caller utterances.
- The guide includes a repeatable baseline-change-compare workflow instead of
  relying on subjective call feel.
- The guide includes practical scenarios for short backchannels, real command
  interruptions, missed interruptions, false interruptions, long caller
  objections, and consultation recovery.
- The guide includes concrete examples of expected and deficient recovery
  responses.
- The guide references the existing quality evaluation script and validation
  commands.

## Non-Goals

- Changing runtime defaults.
- Replacing the LiveKit interruption engine.
- Defining production SLAs before enough representative telemetry exists.
