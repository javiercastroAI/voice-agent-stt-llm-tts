# Change: Production Readiness Loop for Interruption, Barge-in, and Latency

## Goal

Create a repeatable engineering loop that improves the voice-agent runtime until
interruption handling, barge-in recovery, transcript stability, and perceived
latency meet production-readiness gates with reproducible telemetry evidence.

The loop converts subjective call feel into measurable pass/fail criteria. A
release is production-ready only after the same scripted scenario suite passes
the quality evaluator, manual call review, regression tests, and governance
checks across repeated runs.

## Scope

- Define a production-readiness target for interruption, barge-in, latency, and
  transcript stability.
- Run a baseline-change-compare loop using the existing telemetry SQLite files,
  JSONL files, web UI state, and `scripts/evaluate-telemetry.py`.
- Use `specs/scenarios/production-readiness.json` as the versioned manual
  caller scenario pack until a synthetic caller exists.
- Use `scripts/record-loop-run.py` after each completed call to write a durable
  run record with commit, config hash, scenario pack id, telemetry row range,
  machine quality report, and manual verdict.
- Keep the loop spec-first: every behavior, threshold, prompt, runtime, or
  telemetry change starts with a spec delta before implementation is finalized.
- Improve one variable or code path per iteration unless an incident-level bug
  requires a bundled fix.
- Require the same scenario pack on every iteration: normal turns, command
  interruptions, short backchannels, false-positive noise, missed
  interruptions, long objections, and consultation recovery.
- Preserve both machine evidence and human review notes for every iteration.
- Promote only changes that improve the target metric without degrading
  guardrails.

## Production Target

The production target is reached when all of these conditions are true for at
least three consecutive representative runs:

- `scripts/evaluate-telemetry.py --json` returns `status: "pass"`.
- Barge-in turn confirmation rate is at least 95%.
- Barge-in false-candidate rate is at most 5%.
- Immediate mute success rate is at least 98%.
- Average overtalk is at most 250 ms.
- Maximum overtalk is at most 1 second.
- Average LLM TTFT is at most 900 ms.
- Maximum LLM TTFT is at most 2 seconds.
- Average TTS TTFB is at most 900 ms.
- Maximum TTS TTFB is at most 2 seconds.
- Final transcript fragmentation rate is at most 5%.
- No command interruption continues the previous agent script after the caller
  clearly takes the turn.
- No short backchannel derails the call flow into an unrelated objection path.
- No recovery response is truncated, contradictory, or longer than needed for a
  contact-center recovery turn.

If real production traffic later shows stricter or looser needs, the target must
be changed in specs first and then reflected in the evaluator thresholds.

## Engineering Loop

Each iteration follows this order:

1. Record the current commit, configuration, telemetry row ids, and scenario
   pack version.
2. Run the full scenario pack without changing variables mid-run.
3. Evaluate telemetry with `scripts/evaluate-telemetry.py --json`.
4. Record manual review notes for interruption timing, caller-word loss,
   recovery relevance, backchannel handling, and perceived wait.
5. Pick the highest-impact failing component from the telemetry report.
6. Make exactly one targeted change to configuration, prompt, runtime behavior,
   telemetry, or tests.
7. Update specs and tests in the same change set when behavior or thresholds
   change.
8. Re-run the same scenario pack and compare against the baseline.
9. Keep the change only if the target component improves and no guardrail moves
   from pass to warn or fail.
10. Stop the loop only when the production target passes for three consecutive
    representative runs and release approval evidence is complete.

During the current development phase, the human tester provides the caller side
of the call. After each call ends, the loop engineer records the run, reviews
telemetry and human notes, proposes one next improvement, implements it,
validates it, and asks the human tester to repeat the same scenario pack.

Post-call recording command:

```bash
python3 scripts/record-loop-run.py \
  --profile production \
  --manual-verdict unknown \
  --notes "Replace with clipped words, awkward pauses, or recovery issues"
```

## Backlog Order

1. Add regression fixtures for backchannel, command interruption, false
   interruption, late transcript, and recovery paths.
2. Add documentation for release evidence: telemetry report, manual notes,
   validation commands, residual risks, and approval record.
3. Add a synthetic caller participant that can play timed speech, silence,
   noise, and interruption audio through the real STT/VAD path.
4. Once evidence is stable, update CI or release governance so production
   release candidates must include a passing production-readiness report.

## Acceptance Criteria

- The loop has a written production target with numeric thresholds for barge-in,
  immediate mute, overtalk, LLM TTFT, TTS TTFB, and transcript fragmentation.
- The loop requires repeated representative runs before production readiness can
  be claimed.
- The loop specifies a fixed scenario pack and prevents comparing runs that used
  different scenes or changed variables mid-run.
- The fixed scenario pack is stored at
  `specs/scenarios/production-readiness.json`.
- Post-call loop records can be written by `scripts/record-loop-run.py`.
- `scripts/evaluate-telemetry.py` supports a production threshold profile.
- The loop separates machine telemetry gates from manual call-quality review.
- The loop requires spec, test, implementation, and governance updates in the
  same change set for threshold or behavior changes.
- The loop names the first implementation backlog items needed to make the
  production target fully machine-verifiable.
- The existing scaffold/spec validation command passes after adding this plan.

## Non-Goals

- Claiming the current runtime is production-ready without new representative
  telemetry evidence.
- Replacing LiveKit's native interruption engine.
- Optimizing multiple unrelated latency variables in a single iteration.
- Treating subjective call feel as sufficient release evidence.
