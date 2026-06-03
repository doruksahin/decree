"""Tests for `decree commit-check` core library (SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J).

Phase 1: the pure core library only — four functions in
`decree.commands.commit_check`. No argparse/CLI/MCP here.

Corpus building reuses the `git_project` fixture pattern from
`tests/test_commit.py` (a tmp dir that is both a git repo and a decree
project).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from decree.commands.commit_check import (
    coverage,
    governed_changes,
    range_trailer_ids,
    trailer_ids,
)
from decree.index_db import IndexDB, default_db_path

# ── Fixtures (mirrors tests/test_commit.py) ─────────────────


def _decree_toml() -> str:
    return """\
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


def _git(cwd: Path, *args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=check,
        capture_output=True,
        text=True,
        input=input_text,
    )


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A tmp dir that is both a git repo and a decree project."""
    _git(tmp_path, "init", check=False)
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "decree.toml").write_text(_decree_toml())
    (tmp_path / "decree" / "spec").mkdir(parents=True)
    return tmp_path


def _write_spec(project: Path, spec_id: str, status: str, governs: list[str]) -> None:
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    content = f"""---
id: {spec_id}
status: {status}
date: 2026-05-12
governs:
{governs_yaml}
---

# {spec_id} Test SPEC

## Overview

    Some prose.
"""
    (project / "decree" / "spec" / f"{spec_id.lower()}-test.md").write_text(content)


def _index(project: Path) -> IndexDB:
    import os

    cwd = os.getcwd()
    os.chdir(project)
    try:
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        return db
    finally:
        os.chdir(cwd)


# ── governed_changes ────────────────────────────────────────


class TestGovernedChanges:
    def test_only_in_flight_governed_pairs(self, git_project: Path):
        # approved (in-flight) SPEC governs tokens.py; implemented (terminal)
        # SPEC governs legacy.py; other.py is ungoverned.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/auth/tokens.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "implemented", ["src/legacy.py"])
        db = _index(git_project)

        result = governed_changes(db, ["src/auth/tokens.py", "src/legacy.py", "src/other.py"])

        assert len(result) == 1
        (gc,) = result
        assert gc.path == "src/auth/tokens.py"
        assert gc.decision_id == "SPEC-00000000000000000000000001"
        assert gc.type == "spec"
        assert gc.title


# ── trailer_ids ─────────────────────────────────────────────


class TestTrailerIds:
    def test_all_kinds_and_multivalue(self):
        msg = (
            "feat: do a thing\n\n"
            "body text\n\n"
            "Implements: SPEC-0000000000000000000000000A\n"
            "Refs: SPEC-0000000000000000000000000B\n"
            "Fixes: SPEC-0000000000000000000000000C\n"
            "Implements: SPEC-0000000000000000000000000D, SPEC-0000000000000000000000000E\n"
        )
        assert trailer_ids(msg) == {
            "SPEC-0000000000000000000000000A",
            "SPEC-0000000000000000000000000B",
            "SPEC-0000000000000000000000000C",
            "SPEC-0000000000000000000000000D",
            "SPEC-0000000000000000000000000E",
        }

    def test_no_trailers_is_empty(self):
        assert trailer_ids("feat: nothing here\n\njust a body, no trailers\n") == set()


# ── range_trailer_ids ───────────────────────────────────────


class TestRangeTrailerIds:
    def test_union_across_range(self, git_project: Path):
        # base commit
        (git_project / "a.txt").write_text("a\n")
        _git(git_project, "add", "a.txt")
        _git(git_project, "commit", "-m", "base")
        base = _git(git_project, "rev-parse", "HEAD").stdout.strip()

        # commit 1 in range carries a trailer
        (git_project / "b.txt").write_text("b\n")
        _git(git_project, "add", "b.txt")
        _git(
            git_project,
            "commit",
            "-m",
            "feat: b\n\nImplements: SPEC-0000000000000000000000000A\n",
        )

        # commit 2 in range carries no trailer
        (git_project / "c.txt").write_text("c\n")
        _git(git_project, "add", "c.txt")
        _git(git_project, "commit", "-m", "chore: c")

        assert range_trailer_ids(git_project, base) == {"SPEC-0000000000000000000000000A"}


# ── coverage ────────────────────────────────────────────────


class TestCoverage:
    def test_partial_coverage(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/auth/tokens.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/billing.py"])
        db = _index(git_project)
        governed = governed_changes(db, ["src/auth/tokens.py", "src/billing.py"])
        assert len(governed) == 2

        result = coverage(governed, {"SPEC-00000000000000000000000001"})

        assert result.covered == 1
        assert result.total == 2
        assert result.fraction == 0.5
        assert len(result.uncovered) == 1
        assert result.uncovered[0].decision_id == "SPEC-00000000000000000000000002"

    def test_zero_governed_is_clean(self):
        result = coverage([], set())
        assert result.total == 0
        assert result.covered == 0
        assert result.uncovered == []
        # No divide-by-zero; vacuously fully covered.
        assert result.fraction == 1.0
