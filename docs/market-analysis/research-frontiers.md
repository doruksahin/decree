# Research frontiers for decree — state-of-the-art directions

Captured 2026-05-12. Companion to `discussion-notes.md` and the Repowise / entire.io analyses.

This document is **a menu, not a plan**. PRD-01KT22NMRS4QGHSFDBZ858PP1T establishes the baseline (SQLite index + keyword-scored retrieval + governs field + MCP) — what Repowise already shipped. This document captures the *research frontiers* beyond that baseline: directions that would make decree a state-of-the-art educational project on decision-provenance graphs rather than "another ADR tool with SQLite." Each subsection is self-contained and can be elevated to a SPEC under PRD-01KT22NMRS4QGHSFDBZ858PP1T, a SPEC under a future PRD-01KT22NMRSXYT95XE808VD8EV4 ("State-of-the-Art Decision Reasoning"), or its own PRD if the scope warrants it.

Knowledge cutoff: most cited prior art is current as of early 2026. Where the frontier moves fast (retrieval, GraphRAG), assume the literature has advanced since this was written; verify before committing to a specific technique.

---

## 0. Why these are frontiers and not feature requests

A feature request is "build this." A research frontier is "we don't yet know whether this works, or how well, or where the failure modes are." All five frontiers below have at least one open question that needs experimentation to answer. If decree picks any of them, it should also commit to an evaluation methodology — at minimum a labeled query set, a baseline (PRD-01KT22NMRS4QGHSFDBZ858PP1T v1), and a metric. Without that, "state of the art" collapses into "we built more stuff."

The Repowise baseline is load-bearing here. Their thesis — "rule-based scoring beats embeddings at ADR-corpus scale" — is a *claim*, not a proven fact at every corpus size or query type. Decree's educational value is partly in re-testing such claims on its own corpus, with its own queries, transparently.

---

## 1. Baseline: PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 (what we get for free before any of this)

To understand what each frontier is enhancing or replacing, the v1 baseline is:

- SQLite index with tables for `decisions`, `governs`, `commits`, `refs`.
- Weighted keyword scoring (Repowise-style: title 3×, rationale 2×, context 1.5×, path-match bonus 5×).
- File-level `governs:` frontmatter field.
- Git trailers (`Implements: SPEC-<ULID>`) as the structural SPEC↔commit link.
- MCP server with five task-shaped tools (`why`, `refs`, `stale`, `intent_review`, `health`).
- Three confidence gates from Repowise (dominance ratio, identifier-citation, hedge-phrase detection).
- `decree why <path>` falls back from governed-file match to text search.

This is competent. It is not state-of-the-art. The frontiers below are how it becomes that.

---

## Frontier A — Retrieval-side research

**Thesis.** Repowise rejected embeddings for ADR-corpus retrieval. They were probably right at their scale, but the claim deserves empirical testing on different corpus shapes (cross-repo, large monorepo, mixed PRD/ADR/SPEC) and different query types (file-path lookups vs. concept queries vs. multi-hop "why does our system work this way" questions). An educational project can run the ablation Repowise didn't publish.

### A.1 Hybrid retrieval (lexical + dense + structural)

Combine three signals into one ranker:

- **Lexical**: BM25 / SQLite FTS5 — what Repowise has today.
- **Dense**: embedding similarity. Use `sqlite-vec` (Alex Garcia, 2024) or `sqlite-vss` for in-process vector search. Models to consider: `bge-small-en-v1.5`, `nomic-embed-text-v1.5`, or a code-aware embedding like `voyage-code-3` if budget permits.
- **Structural**: graph-neighbor score from the governs/refs graph. Decisions one hop from the target path's governing decision get a boost.

Combining the three is the open question. Options: linear weights tuned on a labeled set, Reciprocal Rank Fusion (RRF, the de facto baseline for hybrid retrieval), or a small learned ranker (e.g., LambdaRank with the three signals as features). RRF is the right v1 of A.1 — single hyperparameter (k=60 is standard), no training data needed, well-understood failure modes.

**Open question**: at what corpus size does the embedding signal start adding value over BM25 alone? Repowise says "not at theirs." Run the experiment on a labeled query set for decree's own corpus (which is currently 6 documents — small enough that the answer is plausibly "never," but the methodology stays valid as the corpus grows).

