#!/usr/bin/env bash
# Scenario 6 — "You keep editing a file your decision doesn't own"  [while you code, governed]
# (decree intent-check --under)
#
# An agent in a GOVERNED session works under SPEC-…0001. It plans to edit a helper
# its decision's commits keep touching — but the decision never declared it. At
# the moment of the edit, decree nudges: "consider declaring this." The
# point-of-change counterpart to Scenario 5's batch audit.
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: SPEC-…0001's own commits repeat-touch a helper it never declares"
mkdir -p decree/spec src/auth
cat > decree/spec/spec-00000000000000000000000001-auth-login.md <<'EOF'
---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-10
governs:
  - src/auth/login.py
---

# SPEC-00000000000000000000000001 Auth login flow

## Overview

The login flow. Declares only login.py — note it does NOT declare helper.py.
EOF
printf 'v0\n' > src/auth/login.py
printf 'v0\n' > src/auth/helper.py
git add -A && git commit -qm "init: auth"
printf 'v1\n' > src/auth/login.py; printf 'h1\n' > src/auth/helper.py
git commit -aqm "feat: harden login

Implements: SPEC-00000000000000000000000001"
printf 'v2\n' > src/auth/login.py; printf 'h2\n' > src/auth/helper.py
git commit -aqm "feat: login error handling

Implements: SPEC-00000000000000000000000001"
"$DECREE" index rebuild >/dev/null

banner "In a governed session under SPEC-…0001, planning to edit the helper (advisory, exit 0)"
dc intent-check --plan "edit auth helper" --files src/auth/helper.py \
  --under SPEC-00000000000000000000000001

value   "Governance scope drifts and you catch it in a quarterly audit → 'this file is yours in practice but undeclared' surfaces at the exact moment you touch it."
honesty "Advisory by construction: declare_governs NEVER blocks (exit stays 0) and NEVER feeds why() — it is not a governance fact until a human adds it to 'governs:'. Squash-immune (needs commit_count >= 2)."
