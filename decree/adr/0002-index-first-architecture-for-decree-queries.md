---
date: '2026-05-12'
references:
- PRD-003
status: accepted
---

# ADR-0002 Index-First Architecture for Decree Queries

## Context and Problem Statement

PRD-003 calls for a queryable provenance graph: `decree why <path>`, `decree refs <id>`, `decree stale`, `decree health`, an MCP server, and an intent-review API surface. Each of those new commands needs to answer questions over the same data — frontmatter, cross-references, governs-links, git trailers — that today is reparsed from disk on every invocation.

The architectural question is where the query layer lives:

- Do we build a SQLite index as the new source of truth for queries and migrate every command (existing and new) to read from it?
- Or do we keep frontmatter as the only source of truth for queries and add new commands as additional frontmatter-walking passes?
- Or something between?

Decree today is ~1,200 lines of Python with no database dependency. Its commands all reparse `decree/**/*.md` on each invocation. At the current corpus size (4 documents in this dogfood repo, dozens to low hundreds in a real consumer) reparse latency is not visible. It will become visible once consumers issue many `why` queries per session (an LLM agent making 10–50 calls per task) and once `stale` / `health` need to correlate against `git log` output.

There is a second concern: an MCP server's whole point is to be a thin, stable, fast surface. If the MCP tool implementations are subprocess-shelling out to CLI commands that reparse frontmatter, the MCP tools inherit that cost and add subprocess startup on top. The MCP surface ends up only as reliable as the slowest CLI reparse path.

A third concern is dogfood timing. SPEC-001 is still in `draft` at 86% (with v2 backlog items in its checkbox list — exactly the kind of coherence issue PRD-003 R6 is meant to fix). PRD-002 is `approved` but at 0%. Migrating existing commands while in-flight work is open is the textbook setup for a stalled migration.

### Prior art: integrate vs. replicate

Before deciding on an internal architecture, the question is whether to *adopt an existing tool* rather than build a new one:

