"""SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D — observed_governs + dead-governance.

Temp git-repo fixtures in the same style as tests/test_health.py. The critical
regressions are the reviewer's traps: a SPEC whose only trailer-linked commit is
the repository ROOT commit must be observed (not a flag-everything generator),
and a directory `governs:` entry written WITHOUT a trailing slash must not be
falsely flagged dead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from decree.commands.health import (
    _report_to_dict,
    dead_governance,
    health,
    unobserved_decisions,
)
from decree.index_db import IndexDB, default_db_path

SPEC_ID = "SPEC-00000000000000000000000001"
TRAILER = f"Implements: {SPEC_ID}"

_DECREE_TOML = """\
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


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)


def _spec_path(repo: Path) -> Path:
    return repo / "decree" / "spec" / "spec-00000000000000000000000001-test.md"


def _write_spec(repo: Path, governs: list[str]) -> None:
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    _spec_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _spec_path(repo).write_text(
        f"---\nid: {SPEC_ID}\nstatus: implemented\ndate: 2026-05-10\n"
        f"governs:\n{governs_yaml}\n---\n\n# {SPEC_ID} test\n\n## Overview\n\nProse.\n"
    )


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True)


def _commit_file(repo: Path, path: str, content: str, message: str) -> None:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", path], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True)


def _make_repo(repo: Path, *, governs: list[str], files: dict[str, str], root_message: str = "init") -> None:
    """Repo with decree.toml + a SPEC governing `governs`, `files` written, one
    root commit carrying `root_message` (which may include an Implements trailer)."""
    _git_init(repo)
    (repo / "decree.toml").write_text(_DECREE_TOML)
    _write_spec(repo, governs)
    for path, content in files.items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    _commit_all(repo, root_message)


def _rebuild(repo: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(repo)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(repo))
    db.rebuild(repo)
    return db


def _observed_paths(db: IndexDB, decision_id: str = SPEC_ID) -> set[str]:
    return {
        row[0]
        for row in db.db.conn.execute(  # type: ignore[attr-defined]
            "SELECT path FROM observed_governs WHERE decision_id = ?", (decision_id,)
        )
    }


class TestDeadGovernance:
    def test_flags_declared_path_no_linked_commit_touched(self, tmp_path: Path, monkeypatch) -> None:
        _make_repo(tmp_path, governs=["src/a.py", "src/b.py"], files={"src/a.py": "x", "src/b.py": "y"})
        _commit_file(tmp_path, "src/a.py", "x2", f"feat: a\n\n{TRAILER}")
        findings = dead_governance(_rebuild(tmp_path, monkeypatch))
        assert len(findings) == 1
        assert findings[0].decision_id == SPEC_ID
        assert findings[0].paths == ("src/b.py",)
        assert findings[0].linked_commit_count == 1

    def test_root_commit_is_observed_not_dead(self, tmp_path: Path, monkeypatch) -> None:
        # M1: the SPEC's only trailer-linked commit IS the repo root commit.
        # With per-sha `git diff-tree` this would return empty → falsely dead.
        _make_repo(tmp_path, governs=["src/a.py"], files={"src/a.py": "x"}, root_message=f"feat: init\n\n{TRAILER}")
        db = _rebuild(tmp_path, monkeypatch)
        assert dead_governance(db) == []
        assert "src/a.py" in _observed_paths(db)
        assert SPEC_ID not in unobserved_decisions(db)

    def test_slashless_directory_not_dead(self, tmp_path: Path, monkeypatch) -> None:
        # M2: a directory governs entry WITHOUT a trailing slash, touched under it.
        _make_repo(tmp_path, governs=["src/auth"], files={"src/auth/login.py": "x"})
        _commit_file(tmp_path, "src/auth/login.py", "x2", f"feat: a\n\n{TRAILER}")
        assert dead_governance(_rebuild(tmp_path, monkeypatch)) == []

    def test_symbol_entry_never_flagged(self, tmp_path: Path, monkeypatch) -> None:
        # S2: a symbol-scoped entry is unobservable at file grain → never dead.
        _make_repo(tmp_path, governs=["src/foo.py#Bar"], files={"src/foo.py": "x", "src/other.py": "y"})
        _commit_file(tmp_path, "src/other.py", "y2", f"feat: a\n\n{TRAILER}")
        assert dead_governance(_rebuild(tmp_path, monkeypatch)) == []

    def test_unobserved_when_no_linked_commit(self, tmp_path: Path, monkeypatch) -> None:
        # S3: governs a path but no commit carries its trailer → unobserved, not dead.
        _make_repo(tmp_path, governs=["src/a.py"], files={"src/a.py": "x"})
        db = _rebuild(tmp_path, monkeypatch)
        assert dead_governance(db) == []
        assert SPEC_ID in unobserved_decisions(db)

    def test_json_shape_and_coverage(self, tmp_path: Path, monkeypatch) -> None:
        _make_repo(tmp_path, governs=["src/a.py", "src/b.py"], files={"src/a.py": "x", "src/b.py": "y"})
        _commit_file(tmp_path, "src/a.py", "x2", f"feat: a\n\n{TRAILER}")
        d = _report_to_dict(health(_rebuild(tmp_path, monkeypatch), tmp_path, 10, 30))
        assert d["dead_governance"] == [{"decision_id": SPEC_ID, "paths": ["src/b.py"], "linked_commit_count": 1}]
        assert d["unobserved_decisions"] == []
        assert isinstance(d["observed_as_of"], str) and d["observed_as_of"]


class TestObservedGoverns:
    def test_excludes_lockfiles_and_corpus_docs(self, tmp_path: Path, monkeypatch) -> None:
        _make_repo(tmp_path, governs=["src/a.py"], files={"src/a.py": "x"})
        # One trailered commit touching real code, a lockfile, and the SPEC doc.
        (tmp_path / "uv.lock").write_text("lock\n")
        (tmp_path / "src" / "a.py").write_text("x2\n")
        _spec_path(tmp_path).write_text(_spec_path(tmp_path).read_text() + "\nedit\n")
        _commit_all(tmp_path, f"feat: mix\n\n{TRAILER}")
        observed = _observed_paths(_rebuild(tmp_path, monkeypatch))
        assert "src/a.py" in observed
        assert "uv.lock" not in observed
        assert not any(p.startswith("decree/") for p in observed)

    def test_empty_without_trailers(self, tmp_path: Path, monkeypatch) -> None:
        # S5: commits exist but none carry a decree trailer → `commits` AND
        # `observed_governs` are both empty (wiped together, no desync).
        _make_repo(tmp_path, governs=["src/a.py"], files={"src/a.py": "x"})
        _commit_file(tmp_path, "src/a.py", "x2", "feat: a (no trailer)")
        db = _rebuild(tmp_path, monkeypatch)
        conn = db.db.conn  # type: ignore[attr-defined]
        assert conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM observed_governs").fetchone()[0] == 0
