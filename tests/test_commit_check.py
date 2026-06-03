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


# ── Phase 2: CLI (commit_check_run) ─────────────────────────


import argparse  # noqa: E402
import json  # noqa: E402

from decree.commands.commit_check import commit_check_run  # noqa: E402


def _args(**kw) -> argparse.Namespace:
    """Build a commit-check args namespace with sane defaults."""
    base = {
        "diff": None,
        "diff_base": None,
        "message": None,
        "strict": False,
        "min_coverage": None,
        "json": False,
        "project": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _commit_touching(project: Path, rel: str, msg: str) -> str:
    """Create + commit a file (creating parent dirs); return the new HEAD sha."""
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n")
    _git(project, "add", rel)
    _git(project, "commit", "-m", msg)
    return _git(project, "rev-parse", "HEAD").stdout.strip()


def _run(project: Path, capsys, **kw) -> tuple[int, str]:
    """Run commit_check_run from inside `project`; return (exit_code, stdout)."""
    import os

    cwd = os.getcwd()
    os.chdir(project)
    try:
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        rc = commit_check_run(_args(project=str(project), **kw))
    finally:
        os.chdir(cwd)
    out = capsys.readouterr().out
    return rc, out


class TestCommitCheckCLI:
    # ── 2.1 input-mode resolution ──────────────────────────

    def test_staged_without_message_or_base_exits_2(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        rc, _out = _run(git_project, capsys)
        assert rc == 2

    def test_missing_index_exits_2(self, git_project: Path, capsys):
        # No _index() call → no SQLite cache built.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        rc, _out = _run(git_project, capsys, message="ignored")
        assert rc == 2

    def test_bad_project_exits_2(self, tmp_path: Path, capsys):
        # A directory with no decree.toml.
        import os

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            rc = commit_check_run(_args(project=str(tmp_path), message="x"))
        finally:
            os.chdir(cwd)
        assert rc == 2

    # ── 2.2 report + exit codes (diff-base / CI mode) ──────

    def test_covered_diff_base_exit_0(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        rc, out = _run(git_project, capsys, diff_base=base)
        assert rc == 0
        assert "1/1" in out

    def test_uncovered_advisory_exit_0(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(git_project, "src/a.py", "feat: a (no trailer)")
        rc, out = _run(git_project, capsys, diff_base=base)
        assert rc == 0
        assert "0/1" in out
        assert "SPEC-00000000000000000000000001" in out
        assert "src/a.py" in out
        assert "decree commit --implements SPEC-00000000000000000000000001" in out

    def test_uncovered_strict_exit_1(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(git_project, "src/a.py", "feat: a (no trailer)")
        rc, _out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 1

    def test_min_coverage_thresholds(self, git_project: Path, capsys):
        # Two governed paths, one covered → 1/2 = 50%.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/b.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        _commit_touching(git_project, "src/b.py", "feat: b (no trailer)")

        # 50% coverage: >= 50 passes, 51 fails, 0 passes, 100 fails.
        assert _run(git_project, capsys, diff_base=base, min_coverage=50)[0] == 0
        assert _run(git_project, capsys, diff_base=base, min_coverage=51)[0] == 1
        assert _run(git_project, capsys, diff_base=base, min_coverage=0)[0] == 0
        assert _run(git_project, capsys, diff_base=base, min_coverage=100)[0] == 1

    def test_ungoverned_only_exit_0(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(git_project, "src/unrelated.py", "chore: unrelated")
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 0
        assert "no governed changes" in out.lower()

    def test_terminal_spec_governed_no_trailer_exit_0(self, git_project: Path, capsys):
        # implemented (terminal) SPEC → not in-flight → no governed change.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "implemented", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(git_project, "src/a.py", "feat: a (no trailer)")
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 0
        assert "no governed changes" in out.lower()

    # ── 2.1 message mode (commit-msg hook) ─────────────────

    def test_message_mode_covered(self, git_project: Path, capsys):
        # Paths come from a diff file; trailers come from --message.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        diff_path = git_project / "change.diff"
        diff_path.write_text("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -0,0 +1 @@\n+x\n")
        msg_path = git_project / "COMMIT_MSG"
        msg_path.write_text("feat: a\n\nImplements: SPEC-00000000000000000000000001\n")
        rc, out = _run(git_project, capsys, diff=str(diff_path), message=str(msg_path))
        assert rc == 0
        assert "1/1" in out

    # ── 2.3 JSON contract ──────────────────────────────────

    def test_json_contract(self, git_project: Path, capsys):
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/b.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        _commit_touching(git_project, "src/b.py", "feat: b (no trailer)")

        rc, out = _run(git_project, capsys, diff_base=base, json=True)
        payload = json.loads(out)

        assert set(payload.keys()) == {
            "coverage",
            "governed_changes",
            "uncovered",
            "mode",
            "strict",
            "min_coverage",
            "exit",
        }
        assert set(payload["coverage"].keys()) == {"covered", "total", "fraction"}
        assert payload["coverage"] == {"covered": 1, "total": 2, "fraction": 0.5}
        assert payload["mode"] == "diff-base"
        assert payload["strict"] is False
        assert payload["min_coverage"] is None
        assert payload["exit"] == rc == 0

        gcs = sorted(payload["governed_changes"], key=lambda g: g["path"])
        assert gcs[0] == {
            "path": "src/a.py",
            "decision_id": "SPEC-00000000000000000000000001",
            "type": "spec",
            "covered": True,
        }
        # governed_changes entries carry path/decision_id/type/covered only.
        assert set(gcs[1].keys()) == {"path", "decision_id", "type", "covered"}
        assert gcs[1]["path"] == "src/b.py"
        assert gcs[1]["decision_id"] == "SPEC-00000000000000000000000002"
        assert gcs[1]["covered"] is False

        # Exactly one uncovered entry, carrying path/decision_id/title only.
        assert len(payload["uncovered"]) == 1
        unc = payload["uncovered"][0]
        assert set(unc.keys()) == {"path", "decision_id", "title"}
        assert unc["path"] == "src/b.py"
        assert unc["decision_id"] == "SPEC-00000000000000000000000002"
        assert unc["title"]  # non-empty title from the SPEC heading


# ── SPEC matrix: end-to-end coverage of the documented 15-case table ─────────
#
# These drive the real gate path (`commit_check_run` end-to-end, or `coverage`
# over `governed_changes`) rather than asserting on `trailer_ids` in isolation,
# so the matrix is exercised through the same code a real invocation hits.


class TestSpecMatrixEndToEnd:
    def test_case5_refs_trailer_covers_governed(self, git_project: Path, capsys):
        """Case 5: a `Refs:` (not `Implements:`) trailer covers a governed change."""
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nRefs: SPEC-00000000000000000000000001\n",
        )
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 0
        assert "1/1" in out

    def test_case5b_fixes_trailer_covers_governed(self, git_project: Path, capsys):
        """Case 5 (variant): a `Fixes:` trailer also covers a governed change."""
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "fix: a\n\nFixes: SPEC-00000000000000000000000001\n",
        )
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 0
        assert "1/1" in out

    def test_case6_wrong_spec_trailer_leaves_uncovered(self, git_project: Path, capsys):
        """Case 6: a trailer naming the WRONG SPEC leaves the governed change uncovered."""
        # SPEC-…01 governs src/a.py (in-flight). SPEC-…99 exists but does not.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000099", "approved", ["src/other.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000099\n",
        )
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 1
        assert "0/1" in out
        assert "SPEC-00000000000000000000000001" in out

    def test_case7_multivalue_trailer_member_covers(self, git_project: Path, capsys):
        """Case 7: `Implements: A, B` covers a governed change whose decision is B."""
        # Only SPEC-…02 (=B) is in-flight + governs src/b.py; the trailer lists
        # both A and B comma-separated on a single commit. Message mode lets us
        # carry the multi-value trailer cleanly.
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/b.py"])
        _index(git_project)
        diff_path = git_project / "change.diff"
        diff_path.write_text("diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n@@ -0,0 +1 @@\n+x\n")
        msg_path = git_project / "COMMIT_MSG"
        msg_path.write_text(
            "feat: ab\n\nImplements: SPEC-00000000000000000000000001, SPEC-00000000000000000000000002\n"
        )
        rc, out = _run(git_project, capsys, diff=str(diff_path), message=str(msg_path), strict=True)
        assert rc == 0
        assert "1/1" in out

    def test_case11_two_governors_one_cited_is_partial(self, git_project: Path, capsys):
        """Case 11: file governed by TWO in-flight decisions, only one cited → 1/2."""
        # Both SPECs are in-flight and govern the same path src/a.py.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/a.py"])
        db = _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )

        # Sanity: governed_changes yields two pairs for the single path.
        governed = governed_changes(db, ["src/a.py"])
        assert len(governed) == 2
        cov = coverage(governed, {"SPEC-00000000000000000000000001"})
        assert (cov.covered, cov.total) == (1, 2)
        assert [gc.decision_id for gc in cov.uncovered] == ["SPEC-00000000000000000000000002"]

        # End-to-end: 1/2, the uncovered governor listed, exit 1 under --strict.
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 1
        assert "1/2" in out
        assert "SPEC-00000000000000000000000002" in out

    def test_case12_directory_prefix_governance(self, git_project: Path, capsys):
        """Case 12: a decision governing `src/auth/` covers each touched file under it."""
        # Prefix governance: a `governs:` entry ending in `/` matches every path
        # below it (see queries.why prefix_sql).
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/auth/"])
        db = _index(git_project)

        # Two distinct files under the governed directory each become a pair.
        governed = governed_changes(db, ["src/auth/tokens.py", "src/auth/session.py"])
        assert len(governed) == 2
        assert {gc.path for gc in governed} == {"src/auth/tokens.py", "src/auth/session.py"}
        assert {gc.decision_id for gc in governed} == {"SPEC-00000000000000000000000001"}

        # End-to-end: both touched files uncovered without the trailer → exit 1.
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(git_project, "src/auth/tokens.py", "feat: tokens (no trailer)")
        _commit_touching(git_project, "src/auth/session.py", "feat: session (no trailer)")
        rc, out = _run(git_project, capsys, diff_base=base, strict=True)
        assert rc == 1
        assert "0/2" in out

    def test_case15_scalability_smoke(self, git_project: Path, capsys):
        """Case 15 (light): ~50 governed paths complete and report the right total."""
        # One in-flight SPEC governing 50 distinct files; a single commit touches
        # them all and cites the SPEC → all covered, exit 0, total == 50.
        paths = [f"src/mod_{i:02d}.py" for i in range(50)]
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", paths)
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")

        for p in paths:
            target = git_project / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("content\n")
        _git(git_project, "add", "src")
        _git(
            git_project,
            "commit",
            "-m",
            "feat: bulk\n\nImplements: SPEC-00000000000000000000000001\n",
        )

        rc, out = _run(git_project, capsys, diff_base=base)
        assert rc == 0
        assert "50/50" in out


# ── FIX 4: displayed percentage must never contradict the gate ───────────────


class TestDisplayPercentConsistency:
    def test_two_thirds_display_floors_and_matches_gate(self, git_project: Path, capsys):
        """2/3 = 66.67% must display "66%" (floor) so it never implies passing 67."""
        # Three in-flight SPECs each governing one path; two covered → 2/3.
        _write_spec(git_project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000002", "approved", ["src/b.py"])
        _write_spec(git_project, "SPEC-00000000000000000000000003", "approved", ["src/c.py"])
        _index(git_project)
        base = _commit_touching(git_project, "seed.txt", "base")
        _commit_touching(
            git_project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        _commit_touching(
            git_project,
            "src/b.py",
            "feat: b\n\nImplements: SPEC-00000000000000000000000002\n",
        )
        _commit_touching(git_project, "src/c.py", "feat: c (no trailer)")

        # Human output floors 66.67% → "66%", never "67%".
        rc_human, out = _run(git_project, capsys, diff_base=base)
        assert rc_human == 0
        assert "2/3" in out
        assert "66%" in out
        assert "67%" not in out

        # The displayed 66% must not contradict the gate: at --min-coverage 67
        # the gate FAILS (66.67 < 67), consistent with a floored "66%".
        rc_gate = _run(git_project, capsys, diff_base=base, min_coverage=67)[0]
        assert rc_gate == 1
        # And at --min-coverage 66 it passes (66.67 >= 66), also consistent.
        rc_pass = _run(git_project, capsys, diff_base=base, min_coverage=66)[0]
        assert rc_pass == 0
