#!/usr/bin/env bash
# Scenario 5 — "Did the decision's declared scope rot?" (decree health)  [keeping it honest over time]
#
# Months in: an implemented SPEC still claims it governs legacy_sso.py — but no
# commit that ever cited that SPEC touched that file. The map has become fiction.
# Meanwhile the SPEC's commits keep editing a helper it never declared.
source "$(dirname "$0")/_lib.sh"
make_demo_repo

banner "The corpus: a SPEC governing two files, with real trailer-linked history"
mkdir -p decree/spec src/auth
cat > decree/spec/spec-00000000000000000000000001-auth-login.md <<'EOF'
---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-10
governs:
  - src/auth/login.py
  - src/auth/legacy_sso.py
---

# SPEC-00000000000000000000000001 Auth login flow

## Overview

The login flow and its legacy SSO bridge.
EOF
printf 'v0\n' > src/auth/login.py
printf 'v0\n' > src/auth/legacy_sso.py
printf 'v0\n' > src/auth/helper.py
git add -A && git commit -qm "init: auth"

# Two commits that CITE the SPEC (Implements: trailer) and touch login.py +
# helper.py — but never legacy_sso.py. This is what `decree commit` writes.
printf 'v1\n' > src/auth/login.py; printf 'h1\n' > src/auth/helper.py
git commit -aqm "feat: harden login

Implements: SPEC-00000000000000000000000001"
printf 'v2\n' > src/auth/login.py; printf 'h2\n' > src/auth/helper.py
git commit -aqm "feat: login error handling

Implements: SPEC-00000000000000000000000001"
"$DECREE" index rebuild >/dev/null

banner "Health: declared scope no commit touched (a finding, exit 1) + scope the code grew into (advisory)"
dc health

value   "A decision's 'governs' list rots into fiction unnoticed → decree flags declared scope no trailer-linked commit ever touched (DEAD governance, exit 1) and, separately, scope the code grew into but never declared (SUGGESTED, advisory)."
honesty "Convention-bounded: the commit→decision link is the Implements: TRAILER convention, not a git guarantee — deterministic but not certain (needs 'decree commit' discipline)."
honesty "Asymmetry by design: DEAD is a finding (exit 1); SUGGESTED is advisory (exit 0, never feeds why()). A SPEC with zero trailered commits is reported 'unobserved, not dead' (fail-safe)."
