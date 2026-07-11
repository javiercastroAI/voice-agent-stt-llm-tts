# Change: Soft Barge-in and Deterministic Review Consent

## Goal

Make a caller interruption feel immediate without giving a noise or echo edge
authority to discard agent speech. Ensure that an objection can only result in
a recorded case-review request after the caller has explicitly consented.

## Design

- Keep LiveKit speech handles interruptible, but use its false-interruption
  pause/resume path rather than VAD-edge cancellation.
- At a VAD candidate, pause output audio when the output supports pausing.
- Cancel the active reply only after the existing qualified-STT rule confirms
  real caller speech. Resume paused output as soon as the VAD candidate ends
  without transcript evidence, and also on an ignored or false interruption.
- Emit separate soft-pause, soft-resume, and confirmed-cancel telemetry so
  the dashboard distinguishes a reversible floor-yield from a real interrupt.
- Treat native-paused output as active playback: LiveKit reports that phase as
  `listening`, but it still represents an agent response that may need a
  qualified caller interruption.
- Qualify cancellation asymmetrically: a single explicit stop command can
  interrupt; ordinary speech requires two recognized words and is rejected if
  it matches recent agent playback.
- Speak the review-consent offer from a deterministic template for objection
  directives. The template only asks whether the caller wants the request
  recorded; it never says that a review is already in progress or complete.

## Scope

- `voice_agent/config.py`, `voice_agent/barge_in.py`, and `voice_agent/app.py`
  for the two-phase output-control policy.
- `voice_agent/conversation_controller.py` and `voice_agent/agent.py` for the
  pre-consent review wording.
- Regression tests, environment examples, and operator documentation.

## Acceptance Criteria

- A VAD edge alone never cancels an agent response or gains FSM authority.
- A supported audio output pauses at candidate detection, a qualified interim
  or final STT transcript cancels the reply, and a candidate that ends without
  text resumes output immediately.
- A candidate remains detectable while LiveKit has temporarily changed the
  agent state to `listening` for its own false-interruption recovery.
- Playback fragments such as a single captured word cannot cancel speech;
  explicit stop commands and two-word caller interruptions remain responsive.
- A case-review request is only confirmed by the terminal FSM transition after
  explicit caller consent.
- Configuration, telemetry, tests, and operator documentation describe the
  two-phase behavior.

## Non-Goals

- Changing the noise/VAD thresholds.
- Performing an external case review; this system records a request only.
