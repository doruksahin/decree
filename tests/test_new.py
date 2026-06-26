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


def _args(**overrides):
    data = {"doc_type": "adr", "title": "Test", "bucket": "decisions"}
    data.update(overrides)
    return argparse.Namespace(**data)


def test_creates_file(ready_project):
    assert run(_args(title="Use PuLP Solver")) == 0
    files = list((ready_project / "decisions").glob("adr-*.md"))
    assert len(files) == 1
    assert "use-pulp-solver" in files[0].name


def test_frontmatter_is_proposed(ready_project):
    run(_args())
    doc = load(next(iter(ready_project.rglob("adr-*.md"))))
    assert doc.meta.status == "proposed"
    assert doc.meta.id is not None
    assert doc.path.name.startswith(doc.meta.id.lower())


def test_title_in_h1(ready_project):
    run(_args(title="Use PuLP Solver"))
    content = next(iter(ready_project.rglob("adr-*.md"))).read_text()
    assert "# ADR-" in content
    assert " Use PuLP Solver" in content


def test_project_sections_appended(ready_project):
    run(_args())
    content = next(iter(ready_project.rglob("adr-*.md"))).read_text()
    assert "## Consequences" in content
    assert "## Affected Files" in content
    assert "## Validation Needed" in content


def test_creates_unique_ids(ready_project):
    run(_args(title="First"))
    run(_args(title="New"))
    files = list(ready_project.rglob("adr-*.md"))
    ids = {load(path).doc_id for path in files}
    assert len(files) == 2
    assert len(ids) == 2


def test_does_not_generate_index_implicitly(ready_project):
    run(_args())
    assert not (ready_project / "index.md").exists()


def test_creates_file_in_bucket(ready_project):
    assert run(argparse.Namespace(doc_type="adr", title="Bucketed Decision", bucket="platform/auth")) == 0
    files = list((ready_project / "platform" / "auth").glob("adr-*.md"))
    assert len(files) == 1
    assert "bucketed-decision" in files[0].name


def test_rejects_unsafe_bucket_before_writing(ready_project):
    assert run(argparse.Namespace(doc_type="adr", title="Unsafe", bucket="../outside")) == 1
    assert list(ready_project.rglob("adr-*.md")) == []


def test_requires_non_root_bucket_before_writing(ready_project):
    assert run(argparse.Namespace(doc_type="adr", title="No Bucket")) == 1
    assert run(argparse.Namespace(doc_type="adr", title="Root Bucket", bucket=".")) == 1
    assert list(ready_project.rglob("adr-*.md")) == []


def test_refuses_to_overwrite_existing_document(ready_project, monkeypatch):
    doc_id = "ADR-00000000000000000000000001"
    existing = ready_project / "decisions" / filename_for_doc_id(doc_id, "test")
    existing.parent.mkdir(parents=True)
    existing.write_text("original\n")
    monkeypatch.setattr("decree.commands.new.generate_doc_id", lambda prefix: doc_id)

    assert run(_args()) == 1
    assert existing.read_text() == "original\n"
