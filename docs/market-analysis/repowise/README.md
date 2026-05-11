# Repowise: Market Analysis

Sources: https://www.repowise.dev/, https://docs.repowise.dev, blog posts at repowise.dev/blog (retrieved 2026-05-12).

---

## What It Is

Repowise is a codebase intelligence platform that indexes git repositories into a queryable knowledge graph and exposes that graph to AI agents via seven MCP tools. It is AGPL-3.0, self-hostable via pip, with a $15/month hosted Pro tier. It has 1,500+ GitHub stars and 561 repositories indexed as of the analysis date.

The product has three surfaces: a CLI for developers, an MCP server for Claude Code and Cursor, and a web UI for team collaboration. All three share the same underlying indexed data. This is architecturally meaningful — the intelligence layer is built once and consumed by many clients, which is the right layering choice.

---

## Core Thesis

Repowise's stated thesis is that AI agents fail at codebases not because their models are weak but because their context is wrong. From their blog: "Code is not prose. The meaning of a file lives in symbols, calls, imports, tests, history, and ownership." The corollary is that embeddings + vector store — the standard RAG approach for text — produces the wrong signal for code questions, because semantic similarity is not the same as structural relevance.

They back this with a concrete benchmark on pallets/flask: graph-aware MCP context versus naive grep loops produced 2,391 tokens per commit versus 64,039 (27x reduction), 89% fewer file reads, 49% fewer tool calls, 36% lower cost, 19% faster wall time, at equivalent answer quality. That is not a marginal gain.

The rejection of embeddings-only is not ideological. Repowise does use embeddings — but only as a ranking layer for broad recall in their wiki search (dual-indexed via SQLite FTS + LanceDB). For decision record retrieval specifically, they use no embeddings at all. The decision retrieval pipeline is keyword scoring with field-weighted BM25-style matching. Title gets 3.0x, decision/rationale 2.0x, context 1.5x, consequences/tags/files 1.0x, exact file path match +5.0, parent-directory match +3.0. This is a deliberate architectural choice grounded in a specific failure mode: embedding similarity for decisions retrieves documents that "talk about" a topic rather than documents that "govern" the affected code.

---

## Four-Signal Architecture

Repowise compounds understanding across four signal types, each addressing a distinct failure mode of the others:

**Structure** (Tree-sitter, 14 languages): Builds a directed dependency graph of file nodes and symbol nodes. Call resolution uses three confidence tiers — exact (1.0), heuristic (0.7-0.95), fallback (<0.7). MCP tools filter to ≥0.7 by default, trading recall for precision. Atop the graph: PageRank for global importance, betweenness centrality for critical paths, Leiden community detection for module clustering, strongly-connected-component detection for circular dependencies.

