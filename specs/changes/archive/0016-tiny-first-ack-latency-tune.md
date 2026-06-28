# Change: Tiny First Acknowledgement Latency Tune Experiment

## Goal

Document the rejected tiny-first-acknowledgement experiment and preserve the
stable short-response handoff defaults.

## Scope

- Rejected completion token cap experiment.
- Rejected first-acknowledgement speaking instruction experiment.
- Local/example environment defaults and documentation restored to the prior
  stable handoff.
- Deterministic config tests that lock the restored defaults.

## Acceptance Criteria

- The default agent instructions start each response with a direct sentence of
  at most eight words.
- Normal responses stay under fourteen words unless the caller asks for detail.
- Interruption replies target eight to fourteen words.
- The default maximum completion token cap is restored to `20`.
- `.env`, `.env.example`, README, and config tests agree with the restored
  defaults.
- Endpointing and realtime settings are not changed by this rollback.

## Result

The tiny-first-acknowledgement run failed the self-evaluation compared with the
prior baseline: average EOU increased, one barge-in was ignored, transcript
fragmentation rose, and LLM TTFT had a large tail-latency outlier. The stable
handoff remains the default while future latency work focuses on provider/model
TTFT or true streaming TTS.
