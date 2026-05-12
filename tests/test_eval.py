"""SPEC-012 — evaluation-harness tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from random import Random

import pytest

from decree.eval.methods import KeywordBaseline, METHODS
from decree.eval.runner import (
    MethodResult,
    MetricStat,
    _bootstrap_ci,
    build_qrels,
    build_run,
    freeze_baseline,
    metrics_for_ks,
    read_baseline,
    render_markdown,
    report_to_json,
    run_evaluation,
    select_methods,
)
from decree.eval.schema import (
    DECISION_ID_RE,
    Query,
    QuerySet,
    load_query_set,
)
from decree.index_db import IndexDB, default_db_path
from tests.test_queries import _rebuild_index, _write_basic_corpus  # reuse fixture builder


# ── Helpers ────────────────────────────────────────────────


def _build_db(tmp_path: Path, monkeypatch) -> IndexDB:
    _write_basic_corpus(tmp_path)
    return _rebuild_index(tmp_path, monkeypatch)


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


# ── Schema validation tests ────────────────────────────────


class TestSchemaValidation:
    def test_well_formed(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
description: ok
queries:
  - id: q1
    kind: file_path
    query: src/decree/index_db.py
    relevant: [SPEC-003]
  - id: q2
    kind: concept
    query: provenance index
    relevant: [SPEC-003]
    grades: {SPEC-003: 3}
""",
        )
        qs = load_query_set(p)
        assert qs.corpus == "decree"
        assert len(qs.queries) == 2
        assert qs.queries[0].kind == "file_path"
        assert qs.queries[1].grades == {"SPEC-003": 3}
        # effective_grades for binary returns grade=1; for graded returns the dict.
        assert qs.queries[0].effective_grades() == {"SPEC-003": 1}
        assert qs.queries[1].effective_grades() == {"SPEC-003": 3}

    def test_bad_decision_id(self, tmp_path: Path):
        # Malformed: lowercase prefix breaks the `^[A-Z]+-\d+$` regex.
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries:
  - id: q1
    kind: file_path
    query: foo
    relevant: [spec-1]
""",
        )
        with pytest.raises(Exception) as exc:
            load_query_set(p)
        assert "spec-1" in str(exc.value)

    def test_bad_decision_id_no_dash(self, tmp_path: Path):
        # No dash: SPEC001 — doesn't match the regex.
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries:
  - id: q1
    kind: file_path
    query: foo
    relevant: [SPEC001]
""",
        )
        with pytest.raises(Exception) as exc:
            load_query_set(p)
        assert "SPEC001" in str(exc.value)

    def test_unknown_key(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries:
  - id: q1
    kind: file_path
    query: foo
    relevant: [SPEC-001]
    bogus_key: nope
""",
        )
        with pytest.raises(Exception):
            load_query_set(p)

    def test_duplicate_id(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries:
  - id: q1
    kind: file_path
    query: foo
    relevant: []
  - id: q1
    kind: concept
    query: bar
    relevant: []
""",
        )
        with pytest.raises(Exception) as exc:
            load_query_set(p)
        assert "duplicate" in str(exc.value).lower()

    def test_empty_queries(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries: []
""",
        )
        with pytest.raises(Exception):
            load_query_set(p)

    def test_total_queries_mismatch(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
total_queries: 99
queries:
  - id: q1
    kind: file_path
    query: foo
    relevant: []
""",
        )
        with pytest.raises(Exception) as exc:
            load_query_set(p)
        assert "total_queries" in str(exc.value)

    def test_decision_id_regex(self):
        assert DECISION_ID_RE.match("SPEC-001")
        assert DECISION_ID_RE.match("ADR-0001")
        assert DECISION_ID_RE.match("PRD-003")
        assert not DECISION_ID_RE.match("spec-001")
        assert not DECISION_ID_RE.match("SPEC001")

    def test_invalid_kind(self, tmp_path: Path):
        p = _write_yaml(
            tmp_path / "qs.yaml",
            """
corpus: decree
queries:
  - id: q1
    kind: regex
    query: foo
    relevant: []
""",
        )
        with pytest.raises(Exception):
            load_query_set(p)


