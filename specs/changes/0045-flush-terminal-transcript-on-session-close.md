# Change: Flush Terminal Transcript on Session Close

## Goal

Guarantee that the final spoken farewell is finalized into transcript and FSM
response evidence even when LiveKit closes the session without flushing its
text-output chain.

## Scope

- Explicitly flush pending agent transcription text from the console session
  close handler.
- Perform the flush before the dashboard synchronization window, server close,
  and console exit request.
- Keep the flush idempotent when LiveKit already finalized the text normally.
- Reuse the terminal-only streamed-response correlation and deduplication path.

## Human Approval

The user reported another terminal dashboard stuck at 12/13 on 2026-07-10.
Durable evidence showed all twelve non-terminal turns had responses and only the
terminal farewell was absent, despite the farewell appearing in console output.

## Acceptance Criteria

- Session close finalizes any buffered terminal agent text before dashboard
  shutdown.
- Final response coverage becomes N/N in the durable JSONL trace.
- Already-flushed output remains a no-op and cannot create duplicate evidence.
- Close ordering is flush, dashboard wait, server close, process exit.
- Full regression, adherence, spec, and scaffold checks pass.

## Non-Goals

- Synthesizing a response when no farewell text was produced.
- Recording non-terminal text through the terminal fallback.
- Extending dashboard lifetime beyond the bounded synchronization window.
