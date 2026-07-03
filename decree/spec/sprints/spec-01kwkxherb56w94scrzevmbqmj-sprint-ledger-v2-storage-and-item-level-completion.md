---
date: '2026-07-03'
governs:
- src/decree/sprints.py
- src/decree/cli.py
- src/decree/commands/sprint.py
- src/decree/commands/new.py
- src/decree/commands/migrate.py
- src/decree/commands/generate_html.py
- docs/architecture.md
- docs/index.md
- docs/usage.md
- tests/test_cli.py
- tests/test_generate_html.py
- tests/test_sprint.py
- tests/test_sprint_migrate.py
- tests/test_sprint_parallel.py
id: SPEC-01KWKXHERB56W94SCRZEVMBQMJ
references:
- PRD-01KWKXH2EX1WH7XWXCNKSMRW24
- ADR-01KWKXH8423XTBV6CDVXB4B2ZB
status: implemented
---

# SPEC-01KWKXHERB56W94SCRZEVMBQMJ Sprint Ledger v2 Storage and Item-Level Completion

## Overview

Replace the monolithic `decree/sprints/ledger.yaml` with a directory store
(schema `decree.sprints.v2`) in which sprint lifecycle state, each live
membership, and each closed sprint live in separate files. Add mid-sprint
`sprint complete` and `sprint drop` commands, rebase all validation
invariants onto the new layout, and ship a one-shot `decree migrate
sprint-ledger` command. All v1 invariants are preserved; only the storage and
the previously impossible item-level outcomes change.

## Technical Design

### Storage layout

```text
decree/sprints/
  state.yaml                # changes only at init/pause/resume/rollover
  live/<DOC-ID>.yaml        # one file per live membership (uppercase doc id)
  closed/<SPRINT-ID>.yaml   # one append-only archive per closed sprint
```

`state.yaml` holds the lifecycle state:

```yaml
schema: decree.sprints.v2
mode: enabled
state: active            # or: paused
active:                  # present iff state == active
  id: SPRINT-01ABC...
  name: Sprint 2 - Sprint Ledger Completion
  started: '2026-06-26'
paused:                  # present iff state == paused
  since: '2026-07-03'
  reason: summer freeze
```

Each `live/<DOC-ID>.yaml` file is one membership record:

```yaml
document: SPEC-01ABC...   # must equal the filename stem (uppercase)
scope: active             # active | backlog | draft_pool
kind: execution           # execution | planning
source: new               # manual | new | carryover | deferred
added: '2026-07-03'
since: '2026-07-03'       # backlog only
reason: not ready yet     # required for backlog and draft_pool
review_after: '2026-08-01'      # optional, backlog only
carryover_from: SPRINT-01ABC... # optional; scope=active carryover items only
outcome:                  # optional; presence means the item is resolved
  kind: completed         # mid-sprint set: completed | dropped only
  at: '2026-07-03'
  reason: required for dropped
  evidence:
    commits: []
  snapshot:
    status: draft
    primary_done: 10
    primary_total: 10
    deferred_done: 0
    deferred_total: 2
```

Key semantics:

- A live file with an `outcome` block no longer counts as live membership; it
  is a resolved record awaiting fold at the next rollover or pause.
- Live scope=active items record no sprint ID. They belong to whichever
  sprint is active at integration time; sprint attribution is written only
  when the sprint closes and the item folds into `closed/`.
- `closed/<SPRINT-ID>.yaml` keeps exactly the v1 closed SprintRecord shape:
  `id`, `name`, `status: closed`, `started`, `closed`, and `items[]` where
  every item has a mandatory outcome (kind/at/reason/to_sprint/to_document/
  evidence/snapshot) plus `carryover_from` where applicable. Chronological
  sprint order is the ULID-lexicographic order of the filenames.

### In-memory model and write API

`sprints.py` is rewritten around frozen dataclasses:

- `SprintState` mirrors `state.yaml`.
- `LiveItem` mirrors a `live/*.yaml` file, unifying the v1 SprintItem,
  BacklogItem, and DraftPoolItem shapes.
