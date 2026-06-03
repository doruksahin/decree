---
date: '2026-06-03'
governs:
- src/decree/index_db.py
- src/decree/commands/health.py
id: SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ
- SPEC-01KT22NMRY8YK9RP4323KX4RQG
- SPEC-01KT22NMRYNFYM7EN80WS2HD6F
- SPEC-01KT22NMRXFWNE61NSETKATHBA
- SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S
status: implemented
---

# SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D Observed-governs Index and Dead-governance Signal

## Overview

The decision↔code link rots because `governs:` is *declared intent* that drifts
from reality. decree already grounds provenance in git — the `commits` table is
built from `Implements:/Refs:/Fixes:` trailers (SPEC-01KT22NMRY8YK9RP4323KX4RQG),
and `decree health` already reports `stale_decisions` (governed files churned)
and `ungoverned_hotspots` (high-churn files nobody governs)
(SPEC-01KT22NMRYNFYM7EN80WS2HD6F). What is missing is **per-decision
attribution**: comparing a decision's declared `governs:` against the paths its
own trailer-linked commits actually touched.

This SPEC (v1) adds that, deterministically and read-only:

1. **`observed_governs`** — a derived index table recording the files each
   decision's trailer-linked commits touched (extends the provenance index,
   SPEC-01KT22NMRX176PCT00SKJ9G2AQ).
2. **Dead-governance** — a new signal in `decree health`: declared `governs:`
   paths that **no** linked commit ever touched (aspirational/abandoned scope).
   This is the one drift signal with no existing analog and the highest
   precision (no roll-up, no causal guess).

