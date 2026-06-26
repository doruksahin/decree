---
date: '2026-06-26'
governs:
- src/decree/cli.py
- src/decree/commands/agents.py
- src/decree/commands/init.py
- src/decree/templates/agent/skills/
- skills/decree-ddd/SKILL.md
- skills/decree-governs-suggest/SKILL.md
- tests/test_agents.py
- tests/test_init.py
- docs/usage.md
- docs/llm-agent-integration.md
- docs/index.md
- README.md
id: SPEC-01KW2BEQ5J7JWM93K4YAS9GZAB
references:
- PRD-01KW2BDXBB3Y6KAW081GPQTVG8
- ADR-01KW2BEB2KK28J2G4QAQT81737
status: approved
---

# SPEC-01KW2BEQ5J7JWM93K4YAS9GZAB Agent Skill Install CLI

## Overview

Add `decree agents` as the host-agent onboarding command family. The first
subcommands are `install` and `status`, covering Codex and Claude Code skill
installation with project/user scopes, dry-run, overwrite protection, and
optional Claude stop-hook setup.

`decree init --with-agents` reuses the same installer as the zero-friction
project bootstrap path: a new project can scaffold decree and install
project-local Codex/Claude skills in one deterministic command, without asking
the user or an LLM to hand-write TOML or copy skill files.

## Technical Design

Create `src/decree/commands/agents.py` with command-module style
`run(args) -> int`.

### Command surface

```bash
decree agents install --target codex --scope project
decree agents install --target claude --scope project
decree agents install --target all --scope user
decree agents install --target claude --scope project --hooks
decree agents install --target all --scope project --dry-run
decree agents status --target all --scope project
decree init --with-agents
decree init --with-agents --dry-run
```

Arguments:

- `--target`: `codex`, `claude`, or `all`; default `all`.
- `--scope`: `project` or `user`; default `project`.
- `--dry-run`: report planned writes without writing files.
- `--force`: overwrite existing different skill files.
- `--hooks`: with `install`, also install the existing Claude Code stop hook
  when `claude` is included and scope is `project`.

### Skill source and destinations

Package skill templates under:

```text
src/decree/templates/agent/skills/<skill-name>/SKILL.md
```

Install destinations:

- Codex project: `<project>/.codex/skills/<skill-name>/SKILL.md`
- Codex user: `~/.codex/skills/<skill-name>/SKILL.md`
- Claude project: `<project>/.claude/skills/<skill-name>/SKILL.md`
- Claude user: `~/.claude/skills/<skill-name>/SKILL.md`

The command uses package resources or package-relative paths so it works from
editable installs and built wheels.

### Write behavior

For each skill and target destination:

- Missing destination: write file, report `installed`.
- Existing identical file: report `unchanged`.
- Existing different file without `--force`: report `skipped` and return exit
  code `1` after processing all entries.
- Existing different file with `--force`: overwrite and report `updated`.
- `--dry-run`: perform the same comparisons but write nothing and prefix
  statuses with `would-`.

Human output goes through stderr log helpers where appropriate; the per-skill
plan is printed clearly for terminal users. This SPEC does not add a JSON
contract for `decree agents`.

`decree init --with-agents` adds the per-skill results to init's existing
`actions[]` JSON contract with `kind: "agent-skill"`. Its corpus creation
summary remains unchanged: skill writes are setup side effects, not
PRD/ADR/SPEC corpus creations.

### Hooks

`--hooks` calls `install_claude_hook(project_root)` from
`src/decree/commands/hook.py` only when the selected target includes Claude and
scope is `project`. User-scope hook installation is rejected with a clear error
because the existing hook implementation is deliberately project-local.

`decree init --with-agents` never installs hooks. Hook setup remains explicit
via `decree agents install --target claude --scope project --hooks`.

### Skill content

Add/update portable skills:

- `decree-ddd`: current project-state loop, required `--bucket` on `decree new`,
  sprint-aware progress, and `decree generate-html` as the local board review
  surface.
- `decree-governs-suggest`: keep provider-free suggestion contract, and mention
  `decree agents install` as the supported install path.

## Testing Strategy

Add `tests/test_agents.py` with tmp-path projects. Cover:

- Project-scope Codex install writes packaged skill files under
  `.codex/skills`.
- Project-scope Claude install writes packaged skill files under
  `.claude/skills`.
- `--target all` writes both host trees.
- User scope writes under a monkeypatched home directory.
- Existing identical files are `unchanged` and exit `0`.
- Existing different files are skipped and exit `1` without `--force`.
- `--force` overwrites existing different files.
- `--dry-run` writes no files.
- `--hooks` installs the Claude stop hook only for project-scope Claude target.

Validation:

- `uv run pytest tests/test_agents.py tests/test_generate_html.py -q`
- `uv run pytest tests/test_init.py tests/test_agents.py tests/test_cli.py -q`
- `uv run ruff check src/decree/commands/agents.py src/decree/cli.py tests/test_agents.py`
- `uv run ruff format --check src/decree/commands/agents.py src/decree/cli.py tests/test_agents.py`
- `uv run decree lint`
- `uv run decree index verify`

## Acceptance Criteria

- [x] `decree agents install` is registered in CLI help with target, scope,
  dry-run, force, and hooks options.
- [x] Packaged skill templates are installed for Codex project/user scopes.
- [x] Packaged skill templates are installed for Claude Code project/user
  scopes.
- [x] Existing different destination files fail closed unless `--force` is
  explicit.
- [x] `--dry-run` reports planned actions and writes nothing.
- [x] `decree agents status` reports installed/missing skills for the selected
  host and scope.
- [x] `--hooks` reuses the existing Claude stop-hook installer and is rejected
  for user scope.
- [x] `decree-ddd` portable skill documents the current bucket, sprint, and HTML
  board workflow.
- [x] Docs and README show the recommended Codex and Claude Code install flow.
- [x] Targeted tests cover install, status, dry-run, force, and hooks behavior.
- [x] `decree init --with-agents` scaffolds the project and installs
  project-local Codex/Claude skills without installing hooks.
- [x] `decree init --with-agents --dry-run` reports corpus and skill writes
  without touching disk.
