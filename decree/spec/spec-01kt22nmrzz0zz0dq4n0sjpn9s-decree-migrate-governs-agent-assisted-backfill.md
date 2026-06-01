---
date: '2026-05-12'
governs:
- src/decree/commands/migrate.py
id: SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S decree migrate governs — Agent-Assisted Backfill

## Overview

Closes PRD-01KT22NMRS4QGHSFDBZ858PP1T R9. `decree migrate governs` helps
adopt typed `governs:` ownership links in an existing decision corpus without
silently rewriting documents.

Core decree is provider-free:

- `decree migrate governs --analyze --json` emits
  `decree.governs-analysis.v1`.
- An external agent, skill, script, or human review process produces
  `decree.governs-suggestions.v1`.
- `decree migrate governs --apply-suggestions FILE` validates suggestions and
  previews a unified diff.
- `--apply` writes only after explicit confirmation or `--yes`.

This keeps LLM prompting, model choice, auth, retries, and runtime-specific
behavior outside decree core while keeping validation and writes deterministic.

## Technical Design

### Analyze

```bash
decree migrate governs --analyze --json
```

Output schema: `decree.governs-analysis.v1`.

Each document item includes:

- `document_id`
- `document_path`
- `document_type`
- `status`
- `title`
- `needs_governs`
- `existing_governs`
- `candidate_paths`
- `body_excerpt`

Candidate paths are deterministic: decree extracts repo-relative path-looking
mentions from the document body and keeps only paths that exist on disk. The
body excerpt gives external agents enough context to reason without requiring
core decree to call a model.

### Suggestions

Agents must write:

```json
{
  "schema": "decree.governs-suggestions.v1",
  "suggestions": [
    {
      "document_id": "SPEC-01KT22...",
      "governs": ["src/decree/commands/migrate.py"],
      "confidence": "high",
      "rationale": "The SPEC defines the migrate governs behavior."
    }
  ]
}
```

### Apply

```bash
decree migrate governs --apply-suggestions governs-suggestions.json
decree migrate governs --apply-suggestions governs-suggestions.json --apply --yes
```

Validation is fail-closed:

- schema must match `decree.governs-suggestions.v1`
- document IDs must exist in the selected scope
- paths must be repo-relative strings
- absolute paths and `..` segments are rejected
- duplicate entries are rejected
- path part before optional `#symbol` must exist on disk
- existing `governs:` arrays are not overwritten silently
- invalid suggestions are reported and block writes

Writes use the existing atomic frontmatter update path. Preview mode renders a
unified diff and does not write.

## Testing Strategy

- Unit tests cover analysis schema shape and deterministic candidate path
  extraction.
- Unit tests cover suggestions schema validation, invalid path syntax,
  duplicates, missing paths, and existing `governs:` skip behavior.
- CLI tests cover JSON analyze output, JSON apply output, dry-run, write, and
  invalid-suggestion exit codes.
- No provider mocks or live LLM calls are used in CI.

## v1 Acceptance Criteria

- [x] `decree migrate governs --analyze --json` subcommand mode registered.
- [x] Analyze mode emits `decree.governs-analysis.v1`.
- [x] Analyze mode includes document identity, status, title, current governs,
  candidate paths, and body excerpt.
- [x] `decree migrate governs --apply-suggestions FILE` subcommand mode
  registered.
- [x] Suggestions mode accepts only `decree.governs-suggestions.v1`.
- [x] Invalid schema returns exit 2 with an explicit error.
- [x] Invalid suggestion entries return non-zero and do not write.
- [x] Existing `governs:` arrays are skipped instead of overwritten silently.
- [x] Preview mode renders unified diffs without writing.
- [x] `--apply --yes` writes valid suggestions.
- [x] `--dry-run` reports apply intent without writing.
- [x] `--only ID` scopes both analysis and suggestions validation.
- [x] `--json` emits machine-readable analyze/apply payloads.
- [x] No core LLM provider, model-resolution, API-key, or subprocess logic is
  required for governs migration.
- [x] Tests cover the deterministic contract without provider mocks.

## Deferred

- Package the portable `decree-governs-suggest` skill for Claude Code/Codex
  marketplace discovery.
- Add external JSON Schema files for consumers that want schema validation
  outside decree's Python implementation.
