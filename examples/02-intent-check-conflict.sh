#!/usr/bin/env bash
# Scenario 2 — "Is my plan about to collide with a decision?" (decree intent-check)  [before you code]
#
# Before writing a line, an agent plans to change token refresh storage. Hidden
# from it: TWO decisions claim that file, and the in-flight one has open
# acceptance criteria. Decree surfaces it at planning time, not in code review.
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: two decisions claim the same file (one shipped, one in-flight)"
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

Tokens rotate on a schedule and old tokens are revoked.

## Acceptance Criteria

- [ ] Rotation job runs on schedule
- [ ] Old tokens revoked on rotation
EOF
echo "def store(token): ..." > src/auth/tokens.py
git add -A && git commit -qm "init: auth"
"$DECREE" index rebuild >/dev/null

banner "Check the plan BEFORE coding (exit 1 = a finding you can gate CI on)"
dc intent-check --plan "Change token refresh storage" --files src/auth/tokens.py

value   "Discover a two-decision collision in code review (late) → see it at planning time: the conflict, the in-flight SPEC, its unchecked acceptance criteria, and a non-zero exit."
honesty "intent-check reports the STRUCTURAL conflict (two decisions declare the path). It does NOT judge whether they truly contradict — that semantic call is the agent's/reviewer's job."
