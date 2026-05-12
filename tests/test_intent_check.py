"""SPEC-014 — intent-check tests.

Mirrors the fixture and corpus patterns from ``tests/test_intent_review.py``
(SPEC-009). All LLM calls under ``--judge-conflicts`` are mocked via
``monkeypatch.setattr(litellm, ...)`` — no live network in CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from decree.commands.intent_check import (
    IntentCheckReport,
    _judge_conflict,
    _parse_llm_json,
    _plan_mentions_architecture,
    intent_check,
    intent_check_run,
    report_to_dict,
)
from decree.commands.intent_review import Conflict
from decree.index_db import IndexDB, default_db_path


# ── Fixture helpers (mirrors test_intent_review.py) ─────────


def _decree_toml() -> str:
    return """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Problem Statement"]
[types.prd.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.prd.actions]
approve = "approved"
implement = "implemented"

[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"
[types.adr.status_field_requirements]
superseded = ["superseded-by"]

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
"""


def _write_corpus_basic(root: Path, *, spec_status: str = "implemented") -> None:
    """SPEC-001 governs src/foo.py with one unchecked AC."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "001-test.md").write_text(
        """---
status: approved
date: 2026-05-10
---

# PRD-001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "001-test.md").write_text(
        f"""---
status: {spec_status}
date: 2026-05-12
references: [PRD-001]
governs:
  - src/foo.py
---

# SPEC-001 Test SPEC

## Overview

Prose.

## Acceptance Criteria

- [ ] Feature is shipped
- [x] Tests pass
"""
    )


def _write_corpus_two_specs_same_file(root: Path) -> None:
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "001-test.md").write_text(
        """---
status: approved
date: 2026-05-10
---

# PRD-001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "001-a.md").write_text(
        """---
status: implemented
date: 2026-05-01
references: [PRD-001]
governs:
  - src/foo.py
---

# SPEC-001 A

## Overview

A's perspective: it caches the file's hot path.
"""
    )
    (root / "decree" / "spec" / "002-b.md").write_text(
        """---
status: draft
date: 2026-05-12
references: [PRD-001]
governs:
  - src/foo.py
---

# SPEC-002 B

## Overview

B's perspective: it changes the file's serialization format.
"""
    )


def _rebuild_index(root: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(root))
    db.rebuild(root)
    return db


@pytest.fixture
def basic_db_and_root(tmp_path: Path, monkeypatch) -> tuple[IndexDB, Path]:
    _write_corpus_basic(tmp_path)
    db = _rebuild_index(tmp_path, monkeypatch)
    return db, tmp_path


@pytest.fixture
def in_flight_db_and_root(tmp_path: Path, monkeypatch) -> tuple[IndexDB, Path]:
    _write_corpus_basic(tmp_path, spec_status="draft")
    db = _rebuild_index(tmp_path, monkeypatch)
    return db, tmp_path


# ── Internal helpers ────────────────────────────────────────


class TestParseLLMJson:
    def test_bare_json(self) -> None:
        assert _parse_llm_json('{"x": 1}') == {"x": 1}

    def test_fenced_json_block(self) -> None:
        assert _parse_llm_json('```json\n{"x": 1}\n```') == {"x": 1}

    def test_fenced_block_no_lang(self) -> None:
        assert _parse_llm_json("```\n{\"x\": 1}\n```") == {"x": 1}


class TestPlanArchitectureHeuristic:
    @pytest.mark.parametrize(
        "plan",
        [
            "I will redesign the auth flow",
            "We need to decide between Redis and Memcached",
            "Refactor the system to remove the global state",
            "Architecture migration to event sourcing",
            "Choose between SQLite and Postgres for the queue",
        ],
    )
    def test_positive(self, plan: str) -> None:
        assert _plan_mentions_architecture(plan) is True

    @pytest.mark.parametrize(
        "plan",
        [
            "Fix typo in README",
            "Add caching for the auth path",
            "",
            "Bump dependency versions",
        ],
    )
    def test_negative(self, plan: str) -> None:
        assert _plan_mentions_architecture(plan) is False


