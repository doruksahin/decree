#!/usr/bin/env bash
# Scenario 4 — "Gate the diff on governance before human review" (decree intent-review)  [after you code]
#
# Code is written; a PR diff exists. Before a human reviews, does the diff touch
# files under contested or in-flight decisions? A deterministic, exit-coded pass.
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: same two decisions claiming src/auth/tokens.py"
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

Tokens are stored hashed at rest.
EOF
cat > decree/spec/spec-00000000000000000000000002-token-rotation.md <<'EOF'
---
id: SPEC-00000000000000000000000002
status: draft
date: 2026-05-10
governs:
  - src/auth/tokens.py
---

# SPEC-00000000000000000000000002 Token rotation policy

## Overview

Tokens rotate on a schedule.
EOF
echo "def store(token): ..." > src/auth/tokens.py
git add -A && git commit -qm "init: auth"
"$DECREE" index rebuild >/dev/null

banner "Make a change, then review the diff against governance (CI-shaped, exit 1)"
echo "def store(token): rotate()  # the change" > src/auth/tokens.py
git diff > change.diff
dc intent-review --diff change.diff

value   "Governance review that depends on a human remembering every decision → a build gate that fails when a diff collides with the decision corpus."
honesty "Reports structural intersection + conflict/stale findings; makes NO judgment about whether the change is correct. Exit 1 means 'a human/agent must look', not 'this is wrong'."
