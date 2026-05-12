---
date: '2026-05-12'
status: approved
---

# PRD-003 Queryable Decision Provenance Graph

## Problem Statement

Decree today validates that documents are internally well-formed (frontmatter, cross-references, status transitions, checkbox progress). It does not make those documents *queryable* by the agents and tools that need them at the moment of code change.

Three concrete consequences are observable in real workflows:

1. **No governed-file retrieval.** An LLM about to modify `src/foo.ts` cannot ask "what decisions govern this file?" without a human translating prose ADRs into a mental index. Decree has no `decree why <path>`, no `governs:` frontmatter field, no reverse index from file → decision. Embedding similarity (the default RAG answer) retrieves documents that *talk about* a topic; it does not retrieve documents that *govern* a path. These are different queries, and only the second one is load-bearing for code change.

2. **The SPEC ↔ commit link is prose, not structure.** Today a SPEC says "implemented in commit abc123" in its body, or it doesn't say at all. The link rots on rebase. `git log --grep` cannot find it. There is no way to ask "show me every commit that implemented SPEC-091" or "is SPEC-091 stale because the files it governs have changed since its status was set?". The provenance graph that should exist between decisions and commits exists only in the heads of the engineers who wrote both.

3. **Decree state is invisible to its consumers.** There is no MCP server, no `--json` output, no stable API. Every consumer (the suppression-expiry ast-check in the Electron app, future Claude Code skills, the planned intent-review panel) re-implements frontmatter parsing in regex. The data exists; the access surface does not. As long as the access surface is "shell out and parse human-formatted text," decree cannot be the source of truth for any system that needs to act on its data.

The failure mode this enables is documented in market research (`docs/market-analysis/discussion-notes.md`): Claude Code rebuilding an abandoned Redis queue because the decision to discontinue it "lived in a Slack thread, a couple of PR comments, and the heads of three engineers — places code search cannot reach." Decree exists to give those decisions a permanent home. This PRD extends decree from "home for decisions" to "queryable provenance graph for decisions," which is the form they have to take if downstream agents and dashboards are going to honor them.

## Requirements

### R1: Provenance graph as SSOT

- The on-disk decree directory (markdown frontmatter + body) remains the source of truth for *authoring*. A SQLite index becomes the source of truth for *querying*.
- Tables (minimum): `decisions(id, type, status, ...)`, `governs(decision_id, path, symbol?)`, `commits(sha, decision_id, trailer_kind)`, `refs(from_id, to_id)`.
- The index is rebuildable from the markdown corpus + `git log` at any time (`decree index rebuild`). It is not authoritative — it is derived.
- Every existing decree command (`lint`, `progress`, `ddd`) and every new one in this PRD reads from the index, not from re-parsing frontmatter on each invocation.

### R2: `governs:` frontmatter field

- New optional frontmatter field on **any document type configured in `decree.toml`** — SPEC, ADR, PRD, and custom types (e.g., the DDR — Design Decision Record — used by some consumers): `governs: [<path>, <path>#<symbol>, ...]`.
- File-level entries (v1): `src/decree/c4.py`, `apps/desktop/src/renderer/src/features/playgrounds/`.
- Symbol-level entries (v2): `src/decree/c4.py#validate_c4`, resolved via tree-sitter or LSP. v2 because file-level renames are the most common breakage in LLM-authored codebases.
- `decree lint` validates listed paths exist in the working tree at the configured repo root.
- The field is opt-in per document. Documents without `governs:` participate in the index as before but contribute zero path-based retrieval signal until the field is added (via manual edit or `decree migrate` — see R9).

### R3: `decree why <path>` and `decree refs <id>`

- `decree why <path>` — given a file path (or `path#symbol`), return the set of decisions that govern it, ordered by status (accepted/approved/implemented first), then by recency.
- `decree refs <id>` — given a decision id, return the reverse index: what other decisions reference it, what commits implement it (via trailer), what files it governs.
- Both commands support `--json` output for programmatic consumers.

### R4: Git-trailer SPEC ↔ commit binding

