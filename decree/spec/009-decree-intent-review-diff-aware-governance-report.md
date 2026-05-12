---
date: '2026-05-12'
governs:
- src/decree/commands/intent_review.py
references:
- PRD-003
- ADR-0002
status: implemented
---

# SPEC-009 decree intent-review — Diff-aware Governance Report

## Overview

Implements PRD-003 R8 — the **intent-review API**. A new `decree intent-review` command (and matching MCP tool) takes a diff and returns a structured report on how the changes intersect with the governance corpus: which decisions govern the changed paths, which decisions are stale, which acceptance criteria are likely affected, and which decisions conflict structurally over the same files.

This is the *post-code* intent review surface. The *pre-code* (planning-phase) intent review — `decree.intent_check(plan, planned_files)` — is PRD-004 R2, a separate, deferred deliverable.

SPEC-009 is the **last** SPEC of PRD-003 v1. After it lands, PRD-003 transitions to `implemented` and PRD-004 (state-of-the-art reasoning, frontier work) unblocks.

The intent_review API stitches together what every prior SPEC built:
- **SPEC-003** index → query substrate.
- **SPEC-004** typed `governs:` → maps changed paths to decisions.
- **SPEC-005** `why()` → governing-decision retrieval.
- **SPEC-006** trailer-aware `commits` table → implemented-commits per decision.
- **SPEC-007** MCP server → the API surface this SPEC adds to.
- **SPEC-008** `health()` + coherence gates → staleness + unchecked-AC signal.

No new library logic — the intent-review function **composes** existing helpers into a single report.

## Technical Design

### CLI surface

```
decree intent-review [--diff PATH | --diff-base REF] [--json] [--project PATH]
```

Diff source — three modes (resolved in this priority):

1. `--diff PATH` — read a unified-diff file (or `-` for stdin).
2. `--diff-base REF` — compute `git diff <REF>...HEAD`.
3. No flag — read from `git diff --cached --name-only` first (staged); if empty, fall back to `git diff` against the current working tree.

The command extracts **changed file paths only** — symbol-level diff hunks aren't used in v1 (governance is file-level per SPEC-004; symbol-level is PRD-003 R2 v2 backlog).

### IntentReport structure

```python
@dataclass(frozen=True)
class IntentReport:
    changed_paths: tuple[str, ...]
    governing_decisions: tuple[GoverningSnapshot, ...]
    stale_governance: tuple[StaleDecision, ...]
    unchecked_acceptance_criteria: tuple[UncheckedAC, ...]
    conflicts: tuple[Conflict, ...]
    recommended_actions: tuple[Recommendation, ...]
```

Component details:

#### `governing_decisions`
For each changed path, a `GoverningSnapshot { decision_id, status, title, match_kind, matched_path, symbol }`. Result of `queries.why()` deduped across paths. Empty list is a valid response (abstention — no governance found).

#### `stale_governance`
Subset of `governing_decisions` where the decision is flagged stale per SPEC-008's `stale_decisions()`. A governing decision IS stale → the change is happening on terrain the decision hasn't kept up with → caller may need to update the decision before proceeding.

#### `unchecked_acceptance_criteria`
For each governing decision in non-terminal status, surface its unchecked primary ACs from the `acceptance_criteria` table. This is the "your diff touches files governed by SPEC-N which still has these unchecked items — does your change finish any of them?" signal.

#### `conflicts`
Pairs of decisions that govern overlapping paths. Two SPECs both declaring `governs: src/auth.py` is a structural conflict (might be intentional but worth surfacing). v1 detection: pure structural overlap. LLM-judged semantic conflicts (one says bcrypt, other says argon2) are PRD-004 / research-frontiers B.4 territory.

#### `recommended_actions`
Heuristic suggestions surfaced as machine-readable verbs:
- `update_decision`: a stale governing decision touched by this diff should be refreshed.
- `check_ac`: an unchecked AC on an in-flight SPEC looks affected.
- `resolve_conflict`: structural conflict between two decisions; pick the live one or supersede the other.
- `add_governance`: changed file has no governing decision (the "ungoverned hotspot" inversion at the per-change level).
- `add_implements_trailer`: about-to-commit changes match an in-flight SPEC's governs paths but `--implements` wasn't provided.

Each `Recommendation { action: str, target_id: str | None, detail: str }`.

### Library shape

```python
# src/decree/commands/intent_review.py

def intent_review(
    db: IndexDB,
    project_root: Path,
    changed_paths: list[str],
    *,
    threshold_commits: int = 10,
) -> IntentReport: ...

def intent_review_run(args: argparse.Namespace) -> int: ...
```

