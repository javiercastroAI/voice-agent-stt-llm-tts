# Change: Bounded Console Process Exit

## Goal

Guarantee that a completed local console call releases the parent console
process even when LiveKit's graceful signal handler shuts down the worker but
blocks while joining its console thread.

## Scope

- Preserve the existing session-close ordering: close the dashboard server,
  request LiveKit's normal SIGINT shutdown, and allow the CLI to join cleanly.
- Arm a short daemon watchdog before raising SIGINT.
- If the process is still alive two seconds later, terminate the already-closed
  console process with a successful exit status.
- Apply the watchdog only to fake-job console calls, never production workers.

## Human Approval

The user reported that the completed call remained active and asked for the
failure to be checked on 2026-07-10. The live trace confirmed that the session
closed while the parent console process remained alive.

## Acceptance Criteria

- Console session close still closes the transcript server first.
- The normal SIGINT shutdown path remains the primary exit mechanism.
- A daemon watchdog forces process exit after two seconds if graceful shutdown
  does not finish.
- The watchdog is armed before SIGINT because the signal handler may not return.
- Unit tests verify signal choice, watchdog delay, daemon mode, and fallback
  exit status without terminating the test runner.
- The full regression, adherence, spec, and scaffold checks pass.

## Non-Goals

- Force-exiting production workers after individual calls.
- Skipping final-farewell playout or terminating before `AgentSession` closes.
- Changing FSM terminal-state or end-call authorization rules.
