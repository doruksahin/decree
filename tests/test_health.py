"""SPEC-008 — staleness + ungoverned-hotspot tests.

Uses a tmp git-repo fixture in the same style as SPEC-006's
`TestSyncCommitsFromGit`.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from decree.commands.health import (
    health,
    stale_decisions,
    ungoverned_hotspots,
)
from decree.index_db import IndexDB, default_db_path


# ── Git fixture helpers (mirrors tests/test_index_db.py) ────


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)


def _commit(repo: Path, file_path: str, body: str, message: str) -> str:
    full = repo / file_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body)
    subprocess.run(["git", "-C", str(repo), "add", file_path], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message],
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


def _decree_toml() -> str:
    return """\
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
"""


def _bootstrap_repo(repo: Path, spec_governs: list[str]) -> None:
    """Create a git repo with decree.toml and a SPEC governing `spec_governs` paths."""
    _git_init(repo)
    (repo / "decree.toml").write_text(_decree_toml())
    (repo / "decree" / "spec").mkdir(parents=True)

    governs_yaml = "\n".join(f"  - {p}" for p in spec_governs)
    spec_body = f"""---
status: implemented
date: 2026-05-10
governs:
{governs_yaml}
---

# SPEC-001 test

## Overview

Prose.
"""
    (repo / "decree" / "spec" / "001-test.md").write_text(spec_body)
    # Create governed files (or dirs for trailing-slash entries) so they have
    # a sane initial state and the SPEC's `governs:` paths exist.
    for p in spec_governs:
        if p.endswith("/"):
            (repo / p).mkdir(parents=True, exist_ok=True)
            (repo / p / ".gitkeep").write_text("")
        else:
            full = repo / p
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("initial\n")

    # Initial commit; everything in one commit, then the SPEC is "last touched" here.
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


def _rebuild_index(repo: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(repo)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(repo))
    db.rebuild(repo)
    return db


# ── Stale decision tests ───────────────────────────────────


class TestStaleDecisions:
    def test_single_decision_with_churn_is_flagged(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/foo.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        # Ensure post-SPEC commits land at strictly later timestamps. git uses
        # whole-second granularity for committer time, so sleep 1.1s.
        time.sleep(1.1)
        # Push 15 commits to src/foo.py
        for i in range(15):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")

        findings = stale_decisions(db, tmp_path, threshold_commits=10)
        assert len(findings) == 1
        sd = findings[0]
        assert sd.decision_id == "SPEC-001"
        assert sd.churn_count == 15
        assert sd.governed_paths[0][0] == "src/foo.py"
        assert sd.governed_paths[0][1] == 15

    def test_decision_under_threshold_not_flagged(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/foo.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        time.sleep(1.1)
        for i in range(3):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")
        findings = stale_decisions(db, tmp_path, threshold_commits=10)
        assert findings == []

    def test_commits_before_decision_dont_count(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Build a repo where src/foo.py was churned 20 times BEFORE the SPEC was added
        _git_init(tmp_path)
        (tmp_path / "decree.toml").write_text(_decree_toml())
        (tmp_path / "decree" / "spec").mkdir(parents=True)
        (tmp_path / "src").mkdir()
        for i in range(20):
            _commit(tmp_path, "src/foo.py", f"pre{i}\n", f"pre {i}")
        # NOW write the SPEC, which becomes the "last touched" reference.
        time.sleep(1.1)
        (tmp_path / "decree" / "spec" / "001-test.md").write_text(
            """---
status: implemented
date: 2026-05-10
governs:
  - src/foo.py
---

# SPEC-001 test

## Overview

Prose.
"""
        )
        _commit(tmp_path, "decree/spec/001-test.md", _ := "spec body", "add SPEC")
        # The previous _commit clobbers the file; restore it to keep parser happy
        (tmp_path / "decree" / "spec" / "001-test.md").write_text(
            """---
status: implemented
date: 2026-05-10
governs:
  - src/foo.py
---

# SPEC-001 test

## Overview

