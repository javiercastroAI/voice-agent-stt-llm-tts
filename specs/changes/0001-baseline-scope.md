# Change: Baseline Scope for Voice agents STT-LLM-TTS (Spec driven)

## Goal

Capture the initial delivery model, boundaries, and validation expectations for this repository.

## Scope

- Repo operating model
- Voice agent application code in `voice_agent/`
- Compatibility backend entrypoint in `backend/`
- Local transcript web UI for console mode
- Baseline specs and contracts
- Validation and contribution workflow

## Acceptance Criteria

- The repo has explicit planner, delivery, and review roles.
- The copied voice agent still starts from `python -m voice_agent.app console`.
- The scaffold backend entrypoint delegates to the copied voice agent app.
- The repo has a `specs/` directory with machine-readable artifacts.
- The repo has a baseline contract placeholder in `contracts/`.
- The repo has a generated shared artifact derived from the contract.

## Non-Goals

- Final product architecture
- Production deployment design
- Domain-specific contract completion
