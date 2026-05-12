# SPEC-002 Completion Report

**Document**: `/Users/doruk/Desktop/SIDE_HUSTLE/decree/decree/spec/002-ddd-cli-completion-report-and-stop-hook.md`
**Transitioned to `implemented` on**: 2026-05-12
**Generated**: 2026-05-12T09:12:27Z
**Total documents in chain**: 2

## Document chain

| Type | ID | Status | Title |
|---|---|---|---|
| PRD | PRD-002 | approved | PRD-002 DDD CLI Command and Proofshot Integration |
| SPEC | SPEC-002 | implemented | SPEC-002 DDD CLI, Completion Report, and Stop Hook |

## Acceptance Criteria — primary (34/34)

### Primary v1 (32/32 complete) (3/3)

- [x] C4Config dataclass in `c4.py`
- [x] DocType gains `c4` field
- [x] Config parses `[types.*.c4]` section from decree.toml

### R1: `decree ddd` CLI command (16/16)

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

### R3: Claude Code stop hook (7/7)

- [x] `scripts/hooks/decree-ddd-stop.sh` exists, is executable, and is shipped with the decree package.
- [x] `decree hook install --type=claude-stop` modifies `.claude/settings.json` to add a `Stop` hook entry; idempotent.
- [x] `decree hook uninstall --type=claude-stop` removes only the entry it added.
- [x] Hook script exits silently with code 0 if no `decree.toml` is found upward from cwd.
- [x] Hook script writes the snapshot to `${HOME}/.claude/projects/<sha-hash>/decree-ddd-snapshot.md` on successful run.
- [x] Hook script exits 0 even if `decree ddd` exits non-zero (hook is informational, not a gate).
- [x] `decree hook install` refuses to write a malformed `.claude/settings.json`; schema validation passes before write.

### R2: Completion report on terminal-status transition (8/8)

- [x] `src/decree/commands/report.py` exists with `generate_report()` + section-extraction helpers.
- [x] `decree status <DOC-ID> <action>` triggers `generate_report()` after a successful transition to a terminal-success status.
- [x] Report file written to the path defined by `[types.<type>.completion_report.location]` template (default: `{dir}/reports/{id}.md` to avoid colliding with the type's filename regex).
- [x] Report contains: document chain (PRD → ADR → SPEC), primary ACs with checked status, deferred-section ACs (separated), generation timestamp.
- [x] Primary vs. deferred AC sections split correctly using the configurable `deferred_sections` patterns (default: "What this does NOT do", "Deferred", "Future work", "v2 backlog", "Out of scope").
- [x] `[types.*.completion_report.enabled = false]` skips report generation entirely for that type.
- [x] `[types.*.completion_report.require_for_terminal_status = true]` causes `decree lint` to fail if a terminal-status document has no report.
- [x] Backward-safe: documents already in terminal-success status when this SPEC ships do not retroactively get reports; only new transitions trigger generation.

## Deferred / Out of scope (0/8)

### Deferred to v2 (0/5 — explicitly out of scope for v1) (0/2)

- [ ] produces/consumes contract validation
- [ ] Data flow Mermaid diagram

### What this does NOT do (deferred to v2 — explicitly out of v1 scope) (0/6)

- [ ] Retroactive report generation for documents already in terminal-success state (`decree report regenerate <id>`).
- [ ] Visual proofshot artifacts (screenshots, Mermaid graphs) in the completion report.
- [ ] Index-backed `decree ddd` — once PRD-003 R1 ships, `decree ddd` can read from the SQLite index for speed; the SPEC implementing PRD-003 R1 handles that refactor.
- [ ] Per-user / global stop-hook installation (only per-project in v1).
- [ ] Auto-triggered status transitions (decree never transitions a document without explicit user action).
- [ ] Slack / GitHub / Linear integration for completion reports.

---

_This report was auto-generated by decree on a terminal-status transition._
