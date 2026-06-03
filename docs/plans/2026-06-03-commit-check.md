# `decree commit-check` — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a deterministic command that reports — and can gate CI on — the **trailer coverage** of a change: of the files a diff touches that are governed by an *in-flight* decision, how many carry a matching `Implements:/Refs:/Fixes:` trailer linking the commit to that decision. Close decree's named weak link (commit→decision is convention, not guarantee) with an *honest, gateable coverage signal* — not an overclaimed "guarantee."

**Architecture (validated by two maintainer reviews — see Design below):**
- A new read-only command `decree commit-check`, sibling to `intent-check`/`intent-review`, with the **same exit-code contract** (0 clean / 1 finding / 2 config error) and `--json`.
- Reads **only the authoritative declared `governs:` layer** via `queries.why()` — *never* `observed_governs`/`commits`-as-truth, never an LLM. Writes nothing.
- Primary mode is **CI on the net diff** (`--diff-base origin/main`): trailers gathered from the commit range, so it **survives squash-merge** (the local per-commit message does not). A secondary **candidate-message mode** (`--message FILE`) supports an *opt-in* local `commit-msg`/`pre-commit` hook the user/harness wires up.
- Advisory by default (exit 0 + report); opt-in **`--strict`** (require 100%) or **`--min-coverage N`** (ratchet) flips uncovered changes to exit 1.

**Tech Stack:** Python 3.11+, argparse CLI, the existing SQLite index (`IndexDB`), `git interpret-trailers`, pytest. No new dependencies, no schema change.

---

## Design (the validated shape — read before coding)

**What it is.** Given a diff, compute the set of *governed changes* = `(path, decision)` pairs where `decision` is **in-flight** (`_status_priority(type, status) == 1`, mirroring `commit.infer_active_spec`) and declares `governs:` over `path` (via `queries.why()`). A pair is **covered** when a matching `Implements:/Refs:/Fixes: <decision-id>` trailer is present in the relevant message(s). Output the coverage fraction, the uncovered pairs, and an exit code.

**Two input modes (one command):**
| Mode | Paths from | Trailers from | Use |
|---|---|---|---|
| `--diff-base REF` (CI, primary) | `git diff REF...HEAD` (`_read_diff_source`) | union of `Implements:/Refs:/Fixes:` across commits in `REF..HEAD` | a PR check that survives squash |
| `--diff PATH` / `--diff -` | the supplied unified diff | requires `--message` | piped diffs |
| `--message FILE` (+ staged) | staged (`_read_diff_source` default) | the candidate commit message file | opt-in local `commit-msg` hook |

**Exit codes (match intent-check/review):** `0` clean *or* advisory-only (no `--strict`); `1` a finding (uncovered governed change, under `--strict`/`--min-coverage`); `2` config error (no index, bad `--project`, unreadable message, missing required input).

