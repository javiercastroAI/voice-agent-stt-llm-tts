# Change: Public Sharing Polish

## Goal

Prepare the repository for external sharing by removing internal, course, local
machine, and unrelated-domain references while preserving the fictional
collections demo scenario.

## Scope

- Public-facing README positioning and setup instructions.
- Package metadata.
- Demo scenario naming from the previous provider label to CloudX.
- Tests and change briefs that assert the demo scenario.
- Removal of unrelated healthcare call-center artifacts from the shareable
  working tree.

## Acceptance Criteria

- README describes the repository as a reusable voice-agent runtime, not as a
  notebook lesson wrapper.
- README contains no local absolute user paths.
- Package metadata references only the providers used by the runtime.
- The fictional demo case keeps MacroHard, Al Corriente S.L., CloudX, and the
  1.527 euro amount.
- Repository search no longer finds retired provider labels, unrelated
  healthcare-domain artifacts, lesson-wrapper language, stale third-party
  provider metadata, or local user-path references in shareable files.

## Non-Goals

- Rebranding the project with a final product name.
- Removing the spec-first operating model.
- Changing runtime defaults unrelated to public presentation.
