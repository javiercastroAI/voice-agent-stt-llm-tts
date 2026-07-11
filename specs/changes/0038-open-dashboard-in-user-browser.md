# Change: Open Dashboard in the User's Browser

## Goal

Open the local call dashboard immediately in the user's normal default browser
when console mode starts, without depending on Codex browser automation.

## Scope

- Start the transcript/FSM dashboard server first.
- Open its resolved URL with Python's standard default-browser integration.
- Perform the browser open before starting the voice session and outbound
  greeting.
- Keep browser opening limited to local fake-job console mode.
- Preserve fallback behavior when the operating system cannot open a browser;
  the printed dashboard URL remains available.

## Human Approval

The user explicitly requested the dashboard in their own browser rather than an
automated browser on 2026-07-10.

## Acceptance Criteria

- Console entrypoint opens the resolved dashboard URL exactly once.
- Browser opening happens after the server starts and before `session.start`.
- Production jobs never open a local browser.
- A browser-launch failure does not prevent the voice session from starting.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Selecting a specific browser application instead of the user's OS default.
- Opening production dashboards on worker hosts.
