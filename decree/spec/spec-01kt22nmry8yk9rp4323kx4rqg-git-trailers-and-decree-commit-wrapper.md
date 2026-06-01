---
date: '2026-05-12'
id: SPEC-01KT22NMRY8YK9RP4323KX4RQG
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRY8YK9RP4323KX4RQG Git Trailers and decree commit Wrapper

## Overview

Implements PRD-01KT22NMRS4QGHSFDBZ858PP1T R4 — the structural SPEC↔commit binding. Two deliverables:

1. **`decree commit` wrapper** — inspects the staged diff, infers the "active SPEC" (the SPEC whose `governs:` paths overlap most with staged files, with unchecked ACs), and prepends `Implements: SPEC-<ULID>` (or `Refs:` / `Fixes:` per-flag) to the commit message via `git interpret-trailers`. Falls back to a manual override flag.
2. **Git-trailer ingestion into the index** — `decree index rebuild` walks `git log` for `Implements:` / `Refs:` / `Fixes:` trailers and populates the `commits` table (currently empty post-SPEC-01KT22NMRX176PCT00SKJ9G2AQ). This unlocks `decree refs SPEC-<ULID>` showing commits that implement the SPEC.

This SPEC closes the half of PRD-01KT22NMRS4QGHSFDBZ858PP1T R4 that SPEC-01KT22NMRX176PCT00SKJ9G2AQ stubbed (the `commits` table exists; this SPEC fills it) and adds a *new* user-facing command (`decree commit`).

The key library choice: **`git interpret-trailers` is part of git itself**, no Python wrapper needed. For walking `git log` we shell out to `git log --format=...` — also no `GitPython` / `pydriller` dependency. (PRD-01KT22NMRS4QGHSFDBZ858PP1T's dependency table reserved those as options; we don't need them for this scope.)

## Technical Design

### Trailer convention

```
<commit subject line>

<commit body, free-form>

Implements: SPEC-01KT22NMRX176PCT00SKJ9G2AQ
Refs: ADR-01KT22NMRV9CP14X5982JJH161, PRD-01KT22NMRS4QGHSFDBZ858PP1T
Fixes: SPEC-01KT22NMRWENYKC3MGRA50M7GE
```

- **`Implements: SPEC-<ULID>`** — primary structural link. SPEC↔commit binding. Multi-value (`Implements: SPEC-01KT22NMRX176PCT00SKJ9G2AQ, SPEC-01KT22NMRXFWNE61NSETKATHBA`) allowed.
- **`Refs:`** — soft reference. The commit touches code governed by these decisions but isn't a primary implementation. Multi-value.
- **`Fixes:`** — bug-fix link. Same shape as `Implements:` but distinct semantically. Multi-value.

Trailer values are decision IDs, matching the existing ref-format regex on each type (e.g., `SPEC-\d{3}`). Invalid IDs are flagged but not blocking — they may be typos, but they shouldn't block a commit. `decree lint` flags them as warnings (deferred — coherence gate, SPEC-01KT22NMRYNFYM7EN80WS2HD6F).

### `decree commit` — wrapper command

```
decree commit [-m MESSAGE] [--implements ID...] [--refs ID...] [--fixes ID...] [--no-infer] [--amend] [--] <git-commit-args>
```

Behavior:

1. **Staged-files check** — call `git diff --cached --name-only` to get the list of staged paths. If empty, refuse with a clear error (matches `git commit` behavior).
2. **Active-SPEC inference** (when `--implements` not explicitly passed and `--no-infer` not set):
   - Query the SQLite index for all SPECs whose `governs:` paths overlap with the staged files (exact + prefix matches, using the same logic as `decree why`).
   - Filter to SPECs in non-terminal status (i.e., still in-flight: `draft`, `review`, `approved`).
   - Among those, prefer the one with the **most unchecked acceptance criteria** (signal: actively being worked on).
   - If a unique winner exists, use it. If multiple tie, fall back: print the candidates and require explicit `--implements`.
   - If none match, no `Implements:` trailer is added. (Commit still goes through.)
3. **Construct the commit message**:
   - Take the user's message (`-m "..."` or `$EDITOR` if no `-m`).
   - Append trailers using `git interpret-trailers --in-place --if-exists addIfDifferent`.
   - Trailers added: one `Implements:` per inferred or `--implements`-provided ID; `Refs:` from `--refs`; `Fixes:` from `--fixes`.
4. **Execute the commit** — shell out to `git commit ...` with the assembled message. Returns whatever `git commit` returns.
5. **Index sync (post-commit)** — after a successful commit, run `IndexDB.sync_commits_from_git()` so `decree refs SPEC-<ULID>` reflects the new commit immediately. (Fast — only walks the new commits since the last sync, OR does a full re-sync; v1 ships full re-sync; incremental is v2 backlog.)

The wrapper is **opt-in** — `git commit` keeps working unmodified. Users who skip `decree commit` lose the `Implements:` trailer for that commit; they can add it manually via `git commit --amend` or accept that the index lookup will not surface that commit.

### Trailer ingestion into the index

`IndexDB.sync_commits_from_git(project_root)` is a new method:

