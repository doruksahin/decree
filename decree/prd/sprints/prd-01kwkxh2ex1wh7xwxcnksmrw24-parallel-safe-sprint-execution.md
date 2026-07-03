---
id: PRD-01KWKXH2EX1WH7XWXCNKSMRW24
status: draft
date: 2026-07-03
references:
- PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ
---

# PRD-01KWKXH2EX1WH7XWXCNKSMRW24 Parallel-Safe Sprint Execution

## Problem Statement

The sprint ledger introduced by PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ stores all
execution state in a single hand-maintained YAML file,
`decree/sprints/ledger.yaml`. It is the only global monolithic mutable file in
a system that is otherwise built on one-file-per-decision documents plus
derived indexes, and it serializes parallel development through four
mechanisms:

1. `decree new spec` auto-enrolls each new SPEC into the active sprint, so
   every git worktree appends to the same YAML list and any two worktrees that
   both create a SPEC collide on merge.
2. Lint's enrollment invariant requires the SPEC file and its ledger entry to
   land in the same commit, so the ledger conflict cannot be deferred or
   worked around; it blocks the commit that introduces the SPEC.
3. The exactly-one-active-sprint rule combined with
   rollover-requires-all-outcomes couples otherwise independent work streams:
   nobody can close a sprint until every stream's items have outcomes.
4. The load→mutate→save cycle takes no lock, so two decree sessions in the
   same worktree can silently lose each other's writes.

Separately, item-level completion is inexpressible mid-sprint. The ledger
model forbids outcomes on active-sprint items and forbids terminal SPECs as
live items, so a SPEC whose acceptance criteria reach 100% halfway through a
sprint has no sanctioned way to be recorded as done until the whole sprint
rolls over.

The guiding principle for the fix: do not relax any invariant. Shrink the
contention surface instead, so that each unit of change owns its own file and
semantic conflicts surface in post-merge lint rather than as git merge
conflicts.

## Requirements

- Sprint membership writes must be conflict-free across git worktrees and
  across concurrent sessions in the same checkout. Two worktrees that each
  create a SPEC (and therefore each record a sprint enrollment) must merge
  without ever touching a shared mutable file.
- Item-level completion must be expressible mid-sprint: when a SPEC's primary
  acceptance criteria reach 100%, an operator or agent must be able to record
  a completed outcome for that one item immediately, without closing the
  sprint and without weakening the existing 100%-primary-progress proof.
  Dropping a single item mid-sprint with a reason must be equally possible.
- An orchestrator supervising parallel work must be able to inspect each
  worktree's sprint state independently and, after an integration merge, run
  a single corpus-wide lint that surfaces any semantic conflicts the merge
  produced. No sprint invariant may be relaxed to make merges pass; conflicts
  move from git's textual layer to lint's semantic layer.
- Existing repositories on the v1 monolithic ledger must migrate with a
  single one-shot command that converts the ledger to the new layout,
  verifies the result, and removes the old file. Sprint entry points must
  detect an unmigrated v1 ledger and fail loudly with the migration command,
  never silently skip sprint checks.

## Success Criteria

- [ ] Two git worktrees each create a new SPEC while sprint mode is active,
  and merging both branches back requires no manual conflict resolution
  because no shared file was modified by either enrollment.
- [ ] After an integration merge of parallel sprint work, `decree lint`
  passes when the merged state is semantically consistent and reports a
  precise per-file error (not a crash or a git conflict marker) when it is
  not.
- [ ] A SPEC whose primary acceptance criteria are 100% complete can be
  marked completed mid-sprint with one command, immediately leaves the
  default progress scope, and its recorded snapshot stays stable even if the
  document changes afterwards.
- [ ] A sprint item can be dropped mid-sprint with a required reason, and the
  drop is auditable in the sprint archive after rollover.
- [ ] Two concurrent decree sessions in the same checkout cannot silently
  lose each other's sprint membership writes.
- [ ] An orchestrator can run `decree sprint status` inside any worktree and
  see that worktree's view of open, done, backlog, and draft-pool items
  without cross-worktree interference.
- [ ] Running the migration command once on a v1 repository produces a valid
  v2 store, deletes the old ledger file, and leaves `decree lint` green; all
  sprint commands fail with a clear pointer to the migration command until it
  has been run.

## Scope

In scope:

- Restructuring sprint execution state storage so each membership record is
  independently writable.
- Mid-sprint completed and dropped outcomes for individual items.
- Locking for the few remaining multi-file transitions (init, pause, resume,
  rollover).
- A one-shot v1-to-v2 migration command and v1 detection errors.
- Documentation and tests for the parallel-worktree workflow and orchestrator
  supervision patterns.

Out of scope:

- Multiple simultaneously active sprints or per-worktree sprint lanes.
- Reopen semantics for terminal SPECs.
- Mid-sprint carried_over, deferred, or superseded outcomes; these remain
  rollover-only.
- Calendar scheduling, estimation, or external tracker integration.
