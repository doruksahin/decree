---
date: '2026-05-12'
governs:
- src/decree/commands/health.py
id: SPEC-01KT22NMRYNFYM7EN80WS2HD6F
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRYNFYM7EN80WS2HD6F Coherence Gates, Staleness, and Ungoverned Hotspots

## Overview

Implements PRD-01KT22NMRS4QGHSFDBZ858PP1T R6 + R7 — the *health surface* of the decree corpus. Two thematic deliverables:

1. **Coherence gates (R6)** — opt-in `decree lint` rules that catch document states that aren't malformed (decree's existing lint already catches those) but are *incoherent*: a SPEC marked `implemented` with 60% checkboxes done, an ADR `accepted` 18 months ago with no SPEC referencing it, deferred-to-v2 items dragging a SPEC's progress below 100%. These are the LLM-authored-codebase failure modes that motivated PRD-01KT22NMRS4QGHSFDBZ858PP1T in the first place.
2. **Staleness + ungoverned hotspots (R7)** — a new `decree health` (alias `decree stale`) command that surfaces *data-push* health signals: decisions whose governed files have churned without the decision being touched, and high-churn files with no governing decision (the Repowise "ungoverned hotspot" inversion).

Both ride on the SQLite index that SPEC-01KT22NMRX176PCT00SKJ9G2AQ shipped and the `commits` table that SPEC-01KT22NMRY8YK9RP4323KX4RQG populates via git trailers. SPEC-01KT22NMRYNFYM7EN80WS2HD6F adds **no new third-party dependencies** — it reuses `git log` (already wrapped in SPEC-01KT22NMRY8YK9RP4323KX4RQG) and the existing `IndexDB` API.

Per SPEC-01KT22NMRYJ4482K92AX9GJTMA's scoping decision, this SPEC also adds **two new MCP tools** (`decree.stale`, `decree.health`) wrapping the new CLI commands' library functions.

## Technical Design

### R6 — Coherence gates (opt-in per project)

Four gates ship in v1. All disabled by default; consumers opt in per type in `decree.toml`:

```toml
[types.spec.coherence]
terminal_status_progress = true          # gate 1
deferred_sections_separated = true       # gate 2 (uses SPEC-01KT22NMRW79Y92MKZT807B2J1's existing patterns)
unreferenced_active = true               # gate 3
unreferenced_after_days = 30             # threshold for gate 3
```

#### Gate 1 — Terminal-status vs primary-checkbox progress

A document whose status is configured terminal-success (e.g., `implemented` for SPEC, `accepted` for ADR — already detected by `is_terminal_success()` in SPEC-01KT22NMRW79Y92MKZT807B2J1) must have **100% of primary acceptance criteria checked**. Deferred-section ACs are excluded (using `_parse_checkboxes_by_section` from SPEC-01KT22NMRW79Y92MKZT807B2J1).

Error format:
```
decree/spec/spec-<ulid>-foo.md: status 'implemented' but primary AC progress is 32/37 (86%). Check remaining items or move them to a deferred section.
```

This is the exact bug SPEC-01KT22NMRWENYKC3MGRA50M7GE has dogfooded since this work started. SPEC-01KT22NMRYNFYM7EN80WS2HD6F ships the gate; SPEC-01KT22NMRWENYKC3MGRA50M7GE either gets remediated or its remaining items get moved to a deferred section.

#### Gate 2 — Deferred sections counted separately

Already half-implemented in SPEC-01KT22NMRW79Y92MKZT807B2J1's completion-report logic. This gate **promotes** the section-classification to a first-class lint rule: when a doc has both primary and deferred ACs, lint surfaces the split in its output (informational, not an error). It also rejects checkboxes nested inside fenced code blocks (the SPEC-01KT22NMRW79Y92MKZT807B2J1 example-report cosmetic bug — illustrations in code blocks shouldn't count). Configurable via `deferred_sections` patterns from decree.toml.

Output (informational; gate emits as warnings, exit-code 0):
```
decree/spec/spec-<ulid>-bar.md: 3 deferred-section ACs separated from primary (counted independently).
decree/spec/spec-<ulid>-bar.md: 3 checkboxes inside fenced code blocks (ignored — illustrations).
```

The "ignored — illustrations" handling means **primary AC progress no longer over-counts code-block examples**. This requires SPEC-01KT22NMRW79Y92MKZT807B2J1's `_parse_checkboxes_by_section` to be extended to skip checkboxes inside ` ```...``` ` fences. The change is contained to that one function and benefits SPEC-01KT22NMRW79Y92MKZT807B2J1's report generation as well.

#### Gate 3 — Unreferenced active decisions

