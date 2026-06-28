# Change: Public Default LLM

## Goal

Use `gpt-4o-mini` as the public default language model for the voice-agent
runtime and repo configuration.

## Scope

- Runtime configuration defaults
- Repo-local `.env` and `.env.example`
- Documentation and tests that describe or assert the default LLM

## Acceptance Criteria

- The voice agent default LLM is `gpt-4o-mini`.
- The repo-local `.env` and `.env.example` set `OPENAI_MODEL=gpt-4o-mini`.
- Documentation reflects `gpt-4o-mini` as the default LLM.
- Tests remain green after the default-model change.

## Non-Goals

- Changing the default STT model
- Changing the default TTS model
- Adding model-selection heuristics
