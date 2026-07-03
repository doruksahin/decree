# Sprint-Scoped Execution Tracking — Handoff

**Date:** 2026-06-26
**Status:** Discussion draft
**Superseded by:** [2026-07-03-parallel-safe-sprint-ledger.md](2026-07-03-parallel-safe-sprint-ledger.md) and [ADR-01KWKXH8423XTBV6CDVXB4B2ZB](../../decree/adr/sprints/adr-01kwkxh8423xtbv6cdvxb4b2zb-directory-decomposed-sprint-ledger.md) — the `ledger.yaml` monolith described below is now the v2 directory store.
**Related docs:**
[PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ](../../decree/prd/prd-01kw1qezec1r1bstzn1ssppcej-sprint-scoped-execution-tracking.md),
[ADR-01KW1QGHBT2BSZ2HVT55G1QSJB](../../decree/adr/adr-01kw1qghbt2bsz2hvt55g1qsjb-sprint-ledger-and-carryover-semantics.md),
[SPEC-01KW1QJ27R175NVM8QNGW1FX8N](../../decree/spec/spec-01kw1qj27r175nvm8qngw1fx8n-sprint-ledger-cli-and-validation.md)

## Goal

Add sprint-aware execution tracking without turning sprints into governance
truth.

For end users, this means `decree progress` and `decree ddd` can focus on the
current sprint by default, while `decree why`, `decree refs`,
`decree intent-check`, `decree intent-review`, `decree health`, and index
verification still see the whole decision corpus.

The key distinction:

- PRD/ADR/SPEC references explain product and architecture intent.
- Sprint records explain when execution work was planned, finished, carried
  over, deferred, or dropped.

## What Changes For Existing Users

Nothing changes until a project explicitly enables sprint mode.

Existing repositories without `decree/sprints/ledger.yaml` keep current behavior:

```bash
decree progress   # whole corpus, as today
decree ddd        # whole corpus, as today
decree lint       # existing document checks only
```

Sprint mode starts only with:

```bash
decree sprint init "Sprint 1"
```

After that, sprint-specific invariants become part of `decree lint`, and
task-facing commands gain active-sprint defaults.

## New Mental Model

Sprint mode introduces a ledger at:

```text
decree/sprints/ledger.yaml
```

The ledger is the source of truth for:

- active or paused sprint mode
- sprint membership
- backlog membership
- draft-pool membership
- rollover outcomes
- carryover links
- closed-sprint snapshots

It is not a replacement for `references:` or `governs:`.

## Operating States

Once sprint mode is enabled, the ledger is always in one of two states.

**Active**

There is exactly one active sprint.

```bash
decree sprint status
```

Expected meaning: day-to-day sprint work is running. New SPECs can default into
the active sprint.

**Paused**

There is no active sprint, and the pause has an auditable reason.

```bash
decree sprint pause --reason "summer freeze"
decree sprint resume "Sprint 2"
```

Expected meaning: the project intentionally has no active sprint. During pause,
`decree new spec` must be explicit:

```bash
decree new spec "Future sync engine" --backlog --reason "not scheduled yet"
decree new spec "Experimental parser" --draft-pool --reason "speculative"
```

## New User-Facing Commands

Planned command namespace:

```bash
decree sprint init "Sprint 1"
decree sprint status
decree sprint pause --reason "summer freeze"
decree sprint resume "Sprint 2"
decree sprint add SPEC-... 
decree sprint add PRD-... --kind planning
decree sprint backlog SPEC-... --reason "not ready"
decree sprint draft SPEC-... --reason "speculative"
decree sprint defer SPEC-... --reason "blocked by API"
decree sprint drop SPEC-... --reason "no longer needed"
decree sprint rollover "Sprint 2" --outcomes outcomes.yaml
decree sprint list --sprint SPRINT-...
decree sprint list --backlog
```

The default executable task type is SPEC. PRD and ADR are context by default.
They can be tracked as planning work only when explicitly added as planning
items.

## Daily Workflow

Before sprint mode:

```bash
decree progress
```

shows all documents.

After sprint mode is enabled and active:

```bash
decree progress
```

shows active sprint execution work.

To see old behavior:

```bash
decree progress --corpus
```

To inspect other scopes:

```bash
decree progress --sprint SPRINT-...
decree progress --backlog
decree progress --draft-pool
decree progress --all-sprints
```

## Progress Output

Progress output should visibly separate work from context.

Example shape:

```text
Tasks
  SPEC-01...  Sprint Ledger CLI and Validation  draft  0% (0/27 primary)

Planning
  PRD-01...   Sprint-Scoped Execution Tracking  draft

Context
  PRD-01...   referenced by SPEC-01...
  ADR-01...   referenced by SPEC-01...
```

Only `Tasks` and explicit `Planning` items count toward scoped progress totals.
`Context` is explanatory only. A PRD appearing under `Context` does not mean it
is unfinished sprint execution work.

## Creating New Work

When sprint mode is active:

```bash
decree new spec "Add OAuth token rotation"
```

creates the SPEC and adds it to the active sprint.

When work should not enter the active sprint:

```bash
decree new spec "Add audit export" --backlog --reason "not scheduled yet"
decree new spec "Try alternate index design" --draft-pool --reason "spike only"
```

When sprint mode is paused, plain `decree new spec "Title"` fails because there
is no active sprint to receive it. The user must choose backlog or draft pool
explicitly.

