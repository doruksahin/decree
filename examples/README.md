# decree, by example — pragmatic results

Six runnable scenarios. Each builds a throwaway git repo + decree corpus, runs
**real** `decree` commands, and prints the **real** output under a `VALUE:` line
(what you gain) and a `HONESTY:` line (where decree refuses to overclaim). Nothing
here is mocked.

```bash
bash examples/run-all.sh                              # uses `decree` on PATH
DECREE="$PWD/.venv/bin/decree" bash examples/run-all.sh   # from a local checkout
bash examples/05-health-dead-governance.sh           # or one at a time
```

## The arc: before → while → after → over time

decree answers one question across the life of a change — *"which decision
explains this code, and is my change still aligned?"*

| # | When | Command | The question it answers | What decree prints | Exit |
|---|------|---------|--------------------------|--------------------|------|
| 1 | before you code | `decree why <file>` | "Why is this file the way it is?" | `tokens.py — 1 governing decision ▸ SPEC-…01 (JWT token storage)`; an ungoverned file → `no governing decisions` (abstention) | 0 |
| 2 | before you code | `decree intent-check --plan … --files …` | "Will my plan collide with a decision?" | a **conflict** (two SPECs claim `tokens.py`) + the in-flight SPEC's **unchecked acceptance criteria** | **1** |
| 3 | while you code (parallel) | `decree intent-check … --other-active-files …` | "Is another agent about to touch this file?" | `isolate_session: src/auth/tokens.py is also planned by session-b` | **1** |
| 4 | after you code | `decree intent-review --diff …` | "Does this diff collide with governance?" | `Conflicts (1): ✗ src/auth/tokens.py: SPEC-…01, SPEC-…02` | **1** |
| 5 | over time | `decree health` | "Did the decision's declared scope rot?" | **Dead governance**: `src/auth/legacy_sso.py` (declared, never touched) + **Suggested** (advisory): `src/auth/helper.py (touched in 2 commits)` | **1** |
| 6 | while you code (governed) | `decree intent-check --under <decision>` | "Am I editing a file my decision doesn't own?" | `declare_governs [SPEC-…01]: commits repeat-touch src/auth/helper.py, not in its governs:` | 0 |

**Exit codes are the contract:** `1` = a finding you can gate CI on (conflict,
live overlap, dead governance); `0` = clean *or* advisory-only (suggestions never
block); `2` = config error (e.g. an unknown `--under` id).

## Why each ends on a HONESTY line — that's the pitch

decree is trustworthy *because* it refuses to overclaim:

- `why` / `intent-check` / `intent-review` answer **only from declared `governs:`** — never git, never semantic guessing. An empty result is a **valid abstention**, not a failure (Scenarios 1–4, 6).
- decree reports **structural** conflicts/overlaps; whether a change is *actually OK* is the human's/agent's call — decree does **no semantic judgment** (Scenarios 2–4).
- the git-derived health signals are **advisory and convention-bounded** — deterministic computation over the `Implements:` *trailer convention*, not certainty; they need `decree commit` trailer discipline. **Dead governance is a finding; suggested governance is advisory and never feeds `why()`** (Scenarios 5–6). See [../docs/provenance-model.md](../docs/provenance-model.md) and [../docs/health-signals.md](../docs/health-signals.md).

## Notes for reproducibility

Scenarios hand-author docs with **pinned IDs** (`SPEC-0000…01`) rather than
`decree new` (which mints a random ULID + today's date), so the structural output
is stable across runs. The only non-deterministic lines are git-derived
timestamps (`observed as of …`), which the pitch never relies on.