**Git history** (last 500 commits, configurable to 5,000): Hotspot detection flags files in the top 25th percentile on both churn and complexity. Co-change pairs identify "files that change together in the same commit without an import link between them" — hidden coupling that static analysis cannot see. Ownership tracks three dimensions: primary owner (historical), recent owner (active), contributor count. Bus factor (score of 1 = one person owns >80% of a file's history) surfaces organizational risk.

**Documentation** (LLM-authored wiki): Nine-level hierarchical generation from symbols up to repo. Three page types: file pages, module pages, symbol spotlights (for high-PageRank + high-call-frequency symbols). Pages carry `confidence_score` and `freshness_status`. Incremental: after each commit, only 3-10 affected pages regenerate, completing in under 30 seconds.

**Decisions**: Three capture paths — CLI interactive entry, inline `# DECISION:` source markers extracted at index time, and git archaeology (auto-proposed from significant commits, with a 10-second timeout). Staleness detection compares `last_commit_at` on governed files against `last_update_at` on their decision records. The `decision health` command surfaces ungoverned hotspots: high-churn files with no decision record attached.

The key insight is that each signal compensates for the others' failure modes. PageRank alone cannot distinguish dead code from stable boundary-enforcing files; git history resolves this. Structural analysis cannot find hidden coupling; co-change pairs find it. Documentation alone goes stale; freshness scoring surfaces the decay. None of the four signals is sufficient alone, and the combination is the product.

---

## The "Ungoverned Hotspots" Report

This is Repowise's operational moat. `repowise decision health` (and the `get_why` MCP tool in health mode) returns: summary counts, stale decisions, proposed records awaiting review, and the ungoverned hotspots list — high-churn files with no decision record.

This inverts the typical ADR workflow. Standard ADR practice is author-pull: someone writes a decision record when they feel like it. Repowise makes it data-push: the system tells you which files are changing fastest and have no recorded rationale. That is a qualitatively different threat model for documentation rot.

For decree, this is the most directly applicable pattern (see decree-implications.md for the concrete proposal).

---

## Decision-Linking Model

Decisions are graph nodes linked to file and symbol nodes, not just path strings. This matters because it enables the +5.0 / +3.0 exact/parent-directory scoring bonuses in retrieval — the score isn't just keyword match, it is keyword match conditioned on whether the queried file is actually listed as a governed target.

The `get_why` MCP tool has four modes:
- **Search**: Natural language query → 8 merged hits (keyword + semantic, deduped) + related wiki pages
- **Path**: File path → decisions affecting that file, origin story, alignment scores, git archaeology fallback
- **Health**: No parameters → ungoverned hotspots dashboard
- **Workspace**: `repo="all"` → cross-repository decision queries, capped at 15 results

Path detection is simple: queries containing `/` or ending with `.py` route to mode 2. Everything else goes to search. This is the right default — don't make the caller specify the mode explicitly when the query shape disambiguates it.

---

## Three Confidence Gates in `get_answer`

`get_answer` is their general RAG Q&A tool. It runs retrieval, enrichment, and synthesis in one call. Three gates protect against hallucination:

1. **Dominance ratio**: If the top retrieval score is not ≥1.2x the second-place score, synthesis is skipped and raw excerpts are returned instead. The model is not allowed to synthesize from a tie.

2. **Identifier-citation gate**: If the query names specific symbols (identifiers) but none appear in the top hits, confidence downgrades from high to medium. The retrieval did not find what the query actually asked about.

3. **Hedge-phrase detection**: If the LLM's own output contains phrases indicating uncertainty, confidence downgrades from high to low. The model cannot lie about its confidence in its own answer.

These gates are rule-based — no rerankers, no HyDE, no query rewriting, no chain-of-thought retrieval. Repowise explicitly avoids these. The rule-based approach is both simpler and more auditable.

---

## What They Do Not Do

Worth flagging explicitly:
- No rerankers
- No HyDE (Hypothetical Document Embeddings)
- No query rewriting
- No chain-of-thought retrieval
- No embeddings for decision retrieval (only for wiki semantic search)

Their re-ranking is rule-based: field weights, file-path bonuses, dominance ratio gating, identifier presence checks. This is a deliberate architectural position, not an omission.

---

## What Is Worth Stealing for decree

Four things stand out as directly applicable, in order of leverage:

1. **Ungoverned hotspots**: The `governs:` frontmatter field + `decree health` command that intersects churn data with governed-file coverage. This is the single highest-value signal decree lacks.

2. **`--json` output across all commands**: Repowise's MCP integration only works because every tool returns structured data. decree's consumers (Claude Code hooks, CI scripts, shell pipelines) currently reimplement frontmatter parsing in grep/awk. This is a low-cost, high-leverage fix.

3. **MCP server**: Seven task-shaped tools beat entity CRUD. decree's state — status transitions, progress percentages, ungoverned hotspots, cross-reference chains — is invisible to Claude Code today. An MCP wrapper over the existing Python commands resolves this without rewriting anything.

4. **Coherence gate**: A SPEC marked `implemented` with <80% checkboxes checked is incoherent. `decree lint` does not catch this. Repowise's confidence gates are the right model: compute a ratio (checkboxes_done / checkboxes_total), define a threshold, fail lint when the claim exceeds the evidence.

Full analysis of each item with LOC estimates and prerequisites is in decree-implications.md.

---

## What Is Shallow Overlap

Repowise has decision records; decree has decision records. This overlap is shallow. Their decision record is a linked graph node with file/symbol targets, staleness tracking, and three automated capture paths. decree's ADR is a validated markdown file with status transitions and cross-reference linting. The concepts share a name but serve different architectural roles. Decree does not need to become Repowise's decision layer — it needs to borrow the ungoverned-hotspots reporting pattern and stop there.

---

## Business / Threat Assessment

Repowise is AGPL-3.0 and self-hostable, which means it is a direct competitor to any tool in the "code intelligence for AI agents" space, but it is not a direct competitor to decree. decree is a document lifecycle manager that composes into CI hooks; Repowise is a codebase graph intelligence platform. They are orthogonal. The natural integration is: decree manages the document lifecycle, Repowise surfaces which code lacks decree coverage.

The threat model for decree is not Repowise eating its market. The threat is decree remaining invisible to AI agents while tools like Repowise become the default context layer. The MCP gap is existential at the relevant time horizon.
