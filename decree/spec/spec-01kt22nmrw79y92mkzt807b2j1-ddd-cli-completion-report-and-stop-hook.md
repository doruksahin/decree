---
date: '2026-05-12'
governs:
- src/decree/commands/ddd.py
- src/decree/commands/hook.py
- src/decree/commands/report.py
- scripts/hooks/decree-ddd-stop.sh
id: SPEC-01KT22NMRW79Y92MKZT807B2J1
references:
- PRD-01KT22NMRR0BX7KBF0F0N5ER6Z
status: implemented
---

# SPEC-01KT22NMRW79Y92MKZT807B2J1 DDD CLI, Completion Report, and Stop Hook

## Overview

Implements PRD-01KT22NMRR0BX7KBF0F0N5ER6Z (DDD CLI Command and Proofshot Integration). Three deliverables ship in this SPEC:

1. **`decree ddd` CLI command** — ports the phase-detection logic currently in the `/decree:ddd` skill (markdown instructions) to Python, exposed as a first-class CLI subcommand. Offline, no LLM calls, supports `--json` for agent consumers.
2. **Claude Code stop hook** — a shell wrapper that runs `decree ddd` at session end and writes a starting-point summary for the next session.
3. **Completion report on terminal-status transition** — when a document transitions to a terminal-success status (e.g., `decree status SPEC-<ULID> implement`), decree writes a markdown report capturing the document chain, AC state, and timestamps.

All three are additive — existing decree behavior is unchanged. No new third-party dependencies; the SPEC reuses decree's existing stack (`pydantic`, `python-frontmatter`, stdlib).

## Technical Design

### Component 1: `decree ddd` CLI command

#### CLI surface

```
decree ddd [--json] [--quiet] [--project PATH]
```

- `--json` — structured JSON output (for stop hook + agents). Schema specified below.
- `--quiet` — suppress phase explanations; print only the structured summary line + next action.
- `--project PATH` — operate against a project at PATH instead of cwd (useful for the stop hook, which may run from outside the project directory).

Exit codes:
- `0` — corpus is healthy: `decree lint` passes, no stale state detected, at least one document or empty corpus.
- `1` — lint errors present, OR stale state detected per any R6 coherence gate that is enabled in `decree.toml`. (Until PRD-01KT22NMRS4QGHSFDBZ858PP1T R6 ships, the staleness check is "approved PRD with no referencing ADR after N days" — implemented inline in this SPEC as a simple check, refactored later when R6 ships.)

#### Phase-detection logic

The existing `/decree:ddd` skill defines seven phases (Phase 0 through Phase 6 in its decision tree). Port them verbatim into `src/decree/commands/ddd.py`:

| Phase | Condition | Next action |
|---|---|---|
| 0 — IDEATION | All `dir`s empty (or contain only `index.md`) | `decree new prd "<title>"` |
| 1 — ARCHITECTURE DECISIONS | PRD exists, no ADR has `references: [PRD-<ULID>]` | `decree new adr "<title>"` referencing the PRD |
| 2 — TECHNICAL DESIGN | ADR `accepted`, no SPEC has `references: [ADR-<ULID>]` | `decree new spec "<title>"` referencing the ADR |
| 3 — PLANNING | SPEC exists with checkboxes, 0% progress | Write implementation plan or start implementing |
| 4 — IMPLEMENTATION | SPEC has 1-99% progress | List unchecked items |
| 5 — COMPLETION | SPEC at 100% checkboxes | `decree status SPEC-<ULID> implement` |
| 6 — DONE | All documents in terminal-but-healthy states | Optionally: start a new PRD |

Phase detection is "first match wins" in the order above — projects with multiple in-flight chains report the *highest-urgency* phase (Phase 4 trumps Phase 1 if both are present).

#### Internal API (Python)

