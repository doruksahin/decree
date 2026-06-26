---
id: SPEC-01KW1QJ27R175NVM8QNGW1FX8N
status: draft
date: 2026-06-26
references:
- PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ
- ADR-01KW1QGHBT2BSZ2HVT55G1QSJB
governs:
- src/decree/cli.py
- src/decree/identity.py
- src/decree/sprints.py
- src/decree/parser.py
- src/decree/validators.py
- src/decree/index_db.py
- src/decree/commands/new.py
- src/decree/commands/sprint.py
- src/decree/commands/progress.py
- src/decree/commands/ddd.py
- src/decree/commands/lint.py
- src/decree/commands/mcp_server.py
- docs/index.md
- docs/usage.md
- tests
---

# SPEC-01KW1QJ27R175NVM8QNGW1FX8N Sprint Ledger CLI and Validation

## Overview

Add sprint-scoped execution tracking to decree while preserving the
PRD/ADR/SPEC decision graph as governance truth. Sprint state is stored in a
dedicated ledger, not in decision-document `references:`. Once sprint mode is
initialized, task-facing commands default to the active sprint when the ledger is
active, while governance-facing commands remain corpus-wide. The ledger can also
enter a paused state for intentional no-sprint periods.

This SPEC covers the first implementation slice: the sprint ledger schema,
CLI commands for initialization, pause/resume, and rollover, validation
invariants, progress and DDD scoping, MCP progress parity, and
documentation/tests. Calendar scheduling, estimates, assignees, and external
tracker integrations are out of scope.

## Technical Design

### Ledger Source of Truth

Create a dedicated sprint ledger at `decree/sprints/ledger.yaml`.

The file is structured data, not a configured PRD/ADR/SPEC document type. A new
module owns sprint-ledger I/O and validation; `parser.py` remains responsible
for decision-document I/O only.

Initial schema:

```yaml
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-01...
paused: null
sprints:
  - id: SPRINT-01...
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: SPEC-01...
        kind: execution
        source: new
        added: 2026-06-26
        carryover_from: null
        outcome: null
backlog:
  - document: SPEC-01...
    kind: execution
    source: manual
    since: 2026-06-26
    added: 2026-06-26
    review_after: 2026-07-26
    reason: not ready for the active sprint
draft_pool:
  - document: SPEC-01...
    kind: execution
    added: 2026-06-26
    reason: speculative design, no sprint commitment yet
```

Paused ledger shape:

```yaml
schema: decree.sprints.v1
mode: enabled
state: paused
active: null
paused:
  since: 2026-07-01
  reason: summer freeze
sprints:
  - id: SPRINT-01...
    name: Sprint 1
    status: closed
    started: 2026-06-26
    closed: 2026-06-30
    items: []
backlog: []
draft_pool: []
```

Closed sprint item outcome shape:

```yaml
outcome:
  kind: completed | carried_over | deferred | dropped | superseded
  at: 2026-06-26
  reason: explicit reason except for completed
  to_sprint: SPRINT-01...      # carried_over only
  to_document: SPEC-01...      # superseded only
  evidence:
    commits: []                # optional trailer-linked commits observed at close
  snapshot:
    status: approved
    primary_done: 10
    primary_total: 10
    deferred_done: 0
    deferred_total: 2
```

The snapshot is written at sprint close/rollover time and is never recomputed
from later live document state. `completed` is accepted only when the snapshot
shows primary acceptance criteria at 100%. Optional commit evidence can be
stored for audit, but it does not replace the acceptance-criteria proof in v1.

### Sprint Identity

Add `SPRINT-ULID` identity generation and validation. Sprint IDs are not
decision IDs and must not be accepted by `require_doc_id`. Use a separate
`require_sprint_id` helper or equivalent.

### CLI

Add a `decree sprint` command namespace:

- `decree sprint init "Sprint 1"` creates the ledger, creates the first active
  sprint, and enables sprint mode. It fails if a ledger already exists unless an
  explicit idempotent status path is requested.
- `decree sprint status` prints active sprint, backlog count, draft-pool count,
  paused state, paused reason, and closed sprint count.
- `decree sprint pause --reason TEXT` transitions the ledger from active to
  paused only when the active sprint is already closed through rollover/finish
  semantics. It records `paused.since` and `paused.reason`.
- `decree sprint resume "Sprint N"` creates a new active sprint from paused
  mode and clears the paused block.
- `decree sprint add DOC_ID [--kind execution|planning]` adds a decision
  document to the active sprint. SPEC defaults to `execution`; PRD/ADR must use
  `--kind planning`.
- `decree sprint backlog DOC_ID --reason TEXT` moves or creates a backlog entry.
- `decree sprint draft DOC_ID --reason TEXT` records an explicit no-sprint
  commitment for a draft or speculative item.
- `decree sprint drop DOC_ID --reason TEXT` records a mid-sprint dropped
  outcome for an active item.
