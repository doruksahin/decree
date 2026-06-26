"""Tests for decree.commands.index."""

import argparse

import pytest

from decree.commands.index import run


@pytest.fixture
def populated_adr_dir(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "adr-00000000000000000000000001-first.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000001\n"
        "status: accepted\n"
        "date: 2026-04-01\n"
        "---\n\n"
        "# ADR-00000000000000000000000001 First Decision\n"
    )
    (d / "adr-00000000000000000000000002-second.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000002\n"
        "status: proposed\n"
        "date: 2026-04-02\n"
        "---\n\n"
        "# ADR-00000000000000000000000002 Second Decision\n"
    )
    return d


def test_generates_index(populated_adr_dir):
    assert run(argparse.Namespace()) == 0
    index = (populated_adr_dir / "index.md").read_text()
    assert "ADR-00000000000000000000000001" in index
    assert "First Decision" in index
    assert "TEMPLATE" not in index


def test_accepted_before_proposed(populated_adr_dir):
    run(argparse.Namespace())
    index = (populated_adr_dir / "index.md").read_text()
    assert index.index("ADR-00000000000000000000000001") < index.index("ADR-00000000000000000000000002")


def test_empty_dir(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    assert run(argparse.Namespace()) == 0
    assert (project_dir / "docs" / "adr" / "index.md").exists()


def test_noncanonical_markdown_file_is_not_source_document(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "TEMPLATE.md").write_text("# Template\n")

    assert run(argparse.Namespace()) == 0
    assert "TEMPLATE" not in (d / "index.md").read_text()


def test_index_includes_nested_documents_and_skips_reports(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    nested = d / "platform"
    reports = d / "reports"
    nested.mkdir()
    reports.mkdir()
    (nested / "adr-00000000000000000000000003-nested.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000003\n"
        "status: proposed\n"
        "date: 2026-04-03\n"
        "---\n\n"
        "# ADR-00000000000000000000000003 Nested Decision\n"
    )
    (reports / "adr-00000000000000000000000004-report.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000004\n"
        "status: proposed\n"
        "date: 2026-04-04\n"
        "---\n\n"
        "# ADR-00000000000000000000000004 Report Snapshot\n"
    )

    assert run(argparse.Namespace()) == 0
    index = (d / "index.md").read_text()
    assert "Nested Decision" in index
    assert "Report Snapshot" not in index
