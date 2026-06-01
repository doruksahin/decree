---
date: '2026-05-12'
id: PRD-01KT22NMRTAF9581AXC53EHQTW
status: approved
---

# PRD-01KT22NMRTAF9581AXC53EHQTW Real-Corpus Validation Against jira-task-to-md

## Problem Statement

PRD-01KT22NMRS4QGHSFDBZ858PP1T and PRD-01KT22NMRSXYT95XE808VD8EV4 v1 built the substrate (SQLite index, governs field, queries, MCP, calibrated abstention, intent-review/check). Every measurement decree makes today is against its **own ~20-doc corpus**: 33 hand-authored queries, n=19 calibration samples. The SPEC-01KT22NMS0VWCTYPFPHP8M8V36 implementation report stated it plainly — at that scale, `crepes` is "largely ceremonial"; the conformal p-values are well-defined but the test-precision CI is roughly [0.55, 0.997]. We don't know whether decree's design hypotheses hold past toy scale.

Three specific claims are currently unfalsifiable:

1. **"Keyword-v1 is a competent baseline for ADR-corpus retrieval"** (the Repowise thesis decree replicated). The SPEC-01KT22NMRZXE5C42F6Z0ZY559A dogfood found that BM25 over-ranks umbrella PRDs above implementing SPECs, and that cross-doc lexical overlap beats topical relevance. Whether these gaps are minor (10% of queries) or load-bearing (>50% of queries) is unknown until we run against a corpus where the queries weren't authored by the same person who wrote the docs.

2. **"Calibrated abstention is worth the recall hit"**. Currently `keyword-v1-calibrated` drops R@1 from 0.85 → 0.80 in exchange for "fewer wrong answers." At n=19, that delta is within the CI noise. At n=100, we'll know whether the trade is actually favorable.

3. **"The agent-assisted governs backfill is useful"** (core `migrate governs --analyze --json` plus an external `decree.governs-suggestions.v1` producer). It's only ever been tested on controlled fixtures. We've never run it against an actual corpus where the answer isn't already known.

The decree project is fundamentally an *educational/research artifact*. Without a real-corpus evaluation, the PM-level claims it makes ("queryable provenance graph", "calibrated trust surface", "intent-review for LLM-authored code") are aspirational rather than measured.

The jira-task-to-md corpus is the natural target. It exists. It's 167 documents — substantial. It's the project where decree was *meant* to be applied. It was the integration test target named in PRD-01KT22NMRS4QGHSFDBZ858PP1T R9. This PRD finally runs that integration test and reports what we find.

The deliverable is **a report**, not features. Decree gains no new commands or APIs in this PRD. What it gains is a publicly-reviewable evaluation against a real corpus, with honest findings and identified gaps.

## Requirements

### R1: Apply `decree migrate governs --analyze` and external suggestions to jira-task-to-md's corpus

- Run the SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S tool against the 167-doc jira-task-to-md corpus.
- Sample ≥20% of generated proposals for human spot-check.
- Capture: total proposed paths, paths-that-exist rate, human-edit rate, false-positive count.
- API cost cap: $25. If exceeded, document the cost / coverage trade.
- Output: `docs/evaluation/jira-corpus-governs-suggest-2026-05-12.md` with example proposals and aggregate stats.

### R2: Build a 100-200 query labeled benchmark

- File: `eval/queries-jira.yaml` (in the decree repo, NOT in jira-task-to-md).
- Composition: ≥40 `file_path` queries, ≥40 `concept` queries, ≥20 abstention queries.
- Provenance per query: hand-authored / LLM-bootstrapped / human-spot-checked. Recorded in the YAML alongside each query.
- LLM-bootstrapped queries must be spot-checked at ≥25% sampling before claiming.
- Schema-compatible with SPEC-01KT22NMRZXE5C42F6Z0ZY559A's loader (no schema changes — corpus identifier becomes "jira-task-to-md" instead of "decree").

### R3: Run retrieval evaluation on the new corpus

- `decree retrieval-eval --queries eval/queries-jira.yaml --freeze` writes `eval/baselines/keyword-v1-jira.json`.
- Report metrics: Recall@K (K=1,3,5,10), MRR, nDCG@10 with bootstrap 95% CIs at 1000 resamples.
- Compare to the frozen decree-corpus baseline (`eval/baselines/keyword-v1.json`) — does the keyword approach hold up at 5x corpus size?

### R4: Recalibrate abstention against the new query set

- `decree retrieval-eval --calibrate --queries eval/queries-jira.yaml --target-precision 0.9`.
- At ≥60 calibration samples (60/40 split from a 100-query set yields 60 calibration), conformal p-values become meaningful.
- Write `eval/calibrations/keyword-v1-jira.json` (alongside the existing `keyword-v1.json`).
- Report: chosen threshold, test-set precision, coverage, comparison to decree-corpus calibration.

