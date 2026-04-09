#!/usr/bin/env bash
        set -euo pipefail

        ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        cd "$ROOT_DIR"

        if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
          echo "Not a git repository: $ROOT_DIR" >&2
          exit 1
        fi

        if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
          echo "No commits found. Create an initial commit before creating worktrees." >&2
          exit 1
        fi

        mkdir -p .worktrees

        default_base_branch() {
          local remote_head
          remote_head="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
          if [[ -n "$remote_head" ]]; then
            echo "${remote_head#origin/}"
            return
          fi

          local current_branch
          current_branch="$(git branch --show-current)"
          if [[ -n "$current_branch" ]]; then
            echo "$current_branch"
            return
          fi

          echo "main"
        }

        BASE_BRANCH="$(default_base_branch)"

        create_worktree() {
          local name="$1"
          local branch="$2"
          local path=".worktrees/$name"

          if [ -d "$path" ]; then
            echo "exists: $path"
            return
          fi

          if git show-ref --verify --quiet "refs/heads/$branch"; then
            git worktree add "$path" "$branch"
          else
            git worktree add -b "$branch" "$path" "$BASE_BRANCH"
          fi
        }

        create_worktree "backend" "codex/agent-backend"
create_worktree "tests" "codex/agent-tests"

        echo
        echo "Base branch: $BASE_BRANCH"
        echo "Worktrees ready:"
        git worktree list