- A `decree commit` wrapper inspects the staged diff, infers the "active SPEC" (the SPEC with the most-recent unchecked AC whose file pattern matches the staged files), and prepends `Implements: SPEC-NNN` to the commit message.
- The user can override or skip the inference.
- `decree lint` (with a config opt-in) validates that every commit on the current branch tagged `Implements: SPEC-NNN` references a SPEC that exists and is in an allowed status.
- Rebase-safe: trailers travel with the commit body, not with the SHA.

### R5: MCP server with task-shaped tools

- A first-class MCP server exposes decree state as tools, not entity CRUD.
- Minimum tool surface: `decree.why(path)`, `decree.refs(id)`, `decree.stale()`, `decree.intent_review(diff)`, `decree.health()`.
- The MCP server reads from the index — it is a thin query layer, not a re-implementation of decree's logic.
- Distribution shape (FastMCP Python wrapper vs. native TS) is an ADR decision, not a PRD decision.

### R6: Coherence gates

- `decree lint` flags incoherent states the current lint misses. Gates apply across **any document type configured in `decree.toml`**, not just SPEC/ADR:
  - **Terminal-status vs. checkbox progress**: a document whose status is configured as terminal-success (e.g., SPEC `implemented`, PRD `implemented`) has <100% of its primary checkboxes checked.
  - **Deferred-items counted separately**: checkboxes inside a section titled "What this does NOT do", "Deferred", "Future work", or "v2 backlog" are tracked as a separate progress bar from primary acceptance criteria — so v2 backlog doesn't drag the primary AC progress down. (Section-title patterns are configurable per-type in `decree.toml`.)
  - **Unreferenced active decisions**: a document whose type is configured as expecting downstream references (e.g., ADR expects a SPEC; PRD expects an ADR or SPEC) is in an active status (`accepted`, `approved`) but has no document referencing it after N days. Threshold is configurable per type.
  - **Status-field requirements**: extends decree's existing `status_field_requirements` (e.g., `superseded` requires `superseded-by`) — already in decree; just made queryable via the index.
- **All gates are opt-in per project via `decree.toml`.** No gate is enabled by default. Consumers with large existing corpora (e.g., 100+ documents) use `decree migrate audit-coherence` (R9) to assess impact before enabling each gate.

### R7: Staleness and ungoverned-hotspots health report

- `decree health` (or `decree stale`) reports:
  - Decisions whose governed files have churned more than N commits since the decision was last touched.
  - High-churn files in the working tree with no governing decision ("ungoverned hotspots" — the Repowise data-push inversion of author-pull ADR practice).
- Output supports `--json`.

### R8: Intent-review consumer API

- The Electron app (or any consumer) can call `decree.intent_review(diff)` and receive a structured response: which decisions govern the changed paths, which are stale, which have unchecked ACs, which conflict (e.g., two SPECs governing the same file with contradictory directives).
- The API returns data; rendering belongs to the consumer.

### R9: Corpus migration tooling

Existing decree consumers (the dogfood at 7 documents; jira-task-to-md at 167) cannot adopt this PRD's new features through hand-edits at scale. A `decree migrate` command provides preview-first, LLM-assisted, opt-in migration for the two specific surfaces that require corpus-wide work — without rewriting any file the user hasn't reviewed.

- **`decree migrate governs --suggest`** — for each existing document, an LLM reads its body (looking specifically at sections like "Files touched", "Affected files", "Scope", and any prose mentioning paths) and proposes a `governs:` frontmatter array. Output is a unified diff against the current corpus, printed to stdout (or written to `decree-migrate-governs.patch`). No files are modified.
- **`decree migrate governs --apply`** — applies the suggested diff after the user has reviewed it. Idempotent — re-running it on already-migrated documents is a no-op.
- **`decree migrate audit-coherence`** — dry-run R6's coherence gates against the current corpus. Reports, per gate, which documents would fail and the reasons. No changes made. The output is the prerequisite for safely enabling any R6 gate on a corpus with >50 documents.
- **`decree migrate audit-coherence --fix`** — interactive: for each violation, prompt the user to fix (open in `$EDITOR`), defer (record an exception in `decree.toml`), or skip.
- **`decree migrate backfill-trailers`** (v2, optional) — walks `git log`, proposes `git notes refs/notes/decree` annotations linking historical commits to SPECs. Human confirms each suggestion. Uses `git notes` rather than commit-message rewrite to avoid history mutation.
- **`decree migrate --dry-run`** — applies to every subcommand. Shows what would change without writing.