A PRD or ADR in an active status (`approved` / `accepted`) with **no inbound `references` from any document** after N days (config: `unreferenced_after_days`, default 30) is flagged as a potentially stalled decision.

Error format:
```
decree/prd/prd-<ulid>-foo.md: status 'approved' for 12 days with no referencing ADR or SPEC. Stalled? (threshold: 30 days)
```

The "N days" is `today - frontmatter_date`. Frontmatter date is already in the index (`decisions.date`). Reverse-reference check is a one-line SQL query against the `refs` table. Cheap.

Per-type config — PRDs expect ADRs to reference them; ADRs expect SPECs. Configurable in decree.toml via `expected_referrer_types`.

#### Gate 4 — Status-field requirements (already in decree)

decree already enforces `status_field_requirements` (e.g., `superseded` requires `superseded-by`). This SPEC doesn't re-implement it but **surfaces it via the index** so the new `decree health` command can report on it consistently with other findings.

### R7 — `decree health` / `decree stale` (CLI)

A new top-level command bringing the data-push health signal:

```
decree health  [--json] [--project PATH] [--threshold-commits N] [--threshold-days N]
decree stale   # alias: same flags
```

Output sections:

#### Stale decisions

A decision is *stale* if files it `governs:` have churned by N commits since the decision was last touched.

Algorithm:
1. For each decision with `governs:` entries: get the timestamp of the most recent commit touching the decision's own markdown file (`git log -1 --format=%ct -- <doc-path>`).
2. For each governed path: count commits to that path *after* the decision's timestamp (`git log --since=<ts> --oneline -- <path>` then `wc -l`).
3. If total post-decision commits across all governed paths exceeds `--threshold-commits` (default 10), flag as stale.

Output:
```
Stale decisions (governed files have churned without the decision being touched):

  SPEC-<ULID>   28 commits since 2026-03-15 on governs paths:
    src/api/auth.py    (18 commits)
    src/api/session.py (10 commits)
```

#### Ungoverned hotspots

A file is *ungoverned hotspot* if it has high commit churn AND no decision governs it.

Algorithm:
1. `git log --name-only --since=<threshold-days> --pretty=format:` gathers files modified recently. Count per file.
2. For each high-churn file (above `--threshold-commits`), query `governs` table: is any decision governing it (exact or prefix)?
3. If no governance, flag as ungoverned hotspot.

Output:
```
Ungoverned hotspots (high churn, no governing decision):

  src/foo.py        45 commits in last 30 days — no governing decision
  src/api/legacy.py 22 commits in last 30 days — no governing decision
```

This is the Repowise data-push insight: instead of waiting for an ADR author to volunteer, we **tell** them where one is needed.

#### Exit code

- `0` if no stale decisions and no hotspots above threshold.
- `1` otherwise.

This makes `decree health` CI-suitable as a soft gate (`decree health || true` for non-blocking; remove `|| true` to make it blocking).

### MCP tool additions (extending SPEC-01KT22NMRYJ4482K92AX9GJTMA's server)

Per SPEC-01KT22NMRYJ4482K92AX9GJTMA's scoping decision, this SPEC adds **two MCP tools** to the existing FastMCP server in `src/decree/commands/mcp_server.py`:

- `decree.stale` — returns the stale-decisions section as a dict.
- `decree.health` — returns both stale + hotspots sections.

Same 5-section docstring quality bar from SPEC-01KT22NMRYJ4482K92AX9GJTMA. Both tools reuse the library functions this SPEC ships (no new query logic in the MCP layer).

### decree.toml schema additions

```toml
# Per-type coherence configuration
[types.spec.coherence]
terminal_status_progress = true
deferred_sections_separated = true
unreferenced_active = false        # SPEC doesn't typically have downstream references; off by default
deferred_sections = ["What this does NOT do", "Deferred", "Future work"]

[types.prd.coherence]
terminal_status_progress = true
unreferenced_active = true
unreferenced_after_days = 30
expected_referrer_types = ["adr", "spec"]

# Global health command thresholds (CLI defaults)
[health]
threshold_commits = 10              # stale-decision threshold
threshold_days = 30                 # ungoverned-hotspot lookback window
```

All keys optional; defaults compiled in. Validated when decree.toml is loaded.

### Files touched

