---
status: draft
date: 2026-05-12
---

# PRD-004 State-of-the-Art Decision Reasoning

## Problem Statement

PRD-003 establishes a competent decision-provenance graph: SQLite index, weighted keyword retrieval, `governs:` field, git-trailer SPEC↔commit binding, MCP server with five task-shaped tools. That baseline matches what Repowise already shipped. It is necessary but not state-of-the-art, and it is not the form decree needs to take to be genuinely useful in a codebase being authored primarily by LLMs.

Three concrete gaps remain after PRD-003 v1:

1. **Decree's output is not trustworthy enough to be relied on.** Repowise has three confidence gates (dominance ratio, identifier-citation, hedge-phrase). That is a beginning, not a complete trust story. A retrieval system that returns the best-of-bad-options when no decision strongly applies trains its consumers — both humans and LLM agents — to ignore it. Over time, low-trust retrieval becomes worse than no retrieval, because it crowds out the human's own judgment with confident-sounding noise. Decree needs *calibrated abstention*: a principled way to return "no governance found" rather than retrieving something irrelevant, with the calibration tuned against a labeled validation set. This is the single load-bearing trust property for the system, and it is under-researched in the ADR-retrieval space specifically.

2. **Decree is consulted at the wrong time.** PRD-003's intent-review API (R8) runs against a diff — after the agent has already written code. By then, decree is reduced to a code-review tool: it can complain, but the cost of revision is high and the agent has already committed cognitively to the approach it took. The leverage point is *earlier* — during the agent's planning phase, before any code exists. An LLM agent saying "I'm about to implement caching for the auth path" should be able to call `decree.intent_check(plan)` and receive the governing decisions, conflict warnings, and stale-decision flags before it writes a line of code. This shifts decree from passive record-keeping ("here is what was decided") to active influence ("here is what your plan implies, given what was decided"). Code review tools exist; intent review at the planning step is the missing surface, and it is the surface where decree is uniquely valuable for LLM-authored codebases.

3. **No claim decree makes is currently falsifiable.** PRD-003 cites latency targets and consumer fan-out as success criteria, but it has no labeled evaluation set, no baseline metrics, no ablation methodology. "Our retrieval is good" is a hope, not a measurement. For a research project this is fatal — every subsequent claim is unverifiable; every future direction is chosen by intuition rather than evidence. The trust property in (1) cannot be calibrated without an evaluation harness; the intent-review quality in (2) cannot be measured without one either. The harness is infrastructure for the other two requirements, not a separate concern.

The thesis tying these together: **decree's unique value is making LLM-authored code align with prior decisions, and to do that decree must be (a) trusted, (b) consulted at planning time, and (c) measurable.** PRD-003 builds the substrate; this PRD builds the properties that make the substrate worth using.

## Requirements

### R1: Calibrated abstention (E.2 from research-frontiers.md)

- `decree why <path>`, `decree refs <id>`, and `decree.intent_check(plan)` may return an explicit "no governance found" / "low confidence" result rather than the best-of-K candidates when no decision strongly applies.
- The abstention threshold is *calibrated*, not heuristic. Calibration uses a labeled set of (query, ground-truth: "relevant decision exists?" / "no relevant decision") pairs. The threshold is chosen to satisfy a configurable precision target (e.g., "of the queries where we return a decision, ≥90% should have a genuinely relevant one").
- Apply selective-prediction methodology from the literature (El-Yaniv & Wiener 2010; Vovk et al. conformal prediction). Track coverage-risk tradeoff explicitly — report both numbers, not one in isolation.
- New confidence gates beyond Repowise's three, evaluated for marginal contribution:
  - **Status gate**: top hits all deprecated/superseded → abstain or warn.
  - **Recency gate**: only matches are >18 months old and untouched → flag as stale-only.
  - **Coverage gate**: matched governing scope is tiny relative to the queried scope → "low coverage, may not apply."
  - **Authorship gate**: matching decision authored by someone with no recent activity → flag for sanity-check.
