#!/usr/bin/env bash
      set -euo pipefail

      ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
      cd "$ROOT_DIR"

      required_files=(
"README.md"
"AGENTS.md"
"agentic-repo.toml"
"CONTRIBUTING.md"
"SECURITY.md"
".github/CODEOWNERS"
".github/pull_request_template.md"
".github/workflows/ci.yml"
".github/workflows/codeql.yml"
".github/workflows/governance.yml"
".github/workflows/security.yml"
"docs/spec-driven-workflow.md"
"docs/agent-worktree-merge-flow.md"
"docs/level-5-agentic-engineering.md"
"specs/README.md"
"specs/changes/0001-baseline-scope.md"
"specs/changes/0002-level-5-operating-model.md"
"specs/system/rules.json"
"specs/governance/controls.json"
"contracts/interface.schema.json"
"specs/api/examples.json"
"agents/planner-agent.md"
"agents/review-agent.md"
"scripts/check-pr-governance.py"
"scripts/check-scaffold.sh"
"scripts/run-agents.sh"
"scripts/setup-worktrees.sh"
"pyproject.toml"
"scripts/generate-contract-artifacts.py"
"scripts/validate-specs.py"
"shared/__init__.py"
"shared/generated/__init__.py"
"shared/generated/interface_contract.py"
"agents/backend-agent.md"
"agents/test-agent.md"
      )

      required_dirs=(
        ".github/workflows"
        "contracts"
        "docs"
        "shared"
        "specs"
        "specs/changes"
        "specs/system"
        "specs/api"
        "specs/governance"
        "agents"
        "scripts"
      )

      missing=0
      for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
          echo "[missing] $file"
          missing=1
        fi
      done

      for dir in "${required_dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
          echo "[missing-dir] $dir"
          missing=1
        fi
      done

      shopt -s nullglob
      change_specs=(specs/changes/*.md)
      shopt -u nullglob
      if [[ "${#change_specs[@]}" -eq 0 ]]; then
        echo "[missing] specs/changes/*.md"
        missing=1
      fi

      if [[ "$missing" -ne 0 ]]; then
        echo "Scaffold policy failed: missing required files."
        exit 1
      fi

      echo "Scaffold policy check passed."
