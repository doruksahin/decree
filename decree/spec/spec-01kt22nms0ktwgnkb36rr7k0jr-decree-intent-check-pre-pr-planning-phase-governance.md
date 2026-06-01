---
date: '2026-05-12'
governs:
- src/decree/commands/intent_check.py
id: SPEC-01KT22NMS0KTWGNKB36RR7K0JR
references:
- PRD-01KT22NMRSXYT95XE808VD8EV4
status: implemented
---

# SPEC-01KT22NMS0KTWGNKB36RR7K0JR decree intent-check — Pre-PR Planning-Phase Governance

## Overview

Implements PRD-01KT22NMRSXYT95XE808VD8EV4 R2. `decree intent-check` is the
planning-phase counterpart to `decree intent-review`: before code is written,
an agent provides a plan and the files it expects to touch, and decree returns
the decisions that govern those files.

The command is deterministic. It does not call LLM providers, resolve models,
read API keys, or shell out to agent runtimes. Structural conflicts are always
reported as structural conflicts. If an agent wants semantic conflict judging,
it should post-process `decree intent-check --json` outside core decree.

## Technical Design

CLI:

```bash
decree intent-check \
  --plan "Change token refresh storage" \
  --files src/auth/tokens.py tests/test_tokens.py \
  [--with-abstention] \
  [--json] \
  [--project PATH]
```

The report includes:

- `planned_files`
- governing decisions from `governs:` lookups
- stale governance entries
- unchecked acceptance criteria for non-terminal governing docs
- structural conflicts when multiple decisions govern the same planned path
- optional calibrated abstention for ungoverned paths
- recommended actions such as `draft_adr_first`, `update_spec_first`,
  `check_ac`, `update_decision`, `resolve_conflict_first`, and `proceed`

Structural conflict detection is SQL over the SQLite index. It does not infer
whether two decisions are semantically compatible; the deterministic obligation
is to surface the overlap so the agent/user can resolve or justify it.

## Testing Strategy

- Library tests cover empty inputs, governed paths, unchecked ACs,
  architecture-keyword recommendations, deduped planned files, stale
  governance, and structural conflicts.
- CLI tests cover clean exit, conflict exit, JSON shape, missing index, and
  stale index behavior.
- MCP tests cover the same deterministic report shape through the tool wrapper.
- No provider mocks or live LLM calls are used in CI.

## v1 Acceptance Criteria

- [x] `decree intent-check` subcommand registered with deterministic flags.
- [x] `--plan` is required.
- [x] `--files` accepts one or more repo-relative paths.
- [x] Command returns governing decisions for planned files.
- [x] Command surfaces unchecked acceptance criteria for non-terminal governing
  docs.
- [x] Command surfaces stale governance using indexed git history.
- [x] Command surfaces structural conflicts when multiple decisions govern a
  planned path.
- [x] Command supports `--with-abstention`.
- [x] Command supports `--json`.
- [x] Command fails closed when the SQLite index is missing or stale.
- [x] MCP `intent_check` exposes the deterministic report shape.
- [x] Core implementation does not call LLM providers or resolve provider
  models.
- [x] Tests cover structural conflict behavior without provider mocks.

## Deferred

- Add an external agent skill for semantic conflict judging over
  `decree intent-check --json`.
- Add calibrated semantic conflict evaluation only if a labeled corpus exists.