`intent_review()` is the library API; `intent_review_run` is the CLI handler. The library function takes its IndexDB explicitly so the MCP tool can wrap it cleanly.

Internal composition (no new query logic):
1. For each `changed_path`: call `queries.why(db, path)`. Dedupe results into `governing_decisions`.
2. From `governing_decisions`, build the id set. For each: pull `acceptance_criteria` where `deferred = 0 AND done = 0`. Build `unchecked_acceptance_criteria`.
3. Call `health.stale_decisions(db, project_root, threshold_commits)`. Intersect with `governing_decisions` ids → `stale_governance`.
4. Detect `conflicts`: SQL query `governs` table grouping by path, where COUNT(DISTINCT decision_id) > 1, filtered to the changed paths.
5. Generate `recommended_actions` from the above signals — deterministic, no LLM.

### MCP tool

```python
@mcp.tool()
def intent_review(diff: str | None = None, changed_paths: list[str] | None = None) -> dict:
    """Diff-aware governance report — what decisions does this change affect?
    
    Args:
        diff: Unified diff content (string). Optional if `changed_paths` is given.
        changed_paths: List of repo-relative paths the change touches. Optional
            if `diff` is given; if both are present, `changed_paths` wins.
    
    Returns:
        Structured IntentReport dict with: changed_paths, governing_decisions,
        stale_governance, unchecked_acceptance_criteria, conflicts, recommended_actions.
        Empty arrays are valid (abstention; do not confabulate).
    
    When to call:
        - Before authoring a commit on a feature branch — get the governance
          map so the commit message can reference relevant decisions.
        - When reviewing a PR — surface conflicts and stale decisions.
        - Pre-merge — verify no terminal-success-claim contradictions.
    
    When not to call:
        - On documentation-only changes (decree/, docs/) — surfaces nothing useful.
        - On test-only diffs — same.
        - For pre-PR planning intent ("I plan to do X") — that's a different
          tool (PRD-004 R2 `decree.intent_check`), not yet implemented.
    """
    ...
```

Same 5-section docstring quality bar from SPEC-007 / SPEC-008.

### Diff parsing — minimal

We don't need a full unified-diff parser. The information we need is `changed_paths` only. Strategy:

- For a unified diff: scan lines starting with `diff --git a/<path> b/<path>` or `+++ b/<path>`. Collect the `<path>` values, dedupe.
- For a `git diff` command result: already paths-only via `git diff --name-only`.
- If `--diff -` (stdin), buffer stdin and parse the same way.

If the diff includes new-file or rename markers (`new file mode`, `rename from/to`), capture the post-rename path. Deleted files: skip them — they're not governed any more.

No `unidiff` library dependency (was listed as optional in PRD-003 deps; this minimal parser is ~30 LOC and avoids the dep).

### Files touched

- **Create**: `src/decree/commands/intent_review.py` — library function, CLI handler, dataclasses, minimal diff parser, recommendation generator.
- **Modify**: `src/decree/commands/mcp_server.py` — register `intent_review` as the 5th MCP tool.
- **Modify**: `src/decree/cli.py` — register `decree intent-review` subcommand.
- **Create**: `tests/test_intent_review.py` — unit + integration coverage.
- **Modify**: `tests/test_mcp_server.py` — extend tool registry assertions and add `TestIntentReviewTool`.

### What this SPEC does NOT do

- **No pre-PR `intent_check(plan, planned_files)`** — that's PRD-004 R2.
- **No LLM-judged semantic conflict detection** — only structural conflicts (two decisions same path). Semantic = PRD-004 territory.
- **No symbol-level diff analysis** — file-level only. Symbol governance is R2 v2 backlog.
- **No `unidiff` dependency** — minimal in-house parser.
- **No GitHub PR bot** — research-frontiers D.3 territory.
- **No auto-trailer injection** — the `add_implements_trailer` recommendation is informational; user runs `decree commit` themselves.
- **No history rewrites** — read-only.

## Testing Strategy

### Unit tests (`tests/test_intent_review.py`)