# ── KeywordBaseline tests ───────────────────────────────────


class TestKeywordBaseline:
    def test_file_path_query(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        baseline = KeywordBaseline()
        q = Query(id="q", kind="file_path", query="src/foo.py", relevant=["SPEC-001"])
        result = baseline.query(db, q, k=5)
        assert result == ["SPEC-001"]

    def test_concept_query_fts(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        baseline = KeywordBaseline()
        # _write_basic_corpus's SPEC mentions "Overview" + "Prose" — search a body token.
        q = Query(id="q", kind="concept", query="Overview", relevant=["SPEC-001"])
        result = baseline.query(db, q, k=5)
        # FTS hits on the SPEC's body — SPEC-001 must appear in the ranked results.
        assert "SPEC-001" in result

    def test_empty_concept_result(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        baseline = KeywordBaseline()
        q = Query(id="q", kind="concept", query="kubernetes-operator-helm-chart", relevant=[])
        result = baseline.query(db, q, k=5)
        assert result == []

    def test_empty_file_path_result(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        baseline = KeywordBaseline()
        q = Query(id="q", kind="file_path", query="src/nonexistent/whatever.py", relevant=[])
        assert baseline.query(db, q, k=5) == []

    def test_registry_has_keyword_v1(self):
        assert "keyword-v1" in METHODS
        assert METHODS["keyword-v1"].name == "keyword-v1"


# ── Metric / bootstrap tests ───────────────────────────────


class TestMetrics:
    def test_metrics_for_ks(self):
        ms = metrics_for_ks([1, 3, 5])
        strs = [str(m) for m in ms]
        assert "R@1" in strs
        assert "R@3" in strs
        assert "R@5" in strs
        assert "RR" in strs  # MRR renders as RR
        assert "nDCG@10" in strs

    def test_metric_computation_hand_computed(self, tmp_path: Path, monkeypatch):
        """Run with a synthetic qrels + run; check R@1, R@3, MRR vs hand math."""
        import ir_measures
        from ir_measures import MRR, R, nDCG

        # 2 queries.
        # Q1: relevant = {d1}, run = {d2:3, d1:2, d3:1}  → rank of d1 is 2.
        #     R@1 = 0, R@3 = 1, MRR = 1/2.
        # Q2: relevant = {d4, d5}, run = {d4:3, d5:2}    → ranks 1, 2.
        #     R@1 = 1/2 (one of two relevant retrieved), R@3 = 1.0, MRR = 1.
        qrels = {"q1": {"d1": 1}, "q2": {"d4": 1, "d5": 1}}
        run = {
            "q1": {"d2": 3.0, "d1": 2.0, "d3": 1.0},
            "q2": {"d4": 3.0, "d5": 2.0},
        }
        agg = ir_measures.calc_aggregate([R @ 1, R @ 3, MRR, nDCG @ 10], qrels, run)
        # Mean of R@1: (0 + 0.5) / 2 = 0.25
        assert agg[R @ 1] == pytest.approx(0.25, abs=1e-6)
        # Mean of R@3: (1 + 1) / 2 = 1.0
        assert agg[R @ 3] == pytest.approx(1.0, abs=1e-6)
        # Mean of MRR: (1/2 + 1) / 2 = 0.75
        assert agg[MRR] == pytest.approx(0.75, abs=1e-6)

    def test_bootstrap_ci_synthetic(self):
        rng = Random(123)
        values = [rng.random() for _ in range(100)]
        low, high = _bootstrap_ci(values, n_resamples=200)
        mean = sum(values) / len(values)
        assert low <= mean <= high
        assert low > 0.0 and high < 1.0  # bounded by data
        assert isinstance(low, float) and isinstance(high, float)
        # finite
        import math

        assert math.isfinite(low) and math.isfinite(high)

    def test_bootstrap_ci_single_value(self):
        low, high = _bootstrap_ci([0.5], n_resamples=200)
        assert low == 0.5 and high == 0.5

    def test_bootstrap_ci_empty(self):
        low, high = _bootstrap_ci([], n_resamples=200)
        assert low == 0.0 and high == 0.0


# ── Runner integration ─────────────────────────────────────


class TestRunner:
    def test_run_evaluation_against_basic_corpus(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        qs = QuerySet(
            corpus="basic",
            queries=[
                Query(id="q1", kind="file_path", query="src/foo.py", relevant=["SPEC-001"]),
                Query(id="q2", kind="concept", query="Overview", relevant=["SPEC-001"]),
                Query(id="q3", kind="file_path", query="src/missing.py", relevant=[]),
            ],
        )
        report = run_evaluation(
            db=db,
            query_set=qs,
            methods=[KeywordBaseline()],
            k_values=[1, 3, 5],
            bootstrap_iterations=100,
        )
        assert report.query_count == 3
        assert len(report.methods) == 1
        mr = report.methods[0]
        assert mr.error is None
        # q1 must return SPEC-001 at rank 0 → R@1 = 1
        assert mr.per_query["q1"]["R@1"] == pytest.approx(1.0)
        # abstention q3 must be excluded from per_query (filtered before iter_calc)
        assert "q3" not in mr.per_query
        # Stats are populated for every metric in metrics_for_ks.
        metrics = {s.metric for s in mr.stats}
        assert {"R@1", "R@3", "R@5", "RR", "nDCG@10"} <= metrics

    def test_select_methods_unknown_raises(self):
        with pytest.raises(KeyError):
            select_methods(["definitely-not-a-method"])

    def test_select_methods_default_returns_all(self):
        ms = select_methods(None)
        names = [m.name for m in ms]
        assert "keyword-v1" in names


# ── Report / template ───────────────────────────────────────


class TestReport:
    def _make_report(self, tmp_path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        qs = QuerySet(
            corpus="basic",
            queries=[
                Query(id="q1", kind="file_path", query="src/foo.py", relevant=["SPEC-001"]),
                Query(id="q2", kind="concept", query="Overview", relevant=["SPEC-001"]),
            ],
        )
        return run_evaluation(
            db=db,
            query_set=qs,
            methods=[KeywordBaseline()],
            k_values=[1, 3],
            bootstrap_iterations=100,
        )

    def test_markdown_has_all_sections(self, tmp_path: Path, monkeypatch):
        report = self._make_report(tmp_path, monkeypatch)
        md = render_markdown(report)
        # 6 mandatory section headers per SPEC.
        for header in [
            "# Retrieval Evaluation",
            "## Summary",
            "## Per-method tables",
            "## Ablation vs baseline",
            "## Methodology",
            "## Limitations",
            "## Per-query breakdown",
        ]:
            assert header in md, f"missing section: {header}"

    def test_limitations_section_has_at_least_three(self, tmp_path: Path, monkeypatch):
        report = self._make_report(tmp_path, monkeypatch)
        md = render_markdown(report)
        limitations = md.split("## Limitations")[1].split("##")[0]
        # numbered list items "1." "2." "3."
        assert "1." in limitations and "2." in limitations and "3." in limitations

    def test_json_round_trip(self, tmp_path: Path, monkeypatch):
        report = self._make_report(tmp_path, monkeypatch)
        payload = json.loads(report_to_json(report))
        assert payload["corpus"] == "basic"
        assert payload["query_count"] == 2
        assert payload["k_values"] == [1, 3]
        assert payload["methods"][0]["name"] == "keyword-v1"


# ── Baseline freeze + read ──────────────────────────────────


class TestBaseline:
    def test_freeze_and_read(self, tmp_path: Path, monkeypatch):
        db = _build_db(tmp_path, monkeypatch)
        qs = QuerySet(
            corpus="basic",
            queries=[
                Query(id="q1", kind="file_path", query="src/foo.py", relevant=["SPEC-001"]),
            ],
        )
        report = run_evaluation(
            db=db,
            query_set=qs,
            methods=[KeywordBaseline()],
            k_values=[1, 3],
            bootstrap_iterations=100,
        )
        target = report.methods[0]
        snap_path = tmp_path / "eval" / "baselines" / "keyword-v1.json"
        freeze_baseline(target, snap_path)
        assert snap_path.exists()
        # read back round-trips the stats list verbatim
        snap = read_baseline(snap_path)
        assert snap is not None
        assert snap["method_name"] == "keyword-v1"
        assert [s["metric"] for s in snap["stats"]] == [s.metric for s in target.stats]
        assert read_baseline(tmp_path / "missing.json") is None


# ── End-to-end CLI integration ──────────────────────────────


def _run_cli(args: list[str]) -> int:
    from decree.cli import main

    sys_argv = sys.argv
    sys.argv = ["decree", *args]
    try:
        return main()
    finally:
        sys.argv = sys_argv


class TestCli:
    def _setup(self, tmp_path: Path, monkeypatch) -> Path:
        _write_basic_corpus(tmp_path)
        _rebuild_index(tmp_path, monkeypatch)
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        (eval_dir / "queries.yaml").write_text(
            """
corpus: basic
queries:
  - id: q1
    kind: file_path
    query: src/foo.py
    relevant: [SPEC-001]
  - id: q2
    kind: concept
    query: Overview
    relevant: [SPEC-001]
  - id: q3
    kind: file_path
    query: src/missing.py
    relevant: []
"""
        )
        return tmp_path

    def test_retrieval_eval_writes_report(self, tmp_path: Path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch)
        output = tmp_path / "out.md"
        rc = _run_cli(
            [
                "retrieval-eval",
                "--queries",
                str(tmp_path / "eval" / "queries.yaml"),
                "--output",
                str(output),
                "--bootstrap-iterations",
                "50",
                "--project",
                str(tmp_path),
            ]
        )
        assert rc == 0
        assert output.exists()
        md = output.read_text()
        assert "Retrieval Evaluation" in md
        assert "keyword-v1" in md

    def test_retrieval_eval_json_output(self, tmp_path: Path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        output = tmp_path / "out.md"
        rc = _run_cli(
            [
                "retrieval-eval",
                "--queries",
                str(tmp_path / "eval" / "queries.yaml"),
                "--output",
                str(output),
                "--json",
                "--bootstrap-iterations",
                "50",
                "--project",
                str(tmp_path),
            ]
        )
        assert rc == 0
        json_path = output.with_suffix(output.suffix + ".json")
        assert json_path.exists()
        payload = json.loads(json_path.read_text())
        assert payload["corpus"] == "basic"

    def test_retrieval_eval_missing_queries_exit_2(self, tmp_path: Path, monkeypatch):
        # Set up corpus + index, but no eval/queries.yaml.
        _write_basic_corpus(tmp_path)
        _rebuild_index(tmp_path, monkeypatch)
        rc = _run_cli(
            [
                "retrieval-eval",
                "--queries",
                str(tmp_path / "does-not-exist.yaml"),
                "--project",
                str(tmp_path),
            ]
        )
        assert rc == 2

    def test_retrieval_eval_freeze_then_read(self, tmp_path: Path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        output = tmp_path / "out.md"
        rc = _run_cli(
            [
                "retrieval-eval",
                "--queries",
                str(tmp_path / "eval" / "queries.yaml"),
                "--output",
                str(output),
                "--freeze",
                "--bootstrap-iterations",
                "50",
                "--project",
                str(tmp_path),
            ]
        )
        assert rc == 0
        snap = tmp_path / "eval" / "baselines" / "keyword-v1.json"
        assert snap.exists()
        # Second run, without --freeze, picks up the snapshot.
        rc2 = _run_cli(
            [
                "retrieval-eval",
                "--queries",
                str(tmp_path / "eval" / "queries.yaml"),
                "--output",
                str(output),
                "--bootstrap-iterations",
                "50",
                "--project",
                str(tmp_path),
            ]
        )
        assert rc2 == 0