**Prior art**: BEIR benchmark (Thakur et al., 2021); ColBERTv2 (Santhanam et al., 2022); BM25 + dense hybrid in production (Vespa, Qdrant docs); the IR community's general finding that BM25 is hard to beat below ~10k documents without query-side training data.

### A.2 GraphRAG-style community summarization

Microsoft's GraphRAG (Edge et al., 2024) clusters entities in a knowledge graph into "communities," generates LLM summaries per community, and uses those summaries for high-level questions ("what's our overall approach to caching?") that don't have a single-document answer.

Decree's natural communities: decisions that govern overlapping file sets, decisions that reference each other, decisions in the same architectural area (auth, persistence, IPC, …). Algorithm: Leiden or Louvain community detection on the governs+refs graph, then per-community LLM-summarized "what does this cluster of decisions say."

**Open question**: are decree corpora ever large enough for GraphRAG to add value? GraphRAG's win condition is "high-level synthesis questions over hundreds of entities." A decree corpus might top out at low hundreds of decisions in a mature project — borderline. The educational answer: build it, measure, report the threshold.

**Prior art**: Edge et al., "From Local to Global: A Graph RAG Approach to Query-Focused Summarization," 2024. Microsoft's open-source graphrag package. `networkx.algorithms.community` for the clustering side.

### A.3 LLM re-ranking with surfaced reasoning

Top-K from the cheap retriever → LLM judge re-ranks → final ordering. The interesting twist: surface the judge's reasoning *to the user*, not just the ranking. "We surfaced ADR-<ULID> first because your changed files match its governed paths and it explicitly addresses the auth-token flow in your diff."

This makes the system *legible*: a developer can see why a decision was retrieved and override if the reasoning is wrong. Repowise has hedge-phrase detection but no surfaced reasoning.

**Open question**: is the latency cost (one LLM call per query, ~500ms-2s) acceptable for the MCP / IDE-hover use case? Probably not for hover, fine for `decree why`. Two-tier surface might be required.

**Prior art**: RankGPT (Sun et al., 2023); RankVicuna; the broader "LLM as ranker" literature. For surfaced reasoning: chain-of-thought literature, Anthropic's research on faithful reasoning.

### A.4 Active learning from rejections

