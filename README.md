# Voice Agent

A Python voice-agent runtime for building and testing low-latency contact-center
experiences with OpenAI, LiveKit Agents, Silero VAD, barge-in handling, local
telemetry, and a transcript web UI.

Author: Javier Castro. This project is shared for research and education
purposes.

The checked-in demo profile is a Spanish outbound collections scenario:
`MacroHard` calls `Al Corriente S.L.` about one pending `CloudX` monthly charge
for `1.527 euros`. The scenario is deliberately fictional and its case data is
loaded from `examples/collections/al-corriente.case.json`.

## Features

- OpenAI LLM, speech-to-text, and text-to-speech integration.
- Generic LangGraph conversation FSM outside the speaking LLM.
- Typed OpenAI intent interpretation with deterministic transition guards.
- LiveKit Agents runtime for console, development room, and worker execution.
- Fast controlled STT path with Spanish language pinning.
- Configurable barge-in detection, immediate mute, false-interruption handling,
  and recovery telemetry.
- Live web transcript with agent/user state, timing metrics, and barge-in KPIs.
- JSONL and SQLite telemetry for post-session quality analysis.
- Spec-first governance scaffold with tests and validation scripts.

## Requirements

- Python 3.11 or newer.
- A microphone and speaker for local `console` mode.
- An OpenAI API key.
- LiveKit credentials for `dev` or `start` room/worker modes.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

Edit `.env` and set at least:

```env
OPENAI_API_KEY=...
```

For LiveKit room or worker execution, also set:

