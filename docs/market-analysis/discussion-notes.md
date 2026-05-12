# decree market analysis — discussion notes

Generated 2026-05-12. Sources: repowise.dev, docs.repowise.dev, entire.io.
Full analysis: `docs/market-analysis/repowise/` and `docs/market-analysis/entire-io/`.

---

## decree today — verified gaps

Source read: `/Users/doruk/Desktop/SIDE_HUSTLE/decree/src/decree/`, six command modules, ~1200 LOC Python.

Confirmed gaps (not already fixed):
- No `governs:` frontmatter field — SPECs can name file paths in prose but nothing validates they exist or builds a reverse index
- No `--json` flag on any command — all output is ANSI human text; consumers (suppression-expiry, CI) re-implement frontmatter parsing in regex
- No `decree why <path>` — cannot ask "what SPEC governs this file?"
- No coherence enforcement — `status: implemented` with 5% checkboxes checked passes lint
- No MCP server — decree state is invisible to Claude Code / Cursor
- No `decree refs <id>` — cannot ask "what references this SPEC?"
- No history/staleness layer — no git churn, co-change, or staleness signal

---

## Repowise — key findings

### Their core thesis (the load-bearing piece)

"RAG for code is not embeddings + a vector store." Repowise uses a four-signal architecture: code structure (AST/imports), git history (churn, co-change, authorship), docs (wiki, comments), and decisions (ADRs, RFCs). Embeddings are used for wiki search only. Decision-record retrieval uses zero embeddings by deliberate choice.

### Why no embeddings for decisions

Embedding similarity retrieves documents that *talk about* a topic. Decision retrieval needs documents that *govern* a file. These are different queries. An embedding search for "auth" retrieves every document mentioning authentication. A governed-file query retrieves only documents whose `affected_files` list includes the queried path. The structural link is load-bearing.

### Their decision retrieval pipeline (directly applicable to decree)

SQLite + weighted keyword scoring:
- title: 3×
- rationale: 2×
- context: 1.5×
- exact file-path match (via `affected_files`): +5.0 bonus
- parent-directory match: +3.0 bonus

The path bonuses are only earned if the structural `affected_files` link exists — text match alone cannot earn them. This makes explicit governs-links the mechanism that separates "documents about this topic" from "documents governing this file."

### Three confidence gates in `get_answer`

1. **Dominance ratio**: top score must be ≥ 1.2× second score. If not, return raw candidates — do not synthesize. They would rather return competing ADRs than blend them into a hallucinated composite.
2. **Identifier-citation gate**: query symbols must appear in top hits — prevents off-topic retrieval.
3. **Hedge-phrase detection**: if top document contains hedging language, downgrade confidence.

`get_why` path mode: query contains a file path → retrieve by governed-file match first, fall back to text search.

### "Ungoverned hotspots" — their highest-value signal

Intersection of high-churn files with absence of decision-record coverage. Standard ADR practice is author-pull (people write records when they feel like it). Health reporting is data-push: the system tells you which files are changing fastest with no recorded rationale. This inverts the workflow from passive to active.

### What they explicitly do not do

No rerankers, no HyDE, no query rewriting, no chain-of-thought retrieval. Re-ranking is rule-based. At ADR-corpus scale (~dozens to low hundreds of documents), rule-based scoring is more predictable and auditable than learned models.

### Business context

AGPL-3.0, 7 MCP tools, GitHub integration. Their benchmark: 27× token reduction, 89% fewer file reads vs. naive full-context approaches. The MCP tooling is task-shaped (verbs) not entity CRUD (nouns): `get_why`, `get_answer`, `search_codebase` — not `read_decision`, `list_decisions`.

---

## entire.io — key findings

### The central claim

The gap between intent and code is the foundational engineering artifact, and every developer tool before theirs left it unaddressed. Thomas Dohmke (former GitHub CEO, $60M seed): "the entire software ecosystem is being bottlenecked by a manual system of production that was never designed for the era of AI."

### The failure mode they name

From their intent-review post: Claude Code confidently rebuilt an abandoned Redis queue because it saw the code files but not the team's decision to discontinue Redis due to replication lag. That decision "lived in a Slack thread, a couple of PR comments, and the heads of three engineers — places code search cannot reach." The agent did not write bad code. It wrote reasonable code from incomplete context. That is an infrastructure failure, not a model failure.

### What they treat as load-bearing

