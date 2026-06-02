---
date: '2026-06-02'
governs:
- src/decree/commands/mcp_server.py
- src/decree/commands/intent_check.py
- src/decree/commands/progress.py
- src/decree/cli.py
id: SPEC-01KT3M6NY02TXXPJCP52QEYFW1
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- PRD-01KT22NMRSXYT95XE808VD8EV4
- ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV
status: implemented
---

# SPEC-01KT3M6NY02TXXPJCP52QEYFW1 Agentkith parallel-session MCP support

## Overview

Extends decree's MCP surface so a parallel-agent host (e.g. the Agentkith
canvas, which runs many concurrent Claude/Codex coding sessions) can govern a
session across its whole lifecycle — *plan → isolate → run → close* — without
re-implementing decree's logic or shelling out to parse human-formatted text.

It delivers the next slice of PRD-01KT22NMRS4QGHSFDBZ858PP1T **R5 (MCP server
with task-shaped tools)** by adding the two tools the closeout phase needs, and
the next slice of PRD-01KT22NMRSXYT95XE808VD8EV4 (decision reasoning) by
teaching `intent_check` to answer the question decision-level governance cannot:
*"is another session that is running right now also about to write one of my
files?"* The architectural choice behind that last piece — that decree computes
the overlap from caller-supplied state but never tracks session state itself —
is recorded in ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV.

This SPEC covers only the **decree side** (library + MCP tools + CLI parity).
The Agentkith app wiring that consumes these tools is explicitly deferred (see
the deferred section) — it lives in the app repository, not here.

## Technical Design

Three additive, backward-compatible changes:

### 1. Cross-session live-conflict detection in `intent_check`
- New keyword-only param `other_active_files: dict[str, list[str]] | None`
  on the `intent_check()` library function and the `intent_check` MCP tool —
  a mapping of *other* live session id → the paths that session plans to write.
- decree intersects each entry with `planned_files` and returns a **new,
  separate** `live_conflicts` field on `IntentCheckReport`
  (`LiveSessionConflict(path, session_ids)`), kept distinct from the
  governance `conflicts` array per ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV (option C —
  overloading `Conflict.decision_ids` with session ids — was rejected).
- A new recommendation verb `isolate_session` is emitted per overlap.
- decree stores nothing: when `other_active_files` is `None` (every existing
  caller) behaviour is unchanged and `live_conflicts` is empty.
- `report_to_dict` serializes `live_conflicts`; the CLI exit code, its docstring,
  and the info log now also trip on a live overlap.

### 2. `progress` MCP tool
- Wraps a new pure-library helper `progress.progress_for_scope(*, doc_id,
  chain_id)` (no stdout) that mirrors the CLI's `--doc`/`--chain` scoping and
  returns per-document + aggregate primary/deferred acceptance-criteria counts.
- Reads documents from disk via the parser (not the SQLite index), so it is the
  one query path that does not require a built index; an unknown id returns a
  structured `{"error": ...}` dict rather than raising.

### 3. `report` MCP tool
- Wraps `report.regenerate_reports(...)` to emit per-decision completion-report
  artifacts (the auditable closeout handoff). It is the only **write** tool on
  the server; `dry_run=True` previews without touching disk.

### CLI parity
- `decree intent-check --other-active-files '<json>'` accepts a JSON object of
  `{session_id: [paths]}`, so the library, the MCP tool, and the CLI expose the
  same capability (no silent agent-vs-CLI asymmetry). Invalid JSON exits 2.

## Testing Strategy

- Unit tests for the library: `other_active_files` overlap math (empty default,
  single overlap + `isolate_session`, multiple sessions sorted), and the stable
  `report_to_dict` schema including `live_conflicts`
  (`tests/test_intent_check.py`).
- CLI tests: `--other-active-files` surfaces `live_conflicts` and trips exit 1;
  invalid JSON exits 2 (`tests/test_intent_check.py::TestIntentCheckCLI`).
- MCP tests: `progress` (all/doc/unknown-id), `report` (dry-run), and
  `intent_check` live-conflict round-trip, plus the tool-registry count and the
  5-section docstring assertions for the new tools (`tests/test_mcp_server.py`).
- Full suite green (600 tests) and `decree lint` clean; one Towncrier fragment
  added (`changelog.d/+agentkith-mcp-integration.feature`).

## Acceptance Criteria

- [x] `intent_check()` accepts opt-in `other_active_files` and returns a separate `live_conflicts` field (governance `conflicts` left untouched)
- [x] An `isolate_session` recommendation is emitted, one per live overlap
- [x] `report_to_dict` serializes `live_conflicts`; the `--json`/MCP schema change is additive and backward compatible
- [x] `progress` MCP tool returns structured per-doc/chain/corpus acceptance-criteria counts and a structured error on unknown id
- [x] `report` MCP tool regenerates completion reports and honors `dry_run`
- [x] `intent_check` MCP tool exposes `other_active_files` with a 5-section docstring
- [x] `decree intent-check --other-active-files` gives CLI parity (library, MCP, CLI agree); invalid JSON exits 2
- [x] CLI exit code, `intent_check_run` docstring, and info log reflect the live-conflict blocker
- [x] Unit + CLI + MCP protocol tests added and the full suite passes (600); changelog fragment added
- [x] The cross-session design decision is recorded in ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV

## What this does NOT do (deferred to the Agentkith app repository)

These are consumer-side wiring tasks; they belong to the Agentkith app, not the
decree corpus, and are tracked here only for traceability.

- [ ] App writes a `decree mcp serve` entry into the per-session MCP config it generates for Claude/Codex
- [ ] App calls `intent_check` (with `other_active_files`) before a worktree-bound session launches
- [ ] App maintains a live registry of each running session's planned files to feed `other_active_files`
- [ ] App runs `progress` / `intent_review` / `report` on the session-shutdown event for closeout evidence
- [ ] App loads the real decree graph on project open (replaces the hardcoded `DecreeGraphView`)