When a developer dismisses a retrieved decision (closes the panel, doesn't reference it in commit, marks "not relevant"), record negative signal. Over time, train a small ranker on the labeled (query, decision, relevant?) triples.

This is the only frontier item that gets *better* with use, not worse. It's also the one that requires UI work (capture the dismissal) and concept-drift handling (decisions that became irrelevant for old reasons may become relevant again).

**Open question**: how long until a single user generates enough signal to outperform the unsupervised baseline? Probably months in real use. For an educational project, can be simulated with LLM-generated labels.

**Prior art**: learning-to-rank literature (RankNet, LambdaRank, LambdaMART). Online learning for IR (Counterfactual Learning to Rank, Joachims et al.). Implicit feedback IR survey (Joachims).

### A.5 Evaluation harness

This is the meta-frontier. None of A.1–A.4 are credible without a way to measure them. Build:

- A **labeled query set** for decree's corpus: 50-200 queries with ground-truth relevant decisions per query. Either hand-labeled (slow, high quality) or LLM-bootstrapped + human-spot-checked.
- A **baseline evaluator** that runs PRD-01KT22NMRS4QGHSFDBZ858PP1T v1's keyword retrieval over the query set and reports Recall@K, MRR, NDCG@10.
- A **metric harness** that runs any new retrieval method against the same queries and reports delta vs. baseline, with confidence intervals.
- A **report generator** (`decree retrieval-eval`) that produces a markdown report for each ablation.

This is the *single highest-leverage* item in this whole document. Without it, every other A-frontier is unfalsifiable.

**Prior art**: BEIR (Thakur et al.); MTEB (Muennighoff et al.); the IR evaluation literature broadly; the academic norm of ablation tables.

---

## Frontier B — Graph-side research

**Thesis.** The provenance graph isn't just retrieval-substrate — it has structure and time-evolution that contain information not available to retrieval alone. Treating it as a queryable database, not a pre-computed index, unlocks questions retrieval can't answer.

### B.1 Temporal queries

"What governed `src/auth.ts` at commit `abc123`?" requires reconstructing the decision graph as it existed at that commit's timestamp. Decisions have status timelines (draft → review → approved → implemented → deprecated). Files have lifecycles (created, modified, renamed, deleted). The graph is time-indexed.

Implementation: bitemporal modeling — store both "valid time" (when the decision was authoritative in the real world) and "transaction time" (when it was recorded in the index). Datomic's data model is the reference implementation.

**Open question**: what's the query language? SQL with date predicates is one option; a small DSL is another. The educational value is in modeling the bitemporal substrate correctly — most ADR tools have neither dimension.

**Use cases**: blame-like analysis ("which decision was relevant when this bug was introduced?"); regression detection ("this file was governed by ADR-X six months ago, ADR-X is now superseded, has the code been updated to match the superseding decision?").

**Prior art**: Datomic (Rich Hickey); Snodgrass's bitemporal database literature; SQL:2011's temporal tables; the architectural-knowledge-evolution literature in software engineering.

### B.2 Causal vs. correlational governance

Distinguish decisions that *caused* a piece of code (referenced in the implementing commit's trailer or PR description) from decisions that *touch* it (mentioned in the file path the decision governs, but not the proximate cause of the code's existence).

Causal links are higher signal for "why is this code the way it is?". Correlational links are still useful for "what decisions should I be aware of when modifying this?".

**Open question**: how is causality assigned? Trailer-mediated commits are easy (`Implements: SPEC-<ULID>` is a causal link). For files predating the SPEC, you need archaeology — `git log -p` + LLM judge to ask "did this commit implement that decision?" This is genuinely hard and could be its own SPEC.

**Use cases**: `decree why-causal <path>` (only causal decisions); `decree why-related <path>` (causal + correlational, current default behavior).

**Prior art**: software archaeology literature; the SZZ algorithm for bug-introducing-commit identification has a related shape (causal link from commit to bug). Counterfactual reasoning in ML.

### B.3 Decision lineage / supersedes lattice

Beyond simple `supersedes`: build a directed acyclic graph (DAG) of decision evolution. "ADR-<ULID> was deprecated by ADR-<ULID> which was partially superseded by ADR-<ULID> for the read path only." Query the lattice: "what's the *live* decision lineage for caching?" returns the current frontier (decisions not yet superseded) plus the relevant deprecations.

Edge types: `supersedes`, `partially-supersedes`, `extends`, `refines`, `deprecates`, `consolidates`. Each edge carries metadata (which aspect was superseded, scope of the supersedence).

**Open question**: is the edge-type taxonomy small enough to be useful? Too many edge types → no one will annotate correctly. Too few → can't express partial supersedence. The MADR spec has a small vocabulary worth borrowing.

**Use cases**: `decree lineage <id>` traces ancestry; `decree current <topic>` returns the live decisions for a topic, with deprecated decisions reachable for context.

**Prior art**: MADR's supersedes convention; semantic versioning's notion of breaking vs. compatible changes; the academic-paper citation graph (cites, retracts, corrects).

### B.4 Conflict detection between decisions

Surface when two decisions disagree about the same file or symbol. Two SPECs both governing `src/auth.ts` with one saying "use bcrypt" and another saying "use argon2" is a conflict. Today nothing detects this.

Detection: structural (both `governs:` lists include the path) + semantic (LLM judges whether the decisions actually disagree, vs. addressing different aspects of the same file). The structural part is cheap; the semantic part is expensive but offline-precomputable.

**Open question**: false positives are the killer. If `decree conflicts` raises 30 alarms a day, the developer ignores all of them. The detection has to be precision-biased — high precision, low recall — or it's worse than nothing.

**Use cases**: `decree conflicts` health command; pre-merge gate ("this PR's changes are governed by ADR-X and SPEC-Y which conflict — resolve before merging"); `decree resolve` workflow that records which decision wins for which scope.

**Prior art**: software-architecture conformance checking; the "architectural drift" literature; static-analysis tools that detect contradictory specifications.

### B.5 Cross-repo provenance

Decisions in repo A govern code in repo B. Microservices, monorepos with submodules, multi-language stacks where the architecture decisions live in a docs repo and the code lives in service repos.

This requires: a federation protocol (how does repo B's decree know about repo A's decisions?), an authority model (who can govern what?), and a cache invalidation story (when repo A's decision changes, repo B's index has to update).

**Open question**: is this worth doing at all, or is "copy the relevant ADRs into your repo" good enough? Federation has a real cost. The educational answer might be "model it as a thought experiment, don't ship it."

**Use cases**: enterprise multi-repo settings; open-source ecosystems where decisions in a spec repo (e.g., RFC repos) govern many implementations.

**Prior art**: federated package managers; the W3C / IETF RFC ecosystem; Backstage's Software Catalog (multi-repo entity model).

---

## Frontier C — Authoring-side research

**Thesis.** Repowise and most prior art treat decisions as *given input* and focus on retrieval/health. The frontier the entire.io analysis points at is *authoring*: LLMs helping create decisions in the first place, refining them, surfacing missed alternatives, drafting them from observable code evolution. This is where decree could be uniquely valuable for LLM-authored codebases.

### C.1 Auto-propose ADRs from ungoverned hotspots

When `decree health` flags a high-churn file with no governing decision (the Repowise "ungoverned hotspot" signal), automatically draft a candidate ADR for human review. The draft is grounded in: the file's commit history, the LLM's reading of the commits ("this file has been modified 40 times in the last quarter, primarily for caching-related changes"), and a templated MADR structure.

The human keeps the LLM's draft, edits it, or discards it. Either way, the hotspot becomes either governed or explicitly acknowledged as out-of-scope-for-ADRs.

**Open question**: how often is the draft useful? If <30%, the workflow generates noise. The educational answer: measure on decree's own corpus + a synthetic corpus.

**Prior art**: GitHub Copilot Pull Request descriptions; commit-message-generation literature (e.g., CommitGen); the "explain this code" LLM use case generalized to "explain this code's history."

### C.2 Pre-PR intent review

Run intent-review during the agent's *planning* phase, before any code is written. The agent says "I'm about to implement X"; decree returns "decisions Y and Z govern the files you're about to touch; here are conflicts to be aware of." The agent then either proceeds, asks the human, or adjusts the plan.

This is the entire.io "intent review > code review" pitch, but earlier in the loop — at the intent step, not after the diff.

**Open question**: what's the MCP-tool shape for this? `decree.intent_check(planned_files: list[str], plan_summary: str)` returns governance + conflict warnings. The agent integrates this into its planning prompt. Concretely useful, narrow.

**Use cases**: any LLM agent working on a decree-enabled repo; pre-commit hook variant that checks intent against the staged diff before allowing the commit.

**Prior art**: entire.io's CLI (the only commercial product that does intent review at all, as of early 2026); pre-commit hook literature; AI-assisted-planning research in the agent space (broadly).

### C.3 Decision refinement loop

LLM reads a draft ADR, surfaces missed alternatives ("you compared Postgres and SQLite but not DuckDB"), asks adversarial questions ("what happens at 10× current scale?"), suggests rejected-options to document ("you should record why you rejected Redis"). The author iterates with the LLM until the decision is dense.

The MADR template already has "Considered Options" — this turns that section into an LLM-facilitated dialogue rather than a stub the author fills in alone.

**Open question**: does this actually produce better decisions, or just more verbose ones? Verbosity is not a virtue. Evaluate by asking three independent reviewers to compare LLM-refined ADRs vs. solo-authored ADRs on a quality rubric.

**Prior art**: peer-review automation literature; the "devil's advocate" prompting pattern; structured argumentation tools (Toulmin model in software-architecture documentation).

### C.4 Multi-repo coherence

When an ADR in repo A contradicts an ADR in repo B (federated decree network), flag it. This is B.5's flip side — cross-repo provenance from the *authoring* angle. Same caveats apply: federation is expensive, may not be worth building.

---

## Frontier D — Surface-side research

**Thesis.** A decision-provenance graph is only as good as its access surface. CLI is fine for humans who remember to ask; MCP is fine for agents that opt in. The frontier is making decisions *unmissable* in the tools developers already use.

### D.1 LSP server

Decree as a Language Server Protocol server. Any LSP-aware editor (VS Code, Neovim, Helix, Zed, JetBrains IDEs) gets hover tooltips on file paths, function names, and symbols: "this is governed by ADR-<ULID>, SPEC-01KT22NMRYJ4482K92AX9GJTMA (stale 60 days)." `textDocument/hover`, `textDocument/definition` jumping to the governing decision, `textDocument/codeAction` to "draft an ADR for this symbol."

**Open question**: what's the minimal LSP surface? `hover` + `definition` + `codeLens` covers 80% of value. `completion` for symbol-level governance authoring is interesting but second-order.

**Prior art**: pylsp; rust-analyzer (the LSP reference implementation); the language-server protocol spec itself.

### D.2 Reactive subscriptions

Agents subscribe to "files I'm about to modify"; decree pushes governance updates before the edit, not after. WebSocket or long-poll transport over the MCP server.

**Open question**: is push actually better than pull? An agent that knows to ask `decree.why(path)` before each edit is just as informed. Push reduces latency and prevents the agent from forgetting to ask.

**Prior art**: LSP's pull-based diagnostics vs. server-pushed; database trigger systems; file-watcher patterns generally.

### D.3 PR review bot

GitHub bot that runs intent-review on every PR, comments with governance impact ("this PR touches files governed by ADR-<ULID> and SPEC-01KT22NMRYJ4482K92AX9GJTMA; SPEC-01KT22NMRYJ4482K92AX9GJTMA is stale; here are unchecked acceptance criteria potentially affected by these changes").

**Open question**: signal-to-noise. Same as B.4 — a high-volume false-positive bot gets muted. Calibrate to comment only when confident.

**Prior art**: Dependabot, Renovate, Stale; the broader bot-on-GitHub-PR ecosystem.

### D.4 Decision explorer (Datasette-style web UI)

`decree serve` launches a Datasette-style read-only web UI over the SQLite index. Full-text search, graph visualization (governance edges, refs graph, supersedes lattice), time-travel slider for B.1, faceted filtering by status / type / age.

This is the "show this to a non-developer" surface. PMs, engineering managers, security reviewers all benefit from being able to browse the decision corpus without git or markdown literacy.

**Open question**: does the project have a target user beyond developers? If yes, this is high-value. If no, defer.

**Prior art**: Datasette (Simon Willison) — literally the right tool, MIT-licensed, designed for exactly this. Decree could ship a Datasette plugin (`datasette-decree`) rather than build a custom web UI. **This is the highest library-leverage win in Frontier D.**

### D.5 Live dashboard

Real-time staleness, churn, ungoverned hotspots, conflicts. Refreshed on git hooks or file-watcher events. Could be a tab in D.4's web UI or a separate `decree dashboard` command that opens a long-lived terminal UI (Textual / Rich).

**Open question**: who watches dashboards? Usually no one, unless they're triggered by alerts. Worth designing the alert layer alongside.

**Prior art**: CodeScene's dashboard (the visual reference for architectural health); Grafana / Prometheus patterns for alert-driven dashboards.

---

## Frontier E — Trust and abstention

**Thesis.** Most retrieval systems over-retrieve confidently. Returning irrelevant results is worse than returning none, because it trains the user to ignore the system. The frontier is *knowing when not to answer*, and surfacing uncertainty honestly. This is under-researched in the ADR-retrieval space specifically and an excellent niche for an educational project to claim.

### E.1 Confidence gates beyond Repowise's three

Repowise has three gates: dominance ratio (top score must be ≥1.2× second), identifier-citation (query symbols must appear in top hits), hedge-phrase detection. Additional gates to consider:

- **Status gate** — if all top hits are deprecated/superseded, abstain or warn explicitly.
- **Recency gate** — if the only matching decisions are >18 months old without any touching commits, flag as stale-but-only-option.
- **Coverage gate** — if the matched governing scope is tiny (one path out of dozens in the diff), surface "low coverage, may not be relevant."
- **Authorship gate** — if the matching decision was authored by someone no longer active in the codebase (no commits in 12+ months), surface for sanity-check.

**Open question**: how do gates compose? Multiplicatively? Disjunctively? Calibrate against a labeled set.

### E.2 Calibrated abstention

When no decision strongly applies, return "no governance found" rather than the best-of-bad-options. This requires a calibrated threshold below which the system says "I don't know" — set by validation on a labeled set where the ground-truth answer is "no relevant decision."

**Open question**: what's the right loss for calibration? Selective prediction literature has standard answers (coverage-risk curves, conformal prediction). Apply them.

**Prior art**: selective prediction (El-Yaniv & Wiener, 2010); conformal prediction (Vovk et al.); the broader uncertainty-quantification literature; "I don't know" responses in QA systems.

### E.3 Decision freshness decay

Old decisions weight down in retrieval with an explicit decay curve. The decay should be configurable: a project might want exponential decay with τ = 6 months, or sigmoid decay after 12 months, or no decay for `architectural` decisions and steep decay for `tactical` ones.

**Open question**: does freshness decay actually help retrieval quality, or just rotate which decisions get surfaced without improving precision? Test against a labeled set.

**Prior art**: time-decayed scoring in news IR (Google's "Freshness" patent, broadly); the staleness literature in software-architecture conformance.

### E.4 Adversarial probing

Test the retrieval with intentionally misleading queries — queries designed to lure the system into surfacing irrelevant decisions. Measure how often the system retrieves something irrelevant vs. abstaining. This is the "red team" methodology applied to ADR retrieval.

**Open question**: how are adversarial queries generated? LLM-generated against the corpus, with the goal "fool the retriever." The educational value is in cataloging the failure modes systematically.

**Prior art**: adversarial NLP (TextFooler, BERT-Attack); adversarial IR (poisoning attacks on retrieval); the broader robustness literature.

---

## Cross-cutting themes

Several themes show up across multiple frontiers and deserve their own treatment if pursued seriously.

### Evaluation rigor

A.5 names the evaluation harness, but every frontier needs one. The harness from A applies (with extensions) to B, C, D, E. Investing in evaluation infrastructure once pays off across all five frontiers. Treat this as table-stakes if "state-of-the-art" is the goal — without it, claims are not falsifiable, and the project is not research-grade.

### LLM-as-judge as a dependency

A.3, C.1, C.3 all use an LLM as a component (re-ranker, draft author, refinement partner). This creates: a cost dependency (each query costs money), a determinism gap (LLMs drift), and an evaluation challenge (LLM-judged outputs are correlated with the LLM doing the judging — well-documented bias). Mitigate with: multiple independent judges, deterministic prompts, and at least one human-labeled gold set for calibration.

### Library leverage stays load-bearing

PRD-01KT22NMRS4QGHSFDBZ858PP1T's Dependencies subsection (sqlite-utils, pydriller, mistletoe, networkx, mcp[cli]) covers v1. Each frontier adds:

| Frontier | Likely additional dependencies |
|---|---|
| A | `sqlite-vec` or `sqlite-vss`; sentence-transformers or an API embedding client; possibly `rank_bm25` if FTS5 is insufficient |
| B | `python-dateutil` for temporal arithmetic; possibly `nx-temporal` (research-grade) |
| C | An LLM client (Anthropic/OpenAI SDK); prompt-template library (Jinja2 is fine) |
| D | `datasette` + custom plugin; `pygls` for the LSP server; `textual` for terminal dashboard |
| E | `crepes` or similar for conformal prediction; possibly scikit-learn for calibration models |

All are MIT/Apache/BSD as of writing. The "don't reinvent the wheel" discipline from PRD-01KT22NMRS4QGHSFDBZ858PP1T carries forward.

---

## How to pick

Three honest framings the project can adopt:

### Depth-first: one frontier, done well

Pick A (with A.5 as the spine) and treat the project as a research contribution on retrieval methods for decision documents. Build the eval harness; ablate; write up. This is the path to a publishable artifact.

### Breadth-first: one item per frontier

Pick one item from each of A–E and ship a v2 that touches all five surfaces. This is the showcase path — the demo is broad, every visitor can find something they care about.

### Theme-first: pick a thread that cuts across

E.g., "trust and abstention" pulls E.1–E.4 plus A.5 (you need eval to measure trust) plus A.3 (LLM re-rank with surfaced reasoning is a trust surface) plus D.4 (a UI that shows confidence). This is the path to a coherent narrative.

### Sequencing suggestions independent of framing

Whatever else gets picked, A.5 (evaluation harness) and D.4 (Datasette plugin) should come early. A.5 is a force multiplier for every subsequent claim. D.4 is the lowest-effort high-leverage surface — Datasette does the work, decree contributes a thin plugin, the corpus becomes browsable to non-developers immediately.

B.1 (temporal queries) and E.2 (calibrated abstention) are the items I'd flag as **highest novelty** — least covered by prior art in the ADR-retrieval space specifically. If "state-of-the-art" means "contributes something new," they're the strongest candidates.

C.1 (auto-propose ADRs) and C.2 (pre-PR intent review) are the items I'd flag as **highest practical demo impact** — what people see when shown decree. If "state-of-the-art" means "this looks impressive and is novel-feeling," they win.

---

## Open meta-questions

Before picking, three questions worth answering explicitly:

1. **What's the corpus we're optimizing for?** Decree's own dogfood corpus (currently 6 documents) is too small for most retrieval research. A representative corpus — either synthesized or borrowed from a real ADR-heavy open-source project (the C4 model project itself has a public ADR set; CNCF projects often do) — is a prerequisite for credible work in Frontier A. Pick the target corpus now or all later experiments are unfalsifiable.

2. **What's the unit of governance?** File-level (PRD-01KT22NMRS4QGHSFDBZ858PP1T v1), symbol-level (PRD-01KT22NMRS4QGHSFDBZ858PP1T v2 backlog), or function-call-graph level (research-grade)? The choice cascades into every frontier — A's retrieval, B's graph structure, C's auto-proposal granularity, D's LSP hover scope, E's abstention thresholds.

3. **Is decree a tool or a research artifact?** If a tool: usability, stability, docs matter more than novelty. If a research artifact: novelty, evaluation rigor, writeup matter more than ergonomics. The project can be both eventually, but the *current* phase is one or the other. Picking determines which trade-offs to make at every decision point below.

---

## References (selected prior art cited above)

- **Retrieval / IR**
  - Thakur et al., *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models*, 2021.
  - Santhanam et al., *ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction*, 2022.
  - Gao et al., *Precise Zero-Shot Dense Retrieval without Relevance Labels* (HyDE), 2022.
  - Sun et al., *Is ChatGPT Good at Search? Investigating Large Language Models as Re-Ranking Agents* (RankGPT), 2023.
  - Joachims, *Optimizing Search Engines using Clickthrough Data* (foundational implicit-feedback IR), 2002.
- **Graph-based retrieval**
  - Edge et al., *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, 2024.
  - Microsoft GraphRAG: https://github.com/microsoft/graphrag
- **Temporal databases**
  - Snodgrass, *The TSQL2 Temporal Query Language*, 1995.
  - Datomic data model (Rich Hickey): https://docs.datomic.com
  - SQL:2011 temporal extensions.
- **Trust / abstention**
  - El-Yaniv & Wiener, *On the Foundations of Noise-free Selective Classification*, 2010.
  - Vovk, Gammerman, Shafer, *Algorithmic Learning in a Random World* (conformal prediction), 2005.
- **Software-architecture knowledge**
  - Tornhill, *Your Code as a Crime Scene* (code-maat / hotspots methodology).
  - The MADR specification: https://adr.github.io/madr/
  - Repowise architecture analysis: `docs/market-analysis/repowise/`.
  - entire.io analysis: `docs/market-analysis/entire-io/`.
- **Tools / libraries**
  - sqlite-utils: https://github.com/simonw/sqlite-utils
  - sqlite-vec: https://github.com/asg017/sqlite-vec
  - Datasette: https://datasette.io
  - pygls (LSP framework for Python): https://github.com/openlawlibrary/pygls
  - networkx: https://networkx.org
  - PyDriller: https://github.com/ishepard/pydriller
  - mcp[cli] (official Python SDK): https://github.com/modelcontextprotocol/python-sdk
