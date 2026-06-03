#!/usr/bin/env bash
# Scenario 1 — "Why is this file the way it is?" (decree why)   [before you code]
#
# An engineer/agent is about to edit src/auth/tokens.py. Why are tokens hashed,
# not encrypted? The decision exists — but is it *attached* to the code?
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: one decision that governs the auth tokens file"
mkdir -p decree/spec src/auth
cat > decree/spec/spec-00000000000000000000000001-jwt-token-storage.md <<'EOF'
---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-10
governs:
  - src/auth/tokens.py
---

# SPEC-00000000000000000000000001 JWT token storage

## Overview

Access tokens are stored hashed at rest; the raw token never lands in the DB.
EOF
echo "def store(token): ..." > src/auth/tokens.py
echo "def charge(): ..."     > src/auth/charge.py   # deliberately ungoverned
git add -A && git commit -qm "init: auth"
"$DECREE" index rebuild >/dev/null

banner "Ask which decision governs the file you're about to touch"
dc why src/auth/tokens.py
dc why src/auth/tokens.py --json

banner "The honesty beat: a file no decision governs"
dc why src/auth/charge.py

value   "git blame + grep + Slack archaeology → one command that returns the exact governing decision."
honesty "why answers ONLY from declared 'governs:' frontmatter — never git, never semantic guessing."
honesty "An empty result is a valid abstention (exit 0), not a failure. decree won't invent a decision."
