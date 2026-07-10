# Change: Console Worker Exits on Terminal Hang-up

## Goal

Make a completed local console call terminate the full console runner exactly as
an operator-initiated Ctrl-C/Exit does, instead of closing only the inner agent
session and leaving the parent worker alive.

## Scope

- Keep the existing `end_call` tool responsible for farewell playout and
  `AgentSession` shutdown.
- When a fake-job console session emits `close`, close the transcript web server
  and raise the CLI's handled interrupt signal.
- Let LiveKit's console CLI catch that signal and execute its normal worker
  `aclose()` and thread join path.
- Do not signal the process for production room jobs.

## Human Approval

The user explicitly requested terminal hang-up to behave like Codex console
Exit on 2026-07-10.

## Acceptance Criteria

- A console session close requests one console-process exit after closing the
  transcript server.
- The exit request uses the same handled interrupt path as Ctrl-C.
- The console worker shuts down without requiring a later Codex `write_stdin`.
- Production room sessions retain their existing lifecycle.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Stopping a production worker after each production call.
- Replacing the terminal-only `end_call` tool guard.
