#!/usr/bin/env bash
# Scenario 3 — "Is another agent about to touch this same file?"  [while you code, in parallel]
# (decree intent-check --other-active-files)
#
# Two agent sessions run in parallel. Both independently plan to write the same
# file. Neither knows about the other → silent clobber. Decree, given the other
# live session's planned paths, flags the live overlap now.
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: one decision governing the contested file"
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
echo "def store(token): ..." > src/auth/tokens.py
git add -A && git commit -qm "init: auth"
"$DECREE" index rebuild >/dev/null

banner "This session plans tokens.py — we tell decree session-b also plans it"
dc intent-check --plan "Edit token storage" --files src/auth/tokens.py \
  --other-active-files '{"session-b": ["src/auth/tokens.py"]}'

value   "Two parallel agents edit the same file blind and you reconcile the wreck later → the live collision is flagged before either starts, with an 'isolate_session' recommendation (exit 1)."
honesty "decree owns NO session state. The caller supplies the other sessions' planned paths; decree only computes the overlap. It reports THAT two sessions claim the file, not who should win."