No LLM (this is the deterministic cousin of the "auto-propose ADRs from
ungoverned hotspots" research frontier in `docs/market-analysis/research-frontiers.md`),
no new dependency, and the observation cache is **never** read by `why()`.
Missing-governance detection and suggest/write are deferred to follow-up SPECs.

## Technical Design

### `observed_governs` index table

A new table created in `IndexDB.init_schema` beside `commits`/`governs`, at
**raw file grain** (no directory roll-up baked in — thresholds will change, and
the dead check needs exact-file resolution):

```
observed_governs(decision_id, path, commit_count, last_seen_at)
  pk (decision_id, path); index on decision_id
```

Like the rest of the index it is a **derived read-cache** — frontmatter remains
the source of truth.

**Population — inside `sync_commits_from_git`.** That method already extracts the
trailer-linked `(sha, decision_id)` set. To attribute files, take a **single
batched** `git log --format=<sentinel + %H> --name-only` pass over the whole
history (the pattern `health._recent_file_churn` already uses), parse `sha →
touched files` in Python, then join in memory against the linked set; per
`(decision_id, path)` count the distinct touching commits and keep the max
`committed_at` as `last_seen_at`.

> **Why batched, not per-sha `git diff-tree -r <sha>`:** `diff-tree -r` returns
> an empty set (exit 0, undetectable) for the **root commit** and **merge
> commits**. The dominant real shape is "a decision's only `Implements:` commit
> *is* the repository's root commit" — which would zero the observation basis
> and invert the dead-governance gate into a flag-everything generator while the
> test suite stays green. `git log --name-only` emits the root commit's files
> correctly and attributes a merge's constituent changes to their real child
> commits.

**Filters** (touched files dropped before counting): the decision's own doc path
(`SELECT path FROM decisions WHERE id = ?` — already stored and indexed, used by
`stale_decisions`), the decree corpus directories (sourced from `config.py`, not
hardcoded), and generated artifacts (reuse `health._is_generated_artifact`,
which already covers `index.md` and `reports/`; add lockfiles).

**Lifecycle:** full wipe-and-insert in the **same transaction** as the `commits`
wipe. Every code path that wipes/returns for `commits` (non-git, empty/broken
repo) must do the identical wipe for `observed_governs`, or the two tables
desync and dead-governance joins stale observations against fresh commits.
Non-git repositories are a clean no-op.

### Dead-governance signal (in `decree health`)

`dead_governance(db)`: for each decision with declared `governs:` paths, a path
`P` is **dead** iff the decision has **≥1 trailer-linked commit** and **no**
observed file `F` for that decision is covered by `P`.

- **Cover predicate — dead-check-local, NOT shared with `why()`:**
  `_path_covers(P, F)` = `P == F` **or** `F.startswith(P.rstrip('/') + '/')`.
  This intentionally diverges from `why()`'s matching, which prefix-matches only
  governs paths that end in `/` (`queries.py`). The `governs` field
  (SPEC-01KT22NMRXFWNE61NSETKATHBA) permits directory entries written **without**
  a trailing slash, so a live directory declared as `src/auth` whose commits
  touch `src/auth/login.py` must **not** be flagged dead. `why()` is left
  untouched — sharing one predicate would either leak this permissiveness into
  `why()` (forbidden) or reintroduce the false positive.
- **Symbol entries are excluded, not flagged.** A `governs` row with a non-empty
  `symbol` (`path#symbol`) can never be covered by a file-grained observation;
  it is *unobservable at this grain*, not dead, and is omitted from the signal.
- **Precision gate.** A decision with zero trailer-linked commits yields no dead
  claims; its paths are **unobserved**, not dead, and the reason is surfaced.
  (A squash-merge over-attributes files and can therefore only *suppress* a dead
  claim, never invent one — fail-safe.)

**Surface:** a new "Dead governance" section in `decree health` human output and
a `dead_governance` key in `--json` (per decision: `decision_id`, dead `paths`,
`linked_commit_count`), plus an honesty line — observed as of the index's
`last_rebuilt_at` (from `index_meta`), and the count of decisions with no
trailer-linked commits (unobserved). It reads `observed_governs` **as-is**
(stale-tolerant, exactly as `governs` is read today) and **never** triggers a
rebuild inside health.

### Relationship to existing decisions

Extends the provenance index (SPEC-01KT22NMRX176PCT00SKJ9G2AQ) and consumes the
trailer/commit source (SPEC-01KT22NMRY8YK9RP4323KX4RQG). Lives inside
`decree health` (SPEC-01KT22NMRYNFYM7EN80WS2HD6F), complementing `stale_decisions`
and `ungoverned_hotspots` with the per-decision attribution neither provides,
without duplicating either. Matches but deliberately diverges from `why()`'s
`governs` matching (SPEC-01KT22NMRXFWNE61NSETKATHBA) for the dead check only.
The suggest/write half belongs to `decree migrate governs`
(SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S), not here.

## Testing Strategy

`pytest` over a temp-git fixture, extending the `_git_init` / `_commit` /
`_bootstrap_repo` helpers in `tests/test_health.py`. The existing
single-root-commit fixture *is* the root-commit case; add a multi-commit variant
and a merge variant so the batched-log attribution is exercised. Cover
observation population (counts; own-`.md` via `decisions.path`; generated/corpus
filters; non-git and empty-repo no-op with `commits`/`observed_governs`
consistency) and the dead signal (exact and directory-prefix alive/dead;
slashless-directory not-dead; symbol-never-dead; unobserved-not-dead with reason;
`--json` shape and per-decision `linked_commit_count`). Gates: `ruff`, `pytest`,
`decree lint`, `decree index regenerate`, Towncrier fragment. **Dogfood note:**
the decree corpus uses file paths and trailing-slash directories, so the
slashless-directory false positive is *not* exercised by the corpus — it must be
covered by an explicit external-style test, never by corpus validation alone.

## v1 Acceptance Criteria

- [x] `observed_governs(decision_id, path, commit_count, last_seen_at)` table created in `init_schema`, raw file grain, pk `(decision_id, path)`, indexed on `decision_id`.
- [x] Populated in `sync_commits_from_git` from a single batched `git log --name-only` pass joined to trailer-linked commits — never per-sha `git diff-tree` (root- and merge-commit safe).
- [x] Root-commit and merge-commit file touches are attributed, not dropped.
- [x] Touched-file filters applied: decision documents (`decisions.path`), decree-generated `index.md` / completion-report files, and dependency lockfiles — so only real governed code is recorded.
- [x] `observed_governs` is wiped/inserted in the same transaction as `commits`; every `commits` wipe/no-op path (non-git, empty/broken repo) performs the identical wipe for `observed_governs`.
- [x] `dead_governance(db)` reports declared `governs:` paths no linked commit touched, using a dead-check-local cover predicate where a directory path covers files beneath it even without a trailing slash; `why()` is unchanged.
- [x] Symbol-scoped `governs` entries (`path#symbol`) are excluded from the dead signal and never flagged dead.
- [x] A decision with zero trailer-linked commits produces no dead claims; its paths are reported "unobserved" with the reason.
- [x] `decree health` gains a "Dead governance" human section and a `dead_governance` key in `--json` with per-decision `linked_commit_count` and an "as of `<last_rebuilt_at>`" honesty line.
- [x] `dead_governance` reads `observed_governs` as-is (stale-tolerant); `decree health` never triggers an index rebuild.
- [x] `observed_governs` is never read by `why()` or `intent-check` — those answer only from declared `governs:` (no silent fallback).
- [x] Tests cover root/merge commits, slashless-directory not-dead, symbol-never-dead, unobserved-not-dead, filter behaviour, and the `--json` shape.

## Deferred

Explicitly out of scope for v1 (each becomes its own SPEC under
PRD-01KT22NMRS4QGHSFDBZ858PP1T, only after v1's dead-governance signal is
validated as low-false-positive on a real corpus):

- [ ] **Missing-governance** — paths a decision's commits touch heavily but that are not in its `governs:`, with noise control (tuned thresholds + inverse-document-frequency down-weighting so a file touched by many decisions governs nothing).
- [ ] **Directory roll-up heuristic** — collapsing observed files into directory suggestions (only needed once a frontmatter value is produced).
- [ ] **Git-derived candidate source in `decree migrate governs --analyze`** alongside the existing body-text source, and `--write` routed through the existing `--apply-suggestions` atomic path (SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S) — no second writer.
- [ ] **Surfacing** the signals via the existing MCP `health` tool payload (not a new tool) and as `decree lint` / `decree ddd` hints (not a new command).