```python
# src/decree/commands/ddd.py

from dataclasses import dataclass
from enum import Enum

class Phase(Enum):
    IDEATION = "ideation"
    ARCHITECTURE_DECISIONS = "architecture_decisions"
    TECHNICAL_DESIGN = "technical_design"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    COMPLETION = "completion"
    DONE = "done"

@dataclass(frozen=True)
class DocumentChain:
    prd: DocumentSummary | None
    adrs: tuple[DocumentSummary, ...]
    specs: tuple[DocumentSummary, ...]

@dataclass(frozen=True)
class DDDAssessment:
    phase: Phase
    project_path: Path
    documents: dict[str, int]      # {"prd": 4, "adr": 2, "spec": 1}
    progress: ProgressSummary       # {"completed": 32, "total": 54, "percent": 59}
    chains: tuple[DocumentChain, ...]
    suggested_actions: tuple[Suggestion, ...]
    health: HealthSummary           # {"lint_errors": 0, "stale_docs": 0}

def assess(project_path: Path) -> DDDAssessment: ...
def format_human(assessment: DDDAssessment, quiet: bool = False) -> str: ...
def format_json(assessment: DDDAssessment) -> str: ...
```

The `assess()` function reuses existing decree internals — it calls the in-process equivalents of `decree lint` and `decree progress`, not subprocesses. This matters because the stop hook will call `decree ddd` frequently; subprocess startup cost compounds.

#### JSON schema

```json
{
  "phase": "implementation",
  "project_path": "/Users/doruk/Desktop/SIDE_HUSTLE/decree",
  "documents": {"prd": 4, "adr": 2, "spec": 1},
  "progress": {"completed": 32, "total": 54, "percent": 59},
  "chains": [
    {
      "prd": {"id": "PRD-01KT22NMRR63TXR7NX5XYRG5FK", "status": "approved", "title": "C4 Architecture Support"},
      "adrs": [{"id": "ADR-01KT22NMRV7GMAXKWSBEEN68KE", "status": "accepted", "title": "Coupled C4 Module..."}],
      "specs": [{"id": "SPEC-01KT22NMRWENYKC3MGRA50M7GE", "status": "draft", "progress_percent": 86, "title": "C4 Validation..."}]
    }
  ],
  "suggested_actions": [
    {"action": "complete_spec", "spec_id": "SPEC-01KT22NMRWENYKC3MGRA50M7GE", "remaining_items": 5},
    {"action": "start_spec", "prd_id": "PRD-01KT22NMRR0BX7KBF0F0N5ER6Z"}
  ],
  "health": {"lint_errors": 0, "stale_docs": 0}
}
```

The schema is locked-in by a `pydantic` model in `src/decree/commands/ddd.py` so consumers can rely on it.

### Component 2: Claude Code stop hook

#### Shape

A bash wrapper at `scripts/hooks/decree-ddd-stop.sh` (shipped with decree) that:

1. Detects whether the current directory has a `decree.toml` — if not, exits 0 because the hook is opt-in per project. Set `DECREE_HOOK_DEBUG=1` to print the skip reason.
2. Runs `decree ddd --quiet` capturing stdout.
3. Writes the output to `${HOME}/.claude/projects/<project-hash>/decree-ddd-snapshot.md` — the location Claude Code's next-session startup hook reads for context.
4. Exits 0 regardless of `decree ddd`'s exit code (the hook is informational, not a gate).

#### Installation

```
decree hook install --type=claude-stop
decree hook install --type=claude-stop --uninstall
```

- Modifies `.claude/settings.json` in the project to add a `Stop` hook entry pointing to the shipped script.
- Idempotent — re-running install is a no-op if the hook is already configured.
- Validates `.claude/settings.json` against a JSON schema before writing (refuses to corrupt the file).

Alternative shape (documented but not implemented in v1): consumers may manually add the hook to `~/.claude/settings.json` (global) or `.claude/settings.json` (project) per Claude Code's hook documentation.

#### Hook script (shipped with decree)

```bash
#!/usr/bin/env bash
# decree-ddd-stop.sh — Claude Code stop hook
set -euo pipefail

# Find the project root (walks upward looking for decree.toml)
PROJECT_ROOT="$(decree find-root 2>/dev/null || true)"
if [[ -z "$PROJECT_ROOT" ]]; then
  exit 0  # not a decree-enabled project; no-op by hook contract
fi

# Compute the snapshot path
PROJECT_HASH="$(echo -n "$PROJECT_ROOT" | sha256sum | head -c 16)"
SNAPSHOT_DIR="${HOME}/.claude/projects/${PROJECT_HASH}"
mkdir -p "$SNAPSHOT_DIR"

# Run decree ddd and capture
decree ddd --quiet --project "$PROJECT_ROOT" > "${SNAPSHOT_DIR}/decree-ddd-snapshot.md" 2>/dev/null || true

exit 0
```

