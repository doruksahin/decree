"""Tests for decree.cli — entry point."""

import importlib.metadata
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import decree
from decree.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["version"]


def test_help():
    r = subprocess.run([sys.executable, "-m", "decree.cli", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "new" in r.stdout
    assert "lint" in r.stdout


def test_new_help():
    r = subprocess.run(
        [sys.executable, "-m", "decree.cli", "new", "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "title" in r.stdout.lower()
    assert "--bucket" in r.stdout


def test_list_help():
    r = subprocess.run(
        [sys.executable, "-m", "decree.cli", "list", "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "--tree" in r.stdout
    assert "--bucket" in r.stdout


def test_version_metadata_is_single_sourced_from_pyproject():
    expected = _project_version()
    assert importlib.metadata.version("decree") == expected
    assert decree.__version__ == expected


def test_version_help_uses_installed_package_metadata():
    r = subprocess.run([sys.executable, "-m", "decree.cli", "--version"], capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.strip() == f"decree {_project_version()}"


def test_changelog_has_section_for_current_project_version():
    assert f"## v{_project_version()}" in (ROOT / "CHANGELOG.md").read_text()


# ── Structured error contract (decree.error.v1) ─────────────


def test_json_mode_unhandled_error_emits_structured_contract(monkeypatch, capsys):
    """An unexpected error under --json yields decree.error.v1 on stdout, never a traceback.

    Programmatic consumers (e.g. an app that spawns the CLI) must get a stable
    machine-readable error instead of having to scrape a Python traceback off
    stderr. See docs/json-contracts.md.
    """
    import decree.commands.queries as queries

    def boom(_args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(queries, "why_run", boom)
    monkeypatch.setattr(sys, "argv", ["decree", "why", "src/x.py", "--json"])

    rc = main()
    assert rc == 2

    captured = capsys.readouterr()
    assert "Traceback" not in captured.out  # no leaked Python traceback on stdout
    payload = json.loads(captured.out)
    assert payload["schema"] == "decree.error.v1"
    assert payload["error"]["command"] == "why"
    assert payload["error"]["kind"] == "RuntimeError"
    assert "kaboom" in payload["error"]["message"]


def test_non_json_mode_unhandled_error_is_not_swallowed(monkeypatch):
    """Without --json, an unexpected error still surfaces (the human/dev path is unchanged)."""
    import decree.commands.queries as queries

    def boom(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(queries, "why_run", boom)
    monkeypatch.setattr(sys, "argv", ["decree", "why", "src/x.py"])

    with pytest.raises(RuntimeError):
        main()
