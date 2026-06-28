# Change: Public Repository Structure

## Goal

Make the repository easier to understand as a reusable voice-agent project by
separating demo prompts, examples, and current change briefs.

## Scope

- Move the long collections prompt out of runtime configuration and into
  `prompts/`.
- Add `AGENT_INSTRUCTIONS_FILE` so examples can load prompt files without
  embedding long prompt text in `.env`.
- Add `examples/collections/` as the shareable demo entry point.
- Archive historical experiment notes that add noise to the public change list.
- Update README and tests to document the new structure.

## Acceptance Criteria

- `voice_agent/config.py` no longer embeds the full collections prompt.
- The default prompt still loads the MacroHard / Al Corriente S.L. / CloudX demo.
- `AGENT_INSTRUCTIONS` continues to override all prompt-file behavior.
- `AGENT_INSTRUCTIONS_FILE` can load a repo-relative prompt file.
- README points readers to `prompts/` and `examples/collections/`.
- Tests, spec validation, and scaffold validation pass.

## Non-Goals

- Changing the demo call flow.
- Removing the spec-first operating model.
- Creating a full plugin or package-data system for prompt distribution.
