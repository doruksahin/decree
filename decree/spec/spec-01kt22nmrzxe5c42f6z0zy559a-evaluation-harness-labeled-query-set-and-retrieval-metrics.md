---
date: '2026-05-12'
governs:
- src/decree/eval/
- src/decree/commands/eval.py
- eval/queries.yaml
id: SPEC-01KT22NMRZXE5C42F6Z0ZY559A
references:
- PRD-01KT22NMRSXYT95XE808VD8EV4
status: implemented
---

# SPEC-01KT22NMRZXE5C42F6Z0ZY559A Evaluation Harness — Labeled Query Set and Retrieval Metrics

## Overview

Implements PRD-01KT22NMRSXYT95XE808VD8EV4 R3 — the evaluation harness. The spine of PRD-01KT22NMRSXYT95XE808VD8EV4: nothing R1 (calibrated abstention) claims is falsifiable without a labeled query set + metric runner. This SPEC ships that infrastructure.

What lands:
1. **Labeled query set schema** — YAML format in `eval/queries.yaml`, human-editable, supports binary or graded relevance.
2. **`decree retrieval-eval` command** — runs registered retrieval methods against the query set, reports Recall@K / MRR / NDCG@10 with bootstrap confidence intervals.
3. **Plugin interface** — `RetrievalMethod` protocol so PRD-01KT22NMRS4QGHSFDBZ858PP1T's keyword baseline + future PRD-01KT22NMRSXYT95XE808VD8EV4 methods (calibrated, hybrid, etc.) plug in with one signature.
4. **Frozen baseline** — current PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 keyword scoring is named `keyword-v1`, results snapshotted to `eval/baselines/keyword-v1.json` so future runs report delta against a fixed point.
5. **Markdown report** — per-method tables, ablation deltas, CIs, methodology + limitations.

