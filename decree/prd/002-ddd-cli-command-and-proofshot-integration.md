---
status: draft
date: 2026-04-30
---

# PRD-002 DDD CLI Command and Proofshot Integration

## Problem Statement

Decree Driven Development (DDD) currently exists only as a Claude Code skill (`/decree:ddd`). It assesses project state, determines the lifecycle phase, and suggests next actions — but it requires Claude Code. There is no way to run DDD from the terminal, no verification that implementation matches the spec, and no way to automatically capture proof of completion.

Additionally, when a SPEC reaches 100% and implementation is done, there is no structured "done" signal. The developer manually checks boxes and transitions statuses, but nothing captures what was actually built or whether it matches the acceptance criteria.

## Requirements

### R1: `decree ddd` CLI command

- [ ] `decree ddd` prints the current phase (same logic as `/decree:ddd` skill)
- [ ] Shows document chain with status and progress per document
- [ ] Identifies the next action and prints a suggestion
- [ ] Works offline, no LLM calls — reads `decree.toml`, runs `decree lint` and `decree progress` internally
- [ ] Exit code: 0 if healthy, 1 if lint errors or stale state detected

### R2: Proofshot integration

- [ ] After SPEC reaches 100% and `decree status SPEC-NNN implement` is run, decree generates a completion report
- [ ] Report captures: document chain (PRD → ADR → SPEC), all acceptance criteria with checked status, timestamps
- [ ] Report is written as a markdown file in the SPEC's directory (e.g., `decree/spec/001-report.md`)
- [ ] `decree lint` validates report existence for implemented SPECs (opt-in via config)

### R3: Claude Code stop hook

- [ ] Decree provides a stop hook that runs `decree ddd` when a Claude Code session ends
- [ ] Hook output is appended to the session context, giving the next session a starting point
- [ ] Installable via `decree hook install` or documented as a manual `.claude/settings.json` entry
- [ ] Hook is non-blocking — if decree is not initialized in the project, it exits silently

## Success Criteria

- [ ] `decree ddd` produces the same phase assessment as `/decree:ddd` skill without requiring Claude Code
- [ ] A developer using only the CLI can follow the full PRD → ADR → SPEC → Implementation → Report flow
- [ ] Stop hook captures project state between Claude Code sessions
- [ ] Completion report provides an auditable record of what was decided and what was built

## Scope

**In scope:**
- `decree ddd` command (phase detection, suggestions, document chain display)
- Completion report generation (proofshot)
- Claude Code stop hook for `decree ddd`
- Config flag for report validation in lint

**Out of scope:**
- LLM-powered assessment (decree stays deterministic and offline)
- Screenshot capture or visual proof (proofshot is document-level, not visual)
- Auto-transitioning statuses (decree suggests, human decides)
- Changes to existing commands (new, status, lint, index, graph, progress)