- `SprintRecord` and `SprintItem` are kept unchanged for closed archives.
- `LedgerView` assembles `{state, live: dict[doc_id -> LiveItem], closed:
  tuple[SprintRecord, ...]}` with helpers: `active_items`,
  `active_open_items` (outcome is None), `active_done_items`,
  `backlog_items`, `draft_pool_items`, and `live_membership()` which counts
  only outcome-less files.

I/O functions write only the affected file:

- `load_state(root)` — cheap read of `state.yaml` only (used by new-document
  gating).
- `load_view(root)` — assemble the full directory.
- `save_state(state, root)` — tempfile+rename under `_ledger_lock(root)`.
- `create_live_item(item, root)` — `os.open(O_CREAT|O_EXCL|O_WRONLY)` for an
  atomic exists-check; raises `SprintLedgerError` if the document already has
  any live file, with a message that distinguishes outcome-bearing files
  ("resolved record folds at next rollover").
- `rewrite_live_item(item, root)` — tempfile+rename; used by complete/drop.
- `remove_live_item(doc_id, root)` — fold-time only (rollover/pause).
- `write_closed_sprint(record, root)` — new archive file; error if it exists.
- `_ledger_lock(root)` — context manager taking `fcntl.flock` EX on
  `.decree/sprints.lock` (derived state, gitignored — never committed with the
  store); on ImportError (no fcntl) it yields without locking as a documented
  no-op. Used by init/pause/resume/rollover and the mid-sprint
  `complete`/`drop` rewrites.

v1 handling: `LEDGER_REL_PATH` is kept only for detection and the migrate
command's private reader. Every sprint entry point raises `SprintLedgerError`
("sprint ledger v1 detected; run `decree migrate sprint-ledger`") when
`ledger.yaml` exists and `state.yaml` does not. `sprint_mode_enabled(root)`
returns True if either file exists, so lint surfaces the migration error
loudly instead of silently skipping sprint checks; `validate_ledger` returns
that error as its single error in that case.

### Operation semantics

- `init_ledger(name, root, today)` — creates `sprints/live` and
  `sprints/closed`, writes `state.yaml`; errors if `state.yaml` or a v1
  `ledger.yaml` exists.
- `add_to_active_sprint(document, kind, source, root, today)` — requires
  active state; creates a scope=active live file with a structural duplicate
  check.
- `add_to_backlog(...)` / `add_to_draft_pool(...)` — create a live file with
  the scope, reason, and (for backlog) `since`; allowed while paused, as in
  v1.
