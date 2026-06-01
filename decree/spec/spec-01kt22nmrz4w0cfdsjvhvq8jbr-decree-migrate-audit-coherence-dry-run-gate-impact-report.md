---
date: '2026-05-12'
governs:
- src/decree/commands/migrate.py
id: SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR decree migrate audit-coherence — Dry-run Gate Impact Report

## Overview

Implements the first half of PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 — the audit half of corpus migration tooling. A new `decree migrate audit-coherence` command runs SPEC-01KT22NMRYNFYM7EN80WS2HD6F's coherence gates in **dry-run mode against the entire corpus** and reports per-gate violations. Use case: before flipping a gate on globally in `decree.toml`, the maintainer wants to know "if I enabled gate 1 today, how many docs would lint fail on?". Without this, the only options are (a) enable blind and remediate the resulting lint storm, or (b) eyeball every doc manually.

This SPEC also adds an interactive `--fix` mode for one-by-one remediation, and `--json` output for CI / pipeline consumers.

The other half of PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 — agent-assisted `decree migrate governs --analyze/--apply-suggestions` — ships in **SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S** and is revised by **SPEC-01KT22NMS0BN1F5B01HEFK87W0**. The `git notes` backfill stays v2.

After SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR + SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S land, PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 closes.

## Technical Design

### CLI surface

```
decree migrate audit-coherence [--gate GATE]... [--fix] [--json] [--project PATH]
```

- `--gate GATE` (repeatable) — limit the audit to specific gates. Values: `terminal_status_progress`, `unreferenced_active`, `status_field_requirements`. Default: all gates.
- `--fix` — interactive remediation mode (described below).
- `--json` — structured output for CI consumers.
- `--project PATH` — operate against a project at PATH.

Exit codes:
- `0` — no violations across all selected gates.
- `1` — at least one violation found (CI-suitable).

### Audit logic

Reuses SPEC-01KT22NMRYNFYM7EN80WS2HD6F's validators in **preview mode** — same `validate_terminal_status_progress` and `validate_unreferenced_active`, but called with the project's coherence config *overridden* to enable every selected gate regardless of decree.toml. Each violation is captured into a structured `AuditFinding`.

```python
# src/decree/commands/migrate.py

@dataclass(frozen=True)
class AuditFinding:
    doc_path: str
    doc_id: str
    gate: str                # "terminal_status_progress" / "unreferenced_active" / "status_field_requirements"
    severity: str            # "error" / "warning"
    message: str
    suggested_fix: str | None  # e.g., "check 5 unchecked ACs", "transition status back to draft"

@dataclass(frozen=True)
class AuditReport:
    findings: tuple[AuditFinding, ...]
    by_gate: dict[str, int]      # count per gate
    by_type: dict[str, int]      # count per doc type
    total: int
```

`audit_coherence(project_root, gates=None) -> AuditReport` is the library API. `audit_coherence_run(args)` is the CLI handler.

### Interactive `--fix` mode

For each finding:

```
[1/12] decree/spec/006-...md
  Gate: terminal_status_progress
  Issue: status 'implemented' but primary AC progress is 0/27 (0%)
  
  Options:
    f) Fix — open $EDITOR on the document
    s) Skip this finding
    d) Defer — add this doc to decree.toml exceptions for this gate
    q) Quit (apply changes so far; skip the rest)
  
  Choice [f/s/d/q]:
```

The `d` option writes to `[types.<type>.coherence_exceptions]` in decree.toml (a list of `doc_id` strings to skip per gate). This lets the maintainer defer remediation without losing the signal — gate-enabled lint still flags everything except listed exceptions.

`--fix` is **interactive only**; not used in CI / scripts. If stdout is not a TTY, the command refuses with a clear error suggesting `--json` for non-interactive use.

### Decree.toml extension

```toml
[types.spec.coherence_exceptions]
terminal_status_progress = ["SPEC-01KT22NMRY8YK9RP4323KX4RQG", "SPEC-01KT22NMRYJ4482K92AX9GJTMA"]   # gate 1 deferrals
```

Parsed by `config.py` alongside the existing coherence block. Each gate-name key maps to a list of doc IDs to skip when that gate runs. Used both by the live gate (skip listed docs) and by the audit (still report, but flag as "deferred via exception").

### Files touched

- **Create**: `src/decree/commands/migrate.py` — `audit_coherence()`, `audit_coherence_run()`, `AuditFinding`, `AuditReport` dataclasses, interactive `--fix` loop.
- **Modify**: `src/decree/cli.py` — register `decree migrate audit-coherence` sub-namespace.
- **Modify**: `src/decree/config.py` — parse `[types.<name>.coherence_exceptions]` block.
- **Modify**: `src/decree/validators.py` — accept `exceptions: set[str] | None = None` parameter on `validate_terminal_status_progress` and `validate_unreferenced_active`; skip listed doc_ids. (Optional / minimal change — the audit can also filter post-hoc.)
- **Create**: `tests/test_migrate_audit.py` — unit + integration tests.

