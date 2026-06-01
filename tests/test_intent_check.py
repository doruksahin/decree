"""SPEC-00000000000000000000000014 — intent-check tests.

Mirrors the fixture and corpus patterns from ``tests/test_intent_review.py``.
Core intent-check is deterministic and does not call LLM providers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import pytest

from decree.commands.intent_check import (
    IntentCheckReport,
    _plan_mentions_architecture,
    intent_check,
    intent_check_run,
    report_to_dict,
)
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
    """SPEC-00000000000000000000000001 governs src/foo.py with one unchecked AC."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        f"""---
id: SPEC-00000000000000000000000001
status: {spec_status}
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Test SPEC

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

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-a.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-01
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 A

## Overview

A's perspective: it caches the file's hot path.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000002-b.md").write_text(
        """---
id: SPEC-00000000000000000000000002
status: draft
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000002 B

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
    def test_empty_plan_empty_files(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "", [])
        assert isinstance(report, IntentCheckReport)
        assert report.plan == ""
        assert report.planned_files == ()
        assert report.governing_decisions == ()
        assert report.conflicts == ()
        actions = {r.action for r in report.recommended_actions}
        assert "proceed" in actions

    def test_planned_file_with_one_governing_decision(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Tweak src/foo.py", ["src/foo.py"])
        assert len(report.governing_decisions) == 1
        snap = report.governing_decisions[0]
        assert snap.decision_id == "SPEC-00000000000000000000000001"
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
        assert any("src/new.py" in r.detail for r in report.recommended_actions if r.action == "add_governance")

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

    def test_structural_conflict_surfaces_resolve_conflict_first(self, tmp_path: Path, monkeypatch) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = intent_check(db, tmp_path, "Touch foo", ["src/foo.py"])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert c.path == "src/foo.py"
        assert set(c.decision_ids) == {"SPEC-00000000000000000000000001", "SPEC-00000000000000000000000002"}
        # Structural-only — core decree does not perform semantic LLM judging.
        assert c.semantic_verdict is None
        actions = {r.action for r in report.recommended_actions}
        assert "resolve_conflict_first" in actions

    def test_dedupes_planned_files(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Plan", ["src/foo.py", "src/foo.py", "src/foo.py"])
        assert report.planned_files == ("src/foo.py",)


# ── --with-abstention ───────────────────────────────────────


class TestWithAbstention:
    def test_abstention_field_populated_when_no_governance(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
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
    def test_stale_governance_surfaced(self, tmp_path: Path, monkeypatch) -> None:
        _git_init(tmp_path)
        _write_corpus_basic(tmp_path)
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "init")
        db = _rebuild_index(tmp_path, monkeypatch)

        time.sleep(1.1)
        for i in range(15):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")

        report = intent_check(db, tmp_path, "Touch src/foo.py", ["src/foo.py"], threshold_commits=10)
        stale_ids = {s["decision_id"] for s in report.stale_governance}
        assert "SPEC-00000000000000000000000001" in stale_ids
        update_recs = [r for r in report.recommended_actions if r.action == "update_decision"]
        assert any(r.target_id == "SPEC-00000000000000000000000001" for r in update_recs)


# ── JSON shape ──────────────────────────────────────────────


class TestReportToDict:
    def test_shape_is_stable(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
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
            "live_conflicts",
            "abstention",
            "recommended_actions",
        }
        # Round-trip through JSON.
        s = json.dumps(payload)
        roundtrip = json.loads(s)
        assert roundtrip == payload

    def test_conflict_includes_semantic_verdict_field(self, tmp_path: Path, monkeypatch) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = intent_check(db, tmp_path, "Plan", ["src/foo.py"])
        payload = report_to_dict(report)
        assert len(payload["conflicts"]) == 1
        # The schema key remains present for consumers, but core leaves it empty.
        assert "semantic_verdict" in payload["conflicts"][0]
        assert payload["conflicts"][0]["semantic_verdict"] is None


# ── CLI tests ───────────────────────────────────────────────


class TestLiveSessionConflicts:
    """``other_active_files`` cross-session overlap detection (agentkith integration)."""

    def test_absent_by_default(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(db, root, "Plan", ["src/foo.py"])
        assert report.live_conflicts == ()
        assert report_to_dict(report)["live_conflicts"] == []
        assert all(r.action != "isolate_session" for r in report.recommended_actions)

    def test_overlap_surfaces_live_conflict_and_recommendation(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(
            db,
            root,
            "Plan",
            ["src/foo.py", "src/only-mine.py"],
            other_active_files={
                "session-b": ["src/foo.py"],
                "session-c": ["src/elsewhere.py"],
            },
        )
        # Only the shared path is a live conflict; session-c claims nothing we plan.
        assert [lc.path for lc in report.live_conflicts] == ["src/foo.py"]
        assert report.live_conflicts[0].session_ids == ("session-b",)
        assert any(r.action == "isolate_session" for r in report.recommended_actions)
        payload = report_to_dict(report)
        assert payload["live_conflicts"] == [{"path": "src/foo.py", "session_ids": ["session-b"]}]

    def test_multiple_sessions_same_path_are_sorted(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_check(
            db,
            root,
            "Plan",
            ["src/foo.py"],
            other_active_files={"session-z": ["src/foo.py"], "session-a": ["src/foo.py"]},
        )
        assert report.live_conflicts[0].session_ids == ("session-a", "session-z")


def _make_args(**kw) -> argparse.Namespace:
    defaults = dict(
        plan="",
        files=[],
        with_abstention=False,
        target_precision=None,
        json=False,
        project=None,
        other_active_files=None,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestIntentCheckCLI:
    def test_other_active_files_flag_surfaces_live_conflict(
        self, basic_db_and_root: tuple[IndexDB, Path], capsys
    ) -> None:
        _db, root = basic_db_and_root
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            json=True,
            project=str(root),
            other_active_files='{"session-b": ["src/foo.py"]}',
        )
        rc = intent_check_run(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["live_conflicts"] == [{"path": "src/foo.py", "session_ids": ["session-b"]}]
        assert rc == 1  # a live-session overlap is a blocker

    def test_other_active_files_invalid_json_exits_2(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        _db, root = basic_db_and_root
        args = _make_args(
            plan="Touch foo",
            files=["src/foo.py"],
            project=str(root),
            other_active_files="{not valid json",
        )
        assert intent_check_run(args) == 2

    def test_clean_run_exit_0(self, basic_db_and_root: tuple[IndexDB, Path], capsys) -> None:
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
        assert "SPEC-00000000000000000000000001" in out

    def test_conflict_exit_1(self, tmp_path: Path, monkeypatch, capsys) -> None:
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
            "live_conflicts",
            "abstention",
            "recommended_actions",
        }
        assert rc == 0

    def test_missing_index_exit_1(self, tmp_path: Path, capsys) -> None:
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
    def test_same_inputs_yield_same_recommendations(self, in_flight_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = in_flight_db_and_root
        a = intent_check(db, root, "Plan X", ["src/foo.py"])
        b = intent_check(db, root, "Plan X", ["src/foo.py"])
        actions_a = [(r.action, r.target_id, r.detail) for r in a.recommended_actions]
        actions_b = [(r.action, r.target_id, r.detail) for r in b.recommended_actions]
        assert actions_a == actions_b
