"""SPEC-01KT22NMRZXE5C42F6Z0ZY559A evaluation runner.

Pulls the whole loop together:

    1. Load the QuerySet (already validated).
    2. For each method x query, call `method.query(db, query, k=max_k)` and
       form a TREC-style `run` dict (decision_id → descending score).
    3. Build the qrels dict from each query's `effective_grades()`.
    4. `ir_measures.calc_aggregate` for the headline numbers.
    5. `ir_measures.iter_calc` + `scipy.stats.bootstrap` for 95% CIs.
    6. Render the markdown report via jinja2.

The runner is *pure*: it takes data in, returns a `RunReport` out. The
CLI handler (`commands.eval.eval_run`) is responsible for writing files.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ir_measures
import numpy as np
from ir_measures import MRR, R, nDCG
from jinja2 import Environment, FileSystemLoader, select_autoescape
from scipy.stats import bootstrap

from decree.eval.methods import METHODS, RetrievalMethod
from decree.eval.schema import QuerySet
from decree.index_db import IndexDB

# ── Data classes ────────────────────────────────────────────


@dataclass(frozen=True)
class MetricStat:
    """Mean + 95% bootstrap CI for one (method, metric) pair."""

    metric: str
    mean: float
    ci_low: float
    ci_high: float
    n: int  # query count contributing


@dataclass(frozen=True)
class MethodResult:
    """Per-method results: aggregate metrics, per-query metric values, the run."""

    method_name: str
    description: str
    stats: list[MetricStat]
    per_query: dict[str, dict[str, float]]  # {query_id: {metric: value}}
    run: dict[str, dict[str, float]]  # {query_id: {decision_id: score}}
    error: str | None = None  # populated when the whole method failed


@dataclass(frozen=True)
class RunReport:
    """End-to-end evaluation result."""

    corpus: str
    query_count: int
    methods: list[MethodResult]
    qrels: dict[str, dict[str, int]]
    k_values: list[int]
    bootstrap_iterations: int
    generated_at: str
    baseline_name: str | None = None
    baseline_snapshot: dict[str, Any] | None = None
    ablation: list[dict[str, Any]] = field(default_factory=list)


# ── Metric set ──────────────────────────────────────────────


def metrics_for_ks(ks: list[int]) -> list[Any]:
    """Build the ir_measures metric set: Recall@K for each k, plus MRR + nDCG@10."""
    measures: list[Any] = [R @ k for k in ks]
    measures.append(MRR)
    measures.append(nDCG @ 10)
    return measures


# ── qrels + run builders ───────────────────────────────────


def build_qrels(qs: QuerySet) -> dict[str, dict[str, int]]:
    """{query_id → {decision_id → relevance grade}}.

    Queries with no relevant docs are *included* with an empty inner dict
    so ir_measures still sees them and Recall@K is well-defined (returns 0 if
    no relevant docs exist, by convention — but we filter abstention queries
    out of metric calc to avoid divide-by-zero noise; see `run_evaluation`).
    """
    qrels: dict[str, dict[str, int]] = {}
    for q in qs.queries:
        qrels[q.id] = q.effective_grades()
    return qrels


def build_run(
    method: RetrievalMethod,
    db: IndexDB,
    qs: QuerySet,
    *,
    max_k: int,
) -> dict[str, dict[str, float]]:
    """Score = rank-inverse so ir_measures orders results correctly."""
    run: dict[str, dict[str, float]] = {}
    for q in qs.queries:
        ids = method.query(db, q, k=max_k)
        # Assign descending scores: rank 0 → max_k, rank 1 → max_k-1 … so the
        # first-returned doc has the highest score. ir_measures sorts by score
        # descending.
        scores: dict[str, float] = {}
        for rank, did in enumerate(ids):
            scores[did] = float(max_k - rank)
        run[q.id] = scores
    return run


# ── Bootstrap CI ────────────────────────────────────────────


def _bootstrap_ci(values: list[float], *, n_resamples: int) -> tuple[float, float]:
    """Return (low, high) 95% CI via scipy.stats.bootstrap.

    Falls back to (mean, mean) for n < 2, where bootstrap is undefined.
    """
    if len(values) < 2:
        m = float(np.mean(values)) if values else 0.0
        return (m, m)
    arr = np.array(values, dtype=float)
    res = bootstrap(
        (arr,),
        statistic=np.mean,
        n_resamples=n_resamples,
        confidence_level=0.95,
        method="percentile",
        random_state=42,
    )
    ci = res.confidence_interval
    return (float(ci.low), float(ci.high))


# ── Core runner ─────────────────────────────────────────────


def run_evaluation(
    *,
    db: IndexDB,
    query_set: QuerySet,
    methods: list[RetrievalMethod],
    k_values: list[int] | None = None,
    bootstrap_iterations: int = 1000,
    baseline_name: str | None = "keyword-v1",
    baseline_snapshot: dict[str, Any] | None = None,
) -> RunReport:
    """Run every method x every query and assemble a RunReport."""
    k_values = sorted(set(k_values or [1, 3, 5, 10]))
    measures = metrics_for_ks(k_values)
    measure_str_to_metric_name = {str(m): str(m) for m in measures}

    qrels = build_qrels(query_set)
    # Filter out abstention queries (relevant: []) from metric calc — ir_measures
    # treats them as 0/undefined and inflates noise. We still report them in the
    # per-query breakdown when --verbose is set.
    scoring_qrels = {qid: rels for qid, rels in qrels.items() if rels}

    method_results: list[MethodResult] = []
    for method in methods:
        try:
            run = build_run(method, db, query_set, max_k=max(k_values))
            scoring_run = {qid: docs for qid, docs in run.items() if qid in scoring_qrels}

            # Per-query metric values (needed for bootstrap CIs).
            per_query: dict[str, dict[str, float]] = {qid: {} for qid in scoring_qrels}
            per_metric_values: dict[str, list[float]] = {str(m): [] for m in measures}
            for metric_obj in ir_measures.iter_calc(measures, scoring_qrels, scoring_run):
                key = str(metric_obj.measure)
                per_metric_values[key].append(float(metric_obj.value))
                per_query[metric_obj.query_id][key] = float(metric_obj.value)

            stats: list[MetricStat] = []
            for m_str in (str(x) for x in measures):
                values = per_metric_values.get(m_str, [])
                if values:
                    mean = float(np.mean(values))
                    low, high = _bootstrap_ci(values, n_resamples=bootstrap_iterations)
                else:
                    mean, low, high = 0.0, 0.0, 0.0
                stats.append(
                    MetricStat(
                        metric=measure_str_to_metric_name[m_str],
                        mean=mean,
                        ci_low=low,
                        ci_high=high,
                        n=len(values),
                    )
                )

            method_results.append(
                MethodResult(
                    method_name=method.name,
                    description=method.description,
                    stats=stats,
                    per_query=per_query,
                    run=run,
                    error=None,
                )
            )
        except Exception as e:
            method_results.append(
                MethodResult(
                    method_name=method.name,
                    description=method.description,
                    stats=[],
                    per_query={},
                    run={},
                    error=f"{type(e).__name__}: {e}",
                )
            )

    # Ablation table: per-metric delta of each non-baseline method vs baseline.
    ablation: list[dict[str, Any]] = []
    baseline_result = next((mr for mr in method_results if mr.method_name == baseline_name), None)
    if baseline_result is not None:
        baseline_by_metric = {s.metric: s for s in baseline_result.stats}
        for mr in method_results:
            if mr.method_name == baseline_name or mr.error:
                continue
            for s in mr.stats:
                base = baseline_by_metric.get(s.metric)
                if base is None:
                    continue
                ablation.append(
                    {
                        "method": mr.method_name,
                        "metric": s.metric,
                        "mean": s.mean,
                        "baseline_mean": base.mean,
                        "delta": s.mean - base.mean,
                        "ci_overlaps": not (s.ci_low > base.ci_high or base.ci_low > s.ci_high),
                    }
                )

    return RunReport(
        corpus=query_set.corpus,
        query_count=len(query_set.queries),
        methods=method_results,
        qrels=qrels,
        k_values=k_values,
        bootstrap_iterations=bootstrap_iterations,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        baseline_name=baseline_name,
        baseline_snapshot=baseline_snapshot,
        ablation=ablation,
    )


# ── Report rendering ────────────────────────────────────────


def _template_env() -> Environment:
    template_dir = Path(__file__).parent
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(disabled_extensions=("md", "j2")),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_markdown(report: RunReport, *, verbose: bool = False) -> str:
    env = _template_env()
    tmpl = env.get_template("report_template.md.j2")
    return tmpl.render(
        report=report,
        verbose=verbose,
        fmt=_fmt,
    )


def _fmt(value: float, *, places: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value).lower()
    return f"{value:.{places}f}"


def report_to_json(report: RunReport) -> str:
    payload = {
        "corpus": report.corpus,
        "query_count": report.query_count,
        "k_values": report.k_values,
        "bootstrap_iterations": report.bootstrap_iterations,
        "generated_at": report.generated_at,
        "baseline_name": report.baseline_name,
        "baseline_snapshot": report.baseline_snapshot,
        "qrels": report.qrels,
        "methods": [
            {
                "name": mr.method_name,
                "description": mr.description,
                "error": mr.error,
                "stats": [asdict(s) for s in mr.stats],
                "per_query": mr.per_query,
                "run": mr.run,
            }
            for mr in report.methods
        ],
        "ablation": report.ablation,
    }
    return json.dumps(payload, indent=2, sort_keys=False)


# ── Baseline freeze / read ──────────────────────────────────


def freeze_baseline(method_result: MethodResult, path: Path) -> None:
    """Persist a method's per-query scores to JSON for future comparison."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method_name": method_result.method_name,
        "description": method_result.description,
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "stats": [asdict(s) for s in method_result.stats],
        "per_query": method_result.per_query,
        "run": method_result.run,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))


def read_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ── Convenience: registered methods picker ─────────────────


def select_methods(names: list[str] | None) -> list[RetrievalMethod]:
    """Pick methods from the registry. If `names` is None, return all."""
    if names is None:
        return list(METHODS.values())
    out: list[RetrievalMethod] = []
    missing: list[str] = []
    for n in names:
        if n not in METHODS:
            missing.append(n)
        else:
            out.append(METHODS[n])
    if missing:
        raise KeyError(f"unknown method(s): {', '.join(missing)}. Registered: {', '.join(sorted(METHODS))}")
    return out


# Re-export for the helper that ablates a single per-query series.
__all__ = [
    "MethodResult",
    "MetricStat",
    "RunReport",
    "build_qrels",
    "build_run",
    "freeze_baseline",
    "metrics_for_ks",
    "read_baseline",
    "render_markdown",
    "report_to_json",
    "run_evaluation",
    "select_methods",
]


# Keep `statistics` import in case future ablation tables want stdev etc.
_ = statistics
