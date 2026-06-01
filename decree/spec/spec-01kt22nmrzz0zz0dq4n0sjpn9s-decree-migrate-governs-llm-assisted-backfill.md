---
date: '2026-05-12'
governs:
- src/decree/commands/migrate.py
- src/decree/migrate_prompts.py
id: SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S decree migrate governs — LLM-Assisted Backfill

## Overview

Closes PRD-01KT22NMRS4QGHSFDBZ858PP1T R9. New CLI: `decree migrate governs --suggest [--apply]`. For each document in the corpus *without* a `governs:` field, an LLM reads the document body (looking specifically at sections like "Files touched", "Affected files", "Scope", "Technical Design") and proposes a `governs:` array of repo-relative file paths. The proposal is output as a unified diff against the document; `--apply` writes the diff. Preview-first, LLM-assisted, no silent rewrites — exactly the design properties pinned in PRD-01KT22NMRS4QGHSFDBZ858PP1T R9.

After SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S lands, PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 closes and PRD-01KT22NMRSXYT95XE808VD8EV4 unblocks. The `git notes` backfill stays v2.

The implementation uses **`litellm`** as the LLM provider abstraction (PM call: "write less code, no brittle wrappers"). One library, one call signature, swap providers via a `--model` flag or `DECREE_LLM_MODEL` env var. Pinned to `>=1.83,<2` (post-2026-03-24 supply-chain incident; only clean releases).

## Technical Design

### CLI surface

```
decree migrate governs --suggest [--apply] [--model MODEL] [--dry-run] [--only ID]... [--project PATH] [--json]
```

- `--suggest` — emit a unified-diff proposal to stdout. Default mode; required for `--apply` to make sense (without it, `--apply` is rejected).
- `--apply` — apply the proposed diff to documents on disk. Refuses to run without first surfacing the diff (interactive y/n confirmation unless `--yes`).
- `--model MODEL` — model string. Resolution is explicit and shared via `decree.llm_io.resolve_model`: CLI flag, `DECREE_LLM_MODEL`, local `claude` CLI as `claude-code/sonnet`, `ANTHROPIC_API_KEY` as `claude-3-5-sonnet-latest`, `OPENAI_API_KEY` as `gpt-4o-mini`, then a hard configuration error if no provider is available.
- `--dry-run` — even with `--apply`, don't write. Print what would happen.
- `--only ID` (repeatable) — limit to specific document IDs.
- `--project PATH` — operate against a project at PATH.
- `--json` — emit machine-readable output.

Exit codes:
- `0` — proposal generated cleanly (with or without `--apply`).
- `1` — at least one document failed (LLM error, malformed response, network) — but other documents still processed; failures listed.
- `2` — config error (no API key, unknown model, no docs need backfill).

### Library: `litellm`

```python
from litellm import completion

response = completion(
    model=model,                              # provider/model-id string
    messages=[{"role": "user", "content": prompt}],
    temperature=0.0,                          # deterministic-ish for repeatability
    response_format={"type": "json_object"},  # ask for structured output
    timeout=60,
)
content = response.choices[0].message.content
```

This signature is the same regardless of whether `model` resolves to `claude-3-5-sonnet`, `gpt-4o-mini`, `bedrock/...`, or `ollama/...`. The API-key resolution (per-provider env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) is handled by litellm.

Pin in `pyproject.toml`: `"litellm>=1.83,<2"`.

### Prompt design

One prompt template, applied per-document. Lives in `src/decree/migrate_prompts.py` (so a future LLM-judge SPEC can reuse it). Shape:

```
You are helping migrate a software decision document to a typed `governs:` frontmatter field.

The document below describes a decision (PRD/ADR/SPEC). Identify the repo-relative file paths
that this document *governs* — files whose existence or shape is justified by the decision,
files that this decision's implementation creates or modifies, files that future changes to
this decision would affect.

Look specifically at sections titled:
  - "Files touched"
  - "Affected files"
  - "Scope" / "In scope"
  - "Technical Design"

Rules for the output:
  - Paths must be repo-relative (no leading `/`, no `..`).
  - Skip test files unless the document is specifically about test infrastructure.
  - Skip documentation files (decree/, docs/) unless the document is specifically about
    documentation infrastructure.
  - Use directory paths (ending with `/`) when a document governs a whole subtree.
  - Maximum 12 entries. If more candidates exist, pick the most-load-bearing ones.

Return strictly valid JSON of the form:
  {"governs": ["path/one.py", "path/two.py", "path/sub/"], "confidence": "high" | "medium" | "low", "rationale": "one-sentence explanation"}

Document body follows:

---

<doc body, truncated to ~6000 tokens if needed>
```

