# Parallel-Safe Sprint Ledger — Design Note

**Date:** 2026-07-03
**Status:** Implemented (schema `decree.sprints.v2`)
**Supersedes:** the `ledger.yaml` storage model in
[2026-06-26-sprint-scoped-execution-handoff.md](2026-06-26-sprint-scoped-execution-handoff.md)
**Related docs:**
[PRD-01KWKXH2EX1WH7XWXCNKSMRW24](../../decree/prd/sprints/prd-01kwkxh2ex1wh7xwxcnksmrw24-parallel-safe-sprint-execution.md),
[ADR-01KWKXH8423XTBV6CDVXB4B2ZB](../../decree/adr/sprints/adr-01kwkxh8423xtbv6cdvxb4b2zb-directory-decomposed-sprint-ledger.md),
[SPEC-01KWKXHERB56W94SCRZEVMBQMJ](../../decree/spec/sprints/spec-01kwkxherb56w94scrzevmbqmj-sprint-ledger-v2-storage-and-item-level-completion.md)

## Goal

Make sprint tracking safe for parallel git worktrees.

The v1 ledger (`decree/sprints/ledger.yaml`) was the only hand-maintained,
global, monolithic mutable file in a system otherwise built on
one-file-per-decision documents. Every worktree that ran `decree new spec`
appended to the same YAML list, so parallel streams met in merge conflicts,
and item-level completion was inexpressible mid-sprint.

The fix does not relax any invariant. It shrinks the contention surface: one
file per unit of change, with semantic conflicts surfacing in post-merge lint.

## What Changed vs v1

**Directory store.** The monolith is decomposed:

```text
decree/sprints/
  state.yaml                # sprint lifecycle; changes only at init/pause/resume/rollover
  live/<DOC-ID>.yaml        # one file per live membership (active, backlog, draft pool)
  closed/<SPRINT-ID>.yaml   # one append-only archive per closed sprint
```

Enrolling a new SPEC creates exactly one new file under `live/`. Two worktrees
enrolling different SPECs never touch the same path.

**Item-level completion.** Two new commands record outcomes mid-sprint instead
of deferring everything to rollover:

```bash
decree sprint complete SPEC-... --commit <sha>   # requires 100% primary ACs
decree sprint drop SPEC-... --reason "no longer needed"
```

`completed` still means proven: the command refuses unless primary acceptance
criteria are at 100%, and it stores the same snapshot rollover would.
Resolved items keep their live file (with an `outcome:` block) until the next
rollover folds them into the closed archive.

**Sprint-agnostic live items.** A live `scope: active` file records no sprint
id. The item belongs to whichever sprint is active at integration time;
attribution is written only when a sprint closes. This is what lets a worktree
branched before a rollover merge cleanly after it.

**Single-writer rollover.** Only the lifecycle transitions — `init`, `pause`,
`resume`, `rollover` — rewrite `state.yaml`, and they run under a file lock.
Rollover now needs outcomes only for the items still open; anything completed
or dropped mid-sprint is already resolved. Pause refuses while open
active-sprint items remain.

## Migration Path

Existing v1 projects run one command:

```bash
decree migrate sprint-ledger --dry-run   # print the plan, write nothing
decree migrate sprint-ledger --apply     # write v2 files, delete ledger.yaml, validate
```

Closed sprints become `closed/<SPRINT-ID>.yaml`, the active sprint becomes
`state.yaml` plus one `live/` file per item, and backlog/draft-pool entries
become `live/` files with their scope. Until migration runs, every sprint
entry point fails loudly with
`sprint ledger v1 detected; run 'decree migrate sprint-ledger'` — sprint
checks are never silently skipped.

## Orchestrator Workflow

The layout is designed for a supervising session fanning work out to
worktrees:

1. Orchestrator holds the main checkout; only it runs `init`, `pause`,
   `resume`, and `rollover`.
2. Each worker worktree creates its own SPEC (`decree new spec` writes one
   `live/` file) and implements it.
3. A worker that finishes runs `decree sprint complete SPEC-...` — a rewrite
   of its own file only — then transitions the document status.
4. The orchestrator inspects any worktree with `decree sprint status` and
   `decree progress` (resolved items leave the default scope; use
   `--sprint <SPRINT-ID>` to include them).
5. After merging worker branches, the orchestrator runs `decree lint` — the
   post-merge integration gate where duplicate membership or invalid outcomes
   surface as errors, not silent drift.

## What Did Not Change

Sprint semantics survive intact: exactly one active sprint, completed requires
proof, backlog requires accountability, carryover stays explicit and linear,
and governance (`why`, `refs`, `intent-check`) remains corpus-wide. The
`decree progress` / `decree ddd` scoping flags and the generated HTML board
keep their contracts.

## Summary

```text
one file per membership → parallel worktrees don't conflict
complete/drop mid-sprint → outcomes recorded when work finishes
live items sprint-agnostic → merges stay clean across rollovers
state.yaml single-writer → lifecycle stays strict, under a lock
decree migrate sprint-ledger → one-shot opt-in for v1 projects
```
