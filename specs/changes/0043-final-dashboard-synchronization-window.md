# Change: Final Dashboard Synchronization Window

## Goal

Let the browser fetch the final end-of-call assessment before the local
dashboard server and console process exit.

## Scope

- Keep call audio and microphone shutdown immediate through `AgentSession`.
- After the session emits `close`, retain only the local dashboard endpoint for
  a bounded 750 ms synchronization window.
- Close the dashboard server and request console-process exit after the window.
- Keep the delay longer than the dashboard's 350 ms polling interval.

## Human Approval

The user reported a second terminal dashboard stuck at 12/13 on 2026-07-10.
The runtime trace showed the final farewell at 19:28:22.423 and session close at
19:28:22.649, leaving only 226 ms for a browser that polls every 350 ms.

## Acceptance Criteria

- The final assessment remains fetchable for at least one complete browser poll
  after the farewell has been finalized.
- Microphone and audio resources remain governed by immediate session closure.
- Dashboard close still occurs before the console exit request.
- The synchronization delay is bounded and unit-tested without real sleeping.
- Lifecycle, dashboard, adherence, and full regression checks pass.

## Non-Goals

- Keeping the dashboard server alive indefinitely after a call.
- Delaying the spoken farewell or audio-session shutdown.
- Replacing the terminal streamed-response evidence fallback.