Confidence + rationale are surfaced in the unified-diff preview as comments so a human reviewer can prioritise scrutiny on `low`-confidence proposals.

### Suggestion flow

```python
def suggest_governs_for_doc(doc, llm_model) -> SuggestionResult: ...
```

Per-document:
1. Skip if `doc.meta.governs` is already non-empty AND not in `--force-regenerate` mode (off by default).
2. Build the prompt with the document's body (truncate to a model-safe length using simple character heuristic; v1 doesn't compute tokens).
3. Call `litellm.completion(...)`.
4. Parse the response JSON. Validate each path: must be a string, no leading `/`, no `..`. Invalid entries are dropped (logged as warnings).
5. Validate each *path part* (split on `#`) exists in the working tree at project_root. Missing paths included in the suggestion but flagged as `unverified`.
6. Build a `SuggestionResult { doc_id, current_governs, proposed_governs, confidence, rationale, verified_paths, unverified_paths, error?: str }`.

Across all docs, the command emits:
- **Human mode**: a series of unified-diff hunks per document, each prefixed with the LLM's confidence + rationale as comments.
- **JSON mode**: an array of `SuggestionResult` dicts.

### `--apply` mode

Writes the proposed `governs:` array to each document's frontmatter using `python-frontmatter` (already in deps). For `--apply` to run:
- Either the user typed `y` at the interactive confirmation, OR
- `--yes` was passed (CI-suitable).