- **Modify**: `src/decree/commands/lint.py` — wire in coherence gates after existing validators. Per-type config dispatch.
- **Modify**: `src/decree/commands/report.py` — extend `_parse_checkboxes_by_section` to skip checkboxes inside fenced code blocks (one toggle inside the line walk).
- **Modify**: `src/decree/config.py` — parse `[types.*.coherence]` blocks and `[health]` block; expose on `DocType` or via a separate `coherence_config` accessor (implementer chooses).
- **Create**: `src/decree/commands/health.py` — `health()` + `stale_decisions()` + `ungoverned_hotspots()` library functions; `health_run` and `stale_run` CLI handlers.
- **Modify**: `src/decree/commands/mcp_server.py` — register `stale` and `health` as MCP tools wrapping the new library functions.
- **Modify**: `src/decree/cli.py` — register `decree health` and `decree stale` subcommands.
- **Modify**: `src/decree/validators.py` — new validators (one per gate). Per-type config-aware.
- **Create**: `tests/test_coherence.py` — gate-by-gate unit tests.
- **Create**: `tests/test_health.py` — staleness + hotspot unit + integration tests.
- **Modify**: `tests/test_mcp_server.py` — extend with the two new tools.

### What this SPEC does NOT do

- **No body-link extraction** — mistletoe is still idle. Body links are a query enrichment. Defer to a future SPEC.
- **No commit-trailer well-formedness lint gate** — could be added later.
- **No `pydriller` dependency** — churn analysis uses `git log` shellouts (same pattern as SPEC-01KT22NMRY8YK9RP4323KX4RQG's `sync_commits_from_git`).
- **No streaming / incremental health** — full scan each invocation. Caching is v2 polish.
- **No GitHub / Slack / Linear integration** — health is local CLI/MCP, not push.
- **No auto-suggested ADR drafts** — frontiers C.1 in `docs/market-analysis/research-frontiers.md`. PRD-01KT22NMRSXYT95XE808VD8EV4 territory.
- **No status-field-requirements gate beyond surfacing existing decree behavior** — gate 4 only reports.

## Testing Strategy

### Unit tests (`tests/test_coherence.py`)

- **Gate 1 — terminal status with incomplete primary**: SPEC marked `implemented` with 60% primary ACs → lint error.
- **Gate 1 — terminal status with 100% primary**: lint passes.
- **Gate 1 — deferred items don't drag progress**: SPEC marked `implemented` with 100% primary + 0% deferred → lint passes.
- **Gate 1 — opt-in**: gate disabled in decree.toml → no error even when violated.
- **Gate 2 — code-block checkboxes excluded**: A `- [x]` inside ```` ``` ```` fences is not counted toward AC progress.
- **Gate 2 — deferred patterns custom**: project configures `deferred_sections = ["Backlog"]` → "Backlog" section ACs counted separately.
- **Gate 3 — unreferenced PRD after N days**: PRD `approved` 35 days ago, no referencing ADR → lint error (threshold 30).
- **Gate 3 — unreferenced PRD within window**: PRD `approved` 5 days ago → no error.
- **Gate 3 — opt-in**: gate disabled → no error.
- **Gate 4 — status-field surface**: lint reports `superseded` requires `superseded-by` violation via the index.

### Unit tests (`tests/test_health.py`)

- **Stale — single decision with churned governs**: SPEC governs `src/foo.py`; 15 commits to `src/foo.py` after SPEC's last touch → flagged stale.
- **Stale — decision itself touched recently**: SPEC governs `src/foo.py`; commits before SPEC's last touch don't count → not stale.
- **Hotspot — high-churn file without governance**: `src/legacy.py` with 50 recent commits, no governing decision → flagged hotspot.
- **Hotspot — high-churn file WITH governance**: `src/api/auth.py` with 50 commits, governed by SPEC-<ULID> → not flagged.
- **Threshold customization**: `--threshold-commits 5` flags decisions/files that wouldn't trigger at default 10.
- **`--json` output**: schema-stable structured response.
- **Exit code**: `0` when clean, `1` when findings exist.
- **No git repo**: command no-ops with a warning (doesn't crash).

### Integration tests

- **End-to-end CLI**: tmp git repo with a fixture corpus → run `decree health` → assert expected findings.
- **End-to-end MCP**: in-process call to `decree.health` MCP tool returns the same data shape.

### Dogfood

- After SPEC-01KT22NMRYNFYM7EN80WS2HD6F ships: run `decree health` against the decree corpus itself. Expectations:
  - SPEC-01KT22NMRWENYKC3MGRA50M7GE is `draft` not `implemented`, so gate 1 doesn't apply yet.
  - PRD-01KT22NMRR0BX7KBF0F0N5ER6Z was `approved` then `implemented` quickly — gate 3 wouldn't flag it.
  - PRD-01KT22NMRR63TXR7NX5XYRG5FK has been `approved` since 2026-04-05; if `unreferenced_active = true` for PRD type, it would only flag if no SPEC references it. SPEC-01KT22NMRWENYKC3MGRA50M7GE does. → no flag.
  - Ungoverned hotspots in decree itself: `src/decree/cli.py` is high-churn but governed (SPEC-01KT22NMRW79Y92MKZT807B2J1 and SPEC-01KT22NMRXWCS5TK5VC1FT6JER both touch it via their governs). So likely clean.
- The PM enables the gates one at a time after SPEC-01KT22NMRYNFYM7EN80WS2HD6F ships, using `decree migrate audit-coherence` (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6) for impact assessment before global enablement.

## v1 Acceptance Criteria

### Coherence gates (R6)

- [x] `src/decree/validators.py` has new validators: `validate_terminal_status_progress`, `validate_unreferenced_active`, plus the existing `validate_governs_paths` pattern.
- [x] Each gate is opt-in per-type via `[types.<type>.coherence]` in decree.toml.
- [x] Gate 1 (terminal-status progress): a doc in terminal-success status with <100% primary AC progress emits a lint error.
- [x] Gate 2 (deferred sections): primary and deferred ACs counted separately; `_parse_checkboxes_by_section` extended to skip checkboxes inside fenced code blocks.
- [x] Gate 3 (unreferenced active): per-type `expected_referrer_types` list controls which types are checked.
- [x] Gate 4 (status-field requirements): surfaces existing decree behavior via the index (no behavior change — only reporting).
- [x] Gates disabled by default in `decree.toml`; existing 349-test suite unaffected by their existence.

### Health command (R7)

- [x] `src/decree/commands/health.py` exists with `stale_decisions()`, `ungoverned_hotspots()` library functions and `health_run`, `stale_run` CLI handlers.
- [x] `decree health` subcommand registered, supports `--json`, `--project`, `--threshold-commits`, `--threshold-days`.
- [x] `decree stale` alias also registered.
- [x] Stale-decision detection works: decision governing files that have churned post-touch is flagged.
- [x] Ungoverned-hotspot detection works: high-churn files with no governing decision are flagged.
- [x] No-git-repo case: command no-ops with a warning, exit 0.
- [x] `--json` output schema-stable.
- [x] Exit code: 0 if clean, 1 if findings.

### MCP tool additions

- [x] `decree.stale` MCP tool registered in `mcp_server.py`, wraps `stale_decisions()`.
- [x] `decree.health` MCP tool registered, wraps `health()` (combined).
- [x] Both tools follow SPEC-01KT22NMRYJ4482K92AX9GJTMA's 5-section docstring structure.
- [x] `tools/list` returns 4 tools total (`why`, `refs`, `stale`, `health`).

### Config

- [x] `[types.*.coherence]` block parsed in `src/decree/config.py`.
- [x] `[health]` top-level block parsed for default thresholds.
- [x] Unknown keys in coherence config emit clear errors at load time.

### Tests

- [x] `tests/test_coherence.py` covers all gate unit cases.
- [x] `tests/test_health.py` covers staleness + hotspot unit cases + integration.
- [x] `tests/test_mcp_server.py` extended with the two new tools.
- [x] Full suite passes (349 baseline + new tests).

### Dogfood

- [x] Run `decree health` against the decree project itself; record findings in the SPEC-01KT22NMRYNFYM7EN80WS2HD6F completion report.
- [x] Enable gate 1 (terminal-status progress) on the SPEC type in decree.toml; confirm lint passes (or remediate findings).
- [x] SPEC-01KT22NMRYNFYM7EN80WS2HD6F's frontmatter declares `governs: ["src/decree/commands/health.py"]` after the file exists.

## What this does NOT do (deferred)

- [ ] Body-link extraction (mistletoe) — future SPEC.
- [ ] Commit-trailer well-formedness lint gate — future SPEC.
- [ ] Cached / incremental health — v2 polish.
- [ ] Auto-suggested ADR drafts from ungoverned hotspots — research-frontiers C.1 / PRD-01KT22NMRSXYT95XE808VD8EV4.
- [ ] GitHub / Slack push notifications.
- [ ] Custom health checks via decree.toml plugin hooks.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R6 (coherence gates) + R7 (staleness + hotspots) — what this SPEC implements.
- ADR-01KT22NMRV9CP14X5982JJH161 — Option C hybrid; staleness queries hit the index.
- SPEC-01KT22NMRW79Y92MKZT807B2J1 — `_parse_checkboxes_by_section` reused and extended (code-fence handling).
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ — index substrate (especially the `commits` table from SPEC-01KT22NMRY8YK9RP4323KX4RQG).
- SPEC-01KT22NMRY8YK9RP4323KX4RQG — git log / git interpret-trailers shellout pattern reused for churn analysis.
- SPEC-01KT22NMRYJ4482K92AX9GJTMA — MCP server extended with `stale` and `health` tools.
- Repowise "ungoverned hotspots" analysis — `docs/market-analysis/repowise/` and `docs/market-analysis/discussion-notes.md`.
