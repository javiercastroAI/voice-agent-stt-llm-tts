# Change: Terminal Speech-Handle Evidence

## Goal

Finalize terminal response evidence from LiveKit's completed end-call speech
handle, which remains authoritative even when optional transcript and
conversation-item callbacks are omitted.

## Scope

- Register a completion callback on the exact speech handle that owns the
  `end_call` tool invocation and farewell.
- After playout completes, select the last non-empty assistant message from the
  handle's committed chat items.
- Correlate that actual message with the pending terminal FSM transition.
- Retain existing conversation-item, streamed-text, session-close flush, and
  deduplication paths as compatible fallbacks.

## Human Approval

The user explicitly requested that the repeatedly pending terminal assessment
be solved on 2026-07-10. Multiple durable traces showed only the final terminal
response missing even though the farewell audibly completed.

## Acceptance Criteria

- Completed end-call speech records the actual final assistant message.
- Non-assistant and empty speech-handle items are ignored.
- A later duplicate callback cannot create orphan response evidence.
- Durable response coverage reaches N/N before session close.
- Existing terminal authorization and resource-release behavior remains intact.
- Full regression, adherence, spec, and scaffold checks pass.

## Non-Goals

- Recording unplayed model output.
- Treating the tool's farewell instructions as if they were spoken text.
- Replacing the external FSM's authority over call termination.
