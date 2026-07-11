# Change: Live Call Adherence Verdict

## Goal

Make the dashboard state plainly whether a completed call was satisfactory
according to deterministic script adherence and successful FSM completion, and
show actionable improvement opportunities when it was not.

## Scope

- Evaluate the minimized live FSM trace against the runtime case definition.
- Add a summary-first call assessment panel above the detailed FSM monitor.
- Keep the verdict deterministic; do not use an LLM judge for compliance.
- Distinguish `in_progress`, `finalizing`, `pass`, `warn`, and `fail` states.
- Mark a call satisfactory only when the FSM reaches `ended`, `should_end` is
  true, the terminal assistant response is recorded, and trace adherence passes.
- Show terminal-state, response-evidence, and script-adherence checks.
- Translate deterministic findings into concise improvement actions.
- Preserve the final verdict in the browser while call resources shut down.

## Source And Metric Definitions

- Source: `FSMTraceRecorder` transition and assistant-response events projected
  into `TranscriptStore`.
- FSM completion: latest phase is `ended` and `should_end=true`.
- Response coverage: correlated assistant responses divided by FSM transitions.
- Script adherence: `evaluate_trace` using the active, validated case context.
- Satisfactory: terminal FSM, complete terminal evidence, and adherence `pass`.

## Human Approval

The user explicitly requested a clear end-of-call satisfaction verdict and
visible improvement recommendations on the dashboard on 2026-07-10.

## Acceptance Criteria

- The API snapshot exposes a structured `call_assessment` object.
- Non-terminal calls never display a completed pass or fail verdict.
- A terminal transition waits for its correlated final response before scoring.
- Deterministic pass displays `Satisfactory`; warning displays `Needs review`;
  failure displays `Unsatisfactory`.
- The panel shows the evidence denominator and improvement actions.
- The assessment panel updates only when its source payload changes and has no
  animation or polling flicker.
- Desktop and narrow layouts remain readable.
- Unit, adherence, spec, and scaffold checks pass.

## Non-Goals

- Using an LLM judge for privacy, transition, or terminal compliance.
- Replacing the detailed FSM transition monitor.
- Persisting dashboards after the local console process exits.
- Adding case-specific Al Corriente behavior to the generic FSM.