`decree find-root` is a new minor command added by this SPEC (~10 LOC — walks upward looking for `decree.toml`). It's also useful standalone.

### Component 3: Completion report on terminal-status transition

#### Trigger

When `decree status <DOC-ID> <action>` transitions a document to a terminal-success status (e.g., SPEC `implemented`, PRD `implemented`), decree writes a completion report to `<dir>/<id>-report.md` adjacent to the document.

Terminal-success statuses are detected via decree.toml — any status that has no outgoing transitions defined in `[types.<type>.transitions]` *and* is not explicitly marked terminal-failure (like `rejected`, `archived`). For now, the heuristic is "status `implemented` for PRD/SPEC; status `accepted` for ADR." Configurable in v2 if needed.

#### Report contents

```markdown
# SPEC-01KT22NMRWENYKC3MGRA50M7GE Completion Report

**Document**: `decree/spec/spec-01kt22nmrwenykc3mgra50m7ge-c4-validation-and-diagram-generation.md`
**Transitioned to `implemented` on**: 2026-05-15
**Total documents in chain**: 3 (PRD-01KT22NMRR63TXR7NX5XYRG5FK ← ADR-01KT22NMRV7GMAXKWSBEEN68KE ← SPEC-01KT22NMRWENYKC3MGRA50M7GE)

## Document chain

| Type | ID | Status | Title |
|---|---|---|---|
| PRD | PRD-01KT22NMRR63TXR7NX5XYRG5FK | approved | C4 Architecture Support |
| ADR | ADR-01KT22NMRV7GMAXKWSBEEN68KE | accepted | Coupled C4 Module vs Plugin Architecture |
| SPEC | SPEC-01KT22NMRWENYKC3MGRA50M7GE | implemented | C4 Validation and Diagram Generation |

## Acceptance Criteria

### Primary v1 (32/32 complete)

- [x] C4Config dataclass in `c4.py`
- [x] DocType gains `c4` field
- [x] Config parses `[types.*.c4]` section from decree.toml
- [... full list ...]

### Deferred to v2 (0/5 — explicitly out of scope for v1)

- [ ] produces/consumes contract validation
- [ ] Data flow Mermaid diagram
- [... full list ...]

## Generated

This report was auto-generated by decree on 2026-05-15.
```

Sections are derived from the source document — primary ACs and deferred sections are split using the same logic that will eventually power PRD-01KT22NMRS4QGHSFDBZ858PP1T R6's coherence gates (extracted now so it's reused later).

#### Configuration

```toml
# decree.toml
[types.spec.completion_report]
enabled = true                        # default: true once this SPEC ships
location = "{dir}/{id}-report.md"     # template — {dir}, {id}, {slug} available
deferred_sections = ["What this does NOT do", "Deferred", "v2"]  # section titles that don't count toward primary AC progress
```

Per-type configuration — PRDs can have completion reports, ADRs typically don't (no progress to summarize).

#### `decree lint` validation (opt-in)

```toml
[types.spec.completion_report]
enabled = true
require_for_terminal_status = true    # lint fails if implemented SPEC has no report
```

When `require_for_terminal_status = true`, `decree lint` checks that every document in a terminal-success status has a corresponding report file.

### Files touched

- **Create**: `src/decree/commands/ddd.py` — `assess()`, `format_human()`, `format_json()`, the dataclasses, the phase-detection state machine.
- **Create**: `src/decree/commands/report.py` — `generate_report()`, section-extraction helpers (primary vs. deferred).
- **Create**: `src/decree/commands/hook.py` — `install_claude_hook()`, `uninstall_claude_hook()`, settings.json schema validation.
- **Create**: `scripts/hooks/decree-ddd-stop.sh` — the shipped stop hook script.
- **Create**: `tests/test_ddd.py` — phase-detection fixtures across all 7 phases.
- **Create**: `tests/test_report.py` — report generation with primary/deferred section handling.
- **Create**: `tests/test_hook.py` — installation/uninstallation, settings.json safety.
- **Modify**: `src/decree/cli.py` — register `ddd`, `report`, `hook` subcommands and the new `--find-root` flag.
- **Modify**: `src/decree/commands/status.py` — call `generate_report()` after a successful transition to a terminal-success status.
- **Modify**: `src/decree/config.py` — parse `[types.*.completion_report]` config.
- **Modify**: `pyproject.toml` — no new dependencies. Possibly add the hook script to `[project.scripts]` if we want it as a console entry point instead of a shell script.