- `complete_item(document, commits, root, today)` — new. The item must be a
  live scope=active outcome-less item; a snapshot is taken and the primary
  acceptance criteria must be 100% (reusing the exact v1 message "cannot be
  completed unless primary acceptance criteria are 100%"); the outcome
  `{kind: completed, at, evidence: {commits}, snapshot}` is written via
  `rewrite_live_item`, touching only that item's own file. Works for
  execution and planning items.
- `drop_item(document, reason, root, today)` — new; same mechanics with
  `kind: dropped`, a required reason, and a snapshot recorded for audit.
- `pause_ledger(reason, root, today)` — requires active state; every
  scope=active item must already carry an outcome (open items produce the
  error "cannot pause with open active-sprint items; complete, drop, or
  rollover them first"); folds the resolved items into
  `closed/<active-id>.yaml` with `closed=today`, removes their live files,
  and sets state to paused. Runs under the lock.
- `resume_ledger(name, root, today)` — paused to active with a fresh
  SPRINT-ULID.
- `rollover_ledger(name, outcomes, docs, root, today)` — the outcomes file
  must cover exactly the open active items; items completed or dropped
  mid-sprint are already resolved (missing/extra errors keep v1 wording).
  Builds the closed record from the active state plus all active items,
  enforces the 100% completed gate, writes the archive, removes folded live
  files, creates carryover live files (scope=active, source=carryover,
  `carryover_from` set to the old sprint id, `added=today`), and updates
  `state.active`. Runs under the lock. A `carried_over` outcome's `to_sprint`
  is the new sprint id.
- `select_sprint_scope(docs, args, root)` — signature and `SprintScope` shape
  unchanged. Default scope: live scope=active outcome-less items. `--sprint
  ID` for the active id includes all active items (resolved ones too);
  otherwise it reads the closed archive. `--all-sprints` covers archives plus
  active items; `--backlog`/`--draft-pool` select live files by scope; the
  paused-default error text matches v1.
- `load_outcomes_file(path)` — unchanged.

### Validation invariants

Kept (rebased onto the layout):

- schema and mode checks; active state requires a complete `active` block;
  paused requires `since` and `reason`; paused forbids scope=active live
  files.
- live filename stem equals the `document` field (uppercase), the id is
  canonical, the document exists in the corpus, `kind` is valid, and
  execution items are SPECs.
- backlog requires source/since/reason with the 30-day age warning
  (hardcoded); draft_pool requires reason.
- closed archives: status closed, closed date present, every item has an
  outcome, outcome validation including the completed gate ("completed
  outcome requires snapshot primary progress at 100%").
- carryover linearity across ULID-ordered archives; the last archive may
  target the current active sprint id, in which case a matching live file
  with `carryover_from` is required.
- stale-reference health for live active outcome-less items (message kept).
- enrollment coverage keeps the message "must be in active sprint, backlog,
  or draft_pool"; a document satisfies enrollment if it has any live file
  (any scope, resolved or not) or appears in any closed archive.
  `first_started` is the minimum of archive starts and the active start.

Changed:

- The v1 error "active sprint item must not have outcome" is deleted. Live
  outcome kinds are restricted to `{completed, dropped}`; any other kind in a
  live file is an error.
- An outcome is only legal on scope=active live files.
- The terminal-SPEC-as-live-item error applies only to outcome-less items.
- One-active-sprint becomes structural: no archive may have a status other
  than closed, no archive id may equal `state.active.id`, and archive ids
  must be unique.
- Duplicate live membership becomes structural, with a defensive error kept
  for two live files declaring the same `document` field (filename mismatch
  case).
- New: malformed YAML or non-mapping live/closed files produce a per-file
  error instead of a crash.

### CLI additions

- `sprint` parser description rewritten for the directory store; `sprint
  init` creates `state.yaml`.
- New `sprint complete DOCUMENT [--commit SHA]...` — `--commit` repeatable as
  evidence; records a completed outcome for one item mid-sprint; requires
  100% primary acceptance criteria.
- New `sprint drop DOCUMENT --reason TEXT` — mid-sprint dropped outcome.
- `sprint pause` help updated: pausing is possible after every active item is
  completed, dropped, or rolled over.
- `sprint rollover --outcomes` help updated: the file maps each open active
  sprint document; items completed or dropped mid-sprint are already
  resolved.
- `sprint status` prints state, active sprint id/name, open items, done items
  ("done (awaiting rollover)"), and backlog/draft-pool counts.
- New `migrate sprint-ledger` parser: required mutually exclusive `--dry-run`
  | `--apply`, plus `--project PATH` (default cwd); no `--json`, matching
  `migrate ids`. Wired into the migrate dispatch with an updated namespace
  description.
- `commands/sprint.py` gains complete/drop branches and ports all existing
  branches to the new API, keeping the draft-pool/draft alias handling.
- `commands/new.py` gates on the cheap `load_state` and writes enrollment as
  one live file; error text unchanged.
- `commands/generate_html.py` builds the board from `load_view`, synthesizing
  the active SprintRecord from state plus live active items and reading
  closed records from ULID-sorted archives (active last); backlog/draft_pool
  come from live files. The `decree.board.v1` payload is unchanged; the
  default selected sprint is the active one, falling back to the last closed.
- `commands/mcp_server.py` needs no change (insulated via
  `progress_for_scope`).

### Migration algorithm

`migrate_sprint_ledger_run(args)` in `commands/migrate.py` uses a private v1
reader (the v1 `from_raw` parsing moves into migrate.py or a module-private
v1 section of sprints.py). The plan maps:

- each closed sprint to `closed/<SPRINT-ID>.yaml`;
- the active sprint to `state.yaml` (`active: {id, name, started}`) plus one
  `live/<DOC-ID>.yaml` per item with scope=active, preserving kind, source,
  added, and `carryover_from` (v1 guarantees active items are outcome-less);
- backlog entries to scope=backlog live files (since/review_after/reason/
  source preserved);
- draft_pool entries to scope=draft_pool live files.

`--dry-run` prints the plan (files to create, `ledger.yaml` removal) and
writes nothing, exiting 0. `--apply` guards that `state.yaml` is absent and
`ledger.yaml` is present (otherwise exit 2 with a message), writes all files,
deletes `ledger.yaml`, prints a summary, then runs `validate_ledger` and
exits 1 on errors, 0 when clean. The plan/apply structure follows `migrate
ids`.

## Testing Strategy

Follow the binding conventions in tests/CLAUDE.md: module-level helpers,
all-zero ULIDs, `monkeypatch.chdir(tmp_path)`, in-process
`<module>.run(argparse.Namespace(...))` with every flag defaulted,
capsys+json parsing, exit-code assertions, and model inspection through
`load_view`/`validate_ledger`. Error-message substrings are load-bearing.

Rewrite the eight inline v1 ledger fixtures (seven in `tests/test_sprint.py`,
one in `tests/test_generate_html.py`) to v2 through one shared helper such as
`_write_v2_ledger(root, state=..., live=[...], closed=[...])`. New test
areas: storage round-trip and per-file malformed/mismatch errors; init;
v1-detection errors from lint, sprint status, and `decree new spec`; complete
(happy path writing only its own file, sub-100% gate refusal, planning items,
already-resolved refusal, not-in-active refusal, post-complete lint/scoping/
snapshot-immutability behavior); drop; pause folding resolved items and
refusing open ones; rollover covering only open items with carryover live
files and archives; migration of a dogfood-shaped fixture plus dry-run and
guard exits; every validation invariant positive and negative; a no-git
parallel-union simulation of two project copies; lock acquisition (skipped
without fcntl); and CLI help smoke tests for the new subcommands. The CLI/MCP
parity and generate-html board tests stay green on v2 fixtures, and the
tests/CLAUDE.md test map gains the new rows.

## Acceptance Criteria

- [x] The v2 directory store round-trips: `load_view` reads what
  `save_state`/`create_live_item`/`rewrite_live_item`/`write_closed_sprint`
  wrote, and writes touch only the affected file.
- [x] With a v1 `ledger.yaml` present and no `state.yaml`, lint, `sprint
  status`, and `decree new spec` all fail (exit 1) with an error pointing at
  `decree migrate sprint-ledger`.
- [x] `decree sprint complete DOC` refuses items below 100% primary
  acceptance criteria and, on success, writes the completed outcome plus
  snapshot into that item's own live file only.
- [x] `decree sprint drop DOC --reason TEXT` records a dropped outcome with
  the reason and a snapshot.
- [x] `decree sprint pause` refuses while open active items exist and folds
  resolved items into the closed archive when none remain open.
- [x] `decree sprint rollover` requires outcomes for exactly the open items,
  folds pre-resolved items with their mid-sprint outcomes, creates carryover
  live files with `carryover_from`, and writes the closed archive.
- [x] `decree migrate sprint-ledger --apply` migrates this repository's own
  v1 ledger to a v2 store that passes `validate_ledger`, and removes
  `ledger.yaml`; `--dry-run` writes nothing.
- [x] The parallel union simulation passes: two copies of a project each
  create a different SPEC with its live file, the files are unioned back,
  and lint is green with both items in scope.
- [x] All documentation surfaces and CLI help texts describe the v2 store,
  `sprint complete`/`sprint drop`, and `migrate sprint-ledger`.

### Deferred

- [ ] Multiple active sprints or per-worktree lanes.
- [ ] Reopen semantics for terminal SPECs.
- [ ] Mid-sprint carried_over/deferred/superseded outcomes (rollover-only).
- [ ] `sprint list` subcommand and decree.toml sprint configuration keys.
- [ ] Windows file locking (fcntl-less platforms run the documented no-op).
- [ ] `--json` output for sprint subcommands and `migrate sprint-ledger`.
