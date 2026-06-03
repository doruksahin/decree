# Shared boilerplate for the decree demo scenarios. Sourced by each scenario;
# the *story* (corpus, git history, commands) stays inline in each scenario so a
# reader sees the whole thing top-to-bottom. This file is only the un-interesting
# setup + the one demo helper — deliberately small, no DSL, no framework.
#
# Override the binary for local checkout testing:
#   DECREE="$PWD/.venv/bin/decree" bash examples/01-why.sh
set -uo pipefail
DECREE="${DECREE:-decree}"

# A throwaway git repo + decree project in a temp dir, removed on exit. Git
# identity + gpgsign-off are required or commits fail in clean environments.
make_demo_repo() {
  TMP="$(mktemp -d)" || exit 1
  trap 'rm -rf "$TMP"' EXIT
  cd "$TMP" || exit 1
  git init -q
  git config user.email demo@example.com
  git config user.name "Decree Demo"
  git config commit.gpgsign false
  cat > decree.toml <<'TOML'
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
TOML
}

# dc <args…> — run a decree command for the demo: echo it prettily (as `decree …`,
# never the absolute binary path), let its REAL output through, and print its REAL
# exit code. decree's findings exit 1 and config errors exit 2 — those are the
# story, not failures — so a non-zero exit must NOT abort the demo.
dc() {
  printf '\n\033[1;36m$ decree %s\033[0m\n' "$*"
  "$DECREE" "$@"
  printf '\033[2m→ exit %d\033[0m\n' "$?"
}

banner()  { printf '\n\033[1m── %s ──\033[0m\n' "$*"; }
value()   { printf '\033[1;32mVALUE:\033[0m   %s\n' "$*"; }
honesty() { printf '\033[1;33mHONESTY:\033[0m %s\n' "$*"; }
