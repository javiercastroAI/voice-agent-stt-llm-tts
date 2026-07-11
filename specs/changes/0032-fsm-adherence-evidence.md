# Change: FSM Adherence Evidence and Evaluation

## Goal

Create durable per-turn FSM evidence, deterministic adherence checks, scripted
scenario replay in CI, an optional soft-quality judge, and a combined evidence
path for real-audio STT, barge-in, and latency runs.

## Scope

- Record FSM transition evidence and the corresponding assistant response as
  correlated JSONL events without writing case payloads or internal metadata.
- Configure tracing with `FSM_TRACE_PATH`; tracing remains opt-in because it
  contains caller transcripts.
- Add a versioned scripted FSM adherence scenario pack.
- Replay scenario events through the real LangGraph FSM in offline tests.
- Deterministically reject privacy disclosure, invalid or stale transitions,
  missing responses, unsupported resolutions, and non-terminal termination.
- Add `scripts/evaluate-fsm-adherence.py` for scenario and trace evaluation.
- Add an optional OpenAI Structured Outputs judge for clarity, tone, and
  concision only. Its result cannot override deterministic compliance.
- Add a real-audio scenario pack for STT errors, barge-in, false interruption,
  and latency evidence.
- Add `scripts/evaluate-fsm-audio-run.py` to combine FSM adherence with the
  existing production telemetry quality report.
- Run deterministic scenario replay in CI.

## Evidence Boundary

The trace may contain caller and assistant transcripts, interpreted intent,
phase transition, directive, guard reason, refusal count, selected resolution,
and verification/terminal flags. It must not contain customer case payloads,
amounts copied from configuration, references, or internal metadata as separate
trace fields.

## Verdict Model

- `complianceStatus` is calculated only by deterministic rules.
- Privacy, transition, termination, and resolution failures always fail the
  compliance verdict.
- `softQuality` is optional and reports clarity, tone, and concision.
- A soft-quality pass never changes a deterministic failure to pass.
- Real-audio readiness requires both FSM compliance and production telemetry
  quality to pass.

## Human Approval

The user explicitly approved this adherence and real-audio evaluation layer on
2026-07-10.

## Acceptance Criteria

- Opening and every completed user turn receive stable trace identifiers.
- Assistant evidence is correlated to the oldest pending FSM turn.
- Duplicate assistant events do not create duplicate evidence.
- Scenario replay covers every FSM phase and global guard.
- Scenario replay uses typed events and the production LangGraph graph.
- Pre-verification assistant text is checked against sensitive case values.
- Explicit termination must reach `ended` in the same turn.
- Selected resolutions must exist in runtime case configuration.
- Missing, duplicate, or orphan response evidence is reported.
- Optional judging sends only trace text and FSM directive, uses `store=false`,
  and cannot alter deterministic status.
- Combined audio evaluation fails when either FSM adherence or production
  voice telemetry fails.
- All tests and repository governance checks pass.

## Non-Goals

- Using an LLM judge for privacy, state-transition, or termination decisions.
- Checking real customer transcripts into the repository.
- Automating microphone routing without an approved virtual-audio fixture.
- Claiming production readiness from synthetic or unit tests alone.
