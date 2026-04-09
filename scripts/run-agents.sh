#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_MODE="worktrees"

usage() {
  cat <<'EOF'
Usage: ./scripts/run-agents.sh [options]

Options:
  --worktrees   Run commands from .worktrees/* branches (default and recommended).
  --root        Run commands from this checkout instead of isolated worktrees.
  -h, --help    Show this help.
EOF
}

while (($# > 0)); do
  case "$1" in
    --worktrees)
      RUN_MODE="worktrees"
      shift
      ;;
    --root)
      RUN_MODE="root"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ "$RUN_MODE" = "worktrees" ]; then
  for wt in "./.worktrees/backend" "./.worktrees/tests"; do
    if [ ! -d "$wt" ]; then
      echo "Missing $wt. Run ./scripts/setup-worktrees.sh first." >&2
      exit 1
    fi
  done
else
  echo "Root mode bypasses worktree isolation. Use only for deliberate single-branch work." >&2
fi

PIDS=()
STATUS_FILE="$(mktemp "${TMPDIR:-/tmp}/bootstrap-agents-status.XXXXXX")"

cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  wait >/dev/null 2>&1 || true
  rm -f "$STATUS_FILE"
}

trap cleanup EXIT INT TERM

start_agent() {
  local label="$1"
  local worktree="$2"
  local command="$3"

  (
    cd "$worktree"
    set +e
    bash -lc "$command" 2>&1 | while IFS= read -r line; do
      printf '[%s] %s\n' "$label" "$line"
    done
    code=${PIPESTATUS[0]}
    set -e
    printf '%s:%s\n' "$label" "$code" >> "$STATUS_FILE"
  ) &
  PIDS+=("$!")
}

if [ "$RUN_MODE" = "worktrees" ]; then
  BACKEND_DIR="$ROOT_DIR/.worktrees/backend"
  UI_DIR="$ROOT_DIR/.worktrees/ui"
  TESTS_DIR="$ROOT_DIR/.worktrees/tests"
else
  BACKEND_DIR="$ROOT_DIR"
  UI_DIR="$ROOT_DIR"
  TESTS_DIR="$ROOT_DIR"
fi

start_agent "backend" "$BACKEND_DIR" "python3 -m backend.app"
start_agent "tests" "$TESTS_DIR" "python3 -m unittest discover -s tests -p 'test_*.py'"

echo "Agents running from $RUN_MODE mode. Press Ctrl+C to stop all."

while true; do
  if [ -s "$STATUS_FILE" ]; then
    IFS=":" read -r EXIT_LABEL EXIT_CODE < "$STATUS_FILE"
    break
  fi
  sleep 1
done

if [ "$EXIT_CODE" -ne 0 ]; then
  echo "$EXIT_LABEL agent exited with code $EXIT_CODE. Stopping all."
fi

exit "$EXIT_CODE"
