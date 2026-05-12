#!/usr/bin/env bash
# decree-ddd-stop.sh
#
# Claude Code Stop hook. Runs `decree ddd --quiet` and writes the output to
# a snapshot file that the next Claude Code session can read at startup.
#
# Installed by `decree hook install --type=claude-stop`. Safe to run from
# anywhere — if no decree.toml is found upward from cwd, exits silently.

set -euo pipefail

# Locate the enclosing decree project (walks upward looking for decree.toml).
# Exits 0 silently if decree is not installed or not in a decree project.
if ! command -v decree >/dev/null 2>&1; then
  exit 0
fi

if ! PROJECT_ROOT="$(decree find-root 2>/dev/null)"; then
  exit 0
fi

# Build a deterministic snapshot location per project.
# Hash the project root path so projects with similar names don't collide.
if command -v shasum >/dev/null 2>&1; then
  PROJECT_HASH="$(printf '%s' "$PROJECT_ROOT" | shasum -a 256 | cut -c1-16)"
elif command -v sha256sum >/dev/null 2>&1; then
  PROJECT_HASH="$(printf '%s' "$PROJECT_ROOT" | sha256sum | cut -c1-16)"
else
  # Fallback: use the basename + length as a poor man's hash
  PROJECT_HASH="$(basename "$PROJECT_ROOT")-${#PROJECT_ROOT}"
fi

SNAPSHOT_DIR="${HOME}/.claude/projects/${PROJECT_HASH}"
SNAPSHOT_FILE="${SNAPSHOT_DIR}/decree-ddd-snapshot.md"

mkdir -p "$SNAPSHOT_DIR"

# Run the assessment and write the snapshot. We intentionally swallow non-zero
# exit codes — the hook is informational, not a gate.
{
  printf '# decree ddd snapshot — %s\n\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  printf '_Project: %s_\n\n' "$PROJECT_ROOT"
  printf '```\n'
  decree ddd --quiet --project "$PROJECT_ROOT" 2>&1 || true
  printf '```\n'
} > "$SNAPSHOT_FILE" 2>/dev/null || true

exit 0
