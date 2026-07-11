# Change: Generic LangGraph Conversation FSM

## Goal

Add a case-agnostic finite-state machine for outbound collections calls. The
FSM runs outside the LLM, owns deterministic conversation transitions and
guards, and accepts customer and account details as runtime case context.

## Scope

- Use LangGraph's low-level `StateGraph` API only for FSM orchestration.
- Keep LiveKit responsible for STT, TTS, VAD, audio transport, and barge-in.
- Represent caller input as a typed turn event produced outside the FSM by an
  interpreter or deterministic application event.
- Keep client, customer, product, amount, currency, dates, and available
  resolutions in injected case context rather than graph topology or rules.
- Model opening, identity verification, case disclosure, recognition,
  objection handling, resolution, confirmation, escalation, and call end.
- Enforce privacy, refusal, unsupported-resolution, and termination rules with
  deterministic Python guards.
- Preserve the existing Al Corriente scenario as demo configuration and test
  data only; it must not be embedded in the generic FSM implementation.
- Add a framework-independent controller API that a later LiveKit turn hook and
  LLM intent interpreter can call without giving the LLM transition authority.

## Architecture Boundary

```text
LiveKit transcript -> turn interpreter -> LangGraph FSM -> response directive
LiveKit audio      <- LLM phrasing      <- validated state and case context
```

The interpreter may use an LLM to classify ambiguous language. It returns a
typed event and optional objection or resolution classification. LangGraph
validates that event, executes the transition, and emits a response directive.
The response model may phrase the directive but may not mutate graph state.

## Human Approval

The user explicitly approved on 2026-07-10 that LangGraph is used only for the
external-to-the-LLM FSM and that the FSM is generic rather than specific to the
Al Corriente case.

## Acceptance Criteria

- A compiled LangGraph `StateGraph` processes one typed event per invocation.
- The graph and its tests contain no Al Corriente, CloudX, or case-specific
  monetary values.
- Sensitive case phases cannot be entered until identity is verified.
- An explicit termination request ends the call from every phase.
- A wrong-party signal ends the call without case disclosure.
- The configured refusal limit ends the call deterministically.
- Human-help and vulnerability signals route to escalation.
- Only resolution types allowed by the injected case context can be selected.
- At least two unrelated case contexts can use the same compiled graph.
- State transitions and response directives are testable without audio or live
  OpenAI API calls.
- Existing repository tests and spec/scaffold validation continue to pass.

## Non-Goals

- Replacing LiveKit's voice pipeline or interruption controls.
- Letting an LLM choose or execute unvalidated state transitions.
- Implementing a production LLM intent classifier in this change.
- Migrating the current demo prompt or case-loading mechanism.
- Adding durable production checkpoint storage before its retention and data
  protection policy is approved.