- Gate composition is evaluated empirically — multiplicative, disjunctive, or learned combinations are all candidates. Pick the one with the best coverage-risk profile on the validation set.
- Surface *why* the system abstained, when it does. "No decision strongly governs this path; closest match was ADR-0042 but it's superseded by ADR-0089 which doesn't list this path." A user who knows the reason can override; one who doesn't will distrust the abstention.

### R2: Pre-PR intent review (C.2 from research-frontiers.md)

- New MCP tool `decree.intent_check(plan: str, planned_files: list[str]) -> IntentReport`.
- `IntentReport` structure (subject to SPEC refinement):
  - `governing_decisions`: list of `(decision_id, status, scope_match_strength, why)` for each decision that governs any of the `planned_files`.
  - `conflicts`: pairs of decisions that disagree about the same file, with LLM-judged "is this an actual conflict or different aspects of the same file?" verdict.
  - `stale_governance`: governing decisions whose `governs:` files have churned heavily since the decision was last touched.
  - `unchecked_acceptance_criteria`: ACs from in-flight SPECs that the plan's `planned_files` likely affect.
  - `abstention`: structured "we don't have governance for this" response when nothing strongly applies (R1 mechanism).
  - `recommended_actions`: ranked list of next steps the agent could take (e.g., "draft a new ADR before proceeding"; "reference SPEC-007 in your implementation"; "resolve conflict between ADR-0042 and SPEC-091 first").