**Design properties (load-bearing):**
- *Preview-first*: every subcommand has a `--suggest` / `audit` / `--dry-run` mode. Nothing is rewritten silently.
- *LLM-assisted, not LLM-decided*: the `governs:` suggester proposes; the user accepts. A 128-SPEC corpus cannot be hand-authored; trusting an LLM blindly is reckless. The two-step (suggest → apply) is the user's control surface.
- *Per-gate opt-in*: R6 gates are enabled one at a time through `decree.toml`, each preceded by an `audit-coherence` run for that gate. No "big bang."
- *Reversible*: `decree migrate governs --apply` produces a single commit (or a single patch); reverting is a `git revert` or a `git apply -R`.
- *Validated against the real-world corpus*: the SPEC implementing R9 ships with an integration test against jira-task-to-md's 167-document corpus. If migration is incorrect there, it's incorrect anywhere.

**What R9 explicitly does not do:**
- It does not preserve backward compatibility through forever-flags. There is no `--legacy-mode` left in decree after migration; the post-R9 codebase is the only codebase.
- It does not maintain dual read paths in decree itself. Old "string-match the affected_files prose" code paths are deleted once `governs:` is the way, not kept as a fallback.
- It does not perform automated history rewrites. `git notes` for trailer backfill is additive; no `git filter-branch`, no commit-message rewrites.

## Success Criteria