### What this SPEC does NOT do

- **No `decree migrate governs --analyze/--apply-suggestions`** — SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S and SPEC-01KT22NMS0BN1F5B01HEFK87W0.
- **No `decree migrate backfill-trailers`** — v2 (git notes).
- **No automated remediation** — `--fix` is interactive only; user makes every change.
- **No LLM-judged severity ranking** — severity is gate-derived (gate 1 = error; gate 2 split-count = warning).
- **No GitHub PR opening** — `--fix` opens `$EDITOR`, doesn't push branches.
- **No bulk edit** — one violation at a time in `--fix`. Future could add a `--bulk-defer all`.

## Testing Strategy

### Unit tests (`tests/test_migrate_audit.py`)

- **`audit_coherence` — clean corpus**: a corpus with no violations → `AuditReport.total == 0`, exit 0.
- **`audit_coherence` — terminal-status violations**: corpus with 2 SPECs in `implemented` with <100% primary progress → 2 findings.
- **`audit_coherence` — unreferenced active**: corpus with PRD `approved` 60 days ago, no SPEC referencing → 1 finding.
- **`audit_coherence` — gate filter**: `--gate terminal_status_progress` only returns gate-1 findings.
- **`audit_coherence` — exceptions honored**: SPEC-01KT22NMRY8YK9RP4323KX4RQG in `coherence_exceptions.terminal_status_progress` → not flagged.
- **`--json` output**: schema-stable, validates round-trip.
- **`--fix` mode — non-TTY**: stdin is not a TTY → exit 1 with clear error.
- **Exit code**: 0 clean, 1 with findings.

### Integration tests

- **End-to-end against fixture corpus**: tmp project with controlled violations → audit returns the expected findings.
- **End-to-end against decree corpus**: `decree migrate audit-coherence --gate terminal_status_progress` returns findings for SPEC-01KT22NMRY8YK9RP4323KX4RQG + SPEC-01KT22NMRYJ4482K92AX9GJTMA (the real-world incoherence SPEC-01KT22NMRYNFYM7EN80WS2HD6F surfaced).

### Dogfood

- Run `decree migrate audit-coherence` against the decree corpus. Capture output in SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR completion report.
- Use `--fix` mode interactively to remediate SPEC-01KT22NMRY8YK9RP4323KX4RQG + SPEC-01KT22NMRYJ4482K92AX9GJTMA (backfill missing AC checks) OR add them as exceptions. PM call after audit runs.

## v1 Acceptance Criteria

### Library + CLI

- [x] `src/decree/commands/migrate.py` exists with `audit_coherence()`, `audit_coherence_run()`, `AuditFinding`, `AuditReport`.
- [x] Reuses SPEC-01KT22NMRYNFYM7EN80WS2HD6F validators in preview mode (no duplication of validation logic).
- [x] `decree migrate audit-coherence` subcommand registered.
- [x] `--gate GATE` filter (repeatable) limits scope.
- [x] `--json` produces schema-stable structured response.
- [x] Exit 0 clean, 1 if findings.

### Interactive `--fix`

- [x] `--fix` runs an interactive prompt per finding.
- [x] Four options: fix (opens $EDITOR), skip, defer, quit.
- [x] `--fix` refuses non-TTY input with a clear error.
- [x] Deferrals are written to `[types.<type>.coherence_exceptions]` in decree.toml.
- [x] After `--fix` completes, exit code reflects remaining unresolved findings.

### Coherence exceptions

- [x] `[types.<name>.coherence_exceptions]` parsed in `config.py`.
- [x] Each gate's exception list (e.g., `terminal_status_progress = ["SPEC-01KT22NMRY8YK9RP4323KX4RQG"]`) skips listed docs when the gate runs.
- [x] Audit still reports exception-listed docs but tags them `deferred via exception` (informational, not error).

### Tests

- [x] `tests/test_migrate_audit.py` covers all unit + integration cases.
- [x] Full test suite passes (417 baseline + new tests).

### Dogfood

- [x] SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR's frontmatter declares `governs: ["src/decree/commands/migrate.py"]` after the file exists.
- [x] PM runs audit against decree corpus; records output in SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR completion report.
- [x] PM either backfills SPEC-01KT22NMRY8YK9RP4323KX4RQG/007 ACs (preferred) or records exceptions for them (acceptable interim).

## What this does NOT do (deferred)

- [ ] `decree migrate governs --analyze/--apply-suggestions` — SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S and SPEC-01KT22NMS0BN1F5B01HEFK87W0.
- [ ] `decree migrate backfill-trailers` (git notes) — v2.
- [ ] Automated (non-interactive) remediation.
- [ ] Bulk-defer (`--defer-all` style).
- [ ] CI bot integration.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 (the audit half) — what this SPEC implements.
- SPEC-01KT22NMRYNFYM7EN80WS2HD6F — coherence-gate validators reused in preview mode.
- SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S (next) — completes PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 with governs-backfill tooling.
