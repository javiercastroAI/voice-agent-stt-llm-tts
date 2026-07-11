# Change: Conversation Control Room UI

## Goal

Recompose the live console as a precise, dark operational workspace in which
the transcript and deterministic FSM read as synchronized views of one event
stream.

## Visual Thesis

The console is a scientific instrument: graphite surfaces, warm off-white
type, luminous teal for live signal, amber for guarded or waiting states, and
red only for failures. The executable FSM graph is the visual signature.

## Content Plan

- Start with a persistent command header containing product identity,
  connection presence, user state, agent state, barge-in state, and refresh
  cadence.
- Place the live transcript and FSM monitor together in the primary viewport,
  with the FSM occupying the larger desktop column and appearing first on
  narrow screens.
- Express the causal chain as intent, guard, transition, directive, and spoken
  verdict without duplicating the underlying state payload.
- Move assessment, metrics, model metadata, and technologies into a secondary
  evidence workspace below the live surface, while presenting research
  provenance in the persistent command header.

## Interaction Thesis

- Animate the active FSM route as a short signal pulse when a transition is
  observed.
- Give listening, thinking, and speaking distinct low-amplitude presence
  signals.
- Reveal terminal assessment state with a brief settling transition, while
  disabling all nonessential movement for reduced-motion users.

## Scope

- Replace the marketing-style hero and light card presentation with a dark,
  cardless control-room composition.
- Preserve every required DOM identifier and the complete `/api/state`
  contract.
- Preserve the 350 ms polling cadence, render fingerprints, graph topology,
  transcript behavior, metrics, assessment, and compliance semantics.
- Improve first-viewport density, evidence hierarchy, graph prominence,
  transcript readability, keyboard focus, and responsive behavior.
- Present `RESEARCH PROVENANCE`, `Javier Castro`, `DNAI`, and `2026` together
  in the persistent command header; do not duplicate that provenance at the
  bottom of the page.

## Human Approval

The user explicitly requested implementation of the award-level console
redesign and required it to remain reversible on a dedicated branch on
2026-07-11.

## Acceptance Criteria

- A viewer can identify the active speaker, current FSM phase, latest causal
  transition, and structural/spoken verdicts within three seconds.
- Research provenance appears at the top of the console, above the product
  name, and does not appear in the secondary evidence workspace.
- Desktop widths show transcript at roughly 40 percent and FSM at roughly 60
  percent in one synchronized primary workspace.
- At 390 px width the FSM precedes the transcript, the graph remains legible,
  labels do not clip, and no horizontal page scrolling occurs.
- Transcript entries use an editorial evidence stream rather than chat
  bubbles, while diarized segments and live text remain visible.
- Empty, active, guarded, failed, finalizing, passed, and terminal states have
  intentional presentations with color used only for operational meaning.
- Active-route, presence, and terminal motion are restrained and disabled by
  `prefers-reduced-motion`.
- All existing UI contract IDs, API fields, polling behavior, and regression
  tests remain valid.

## Non-Goals

- Changes to voice behavior, FSM transitions, intent interpretation, runtime
  payloads, telemetry persistence, or call controls.
- Introduction of a frontend framework, package manager, external font, or
  asset pipeline.
- New operator actions, filters, or mutable dashboard state.
