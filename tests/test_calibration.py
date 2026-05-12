"""SPEC-013 — confidence gates + calibration tests."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from decree.eval.calibration import (
    Calibration,
    _pick_threshold,
    calibrate_method,
    read_calibration,
    save_calibration,
)
from decree.eval.gates import (
    ALL_GATES,
    GateSignal,
    RetrievalRow,
    authorship_gate,
    composite,
    compute_signals,
    coverage_gate,
    dominance_gate,
    enrich_rows,
    hedge_phrase_gate,
    identifier_citation_gate,
    recency_gate,
    status_gate,
)
from decree.eval.methods import KeywordBaseline, KeywordCalibrated
from decree.eval.schema import Query, QuerySet
from decree.index_db import IndexDB, default_db_path

from tests.test_queries import _rebuild_index, _write_basic_corpus


# ── Helpers ────────────────────────────────────────────────


def _basic_db(tmp_path: Path, monkeypatch) -> IndexDB:
    _write_basic_corpus(tmp_path)
    return _rebuild_index(tmp_path, monkeypatch)


def _row(
    decision_id: str = "SPEC-001",
    rank: int = 0,
    raw_score: float = 5.0,
    title: str = "Example",
    status: str = "implemented",
    date_str: str | None = None,
    body: str = "",
    governs_paths: tuple[str, ...] = (),
    doc_path: str = "",
) -> RetrievalRow:
    if date_str is None:
        date_str = date.today().isoformat()
    return RetrievalRow(
        decision_id=decision_id,
        rank=rank,
        raw_score=raw_score,
        title=title,
        status=status,
        date_str=date_str,
        body=body,
        governs_paths=governs_paths,
        doc_path=doc_path,
    )


def _q(query_str: str = "src/foo.py", kind: str = "file_path", *, relevant: list[str] | None = None) -> Query:
    return Query(id="q-test", kind=kind, query=query_str, relevant=relevant or [])


# ── Per-gate tests ─────────────────────────────────────────


class TestDominanceGate:
    def test_single_candidate_returns_one(self):
        sig = dominance_gate(_q(), [_row(raw_score=10.0)], db=None)  # type: ignore[arg-type]
        assert sig.name == "dominance"
        assert sig.score == 1.0

    def test_clean_dominance(self):
        rows = [_row(raw_score=10.0), _row(decision_id="SPEC-002", rank=1, raw_score=2.0)]
        sig = dominance_gate(_q(), rows, db=None)  # type: ignore[arg-type]
        # 10/2 = 5 → saturates at 1.0
        assert sig.score == 1.0

    def test_close_race(self):
        rows = [_row(raw_score=10.0), _row(decision_id="SPEC-002", rank=1, raw_score=9.0)]
        sig = dominance_gate(_q(), rows, db=None)  # type: ignore[arg-type]
        # 10/9 / 2 ≈ 0.55
        assert 0.5 < sig.score < 0.6

    def test_empty(self):
        sig = dominance_gate(_q(), [], db=None)  # type: ignore[arg-type]
        assert sig.score == 0.0


class TestIdentifierCitationGate:
    def test_full_hit(self):
        rows = [
            _row(
                title="SPEC-003 SQLite Provenance Index",
                governs_paths=("src/decree/index_db.py",),
            )
        ]
        sig = identifier_citation_gate(_q("src/decree/index_db.py"), rows, db=None)  # type: ignore[arg-type]
        # tokens: ['src','decree','index','db','py'] — all should be in title+governs
        assert sig.score == 1.0

    def test_partial_hit(self):
        rows = [
            _row(title="something unrelated", governs_paths=("src/decree/other.py",))
        ]
        sig = identifier_citation_gate(_q("src/decree/index_db.py"), rows, db=None)  # type: ignore[arg-type]
        # tokens: src, decree, index, db, py — index/db missing from haystack
        assert 0 < sig.score < 1.0

    def test_no_hit(self):
        rows = [_row(title="zzzz qqqq", governs_paths=("zzzz/qqqq",))]
        sig = identifier_citation_gate(_q("src/decree/index_db.py"), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 0.0


class TestHedgePhraseGate:
    def test_clean_body(self):
        rows = [_row(body="This SPEC is definitive and complete.")]
        sig = hedge_phrase_gate(_q(), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 1.0

    def test_hedged_body(self):
        rows = [_row(body="We might possibly TBD this; consider unclear options.")]
        sig = hedge_phrase_gate(_q(), rows, db=None)  # type: ignore[arg-type]
        # 5 hedge terms → 0
        assert sig.score == 0.0

    def test_empty_body_fails_open(self):
        rows = [_row(body="")]
        sig = hedge_phrase_gate(_q(), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 1.0


class TestStatusGate:
    def test_terminal_success(self):
        sig = status_gate(_q(), [_row(status="implemented")], db=None)  # type: ignore[arg-type]
        assert sig.score == 1.0
        sig2 = status_gate(_q(), [_row(status="accepted")], db=None)  # type: ignore[arg-type]
        assert sig2.score == 1.0

    def test_warn_status(self):
        sig = status_gate(_q(), [_row(status="deprecated")], db=None)  # type: ignore[arg-type]
        assert sig.score == 0.0
        sig2 = status_gate(_q(), [_row(status="superseded")], db=None)  # type: ignore[arg-type]
        assert sig2.score == 0.0

    def test_active_intermediate(self):
        sig = status_gate(_q(), [_row(status="draft")], db=None)  # type: ignore[arg-type]
        assert sig.score == 0.5


class TestRecencyGate:
    def test_today(self):
        sig = recency_gate(_q(), [_row(date_str=date.today().isoformat())], db=None)  # type: ignore[arg-type]
        assert sig.score == 1.0

    def test_old(self):
        long_ago = (date.today() - timedelta(days=600)).isoformat()
        sig = recency_gate(_q(), [_row(date_str=long_ago)], db=None)  # type: ignore[arg-type]
        # 600 / 540 > 1 → clamp to 0
        assert sig.score == 0.0

    def test_midrange(self):
        d = (date.today() - timedelta(days=270)).isoformat()
        sig = recency_gate(_q(), [_row(date_str=d)], db=None)  # type: ignore[arg-type]
        # 1 - 270/540 = 0.5
        assert abs(sig.score - 0.5) < 0.01

    def test_unparseable(self):
        sig = recency_gate(_q(), [_row(date_str="not-a-date")], db=None)  # type: ignore[arg-type]
        assert sig.score == 0.5


class TestCoverageGate:
    def test_exact_match(self):
        rows = [_row(governs_paths=("src/foo.py",))]
        sig = coverage_gate(_q("src/foo.py"), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 1.0

    def test_prefix_match(self):
        rows = [_row(governs_paths=("src/api/",))]
        sig = coverage_gate(_q("src/api/handler.py"), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 0.5

    def test_no_match(self):
        rows = [_row(governs_paths=("src/other/",))]
        sig = coverage_gate(_q("src/api/handler.py"), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 0.1

    def test_concept_query_neutral(self):
        rows = [_row(governs_paths=("src/foo.py",))]
        sig = coverage_gate(_q("some concept", kind="concept"), rows, db=None)  # type: ignore[arg-type]
        assert sig.score == 0.5


class TestAuthorshipGate:
    def test_no_git_fails_open(self, tmp_path: Path):
        # Build a tmp IndexDB outside any git repo.
        db_path = tmp_path / "x.sqlite"
        db = IndexDB(db_path)
        db.init_schema()
        rows = [_row(doc_path="decree/spec/001-test.md")]
        sig = authorship_gate(_q(), rows, db)
        assert sig.score == 0.5  # fail-open


# ── Composite ──────────────────────────────────────────────


class TestComposite:
    def test_all_ones(self):
        sigs = [GateSignal(f"g{i}", 1.0) for i in range(7)]
        assert abs(composite(sigs) - 1.0) < 1e-9

    def test_veto(self):
        sigs = [GateSignal("a", 1.0), GateSignal("b", 1.0), GateSignal("c", 0.0)]
        # 0 collapses geometric mean toward 0. With eps=1e-6 over 3 signals,
        # composite = (1e-6)^(1/3) ≈ 0.01. The key property: 1+ orders of
        # magnitude below a "healthy" composite (~1.0).
        result = composite(sigs)
        assert result <= 0.02
        healthy = composite([GateSignal("a", 1.0), GateSignal("b", 1.0), GateSignal("c", 1.0)])
        assert result < healthy / 10

    def test_uniform_weights_default(self):
        sigs = [GateSignal("a", 0.5), GateSignal("b", 0.5)]
        assert abs(composite(sigs) - 0.5) < 1e-9

    def test_custom_weights(self):
        sigs = [GateSignal("a", 0.5), GateSignal("b", 1.0)]
        # weight b heavily → composite skews toward 1
        comp_heavy_b = composite(sigs, weights={"a": 1.0, "b": 10.0})
        comp_uniform = composite(sigs)
        assert comp_heavy_b > comp_uniform

    def test_empty(self):
        assert composite([]) == 0.0


# ── _pick_threshold ────────────────────────────────────────


class TestPickThreshold:
    def test_meets_precision(self):
        scores = [0.2, 0.4, 0.6, 0.8, 0.9, 0.95]
        labels = [0, 0, 1, 1, 1, 1]
        # target 1.0 → only τ above 0.4 keeps purely positive predictions
        tau, p, c = _pick_threshold(scores, labels, target_precision=1.0)
        assert p == 1.0
        assert c > 0
        assert tau >= 0.4

    def test_target_monotonic(self):
        scores = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
        labels = [0, 0, 1, 1, 1, 1]
        tau_lo, _, _ = _pick_threshold(scores, labels, target_precision=0.5)
        tau_hi, _, _ = _pick_threshold(scores, labels, target_precision=0.9)
        # Higher target → at least as high a threshold.
        assert tau_hi >= tau_lo


# ── enrich_rows ────────────────────────────────────────────


class TestEnrichRows:
    def test_pulls_body_and_governs(self, tmp_path: Path, monkeypatch):
        db = _basic_db(tmp_path, monkeypatch)
        rows = enrich_rows(db, ["SPEC-001"])
        assert len(rows) == 1
        r = rows[0]
        assert r.title.startswith("Test SPEC") or "SPEC" in r.title
        assert "src/foo.py" in r.governs_paths
        assert r.status == "implemented"

    def test_empty_list(self, tmp_path: Path, monkeypatch):
        db = _basic_db(tmp_path, monkeypatch)
        assert enrich_rows(db, []) == []


# ── Calibration round-trip ─────────────────────────────────


class TestCalibrationRoundTrip:
    def test_save_read(self, tmp_path: Path):
        cal = Calibration(
            method_name="keyword-v1",
            target_precision=0.9,
            threshold=0.42,
            gate_weights={"dominance": 1.0},
            calibrated_at="2026-05-12T00:00:00+00:00",
            n_calibration_queries=10,
            test_precision=0.9,
            test_coverage=0.6,
            notes="ok",
        )
        path = tmp_path / "cal.json"
        save_calibration(cal, path)
        loaded = read_calibration(path)
        assert loaded == cal

    def test_read_rejects_extra(self, tmp_path: Path):
        path = tmp_path / "cal.json"
        path.write_text(json.dumps({"method_name": "x", "threshold": 0.5, "target_precision": 0.9,
                                    "calibrated_at": "2026-05-12", "n_calibration_queries": 1,
                                    "extra_field": "boom"}))
        with pytest.raises(Exception):
            read_calibration(path)


# ── Calibration end-to-end (synthetic) ─────────────────────


class TestCalibrationE2E:
    def test_synthetic_query_set(self, tmp_path: Path, monkeypatch):
        db = _basic_db(tmp_path, monkeypatch)

        # A synthetic 6-query set; half are exact matches (label=1), half are
        # path queries to nonexistent files (label=0).
        queries = [
            Query(id=f"hit-{i}", kind="file_path", query="src/foo.py", relevant=["SPEC-001"])
            for i in range(3)
        ] + [
            Query(id=f"miss-{i}", kind="file_path", query=f"src/nonexistent_{i}.py", relevant=[])
            for i in range(3)
        ]
        qs = QuerySet(corpus="test", description="synthetic", queries=queries)

        cal = calibrate_method(
            method=KeywordBaseline(),
            query_set=qs,
            target_precision=0.5,
            project_root=tmp_path,
            db=db,
        )
        assert cal.method_name == "keyword-v1"
        assert cal.threshold >= 0.0
        # All 7 gates should appear in default weights.
        assert set(cal.gate_weights.keys()) == {
            "dominance",
            "identifier-citation",
            "hedge-phrase",
            "status",
            "recency",
            "coverage",
            "authorship",
        }
        assert cal.notes is not None


# ── KeywordCalibrated method ──────────────────────────────


class TestKeywordCalibrated:
    def test_loads_calibration_if_present(self, tmp_path: Path, monkeypatch):
        # Place a calibration file at the canonical location.
        _write_basic_corpus(tmp_path)
        cal_dir = tmp_path / "eval" / "calibrations"
        cal_dir.mkdir(parents=True)
        cal = Calibration(
            method_name="keyword-v1",
            target_precision=0.9,
            threshold=0.95,  # very strict — almost everything abstains
            gate_weights={},
            calibrated_at="2026-05-12T00:00:00+00:00",
            n_calibration_queries=10,
        )
        save_calibration(cal, cal_dir / "keyword-v1.json")
        monkeypatch.chdir(tmp_path)
        from decree.config import get_project_root, load_doc_types
        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        method = KeywordCalibrated()
        assert abs(method.threshold - 0.95) < 1e-6

    def test_high_confidence_returns_baseline_results(
        self, tmp_path: Path, monkeypatch
    ):
        db = _basic_db(tmp_path, monkeypatch)
        # Use threshold=0 (no calibration installed) — method behaves like baseline.
        method = KeywordCalibrated(calibration_path=tmp_path / "no-such.json")
        q = Query(id="x", kind="file_path", query="src/foo.py", relevant=["SPEC-001"])
        result = method.query(db, q, k=5)
        assert "SPEC-001" in result
        assert method.last_abstention_reason() is None

    def test_low_confidence_abstains(self, tmp_path: Path, monkeypatch):
        db = _basic_db(tmp_path, monkeypatch)
        # Install an absurdly strict calibration so any signal triggers abstention.
        cal_path = tmp_path / "high-threshold.json"
        save_calibration(
            Calibration(
                method_name="keyword-v1",
                target_precision=0.99,
                threshold=2.0,  # impossible — composite ≤ 1
                gate_weights={},
                calibrated_at="2026-05-12T00:00:00+00:00",
                n_calibration_queries=1,
            ),
            cal_path,
        )
        method = KeywordCalibrated(calibration_path=cal_path)
        q = Query(id="x", kind="file_path", query="src/foo.py", relevant=["SPEC-001"])
        result = method.query(db, q, k=5)
        assert result == []
        assert method.last_abstention_reason() is not None
        assert "below threshold" in method.last_abstention_reason()
        diag = method.last_diagnostics()
        assert diag["threshold"] == 2.0
        assert diag["composite"] < 2.0
        assert len(diag["signals"]) == 7
        assert diag["would_return"] == ["SPEC-001"]

    def test_compute_signals_returns_seven(self, tmp_path: Path, monkeypatch):
        db = _basic_db(tmp_path, monkeypatch)
        q = Query(id="x", kind="file_path", query="src/foo.py", relevant=["SPEC-001"])
        rows = enrich_rows(db, ["SPEC-001"])
        signals = compute_signals(q, rows, db)
        names = [s.name for s in signals]
        assert names == [
            "dominance",
            "identifier-citation",
            "hedge-phrase",
            "status",
            "recency",
            "coverage",
            "authorship",
        ]


# ── All-gates registry ────────────────────────────────────


def test_all_gates_count():
    assert len(ALL_GATES) == 7
