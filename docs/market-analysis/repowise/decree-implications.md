# Repowise → decree: Improvement Implications

Ordered by leverage (most to least). Each item: Repowise insight, what decree gets, rough LOC, prerequisites.

Sources: https://www.repowise.dev/, https://docs.repowise.dev, blog posts (retrieved 2026-05-12). decree source: `/Users/doruk/Desktop/SIDE_HUSTLE/decree/src/decree/`.

---

## 1. `governs:` frontmatter field + `decree why <path>` retrieval command

**Repowise insight**: Decision records linked to graph nodes via explicit `affected_files` lists receive a +5.0 scoring bonus (exact path) or +3.0 bonus (parent-directory) during retrieval. This means "what governs this file?" is answerable without full-text search if the structural link exists in the document. The `get_why` path mode demonstrates the pattern: query contains a file path → retrieve decisions by governed-file match first, fall back to text search second.

**What decree gets**: A `governs:` frontmatter field (list of paths/globs) in `DocFrontmatter`. A new `decree why <path>` command that: (1) builds a reverse index of path → SPEC IDs from all `governs:` fields, (2) scores candidates with path-match bonus + field-weighted keyword scoring (title 3x, context 1.5x, body 1x), (3) applies a dominance ratio gate — if `top_score < 1.2 * second_score`, returns candidates without picking a winner, (4) reports "no governing document" when no match exists rather than returning the nearest-scoring document. This makes the invisible visible: `decree why apps/src/renderer/pages/playgrounds/ui/FilterBar.tsx` becomes a real query.

**`lint.py` integration**: `validate_governs_paths_exist()` — check that every path in `governs:` exists on disk. ~30 lines in `validators.py`. Hook into `lint.run()` alongside the existing `validate_attachments_exist` pattern (already opt-in via `--check-attachments`; governs-path checking should be on by default since it is a structural claim, not an optional attachment).

**Rough LOC**: ~150 lines total — 20 in `parser.py` (new field), 30 in `validators.py`, 100 in `commands/why.py` (new command), 10 in `cli.py` (register command).

**Prerequisites**: None. Additive. No breaking changes to existing schema if `governs:` is optional.

---

## 2. `--json` output flag across all commands

**Repowise insight**: Repowise's MCP integration works because every tool returns structured data. Their "raw text vs. synthesized answer" blog post makes this explicit: "The fastest way to make an MCP tool worse is to answer the question for the model." The corollary for CLI tools: the fastest way to make a CLI tool worse for programmatic consumers is to return human-formatted text. The pattern they endorse: `inspect → return raw evidence; summarize → bounded synthesis with citations`. decree's current output is all human-formatted — fixed-width table text with `success()` / `fail()` ANSI output. There is no machine-readable path.

**What decree gets**: `--json` on every command (`lint`, `progress`, `status`, `why`, `index`, `graph`). Each command returns a JSON object with a stable schema: `{"ok": bool, "errors": [...], "data": {...}}`. `lint --json` returns `{"ok": false, "errors": ["ADR-0042: missing section Context"]}`. `progress --json` returns `{"ok": true, "data": {"docs": [{"id": "SPEC-001", "status": "implemented", "done": 14, "total": 14, "pct": 100}, ...]}}`. This unblocks three consumers that currently re-parse text: (a) the husky pre-commit hook, (b) CI status reporting, (c) the MCP server (item 4 below). Without `--json`, items 3 and 4 on this list require parsing human text. With it, they are thin wrappers.

**Rough LOC**: ~80 lines total — add a `--json` flag to each command's `argparse` setup (10 lines in `cli.py`), add a `emit(args, data)` helper in `log.py` that checks `args.json` and either prints JSON or falls through to existing human output (~20 lines), update each command's `run()` to collect results into a dict and call `emit()` (~50 lines across 6 commands).

**Prerequisites**: None.

---

## 3. Coherence gate in `lint`: status vs. checkbox completion

**Repowise insight**: Repowise's `get_answer` dominance ratio gate establishes the principle: do not let a high-confidence claim survive weak evidence. A SPEC marked `implemented` with 40% of its checkboxes complete is making a false claim. The status says "done"; the evidence says "less than half done." Repowise would call this an ungoverned hotspot in the confidence dimension — the label exceeds what the data supports.

**What decree gets**: A new lint rule: `validate_status_coherence()`. For each document with status `implemented` (or any configurable terminal status), count checkboxes. If `done / total < threshold` (suggested default: 0.80), emit an error: `SPEC-042: status 'implemented' but only 6/14 items complete (43%)`. The threshold should be configurable per doc type in `decree.toml` — some types may not use checkboxes at all and should be exempted. The check must short-circuit when `total == 0` (no checkboxes means the document is not checkbox-driven and the rule does not apply). This closes the most common coherence failure in LLM-authored SPEC workflows: the model marks a SPEC done when the task is conceptually complete but before writing the test cases.

**Rough LOC**: ~40 lines — `validate_status_coherence()` in `validators.py` (~25 lines), hook into `lint.run()` (~10 lines), add `coherence_threshold` to doc type config (~5 lines in `config.py`).

**Prerequisites**: None — `progress.py` already has `_count_checkboxes()`. Copy the regex or import it from a shared location.

---

## 4. MCP server: task-shaped tools over the existing commands

