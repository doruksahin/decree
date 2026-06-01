"""Tests for decree.cli — entry point."""

import importlib.metadata
import subprocess
import sys
import tomllib
from pathlib import Path

import decree

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
