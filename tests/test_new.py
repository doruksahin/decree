"""Tests for decree.commands.new."""

import argparse

import pytest

from decree.commands.new import run
from decree.identity import filename_for_doc_id
from decree.parser import load


@pytest.fixture
def ready_project(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    return project_dir / "docs" / "adr"


def test_creates_file(ready_project):
    assert run(argparse.Namespace(doc_type="adr", title="Use PuLP Solver")) == 0
    files = list(ready_project.glob("adr-*.md"))
    assert len(files) == 1
    assert "use-pulp-solver" in files[0].name


def test_frontmatter_is_proposed(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    doc = load(next(iter(ready_project.glob("adr-*.md"))))
    assert doc.meta.status == "proposed"
    assert doc.meta.id is not None
    assert doc.path.name.startswith(doc.meta.id.lower())


def test_title_in_h1(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Use PuLP Solver"))
    content = next(iter(ready_project.glob("adr-*.md"))).read_text()
    assert "# ADR-" in content
    assert " Use PuLP Solver" in content


def test_project_sections_appended(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    content = next(iter(ready_project.glob("adr-*.md"))).read_text()
    assert "## Consequences" in content
    assert "## Affected Files" in content
    assert "## Validation Needed" in content


def test_creates_unique_ids(ready_project):
    run(argparse.Namespace(doc_type="adr", title="First"))
    run(argparse.Namespace(doc_type="adr", title="New"))
    files = list(ready_project.glob("adr-*.md"))
    ids = {load(path).doc_id for path in files}
    assert len(files) == 2
    assert len(ids) == 2


def test_does_not_generate_index_implicitly(ready_project):
    run(argparse.Namespace(doc_type="adr", title="Test"))
    assert not (ready_project / "index.md").exists()


def test_refuses_to_overwrite_existing_document(ready_project, monkeypatch):
    doc_id = "ADR-00000000000000000000000001"
    existing = ready_project / filename_for_doc_id(doc_id, "test")
    existing.write_text("original\n")
    monkeypatch.setattr("decree.commands.new.generate_doc_id", lambda prefix: doc_id)

    assert run(argparse.Namespace(doc_type="adr", title="Test")) == 1
    assert existing.read_text() == "original\n"
