"""SPEC-00000000000000000000000009 — intent-review tests.

Mirrors the fixture patterns from `tests/test_queries.py` and the tmp git-repo
recipe from `tests/test_health.py`.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import time
from pathlib import Path

import pytest

from decree.commands.intent_review import (
    IntentReport,
    intent_review,
    intent_review_run,
    parse_diff,
    report_to_dict,
)
from decree.index_db import IndexDB, default_db_path

# ── Fixture helpers ─────────────────────────────────────────


def _decree_toml() -> str:
    """Three-type decree.toml — mirrors tests/test_queries.py."""
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
    """SPEC-00000000000000000000000001 governing src/foo.py, with one optional unchecked AC."""
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
    """SPEC-00000000000000000000000001 and SPEC-00000000000000000000000002 both declaring governs: src/foo.py."""
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

Prose.
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

Prose.
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


# ── Diff parser unit tests ──────────────────────────────────


class TestParseDiff:
    def test_empty_diff_returns_empty(self) -> None:
        assert parse_diff("") == []

    def test_single_file_diff(self) -> None:
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "index 0000000..1111111 100644\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -0,0 +1 @@\n"
            "+x = 1\n"
        )
        assert parse_diff(diff) == ["src/foo.py"]

    def test_multi_file_diff(self) -> None:
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/src/b.py b/src/b.py\n"
            "--- a/src/b.py\n"
            "+++ b/src/b.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
        )
        assert parse_diff(diff) == ["src/a.py", "src/b.py"]

    def test_rename_uses_post_rename_path(self) -> None:
        diff = (
            "diff --git a/src/old.py b/src/new.py\n"
            "similarity index 100%\n"
            "rename from src/old.py\n"
            "rename to src/new.py\n"
        )
        assert parse_diff(diff) == ["src/new.py"]

    def test_deleted_file_excluded(self) -> None:
        diff = (
            "diff --git a/src/gone.py b/src/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/src/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-bye\n"
        )
        assert parse_diff(diff) == []

    def test_mixed_add_modify_delete(self) -> None:
        diff = (
            "diff --git a/src/keep.py b/src/keep.py\n"
            "--- a/src/keep.py\n"
            "+++ b/src/keep.py\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n"
            "diff --git a/src/gone.py b/src/gone.py\n"
            "deleted file mode 100644\n"
            "--- a/src/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-bye\n"
            "diff --git a/src/new.py b/src/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new.py\n"
            "@@ -0,0 +1 @@\n"
            "+hello\n"
        )
        result = parse_diff(diff)
        assert "src/keep.py" in result
        assert "src/new.py" in result
        assert "src/gone.py" not in result

    def test_dedupe(self) -> None:
        # Same diff --git header twice should still dedupe.
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
        )
        assert parse_diff(diff) == ["src/a.py"]


# ── Library unit tests ──────────────────────────────────────


class TestIntentReviewLibrary:
    def test_empty_changed_paths(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_review(db, root, [])
        assert isinstance(report, IntentReport)
        assert report.changed_paths == ()
        assert report.governing_decisions == ()
        assert report.stale_governance == ()
        assert report.unchecked_acceptance_criteria == ()
        assert report.conflicts == ()
        assert report.recommended_actions == ()

    def test_ungoverned_path(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_review(db, root, ["src/unknown.py"])
        assert report.governing_decisions == ()
        actions = {r.action for r in report.recommended_actions}
        assert "add_governance" in actions
        # The detail for add_governance should reference the path.
        gov_recs = [r for r in report.recommended_actions if r.action == "add_governance"]
        assert any("src/unknown.py" in r.detail for r in gov_recs)

    def test_one_governing_decision(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_review(db, root, ["src/foo.py"])
        assert len(report.governing_decisions) == 1
        snap = report.governing_decisions[0]
        assert snap.decision_id == "SPEC-00000000000000000000000001"
        assert snap.status == "implemented"
        assert snap.match_kind == "exact"

    def test_unchecked_ac_surfaced_for_in_flight_spec(self, in_flight_db_and_root: tuple[IndexDB, Path]) -> None:
        # SPEC-00000000000000000000000001 is draft (non-terminal) so its unchecked AC should surface.
        db, root = in_flight_db_and_root
        report = intent_review(db, root, ["src/foo.py"])
        ac_texts = [ac.text for ac in report.unchecked_acceptance_criteria]
        # We declared "Feature is shipped" as an unchecked AC, "Tests pass" as done.
        assert any("Feature is shipped" in t for t in ac_texts)
        assert all("Tests pass" not in t for t in ac_texts)
        actions = {r.action for r in report.recommended_actions}
        assert "check_ac" in actions

    def test_unchecked_ac_not_surfaced_for_terminal_spec(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        # SPEC-00000000000000000000000001 is `implemented` (terminal) → don't surface its ACs.
        db, root = basic_db_and_root
        report = intent_review(db, root, ["src/foo.py"])
        assert report.unchecked_acceptance_criteria == ()

    def test_structural_conflict_detected(self, tmp_path: Path, monkeypatch) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = intent_review(db, tmp_path, ["src/foo.py"])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert c.path == "src/foo.py"
        assert set(c.decision_ids) == {"SPEC-00000000000000000000000001", "SPEC-00000000000000000000000002"}
        actions = {r.action for r in report.recommended_actions}
        assert "resolve_conflict" in actions

    def test_add_implements_trailer_for_in_flight_spec(self, in_flight_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = in_flight_db_and_root
        report = intent_review(db, root, ["src/foo.py"])
        actions = {r.action for r in report.recommended_actions}
        assert "add_implements_trailer" in actions
        rec = next(r for r in report.recommended_actions if r.action == "add_implements_trailer")
        assert rec.target_id == "SPEC-00000000000000000000000001"

    def test_dedupes_changed_paths(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_review(db, root, ["src/foo.py", "src/foo.py"])
        assert report.changed_paths == ("src/foo.py",)


# ── Stale-governance integration test (tmp git repo) ────────


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


class TestIntentReviewStale:
    def test_stale_governance_surfaced(self, tmp_path: Path, monkeypatch) -> None:
        # Build a fresh git repo with one SPEC governing src/foo.py.
        _git_init(tmp_path)
        _write_corpus_basic(tmp_path)
        # Initial commit: everything as-is.
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "init")
        db = _rebuild_index(tmp_path, monkeypatch)

        # Wait so subsequent commits are strictly after the SPEC's last touch.
        time.sleep(1.1)
        for i in range(15):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")

        report = intent_review(db, tmp_path, ["src/foo.py"], threshold_commits=10)
        # SPEC-00000000000000000000000001 should appear as stale governance.
        stale_ids = {s["decision_id"] for s in report.stale_governance}
        assert "SPEC-00000000000000000000000001" in stale_ids
        # And a recommendation to update_decision should be emitted.
        update_recs = [r for r in report.recommended_actions if r.action == "update_decision"]
        assert any(r.target_id == "SPEC-00000000000000000000000001" for r in update_recs)


# ── JSON shape ──────────────────────────────────────────────


class TestReportToDict:
    def test_shape_is_stable(self, basic_db_and_root: tuple[IndexDB, Path]) -> None:
        db, root = basic_db_and_root
        report = intent_review(db, root, ["src/foo.py"])
        payload = report_to_dict(report)
        assert set(payload.keys()) == {
            "changed_paths",
            "governing_decisions",
            "stale_governance",
            "unchecked_acceptance_criteria",
            "conflicts",
            "recommended_actions",
            "under_decision",
            "under_error",
            "governs_gaps",
        }
        # Round-trip through JSON.
        s = json.dumps(payload)
        roundtrip = json.loads(s)
        assert roundtrip == payload


# ── CLI tests ───────────────────────────────────────────────


def _make_args(**kw) -> argparse.Namespace:
    defaults = dict(diff=None, diff_base=None, json=False, project=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class TestIntentReviewCLI:
    def test_diff_from_file(self, basic_db_and_root: tuple[IndexDB, Path], tmp_path: Path, capsys) -> None:
        _db, root = basic_db_and_root
        diff_path = tmp_path / "patch.diff"
        diff_path.write_text(
            "diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        args = _make_args(diff=str(diff_path), project=str(root))
        rc = intent_review_run(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "src/foo.py" in out
        assert "SPEC-00000000000000000000000001" in out

    def test_diff_from_stdin(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        monkeypatch,
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        diff_text = "diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(diff_text))
        args = _make_args(diff="-", project=str(root))
        rc = intent_review_run(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "src/foo.py" in out

    def test_diff_from_staged(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        # Initialize a git repo, commit baseline, then stage a change to src/foo.py.
        _git_init(root)
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "init")
        (root / "src" / "foo.py").write_text("changed = 1\n")
        _git(root, "add", "src/foo.py")

        args = _make_args(project=str(root))
        rc = intent_review_run(args)
        out = capsys.readouterr().out
        assert "src/foo.py" in out
        # SPEC-00000000000000000000000001 governs src/foo.py and is in terminal status, so exit 0.
        assert rc == 0

    def test_json_output_schema(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        tmp_path: Path,
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        diff_path = tmp_path / "patch.diff"
        diff_path.write_text("diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n")
        args = _make_args(diff=str(diff_path), json=True, project=str(root))
        rc = intent_review_run(args)
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert set(payload.keys()) == {
            "changed_paths",
            "governing_decisions",
            "stale_governance",
            "unchecked_acceptance_criteria",
            "conflicts",
            "recommended_actions",
            "under_decision",
            "under_error",
            "governs_gaps",
        }
        assert rc == 0

    def test_exit_code_1_on_conflict(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _write_corpus_two_specs_same_file(tmp_path)
        _rebuild_index(tmp_path, monkeypatch)
        diff_path = tmp_path / "patch.diff"
        diff_path.write_text("diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n")
        args = _make_args(diff=str(diff_path), project=str(tmp_path))
        rc = intent_review_run(args)
        capsys.readouterr()
        assert rc == 1

    def test_exit_code_0_when_clean(
        self,
        basic_db_and_root: tuple[IndexDB, Path],
        tmp_path: Path,
        capsys,
    ) -> None:
        _db, root = basic_db_and_root
        diff_path = tmp_path / "patch.diff"
        diff_path.write_text(
            "diff --git a/src/unrelated.py b/src/unrelated.py\n--- a/src/unrelated.py\n+++ b/src/unrelated.py\n"
        )
        args = _make_args(diff=str(diff_path), project=str(root))
        rc = intent_review_run(args)
        capsys.readouterr()
        # No governance, no conflicts, no stale → exit 0 (advisory only).
        assert rc == 0