### R5: Write up findings publicly

- `docs/evaluation/jira-corpus-2026-05-12.md`.
- Sections:
  - **Corpus stats**: 167 docs, types breakdown, age distribution, existing governs coverage (probably 0% pre-backfill).
  - **Methodology**: query set provenance, eval flags, bootstrap settings.
  - **Governs-backfill results** (R1 summary).
  - **Retrieval baseline** (R3 numbers).
  - **Calibration results** (R4 numbers).
  - **Findings**: which design hypotheses held? Which failed? Specific bugs / behaviors surfaced.
  - **Limitations**: corpus is one project; queries hand-authored; LLM-bootstrap caveats; labeler-bias caveats.
  - **What this opens up**: motivates PRD-01KT22NMRTFTWFFARAN0PVEETA (likely hybrid retrieval) or other directions.
- Reviewable by someone outside the decree project. Stylistically neutral; no hype.

## Success Criteria

- R1-R5 all completed; all artifacts present in-tree.
- The eval writeup contains at least one **concrete confirmed claim** (with effect size + CI) and at least one **concrete falsified claim** about decree's design hypotheses. Mixed findings are the honest outcome of validation; "everything worked" is suspicious and means the queries weren't adversarial enough.
- API costs documented; under $25.
- No new third-party dependencies. All tooling exists from PRD-01KT22NMRS4QGHSFDBZ858PP1T + PRD-01KT22NMRSXYT95XE808VD8EV4.
- Tests still pass post-PRD work (because no production code should change for this validation pass).
- The decree project's MIT license is unchanged. jira-task-to-md is a separate repo; we operate on a *copy* of its corpus that we don't redistribute.

## Scope

**In scope (v1):**
- Full pipeline from `migrate governs --analyze` → external suggestions → query set authoring → retrieval eval → calibration → writeup.
- decree-corpus and jira-corpus baselines reported side-by-side for comparison.
- Honest limitations.

**Out of scope:**
- Building new retrieval methods. If R3 reveals that keyword-v1 is insufficient, the *next* PRD ships hybrid retrieval. This PRD only measures.
- Recommendations to the jira-task-to-md project itself. We don't push any decisions back to that repo.
- Real-time / continuous evaluation. One-shot snapshot in v1; re-runs as the corpus evolves are future work.
- External corpora beyond jira-task-to-md (CNCF ADRs, C4 project, etc.). One corpus is enough for v1.

## Dependencies

- All tooling from PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 and PRD-01KT22NMRSXYT95XE808VD8EV4 v1.
- A copy of jira-task-to-md's decree corpus (at `/Users/doruk/Desktop/ADCREATIVE/jira-task-to-md/decree/`). PM provides path; SPECs reference but don't bundle.
- An external LLM-capable agent/runtime for R1 suggestions and the LLM-bootstrap portion of R2. Core decree does not require provider API keys.

## Open questions

1. **Calibration set size**: is 100 queries enough for crepes to start being meaningful (vs the ceremonial 19)? Literature suggests ~100 minimum; we're at the low end. SPEC implementing R4 documents the resulting CI widths.

2. **LLM model choice for external suggestions**: should we use the same model for governs suggestions and for label-bootstrap to ensure consistency? PM call: yes. The R1/R2 SPECs lock the model in their respective frontmatter or agent runbook.

3. **Spot-check fraction**: 20% of governs proposals + 25% of bootstrapped labels. Both numbers are guesses. SPECs document them; future PRDs revise based on what worked.

4. **What if R3 shows keyword-v1 is great?** Then PRD-01KT22NMRTAF9581AXC53EHQTW closes as "validation passed; no PRD-01KT22NMRTFTWFFARAN0PVEETA needed yet." That's a valid outcome. We don't have to find problems.

5. **What if R3 shows keyword-v1 is terrible?** Then PRD-01KT22NMRTFTWFFARAN0PVEETA (hybrid retrieval, deferred from PRD-01KT22NMRSXYT95XE808VD8EV4) is well-motivated. We have a quantitative case for the work.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T, PRD-01KT22NMRSXYT95XE808VD8EV4 — the substrate this PRD validates.
- SPEC-01KT22NMS0BN1F5B01HEFK87W0 — provider-free analyze/apply contract used in R1.
- SPEC-01KT22NMRZXE5C42F6Z0ZY559A — eval harness used in R3.
- SPEC-01KT22NMS0VWCTYPFPHP8M8V36 — calibrated abstention used in R4.
- `docs/market-analysis/discussion-notes.md` — the original Repowise + entire.io framing this PRD operationalises a measurement against.
- jira-task-to-md project root: `/Users/doruk/Desktop/ADCREATIVE/jira-task-to-md/` (PM context; not bundled).