**Traceability must live in the same version-control system as code.** Their CLI stores transcripts, prompts, attribution, summaries as git objects. Checkpoint metadata travels with the repository, survives rebases (linked by commit trailer not commit hash), available to anyone who clones the repo. Anything stored elsewhere drifts — not a discipline problem, the natural state of documentation in a separate system.

**Intent review is a different activity than code review and must happen before it.** "Code review: is this change well-implemented? Intent review: is this change well-conceived in light of what the team already decided?" A diff cannot answer the second question.

### Their worldview on engineering teams

Humans have moved from primary producers to orchestrators and governors. "The role of the developer is shifting from writing code to conducting an orchestra of agents." When an agent generates 90% of a feature, the relevant signal for the next person is not the diff — it is the prompt, the alternatives discarded, the session transcript.

### Where this differs from decree's frame

decree manages the document lifecycle — creation, status transitions, cross-reference integrity, checkbox progress. It enforces that documents are internally consistent and correctly linked to each other.

The gap: **decree manages the documents but not the provenance of decisions recorded in those documents.** An ADR in decree is a file with validated frontmatter and a status. What it cannot answer: what alternatives were rejected? What commit introduced the behavior it governs? What changed in the codebase that made this ADR stale before its status was updated?

Three pressure points:
1. Decisions must be queryable, not just readable — structured pre-change queries, not prose parsing
2. Co-location in git is the only reliable anchor — decree stores docs in git (correct), but the link between SPEC and implementing commits is narrative (prose body), not structural (git trailer)
3. Traceability is infrastructure, not documentation — decree enforces well-formedness; that is necessary but not sufficient

### The single most transferable principle

"The 'why' has the same lifecycle as the code it explains, and must be stored in the same provenance graph." Decree stores documents in the same repo as code — right location, wrong coupling. The link between document status and code history should be something git can traverse, not something a human reads in a docs folder.

---

## Proposed action steps — ordered by execution priority

| # | Feature | LOC | Prerequisite | Rationale |
|---|---------|-----|--------------|-----------|
| 1 | `--json` flag across all commands | ~80 | none | Lowest risk, unblocks everything downstream |
| 2 | Coherence gate: status vs. checkboxes | ~40 | none | Closes most common LLM-authored SPEC failure; reuses existing `_count_checkboxes()` |
| 3 | `governs:` field + `decree why <path>` | ~150 | none | Enables governed-file retrieval; lint validates paths exist |
| 4 | MCP server (5 task-shaped tools) | ~200 | #1 required | Makes decree visible to Claude Code/Cursor; thin subprocess wrapper |
| 5 | `decree health` ungoverned hotspots | ~120 | #3 required | Data-push inversion of author-pull ADR practice |
| 6 | `decree refs <id>` reverse index | ~60 | #2 for full utility | Blast-radius command; reference data already in frontmatter |

Total: ~650 LOC against existing ~1,200-line codebase.

Execution order if doing in one week: **1 → 2 → 3 → 4 → 5 → 6**

### Items the Repowise analysis suggests skipping (for now)

- Embeddings / vector store for any decree query — rule-based scoring is more predictable at ADR-corpus scale
- Rerankers, HyDE, query rewriting — not needed at this corpus size
- Dependency graph / git archaeology (Repowise features) — high complexity, low decree leverage

### Items the entire.io analysis suggests exploring after the above

- **Staleness lint**: SPEC `implemented` with no commit trailer linking to it → lint error. ADR `accepted` with no referencing SPEC after N days → lint warning.
- **`decree index --json` as agent-facing artifact**: not a human summary but a structured, stable-schema document an agent queries before modifying a file.
- **Git trailers on implementation commits** (`Implements: SPEC-126`): structural link that survives rebase, surfaceable via `git log --grep`, validatable in pre-commit. Prose body references drift; git trailers don't.

---

## Open questions for discussion

1. **Execution sequence**: does `--json` first still make sense, or does the entire.io framing suggest the git-trailer / staleness work should move up?

2. **`governs:` scope**: paths only, or also symbol names (function/class level)? Repowise does graph-node level (file + symbol). Is that worth the complexity increase for decree?

3. **MCP server shape**: FastMCP Python wrapper shelling out to `decree --json`, or native TypeScript MCP server in the consuming project? The latter avoids the Python subprocess dependency for JS-first consumers.

4. **Staleness threshold**: what makes an ADR stale? Age since last git-touching-governed-file? Age since status was set? Both?

5. **entire.io's git-trailer approach**: is `Implements: SPEC-NNN` in commit messages enough, or does this need a `decree commit` command that auto-adds the trailer?
