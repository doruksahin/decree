"""File-level parallel-development proof for the sprint directory store (no git).

Two copies of a project stand in for two worktrees. The invariant under test is
structural: each `decree new spec` touches only its own new document file and
its own live membership file, so parallel change-sets are disjoint and a union
merge cannot conflict. The git-level single-file conflict case is covered by
the repo's e2e simulation, not here.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from decree.commands import lint, new, progress, sprint
from decree.config import get_project_root, load_doc_types
from decree.sprints import load_view, validate_ledger


def _write_config(root: Path) -> None:
    (root / "decree.toml").write_text(
        """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = []

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
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
warn_on_reference = ["rejected"]
required_sections = []

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []

[types.adr.actions]
accept = "accepted"
reject = "rejected"

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = []

[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
approve = "approved"
implement = "implemented"
"""
    )
    for name in ("prd", "adr", "spec"):
        (root / "decree" / name).mkdir(parents=True)


def _new_args(**overrides):
    data = {
        "doc_type": "spec",
        "title": "New Capability",
        "backlog": False,
        "draft_pool": False,
        "reason": None,
        "bucket": "sprint-work",
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _progress_args(**overrides):
    data = {
        "json": True,
        "doc": None,
        "chain": None,
        "governs": None,
        "changed": False,
        "base": None,
        "sprint": None,
        "all_sprints": False,
        "backlog": False,
        "draft_pool": False,
        "corpus": False,
        "include_context": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _reset_root_caches() -> None:
    get_project_root.cache_clear()
    load_doc_types.cache_clear()


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _diff_paths(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    """Paths added, removed, or modified between two snapshots."""
    return {path for path in set(before) | set(after) if before.get(path) != after.get(path)}


def _live_stem(paths: set[str]) -> str:
    return next(Path(path).stem for path in paths if path.startswith("decree/sprints/live/"))


def test_parallel_creations_touch_disjoint_paths_and_union_merge_lints_clean(tmp_path, monkeypatch, capsys) -> None:
    project_a = tmp_path / "worktree-a"
    project_a.mkdir()
    _write_config(project_a)
    monkeypatch.chdir(project_a)
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0
    assert new.run(_new_args(title="Base Spec")) == 0
    base = _tree_snapshot(project_a)
    base_spec = _live_stem(set(base))

    project_b = tmp_path / "worktree-b"
    shutil.copytree(project_a, project_b)

    assert new.run(_new_args(title="Feature Alpha")) == 0
    changes_a = _diff_paths(base, _tree_snapshot(project_a))

    monkeypatch.chdir(project_b)
    _reset_root_caches()
    assert new.run(_new_args(title="Feature Beta")) == 0
    changes_b = _diff_paths(base, _tree_snapshot(project_b))

    # The invariant: each creation writes exactly its own document file and its
    # own live membership file — nothing shared (state.yaml stays untouched) —
    # so the two change-sets are disjoint by construction.
    assert len(changes_a) == 2
    assert len(changes_b) == 2
    assert changes_a.isdisjoint(changes_b)
    for changes in (changes_a, changes_b):
        assert sum(1 for path in changes if path.endswith(".md")) == 1
        assert sum(1 for path in changes if path.startswith("decree/sprints/live/")) == 1

    spec_a = _live_stem(changes_a)
    spec_b = _live_stem(changes_b)

    # Union-copy B's new files into A — the file-level shape of a conflict-free merge.
    for rel in sorted(changes_b):
        target = project_a / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project_b / rel, target)

    monkeypatch.chdir(project_a)
    _reset_root_caches()
    capsys.readouterr()
    assert lint.run(argparse.Namespace(check_attachments=False)) == 0

    view = load_view(project_a)
    assert {item.document for item in view.active_open_items} == {base_spec, spec_a, spec_b}

    capsys.readouterr()
    assert progress.run(_progress_args()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"].startswith("active sprint")
    assert {doc["doc_id"] for doc in payload["documents"]} == {base_spec, spec_a, spec_b}


def test_divergent_scope_copies_surface_mismatch_error_after_union(tmp_path, monkeypatch, capsys) -> None:
    """The same document enrolled with different scopes in two copies collapses
    onto one live filename; keeping both bodies in one tree requires a second
    (mismatched) filename, which post-merge lint reports as an error — no crash."""
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0
    assert new.run(_new_args(title="Contested Spec")) == 0
    doc_id = next(iter(load_view(tmp_path).live))

    divergent = tmp_path / "decree" / "sprints" / "live" / "SPEC-00000000000000000000000042.yaml"
    divergent.write_text(
        f"document: {doc_id}\n"
        "scope: backlog\n"
        "kind: execution\n"
        "source: manual\n"
        "added: '2026-07-01'\n"
        "since: '2026-07-01'\n"
        "reason: divergent copy kept it out of the sprint\n"
    )

    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())
    assert any(f"filename stem must equal document field {doc_id}" in e for e in result.errors)
    assert any("live document appears in both" in e for e in result.errors)

    capsys.readouterr()
    assert lint.run(argparse.Namespace(check_attachments=False)) == 1
    assert "filename stem must equal document field" in capsys.readouterr().out


def test_sequential_new_runs_write_independent_live_files_and_complete_touches_one(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0

    live_dir = tmp_path / "decree" / "sprints" / "live"
    assert new.run(_new_args(title="First Spec")) == 0
    first_id = next(path.stem for path in live_dir.glob("*.yaml"))
    assert new.run(_new_args(title="Second Spec")) == 0
    stems = {path.stem for path in live_dir.glob("*.yaml")}
    assert len(stems) == 2
    second_id = next(iter(stems - {first_id}))

    second_bytes = (live_dir / f"{second_id}.yaml").read_bytes()
    assert sprint.run(argparse.Namespace(sprint_action="complete", document=first_id, commit=["abc1234"])) == 0

    # complete rewrites only the completed item's own live file.
    assert (live_dir / f"{second_id}.yaml").read_bytes() == second_bytes
    view = load_view(tmp_path)
    first = view.live[first_id]
    assert first.outcome is not None
    assert first.outcome["kind"] == "completed"
    assert first.outcome["evidence"] == {"commits": ["abc1234"]}
    assert view.live[second_id].outcome is None
    assert {item.document for item in view.active_open_items} == {second_id}
