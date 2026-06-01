"""Tests for `decree commit` — git-trailer wrapper (SPEC-00000000000000000000000006)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from decree.commands.commit import (
    apply_trailers,
    build_trailers_arg,
    commit_run,
    infer_active_spec,
)
from decree.index_db import IndexDB, default_db_path

# ── Fixtures ───────────────────────────────────────────────


def _decree_toml() -> str:
    """Minimal config — same shape as tests/test_index_db.py uses."""
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
    for sub in ("prd", "spec"):
        (tmp_path / "decree" / sub).mkdir(parents=True)
    return tmp_path


def _write_spec(
    project: Path,
    spec_id: str,
    status: str,
    governs: list[str],
    *,
    primary_acs: list[tuple[str, bool]] | None = None,
) -> None:
    """Write a SPEC file. primary_acs = [(text, done), ...]"""
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    ac_block = ""
    if primary_acs:
        ac_lines = "\n".join(f"- [{'x' if done else ' '}] {text}" for text, done in primary_acs)
        ac_block = f"\n## Acceptance Criteria\n\n{ac_lines}\n"
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
{ac_block}
"""
    (project / "decree" / "spec" / f"{spec_id.lower()}-test.md").write_text(content)


def _index(project: Path) -> IndexDB:
    """Build & return the IndexDB for tests that need governs/AC lookups."""
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


def _namespace(
    project: Path,
    *,
    message: str | None = None,
    implements: list[str] | None = None,
    refs: list[str] | None = None,
    fixes: list[str] | None = None,
    no_infer: bool = False,
    amend: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project=str(project),
        message=message,
        implements=implements,
        refs=refs,
        fixes=fixes,
        no_infer=no_infer,
        amend=amend,
    )


# ── build_trailers_arg ──────────────────────────────────────


class TestBuildTrailersArg:
    def test_empty(self):
        assert build_trailers_arg(None, None, None) == []
        assert build_trailers_arg([], [], []) == []

    def test_implements_single(self):
        assert build_trailers_arg(["SPEC-00000000000000000000000005"], None, None) == [
            "--trailer",
            "Implements: SPEC-00000000000000000000000005",
        ]

    def test_implements_multi(self):
        out = build_trailers_arg(["SPEC-00000000000000000000000005", "SPEC-00000000000000000000000006"], None, None)
        assert out == [
            "--trailer",
            "Implements: SPEC-00000000000000000000000005",
            "--trailer",
            "Implements: SPEC-00000000000000000000000006",
        ]

    def test_all_three_kinds(self):
        out = build_trailers_arg(
            ["SPEC-00000000000000000000000005"], ["ADR-00000000000000000000000002"], ["SPEC-00000000000000000000000001"]
        )
        assert "--trailer" in out
        assert "Implements: SPEC-00000000000000000000000005" in out
        assert "Refs: ADR-00000000000000000000000002" in out
        assert "Fixes: SPEC-00000000000000000000000001" in out

    def test_rejects_legacy_numeric_id(self):
        with pytest.raises(ValueError, match="TYPE-ULID"):
            build_trailers_arg(["SPEC-006"], None, None)


# ── apply_trailers (via real git interpret-trailers) ────────


class TestApplyTrailers:
    def test_appends_implements(self, git_project: Path):
        msg = "feat: add foo\n\nSome body text."
        trailers = build_trailers_arg(["SPEC-00000000000000000000000005"], None, None)
        out = apply_trailers(git_project, msg, trailers)
        assert "Implements: SPEC-00000000000000000000000005" in out
        assert "feat: add foo" in out

    def test_no_trailers_unchanged(self, git_project: Path):
        msg = "feat: add foo\n\nbody"
        assert apply_trailers(git_project, msg, []) == msg

    def test_multi_implements_produces_two_lines(self, git_project: Path):
        msg = "feat: add foo"
        trailers = build_trailers_arg(
            ["SPEC-00000000000000000000000005", "SPEC-00000000000000000000000006"], None, None
        )
        out = apply_trailers(git_project, msg, trailers)
        assert "Implements: SPEC-00000000000000000000000005" in out
        assert "Implements: SPEC-00000000000000000000000006" in out


# ── infer_active_spec ───────────────────────────────────────


class TestInferActiveSpec:
    def test_unique_winner(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "draft", ["src/foo.py"])
        db = _index(git_project)
        result = infer_active_spec(db, ["src/foo.py"])
        assert result == "SPEC-00000000000000000000000001"

    def test_directory_prefix_match(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "draft", ["src/foo/"])
        db = _index(git_project)
        result = infer_active_spec(db, ["src/foo/bar.py"])
        assert result == "SPEC-00000000000000000000000001"

    def test_no_match_returns_none(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "draft", ["src/foo.py"])
        db = _index(git_project)
        result = infer_active_spec(db, ["unrelated/path.py"])
        assert result is None

    def test_empty_staged_returns_none(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "draft", ["src/foo.py"])
        db = _index(git_project)
        assert infer_active_spec(db, []) is None

    def test_terminal_status_excluded(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "implemented", ["src/foo.py"])
        db = _index(git_project)
        # `implemented` is terminal-success → priority 0, filtered out.
        result = infer_active_spec(db, ["src/foo.py"])
        assert result is None

    def test_tiebreak_by_unchecked_acs(self, git_project: Path):
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000001",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac1", True), ("ac2", True)],
        )
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000002",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac1", False), ("ac2", False), ("ac3", False)],
        )
        db = _index(git_project)
        # SPEC-00000000000000000000000002 has more unchecked → wins.
        result = infer_active_spec(db, ["src/foo.py"])
        assert result == "SPEC-00000000000000000000000002"

    def test_ambiguous_returns_candidate_list(self, git_project: Path):
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000001",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac1", False)],
        )
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000002",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac1", False)],
        )
        db = _index(git_project)
        result = infer_active_spec(db, ["src/foo.py"])
        assert isinstance(result, list)
        ids = {c.decision_id for c in result}
        assert ids == {"SPEC-00000000000000000000000001", "SPEC-00000000000000000000000002"}


