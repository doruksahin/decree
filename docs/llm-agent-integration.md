# LLM Agent Integration

This document is the progressive-disclosure entry point for using decree from
LLM agents and automation.

For the full command capability map and new-project adoption sequence, start
with the [Capability Index](index.md).

## Contract

- `decree.toml` is the project contract. Document types, status lifecycles,
  required sections, coherence gates, and health thresholds live there.
- Frontmatter is authoring truth. `.decree/index.sqlite` is a derived query
  cache and must be rebuilt with `decree index rebuild` after corpus changes.
- Completion reports are generated snapshots, not authoring truth. If checked
  acceptance criteria change after a terminal status transition, refresh them
  with `decree report regenerate`.
- Commands that can be consumed by agents expose `--json` where the output is a
  stable schema. Prefer JSON for automation.
- Empty arrays are valid abstentions. Agents must not invent governance when
  `matches`, `governing_decisions`, or `conflicts` are empty.
- User-visible changes require a Towncrier fragment in `changelog.d/`. Agents
  should write the fragment in the same change while context is fresh.

## Recommended Agent Loop

1. Run `decree lint`.
2. Run `decree index rebuild`.
3. Before coding, run `decree intent-check --plan "..." --files ... --json`.
4. If the response recommends `draft_adr_first`, `update_spec_first`, or
   `resolve_conflict_first`, update decree documents before implementation.
5. After code exists, run `decree intent-review --json` to compare the diff
   against the same governance corpus.
6. Run `decree lint` again after changing decree documents.
7. Add or verify a `changelog.d/` Towncrier fragment for user-visible changes.

## LLM Provider Resolution

Commands that need an LLM use one shared model-resolution chain:

1. `--model MODEL`
2. `DECREE_LLM_MODEL`
3. `claude` on `PATH` -> `claude-code/sonnet`
4. `ANTHROPIC_API_KEY` -> `claude-3-5-sonnet-latest`
5. `OPENAI_API_KEY` -> `gpt-4o-mini`
6. Otherwise the command exits with a configuration error or returns an
   explicit `judge_error` field for MCP tool calls.

`claude-code/...` models route through the local Claude Code CLI. All other
model strings route through litellm.

Claude Code routing is deliberately constrained for batch use:

- single prompt, single turn
- `--output-format json`
- `--permission-mode plan`
- `--strict-mcp-config`
- no tools by default (`--allowedTools none`)
- API-key environment variables are not forwarded to the subprocess

This uses the user's local Claude Code subscription instead of Anthropic or
OpenAI API keys.

## No Hidden Fallbacks

- Missing indexes are errors with a hint to run `decree index rebuild`.
- Stale indexes are errors for query commands and MCP query tools. Rebuild the
  index before asking `why`, `refs`, `intent-check`, or `intent-review` to make
  governance claims.
- Per-document LLM failures in `decree migrate governs` are recorded on that
  document's result and do not abort the whole batch.
- Conflict-judge LLM failures never hide structural conflicts; they leave the
  semantic verdict empty or add `judge_error`.
- Non-git projects make git-derived health and commit-sync data unavailable.
  Commands must say this in their result or documentation instead of implying
  that no history exists.

## Responsibilities

- `src/decree/cli.py`: command registration and user-facing help only.
- `src/decree/llm_io.py`: provider resolution, Claude Code subprocess routing,
  litellm routing, and shared JSON parsing.
- `src/decree/index_db.py`: deterministic derived index and git trailer sync.
- `src/decree/commands/queries.py`: `why` and `refs` library/CLI behavior.
- `src/decree/commands/intent_check.py`: pre-code governance reports.
- `src/decree/commands/intent_review.py`: post-code diff governance reports.
- `src/decree/commands/migrate.py`: corpus migration/audit tooling.
- `src/decree/commands/mcp_server.py`: MCP tool wrappers; no duplicate query
  logic.

## Useful Commands

```bash
decree --help
decree lint
decree index rebuild
decree report regenerate --all --existing-only
decree why src/foo.py --json
decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX --json
decree progress --changed --base origin/main
decree intent-check --plan "..." --files src/foo.py --json
decree intent-review --json
decree migrate ids --dry-run
decree migrate audit-coherence --json
decree migrate governs --suggest --json
uv run towncrier create +.feature --content "Add governed lookup for auth files."
uv run towncrier check --staged
```
