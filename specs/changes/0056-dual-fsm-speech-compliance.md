# Separate FSM adherence from spoken compliance

## Goal

Keep the live graph authoritative for deterministic FSM execution while showing
spoken-response compliance as a separate, compact evidence signal on the same
surface.

## Scope

- Compute structural FSM adherence independently from intent quality,
  conversational progress, and response wording.
- Validate each recorded non-terminal response against a small deterministic
  set of directive-critical rules.
- Expose cumulative `fsm_adherence` and `spoken_compliance` projections in the
  local dashboard state.
- Show independent FSM and speech verdicts above the graph.
- Show the latest turn's speech verdict on its active graph edge and in the
  transition trail.
- Render a temporary runtime edge, including a self-loop, when the executed
  transition is intentionally absent from the simplified business topology.
- Preserve the canonical graph, FSM behavior, polling cadence, and terminal
  speech implementation.

## Human Approval

The user explicitly approved this minimal dual-verdict design on 2026-07-11.
The change adds local dashboard state fields but does not alter the business FSM
or any external service contract.

## Acceptance Criteria

- A declared, continuous runtime transition reports `FSM PASS`, including
  declared fallback and self-loop transitions.
- Unknown, discontinuous, or target-inconsistent transitions report `FSM FAIL`.
- The latest executed transition is always visible, even when it is a fallback
  self-loop omitted from the simplified canonical graph.
- Spoken compliance reports `PASS`, `FAIL`, or `PENDING` independently of FSM
  adherence.
- Resolution language emitted while the directive requires recognition is a
  spoken-compliance failure.
- Premature action or outcome claims are spoken-compliance failures.
- The transition trail exposes the spoken verdict and its deterministic reason.
- Existing FSM execution, call controls, assessment evidence, and dashboard
  content remain intact.
- Focused tests, the full regression suite, JavaScript parsing, spec validation,
  and scaffold validation pass.

## Non-goals

- Changing intent classification or the business transition registry.
- Blocking or regenerating non-compliant speech in this change.
- Adding a probabilistic LLM judge to the live control path.
- Treating conversational progress or classifier accuracy as structural FSM
  adherence.