- **Query latency**: `decree why <path>` returns in <100ms on a corpus of 100+ decisions. Frontmatter re-parsing is eliminated from the hot path.
- **MCP visibility**: a Claude Code session in a decree-enabled repo can call `decree.why(path)` before modifying a file and receive the governing decisions without shelling out and parsing text.
- **Structural SPEC↔commit binding**: every SPEC that transitions to `implemented` has at least one commit with `Implements: SPEC-NNN` in its trailers, validatable via `git log --grep="Implements: SPEC-"`.
- **Staleness surface**: a SPEC whose governed files have changed without the SPEC being touched is flagged automatically. Today this is invisible.
- **Coherence**: a SPEC cannot be marked `implemented` with deferred-to-v2 items dragging primary AC progress below 100% (this PRD's existence already documents the v1 dogfood: SPEC-001 reports 86% but its v1 ACs are 100%).
- **Consumer fan-out**: at least one downstream consumer (the Electron app's intent-review panel, or the existing suppression-expiry ast-check) reads decree state via the MCP/`--json` API instead of regex.
- **Migration completeness**: `decree migrate` (R9) successfully applies to jira-task-to-md's 167-document corpus — `governs --suggest` produces a reviewable diff covering ≥95% of SPECs and ADRs; `audit-coherence` runs against the full corpus without crashing and produces a per-gate violation report. The migration is the integration test for R2 + R6 working at real-world corpus scale.
- **No backward-compat surface in decree itself**: after R9 has been run against a consumer's corpus, there is no remaining code path in decree that reads "old format" documents (e.g., string-matching affected_files prose). The post-migration codebase is the only codebase.

## Scope

**In scope (v1):**
- SQLite index schema + sync + rebuild command.
- `governs:` field at file level (any configured type), validated by lint.
- `decree commit` wrapper with `Implements: SPEC-NNN` trailer inference.
- `decree why`, `decree refs`, `decree stale`, `decree health` commands.
- `--json` output across all read commands.
- MCP server exposing the five task-shaped tools listed in R5.
- Coherence gates (R6) — opt-in per project, per gate.
- **Migration tooling (R9)** — `decree migrate governs --suggest/--apply` and `decree migrate audit-coherence`. Validated against jira-task-to-md's 167-doc corpus.

**In scope (v2, after v1 ships):**
- Symbol-level `governs:` (tree-sitter or LSP-backed).
- Intent-review consumer API surface (`decree.intent_review(diff)`) and the Electron app panel that consumes it.
- Multi-signal scoring (Repowise-style: title 3×, rationale 2×, context 1.5×, path-match bonus) for ranking decisions in `why` results.
- `decree migrate backfill-trailers` — `git notes refs/notes/decree` annotation of historical commits with their implementing SPEC IDs. Deferred to v2 because it requires inference (matching commits to SPECs) and is purely additive on top of v1's forward-only trailer convention.

**Out of scope (v1):**
- Replacing the markdown source of truth — the index is derived, not authoritative.
- Embeddings, hybrid retrieval, learned re-rankers, GraphRAG-style community summarization, temporal queries, conflict detection, LSP server, cross-repo provenance. These are **deferred to PRD-004 (state-of-the-art decision reasoning)** as research directions, not rejected. v1 establishes the keyword-scored baseline so PRD-004's experiments have something to ablate against.

> **On Repowise**: decree is an educational/research project; the AGPL-3.0 boundary is not a constraint here. Decree still replicates Repowise's schema and tool surface under MIT rather than vendoring Repowise — but the rationale is *educational leverage* (we learn more by reimplementing the decision-retrieval pipeline ourselves) rather than license avoidance. If a future direction calls for vendoring or forking Repowise, that's a decision available to us.

## Dependencies (load-bearing)

This PRD's implementation is anchored on existing, proven libraries. SPECs that reimplement any of these in-house should fail review.

| Concern | Library | License | Rationale |
|---|---|---|---|
| SQLite schema, FTS5, migrations, JSON columns | **`sqlite-utils`** | Apache-2.0 | Single biggest "don't build this" win — saves ~300 LOC of CREATE TABLE / migration boilerplate. Maintained by Simon Willison, used in production by Datasette. |
| Git churn, co-change, hotspot mining | **`pydriller`** | Apache-2.0 | "Files modified in commits touching SPEC-X" is one method call. R7's ungoverned-hotspots reduces to ~30 lines of pydriller. |
| Git plumbing (log, diff, notes, trailers) | **`GitPython`** | BSD | Standard, permissive, stable. Use `pygit2` only if perf becomes a measurable issue. |
| Markdown AST for link/reference extraction | **`mistletoe`** | MIT | Typed AST, faster than markdown-it-py. Replaces any regex over `[[wikilinks]]` or `[text](path)`. |
| In-memory graph queries (supersedes chains, reachability) | **`networkx`** | BSD | Reachability, transitive closure, cycle detection. Never roll graph traversal. |
| MCP server framework | **`mcp[cli]`** (official Python SDK, with FastMCP merged in) | MIT | Canonical implementation. `@mcp.tool()` decorators. No third-party wrapper needed in 2026. |
| Frontmatter parsing | **`python-frontmatter`** | MIT | Already a decree dep. |
| Schema validation | **`pydantic>=2`** | MIT | Already a decree dep. R2 `governs:` field validation extends existing schemas. |
| Diff parsing (R8 intent-review) | **`unidiff`** | MIT | Use only if pydriller's modified-files API is insufficient — often it isn't. |
| File-watcher mode (optional R-future) | **`watchdog`** | Apache-2.0 | Only if we add `decree watch` for IDE integration. |
| Git trailer parse/write (R4 SPEC↔commit) | **`git interpret-trailers`** (built into git itself) | git's license | No third-party trailer parser. `git log --format="%(trailers:key=Implements)"` is the read path. |
| Git-notes for ex-post governance attachment | **`git notes`** (built into git itself) | git's license | `refs/notes/decree` lets us link governance to historical commits without rewriting history. Design choice — see ADR-0002 open question. |

**License hazard:** all new deps are MIT/Apache/BSD. Decree remains MIT-distributable. **Do not** add Repowise (AGPL-3.0) or any GPL-encumbered library to the dependency tree.

## References

- `docs/market-analysis/discussion-notes.md` — Repowise (governed-file retrieval, four-signal architecture) and entire.io (provenance graph in git, intent review) findings that motivate this PRD.
- `docs/market-analysis/repowise/` — full Repowise analysis.
- `docs/market-analysis/entire-io/` — full entire.io analysis.
