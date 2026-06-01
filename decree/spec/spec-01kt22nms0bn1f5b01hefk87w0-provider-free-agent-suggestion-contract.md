---
date: 2026-05-12
governs:
- src/decree/commands/migrate.py
- src/decree/commands/intent_check.py
- src/decree/commands/mcp_server.py
- src/decree/llm_io.py
- skills/decree-governs-suggest/SKILL.md
id: SPEC-01KT22NMS0BN1F5B01HEFK87W0
references:
- PRD-01KT22NMRTAF9581AXC53EHQTW
- SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S
- SPEC-01KT22NMS0KTWGNKB36RR7K0JR
status: implemented
---

# SPEC-01KT22NMS0BN1F5B01HEFK87W0 Provider-Free Agent Suggestion Contract

## Overview

Decree core must not own Claude Code, litellm, API-key, model-resolution, or
subprocess behavior. Those are agent-runtime concerns. Core decree owns the
deterministic contract: analyze the corpus, validate explicit suggestions, and
apply only reviewable frontmatter diffs.

This replaces the earlier Claude Code subprocess-provider draft. That draft
would have added `claude-code/...` model routing and a `claude -p` subprocess
adapter into `src/decree/llm_io.py`. The implementation direction changed:
LLM-backed suggestion generation belongs in an agent skill/plugin, not in the
library core.

## Technical Design

### Core responsibility

`decree migrate governs` has two explicit modes:

```bash
decree migrate governs --analyze --json
decree migrate governs --apply-suggestions suggestions.json [--apply] [--yes]
```

`--analyze --json` emits `decree.governs-analysis.v1`:

- document ID, path, type, status, and title
- whether `governs:` is missing
- existing `governs:` values
- deterministic candidate paths mentioned in the document body and present on
  disk
- a body excerpt for an external agent to reason over
- explicit rules for the required suggestions schema

`--apply-suggestions` accepts only `decree.governs-suggestions.v1`:

```json
{
  "schema": "decree.governs-suggestions.v1",
  "suggestions": [
    {
      "document_id": "SPEC-01KT22...",
      "governs": ["src/decree/commands/migrate.py"],
      "confidence": "high",
      "rationale": "The SPEC owns the migrate governs command."
    }
  ]
}
```

Core validates every suggestion before it can write:

- schema must match
- document ID must exist in the selected corpus scope
- entries must be repo-relative strings
- absolute paths and `..` segments are rejected
- duplicate paths are rejected
- path part before optional `#symbol` must exist on disk
- existing `governs:` arrays are never overwritten silently
- invalid suggestions surface as errors and block writes

### Agent responsibility

An agent skill may:

1. run `decree migrate governs --analyze --json`
2. call any model/runtime, including Claude Code, OpenAI, local models, or a
   human review workflow
3. produce `decree.governs-suggestions.v1`
4. call `decree migrate governs --apply-suggestions suggestions.json`

The skill owns provider prompts, auth, subprocess flags, retries, rate limits,
and any runtime-specific behavior.

This repository includes a portable agent skill at
`skills/decree-governs-suggest/SKILL.md`. It is source-controlled guidance for
agents; packaging that skill into a Claude Code/Codex marketplace bundle is a
separate distribution task.

### Removed from core

- `claude-code/...` model namespace
- `claude -p` subprocess adapter
- `DECREE_LLM_MODEL` provider chain
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` fallback logic
- litellm direct dependency
- prompt templates in `src/decree/migrate_prompts.py`
- `intent-check --judge-conflicts` provider execution

`decree intent-check` remains deterministic. It reports structural conflicts;
agent layers may post-process the JSON if semantic LLM judging is needed.

## Testing Strategy

The test suite covers the deterministic contract only:

- `tests/test_migrate_governs.py` covers analysis JSON, suggestions schema
  validation, path validation, dry-run behavior, write behavior, and CLI exit
  codes.
- `tests/test_llm_io.py` covers fenced JSON parsing only.
- `tests/test_intent_check.py` covers structural conflict behavior without
  provider calls.
- `tests/test_mcp_server.py` covers the deterministic MCP `intent_check`
  surface.

No live LLM calls or provider mocks are required in CI.

## v1 Acceptance Criteria

- [x] `decree migrate governs --analyze --json` emits
  `decree.governs-analysis.v1`.
- [x] Analysis output includes document identity, path, type, status, title,
  existing governs, candidate paths, body excerpt, and contract rules.
- [x] `decree migrate governs --apply-suggestions FILE` accepts only
  `decree.governs-suggestions.v1`.
- [x] Suggestions validation rejects unknown document IDs, invalid path syntax,
  duplicate entries, and missing on-disk paths.
- [x] Existing `governs:` arrays are not overwritten silently.
- [x] Preview mode renders unified diffs without writing files.
- [x] `--apply --yes` writes validated suggestions atomically.
- [x] Invalid suggestions block writes and return a non-zero exit code.
- [x] `src/decree/llm_io.py` no longer owns provider execution.
- [x] Claude Code subprocess routing is removed from core.
- [x] litellm is removed from direct runtime dependencies.
- [x] `decree intent-check` no longer resolves or calls LLM providers.
- [x] MCP `intent_check` no longer exposes a provider-backed judge flag.
- [x] CLI help documents the explicit analyze/apply-suggestions contract.
- [x] Docs explain that LLM suggestion generation belongs in agent skills.
- [x] A portable agent skill documents the external suggestion workflow.
- [x] Tests cover the deterministic contract without live LLM calls or provider
  mocks.
- [x] Decree dogfoods the new provider-free contract and passes lint, index
  verify, link check, and pytest.

## Deferred

- Package the portable `decree-governs-suggest` skill for Claude Code/Codex
  marketplace discovery.
- Add a JSON Schema file for suggestions if downstream integrations need
  schema validation outside Python.
- Add an optional semantic conflict-judge skill that post-processes
  `decree intent-check --json`.