# ── commit_run integration ─────────────────────────────────


class TestCommitRun:
    def _stage(self, project: Path, rel_path: str, content: str = "x") -> None:
        full = project / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        _git(project, "add", rel_path)

    def _last_commit_message(self, project: Path) -> str:
        return _git(project, "log", "-1", "--format=%B").stdout

    def test_explicit_implements_lands_trailer(self, git_project: Path):
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo", implements=["SPEC-00000000000000000000000005"])
        rc = commit_run(args)
        assert rc == 0
        assert "Implements: SPEC-00000000000000000000000005" in self._last_commit_message(git_project)

    def test_invalid_implements_exits_before_git_commit(self, git_project: Path, capsys):
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo", implements=["SPEC-006"])

        rc = commit_run(args)

        assert rc == 1
        assert "TYPE-ULID" in capsys.readouterr().err

    def test_multi_implements(self, git_project: Path):
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(
            git_project,
            message="feat: add foo",
            implements=["SPEC-00000000000000000000000005", "SPEC-00000000000000000000000006"],
        )
        rc = commit_run(args)
        assert rc == 0
        body = self._last_commit_message(git_project)
        assert "Implements: SPEC-00000000000000000000000005" in body
        assert "Implements: SPEC-00000000000000000000000006" in body

    def test_refs_and_fixes(self, git_project: Path):
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(
            git_project,
            message="feat: add foo",
            refs=["ADR-00000000000000000000000002"],
            fixes=["SPEC-00000000000000000000000001"],
            no_infer=True,
        )
        rc = commit_run(args)
        assert rc == 0
        body = self._last_commit_message(git_project)
        assert "Refs: ADR-00000000000000000000000002" in body
        assert "Fixes: SPEC-00000000000000000000000001" in body

    def test_inference_unique_winner(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000005", "draft", ["src/foo.py"])
        _index(git_project)  # build index from frontmatter
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo")
        rc = commit_run(args)
        assert rc == 0
        assert "Implements: SPEC-00000000000000000000000005" in self._last_commit_message(git_project)

    def test_no_infer_skips_inference(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000005", "draft", ["src/foo.py"])
        _index(git_project)
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo", no_infer=True)
        rc = commit_run(args)
        assert rc == 0
        assert "Implements:" not in self._last_commit_message(git_project)

    def test_missing_index_requires_explicit_choice(self, git_project: Path, capsys):
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo")

        rc = commit_run(args)

        assert rc == 1
        assert "index not built" in capsys.readouterr().err

    def test_ambiguous_inference_exits_1(self, git_project: Path, capsys):
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000001",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac", False)],
        )
        _write_spec(
            git_project,
            "SPEC-00000000000000000000000002",
            "draft",
            ["src/foo.py"],
            primary_acs=[("ac", False)],
        )
        _index(git_project)
        self._stage(git_project, "src/foo.py", "print(1)\n")
        args = _namespace(git_project, message="feat: add foo")
        rc = commit_run(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Ambiguous" in out
        assert "SPEC-00000000000000000000000001" in out and "SPEC-00000000000000000000000002" in out

    def test_empty_staged_set_refuses(self, git_project: Path, capsys):
        args = _namespace(git_project, message="feat: empty")
        rc = commit_run(args)
        assert rc == 1
        # error() writes to stderr — check both
        captured = capsys.readouterr()
        assert "no staged changes" in (captured.out + captured.err).lower()

    def test_amend_passes_through(self, git_project: Path):
        # First commit
        self._stage(git_project, "src/foo.py", "print(1)\n")
        commit_run(_namespace(git_project, message="initial", no_infer=True))
        # Amend
        self._stage(git_project, "src/foo.py", "print(2)\n")
        rc = commit_run(_namespace(git_project, message="amended", amend=True))
        assert rc == 0
        # The latest commit's subject is now "amended".
        assert "amended" in self._last_commit_message(git_project)

    def test_post_commit_index_sync(self, git_project: Path):
        _write_spec(git_project, "SPEC-00000000000000000000000005", "draft", ["src/foo.py"])
        _index(git_project)
        self._stage(git_project, "src/foo.py", "print(1)\n")
        commit_run(_namespace(git_project, message="feat: foo", implements=["SPEC-00000000000000000000000005"]))
        db = IndexDB(default_db_path(git_project))
        rows = list(
            db.db.conn.execute(  # type: ignore[attr-defined]
                "SELECT decision_id, trailer_kind FROM commits WHERE decision_id = 'SPEC-00000000000000000000000005'"
            )
        )
        assert rows
        assert rows[0][1] == "Implements"