1. Detect whether the project is a git repo via `git rev-parse --show-toplevel`. If not (e.g., decree is being used in a non-git project), return `(0, 0)` because there is no git trailer source to index.
2. Run `git log --format="%H%x00%ct%x00%B%x00%x00"` to stream commit SHA, timestamp, full body. Parse trailer lines using `git interpret-trailers --parse` (one subprocess per commit message — for the jira-task-to-md scale of ~1000 commits this is fine; if perf becomes an issue, batch via temp file).
3. For each commit, extract `Implements:`, `Refs:`, `Fixes:` trailer values (comma-split per value), and upsert rows into `commits(sha, decision_id, trailer_kind, summary, committed_at)`.
4. Wipe `commits` rows from previous syncs whose SHAs no longer exist in `git log` (rewritten history). Optional via `--gc-stale` to be safe; default-on if `git log` returned anything (we trust git).

This is called from `IndexDB.rebuild()` after the markdown side completes:

```
rebuild():
  init_schema()
  wipe(decisions, refs, governs, acceptance_criteria)
  ingest_markdown(...)
  sync_commits_from_git(project_root)      # new in this SPEC
  rebuild_fts(...)
  commit()
```

`RebuildStats` extends to include `commits` count and `git_sync_ms` so regressions are visible.

### Files touched

- **Create**: `src/decree/commands/commit.py` — `commit_run`, `infer_active_spec`, trailer construction helpers.
- **Modify**: `src/decree/index_db.py` — `sync_commits_from_git()` method, called from `rebuild()`. Update `RebuildStats` to include `commits` count and `git_sync_ms` timing.
- **Modify**: `src/decree/cli.py` — register `decree commit` subcommand with the flag surface above.
- **Create**: `tests/test_commit.py` — wrapper command + trailer construction + active-SPEC inference.
- **Modify**: `tests/test_index_db.py` — add tests for `sync_commits_from_git()` using a tmp git repo fixture.

### What this SPEC does NOT do

- **No `git notes refs/notes/decree` backfill** — that's deferred to SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 (migration tooling, PRD-01KT22NMRS4QGHSFDBZ858PP1T R9). Trailers are forward-only here.
- **No interactive REPL for ambiguous active-SPEC** — if inference can't pick a unique winner, we error out and require `--implements`. No "pick one of these" prompt.
- **No incremental commit sync** — `IndexDB.sync_commits_from_git()` re-reads the full git log on every `decree index rebuild`. Incremental (only-new-since-last-sync) is SPEC-01KT22NMRX176PCT00SKJ9G2AQ v2 backlog.
- **No history rewrites** — `decree commit --amend` passes through to `git commit --amend`; we don't filter-branch.
- **No `Co-Authored-By:` or other RFC-822 trailer harvesting** — only the three decree-specific trailer kinds.
- **No commit-message linting** — `decree lint` does NOT validate trailer well-formedness in v1. Could be added later as an opt-in coherence gate (SPEC-01KT22NMRYNFYM7EN80WS2HD6F).
- **No pre-commit hook installation** (`decree hook install --type=pre-commit`) — could come in a future SPEC.

## Testing Strategy

### Unit tests (`tests/test_commit.py`)

- **Trailer construction**: given a message and `Implements: ["SPEC-01KT22NMRX176PCT00SKJ9G2AQ"]`, the output has the trailer block in canonical position (use `git interpret-trailers` directly in a tmp dir).
- **Multi-value trailers**: `--implements SPEC-01KT22NMRX176PCT00SKJ9G2AQ --implements SPEC-01KT22NMRXFWNE61NSETKATHBA` produces correct trailer block (verify what `git interpret-trailers` produces — likely two `Implements:` lines).
- **Active-SPEC inference — unique winner**: staged file `src/decree/foo.py`, governs table has SPEC-01KT22NMRXWCS5TK5VC1FT6JER with that path; infer picks SPEC-01KT22NMRXWCS5TK5VC1FT6JER.
- **Active-SPEC inference — multiple candidates**: two SPECs govern the same file; inference returns the one with more unchecked ACs.
- **Active-SPEC inference — terminal status filtered**: implemented SPEC is excluded from candidates.
- **Active-SPEC inference — ties**: clear error message listing candidates; exit 1.
- **--no-infer**: skips inference entirely, no `Implements:` trailer added.
- **Empty staged set**: refuse with a clear error.

### Unit tests (extending `tests/test_index_db.py`)

- **sync_commits_from_git — simple**: tmp git repo with one commit containing `Implements: SPEC-01KT22NMRWENYKC3MGRA50M7GE` trailer; after sync, `commits` table has one row with the correct SHA / decision_id / trailer_kind.
- **sync_commits_from_git — multiple trailers**: one commit with `Implements: SPEC-01KT22NMRWENYKC3MGRA50M7GE, SPEC-01KT22NMRW79Y92MKZT807B2J1` produces two rows.
- **sync_commits_from_git — Refs and Fixes**: trailer kinds preserved.
- **sync_commits_from_git — non-git project**: returns `(0, 0)` with no crash because there is no commit history to scan.
- **rebuild_includes_commits**: full rebuild populates both markdown side and git side.
- **commits gc on rewrite**: an old SHA that disappears from git log is removed from commits table.

