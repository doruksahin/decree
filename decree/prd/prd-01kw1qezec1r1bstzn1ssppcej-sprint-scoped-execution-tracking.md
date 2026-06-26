---
id: PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ
status: draft
date: 2026-06-26
---

# PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ Sprint-Scoped Execution Tracking

## Problem Statement

Decree users need a way to plan and review current execution work without
losing the long-lived PRD/ADR/SPEC decision chain. Today `decree progress` and
`decree ddd` report across the whole corpus unless a caller supplies an explicit
scope. That makes active work hard to scan once a repository has many completed
decisions, and it gives agents no durable place to record sprint outcomes such
as carryover, deferral, or dropped work.

The sprint mechanism must not turn sprint membership into governance truth. Old
decisions can still govern current code, and product intent can span many
sprints. The system needs a separate execution ledger that narrows task-facing
commands by default while keeping governance queries corpus-wide and auditable.

## Requirements

- Sprint mode must be explicitly initialized before sprint invariants become
  mandatory, so existing or dormant repositories are not forced into synthetic
  active sprints.
- Once sprint mode is initialized, the ledger must be in exactly one operating
  state: active or paused. Active state requires exactly one active sprint.
  Paused state requires no active sprint, plus `since` and `reason` fields that
  explain the freeze.
- Sprint membership must live in a dedicated sprint ledger or sprint document,
  not in PRD/ADR/SPEC `references:` fields.
- SPEC documents must be the default executable sprint task type.
- PRD and ADR documents may appear as context for sprint tasks, but they must
  not count as executable task progress unless explicitly added as planning
  items.
- A new SPEC must default into the active sprint, with explicit escape hatches
  for draft or backlog work.
- A SPEC may appear in more than one sprint only through a linearly linked
  carryover record with a required reason.
- Sprint rollover must be atomic: the current sprint closes, the successor
  becomes active, and every incomplete item receives an explicit outcome.
- Closed sprint outcomes must be historical snapshots and must not be recomputed
  from later live SPEC status.
- A completed sprint outcome must require structural proof, not only a human
  assertion. At minimum the close-time snapshot must show primary acceptance
  criteria at 100%.
- Backlog entries must carry `since`, `reason`, and source metadata so backlog
  cannot become an unbounded limbo for unscheduled work.
- Task-facing commands such as progress and DDD must default to the active
  sprint after sprint mode is enabled.
- Task-facing output must visually separate executable tasks, planning items,
  and referenced context so PRD/ADR context is not mistaken for sprint progress.
- Governance-facing commands such as `why`, `refs`, `lint`, `intent-check`,
  `intent-review`, `health`, and index verification must remain corpus-wide by
  default and must not hide older decisions behind sprint filters.
- Backlog, dropped, deferred, superseded, and reopened work must have explicit
  commands and reason requirements where they can otherwise obscure history.

## Success Criteria

- [ ] A repository can initialize sprint mode and produce exactly one active
  sprint, then pause sprint mode with an auditable reason when no active sprint
  should exist.
- [ ] `decree progress` and `decree ddd` default to the active sprint when
  sprint mode is enabled, while retaining flags for explicit sprint, backlog,
  and whole-corpus views.
- [ ] `decree lint` rejects no active sprint in active mode, multiple active
  sprints, paused mode without a reason, incomplete closed sprint items without
  outcomes, duplicate active/backlog membership, and non-linear carryover
  chains.
- [ ] `decree lint` rejects completed outcomes whose close-time snapshot does
  not prove 100% primary acceptance criteria completion.
- [ ] Backlog entries include `since` and `reason`, and old backlog entries
  produce actionable warnings instead of silently accumulating.
- [ ] Closed sprint reports remain stable after the underlying SPEC documents
  later change status or acceptance criteria.
- [ ] Governance queries still return corpus-wide decisions regardless of the
  active sprint.
- [ ] A PRD created in one sprint can receive new SPECs in later sprints without
  being treated as carryover.
- [ ] The same SPEC cannot silently move between sprints; it requires explicit
  carryover or an explicit reopen path.
- [ ] Progress output separates executable tasks, planning items, and context
  documents.

## Scope

In scope:

- Sprint initialization, active sprint tracking, sprint rollover, and sprint
  finish/pause semantics.
- A ledger-backed model for sprint membership, item outcomes, carryover links,
  backlog membership, backlog aging, and historical snapshots.
- CLI flags that distinguish active sprint, specific sprint, backlog, and
  whole-corpus reporting.
- Lint checks that prevent execution-history drift.
- Documentation and tests covering PRD/SPEC cross-sprint scenarios.

Out of scope:

- Calendar scheduling, velocity estimation, burndown charts, assignee capacity,
  and external issue tracker synchronization.
- Treating sprint membership as a replacement for PRD/ADR/SPEC references or
  `governs:` ownership.
- Hard-blocking all manual edits through git history analysis; git-aware
  mutation detection may be added later as an advisory health signal.