PM directive carried forward: **no brittle custom code, leverage proven OSS libraries.** Specifically:
- `ir_measures` for Recall@K / MRR / NDCG@10 (don't hand-roll).
- `scipy.stats.bootstrap` for confidence intervals (don't hand-roll).
- `pyyaml` (transitive via `python-frontmatter`) for the query-set schema.
- `jinja2` for the report template (one new dep).
- No `ranx` — `ir_measures` covers the metric set.
- No `pandas` — straight Python + numpy is enough for ~200-query corpora.

## Technical Design

### Query set schema

`eval/queries.yaml` (project root):

```yaml
# Metadata
corpus: decree                          # corpus identifier
description: "decree project file-path + concept queries v1"
created: 2026-05-12
author_note: "hand-authored against the decree corpus"
total_queries: 30

queries:
  - id: q001
    kind: file_path                     # file_path | concept
    query: "src/decree/index_db.py"
    relevant: [SPEC-01KT22NMRX176PCT00SKJ9G2AQ]
    grades:                             # optional; integer grade per decision
      SPEC-01KT22NMRX176PCT00SKJ9G2AQ: 3
    note: "exact file-path lookup"
    
  - id: q002
    kind: concept
    query: "how does decree validate path safety in governs entries?"
    relevant: [SPEC-01KT22NMRXFWNE61NSETKATHBA]
    grades:
      SPEC-01KT22NMRXFWNE61NSETKATHBA: 3
    note: "concept query — FTS-friendly"
    
  - id: q003
    kind: file_path
    query: "src/api/nonexistent.py"
    relevant: []                        # explicit empty = abstention is correct
    note: "abstention case — no decision governs this"
```

Schema validation via `pydantic` (already in deps): `QuerySet`, `Query`, `RelevanceGrade` models. Reject unknown keys, validate `relevant` is a list of strings matching the decree ID regex per type.

### Plugin interface

```python
# src/decree/eval/methods.py

class RetrievalMethod(Protocol):
    name: str                           # "keyword-v1", "hybrid-bm25-dense", etc.
    description: str                    # human-readable; surfaces in report
    
    def query(
        self,
        db: IndexDB,
        query: Query,
        *,
        k: int = 10,
    ) -> list[str]:                     # ordered list of decision_ids
        ...
```

v1 ships only one method: `keyword-v1` (wraps `commands.queries.why()` for `file_path` queries and a raw `decisions_fts MATCH` SQL query for `concept` queries — both already in the index). Future SPECs add more methods via Python entry-points OR by adding to a module-level registry in `src/decree/eval/methods.py`.

### `decree retrieval-eval` CLI

```
decree retrieval-eval [--queries PATH] [--method NAME]... [--baseline NAME]
                      [--output PATH] [--json] [--bootstrap-iterations N]
                      [--k K]... [--freeze] [--project PATH]
```

- `--queries PATH` — path to the YAML query set. Default `eval/queries.yaml`.
- `--method NAME` (repeatable) — run only these methods. Default: all registered.
- `--baseline NAME` — name of the method to use as comparison baseline. Default: `keyword-v1`.
- `--output PATH` — write markdown report here. Default: `docs/evaluation/<YYYY-MM-DD>.md`.
- `--json` — also emit machine-readable JSON to `<output>.json`.
- `--bootstrap-iterations N` — bootstrap resample count. Default 1000.
- `--k K` (repeatable) — K values for Recall@K. Default `[1, 3, 5, 10]`.
- `--freeze` — write the chosen baseline's scores to `eval/baselines/<method>.json` (overwrites). Without `--freeze`, the baseline is *read*; with `--freeze`, it's *re-snapshotted*. Default: read.
- `--project PATH` — operate against the project at PATH.

Exit codes:
- `0` — eval ran cleanly.
- `1` — at least one method failed (other methods still reported).
- `2` — config error (query set missing, no methods registered).

### Library: `ir_measures`

```python
import ir_measures
from ir_measures import nDCG, MRR, R

metrics_set = [R @ 1, R @ 3, R @ 5, R @ 10, MRR, nDCG @ 10]

# qrels: {query_id: {doc_id: relevance_grade}}
# run:   {query_id: {doc_id: score}}  — score is rank-inverse for plug-in methods
results = ir_measures.calc_aggregate(metrics_set, qrels, run)
```

`ir_measures` accepts the standard TREC qrels/run format we produce from our YAML loader. Per-query metric values are also accessible via `ir_measures.iter_calc()` — needed for bootstrap CIs.

For binary relevance (no `grades:` block), all relevant docs grade 1.

### Bootstrap confidence intervals

`scipy.stats.bootstrap` over the per-query metric values:

```python
from scipy.stats import bootstrap
import numpy as np

per_query_recall_at_10 = np.array([m.value for m in iter_results if str(m.measure) == "R@10"])
ci = bootstrap(
    (per_query_recall_at_10,),
    statistic=np.mean,
    n_resamples=args.bootstrap_iterations,
    confidence_level=0.95,
).confidence_interval
# → (low, high) reported alongside the mean
```

### Report shape

Generated via `jinja2` from `src/decree/eval/report_template.md.j2`. Sections:

1. **Header**: corpus name, query count, methods evaluated, generation timestamp.
2. **Summary table**: one row per method × metric, with mean + 95% CI.
3. **Per-method tables**: each method's score on every metric × K.
4. **Ablation table** (if `--baseline` set): delta vs baseline with CI overlap analysis.
5. **Methodology**: bootstrap iterations, K values, query-set source.
6. **Limitations**: corpus size, query coverage, labeler caveats — **required output**, not optional. Three minimum.
7. **Per-query breakdown** (`--verbose` only): each query's relevant set vs. each method's top-K.

### Baseline freeze

`keyword-v1` results saved to `eval/baselines/keyword-v1.json` on `--freeze` run. Subsequent runs without `--freeze` compare against the snapshot. The snapshot is intentionally a separate gate to prevent accidental overwriting of a baseline you wanted to ablate against.

### v1 query set composition

PM commits to **option (a)** from PRD-01KT22NMRSXYT95XE808VD8EV4's open question:

- **30 queries minimum for v1**, hand-authored against the decree corpus itself (~17 docs). Mix of `file_path` (15) and `concept` (15) queries. Includes ≥3 abstention cases (relevant: []).
- **The `eval/queries.yaml` file is shipped in-tree** (it's small, and visibility helps reviewers).
- **No external corpus in v1.** When PRD-01KT22NMRSXYT95XE808VD8EV4 evolves a real benchmark, a future SPEC adds an open-source ADR corpus (CNCF, C4 model project, etc.). Decree's own dogfood is enough to make the harness real and proves the methodology.

### Files touched

- **Create**: `src/decree/eval/__init__.py` — package marker.
- **Create**: `src/decree/eval/schema.py` — `QuerySet`, `Query`, `RelevanceGrade` pydantic models + loader.
- **Create**: `src/decree/eval/methods.py` — `RetrievalMethod` protocol + `KeywordBaseline`.
- **Create**: `src/decree/eval/runner.py` — orchestration: load queries → run methods → compute metrics + CIs → write report.
- **Create**: `src/decree/eval/report_template.md.j2` — jinja2 template.
- **Create**: `src/decree/commands/eval.py` — `eval_run(args)` CLI handler.
- **Modify**: `src/decree/cli.py` — register `decree retrieval-eval` subcommand.
- **Modify**: `pyproject.toml` — add `ir_measures>=0.3`, `scipy>=1.11`, `jinja2>=3`. (numpy is transitive via scipy and litellm.)
- **Create**: `eval/queries.yaml` — 30 hand-authored queries for the decree corpus.
- **Create**: `eval/baselines/.gitkeep` — directory placeholder; populated on first `--freeze` run.
- **Create**: `tests/test_eval.py` — unit + integration coverage.

### What this SPEC does NOT do

- **No new retrieval methods beyond `keyword-v1`** — that's SPEC-01KT22NMS0VWCTYPFPHP8M8V36's job (calibrated abstention) and future SPECs (hybrid, GraphRAG).
- **No active learning / online updates** — research-frontiers A.4; out of scope.
- **No automated label bootstrapping at scale** — v1 query set is hand-authored. LLM-bootstrap-then-human-verify tooling is a follow-up SPEC if/when the corpus grows.
- **No live LLM calls in CI** — same as SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S. Tests use fixture corpora.
- **No external corpus integration** — decree-only in v1.
- **No `pandas`** — straight Python + numpy.
- **No GUI / dashboard** — markdown report only.
- **No symbol-level eval** — file-level only.

## Testing Strategy

### Unit tests (`tests/test_eval.py`)

- **Schema validation — well-formed**: load a small YAML, assert `QuerySet` parses cleanly.
- **Schema validation — bad ID format**: query referencing `"FOO-1"` (no matching type) → ValidationError.
- **Schema validation — unknown key**: extra YAML key → ValidationError.
- **Schema validation — duplicate query id**: → ValidationError.
- **KeywordBaseline — file_path query**: query against fixture corpus, assert correct decision_ids returned in order.
- **KeywordBaseline — concept query (FTS)**: query against fixture corpus, assert FTS5 returns ranked decision_ids.
- **KeywordBaseline — empty result**: query that matches nothing → empty list.
- **Metric computation**: known qrels + known run → known Recall@1, MRR, nDCG@10 (compare against hand-computed values to ~3 decimal places).
- **Bootstrap CI**: 100-query synthetic dataset → CI is finite and (low ≤ mean ≤ high).
- **Report generation**: render template with a fixture run, assert all sections present.
- **Baseline freeze**: `--freeze` writes the JSON snapshot.
- **Baseline diff**: subsequent run without `--freeze` reports zero delta against itself.

### Integration tests

- **End-to-end against decree corpus**: minimal `eval/queries.yaml` (3 queries) + the decree corpus → `decree retrieval-eval` produces a report file. Assert exit 0 and report file exists.
- **End-to-end JSON output**: `--json` produces parseable JSON alongside markdown.

### Dogfood

- SPEC-01KT22NMRZXE5C42F6Z0ZY559A's `governs:` declares `["src/decree/eval/", "src/decree/commands/eval.py"]` after the directory exists.
- PM runs `decree retrieval-eval` against the v1 query set (30 queries) and records results in the SPEC-01KT22NMRZXE5C42F6Z0ZY559A completion report. Numbers go in the report; reviewers can scrutinise.

## v1 Acceptance Criteria

### Schema + loader

- [x] `eval/queries.yaml` exists with ≥30 hand-authored queries (≥15 file_path, ≥15 concept; ≥3 abstention cases).
- [x] `src/decree/eval/schema.py` defines pydantic `QuerySet`, `Query`, `RelevanceGrade` models.
- [x] Loader validates: unknown keys rejected; decision IDs match type regexes; per-query `id` unique.
- [x] Loader supports both binary (`relevant: [SPEC-01KT22NMRX176PCT00SKJ9G2AQ]`) and graded (`grades: {SPEC-01KT22NMRX176PCT00SKJ9G2AQ: 3}`) relevance.

### Plugin interface + baseline

- [x] `src/decree/eval/methods.py` defines `RetrievalMethod` protocol.
- [x] `KeywordBaseline` registered as `keyword-v1`; wraps `commands.queries.why()` for file_path queries and `decisions_fts` MATCH for concept queries.
- [x] Method-registration mechanism documented (module-level registry preferred for v1 simplicity).

### Metrics + CIs

- [x] `ir_measures` used for Recall@K / MRR / nDCG@10 (no hand-rolled metric code).
- [x] `scipy.stats.bootstrap` used for 95% CIs (no hand-rolled resampling).
- [x] Default K values: `[1, 3, 5, 10]`.
- [x] Default bootstrap iterations: 1000.

### CLI + report

- [x] `decree retrieval-eval` subcommand registered with all SPEC'd flags.
- [x] Markdown report rendered via jinja2 template; all 6 sections present.
- [x] Methodology + Limitations sections required (template enforces).
- [x] `--baseline keyword-v1` produces delta-vs-baseline table when both methods are run.
- [x] `eval/baselines/keyword-v1.json` written on `--freeze` run; subsequent runs read it.
- [x] `--json` emits machine-readable JSON alongside markdown.

### Dependencies

- [x] `ir_measures>=0.3`, `scipy>=1.11`, `jinja2>=3` added to `pyproject.toml`.
- [x] `uv tool install -e . --reinstall` picks up the new deps.

### Tests

- [x] `tests/test_eval.py` covers all unit + integration cases.
- [x] Full suite passes (459 baseline + new tests).

### Dogfood

- [x] SPEC-01KT22NMRZXE5C42F6Z0ZY559A governs declared after eval/ directory exists.
- [x] PM runs `decree retrieval-eval --freeze` against the 30-query v1 set; output captured in SPEC-01KT22NMRZXE5C42F6Z0ZY559A completion report.
- [x] The frozen `keyword-v1` baseline is committed to the repo at `eval/baselines/keyword-v1.json`.

## What this does NOT do (deferred)

- [ ] Calibrated abstention method — SPEC-01KT22NMS0VWCTYPFPHP8M8V36.
- [ ] Hybrid retrieval (BM25 + dense + structural) — future SPEC.
- [ ] GraphRAG community summarization — research-frontiers A.2.
- [ ] LLM-bootstrap-then-verify label tooling — future SPEC.
- [ ] External corpus integration (CNCF ADRs, C4 model project) — future SPEC.
- [ ] Live LLM calls in CI.
- [ ] Web dashboard for results — research-frontiers D.4.
- [ ] Symbol-level eval.

## References

- PRD-01KT22NMRSXYT95XE808VD8EV4 R3 — the requirement this SPEC implements.
- SPEC-01KT22NMRXWCS5TK5VC1FT6JER — `queries.why()` reused as the file_path retrieval engine.
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ — `decisions_fts` table reused for concept queries.
- `ir_measures` — https://github.com/terrierteam/ir_measures (MIT, the canonical Python IR-metrics library).
- `scipy.stats.bootstrap` — https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html
- Thakur et al., BEIR (2021) — the methodological reference for IR benchmark design.
- research-frontiers.md A.5 — full context on why this is the highest-leverage v1 deliverable.