**Repowise insight**: Repowise ships seven task-shaped MCP tools rather than entity CRUD. Their blog post is direct: "The core problem is not that entity-shaped tools are low level. It is that they are shaped like nouns in your database, while the agent's job is a verb." For decree, the agent's verbs are: check status, find governing document, assess progress, validate. Exposing these as MCP tools makes decree state visible to Claude Code without any changes to the underlying Python — the MCP server is a thin JSON-over-subprocess wrapper.

**What decree gets**: A `decree-mcp` package (or a `pnpm mcp:decree` target in the project that uses decree) that exposes five tools:
- `decree_lint()` → structured errors list (requires item 2 for `--json`)
- `decree_progress(id?)` → progress table or single-doc progress (requires item 2)
- `decree_why(path)` → governing SPEC(s) with confidence (requires item 1)
- `decree_status(id, action)` → transition a document status
- `decree_health()` → ungoverned hotspots + stale docs + coherence failures (requires items 1, 2, 3)

The server is a `FastMCP` or `mcp` Python package wrapper that shells out to `decree --json` and returns parsed JSON as tool results. No new business logic. Each tool is 10-20 lines of Python. The aggregate effort is small; the leverage is large because it makes decree's state queryable in-editor without leaving the AI agent context.

**Rough LOC**: ~200 lines — `src/decree/mcp_server.py` with five tool handlers shelling to `decree --json`, plus `pyproject.toml` entry point for `decree-mcp`.

**Prerequisites**: Item 2 (`--json` flag) is required. Items 1 and 3 expand the server's usefulness but are not blockers.

---

## 5. `decree health` command: ungoverned hotspots report

**Repowise insight**: The most operationally valuable Repowise feature is `repowise decision health` — the intersection of high-churn files with absence of decision-record coverage. Their framing: standard ADR practice is author-pull (people write records when they feel like it); health reporting is data-push (the system tells you which files are changing fastest and have no recorded rationale). This inverts the workflow from passive to active.

**What decree gets**: `decree health` command. In its minimal form (no git integration): load all documents with `governs:` fields, build the governed-path set, compare against a user-provided or auto-discovered source file list. Report files in the source tree that are not covered by any `governs:` field. Output: a list of uncovered paths sorted by directory, with a summary count. This is useful even without churn data — knowing that `apps/src/renderer/pages/playgrounds/ui/` has no governing SPEC is actionable information.

In a richer form (opt-in, requires git): run `git log --format=... --numstat` over the last N commits, compute per-file churn, sort uncovered files by churn descending. This surfaces the highest-risk ungoverned files first — the Repowise "ungoverned hotspot" pattern exactly. The git integration is ~30 lines using `subprocess.run(['git', 'log', ...])` and is entirely opt-in (if git is unavailable or `--no-git` is passed, fall back to alphabetical listing).

**Rough LOC**: ~120 lines — `commands/health.py` (~80 lines), `cli.py` registration (~5 lines), optional git churn helper (~35 lines). The git helper can be a standalone function since it does not touch decree's document model.

**Prerequisites**: Item 1 (`governs:` field) is required. Item 2 (`--json`) expands usefulness but not required for the initial command.

---

## 6. `decree refs <id>` reverse-index command

**Repowise insight**: Repowise's path-mode `get_why` surfaces all decisions affecting a given file. The structural analog in decree is: given a SPEC or ADR ID, find all other documents that reference it via `references:` frontmatter. This is the reverse of `validate_cross_type_references()` which checks that references are valid — the reverse command exposes the reference graph for navigation.

**What decree gets**: `decree refs <id>` command. Load all documents, build a reverse index (`referenced_by: dict[str, list[str]]`), print the list of documents that reference the queried ID. Combined with `--json`, this enables `decree refs ADR-0042 --json | jq '.data.referenced_by[]'` — useful in CI to understand blast radius when deprecating or superseding a document. Also useful for the MCP server's `decree_why` tool to answer "what depends on this decision?".

**Rough LOC**: ~60 lines — `commands/refs.py` (~50 lines, the reverse index is already implicit in `validate_cross_type_references()`), `cli.py` registration (~5 lines), `--json` output (~5 lines via the shared emit helper from item 2).

**Prerequisites**: Item 2 (`--json`) for full utility. No other dependencies — the reference data is already in `DocFrontmatter.references`.

---

## Priority Summary

| # | Feature | LOC | Prerequisite |
|---|---------|-----|--------------|
| 1 | `governs:` field + `decree why <path>` | ~150 | none |
| 2 | `--json` flag across all commands | ~80 | none |
| 3 | Coherence gate: status vs. checkboxes | ~40 | none |
| 4 | MCP server (5 task-shaped tools) | ~200 | item 2 required; items 1, 3 expand it |
| 5 | `decree health` ungoverned hotspots | ~120 | item 1 required |
| 6 | `decree refs <id>` reverse index | ~60 | item 2 for full utility |

Total: ~650 lines of new Python against an existing ~1,200-line codebase. Items 1-3 are independent and can be sequenced in any order. Item 4 depends on item 2. Item 5 depends on item 1. Item 6 depends on item 2 for full utility but can ship standalone.

The correct execution order if doing this in a single focused week: 2 → 3 → 1 → 4 → 5 → 6. Start with `--json` because it unblocks everything downstream, and it is the lowest-risk change (purely additive, zero schema changes, no existing behavior altered).
