---
date: '2026-07-03'
id: ADR-01KWKXH8423XTBV6CDVXB4B2ZB
references:
- PRD-01KWKXH2EX1WH7XWXCNKSMRW24
- PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ
status: accepted
supersedes: ADR-01KW1QGHBT2BSZ2HVT55G1QSJB
---

# ADR-01KWKXH8423XTBV6CDVXB4B2ZB Directory-Decomposed Sprint Ledger

## Context and Problem Statement

The v1 sprint ledger (`decree/sprints/ledger.yaml`) proved the sprint model:
exactly one active sprint, explicit paused mode, snapshot outcomes, linear
carryover, and backlog/draft-pool escape hatches. But it stores every piece of
that state in one mutable YAML file. Every `decree new spec` in every git
worktree appends to the same list, lint requires the enrollment and the SPEC
file in the same commit, and load→mutate→save runs unlocked. The result is
that a design built for parallel-safe decision documents funnels all parallel
execution tracking through a single merge-conflict hotspot.

The ledger also cannot express item-level completion mid-sprint: active items
must be outcome-less and terminal SPECs may not be live items, so a finished
SPEC must wait for full sprint rollover to be recorded as done.

We need a storage decision that removes the write contention and admits
mid-sprint item outcomes without relaxing any existing invariant.

## Decision Drivers

- Conflict-free concurrent membership writes across worktrees and sessions;
  no shared file may be modified by routine enrollment.
- Keep every v1 invariant enforceable: one active sprint, snapshot-proven
  completion, linear carryover, reasoned backlog, enrollment coverage.
- Item-level completed/dropped outcomes must become expressible mid-sprint.
- Semantic conflicts after an integration merge must surface in lint as
  per-file errors, never as crashes or silent state loss.
- Rollover, pause, resume, and init are rare integration ceremonies and may
  remain single-writer; routine per-item operations may not.
- Migration from v1 must be mechanical and one-shot.

## Considered Options

- Keep the monolithic ledger and mitigate with a git merge driver (for
  example a union or custom YAML-aware driver). This leaves the architecture
  untouched, but merge drivers are per-clone configuration that decree cannot
  guarantee, union merges of YAML lists produce structurally invalid or
  semantically wrong documents that lint cannot always distinguish from
  intent, and the unlocked same-worktree lost-write problem is not addressed
  at all.
- Store sprint membership in each document's frontmatter and derive the
  ledger as an index. Writes become perfectly file-local, but this reverses
  the accepted position of ADR-01KW1QGHBT2BSZ2HVT55G1QSJB that execution
  state must not live in decision documents: sprint churn would rewrite
  decision files, pollute their git history, and blur the boundary between
  governance truth and timebox ownership.
- Allow multiple active sprints or per-worktree lanes so each worktree owns
  its own sprint. This dissolves the contention by abandoning the
  exactly-one-active-sprint invariant, which the PRD explicitly refuses:
  lanes multiply rollover ceremonies, make carryover chains branch, and turn
  "which sprint owns this item" into a merge-time question.
- Decompose the ledger into a directory store: `state.yaml` for the sprint
  lifecycle state, one `live/<DOC-ID>.yaml` file per live membership, and one
  append-only `closed/<SPRINT-ID>.yaml` archive per closed sprint. Chosen.

## Decision Outcome

Chosen option: "directory-decomposed store", because it aligns the sprint
ledger with the rest of decree's architecture — one file per unit of change,
derived views assembled at read time — and removes contention at its source
instead of patching over it. Enrollment creates a new file named by the
document ID, so two worktrees enrolling different SPECs touch disjoint paths
and merge trivially; enrolling the same SPEC twice collides on the same
filename, so git itself surfaces the conflict at merge time on exactly one
small file (post-merge lint arbitrates the semantic duplicates git cannot see,
such as filename/document-field mismatches).

`state.yaml` changes only at init, pause, resume, and rollover; these
transitions run under an advisory file lock and stay deliberately
single-writer — rollover remains an integration ceremony performed at the
point where parallel streams converge, not something a worktree does on its
own. `closed/<SPRINT-ID>.yaml` archives are append-only history with the
exact v1 closed-sprint record shape.

Consequences:

- An outcome-bearing live file no longer counts as live membership. Presence
  of an `outcome` block means the item is resolved and merely awaits folding
  into the closed archive at the next rollover or pause; live membership
  queries count only outcome-less files.
- Live items with active scope are sprint-agnostic until fold. A live file
  records no sprint ID; the item belongs to whichever sprint is active at
  integration time, and sprint attribution is written exactly once, when the
  sprint closes and the item folds into its archive. This is what lets a
  worktree enroll items without knowing or racing on sprint identity.
- `completed` and `dropped` become available as mid-sprint item-level
  outcomes, written by rewriting only that item's own live file. The
  completed outcome keeps the v1 proof obligation: the close-time snapshot
  must show primary acceptance criteria at 100%.
- `carried_over`, `deferred`, and `superseded` remain rollover-only outcome
  kinds, because they relocate membership or re-target documents and
  therefore only make sense at the fold point. Lint rejects them in live
  files.
- Rollover semantics narrow slightly: the outcomes file must cover exactly
  the still-open items, since mid-sprint completed/dropped items are already
  resolved and fold with the outcomes they carry.
- The invariant surface is preserved but restated structurally: one active
  sprint is checked against archives and state, duplicate membership is a
  duplicate-filename or duplicate-document-field error, and malformed
  per-item files produce per-file lint errors instead of a whole-ledger parse
  failure.
- v1 repositories must run a one-shot migration; every sprint entry point
  detects a leftover `ledger.yaml` and fails with a pointer to the migration
  command rather than guessing.
