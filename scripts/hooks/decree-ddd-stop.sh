#!/usr/bin/env bash
# decree-ddd-stop.sh
#
# Claude Code Stop hook. Runs `decree ddd --quiet` and writes the output to
# a snapshot file that the next Claude Code session can read at startup.
#
# Installed by `decree hook install --type=claude-stop`. Safe to run from
# anywhere. Outside a decree project it no-ops with exit 0 by default; set
# DECREE_HOOK_DEBUG=1 to print skip reasons to stderr.

set -euo pipefail

debug() {
  if [[ "${DECREE_HOOK_DEBUG:-}" == "1" ]]; then
    printf '[decree hook] %s\n' "$*" >&2
  fi
}

# Locate the enclosing decree project (walks upward looking for decree.toml).
# Exits 0 because the hook is informational, not a gate.
if ! command -v decree >/dev/null 2>&1; then
  debug "decree command not found; skipping stop-hook snapshot"
  exit 0
fi

if ! PROJECT_ROOT="$(decree find-root 2>/dev/null)"; then
  debug "no decree.toml found upward from cwd; skipping stop-hook snapshot"
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

# Run the assessment and write the snapshot. We intentionally turn non-zero
# decree ddd results into snapshot content because the hook is informational.
if ! {
  printf '# decree ddd snapshot — %s\n\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  printf '_Project: %s_\n\n' "$PROJECT_ROOT"
  printf '```\n'
  decree ddd --quiet --project "$PROJECT_ROOT" 2>&1 || true
  printf '```\n'
} > "$SNAPSHOT_FILE" 2>/dev/null; then
  debug "failed to write stop-hook snapshot to ${SNAPSHOT_FILE}"
fi

exit 0