- `decree sprint defer DOC_ID --reason TEXT` moves an active item to backlog
  with a deferral reason.
- `decree sprint rollover "Sprint 2" --outcomes FILE` atomically closes the
  active sprint, creates the successor sprint, applies every open-item outcome,
  and sets the successor as the sole active sprint.
- `decree sprint list [--sprint ID|--all|--backlog|--draft-pool]` lists ledger
  items without changing state.

`--outcomes FILE` is required for rollover unless every active item already has
a valid close outcome. The file maps document IDs to `completed`, `carryover`,
`deferred`, `dropped`, or `superseded` outcomes. Carryover targets must be the
successor sprint being created by the same rollover. A `completed` outcome is
rejected unless the close-time snapshot proves 100% primary acceptance criteria
completion.

### New Document Integration

When sprint mode is enabled:

- `decree new spec "Title"` adds the new SPEC to the active sprint by default
  only when the ledger state is active.
- `decree new spec "Title" --backlog --reason TEXT` creates the SPEC and records
  it in backlog.
- `decree new spec "Title" --draft-pool --reason TEXT` creates the SPEC and
  records that it has no sprint commitment yet.
- `decree new prd` and `decree new adr` do not automatically become executable
  sprint tasks; callers can add them with `decree sprint add --kind planning`.

If sprint mode is not enabled, `decree new` behavior remains unchanged.
If sprint mode is paused, `decree new spec` without `--backlog` or
`--draft-pool` fails because there is no active sprint to receive the task.

### Progress and DDD Scope

When sprint mode is enabled and no explicit scope is passed:

- `decree progress` selects active sprint execution items when the ledger state
  is active. In paused mode it reports the paused state and requires an explicit
  scope such as `--backlog`, `--draft-pool`, or `--corpus`.
- `decree ddd` assesses active sprint execution items when the ledger state is
  active and includes their referenced PRD/ADR context in the chain display. In
  paused mode it reports the pause reason and suggests resuming or grooming
  backlog.

Existing explicit scope flags continue to win over sprint defaults. Add:

- `--sprint SPRINT-ID`
- `--all-sprints`
- `--backlog`
- `--draft-pool`
- `--corpus` for the previous whole-corpus behavior
- `--include-context` to display PRD/ADR parents for sprint items without
  counting them toward execution progress

Context documents are displayed separately and do not affect primary progress
unless they are explicit planning items.

Human output is grouped into distinct sections:

```text
Tasks
  SPEC-...  70%  active

Planning
  PRD-...   review

Context
  PRD-...   referenced by SPEC-...
  ADR-...   referenced by SPEC-...
```

Only `Tasks` and explicit `Planning` items contribute to scoped progress totals.
`Context` is explanatory only.

### Governance Scope

The following commands remain corpus-wide and do not use active sprint defaults:

- `decree lint`
- `decree why`
- `decree refs`
- `decree intent-check`
- `decree intent-review`
- `decree health`
- `decree index rebuild`
- `decree index verify`
- `decree commit-check`

Lint may validate sprint ledger consistency, but governance lookup must not
filter decisions by sprint.

### Validation Invariants

If `decree/sprints/ledger.yaml` is absent, sprint mode is disabled and existing
repositories keep current behavior.

If sprint mode is enabled, lint errors include:

- active mode with no active sprint
- paused mode with an active sprint
- paused mode without `paused.since` or `paused.reason`
- more than one active sprint
- active sprint ID does not match the top-level `active`
- active sprint item has an outcome
- closed sprint item has no outcome
- `completed` outcome snapshot is missing or is not 100% primary completion
- `carried_over`, `deferred`, `dropped`, or `superseded` outcome lacks a reason
- carryover target is not the immediate successor sprint
- carryover chain branches, skips a sprint, or points backward
- the same live document appears in active sprint, backlog, or draft pool at the
  same time
- a backlog entry lacks `since`, `source`, or `reason`
- a non-terminal SPEC created after sprint mode is enabled is in none of active
  sprint, backlog, or draft pool
- a terminal SPEC is added to a sprint without explicit `reopen` semantics
- a PRD or ADR is added as an execution item instead of a planning item
- active execution SPEC references a rejected, deprecated, superseded, or
  archived parent decision

Lint warnings include backlog entries older than the configured age threshold
without a recent review. Warnings do not fail v1 lint by default, but they must
be visible in human output and JSON output.

Closed sprint immutability is enforced by command behavior. Lint validates
self-consistency of the ledger; git-derived "closed sprint mutated after close"
detection is deferred to an advisory health signal.

### Index and MCP

The SQLite provenance index remains decision-focused. Sprint tables may be
added later if query performance requires it, but v1 reads the ledger directly
for `progress`, `ddd`, and MCP `progress` responses. No query command may fall
back to stale indexed sprint data.

MCP `progress` gains optional sprint scope parameters matching CLI behavior and
defaults to the active sprint when sprint mode is enabled.

