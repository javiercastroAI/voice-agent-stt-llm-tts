# Change: Low-Latency Qualified Barge-in

## Goal

Allow a caller to interrupt promptly once real speech is detected, without
weakening the noise and echo protections that prevent false FSM turns.

## Evidence

In the latest call, a real interruption was detected at speech onset but only
confirmed after the final seven-word transcript. The measured confirmation and
overtalk delay was `3.50s`. The realtime STT emits one-word interim results,
so the three-word barge-in threshold forced the runtime to wait for final STT.

## Scope

- Lower only the interruption confirmation threshold to `0.50s` and one
  recognized interim or final word.
- Keep the separate Silero/realtime-STT noise profile, eight-second AEC warmup,
  echo-input guard, and FSM safety checks unchanged.
- Preserve automatic false-interruption recovery.

## Acceptance Criteria

- A real caller utterance can qualify for interruption from its first stable
  one-word STT interim result after at least `0.50s` of speech.
- The VAD activation threshold, echo suppression, and FSM input guard remain
  unchanged, so background noise and agent playback do not gain FSM authority.
- Configuration, documentation, and deterministic policy tests use the new
  qualified-barge-in defaults.

## Non-Goals

- Reducing the VAD speech-confidence threshold.
- Treating a VAD edge without speech evidence as a caller turn.
