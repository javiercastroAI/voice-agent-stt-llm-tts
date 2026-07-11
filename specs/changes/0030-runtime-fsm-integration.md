# Change: Runtime FSM Integration

## Goal

Connect the generic LangGraph conversation FSM to the active LiveKit agent with
a validated runtime case loader, a typed OpenAI intent interpreter, and the
`on_user_turn_completed` lifecycle hook.

## Scope

- Load case-specific data from a JSON file selected by `CASE_CONTEXT_FILE`.
- Validate case JSON before constructing the voice agent.
- Keep the system prompt case-agnostic and provide case details only through
  the FSM's disclosure-aware response context.
- Classify completed caller transcripts into the existing `TurnEvent` schema
  with OpenAI Structured Outputs and a Pydantic response model.
- Send the interpreter only the caller transcript, current phase, and allowed
  resolution labels; do not send the full case record.
- Advance the FSM before the speaking LLM generates its response.
- Inject one ephemeral system control message into the LiveKit turn context;
  do not persist stale FSM directives into later turns.
- Keep LiveKit responsible for audio, STT, TTS, VAD, and barge-in.
- Support dependency injection so the hook, controller, and interpreter remain
  deterministic in tests without live API requests.

## Failure Behavior

- Invalid or missing case JSON fails startup with a configuration error.
- Empty transcripts do not invoke the interpreter or speaking LLM.
- A structured-output failure, API error, or timeout produces an `unknown`
  event and retains the current safe phase.
- Explicit Spanish or English termination phrases are detected locally before
  the API call so an interpreter outage cannot cause continued persuasion.
- The LLM may classify intent and phrase a response, but only LangGraph may
  mutate call state.

## Human Approval

The user explicitly approved this integration layer on 2026-07-10 after
approving the generic external-to-the-LLM FSM architecture.

## Acceptance Criteria

- Two unrelated valid case JSON files load into the same runtime model.
- Unknown, malformed, and case-incompatible fields are rejected.
- The intent response schema permits only declared FSM intents.
- Interpreter inputs contain no customer name, amount, reference, product, or
  disclosure summary.
- Interpreter output is converted to a validated `TurnEvent`.
- Interpreter errors fail closed to `unknown` without raising into LiveKit.
- Explicit termination remains deterministic when the OpenAI call fails.
- `on_user_turn_completed` advances the FSM and adds a current-turn-only system
  message containing the validated directive and disclosure-safe context.
- The default demo uses a case JSON fixture rather than embedding case values
  in the generic system prompt.
- Existing tests, new integration tests, and repository governance checks pass.

## Non-Goals

- Durable production checkpoint storage.
- Replacing the speaking LLM with LangGraph.
- Closing telephony transport immediately after the farewell audio completes.
- Persisting raw interpreter prompts or caller transcripts as new telemetry.