```env
LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

## Run

Local console mode with microphone and speaker:

```bash
python -m voice_agent.app console
```

With the FSM enabled, the outbound agent automatically speaks its opening when
the session becomes active. Set `FSM_AUTO_OPENING_ENABLED=false` for user-first
testing.

Console mode opens the local `Transcript Web UI` in the user's default browser
before the voice session starts. It shows live transcript state, FSM state,
user and agent speaking state, barge-in counters, and latency metrics. The URL
is also printed as a fallback if the operating system cannot open a browser.

List local audio devices without requiring API keys:

```bash
python -m voice_agent.app console --list-devices
```

Run against a LiveKit room in development mode:

```bash
python -m voice_agent.app dev
```

Run as a worker:

```bash
python -m voice_agent.app start
```

## Configuration

Core options:

- `OPENAI_MODEL` defaults to `gpt-4o-mini`.
- `OPENAI_INTENT_MODEL` defaults to `OPENAI_MODEL` and performs typed intent
  classification before the speaking LLM runs.
- `FSM_INTENT_TIMEOUT_SECONDS` defaults to `2.0`; failures retain the current
  safe phase as an `unknown` event.
- `OPENAI_MAX_COMPLETION_TOKENS` defaults to `60`; set to `none` to disable the
  short-turn cap.
- `OPENAI_LLM_TEMPERATURE` defaults to `0.2`.
- `VOICE_PIPELINE_MODE` defaults to `controlled_fast`; set to
  `cascade_diarized` for the diarized analysis path.
- `OPENAI_STT_LANGUAGE` defaults to `es`.
- `OPENAI_TTS_MODEL` defaults to `gpt-4o-mini-tts`.
- `OPENAI_TTS_VOICE` defaults to `marin`.
- `OPENAI_TTS_RESPONSE_FORMAT` defaults to `pcm`.
- `OPENAI_TTS_SPEED` defaults to `1.05`.
- `AGENT_INSTRUCTIONS` controls the assistant behavior and scenario directly.
- `AGENT_INSTRUCTIONS_FILE` loads assistant behavior from a UTF-8 prompt file.
- `FSM_ENABLED` defaults to `true`.
- `FSM_AUTO_OPENING_ENABLED` defaults to `true`; disable it to retain a
  user-first conversation while keeping FSM processing enabled.
- `CASE_CONTEXT_FILE` defaults to
  `examples/collections/al-corriente.case.json`; point it to another validated
  case JSON file to reuse the same graph for a different case.
- `FSM_TRACE_PATH` enables correlated JSONL transition and assistant-response
  evidence. It is disabled by default because traces contain transcripts; the
  demo example writes `logs/fsm-adherence.jsonl`.

The default prompt file is:

```text
prompts/collections-es.md
```

The prompt contains generic conversational behavior. Customer, account,
product, amount, and available-resolution data come from `CASE_CONTEXT_FILE`
and are withheld from the speaking model until the FSM verifies identity.

For the complete demo configuration, see:

```text
examples/collections/
```

Fast STT options:

- `OPENAI_FAST_STT_MODEL` defaults to `gpt-4o-mini-transcribe`.
- `OPENAI_FAST_STT_REALTIME` defaults to `true`.
- `OPENAI_FAST_STT_TURN_SILENCE_MS` defaults to `150`.
- `OPENAI_FAST_STT_PREFIX_PADDING_MS` defaults to `300`.
- `OPENAI_FAST_STT_VAD_THRESHOLD` defaults to `0.5`.

Barge-in options:

- `BARGE_IN_ENABLED` defaults to `true`.
- `BARGE_IN_TURN_DETECTION_MODE` defaults to `auto`; supported explicit values
  are `stt`, `vad`, `realtime_llm`, and `manual`.
- `BARGE_IN_ENDPOINTING_MODE` defaults to `dynamic`.
- `BARGE_IN_INTERRUPTION_MODE` defaults to `vad`.
- `BARGE_IN_MIN_SPEECH_SECONDS` defaults to `0.20`.
- `BARGE_IN_MIN_WORDS` defaults to `2`.
- `BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS` defaults to `1.2`; set to
  `none` to disable false-interruption detection.
- `BARGE_IN_RESUME_FALSE_INTERRUPTION` defaults to `true`.
- `BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS` defaults to `0.20`.
- `BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS` defaults to `0.55`.
- `BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS` defaults to `0.10`.
- `BARGE_IN_PREEMPTIVE_GENERATION` defaults to `false`.
- `BARGE_IN_USER_AWAY_TIMEOUT_SECONDS` defaults to `30`; set to `none` to
  disable away detection.
- `BARGE_IN_CONFIRMATION_GRACE_SECONDS` defaults to `6.0`.
- `BARGE_IN_IMMEDIATE_MUTE_ENABLED` defaults to `true`.

Telemetry options:

- `BARGE_IN_TELEMETRY_PATH` writes JSONL barge-in events, for example
  `logs/barge-in-telemetry.jsonl`.
- `BARGE_IN_SQLITE_PATH` writes queryable SQLite barge-in events, for example
  `logs/barge-in-telemetry.sqlite3`.
- `VOICE_METRICS_TELEMETRY_PATH` writes JSONL STT, LLM, TTS, EOU, VAD, and
  transcript-stability events.
- `VOICE_METRICS_SQLITE_PATH` writes the same voice metrics to SQLite.

## Telemetry Quality

After a local run with SQLite telemetry enabled:

```bash
python scripts/evaluate-telemetry.py
```

The report evaluates barge-in confirmation, immediate mute, overtalk, LLM
latency, TTS latency, and transcript stability.

For tuning guidance, see
[docs/barge-in-latency-tuning-guide.md](docs/barge-in-latency-tuning-guide.md).

## FSM Adherence Evaluation

Replay every deterministic FSM phase and global guard without API or audio
access:

```bash
python scripts/evaluate-fsm-adherence.py --scenario-only
```

Evaluate a recorded call trace:

```bash
python scripts/evaluate-fsm-adherence.py \
  --trace logs/fsm-adherence.jsonl \
  --json
```

Add `--llm-judge` for the optional clarity, tone, and concision assessment. Its
result is reported separately and cannot override deterministic compliance.

Combine a real microphone run with the production STT, barge-in, and latency
gates:

```bash
python scripts/evaluate-fsm-audio-run.py \
  --scenario-id barge-in-termination \
  --manual-verdict pass \
  --json
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Spec and scaffold validation:

```bash
python scripts/validate-specs.py
./scripts/check-scaffold.sh
```

If shared contracts change:

```bash
python scripts/generate-contract-artifacts.py --check
```

## Repository Model

This repository uses a spec-first delivery model. Behavior, protocol, UI, and
governance changes should be reflected under `specs/` before or alongside code
changes. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[AGENTS.md](AGENTS.md) for the operating model.