Each successful write is reported. The user can re-run `decree migrate audit-coherence` (SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR) or `decree lint` afterwards to verify nothing broke. Path-existence validation (SPEC-01KT22NMRXFWNE61NSETKATHBA's `validate_governs_paths`) catches typos at next lint.

### Batching + parallelism

- Sequential per-document calls in v1. No parallel API calls.
- Rate limiting: trust litellm's defaults; surface failures at the per-doc level.
- For 50–500 doc corpora at ~3s/call, expect 2.5–25 minutes wall time per full run. Acceptable for a one-off migration tool.
- `--only ID` lets the user iterate per-doc cheaply.

### Files touched

- **Create**: `src/decree/migrate_prompts.py` — prompt templates (one for governs in v1).
- **Modify**: `src/decree/commands/migrate.py` — add `suggest_governs()`, `apply_governs()`, `suggest_governs_run()`, `apply_governs_run()` plus dataclasses.
- **Modify**: `src/decree/cli.py` — register `decree migrate governs --suggest|--apply`.
- **Modify**: `pyproject.toml` — add `"litellm>=1.83,<2"`.
- **Create**: `tests/test_migrate_governs.py` — unit tests with a fake/mock litellm client; one integration test with a recorded fixture (no live API call in CI).

### What this SPEC does NOT do

- **No live LLM API call in CI** — tests mock `litellm.completion`. Integration test uses a recorded JSON fixture.
- **No parallel/batched API calls** — sequential in v1. If runtime becomes painful, add `asyncio.gather` in v2.
- **No `--force-regenerate`** — if a doc already has `governs:`, skip it. Future flag for opt-in regeneration.
- **No diff preview UI / TUI** — plain stdout unified diff. Editors / TUIs are out of scope.
- **No streaming** — the response is small enough that streaming adds complexity without value.
- **No backfill of `references:` / `supersedes:` fields** — only `governs:` in v1. Other fields are a future SPEC.
- **No cost reporting** — litellm tracks it but we don't surface it. If a user wants a cost estimate, they can compute (`docs × 3000 input tokens × $`). Future polish.

## Testing Strategy

### Unit tests (`tests/test_migrate_governs.py`)

- **Suggest — clean parse**: mock litellm returning a well-formed JSON; `SuggestionResult` populated correctly.
- **Suggest — invalid path rejected**: mock returns `["/abs/path.py"]`; result drops the entry, logs warning, keeps valid entries.
- **Suggest — missing path flagged**: mock returns a path that doesn't exist on disk; entry kept but `unverified_paths` populated.
- **Suggest — empty proposal**: mock returns `{"governs": []}`; result has empty `proposed_governs`, no error.
- **Suggest — LLM error**: mock raises; `SuggestionResult` has `error` field set; other docs still processed.
- **Suggest — skip docs with existing governs**: doc has `governs: [...]` → skipped (unless `--force-regenerate`, which is OOS in v1).
- **Apply — writes frontmatter**: after suggest, `--apply --yes` writes the new `governs:` field to disk. Round-trip parse confirms.
- **Apply — interactive y/n**: when `--yes` not set, prompts for confirmation; `y` applies, `n` aborts.
- **--only filter**: only the named doc IDs are processed.
- **--dry-run**: `--apply --dry-run` doesn't write but reports what would change.

### Integration tests

- **End-to-end with mock**: tmp corpus with two docs missing governs; mock litellm returns predictable JSON; `--suggest --apply --yes` produces correct on-disk state.
- **Schema-stable JSON output**: `--json` round-trips cleanly.

### Dogfood validation

- After SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S ships, run against the decree project itself (~16 docs, only a few without governs at this point) to validate end-to-end. Capture output in completion report.
- **Real corpus** validation against jira-task-to-md's 167-doc corpus is **the proof point** — the PM runs this once and records sample suggestions + summary stats. This is the integration test PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 was designed for.

## v1 Acceptance Criteria

### Library + CLI

- [x] `src/decree/commands/migrate.py` extended with `suggest_governs()`, `apply_governs()`, `suggest_governs_run()`, `apply_governs_run()` + `SuggestionResult` dataclass.
- [x] `src/decree/migrate_prompts.py` exists with the governs prompt template.
- [x] `decree migrate governs --suggest` subcommand registered.
- [x] `--apply` flag works; refuses to run without preceding `--suggest` semantically (i.e., the diff is shown first).
- [x] `--model` flag + `DECREE_LLM_MODEL` env var + default chain works.
- [x] `--dry-run`, `--only`, `--yes`, `--json`, `--project` flags work.
- [x] Output as unified-diff (human) or structured array (JSON).
- [x] Exit codes match SPEC (0 clean, 1 partial failure, 2 config error).

### LLM integration

- [x] `litellm>=1.83,<2` added to `pyproject.toml`.
- [x] Single `completion()` call signature used for all providers.
- [x] Response parsing: validates JSON shape, drops malformed entries with warnings.
- [x] Path validation: existing paths → `verified`, missing → `unverified` (kept but flagged).
- [x] Skips docs that already have `governs:` (unless future opt-in flag).
- [x] Per-doc error isolation: one LLM failure doesn't abort the batch.

### Apply mode

- [x] Writes via `python-frontmatter`; round-trip parse confirms.
- [x] Interactive y/n confirmation unless `--yes`.
- [x] `--dry-run` prevents writes.

### Tests

- [x] All unit + integration cases mocking `litellm.completion`.
- [x] No live API calls in CI; recorded fixtures used for one integration test.
- [x] Full test suite passes (434 baseline + new tests).

### Dogfood

- [x] SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S's frontmatter declares appropriate `governs:` after implementation.
- [x] PM runs `decree migrate governs --suggest` against decree's own corpus; output captured in completion report.
- [x] PM runs once against jira-task-to-md's 167-doc corpus (or a sampled subset for cost reasons) and records summary stats: success rate, average confidence, example suggestions.

## What this does NOT do (deferred)

- [ ] Live API calls in CI.
- [ ] Parallel / batched API calls.
- [ ] `--force-regenerate` for docs that already have governs.
- [ ] TUI / interactive editor.
- [ ] Backfill of `references:` / `supersedes:` fields.
- [ ] Cost reporting / budget guards.
- [ ] `decree migrate backfill-trailers` (git notes) — v2.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 — the requirement this SPEC closes.
- SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR — audit-coherence half of R9 (already shipped).
- SPEC-01KT22NMRXFWNE61NSETKATHBA — typed `governs:` field this SPEC backfills.
- `litellm` docs — https://docs.litellm.ai
- PM litellm verdict: post-2026-03-24 supply-chain incident, pin `>=1.83`; cost dashboards / proxy server / fallbacks are not used here, but the unified call signature is the reason to adopt.
