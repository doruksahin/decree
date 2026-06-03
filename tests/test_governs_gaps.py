"""SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5 — point-of-change governs-gap suggestions.

`intent-check` / `intent-review` gain `--under <decision>`. When a planned/changed
file is one that decision's own trailer-linked commits repeat-touch
(`commit_count >= 2`) but it doesn't declare, the report surfaces a `governs_gap`
+ a soft `declare_governs` recommendation. Advisory: never changes the exit code
or `proceed`, never feeds `why()`. The known `under` deliberately drops v2's
cross-decision filters (owned-elsewhere / shared-infra), so a path another
decision governs still surfaces *for this decision*.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from decree.commands.intent_check import intent_check, intent_check_run
from decree.commands.intent_review import (
    _read_diff_source,
    compute_governs_gaps,
    intent_review,
    parse_diff,
)
from decree.commands.queries import why
from decree.index_db import IndexDB, default_db_path

D = "SPEC-00000000000000000000000001"  # governs src/auth/  (directory)
D2 = "SPEC-00000000000000000000000002"  # governs src/api (slashless) + src/cache.py
D3 = "SPEC-00000000000000000000000003"  # governs src/foo.py#Bar (symbol)

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


def _write_spec(repo: Path, sid: str, ulid: str, slug: str, governs: list[str]) -> None:
    path = repo / "decree" / "spec" / f"spec-{ulid}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    path.write_text(
        f"---\nid: {sid}\nstatus: implemented\ndate: 2026-05-10\n"
        f"governs:\n{governs_yaml}\n---\n\n# {sid}\n\n## Overview\n\nProse.\n"
    )


def _commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for rel, content in files.items():
        full = repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, capture_output=True)


def _impl(sid: str, body: str) -> str:
    return f"{body}\n\nImplements: {sid}"


def _build_corpus(repo: Path) -> None:
    """observed_governs after rebuild:
    D : engine.py(2) login.py(2) README.md(2) tests/test_e.py(2) cache.py(2) single.py(1)
    D2: api/handler.py(2)
    D3: foo.py(2)
    """
    _git_init(repo)
    (repo / "decree.toml").write_text(_DECREE_TOML)
    _write_spec(repo, D, "00000000000000000000000001", "auth", ["src/auth/"])
    _write_spec(repo, D2, "00000000000000000000000002", "api", ["src/api", "src/cache.py"])
    _write_spec(repo, D3, "00000000000000000000000003", "foo", ["src/foo.py#Bar"])
    _commit(
        repo,
        "chore: bootstrap",
        {
            "src/auth/login.py": "v0\n",
            "src/core/engine.py": "v0\n",
            "src/core/single.py": "v0\n",
            "src/cache.py": "v0\n",
            "src/api/handler.py": "v0\n",
            "src/foo.py": "v0\n",
            "README.md": "v0\n",
            "tests/test_e.py": "v0\n",
        },
    )
    repeat = {
        "src/auth/login.py": "x",
        "src/core/engine.py": "x",
        "src/cache.py": "x",
        "README.md": "x",
        "tests/test_e.py": "x",
    }
    _commit(repo, _impl(D, "feat a"), {k: "a\n" for k in repeat})
    _commit(repo, _impl(D, "feat b"), {k: "b\n" for k in repeat})
    _commit(repo, _impl(D, "feat c"), {"src/core/single.py": "c\n"})  # single touch -> cc=1
    _commit(repo, _impl(D2, "api a"), {"src/api/handler.py": "a\n"})
    _commit(repo, _impl(D2, "api b"), {"src/api/handler.py": "b\n"})
    _commit(repo, _impl(D3, "foo a"), {"src/foo.py": "a\n"})
    _commit(repo, _impl(D3, "foo b"), {"src/foo.py": "b\n"})


def _rebuild(repo: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(repo)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(repo))
    db.rebuild(repo)
    return db


def _gap_paths(db, under, paths):
    gaps, err = compute_governs_gaps(db, under, paths)
    return [g.path for g in gaps], err


class TestComputeGovernsGaps:
    def test_repeat_touched_undeclared_surfaces(self, tmp_path, monkeypatch):
        _build_corpus(tmp_path)
        db = _rebuild(tmp_path, monkeypatch)
        paths, err = _gap_paths(db, D, ["src/core/engine.py"])
        assert err is None
        assert paths == ["src/core/engine.py"]

    def test_squash_immune_single_commit_not_surfaced(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D, ["src/core/single.py"])[0] == []  # cc=1

    def test_declared_directory_excluded(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D, ["src/auth/login.py"])[0] == []  # under src/auth/

    def test_declared_slashless_directory_excluded(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D2, ["src/api/handler.py"])[0] == []  # src/api (no slash)

    def test_symbol_entry_does_not_cover_file(self, tmp_path, monkeypatch):
        # D3 declares src/foo.py#Bar; the file observation surfaces (parity with dead-governance).
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D3, ["src/foo.py"])[0] == ["src/foo.py"]

    def test_structural_excluded(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D, ["README.md", "tests/test_e.py"])[0] == []

    def test_not_observed_excluded(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D, ["src/never/touched.py"])[0] == []

    def test_owned_elsewhere_still_surfaces_for_this_decision(self, tmp_path, monkeypatch):
        # src/cache.py is declared by D2, repeat-touched by D. Under D it IS a gap
        # (the known `under` drops the owned-elsewhere filter v2 needs).
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert _gap_paths(db, D, ["src/cache.py"])[0] == ["src/cache.py"]

    def test_no_under_is_empty(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        assert compute_governs_gaps(db, None, ["src/core/engine.py"]) == ((), None)

    def test_unknown_under_is_error(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        gaps, err = compute_governs_gaps(db, "SPEC-00000000000000000000000099", ["src/core/engine.py"])
        assert gaps == () and err and "not found" in err

    def test_ordering_by_commit_count_then_path(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        # cache.py and engine.py both cc=2 -> tie broken by path asc.
        paths, _ = _gap_paths(db, D, ["src/core/engine.py", "src/cache.py"])
        assert paths == ["src/cache.py", "src/core/engine.py"]


class TestIntentIntegration:
    def test_intent_check_surfaces_gap_and_recommendation(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        report = intent_check(db, tmp_path, "edit engine", ["src/core/engine.py"], under=D)
        assert [g.path for g in report.governs_gaps] == ["src/core/engine.py"]
        assert report.under_decision == D and report.under_error is None
        assert any(r.action == "declare_governs" for r in report.recommended_actions)

    def test_intent_review_surfaces_gap(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        report = intent_review(db, tmp_path, ["src/core/engine.py"], under=D)
        assert [g.path for g in report.governs_gaps] == ["src/core/engine.py"]

    def test_advisory_gap_does_not_change_exit_code(self, tmp_path, monkeypatch):
        # A gap alone (no conflicts/stale/live) must exit 0, identical to no-under.
        _built(tmp_path)
        db = _rebuild(tmp_path, monkeypatch)  # noqa: F841 — chdir side effect for the run handler
        base = argparse.Namespace(
            plan="edit engine",
            files=["src/core/engine.py"],
            json=True,
            project=str(tmp_path),
            other_active_files=None,
            with_abstention=False,
            under=None,
        )
        with_under = argparse.Namespace(**{**vars(base), "under": D})
        assert intent_check_run(base) == 0
        assert intent_check_run(with_under) == 0  # gap present, still 0

    def test_unknown_under_exits_2(self, tmp_path, monkeypatch):
        _built(tmp_path)
        _rebuild(tmp_path, monkeypatch)
        args = argparse.Namespace(
            plan="x",
            files=["src/core/engine.py"],
            json=True,
            project=str(tmp_path),
            other_active_files=None,
            with_abstention=False,
            under="SPEC-00000000000000000000000099",
        )
        assert intent_check_run(args) == 2

    def test_never_feeds_why(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        # engine.py surfaces as a gap but is declared by no one -> why() is empty.
        assert [g.path for g in intent_check(db, tmp_path, "x", ["src/core/engine.py"], under=D).governs_gaps]
        assert why(db, "src/core/engine.py") == []


class TestDeletionsAndDiffStructure:
    def test_structured_diff_strips_deletion(self, tmp_path, monkeypatch):
        db = _rebuild(_built(tmp_path), monkeypatch)
        deletion_diff = (
            "diff --git a/src/core/engine.py b/src/core/engine.py\n"
            "deleted file mode 100644\n"
            "--- a/src/core/engine.py\n"
            "+++ /dev/null\n"
        )
        changed = parse_diff(deletion_diff)
        assert "src/core/engine.py" not in changed  # deletion stripped
        report = intent_review(db, tmp_path, changed, under=D)
        assert report.governs_gaps == ()  # the deleted (gap-eligible) path is not proposed

    def test_read_diff_source_marks_name_only_unstructured(self, tmp_path, monkeypatch):
        _built(tmp_path)
        monkeypatch.chdir(tmp_path)
        # default mode (no --diff) -> name-only -> structured False.
        args = argparse.Namespace(diff=None, diff_base=None)
        _paths, _mode, structured = _read_diff_source(args, tmp_path)
        assert structured is False


def _built(tmp_path: Path) -> Path:
    _build_corpus(tmp_path)
    return tmp_path
