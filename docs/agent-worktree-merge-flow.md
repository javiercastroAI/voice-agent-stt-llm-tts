# Agent Worktree Merge Flow

        This scaffold treats worktree isolation as the default parallel-delivery path.

        ## Worktree Layout

        - `.worktrees/backend` -> branch `codex/agent-backend`
- `.worktrees/tests` -> branch `codex/agent-tests`

        ## Practical Sequence

        1. Start from the integration branch you want to extend.
        2. Create one worktree per delivery agent with `./scripts/setup-worktrees.sh`.
        3. Run the delivery commands from isolated folders with `./scripts/run-agents.sh`.
        4. Commit each agent's output on its own `codex/agent-*` branch.
        5. Merge those branches back together after validation.

        ## Example Merge Commands

        ```bash
        git switch -c codex/integration
        git merge codex/agent-backend
git merge codex/agent-tests
        ```