### Documentation

Update `docs/index.md` and `docs/usage.md` with the sprint capability,
initialization flow, command examples, drift rules, and the distinction between
execution scope and governance scope.

## Testing Strategy

Add focused tests for the ledger parser/validator, CLI command behavior, and
progress/DDD scoping before broad integration tests.

Test files to update or add:

- `tests/test_sprint.py` for ledger schema, invariant validation, and sprint
  command behavior.
- `tests/test_new.py` for `decree new spec` active sprint, backlog, and draft
  pool integration.
- `tests/test_progress.py` for active sprint default, `--corpus`, `--sprint`,
  `--backlog`, and context display.
- `tests/test_ddd.py` for active sprint default assessment.
- `tests/test_lint.py` for sprint-mode lint failures.
- `tests/test_mcp_server.py` for MCP progress scope parity.

Acceptance tests must include a PRD created in one sprint with a new SPEC added
in a later sprint, and a separate same-SPEC carryover scenario to prove the two
cases are not conflated. They must also include a rollover attempting to mark a
partially complete SPEC as completed, a paused sprint system with no active
sprint, and an aged backlog item that produces a visible warning.

## Acceptance Criteria

- [x] `decree sprint init "Sprint 1"` creates `decree/sprints/ledger.yaml` with
  active state, exactly one active sprint, and test coverage.
- [x] `decree sprint pause --reason TEXT` records paused state with `since` and
  `reason`, and `decree sprint resume "Sprint N"` creates the next active
  sprint.
- [x] Sprint ID generation and validation are separate from decision document ID
  validation.
- [ ] The sprint ledger loader rejects malformed schema, duplicate sprint IDs,
  duplicate live membership, invalid decision or sprint IDs, and paused/active
  state contradictions.
- [x] `decree lint` enforces sprint-mode active-or-paused invariants only when
  the ledger exists.
- [ ] `decree lint` rejects incomplete closed sprint items without outcomes and
  outcome records missing required reasons.
- [x] `decree lint` rejects `completed` outcomes unless their close-time
  snapshot proves primary acceptance criteria are 100% complete.
- [ ] `decree lint` rejects non-linear carryover chains, including skipped
  successors, branches, and backward links.
- [ ] Backlog entries require `since`, `source`, and `reason`, and old backlog
  entries produce visible warnings.
- [x] `decree lint` rejects a non-terminal SPEC created after sprint mode is
  enabled when it is absent from active sprint, backlog, and draft pool.
- [x] `decree new spec` adds new SPECs to the active sprint by default when
  sprint mode is enabled and active.
- [x] `decree new spec` fails in paused mode unless `--backlog` or
  `--draft-pool` is supplied.
- [x] `decree new spec --backlog --reason TEXT` creates a backlog entry instead
  of active sprint membership.
- [x] `decree new spec --draft-pool --reason TEXT` records an explicit no-sprint
  commitment instead of leaving the SPEC invisible.
- [x] PRD and ADR documents can be added only as planning items unless a future
  decision changes the executable-task model.
- [x] `decree sprint rollover "Sprint 2" --outcomes FILE` atomically closes the
  old sprint, opens the successor, writes snapshots, and preserves exactly one
  active sprint.
- [x] Carryover of the same SPEC to the successor sprint requires an explicit
  reason and produces symmetric source/target records.
- [ ] A new SPEC under an older PRD can be added to the active sprint without
  being treated as carryover.
- [x] Closed sprint snapshots remain stable after the live SPEC later changes.
- [x] `decree progress` defaults to active sprint execution items when sprint
  mode is enabled.
- [x] `decree progress --corpus` preserves the existing whole-corpus behavior.
- [x] `decree progress --include-context` displays referenced PRD/ADR context
  without counting it toward execution progress.
- [x] `decree progress` human output separates `Tasks`, `Planning`, and
  `Context` sections.
- [x] `decree ddd` defaults to active sprint execution items when sprint mode is
  enabled and still presents the relevant PRD/ADR context.
- [ ] Governance commands (`why`, `refs`, `intent-check`, `intent-review`,
  `health`, `index verify`, `commit-check`) remain corpus-wide and are covered
  by tests proving sprint filters do not hide older decisions.
- [ ] MCP `progress` supports sprint scope parameters and matches CLI aggregate
  counts for active sprint, explicit sprint, backlog, and corpus modes.
- [x] `docs/index.md` and `docs/usage.md` document sprint initialization,
  default scoping, ledger outcomes, carryover semantics, and governance
  boundaries.

### Deferred (v2)

- [ ] Advisory health signal for detecting manual mutation of closed sprint
  records using git history.
- [ ] Velocity, estimates, assignees, calendar dates, and burndown reports.
- [ ] SQLite sprint tables for high-volume corpora if direct ledger reads become
  too slow.
- [ ] External issue tracker synchronization.
