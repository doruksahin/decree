---
date: '2026-06-26'
id: PRD-01KW2BDXBB3Y6KAW081GPQTVG8
status: approved
---

# PRD-01KW2BDXBB3Y6KAW081GPQTVG8 Agent Skill Install DevX

## Problem Statement

Developers can install decree with `uv tool install decree` or similar package
managers, but the agent-facing workflow is still scattered across docs, repo
skills, and host-specific configuration. A Codex or Claude Code user should not
need to know where portable skills live, which files are safe to write, or which
hook is optional before getting useful decree guidance inside their agent.

The missing experience is a single, reversible command that installs decree's
portable agent skills into the selected host scope, reports exactly what it
wrote, refuses accidental overwrites, and leaves higher-risk hooks opt-in.

## Requirements

- Install decree portable skills for Codex and Claude Code from the installed
  package, not only from a source checkout.
- Support project-local install for team repositories and user-local install for
  personal defaults.
- Preserve user-authored files unless `--force` is explicit.
- Provide `--dry-run` and status output so teams can preview install effects in
  docs and CI.
- Keep Claude Code stop-hook installation opt-in; skill installation must not
  silently mutate hook settings.
- Keep Codex integration aligned with Codex's project/user scoped config model
  and Claude Code integration aligned with `.claude/skills/<name>/SKILL.md`.
- Update the bundled decree DDD skill so current agent sessions see required
  buckets, sprint-aware progress, and the HTML board export.
- Document the recommended onboarding flow for Codex and Claude Code users.

## Success Criteria

- A new user can run one command to install decree skills for Codex, Claude
  Code, or both.
- The command is idempotent and reports `installed`, `updated`, `unchanged`, or
  `skipped` per skill.
- Existing different skill files block installation unless `--force` is passed.
- Project-local installs write only inside `.codex/skills` and `.claude/skills`
  under the project root.
- User-local installs write only inside `~/.codex/skills` and
  `~/.claude/skills`.
- `decree agents install --dry-run` writes nothing.
- Docs and CLI help show the recommended "project scope first, hooks optional"
  flow.

## Scope

In scope:

- A core CLI command for installing packaged decree skills.
- Packaged copies of the portable decree skills so installed wheels can seed
  agent hosts without relying on repository files.
- Documentation for Codex and Claude Code onboarding.
- Tests for idempotency, dry-run, overwrite protection, and optional hooks.

Out of scope:

- Installing or managing third-party agent runtimes.
- Reading provider API keys or making LLM calls from core decree.
- Auto-enabling hooks by default.
- Full Codex/Claude plugin marketplace packaging.
