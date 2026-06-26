---
date: '2026-06-26'
id: ADR-01KW2BEB2KK28J2G4QAQT81737
references:
- PRD-01KW2BDXBB3Y6KAW081GPQTVG8
status: accepted
---

# ADR-01KW2BEB2KK28J2G4QAQT81737 Packaged Project Local Agent Skills Installer

## Context and Problem Statement

PRD-01KW2BDXBB3Y6KAW081GPQTVG8 requires a simple agent onboarding path for
Codex and Claude Code. The key design question is where the source of truth for
decree's portable skills should live and how much configuration the installer
should mutate.

Codex supports user-level `~/.codex/config.toml` plus project-scoped
`.codex/config.toml` and project-scoped hooks. Claude Code supports project
skill folders under `.claude/skills/<skill>/SKILL.md` and user skill folders
under `~/.claude/skills/<skill>/SKILL.md`. Both hosts can use project-local
files, which are reviewable and team-shareable, but hooks can affect session
behavior and should remain explicit.

## Decision Drivers

- Installed decree packages must work without a source checkout.
- Project-local onboarding is safer for teams because changes are visible in
  git review.
- User-local install is useful for a developer's personal default workflow.
- Agent hooks are higher-impact than skills and must not be installed silently.
- Existing user-authored agent files must be preserved unless `--force` is
  explicit.
- Core decree must not gain LLM provider dependencies or hidden runtime
  fallbacks.

## Considered Options

- Option A: Document manual copy steps only.
- Option B: Install directly from the repository `skills/` folder.
- Option C: Package canonical skill templates and copy them with
  `decree agents install`.
- Option D: Ship a host-specific plugin/marketplace package for each agent.

## Decision Outcome

Chosen option: Option C, package canonical skill templates and copy them with
`decree agents install`.

This keeps the install path simple, deterministic, and available from an
installed wheel. The repository `skills/` folder remains the human-readable
portable skill source, while packaged templates are the distribution source used
by the CLI. The command writes normal host-native files rather than inventing a
new runtime integration layer.

Consequences:

- Good: one command can install skills for Codex, Claude Code, or both.
- Good: project-local and user-local scopes are explicit.
- Good: overwrite behavior is fail-closed by default.
- Good: Claude stop-hook installation can be offered behind an explicit
  `--hooks` flag and reuse the existing hook module.
- Bad: packaged skill templates duplicate the root portable skill files; tests
  and review must keep them in sync.
- Deferred: plugin marketplace packaging can come later if host ecosystems need
  richer distribution metadata.