Prose.
"""
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "add", "decree/spec/001-test.md"], check=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--amend", "--no-edit"],
            check=True,
            capture_output=True,
        )
        db = _rebuild_index(tmp_path, monkeypatch)
        findings = stale_decisions(db, tmp_path, threshold_commits=10)
        assert findings == []  # the 20 pre-SPEC commits don't count

    def test_threshold_customization(self, tmp_path: Path, monkeypatch) -> None:
        _bootstrap_repo(tmp_path, ["src/foo.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        time.sleep(1.1)
        for i in range(6):
            _commit(tmp_path, "src/foo.py", f"v{i}\n", f"edit {i}")
        # Default threshold 10 → not flagged
        assert stale_decisions(db, tmp_path, threshold_commits=10) == []
        # Lower to 5 → flagged
        findings = stale_decisions(db, tmp_path, threshold_commits=5)
        assert len(findings) == 1

    def test_no_git_returns_empty(self, tmp_path: Path) -> None:
        # No git init
        (tmp_path / "decree.toml").write_text(_decree_toml())
        db = IndexDB(default_db_path(tmp_path))
        # No index either; either way, library should return [] for non-git
        assert stale_decisions(db, tmp_path, threshold_commits=10) == []


# ── Hotspot tests ──────────────────────────────────────────


class TestUngovernedHotspots:
    def test_high_churn_no_governance_is_flagged(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        # Churn an UNGOVERNED file 15 times
        for i in range(15):
            _commit(tmp_path, "src/legacy.py", f"v{i}\n", f"edit {i}")
        findings = ungoverned_hotspots(
            db, tmp_path, threshold_commits=10, threshold_days=30
        )
        paths = [h.path for h in findings]
        assert "src/legacy.py" in paths

    def test_high_churn_with_governance_not_flagged(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        for i in range(15):
            _commit(tmp_path, "src/governed.py", f"v{i}\n", f"edit {i}")
        findings = ungoverned_hotspots(
            db, tmp_path, threshold_commits=10, threshold_days=30
        )
        paths = [h.path for h in findings]
        assert "src/governed.py" not in paths

    def test_directory_prefix_governance(self, tmp_path: Path, monkeypatch) -> None:
        # Governs entry "src/api/" should cover src/api/auth.py
        _bootstrap_repo(tmp_path, ["src/api/"])
        db = _rebuild_index(tmp_path, monkeypatch)
        for i in range(15):
            _commit(tmp_path, "src/api/auth.py", f"v{i}\n", f"edit {i}")
        findings = ungoverned_hotspots(
            db, tmp_path, threshold_commits=10, threshold_days=30
        )
        paths = [h.path for h in findings]
        assert "src/api/auth.py" not in paths

    def test_below_threshold_not_flagged(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        for i in range(3):
            _commit(tmp_path, "src/quiet.py", f"v{i}\n", f"edit {i}")
        findings = ungoverned_hotspots(
            db, tmp_path, threshold_commits=10, threshold_days=30
        )
        paths = [h.path for h in findings]
        assert "src/quiet.py" not in paths


# ── Combined health() report ───────────────────────────────


class TestHealthReport:
    def test_combined_report_shape(self, tmp_path: Path, monkeypatch) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        db = _rebuild_index(tmp_path, monkeypatch)
        report = health(db, tmp_path, threshold_commits=10, threshold_days=30)
        assert hasattr(report, "stale_decisions")
        assert hasattr(report, "ungoverned_hotspots")
        assert report.threshold_commits == 10
        assert report.threshold_days == 30


# ── CLI integration ───────────────────────────────────────


class TestHealthCLI:
    def test_clean_repo_exits_zero(self, tmp_path: Path, monkeypatch) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        _rebuild_index(tmp_path, monkeypatch)
        import argparse

        from decree.commands.health import health_run

        args = argparse.Namespace(
            project=str(tmp_path),
            json=False,
            threshold_commits=10,
            threshold_days=30,
        )
        rc = health_run(args)
        assert rc == 0

    def test_findings_exit_one(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        _rebuild_index(tmp_path, monkeypatch)
        for i in range(15):
            _commit(tmp_path, "src/legacy.py", f"v{i}\n", f"edit {i}")
        import argparse

        from decree.commands.health import health_run

        args = argparse.Namespace(
            project=str(tmp_path),
            json=False,
            threshold_commits=10,
            threshold_days=30,
        )
        rc = health_run(args)
        out = capsys.readouterr().out
        assert rc == 1
        assert "src/legacy.py" in out

    def test_json_output_is_schema_stable(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        _bootstrap_repo(tmp_path, ["src/governed.py"])
        _rebuild_index(tmp_path, monkeypatch)
        for i in range(15):
            _commit(tmp_path, "src/legacy.py", f"v{i}\n", f"edit {i}")
        import argparse

        from decree.commands.health import health_run

        args = argparse.Namespace(
            project=str(tmp_path),
            json=True,
            threshold_commits=10,
            threshold_days=30,
        )
        rc = health_run(args)
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 1
        assert set(payload.keys()) >= {
            "stale_decisions",
            "ungoverned_hotspots",
            "threshold_commits",
            "threshold_days",
        }

    def test_no_git_repo_no_ops(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        # decree.toml but no git
        (tmp_path / "decree.toml").write_text(_decree_toml())
        monkeypatch.chdir(tmp_path)
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        import argparse

        from decree.commands.health import health_run

        args = argparse.Namespace(
            project=str(tmp_path),
            json=False,
            threshold_commits=10,
            threshold_days=30,
        )
        rc = health_run(args)
        captured = capsys.readouterr()
        assert rc == 0
        # info() prints to stderr in decree.log
        assert "not a git repository" in captured.err