- Available as MCP tool, CLI command (`decree intent-check --plan "..." --files "src/foo.ts,src/bar.ts"`), and Python library API (`decree.intent_check(plan, files)`).
- Intent-review reports are *structured data*, not prose. Consumers render — decree returns. (Matches PRD-003 R8's principle.)
- Distinguished from PRD-003 R8 (`intent_review(diff)`) by timing: R2 here runs *pre-code*, on a plan summary; R8 runs *post-code*, on a diff. The two share infrastructure but answer different questions.

### R3: Evaluation harness (A.5 from research-frontiers.md)

- A labeled query set for decree's representative corpus. Composition:
  - 50–200 queries spanning the three query types: file-path lookups, concept queries, multi-hop "why does our system work this way" questions.
  - Each query has ground-truth labels: the set of relevant decisions (possibly empty), with relevance grades if practical (binary minimum, graded preferred).
  - Authoring shape: LLM-bootstrapped + human-spot-checked, with provenance recorded for each label.
  - The corpus is *representative*, not decree's own dogfood. Candidates: a synthesized corpus, an open-source project with a substantial ADR set (CNCF projects, the C4 model project itself), or both. Pick is itself an open question (see Open Questions below).
- `decree retrieval-eval` command:
  - Runs PRD-003 v1 keyword retrieval as the baseline.
  - Runs any retrieval method registered via a plugin interface against the same query set.
  - Reports Recall@K, MRR, NDCG@10, and the coverage-risk curve for R1's calibrated abstention.
  - Output: markdown report with per-method tables, ablation deltas vs. baseline, and confidence intervals (bootstrap recommended).
- All claims made by this PRD or by PRD-003's R3/R5/R7 are validatable against the harness. Anything that can't be measured against it is not load-bearing.
- The harness itself ships before R1 and R2 — they need it for calibration and for measuring intent-check quality, not just as documentation.

## Success Criteria

- **Trust calibration**: at a coverage of 70% (i.e., `decree why` returns a decision 70% of the time and abstains 30%), the precision among returned decisions is ≥90% on the validation set. The tradeoff curve is reportable for other operating points.
- **Abstention is meaningful, not vestigial**: at least 25% of queries on the validation set return abstention, *and* the abstention reasons are distributed across multiple gates (not all driven by one gate, which would indicate the others are dead).
- **Intent-check reduces post-code revision**: in a controlled study (synthetic agents tasked with implementing changes in the validation corpus), agents using `decree.intent_check` before coding produce diffs that conflict with existing decisions ≤50% as often as agents not using it. The study is itself an artifact of R3's harness.
- **Evaluation is reproducible**: `decree retrieval-eval` produces the same numbers across two runs on the same corpus + query set (within bootstrap confidence intervals).
- **Falsifiability surface area**: every requirement in PRD-003 (R1–R8) and every requirement in this PRD (R1–R3) has at least one measurement in the harness's output that supports or refutes its delivery. Claims not measurable against the harness are documented as such.
- **Research artifact quality**: the evaluation results are written up as a public document (`docs/evaluation/<date>.md`) with methodology, results, ablations, and limitations. The writeup is reviewable by someone outside the project.

## Scope

**In scope (v2 — after PRD-003 v1 ships):**
- R1 calibrated abstention with the four new confidence gates + Repowise's three.
- R2 pre-PR intent review via `decree.intent_check`, MCP + CLI + library API.
- R3 evaluation harness with labeled query set, baseline metrics, plugin interface for new retrievers, markdown report generator.
- Selective-prediction methodology (conformal prediction or coverage-risk calibration).
- Public writeup of evaluation results.

**Explicitly deferred (frontiers not picked in this PRD; available for PRD-005 / SPEC follow-ups):**
- A.1 Hybrid retrieval (lexical + dense + structural) — interesting research but Repowise's baseline is probably correct at decree's corpus size; revisit after R3's harness can prove or refute it.
- A.2 GraphRAG community summarization.
- A.4 Active learning from rejections.
- B.1 Temporal queries / bitemporal model.
- B.2 Causal vs. correlational governance.
- B.3 Decision lineage / supersedes lattice.
- B.4 Conflict detection (overlaps with R2's `conflicts` field but the *detection algorithm* is deferred — v2 may use LLM-as-judge as a placeholder).
- B.5 Cross-repo provenance.
- C.1 Auto-propose ADRs from hotspots.
- C.3 LLM-facilitated decision refinement.
- C.4 Multi-repo coherence.
- D.1 LSP server.
- D.2 Reactive subscriptions.
- D.3 PR review bot.
- D.4 Datasette plugin.
- D.5 Live dashboard.
- E.3 Decision freshness decay (subsumed into R1's recency gate at simpler granularity; full freshness-curve research deferred).
- E.4 Adversarial probing — included as a *methodology* inside R3's harness but not as a standalone product feature.

**Out of scope:**
- Replacing PRD-003 v1's baseline retrieval before R3's harness can validate that a replacement is genuinely better.
- Domain-specific ranker training. Generic relevance only in v2.
- Multi-tenancy or multi-user state in the active-learning sense — R1 calibration is per-corpus, not per-user.

## Dependencies

### On other decree work

- **PRD-003 v1 must ship before PRD-004 reaches `review`.** R1's calibration runs against the retriever PRD-003 builds; R2 reuses R8's structure (planning-time vs. diff-time); R3's baseline *is* PRD-003. This PRD stays in `draft` while PRD-003 ships and moves to `review` once the v1 baseline exists.
- **ADR-0002 (Index-First Architecture) — accepted** — constrains the technical surface this PRD's SPECs design against. The hybrid-cache model means the index is where R3's eval queries run.

### On libraries (additions to PRD-003's load-bearing set)

| Concern | Library | License | Rationale |
|---|---|---|---|
| Selective prediction / conformal calibration | `crepes` | MIT | Standard Python implementation of conformal prediction. Saves rebuilding the calibration machinery. |
| Statistical evaluation (bootstrap, CIs, paired tests) | `scipy.stats` + `numpy` | BSD | Standard scientific Python stack for R3's confidence intervals. |
| Information retrieval metrics | `ir_measures` | MIT (verify) | NDCG, MRR, Recall@K with standard semantics. Avoid hand-rolling. Verify license before adopting; if licensing is unclear, prefer a fork or hand-roll the four metrics from scratch (~80 LOC). |
| LLM client for R2 conflict-judgment, R3 bootstrap labeling | Anthropic Python SDK or OpenAI SDK (project-configurable) | MIT-ish | One required, behind a provider-abstraction so research can swap models. |
| Prompt-template management for LLM judgments | `jinja2` | BSD | Standard, already widely used. |

All additions are MIT/BSD or verifiable-MIT-equivalent. Decree's MIT-distributable property remains intact.

### Library leverage stays load-bearing

PRD-003's principle ("SPECs that reimplement these in-house should fail review") extends to this PRD. Specifically: do not reimplement conformal prediction, do not reimplement IR metrics, do not reimplement bootstrap confidence intervals. These are commodity research infrastructure.

## Evaluation methodology

PRD-004 is the first decree document where evaluation methodology is itself a deliverable, not a side-effect. The methodology section of this PRD is load-bearing — SPECs implementing R1/R2/R3 must adhere to it.

1. **Labeled query set provenance** — every label is annotated with its source (LLM-generated, human-authored, spot-checked) and its provenance is preserved in the harness output. LLM-generated labels are not trusted blindly; a 10%+ random sample is human-verified before claiming results.
2. **Baseline reproducibility** — PRD-003 v1's retrieval is frozen as the baseline at the time R3 ships. Subsequent retrieval changes are evaluated against the frozen baseline, with deltas reported.
3. **Confidence intervals** — bootstrap (1000+ resamples) for every reported metric. Point estimates without intervals are not accepted.
4. **Ablations** — each gate in R1's calibrated abstention is ablated independently (composition contribution measured per-gate). Each component of R2's IntentReport is ablated for utility (does removing the `stale_governance` field actually hurt the agent's downstream behavior, or does the agent ignore it anyway?).
5. **Limitations documented** — every published evaluation result names at least three limitations: corpus representativeness, query-set coverage, LLM-judge agreement caveats. Limitations are not optional caveats — they are part of the deliverable.
6. **Adversarial probing** — R3's harness includes a small set of intentionally misleading queries to test the trust property in R1. Coverage of failure modes is reported, not just average-case metrics.

## Open questions for downstream SPECs

1. **Corpus selection for the labeled query set.** Decree's own dogfood corpus (currently 7 documents including PRD-004 itself) is far too small for credible retrieval evaluation. The SPEC implementing R3 must pick: (a) a synthesized representative corpus (LLM-generated decisions designed to span query types), (b) an existing open-source ADR corpus (CNCF projects, the C4 model project, others), or (c) both. The pick determines what generalization claims can be made.
2. **Unit of governance for evaluation.** Are we evaluating file-level retrieval, symbol-level retrieval, or both? PRD-003 v1 ships file-level; symbol-level is v2 backlog. R3 must commit to one or have separate evaluation tracks.
3. **LLM-judge dependency.** R2 conflict detection and R3 label bootstrapping both depend on an LLM judge. Which model, with what prompt structure, and how is judge drift measured over time? The SPEC must specify a "judge contract": exact prompt, model id, deterministic decoding settings, and an audit cadence.
4. **Calibration set size.** Conformal prediction has known minimum-sample-size requirements for tight bounds. The labeled query set's size must accommodate this for R1 to be credible.
5. **Operating-point selection.** R1 commits to a 70% coverage / 90% precision target as a success criterion, but the production default may differ. The SPEC implementing R1 must document how an operating consumer (LLM agent, human via CLI, Electron app) chooses its operating point and whether different consumers should get different defaults.
6. **R2 timing-of-call.** Pre-PR intent review needs to be called *before* the agent writes code. What's the integration shape — does the agent's planning prompt include "call decree.intent_check first"? Is there an MCP-level "planning phase" convention? Or do we just document the pattern and let consumers opt in?

## References

- `docs/market-analysis/research-frontiers.md` — full menu of frontiers; PRD-004 picks E.2, C.2, A.5.
- `docs/market-analysis/discussion-notes.md` — Repowise + entire.io analyses that motivate the trust + intent-review framing.
- PRD-003 — baseline that PRD-004 builds on. R3's eval baseline is frozen PRD-003 v1.
- ADR-0002 — accepted; constrains the technical surface (hybrid-cache, index-as-query-substrate).
- El-Yaniv, R., & Wiener, Y. (2010). *On the Foundations of Noise-free Selective Classification*.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in a Random World*. (Conformal prediction.)
- Thakur, N. et al. (2021). *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models*.
- Edge, D. et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*.
