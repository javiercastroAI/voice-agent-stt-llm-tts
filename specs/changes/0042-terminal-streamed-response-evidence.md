# Change: Terminal Streamed Response Evidence

## Goal

Ensure the end-of-call assessment always receives the terminal farewell evidence
when LiveKit speaks the farewell but omits its usual `conversation_item_added`
event during end-call shutdown.

## Scope

- Keep `conversation_item_added` as the primary assistant-response evidence path.
- Expose finalized console transcription text to an optional callback.
- Record finalized streamed text only when the oldest pending FSM transition is
  terminal.
- Deduplicate a later normal conversation item containing the same terminal
  response.
- Recompute the dashboard assessment before the session and dashboard close.

## Human Approval

The user reported a terminal dashboard permanently stuck at 8/9 response
evidence on 2026-07-10. Runtime logs confirmed the farewell was spoken before
shutdown but no correlated final conversation item reached the trace recorder.

## Acceptance Criteria

- A spoken terminal farewell moves response coverage from N-1/N to N/N.
- Non-terminal streamed responses are not recorded through the fallback path.
- A later duplicate conversation item does not create an orphan response.
- The final deterministic adherence verdict replaces `Finalizing evidence`
  before dashboard shutdown.
- Existing trace, transcript, dashboard, and lifecycle tests continue to pass.

## Non-Goals

- Treating generated-but-unspoken text as response evidence.
- Replacing normal conversation-item correlation for non-terminal turns.
- Delaying resource shutdown to wait indefinitely for optional SDK events.
