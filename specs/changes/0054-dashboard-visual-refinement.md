# Change: Dashboard Visual Refinement

## Goal

Raise the visual quality of the live call dashboard without changing its
runtime behavior, data contract, polling cadence, FSM semantics, or call
controls.

## Scope

- Replace the warm, decorative presentation with a cohesive dark operational
  workspace.
- Strengthen hierarchy through typography, spacing, alignment, and restrained
  use of a single cyan signal color.
- Present status, assessment, FSM evidence, metrics, and transcript as one
  consistent interface rather than a collection of unrelated cards.
- Improve desktop density and small-screen responsiveness.
- Preserve a static FSM monitor between actual FSM data changes.
- Add only restrained entrance and affordance motion, with reduced-motion
  support.

## Human Approval

The user explicitly requested a visual-presence and UI-quality improvement on
2026-07-11, with no functionality changes.

## Acceptance Criteria

- All required UI element IDs and API state fields remain unchanged.
- The 350 ms polling loop, render fingerprints, FSM rendering behavior, and
  end-of-call assessment logic remain unchanged.
- The page has a coherent operational-console visual language at desktop and
  mobile widths.
- Live state, pass, warning, and failure conditions remain visually distinct.
- Keyboard focus is visible and motion is disabled when the operating system
  requests reduced motion.
- Existing web, spec, scaffold, and regression tests pass.

## Non-Goals

- New controls, filters, views, metrics, or interactions.
- Changes to call orchestration, FSM transitions, adherence assessment, or
  voice behavior.
- Changes to API payloads or persistence.