- **Empty diff**: empty `changed_paths` → IntentReport with all-empty arrays, no error.
- **Diff with no governing decisions**: changed paths not in any `governs:` → `governing_decisions` empty; `recommended_actions` includes `add_governance` per path.
- **Diff with one governing decision**: changed path matches SPEC-N's governs → `governing_decisions` has one entry; `unchecked_acceptance_criteria` populated if SPEC-N is in non-terminal status with unchecked ACs.
- **Diff with stale governance**: SPEC-N governs a path, churn since SPEC-N's last touch is above threshold → `stale_governance` includes SPEC-N.
- **Structural conflicts**: two SPECs declaring `governs: src/foo.py` → `conflicts` has one entry referencing both ids.
- **Diff parser — unified diff**: parse a sample multi-file unified diff, assert `changed_paths` matches.
- **Diff parser — rename detection**: `rename from src/old.py rename to src/new.py` → post-rename path captured.
- **Diff parser — deletion skipped**: `--- a/src/gone.py +++ /dev/null` → `src/gone.py` excluded.
- **`--json` output**: schema-stable.
- **CLI — diff from staged**: stage a file, run `decree intent-review` without flags, assert the staged file appears in changed_paths.
- **CLI — diff from --diff PATH**: pass a unified-diff file, assert paths extracted.
- **CLI — diff from stdin (`--diff -`)**: read from stdin.
- **CLI — exit code**: 0 when no conflicts and no stale governance; 1 when either is non-empty (CI-suitable gate).

### MCP tool tests (`tests/test_mcp_server.py` extension)

- **`intent_review` tool — by changed_paths**: pass a list, assert report shape.
- **`intent_review` tool — by diff string**: pass a diff string, assert paths extracted and report built.
- **`intent_review` tool — index missing**: returns structured error.
- **Tool registry**: 5 tools total now (`why`, `refs`, `stale`, `health`, `intent_review`).

### Integration test

- **End-to-end against the decree corpus**: a fixture tmp git repo with a change to `src/decree/index_db.py` → `decree intent-review` reports SPEC-003 as governing decision, no conflicts, no stale (recent commits).

### Dogfood

- After SPEC-009 ships, run `decree intent-review` on the SPEC-009 commit itself. Should show SPEC-009 as governing (via the governs field for `src/decree/commands/intent_review.py`).
- PM smoke-test the MCP tool from a Claude Code session.

## v1 Acceptance Criteria

### Library + CLI

- [x] `src/decree/commands/intent_review.py` exists with `intent_review()` + `intent_review_run()` + dataclasses.
- [x] Library composes existing helpers (`queries.why`, `health.stale_decisions`, `IndexDB`) — no new query logic.
- [x] Returns `IntentReport` with all 6 component fields populated correctly.
- [x] Structural conflict detection: two decisions sharing a `governs:` path → conflict entry.
- [x] Recommendation generator emits the 5 verb kinds when their triggers apply.

### Diff parsing

- [x] Minimal in-house parser handles unified-diff format (no `unidiff` dep).
- [x] Captures post-rename paths for rename markers.
- [x] Excludes deleted files.
- [x] Three diff sources work: `--diff PATH`, `--diff -` (stdin), default (`git diff --cached --name-only` → fallback to working-tree diff).

### MCP tool

- [x] `intent_review` registered in `mcp_server.py` with 5-section docstring.
- [x] Accepts either `diff` string OR `changed_paths` list (precedence per docstring).
- [x] Tool registry has 5 tools total.

### CLI

- [x] `decree intent-review` subcommand registered with `--diff`, `--diff-base`, `--json`, `--project` flags.
- [x] Exit 0 clean, exit 1 if conflicts or stale governance findings exist.
- [x] Subcommand documented in `decree --help`.

### Tests

- [x] `tests/test_intent_review.py` covers all unit + integration cases.
- [x] `tests/test_mcp_server.py` extended; tool registry assertion updated to 5.
- [x] Full suite passes (389 baseline + new tests).

### Dogfood

- [x] SPEC-009's frontmatter declares `governs: ["src/decree/commands/intent_review.py"]` after the file exists.
- [x] PM-recorded smoke test: `decree intent-review` on a fresh commit returns a sensible report.

## What this does NOT do (deferred)

- [ ] Pre-PR `intent_check(plan, planned_files)` — PRD-004 R2.
- [ ] LLM-judged semantic conflict detection — PRD-004 / frontier B.4.
- [ ] Symbol-level diff analysis — PRD-003 R2 v2 backlog.
- [ ] `unidiff` dependency — minimal parser only.
- [ ] GitHub PR bot integration — research-frontiers D.3.
- [ ] Auto-trailer injection on intent-review — informational only.

## References

- PRD-003 R8 — what this SPEC implements.
- ADR-0002 — Option C hybrid; intent_review reads from the index.
- SPEC-005 (`queries.why` reused), SPEC-008 (`health.stale_decisions` reused).
- SPEC-007 — MCP server registry extended.
- PRD-004 R2 — the *pre-PR* counterpart, deferred.
- research-frontiers.md B.4 — LLM-judged semantic conflicts (future direction).
