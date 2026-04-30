"""Tests for decree.commands.new."""

import argparse

import pytest

from decree.commands.new import run
from decree.parser import load


@pytest.fixture
def ready_project(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    return project_dir / "docs" / "adr"


def test_creates_file(ready_project):
    assert run(argparse.Namespace(doc_type="adr", title="Use PuLP Solver")) == 0
    files = list(ready_project.glob("0001-*.md"))
    assert len(files) == 1
    assert "use-pulp-solver" in files[0].name


def test_frontmatter_is_proposed(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    doc = load(next(iter(ready_project.glob("0001-*.md"))))
    assert doc.meta.status == "proposed"


def test_title_in_h1(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Use PuLP Solver"))
    content = next(iter(ready_project.glob("0001-*.md"))).read_text()
    assert "# ADR-0001 Use PuLP Solver" in content


def test_project_sections_appended(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    content = next(iter(ready_project.glob("0001-*.md"))).read_text()
    assert "## Consequences" in content
    assert "## Affected Files" in content
    assert "## Validation Needed" in content


def test_auto_increments(ready_project):
    (ready_project / "0001-existing.md").write_text(
        "---\nstatus: accepted\ndate: 2026-04-01\n---\n\n# ADR-0001 Existing\n"
    )
    run(argparse.Namespace(doc_type="adr", title="New"))
    assert len(list(ready_project.glob("0002-*.md"))) == 1


def test_generates_index(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    assert (ready_project / "index.md").exists()