# ── Library unit tests ──────────────────────────────────────


class TestIntentCheckLibrary:
    def test_empty_plan_empty_files(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "", [])
        assert isinstance(report, IntentCheckReport)
        assert report.plan == ""
        assert report.planned_files == ()
        assert report.governing_decisions == ()
        assert report.conflicts == ()
        actions = {r.action for r in report.recommended_actions}
        assert "proceed" in actions

    def test_planned_file_with_one_governing_decision(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Tweak src/foo.py", ["src/foo.py"])
        assert len(report.governing_decisions) == 1
        snap = report.governing_decisions[0]
        assert snap.decision_id == "SPEC-001"
        assert snap.match_kind == "exact"

    def test_planned_file_match_in_flight_spec_surfaces_ac_and_update_spec_first(
        self, in_flight_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = in_flight_db_and_root
        report = intent_check(db, root, "Modify src/foo.py", ["src/foo.py"])
        ac_texts = [ac.text for ac in report.unchecked_acceptance_criteria]
        assert any("Feature is shipped" in t for t in ac_texts)
        actions = {r.action for r in report.recommended_actions}
        assert "update_spec_first" in actions
        assert "check_ac" in actions

    def test_planned_file_with_no_governance_emits_add_governance(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Touch a new file", ["src/new.py"])
        assert report.governing_decisions == ()
        actions = {r.action for r in report.recommended_actions}
        assert "add_governance" in actions
        # detail mentions the path
        assert any(
            "src/new.py" in r.detail
            for r in report.recommended_actions
            if r.action == "add_governance"
        )

    def test_plan_with_architecture_keyword_emits_draft_adr_first(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(
            db,
            root,
            "Decide between two cache backends and redesign auth",
            ["src/new.py"],
        )
        actions = {r.action for r in report.recommended_actions}
        assert "draft_adr_first" in actions

    def test_plan_without_architecture_keyword_skips_draft_adr_first(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Fix a small typo", ["src/new.py"])
        actions = {r.action for r in report.recommended_actions}
        assert "draft_adr_first" not in actions

    def test_structural_conflict_surfaces_resolve_conflict_first(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = intent_check(db, tmp_path, "Touch foo", ["src/foo.py"])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert c.path == "src/foo.py"
        assert set(c.decision_ids) == {"SPEC-001", "SPEC-002"}
        # Structural-only — no semantic verdict without --judge-conflicts.
        assert c.semantic_verdict is None
        actions = {r.action for r in report.recommended_actions}
        assert "resolve_conflict_first" in actions

    def test_dedupes_planned_files(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(
            db, root, "Plan", ["src/foo.py", "src/foo.py", "src/foo.py"]
        )
        assert report.planned_files == ("src/foo.py",)


# ── --judge-conflicts (LLM mocked) ──────────────────────────


def _mock_completion(payload: dict | None, *, raise_exc: Exception | None = None):
    """Build a MagicMock to substitute for ``litellm.completion``.

    If ``raise_exc`` is set, the mock raises it. Otherwise it returns a
    response with ``choices[0].message.content = json.dumps(payload)``.
    """

    def _make_response(content: str) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    def side_effect(**kwargs):
        if raise_exc is not None:
            raise raise_exc
        return _make_response(json.dumps(payload))

    return MagicMock(side_effect=side_effect)


class TestJudgeConflicts:
    def test_judge_real_conflict(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)

        import litellm

        mock = _mock_completion(
            {"is_real_conflict": True, "reasoning": "they disagree on format"}
        )
        monkeypatch.setattr(litellm, "completion", mock)

        report = intent_check(
            db,
            tmp_path,
            "Touch src/foo.py",
            ["src/foo.py"],
            judge_conflicts=True,
            model="mock-model",
        )
        assert mock.called
        assert len(report.conflicts) == 1
        verdict = report.conflicts[0].semantic_verdict
        assert verdict is not None
        assert verdict["is_real_conflict"] is True
        assert "disagree" in verdict["reasoning"]

    def test_judge_complementary(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)

        import litellm

        mock = _mock_completion(
            {
                "is_real_conflict": False,
                "reasoning": "different aspects of same file",
            }
        )
        monkeypatch.setattr(litellm, "completion", mock)

        report = intent_check(
            db,
            tmp_path,
            "Touch src/foo.py",
            ["src/foo.py"],
            judge_conflicts=True,
            model="mock-model",
        )
        assert len(report.conflicts) == 1
        verdict = report.conflicts[0].semantic_verdict
        assert verdict is not None
        assert verdict["is_real_conflict"] is False

    def test_judge_llm_error_falls_back_to_structural(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)

        import litellm

        mock = _mock_completion(None, raise_exc=RuntimeError("network down"))
        monkeypatch.setattr(litellm, "completion", mock)

        report = intent_check(
            db,
            tmp_path,
            "Touch src/foo.py",
            ["src/foo.py"],
            judge_conflicts=True,
            model="mock-model",
        )
        # Conflict still surfaces, just without semantic_verdict.
        assert len(report.conflicts) == 1
        assert report.conflicts[0].semantic_verdict is None
        actions = {r.action for r in report.recommended_actions}
        assert "resolve_conflict_first" in actions


# ── --with-abstention ───────────────────────────────────────


class TestWithAbstention:
    def test_abstention_field_populated_when_no_governance(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        # An ungoverned path; with_abstention=True should attempt to populate
        # the abstention dict (may be None when there's no calibration JSON
        # on disk, but the kwarg branch should be exercised).
        report = intent_check(
            db,
            root,
            "Touch a new file",
            ["src/never_governed.py"],
            with_abstention=True,
        )
        assert report.governing_decisions == ()
        # The attribute exists; we can't assert non-None without a fixture
        # calibration on disk, but we can assert the type contract.
        assert report.abstention is None or isinstance(report.abstention, dict)


# ── Stale governance ────────────────────────────────────────


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, file_path: str, body: str, message: str) -> None:
    full = repo / file_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    _git(repo, "add", file_path)
    _git(repo, "commit", "-m", message)


class TestStaleGovernance:
    def test_stale_governance_surfaced(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _git_init(tmp_path)
        _write_corpus_basic(tmp_path)
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "init")
        db = _rebuild_index(tmp_path, monkeypatch)

        time.sleep(1.1)
        for i in range(15):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")

        report = intent_check(
            db, tmp_path, "Touch src/foo.py", ["src/foo.py"], threshold_commits=10
        )
        stale_ids = {s["decision_id"] for s in report.stale_governance}
        assert "SPEC-001" in stale_ids
        update_recs = [
            r for r in report.recommended_actions if r.action == "update_decision"
        ]
        assert any(r.target_id == "SPEC-001" for r in update_recs)


# ── JSON shape ──────────────────────────────────────────────


class TestReportToDict:
    def test_shape_is_stable(
        self, basic_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Plan", ["src/foo.py"])
        payload = report_to_dict(report)
        assert set(payload.keys()) == {
            "plan",
            "planned_files",
            "governing_decisions",
            "stale_governance",
            "unchecked_acceptance_criteria",
            "conflicts",
            "abstention",
            "recommended_actions",
        }
        # Round-trip through JSON.
        s = json.dumps(payload)
        roundtrip = json.loads(s)
        assert roundtrip == payload

    def test_conflict_includes_semantic_verdict_field(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = intent_check(db, tmp_path, "Plan", ["src/foo.py"])
        payload = report_to_dict(report)
        assert len(payload["conflicts"]) == 1
        # Even without --judge-conflicts the key must be present.
        assert "semantic_verdict" in payload["conflicts"][0]
        assert payload["conflicts"][0]["semantic_verdict"] is None


# ── CLI tests ───────────────────────────────────────────────


def _make_args(**kw) -> argparse.Namespace:
    defaults = dict(
        plan="",
        files=[],
        with_abstention=False,
        target_precision=None,
        judge_conflicts=False,
        model=None,
        json=False,
        project=None,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestIntentCheckCLI:
    def test_clean_run_exit_0(
        self, basic_db_and_root: tuple[IndexDB, Path], capsys
    ) -> None:
        _db, root = basic_db_and_root
        args = _make_args(
            plan="Touch src/foo.py",
            files=["src/foo.py"],
            project=str(root),
        )
        rc = intent_check_run(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "src/foo.py" in out
        assert "SPEC-001" in out

    def test_conflict_exit_1(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        _rebuild_index(tmp_path, monkeypatch)
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            project=str(tmp_path),
        )
        rc = intent_check_run(args)
        capsys.readouterr()
        assert rc == 1

    def test_judge_conflicts_without_api_key_exit_2(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        monkeypatch,
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        # Strip every API-key env var so resolve_model raises SystemExit(2).
        for var in ("DECREE_LLM_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            judge_conflicts=True,
            project=str(root),
        )
        rc = intent_check_run(args)
        capsys.readouterr()
        assert rc == 2

    def test_json_output_schema_stable(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            json=True,
            project=str(root),
        )
        rc = intent_check_run(args)
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert set(payload.keys()) == {
            "plan",
            "planned_files",
            "governing_decisions",
            "stale_governance",
            "unchecked_acceptance_criteria",
            "conflicts",
            "abstention",
            "recommended_actions",
        }
        assert rc == 0

    def test_missing_index_exit_1(
        self, tmp_path: Path, capsys
    ) -> None:
        # decree.toml present but no index built.
        _write_corpus_basic(tmp_path)
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            project=str(tmp_path),
        )
        rc = intent_check_run(args)
        capsys.readouterr()
        assert rc == 1


# ── Recommendation determinism ──────────────────────────────


class TestRecommendationDeterminism:
    def test_same_inputs_yield_same_recommendations(
        self, in_flight_db_and_root: tuple[IndexDB, Path]
    ) -> None:
        db, root = in_flight_db_and_root
        a = intent_check(db, root, "Plan X", ["src/foo.py"])
        b = intent_check(db, root, "Plan X", ["src/foo.py"])
        actions_a = [(r.action, r.target_id, r.detail) for r in a.recommended_actions]
        actions_b = [(r.action, r.target_id, r.detail) for r in b.recommended_actions]
        assert actions_a == actions_b


# ── _judge_conflict isolation ───────────────────────────────


class TestJudgeConflictHelper:
    def test_parses_well_formed_response(self, monkeypatch) -> None:
        import litellm

        mock = _mock_completion(
            {"is_real_conflict": True, "reasoning": "they disagree"}
        )
        monkeypatch.setattr(litellm, "completion", mock)
        c = Conflict(path="src/foo.py", decision_ids=("SPEC-001", "SPEC-002"))
        result = _judge_conflict(
            "Plan",
            c,
            {"decision_id": "SPEC-001", "title": "A", "body": "body A"},
            {"decision_id": "SPEC-002", "title": "B", "body": "body B"},
            "mock-model",
        )
        assert result == {"is_real_conflict": True, "reasoning": "they disagree"}

    def test_returns_none_on_invalid_payload(self, monkeypatch) -> None:
        import litellm

        # Mock returns a payload missing the required key.
        mock = _mock_completion({"reasoning": "missing the verdict bool"})
        monkeypatch.setattr(litellm, "completion", mock)
        c = Conflict(path="src/foo.py", decision_ids=("SPEC-001", "SPEC-002"))
        result = _judge_conflict(
            "Plan",
            c,
            {"decision_id": "SPEC-001", "title": "A", "body": "body A"},
            {"decision_id": "SPEC-002", "title": "B", "body": "body B"},
            "mock-model",
        )
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch) -> None:
        import litellm

        mock = _mock_completion(None, raise_exc=RuntimeError("api error"))
        monkeypatch.setattr(litellm, "completion", mock)
        c = Conflict(path="src/foo.py", decision_ids=("SPEC-001", "SPEC-002"))
        result = _judge_conflict(
            "Plan",
            c,
            {"decision_id": "SPEC-001", "title": "A", "body": "body A"},
            {"decision_id": "SPEC-002", "title": "B", "body": "body B"},
            "mock-model",
        )
        assert result is None
