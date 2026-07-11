# Change: Automatic Outbound Opening and Terminal Shutdown

## Goal

Make the outbound voice agent initiate the conversation automatically from the
FSM's disclosure-safe opening directive, and close the session once a terminal
farewell has finished playing.

## Scope

- Use LiveKit's `Agent.on_enter` lifecycle hook to schedule the opening reply.
- Generate the opening from the controller's current FSM response context.
- Keep the opening interruptible so normal barge-in behavior still applies.
- Make automatic opening configurable with `FSM_AUTO_OPENING_ENABLED` and
  enable it by default for this outbound runtime.
- Prevent duplicate opening generation if `on_enter` is invoked more than once
  for the same agent instance.
- Reset duplicate protection if scheduling the opening raises, allowing the
  framework to retry activation safely.
- After the FSM reaches `ended`, request a one-shot graceful session shutdown
  when the agent transitions out of speaking after the farewell.

## Human Approval

The user explicitly approved automatic outbound opening and bounded quick-fix
improvements on 2026-07-10.

## Acceptance Criteria

- An FSM-enabled outbound agent calls `generate_reply` from `on_enter` with the
  disclosure-safe `open_and_verify_identity` directive.
- The opening request explicitly allows interruptions.
- The opening control message contains no customer, product, amount, reference,
  disclosure summary, or internal metadata.
- Repeated `on_enter` calls schedule exactly one opening.
- A scheduling exception leaves the opening eligible for a later retry.
- Disabling automatic opening preserves user-first behavior.
- An ended call requests graceful shutdown once, only after agent speech ends.
- Non-terminal state changes do not request shutdown.
- Existing tests, new regressions, and governance validation pass.

## Non-Goals

- Writing a fixed recorded greeting that bypasses the speaking LLM.
- Disabling interruption during the opening or farewell.
- Changing telephony routing or adding warm-transfer behavior.