### Integration tests

- **End-to-end commit + index**: create a tmp git repo with a decree project (minimal corpus); stage a file matching SPEC-01KT22NMRXWCS5TK5VC1FT6JER's governs (or a fixture SPEC); run `decree commit -m "test"`; assert the commit has the `Implements: SPEC-<ULID>` trailer (via `git log --format=%B HEAD -1`); assert `decree refs SPEC-<ULID> --json` now shows the commit in the `commits` array.

### Dogfood validation

- After SPEC-01KT22NMRY8YK9RP4323KX4RQG ships, the very next commit in the decree repo itself should use `decree commit` (the PM commits via that command). Verify with `git log -1 --format="%(trailers:key=Implements)" HEAD` that the trailer is present.
- `decree refs SPEC-01KT22NMRXWCS5TK5VC1FT6JER --json` (or any prior SPEC) should show its associated commit if `Implements:` was set on past commits — but past commits don't have trailers, so this remains empty until backfill (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6).

## v1 Acceptance Criteria

### `decree commit` wrapper

- [x] `src/decree/commands/commit.py` exists with `commit_run`, `infer_active_spec`, trailer construction helpers.
- [x] `decree commit -m "msg"` runs `git commit -m "msg"` with no trailer added when no SPEC matches and no flags given.
- [x] `decree commit -m "msg" --implements SPEC-01KT22NMRXWCS5TK5VC1FT6JER` adds `Implements: SPEC-01KT22NMRXWCS5TK5VC1FT6JER` trailer to the message.
- [x] Multi-value `--implements` (flag repeated) results in correct trailer block.
- [x] `--refs`, `--fixes` work analogously with `Refs:` / `Fixes:` trailer kinds.
- [x] Active-SPEC inference: staged files matching exactly one in-flight SPEC's `governs:` paths → that SPEC is auto-added as `Implements:`.
- [x] Inference filters out SPECs in terminal-success / warn-on-reference status.
- [x] When inference is ambiguous (multiple in-flight matches), prints candidates and exits 1 unless `--implements` is provided.
- [x] `--no-infer` skips active-SPEC inference entirely.
- [x] Empty staged set: refuses with a clear error before invoking git.
- [x] `--amend` passes through to `git commit --amend`.
- [x] After a successful commit, `IndexDB.sync_commits_from_git()` is called so `decree refs` shows the new commit.

### Index sync from git

- [x] `IndexDB.sync_commits_from_git(project_root)` method exists.
- [x] Walks `git log` and parses trailers using `git interpret-trailers --parse` (no Python re-implementation of trailer parsing).
- [x] Populates `commits(sha, decision_id, trailer_kind, summary, committed_at)`.
- [x] Multi-value trailer (`Implements: SPEC-01KT22NMRX176PCT00SKJ9G2AQ, SPEC-01KT22NMRXFWNE61NSETKATHBA`) produces one row per value.
- [x] Non-git projects return `(0, 0)` from trailer sync; no crash.
- [x] Called from `IndexDB.rebuild()` after the markdown side completes.
- [x] `RebuildStats` reports `commits` count and `git_sync_ms` timing.
- [x] Performance: full rebuild including git sync on a multi-hundred-commit repo completes in <3s.

### CLI

- [x] `decree commit` subcommand registered with full flag surface.
- [x] Subcommand documented in `decree --help`.

### Tests

- [x] `tests/test_commit.py` covers all wrapper / inference cases.
- [x] `tests/test_index_db.py` extended with git-sync cases (using a tmp git repo fixture).
- [x] Existing 305 tests continue to pass.
- [x] At least one integration test creates a tmp git repo, runs `decree commit`, verifies the trailer landed and the index reflects it.

### Dogfood

- [x] The SPEC-01KT22NMRY8YK9RP4323KX4RQG implementation commit itself uses `decree commit` and carries `Implements: SPEC-01KT22NMRY8YK9RP4323KX4RQG` trailer (verifiable via `git log -1 --format=%B`).

## What this does NOT do (deferred)

- [ ] `git notes refs/notes/decree` backfill of historical commits — SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 (PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 migration).
- [ ] Interactive disambiguation prompt for ambiguous active-SPEC inference.
- [ ] Incremental commit sync (only-new-since-last-sync) — SPEC-01KT22NMRX176PCT00SKJ9G2AQ v2 backlog.
- [ ] Pre-commit hook installation (`decree hook install --type=pre-commit`).
- [ ] Trailer well-formedness as a `decree lint` rule — SPEC-01KT22NMRYNFYM7EN80WS2HD6F.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R4 — the requirement this SPEC implements.
- ADR-01KT22NMRV9CP14X5982JJH161 — Option C hybrid: the index is the canonical query substrate.
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ — the `commits` table stub this SPEC fills.
- SPEC-01KT22NMRXWCS5TK5VC1FT6JER — `decree refs` will start surfacing populated `commits` after this ships.
- `git-interpret-trailers(1)` man page — the canonical trailer mechanism we wrap.
