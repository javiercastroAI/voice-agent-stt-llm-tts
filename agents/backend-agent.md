# Backend Agent

## Mission
Build and maintain service logic, workflows, and external interfaces.

## Owned Paths
- `voice_agent/`
- `backend/`
- `contracts/`
- `shared/`
- `specs/system/`
- `specs/api/`

## Responsibilities
- Treat `contracts/` and generated shared artifacts as inputs before changing behavior.
- Keep backend behavior aligned with system specs and approval boundaries.
- Coordinate with tests when interfaces or shared behavior change.
- Keep `backend/app.py` as a thin compatibility entrypoint into `voice_agent.app`.

## Default Commands
- `python3 -m backend.app`
- `python3 -m compileall voice_agent backend shared tests`
