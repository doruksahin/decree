# Repowise RAG Thesis: Implications for Decision-Record Retrieval

Source: https://www.repowise.dev/blog/concepts/rag-for-code-is-not-embeddings-plus-a-vector-store, https://docs.repowise.dev/mcp/get-why, https://docs.repowise.dev/mcp/get-answer (retrieved 2026-05-12).

---

## The Argument

Repowise's blog post "RAG for code is not embeddings plus a vector store" makes a specific claim: "Similarity is a useful primitive. It is not relevance." The failure mode they identify is concrete. Ask an embedding-only system "why did auth middleware change?" and it retrieves files that semantically *discuss* auth — not files that *implement* it. Test files and implementation files cluster near each other in embedding space because they share vocabulary. But for the question "what governs this file?", a test file that mentions `authenticate()` is not relevant; the ADR that mandated the session boundary is.

The key distinction: embeddings optimize for semantic proximity, which is a proxy for relevance in open-domain text Q&A. It is a poor proxy for structural questions about code — questions involving call graphs, dependency edges, change history, and ownership. For those questions, you need signals that embeddings do not encode.

---

## How Repowise Resolves It

They do not abandon retrieval — they layer the signals. For different question types, different retrievers take precedence:

- **Wiki search** (open-domain documentation questions): dual-indexed via SQLite FTS (keyword) + LanceDB (vector), merged and deduplicated. Embeddings participate here as one of two signals.
- **Decision retrieval** (architectural rationale questions): zero embeddings. Weighted keyword scoring only.
- **Graph traversal** (structural questions): follows import edges, call edges, co-change pairs. No retrieval in the traditional sense — the graph is the index.
- **Git history** (temporal questions): commit log scan with significance filtering, not vector search.

The decision retrieval pipeline is the most directly applicable to decree, so it is worth describing precisely.

---

## Decision Retrieval Pipeline (the Applicable Model)

From the `get_why` documentation:

**Field weights:**
- Title: 3.0x
- Decision and Rationale fields: 2.0x
- Context field: 1.5x
- Consequences, Tags, Affected Files: 1.0x
- Exact file path match in targets: +5.0 bonus
- Parent-directory match: +3.0 bonus

The scoring is additive and weighted, not cosine similarity. The rationale for these weights is structural: a query asking "why was X chosen?" is most likely answered by the title (naming the decision) and the rationale (explaining the choice), less by the surrounding context, and least by the consequences. The weighting encodes that intuition as a scoring function.

The file-path bonuses are the most important part. A decision that explicitly lists a governed file in its `affected_files` field receives a +5.0 bonus when that exact file is the subject of the query. This means the retrieval is not purely text-similarity — it is conditioned on the structural link between the decision and the code it governs. A document that happens to mention the same words but does not list the file as a governed target scores substantially lower.

This is the correct model for decree's retrieval problem. The equivalent in decree terms: a SPEC that lists `apps/desktop/src/renderer/src/pages/playgrounds/` in a `governs:` frontmatter field should rank dramatically higher than a SPEC that merely mentions the same path in its body text when someone asks `decree why apps/desktop/src/renderer/src/pages/playgrounds/ui/FilterBar.tsx`.

---

## Three Confidence Gates (Applied to Decision Retrieval)

`get_answer` implements three gates that prevent synthesis from weak retrieval. These are rule-based, not learned:

**Gate 1 — Dominance ratio**: If `top_score < 1.2 * second_score`, skip synthesis, return raw excerpts. The signal: when two documents are nearly tied, neither is clearly the right answer, and forcing synthesis produces a blend of two potentially contradictory rationales. This is the correct behavior for architectural decision lookup — returning two competing ADRs with their raw text is more honest than averaging them into a synthetic answer.

**Gate 2 — Identifier-citation gate**: If the query names a specific symbol (a function, a class, a file path) and that identifier does not appear in the top retrieved hits, confidence downgrades from high to medium. The signal: the query was specific, the retrieval was not. The caller should know that the answer may not address the specific thing they asked about.

**Gate 3 — Hedge-phrase detection**: If the synthesized answer contains phrases indicating the LLM is guessing ("may have been", "it is unclear", "possibly"), confidence downgrades from high to low. The model cannot mask its own uncertainty behind a high-confidence label.

For decree, these gates translate directly: a `decree why` command that cannot find a document with score > 1.2x the runner-up should return the candidates rather than pick one. A query naming a specific file that returns no documents with that file in a `governs:` field should report "no governing document found" rather than returning the highest-scored document as if it were authoritative.

---

## What This Rejects

Repowise explicitly does not use:

- **Rerankers**: No learned cross-encoder pass over retrieved candidates.
- **HyDE** (Hypothetical Document Embeddings): No "generate a hypothetical answer and embed it as a query."
- **Query rewriting**: No reformulation of the user's query before retrieval.
- **Chain-of-thought retrieval**: No iterative retrieval loops where the model reasons its way to what it needs.

The rejection is not ignorance of these techniques. It is a product of the specific failure modes they solve versus the ones that matter for code intelligence. HyDE helps when queries are poorly formed relative to a document corpus. For decision records, the queries are typically well-formed (they are file paths or precise questions about architectural choices) and the corpus is small (a repo has tens to hundreds of ADRs, not millions of documents). The overhead of rerankers and HyDE is not justified at that scale, and the techniques introduce latency and opacity that compound badly in CI and editor contexts.

---

## The Implication for decree

decree today has no retrieval at all. `decree lint` validates; `decree progress` counts; `decree status` transitions. None of them answer the question "what SPEC governs this file?" The file path has no semantic connection to the document corpus. You either know the SPEC number or you do not.

The Repowise model prescribes a specific remedy: add a `governs:` frontmatter field (a list of file paths and directory globs), build a reverse index (file path → SPEC IDs), and score queries with file-path match bonuses weighted at +5.0 for exact and +3.0 for parent-directory. No embeddings required. The corpus is small enough that a SQLite FTS pass with weighted fields runs in milliseconds. The dominance ratio gate and identifier-citation gate can be implemented in under 50 lines of Python.

The result is a `decree why <path>` command that returns: (1) the governing SPEC(s) with match score, (2) a confidence signal (dominated / tied / no match), and (3) a fallback to body-text search when no `governs:` link exists. This is directly analogous to `get_why` mode 2, adapted to decree's document-centric model rather than Repowise's graph-node model.

The four-signal architecture (structure + history + docs + ownership) is Repowise's full stack. decree does not need the full stack. It needs the decision-retrieval slice: field-weighted keyword scoring with structural bonuses for governed-path matches, gated by a dominance ratio check. That is the extractable lesson.
