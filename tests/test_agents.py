"""Tests for `decree agents install/status`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from decree.commands.agents import install_agent_skills, run, status_agent_skills
from decree.commands.hook import HOOK_MARKER


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "decree.toml").write_text(
        """[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "implemented"]
warn_on_reference = []
[types.spec.transitions]
draft = ["implemented"]
implemented = []
[types.spec.actions]
implement = "implemented"
"""
    )
    (tmp_path / "decree" / "spec").mkdir(parents=True)
    return tmp_path


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "agents_action": "install",
        "target": "all",
        "scope": "project",
        "dry_run": False,
        "force": False,
        "hooks": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_project_codex_install_writes_packaged_skills(project: Path) -> None:
    results = install_agent_skills(target_value="codex", scope="project", project_root=project)

    assert {result.status for result in results} == {"installed"}
    assert (project / ".codex" / "skills" / "decree-ddd" / "SKILL.md").exists()
    assert (project / ".codex" / "skills" / "decree-governs-suggest" / "SKILL.md").exists()
    assert "decree DDD" in (project / ".codex" / "skills" / "decree-ddd" / "SKILL.md").read_text()


def test_project_claude_install_writes_packaged_skills(project: Path) -> None:
    results = install_agent_skills(target_value="claude", scope="project", project_root=project)

    assert {result.status for result in results} == {"installed"}
    assert (project / ".claude" / "skills" / "decree-ddd" / "SKILL.md").exists()
    assert (project / ".claude" / "skills" / "decree-governs-suggest" / "SKILL.md").exists()


def test_target_all_writes_both_hosts(project: Path) -> None:
    results = install_agent_skills(target_value="all", scope="project", project_root=project)

    assert len(results) == 4
    assert (project / ".codex" / "skills" / "decree-ddd" / "SKILL.md").exists()
    assert (project / ".claude" / "skills" / "decree-ddd" / "SKILL.md").exists()


def test_user_scope_writes_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"

    results = install_agent_skills(target_value="codex", scope="user", project_root=None, home=home)

    assert {result.status for result in results} == {"installed"}
    assert (home / ".codex" / "skills" / "decree-ddd" / "SKILL.md").exists()


def test_existing_identical_files_are_unchanged(project: Path) -> None:
    install_agent_skills(target_value="codex", scope="project", project_root=project)

    results = install_agent_skills(target_value="codex", scope="project", project_root=project)

    assert {result.status for result in results} == {"unchanged"}


def test_existing_different_files_are_skipped_without_force(project: Path) -> None:
    custom = project / ".codex" / "skills" / "decree-ddd" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("custom skill\n")

    results = install_agent_skills(target_value="codex", scope="project", project_root=project)

    skipped = [result for result in results if result.skill == "decree-ddd"]
    assert skipped[0].status == "skipped"
    assert "pass --force" in (skipped[0].reason or "")
    assert custom.read_text() == "custom skill\n"


def test_force_overwrites_existing_different_files(project: Path) -> None:
    custom = project / ".codex" / "skills" / "decree-ddd" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("custom skill\n")

    results = install_agent_skills(target_value="codex", scope="project", project_root=project, force=True)

    updated = [result for result in results if result.skill == "decree-ddd"]
    assert updated[0].status == "updated"
    assert "decree DDD" in custom.read_text()


def test_dry_run_writes_nothing(project: Path) -> None:
    results = install_agent_skills(target_value="all", scope="project", project_root=project, dry_run=True)

    assert {result.status for result in results} == {"would-install"}
    assert not (project / ".codex").exists()
    assert not (project / ".claude").exists()


def test_status_reports_missing_and_installed(project: Path) -> None:
    missing = status_agent_skills(target_value="codex", scope="project", project_root=project)
    assert {result.reason for result in missing} == {"missing"}

    install_agent_skills(target_value="codex", scope="project", project_root=project)
    installed = status_agent_skills(target_value="codex", scope="project", project_root=project)
    assert {result.status for result in installed} == {"unchanged"}
    assert {result.reason for result in installed} == {None}


def test_run_hooks_installs_claude_stop_hook(monkeypatch: pytest.MonkeyPatch, project: Path) -> None:
    monkeypatch.chdir(project)

    rc = run(_args(target="claude", hooks=True))

    assert rc == 0
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    hook_commands = settings["hooks"]["Stop"][0]["hooks"]
    assert hook_commands[0]["_decree_marker"] == HOOK_MARKER


def test_run_rejects_hooks_for_user_scope(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(project)

    rc = run(_args(target="claude", scope="user", hooks=True))

    assert rc == 1
    assert not (project / ".claude").exists()
