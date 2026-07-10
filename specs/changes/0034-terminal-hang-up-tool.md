# Change: Terminal Hang-up Tool and Resource Release

## Goal

End every logically completed call with an explicit hang-up tool call that
releases call-scoped audio, microphone, session, room, dashboard, and worker
resources after the final farewell has played.

## Scope

- Register LiveKit's end-call lifecycle as an agent tool.
- Permit the tool to execute only after the external FSM has set `should_end`.
- Tell the speaking model to call `end_call` as the terminal action instead of
  continuing the conversation or asking another question.
- Let the tool produce one short farewell, wait for its playout, shut down the
  agent session, and delete the production room so remote/SIP participants are
  disconnected.
- Retain the deterministic agent-state shutdown path as a fallback when the
  model does not issue the required tool call.
- Close the local transcript server from the existing session-close handler.

## Human Approval

The user explicitly requested terminal hang-up tool execution and complete call
resource release on 2026-07-10.

## Acceptance Criteria

- `end_call` is exposed to the speaking LLM as a function tool.
- Calling `end_call` before `should_end` raises a tool error and does not start
  shutdown.
- Terminal runtime control requires `end_call` and forbids further questions.
- A valid tool call owns shutdown and suppresses duplicate fallback shutdown.
- If no tool call occurs, the lifecycle fallback still shuts down once after
  the terminal farewell.
- Production hang-up deletes the LiveKit room; session close releases local
  audio and closes the transcript server.
- Local console calls skip room deletion because they have no remote/SIP room,
  while still shutting down the audio session and transcript server.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Allowing the LLM to decide independently that a non-terminal FSM state is
  complete.
- Replacing explicit termination, privacy, or resolution guards in the FSM.