### What this SPEC does NOT do (explicit non-goals for v1)

- Does **not** depend on PRD-01KT22NMRS4QGHSFDBZ858PP1T (SQLite index, `governs:` field). All reads use existing frontmatter parsing.
- Does **not** generate visual artifacts (Mermaid diagrams, screenshots, etc.). PRD-01KT22NMRR0BX7KBF0F0N5ER6Z mentions "proofshot" — for decree's CLI scope, the proofshot equivalent is the textual completion report. Visual verification is a v2 add-on.
- Does **not** auto-transition statuses. The user still runs `decree status SPEC-<ULID> implement` manually; the report is a side-effect of *user-initiated* transitions.
- Does **not** retroactively generate reports for documents already in terminal-success state (e.g., SPEC-01KT22NMRWENYKC3MGRA50M7GE if it ever gets to `implemented`). A separate `decree report regenerate <id>` command can be added in v2 if needed.
- Does **not** alter the existing `/decree:ddd` skill behavior. The skill continues to work (and may eventually delegate to the new CLI command).
- Does **not** install hooks globally. Hook installation is per-project, opt-in.

## Testing Strategy

### Unit tests

- **`tests/test_ddd.py`** — synthetic decree corpora for each of the 7 phases. Each fixture is a temporary directory with a `decree.toml` and a controlled set of docs. Assert that `assess()` returns the correct `Phase` enum and the expected `suggested_actions`.
- **`tests/test_report.py`** — fixtures with SPECs in known shapes (primary-only ACs, primary + deferred sections, no checkboxes at all). Assert that `generate_report()` produces correct markdown, especially the primary vs. deferred split.
- **`tests/test_hook.py`** — assert install adds the correct entry to `.claude/settings.json`; assert uninstall removes only that entry; assert the schema-validation refuses to write a malformed settings.json.

### Integration tests

- **End-to-end CLI**: `decree ddd --json` on each fixture corpus produces JSON that validates against the `pydantic` schema and contains the expected phase + suggestion.
- **End-to-end report**: Spin up a fixture corpus with a SPEC at 100% progress, run `decree status <SPEC> implement`, assert the report file exists at the configured location with the expected content.
- **End-to-end hook**: install hook on a fixture project, simulate a stop event by running the shipped script, assert the snapshot file appears at `${HOME}/.claude/projects/<hash>/decree-ddd-snapshot.md`.

### Dogfood test

- Run `decree ddd` against decree's own corpus (4 PRDs, 2 ADRs, 2 SPECs at SPEC-01KT22NMRW79Y92MKZT807B2J1's draft state) and confirm it reports Phase IMPLEMENTATION pointing at SPEC-01KT22NMRW79Y92MKZT807B2J1 and SPEC-01KT22NMRWENYKC3MGRA50M7GE's remaining items. Manual smoke-check, not automated.

### Real-corpus test (the actual integration test)

- Run `decree ddd --json` against jira-task-to-md's 167-document corpus. Assert the command completes in <500ms (with 100+ docs, the in-process implementation must not pathologically reparse). Assert the JSON output validates against the schema. This is the same corpus that PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 migration will be validated against — exercising decree against it now de-risks both SPECs.

## v1 Acceptance Criteria

Shipped in priority order: R1 (CLI) first, then R3 (hook), then R2 (report). Each AC is a single behavior; checking it requires the corresponding test to pass.

### R1: `decree ddd` CLI command

- [x] `src/decree/commands/ddd.py` exists with `Phase` enum, `DDDAssessment` dataclass, `assess()`, `format_human()`, `format_json()`.
- [x] `decree ddd` subcommand registered in `src/decree/cli.py`.
- [x] Phase 0 (IDEATION) detected when all type dirs are empty (or contain only `index.md`).
- [x] Phase 1 (ARCHITECTURE_DECISIONS) detected when a PRD exists with no referencing ADR.
- [x] Phase 2 (TECHNICAL_DESIGN) detected when an accepted ADR exists with no referencing SPEC.
- [x] Phase 3 (PLANNING) detected when a SPEC has 0% checkbox progress.
- [x] Phase 4 (IMPLEMENTATION) detected for SPECs at 1-99% progress, lists unchecked items.
- [x] Phase 5 (COMPLETION) detected for SPECs at 100% progress.
- [x] Phase 6 (DONE) detected when all docs are in terminal-but-healthy states.
- [x] First-match-wins ordering: a project in Phase 4 reports Phase 4, not Phase 1, even if both apply.
- [x] `--json` output validates against the `pydantic` schema.
- [x] `--quiet` suppresses phase explanations.
- [x] `--project PATH` operates against the specified path.
- [x] Exit code 0 on healthy, 1 on lint errors or stale state.
- [x] `decree find-root` walks upward looking for `decree.toml`, prints the path on stdout, exits 0; exits 1 if not found.
- [x] Performance: `decree ddd --json` completes in <500ms on jira-task-to-md's 167-doc corpus.

