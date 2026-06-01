---
name: decree-governs-suggest
description: Use when an agent needs to generate governs suggestions for an existing decree corpus from `decree migrate governs --analyze --json`; produce only `decree.governs-suggestions.v1` JSON and let core decree validate, preview, and apply it.
---

# decree governs suggest

Use this skill to backfill `governs:` frontmatter without adding LLM provider
logic to core decree.

## Contract

Core decree owns:

- deterministic analysis with `decree migrate governs --analyze --json`
- validation of `decree.governs-suggestions.v1`
- diff preview and writes through `--apply-suggestions`

The agent owns:

- any LLM call, prompt, retry, rate limit, and provider authentication
- deciding whether a document has enough evidence for a suggestion
- writing the suggestions JSON file

## Workflow

1. Run the deterministic analysis:

   ```bash
   uv run decree migrate governs --analyze --json > governs-analysis.json
   ```

2. Read `governs-analysis.json`.

3. For each document where `needs_governs` is true, inspect:

   - `document_id`
   - `title`
   - `document_type`
   - `candidate_paths`
   - `body_excerpt`

4. Write `governs-suggestions.json`:

   ```json
   {
     "schema": "decree.governs-suggestions.v1",
     "suggestions": [
       {
         "document_id": "SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S",
         "governs": ["src/decree/commands/migrate.py"],
         "confidence": "high",
         "rationale": "The SPEC defines migrate governs behavior and acceptance criteria."
       }
     ]
   }
   ```

5. Preview through core decree:

   ```bash
   uv run decree migrate governs --apply-suggestions governs-suggestions.json
   ```

6. Apply only when the user explicitly asks for writes:

   ```bash
   uv run decree migrate governs --apply-suggestions governs-suggestions.json --apply --yes
   ```

## Suggestion Rules

- Use repo-relative paths only.
- Do not use absolute paths.
- Do not include `..` path segments.
- The path before an optional `#symbol` must exist on disk.
- Do not duplicate paths.
- Do not suggest for documents that already have `existing_governs`.
- If evidence is weak, omit the document from `suggestions` and explain the
  omission in your response instead of guessing.
- Never edit frontmatter directly for this task. Always pass suggestions back
  through `decree migrate governs --apply-suggestions`.

For deeper agent integration context, read
[LLM Agent Integration](../../docs/llm-agent-integration.md).
