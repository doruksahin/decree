# Provenance & Determinism Model

> **TL;DR.** decree's provenance has two layers. git **guarantees** which files a
> commit changed (content-addressed, deterministic). git does **not** guarantee
> *which decision* a commit implements — that link is the
> `Implements:/Refs:/Fixes:` **trailer convention**, written by `decree commit`
> or by hand. So every git-derived signal (`commits`, staleness, observed
> governance, dead-governance) is a **deterministic computation over a
> convention-grade input**. decree never presents it as certainty: the signals
> are advisory, fail-safe, and coverage-honest, and they never feed `why()`.

## Why this matters

decree answers: *which decision explains this code, and is the planned change
still aligned?* Part of that answer is git-derived — which commits, touching
which files, claim which decisions. Anyone building or trusting those signals
must know exactly **what is guaranteed and what is convention**, or the tool
silently overclaims — the precise failure mode it exists to prevent.

## The two layers

### Layer 1 — git-guaranteed (deterministic, certain)

git is content-addressed: a commit's SHA is a hash of its tree, parents, and
metadata. From that, these facts are **exact and reproducible**:

- which files a commit changed (the tree diff; `git log --name-only`),
- the commit DAG, authorship, and timestamps.

"Commit `abc123` touched `src/foo.py`" is **certain**. The index reads this layer
for `observed_governs`, staleness churn, and similar.

### Layer 2 — convention (not git-enforced)

git has no concept of a "decision." The only commit→decision link is a **trailer
in the commit message** — `Implements: SPEC-…`, `Refs: …`, `Fixes: …`. A trailer
is free text: a **claim**, written by `decree commit` (which infers the decision
from the staged decision-doc paths) or by hand, and parsed with
`git interpret-trailers`. git neither validates nor enforces it.

"Commit `abc123` implements `SPEC-X`" is a **claim** — only as reliable as the
discipline that wrote it.

## The determinism boundary

- **The computation is deterministic.** Same history + same trailers ⇒ identical
  `commits`, `observed_governs`, and staleness. No LLM; pure SQL over the index.
  Rebuilds are reproducible.
- **The ground truth is not.** Trailer accuracy is a human/agent artifact.
  Garbage trailers in ⇒ garbage provenance out. decree cannot *make* the link
  true; it can only compute faithfully over whatever trailers exist.

So **deterministic ≠ certain.** The pipeline is deterministic; its
trustworthiness is bounded by Layer 2.

## The trailer-discipline dependency (the load-bearing assumption)

Every git-derived signal is only as good as trailer coverage:

| Situation | Effect on provenance |
|---|---|
| Commit with no decree trailer | Invisible — never linked to any decision. |
| One commit batching several decisions' work | Over-attribution — every listed decision "observes" all the commit's files. |
| Squash-merge (N files under one trailer) | Coarse over-attribution. |
| Wrong trailer | Wrong attribution (garbage-in). |
| Renamed decision doc or code | Historical paths differ from current; decree excludes corpus docs by directory to stay robust, but co-change attribution still reflects the historical path. |

## Design response — never overclaim

Because Layer 2 is convention-grade, every decree signal built on it:

- **is advisory** — a `decree health` surface, never an enforced gate;
- **fails safe** — e.g. dead-governance flags a declared `governs:` path "dead"
  only when the decision has **≥1 trailer-linked commit**; otherwise the path is
  **"unobserved," not "dead."** Over-attribution can only *suppress* a dead
  claim, never *invent* one;
- **is coverage-honest** — it surfaces per-decision linked-commit counts, how
  many commits were untrailed and ignored, and the "as of last index sync"
  timestamp, so a reader can judge how solid the basis is;
- **never feeds the authoritative layer** — `observed_governs` (convention-
  derived) must **never** be read by `why()` / `intent-check`, which answer only
  from the **declared** `governs:` frontmatter. Mixing them would be exactly the
  silent fallback decree forbids.

The system's integrity comes from *admitting* the uncertainty and surfacing it,
not from hiding it.

## LLM-driven engineering

The weak link — trailer accuracy — is exactly where ad-hoc LLM commits fail: an
agent may commit without a trailer, batch unrelated work, or squash. For an
autonomous agent the commit→decision link is **probabilistic unless the harness
enforces it.** This cuts both ways:

- A **governed-session harness** (the agent is told which decision it works
  under — e.g. agentkith's "Start governed session") can write
  `Implements: SPEC-X` **more reliably than ad-hoc human commits**, because the
  decision is known at commit time. The structural fix is to have the agent
  commit *through* the harness with `decree commit`.
- To move from convention toward a **guarantee**, add **commit-time
  enforcement**: a pre-commit / CI gate that rejects a commit touching governed
  paths without a corresponding trailer. That is enforcement (a separate
  decision) and largely the harness's responsibility — not the deterministic
  read-layer's.

## Rules for contributors and agents

1. Commit with `decree commit` so trailers are canonical.
2. Treat every git-derived signal as **advisory and coverage-gated**, never
   ground truth.
3. When building a new git-derived signal: keep the computation deterministic;
   fail safe (no claim without an observation basis); be coverage-honest; and
   **never let convention-grade data feed `why()`**.
4. Never present "this commit implemented this decision" as certainty — it is a
   claim whose reliability you must surface, not assume.

## Where this lives in the code

- `src/decree/index_db.py` — `sync_commits_from_git` (Layer 2 ingestion from
  trailers) and `observed_governs` (the Layer 1 file-touch join). A derived
  read-cache; never authoritative.
- `src/decree/commands/health.py` — staleness, ungoverned hotspots, and
  dead-governance: the advisory, coverage-honest surfaces.
- `src/decree/commands/queries.py` — `why` / `refs`: the **authoritative** layer,
  answering only from declared `governs:`. It must stay isolated from the
  convention layer.
- `src/decree/commands/commit.py` — `decree commit`: writes the canonical
  trailers via `git interpret-trailers`.