### R3: Claude Code stop hook

- [x] `scripts/hooks/decree-ddd-stop.sh` exists, is executable, and is shipped with the decree package.
- [x] `decree hook install --type=claude-stop` modifies `.claude/settings.json` to add a `Stop` hook entry; idempotent.
- [x] `decree hook uninstall --type=claude-stop` removes only the entry it added.
- [x] Hook script exits 0 if no `decree.toml` is found upward from cwd and explains skip reasons with `DECREE_HOOK_DEBUG=1`.
- [x] Hook script writes the snapshot to `${HOME}/.claude/projects/<sha-hash>/decree-ddd-snapshot.md` on successful run.
- [x] Hook script exits 0 even if `decree ddd` exits non-zero (hook is informational, not a gate).
- [x] `decree hook install` refuses to write a malformed `.claude/settings.json`; schema validation passes before write.

### R2: Completion report on terminal-status transition

- [x] `src/decree/commands/report.py` exists with `generate_report()` + section-extraction helpers.
- [x] `decree status <DOC-ID> <action>` triggers `generate_report()` after a successful transition to a terminal-success status.
- [x] Report file written to the path defined by `[types.<type>.completion_report.location]` template (default: `{dir}/reports/{id}.md` to avoid colliding with the type's filename regex).
- [x] Report contains: document chain (PRD → ADR → SPEC), primary ACs with checked status, deferred-section ACs (separated), generation timestamp.
- [x] Primary vs. deferred AC sections split correctly using the configurable `deferred_sections` patterns (default: "What this does NOT do", "Deferred", "Future work", "v2 backlog", "Out of scope").
- [x] `[types.*.completion_report.enabled = false]` skips report generation entirely for that type.
- [x] `[types.*.completion_report.require_for_terminal_status = true]` causes `decree lint` to fail if a terminal-status document has no report.
- [x] Backward-safe: documents already in terminal-success status when this SPEC ships do not retroactively get reports; only new transitions trigger generation.

## What this does NOT do (deferred to v2 — explicitly out of v1 scope)

- [ ] Retroactive report generation for documents already in terminal-success state (`decree report regenerate <id>`).
- [ ] Visual proofshot artifacts (screenshots, Mermaid graphs) in the completion report.
- [ ] Index-backed `decree ddd` — once PRD-01KT22NMRS4QGHSFDBZ858PP1T R1 ships, `decree ddd` can read from the SQLite index for speed; the SPEC implementing PRD-01KT22NMRS4QGHSFDBZ858PP1T R1 handles that refactor.
- [ ] Per-user / global stop-hook installation (only per-project in v1).
- [ ] Auto-triggered status transitions (decree never transitions a document without explicit user action).
- [ ] Slack / GitHub / Linear integration for completion reports.

## References

- PRD-01KT22NMRR0BX7KBF0F0N5ER6Z — DDD CLI Command and Proofshot Integration. The three requirements (R1 CLI, R2 proofshot, R3 stop hook) map 1:1 to the three components of this SPEC.
- The `/decree:ddd` skill at `~/.claude/plugins/.../decree/skills/ddd/` — the markdown specification this SPEC ports to Python. The phase decision tree is normative.
- SPEC-01KT22NMRWENYKC3MGRA50M7GE — uses the same "Files touched" + "v1 ACs" + "What this does NOT do" structure for consistency. The deferred-sections pattern documented here is what PRD-01KT22NMRS4QGHSFDBZ858PP1T R6 will eventually formalize as a coherence gate.
- jira-task-to-md decree corpus (167 docs) — the real-world integration test target for the performance AC on `decree ddd --json`.