**Honesty (non-negotiable — this is decree's brand).** Describe it as **"trailer coverage you can gate,"** never "a guarantee" or "from convention toward a guarantee." `--no-verify` and CI overrides exist; the tool *measures and gates where you run it*, it cannot make the link true. Docs must say so, mirroring the dead-governance honesty language.

**Strictly orthogonal to tickets.** decree never reads/maps `PROJ-123`, Gerrit `Change-Id`, or Conventional-Commits subjects. The trailer is a bottom line (`git interpret-trailers`) that coexists with all of them. A ticket ≠ a decision — state this in the docs.

**Scope IN (full v1):** the command (both modes), report + `--strict` + `--min-coverage` + `--json` + `--project`; the MCP `commit_check` tool; the CI recipe; docs; a Towncrier fragment; dogfood ADR+SPEC.

**Explicitly DEFERRED (do NOT build in v1 — record as future work):**
- A core git-hook *installer* in `hook.py` (there is no git-hook mechanism today; it's net-new plumbing and is "the harness's responsibility" per provenance-model.md). Ship instead a **documented** opt-in hook snippet that calls `decree commit-check --message "$1" --strict`.
- Surfacing coverage in `health`/`ddd` (different scope — corpus-wide drift vs a diff). Future.
- Any ticket→decision mapping or LLM inference. Never.

---

## Phase 0 — Dogfood: record the decision in decree itself

### Task 0.1: Write the ADR (the design decision)

`decree new adr "Commit-check as a CI coverage gate, not a commit-msg guarantee"`, then fill it: context (the convention weak link); decision (CI net-diff coverage gate, advisory + `--strict`/`--min-coverage`, reads declared layer only); rejected alternatives (local `commit-msg` hard block — squash-merge destroys it + false-positive friction; calling it a "guarantee" — overclaims past `--no-verify`; ticket→decision mapping — orthogonal); consequences. Reference the relevant PRDs if any.

**Gate:** `decree lint` clean. Commit: `docs: ADR for commit-check coverage gate`.

### Task 0.2: Write the SPEC (the blueprint + acceptance criteria)

`decree new spec "Trailer-coverage gate (decree commit-check)"`, references the ADR, `governs: [src/decree/commands/commit_check.py, src/decree/commands/mcp_server.py]`. Its **Acceptance Criteria** mirror the Phase 1–4 tasks below (each task = one checkbox). This is the trackable plan (`decree progress`).

**Gate:** `decree lint` clean. Commit: `docs: SPEC for commit-check`. Use `decree commit --implements <SPEC>` so this dogfoods the very link the feature checks.

---

## Phase 1 — Core library (`src/decree/commands/commit_check.py`), TDD

Pure functions first; no argparse/IO coupling. New test file `tests/test_commit_check.py` (reuse the `git_project` fixture from `tests/test_commit.py`).

### Task 1.1: `governed_changes(db, paths)` — the in-flight governed (path, decision) set

**Step 1 — failing test:** with a corpus where an **approved** SPEC governs `src/auth/tokens.py` and an **implemented** (terminal) SPEC governs `src/legacy.py`, assert `governed_changes(db, ["src/auth/tokens.py","src/legacy.py","src/other.py"])` returns only the `(tokens.py, SPEC-approved)` pair (in-flight only; terminal and ungoverned excluded).
**Step 2:** run → fails (function missing).
**Step 3 — implement:** for each path call `queries.why(db, path)`; keep decisions with `_status_priority(gd.type, gd.status) == 1`; return `list[GovernedChange(path, decision_id, type, title)]`. Import `why`, `_status_priority` from `queries`.
**Step 4:** test passes.
**Step 5:** commit `feat: commit_check.governed_changes (in-flight declared governance)`.

### Task 1.2: `trailer_ids(message_text)` — parse decision IDs from a message

**Test:** a message with `Implements: SPEC-A`, `Refs: SPEC-B`, `Fixes: SPEC-C`, and `Implements: SPEC-D, SPEC-E` (multi-value) → `{A,B,C,D,E}`; a message with none → `set()`. (Reuse the **canonical** parser: shell out to `git interpret-trailers --parse`, the same one `index_db.sync_commits_from_git` uses — never a Python regex reimplementation.)
**Implement → pass → commit** `feat: commit_check.trailer_ids via git interpret-trailers`.

### Task 1.3: `range_trailer_ids(repo, ref)` — union of trailers across `REF..HEAD`

**Test:** two commits in `REF..HEAD`, one carrying `Implements: SPEC-A`, the other none → `{A}`. (Implementation: `git log --format=%B REF..HEAD` piped through `trailer_ids`, or per-commit; pick the deterministic one and test ordering-independence.)
**Implement → pass → commit.**

### Task 1.4: `coverage(governed, trailer_ids)` — the gateable scalar

**Test:** 2 governed changes, 1 whose decision ∈ trailers → `Coverage(covered=1, total=2, uncovered=[(path,decision)])`, `fraction == 0.5`. Zero governed changes → `total=0`, treated as **fully covered** (vacuously clean, exit 0 — don't divide-by-zero).
**Implement → pass → commit** `feat: commit_check.coverage scalar`.

---

## Phase 2 — CLI command `decree commit-check`

### Task 2.1: argument parsing + input-mode resolution

**Files:** Create `commit_check_run(args)` in `commit_check.py`; register in `cli.py` (`add_parser("commit-check", …)` + `"commit-check": commit_check_cmd.commit_check_run` in the dispatch dict at line ~857). Flags: `--diff-base REF`, `--diff PATH` (`-` = stdin), `--message PATH`, `--strict`, `--min-coverage N` (0–100), `--json`, `--project`.
- Paths via the **reused** `intent_review._read_diff_source(args, root)` (import it; it already handles `--diff`/`--diff-base`/staged).
- Trailers: if `--diff-base` → `range_trailer_ids(root, ref)`; elif `--message` → `trailer_ids(read(message))`; else (staged, no message) → exit 2 with a clear "supply --message or --diff-base" hint.
**Test (CLI-level, via the run fn):** missing index → exit 2; bad input combo → exit 2.
**Commit.**

### Task 2.2: report output (human) + exit-code contract

**Test (end-to-end through `commit_check_run`):**
- governed change + matching trailer (range or message) → exit **0**, report shows `coverage 1/1 (100%)`.
- governed change + no trailer, **no `--strict`** → exit **0** (advisory), report lists the uncovered `(path → SPEC)` and `coverage 0/1 (0%)`.
- same + `--strict` → exit **1**.
- same + `--min-coverage 100` → exit 1; `--min-coverage 0` → exit 0.
- ungoverned-only diff → exit 0, `coverage — (no governed changes)`.
- terminal-SPEC-governed path, no trailer → exit 0 (in-flight only).
**Implement** the human formatter (mirror intent-review's section style: a `Trailer coverage (N/M)` block + an `Uncovered (k)` list with the `decree commit --implements <SPEC>` hint, reusing the existing `add_implements_trailer` wording). **Commit.**

### Task 2.3: `--json` contract (stable, for CI + MCP)

**Test:** asserts the exact shape:
```json
{ "coverage": {"covered": 1, "total": 2, "fraction": 0.5},
  "governed_changes": [{"path": "...", "decision_id": "SPEC-...", "type": "spec", "covered": true}],
  "uncovered": [{"path": "...", "decision_id": "SPEC-...", "title": "..."}],
  "mode": "diff-base|message|diff", "strict": false, "min_coverage": null,
  "exit": 0 }
```
**Implement → pass → commit** `feat: commit-check CLI (report, --strict, --min-coverage, --json)`.

---

## Phase 3 — MCP tool `commit_check`

### Task 3.1: add the `@mcp.tool()` wrapper

**Files:** `src/decree/commands/mcp_server.py` — a new `@mcp.tool()` `commit_check(diff=None, diff_base=None, message=None, strict=False, min_coverage=None)` returning the **same JSON** as the CLI (serialize through the same formatter — like `intent_review`/`intent_check` do, so the two never diverge). Read-only.
**Test:** `tests/test_mcp_*` parity — the MCP payload equals `commit-check --json` for the same inputs.
**Commit** `feat: MCP commit_check tool (identical payload to CLI)`.

---

## Phase 4 — Docs, changelog, honest framing

### Task 4.1: provenance-model.md + health-signals cross-ref

Update `docs/provenance-model.md` §"LLM-driven engineering": note that commit-time enforcement now has a **deterministic coverage gate** (`decree commit-check`), framed honestly as *coverage you can gate, not a guarantee* (bypassable by `--no-verify`/CI override). Keep the "enforcement is the harness's responsibility" line; the **installer** stays out of core.

### Task 4.2: llm-agent-integration.md — extend the loop + MCP list

Add `commit-check` to the recommended loop (after `intent-review`, before/with the commit: "run `decree commit-check --strict` or commit through `decree commit`"). Add `commit_check` to the MCP tools list (now **nine**).

### Task 4.3: usage.md / README — install-into-CI recipe + the orthogonality note

A CI snippet: `decree commit-check --diff-base origin/main --strict`. A documented **opt-in** local hook (a `.git/hooks/commit-msg` snippet calling `decree commit-check --message "$1" --strict`) — clearly labeled opt-in, with the `--no-verify` caveat stated. A short "decisions vs tickets are orthogonal; the trailer composes below your subject/Change-Id" note.

### Task 4.4: Towncrier fragment

`changelog.d/+commit-check.feature`: "Add `decree commit-check`: a deterministic trailer-coverage gate (advisory by default, `--strict`/`--min-coverage` for CI) that reports which governed-file changes lack an `Implements:/Refs:/Fixes:` trailer linking them to their in-flight decision. Reads only declared `governs:`; exposed over MCP."

**Gate (whole feature):** `uv run pytest -q`, `uv run ruff check/format`, `uv run decree lint`, `uv run decree index verify` (after `index rebuild`), `lychee` — all green. Check off the SPEC's ACs; `decree report regenerate` if it hits 100%.

---

## Test matrix (the full surface — all in `tests/test_commit_check.py`)

1. in-flight governed + matching `Implements:` → exit 0, 1/1.
2. in-flight governed + **no** trailer, no `--strict` → exit 0 (advisory), 0/1, uncovered listed.
3. same + `--strict` → exit 1.
4. same + `--min-coverage 100` → 1; `--min-coverage 0` → 0; `--min-coverage 50` with 1/2 → 0 (≥50).
5. `Refs:`/`Fixes:` satisfy (not only `Implements:`).
6. wrong-SPEC trailer → uncovered.
7. multi-value trailer `Implements: A, B` → both satisfied.
8. ungoverned-only diff → exit 0, "no governed changes."
9. terminal/implemented SPEC governs path, no trailer → exit 0 (in-flight only).
10. **squash reality:** `--diff-base REF` with the trailer on one of several commits in `REF..HEAD` → covered (range union).
11. file governed by **two** in-flight decisions, only one cited → uncovered for the other.
12. directory-prefix governance (`src/auth/`) → each touched file under it is a governed change (documents the noise; advisory by default mitigates).
13. missing index → exit 2; staged with no `--message`/`--diff-base` → exit 2.
14. `--json` shape stable; MCP payload == CLI `--json`.
15. **scalability:** a 500-path diff with 50 in-flight decisions completes; `why()` is called per path — if slow, batch via a single index query (note in plan, optimize only if a perf test shows it).

---

## Risk / backwards-compat

Purely additive: one new module, one CLI registration line, one MCP tool, doc edits, a changelog fragment. **No changes** to `index_db`, `queries`, `health`, `commit`, the schema, or any existing command's behavior. Opt-in everywhere (you must run `commit-check` or wire the documented hook). Cannot break existing users. Backwards-compatible JSON is a new stable contract.

## Scalability notes

- `why()` per path is O(paths); for very large diffs, add a single batched declared-governance query if a perf test (case 15) shows it matters — otherwise keep it simple.
- The `--diff-base` range-trailer gather is one `git log` call. CI cost is one diff + one log + N index reads — cheap.
- `--min-coverage` enables **ratcheting adoption** on legacy repos (start at the current %, raise over time) — no flag day.

## Out of scope (record as future ADRs if ever wanted)

Core git-hook installer; `health`/`ddd` coverage surfacing; ticket→decision mapping; LLM trailer inference; auto-writing trailers (that stays `decree commit`'s job — verify and write stay separate).