## PRDs Across Sprints

A PRD is product intent, not sprint ownership.

Valid scenario:

1. Sprint 1 creates `PRD-A`.
2. Sprint 1 implements `SPEC-1` under `PRD-A`.
3. Sprint 2 creates `SPEC-2` under the same `PRD-A`.

This is not carryover. It is new work under existing product intent.

The rule:

```text
PRD history is not binding.
SPEC sprint history is binding.
```

## Same SPEC Across Sprints

The same SPEC can appear in multiple sprints only through explicit carryover.

Valid scenario:

1. `SPEC-X` starts in Sprint 1.
2. Sprint 1 closes.
3. Rollover records `SPEC-X` as carried over to Sprint 2 with a reason.
4. Sprint 2 receives `SPEC-X` as carryover.

Invalid scenario:

```text
SPEC-X appears in Sprint 1 and Sprint 2 with no carryover link.
```

Lint rejects that because it is silent history drift.

## Sprint Close And Rollover

Sprint rollover is deliberately strict.

```bash
decree sprint rollover "Sprint 2" --outcomes outcomes.yaml
```

Every open item must get an outcome:

- `completed`
- `carried_over`
- `deferred`
- `dropped`
- `superseded`

`carried_over`, `deferred`, `dropped`, and `superseded` require a reason.

`completed` requires proof, not a reason. At minimum, the close-time snapshot
must show primary acceptance criteria at 100%.

This prevents rollover pressure from turning partially done work into fake done.

## Completed Means Proven

The ledger stores a close-time snapshot:

```yaml
outcome:
  kind: completed
  at: 2026-06-26
  snapshot:
    status: approved
    primary_done: 10
    primary_total: 10
    deferred_done: 0
    deferred_total: 2
```

If `primary_done != primary_total`, `completed` is invalid.

Optional commit evidence can be recorded later, but v1 does not let commit
evidence replace acceptance-criteria completion.

## Backlog

Backlog is not a silent limbo.

Each backlog entry must record:

- `since`
- `source`
- `reason`
- optional `review_after`

Example:

```yaml
backlog:
  - document: SPEC-01...
    kind: execution
    source: deferred
    since: 2026-06-26
    review_after: 2026-07-26
    reason: blocked by upstream API contract
```

Old backlog entries produce visible warnings. They do not fail v1 lint by
default, but users should see that the backlog needs grooming.

## Draft Pool

Draft pool is for explicit no-sprint commitment.

Use it when a SPEC is speculative, exploratory, or intentionally not scheduled:

```bash
decree sprint draft SPEC-... --reason "spike only"
```

This avoids invisible open SPECs while still allowing non-sprint planning.

## What Lint Starts Checking

Only after sprint mode is initialized, `decree lint` also validates sprint
ledger consistency.

Hard errors include:

- active mode with no active sprint
- paused mode with an active sprint
- paused mode without `since` or `reason`
- more than one active sprint
- closed sprint item without outcome
- completed outcome without 100% primary AC proof
- carryover without a reason
- non-linear carryover chain
- same document in active sprint and backlog/draft pool
- backlog entry missing `since`, `source`, or `reason`
- non-terminal SPEC created after sprint mode but absent from active sprint,
  backlog, and draft pool
- PRD/ADR added as execution work instead of planning work

Warnings include:

- backlog entries older than the configured review threshold

## What Does Not Change

Governance stays corpus-wide.

These commands do not hide older decisions behind the active sprint:

```bash
decree why src/foo.py
decree refs SPEC-...
decree intent-check --plan "..." --files src/foo.py
decree intent-review --diff-base origin/main
decree health
decree index verify
decree commit-check --diff-base origin/main
```

This is intentional. A decision from Sprint 1 can still govern code changed in
Sprint 9.

## Agent Workflow

Agents should treat sprint mode as execution scope, not decision authority.

Typical active sprint loop:

```bash
decree progress
decree ddd
decree why src/decree/commands/progress.py
decree intent-check --plan "..." --files src/decree/commands/progress.py
```

The first two are sprint-scoped by default. The latter two remain corpus-wide.

## Migration Path

Existing repositories need no migration until they opt in.

Opt-in path:

1. Run `decree sprint init "Sprint 1"`.
2. Add current in-flight SPECs to the active sprint.
3. Put intentionally unscheduled SPECs in backlog or draft pool with reasons.
4. Run `decree lint`.
5. Use `decree progress --corpus` when reviewing historical corpus-wide state.

## Discussion Points

These are worth deciding before implementation:

- Should backlog age warnings be configurable in `decree.toml`, the sprint
  ledger, or both?
- Should `completed` require `status: implemented` in addition to 100% primary
  ACs, or is the snapshot enough for v1?
- Should `decree sprint pause` require the active sprint to be closed first, or
  should it be allowed to pause an active sprint with all open items preserved?
- Should repeated carryover produce warning after one carryover or after a
  configurable threshold?
- Should planning items have their own progress accounting, or only status
  display?

## Summary

End users get a current-work view without losing the whole decision graph.

The main behavioral change after opt-in:

```text
progress/ddd default to active sprint
governance remains corpus-wide
completed requires proof
backlog requires accountability
paused mode handles intentional no-sprint periods
```

This keeps sprint tracking useful for daily work while preserving Decree's core
promise: decisions remain traceable beyond a single sprint.