- **Repowise** (repowise.dev) is the closest prior art. It implements weighted SQLite scoring over decision documents, 7 task-shaped MCP tools, governed-file retrieval, and the "ungoverned hotspots" health signal — roughly half of PRD-003's R1, R3, R5, and R7. Repowise is AGPL-3.0; decree is MIT. **Decree is an educational/research project**, so the AGPL boundary is not the deciding factor. The actual reason for replicate-over-integrate is *educational leverage*: reimplementing the retrieval pipeline ourselves is where the learning lives. Repowise's schemas and tool surface (not copyrightable) are replicated; if a later direction makes vendoring/forking Repowise the right move, that option remains open.
- No MIT-licensed equivalent of Repowise's decision retrieval exists as of 2026-05-12. A targeted survey confirmed this (see the conversation context that produced this ADR).
- Existing ADR tools (`adr-tools`, `log4brains`, `adr-manager`, `adr-viewer`, Backstage's ADR plugin) all stop at static-site generation or grep-the-markdown queries. None offer a structured query layer. Decree already exceeds the feature set of `adr-tools`; the others are either editor-coupled (Dendron, Foam, Obsidian) or unmaintained.

The "build, not integrate" decision is therefore an *educational* choice (we want to understand the retrieval pipeline by building it), not a license-forced one. The architectural question that remains is *how* to build.

### Library leverage

The build cost is bounded by what we can lean on. The PRD's "Dependencies (load-bearing)" section locks five permissive libraries (`sqlite-utils`, `pydriller`, `mistletoe`, `networkx`, `mcp[cli]`) that collectively cover the majority of the implementation primitives: SQLite schema management, git mining, markdown AST extraction, graph traversal, and MCP plumbing. The estimated implementation budget (~1500 LOC over 2–3 weeks) assumes those libraries — without them the estimate doubles.

## Decision Drivers

- PRD-003 requires sub-100ms `decree why <path>` on a 100+ document corpus
- MCP server must not be a leaky wrapper over slow CLI reparses
- The on-disk markdown frontmatter must remain authoritative for *authoring* — no command-line ceremony to edit a SPEC
- New decree dependencies should be minimal and standard-library-friendly (SQLite is in CPython stdlib via `sqlite3`)
- Existing commands (`lint`, `progress`, `ddd`, `new`, `status`) work today; they should not regress while v1 of PRD-003 ships
- The index should be deterministically rebuildable from frontmatter + `git log`, never the source of truth itself
- Migration cost should be amortizable, not all-up-front

## Considered Options

### Option A: Index-first foundation (rebuild everything against the index)

Build the SQLite schema and sync layer first. Refactor every existing command (`lint`, `progress`, `ddd`, `new`, `status`) to read from the index. New commands (`why`, `refs`, `stale`, `health`) are SQL queries from day one. The MCP server is a thin layer over the same DB.

- Good: every command reads the same data the same way — one place to evolve schema, one perf profile
- Good: MCP latency is bounded by SQLite, not by frontmatter parsing
- Good: clean mental model — "frontmatter is for authoring, index is for querying"
- Good: the index can store derived data (governs-resolution against working tree, commit-trailer joins) without polluting frontmatter
- Bad: ~2 weeks of foundation work before the first user-visible feature ships; high WIP risk
- Bad: every existing command changes its read path simultaneously — large migration surface, large regression risk
- Bad: SPEC-001 and PRD-002 work has to either pause or land *after* the migration, which means more documents to migrate when the dust settles
- Bad: if the index design turns out to be wrong, the cost of a second migration is double

### Option B: Frontmatter-only, incremental (the discussion-notes 1→6 plan)

Keep frontmatter as the only data source. Add `--json` flag across all read commands (parsing output is the consumer's problem). Add `governs:` as a frontmatter field with lint validation but no index — `decree why <path>` walks every SPEC's `governs:` array on each invocation. MCP server shells out to CLI `--json`. `decree health` and `decree refs` do whatever-N is needed at query time.

- Good: each of the six items in the discussion-notes plan ships value independently
- Good: zero new dependencies, zero migration risk for existing commands
- Good: rollback per feature is trivial
- Bad: `decree why <path>` is O(N) frontmatter parses on every call; at 100+ documents this is hundreds of ms per query
- Bad: MCP server is a leaky wrapper — Claude Code making 30 `decree.why` calls per session pays 30 × N-parse cost
- Bad: `decree refs` does an O(N²) walk to compute reverse references on every invocation
- Bad: `decree stale` requires correlating frontmatter against `git log` — done from scratch every time
- Bad: each new command duplicates frontmatter-walking logic; bug surface grows linearly
- Bad: the index will probably be needed eventually (this is the same trajectory every project that started with grep-the-docs has hit), and putting it off makes the migration larger when it comes

### Option C: Hybrid — index as derived read-cache, frontmatter remains primary

Frontmatter remains the source of truth, including for existing commands. Add a SQLite index as a *derived read-cache*, refreshed by `decree lint` (and a pre-commit hook). Only the new PRD-003 commands (`why`, `refs`, `stale`, `health`) and the MCP server read from the index. Existing commands (`lint`, `progress`, `ddd`, `new`, `status`) are not migrated in v1 — they continue to read frontmatter.

The index is soft-state: any time `decree lint` (or `decree index rebuild`) runs, it rebuilds from frontmatter + `git log`. A stale cache is recoverable in one command. Drift between cache and frontmatter is caught by `decree lint --strict` comparing the two.

In v2, individual existing commands can opt in to read from the index ("`decree progress --use-index`"), then become index-default once we've measured stability. Migration is amortized over weeks, one command at a time, each with its own safety net.

- Good: new commands ship in the timeline of v1 — no 2-week foundation tax
- Good: existing commands unchanged → SPEC-001 and PRD-002 work proceeds in parallel without merge conflicts
- Good: MCP server gets a real DB-backed query surface, not a CLI wrapper
- Good: SQLite is stdlib — no new third-party dependency
- Good: the index can be deleted at any time (`rm .decree/index.sqlite`) and rebuilt — fail-safe
- Good: the cache-refresh model is well-understood (this is how `ctags`, `bundle install`, `npm install` work)
- Bad: two read paths exist (frontmatter for old commands, index for new commands) — a known coherence risk
- Bad: drift detection requires `decree lint --strict` to actually be run; if a user never runs it, drift can persist
- Bad: the endpoint (everything reads from the index) is the same as Option A, just reached more slowly — Option C is partly a deferral of Option A's hard work
- Bad: cache invalidation is the second-hard-problem-in-CS; we will get this wrong at least once

## Decision Outcome

**Chosen option: Option C (hybrid — index as derived read-cache).**

The decisive factor is dogfood timing. Option A's "rebuild everything" path is architecturally cleaner, but PRD-003 has to ship while SPEC-001 and PRD-002 are open, and a simultaneous migration of every existing command is the worst possible context for that. Option C ships the new query surface in v1 without touching the existing commands' read paths — they remain on frontmatter, they remain provably correct under the existing test suite.

The hybrid risk (drift between frontmatter and index) is real but bounded:
- The index is *derived*, never authoritative. If it disagrees with frontmatter, frontmatter wins; the index is rebuilt.
- Every `decree lint` run can include an index-freshness check (compare last-rebuilt mtime against frontmatter mtimes). A pre-commit hook makes this automatic for active projects.
- `decree lint --strict` compares the two and flags divergence. We make this part of CI for decree itself.
- SQLite is single-file and atomic; corruption is recoverable with `decree index rebuild`.

Option B is rejected because it makes the MCP server a leaky wrapper. PRD-003's success criteria require sub-100ms `why` latency and a stable MCP API; Option B cannot meet either without doing most of Option A's work anyway.

Option A is deferred, not rejected. The migration of existing commands to read from the index becomes a v2 work-stream (one SPEC per command, each independently shippable, each with `--use-index` flag → default-on → frontmatter path removed). The decision to do that migration can be re-evaluated after v1 lands and we have real query-volume data from MCP consumers.

### Consequences

- The SPEC that implements R1 (SQLite schema + sync) will design the schema for v1 *and* v2 query patterns — including the ones that existing commands would use, so v2 migration is purely a refactor of read paths, not a schema change.
- `decree index rebuild` becomes a top-level command from day one.
- The index file location is `.decree/index.sqlite` (project-local, gitignored by default — it's a cache).
- The decree.toml will gain a `[index]` section for cache configuration (rebuild triggers, drift-check strictness).
- MCP server, `why`, `refs`, `stale`, `health` all read from the index. `lint`, `progress`, `ddd`, `new`, `status` continue to read frontmatter in v1.
- Drift between frontmatter and index will be caught either by `decree lint` (warning) or `decree lint --strict` (error). The strict mode is what decree's own pre-commit hook enables.

### Open questions for follow-on SPECs

- What triggers automatic index rebuild? `decree lint` only, or also a file-watcher mode for IDE integration (`watchdog`-backed)?
- Does the v1 index store git-trailer commit data, or is that join computed at query time via `git log --format="%(trailers:key=Implements)"`? (Tradeoff: storage vs. live correctness on `decree refs`.)
- Schema versioning: do we ship migrations from day one (via `sqlite-utils` schema diffs), or rebuild-from-scratch only?
- Index location: `.decree/index.sqlite` (per-project, gitignored) vs. `$XDG_CACHE_HOME/decree/<repo-hash>.sqlite` (per-user). v1 picks one.
- **SPEC↔commit binding: trailers vs. git-notes vs. both.** `Implements: SPEC-NNN` in commit *trailers* requires modifying commit messages at creation time (via `decree commit` wrapper or `prepare-commit-msg` hook); they travel with the commit on rebase but require write access at commit time. `git notes` under `refs/notes/decree` can be attached or backfilled *after* the fact onto any commit (including historical ones, foreign branches, or third-party PRs) without rewriting history; they require explicit fetch/push of the notes ref. The principled answer is *both*: trailers are the primary forward-looking convention (visible in `git log` without configuration), notes are the back-fill/annotation channel for cases where the trailer wasn't written. The SPEC implementing R4 needs to decide whether v1 ships notes support or defers it to v2.
