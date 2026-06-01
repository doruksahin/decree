"""Tests for `decree hook install/uninstall/status`."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

from decree.commands.hook import (
    HOOK_MARKER,
    hook_status,
    install_claude_hook,
    run,
    uninstall_claude_hook,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal decree-enabled project (just decree.toml; tests don't need docs)."""
    (tmp_path / "decree.toml").write_text(
        """[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted"]
warn_on_reference = []
[types.adr.transitions]
proposed = ["accepted"]
accepted = []
[types.adr.actions]
accept = "accepted"
"""
    )
    (tmp_path / "decree" / "adr").mkdir(parents=True)
    return tmp_path


class TestInstall:
    def test_install_creates_settings_file(self, project: Path):
        install_claude_hook(project)
        settings_path = project / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data
        assert "Stop" in data["hooks"]
        assert len(data["hooks"]["Stop"]) == 1
        entry = data["hooks"]["Stop"][0]
        assert entry["hooks"][0]["_decree_marker"] == HOOK_MARKER

    def test_install_is_idempotent(self, project: Path):
        install_claude_hook(project)
        install_claude_hook(project)
        install_claude_hook(project)
        data = json.loads((project / ".claude" / "settings.json").read_text())
        # Still only one entry, no duplicates
        assert len(data["hooks"]["Stop"]) == 1

    def test_install_preserves_user_entries(self, project: Path):
        # User pre-existing settings with their own Stop hook
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo user-thing"}]}]}}
            )
        )
        install_claude_hook(project)
        data = json.loads(settings_path.read_text())
        # Both entries present, user's untouched
        assert len(data["hooks"]["Stop"]) == 2
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo user-thing"
        assert "_decree_marker" not in data["hooks"]["Stop"][0]["hooks"][0]
        assert data["hooks"]["Stop"][1]["hooks"][0]["_decree_marker"] == HOOK_MARKER

    def test_install_refuses_malformed_json(self, project: Path):
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{ this is not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            install_claude_hook(project)

    def test_install_refuses_array_at_top_level(self, project: Path):
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("[1,2,3]")
        with pytest.raises(ValueError, match="must be a JSON object"):
            install_claude_hook(project)

    def test_install_refuses_non_object_hooks(self, project: Path):
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"hooks": "not an object"}))
        with pytest.raises(ValueError, match="must be an object"):
            install_claude_hook(project)


class TestUninstall:
    def test_uninstall_removes_only_decree_entries(self, project: Path):
        # Install user entry + decree entry
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo user-thing"}]}]}}
            )
        )
        install_claude_hook(project)
        # Sanity: both entries
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["Stop"]) == 2

        # Uninstall
        removed = uninstall_claude_hook(project)
        assert removed == 1
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["Stop"]) == 1
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo user-thing"

    def test_uninstall_no_settings_file(self, project: Path):
        # Should be a clean no-op
        removed = uninstall_claude_hook(project)
        assert removed == 0

    def test_uninstall_no_decree_entries(self, project: Path):
        # Settings exist but no decree entries
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo user-thing"}]}]}}
            )
        )
        removed = uninstall_claude_hook(project)
        assert removed == 0
        # User entry still there
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["Stop"]) == 1

    def test_uninstall_clears_empty_event_key(self, project: Path):
        install_claude_hook(project)
        uninstall_claude_hook(project)
        data = json.loads((project / ".claude" / "settings.json").read_text())
        # Stop key removed because no entries remain
        assert "hooks" not in data or "Stop" not in data.get("hooks", {})


class TestStatus:
    def test_status_not_installed(self, project: Path):
        installed, _path = hook_status(project)
        assert not installed

    def test_status_installed(self, project: Path):
        install_claude_hook(project)
        installed, path = hook_status(project)
        assert installed
        assert path == project / ".claude" / "settings.json"


class TestRun:
    def test_run_install(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        args = argparse.Namespace(action="install", type="claude-stop")
        rc = run(args)
        assert rc == 0
        assert (project / ".claude" / "settings.json").exists()

    def test_run_uninstall(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        install_claude_hook(project)
        args = argparse.Namespace(action="uninstall", type="claude-stop")
        rc = run(args)
        assert rc == 0

    def test_run_status_returns_1_when_not_installed(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        args = argparse.Namespace(action="status", type="claude-stop")
        rc = run(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "not installed" in out

    def test_run_status_returns_0_when_installed(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        install_claude_hook(project)
        args = argparse.Namespace(action="status", type="claude-stop")
        rc = run(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "installed at" in out

    def test_run_fails_outside_decree_project(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(action="install", type="claude-stop")
        rc = run(args)
        assert rc == 1


class TestStopHookScript:
    def test_debug_reports_no_project_skip_reason(self, tmp_path: Path):
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_decree = fake_bin / "decree"
        fake_decree.write_text('#!/usr/bin/env bash\nif [[ "$1" == "find-root" ]]; then\n  exit 1\nfi\nexit 99\n')
        fake_decree.chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["DECREE_HOOK_DEBUG"] = "1"
        env["HOME"] = str(tmp_path / "home")

        script = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "decree-ddd-stop.sh"
        result = subprocess.run(
            [str(script)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        assert "no decree.toml found upward from cwd" in result.stderr
