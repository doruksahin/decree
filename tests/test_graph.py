"""Tests for decree.commands.graph."""

import argparse

import pytest

from decree.commands.graph import graph_json, run
from decree.commands.index import GRAPH_MARKER
from decree.commands.index import run as index_run


@pytest.fixture
def adr_project(project_dir, monkeypatch):
    """Project with two ADRs — one superseding the other."""
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "adr-00000000000000000000000001-first.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000001\n"
        "status: superseded\n"
        "date: 2026-04-01\n"
        "superseded-by: ADR-00000000000000000000000002\n"
        "---\n\n"
        "# ADR-00000000000000000000000001 First Decision\n"
    )
    (d / "adr-00000000000000000000000002-second.md").write_text(
        "---\n"
        "id: ADR-00000000000000000000000002\n"
        "status: accepted\n"
        "date: 2026-04-02\n"
        "supersedes: ADR-00000000000000000000000001\n"
        "---\n\n"
        "# ADR-00000000000000000000000002 Second Decision\n"
    )
    # Generate index first (includes marker)
    index_run(argparse.Namespace())
    return d


@pytest.fixture
def single_adr_project(project_dir, monkeypatch):
    """Project with a single ADR — no supersede relationships."""
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
    index_run(argparse.Namespace())
    return d


class TestGraphJson:
    def test_emits_documents_and_reference_edges(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        d = project_dir / "docs" / "adr"
        (d / "adr-00000000000000000000000001-base.md").write_text(
            "---\n"
            "id: ADR-00000000000000000000000001\n"
            "status: accepted\n"
            "date: 2026-04-01\n"
            "---\n\n"
            "# ADR-00000000000000000000000001 Base Decision\n"
        )
        (d / "adr-00000000000000000000000002-derived.md").write_text(
            "---\n"
            "id: ADR-00000000000000000000000002\n"
            "status: accepted\n"
            "date: 2026-04-02\n"
            "references: [ADR-00000000000000000000000001]\n"
            "---\n\n"
            "# ADR-00000000000000000000000002 Derived Decision\n"
        )

        result = graph_json()

        assert [doc["id"] for doc in result["documents"]] == [
            "ADR-00000000000000000000000001",
            "ADR-00000000000000000000000002",
        ]
        derived = result["documents"][1]
        assert derived["type"] == "adr"
        assert derived["title"] == "Derived Decision"  # id prefix stripped
        assert derived["relative_path"] == "docs/adr/adr-00000000000000000000000002-derived.md"
        assert derived["references"] == ["ADR-00000000000000000000000001"]
        assert result["edges"] == [{"from": "ADR-00000000000000000000000002", "to": "ADR-00000000000000000000000001"}]

    def test_drops_edge_to_unknown_reference(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        d = project_dir / "docs" / "adr"
        (d / "adr-00000000000000000000000001-only.md").write_text(
            "---\n"
            "id: ADR-00000000000000000000000001\n"
            "status: accepted\n"
            "date: 2026-04-01\n"
            "references: [PRD-00000000000000000000000099]\n"
            "---\n\n"
            "# ADR-00000000000000000000000001 Only Decision\n"
        )

        result = graph_json()

        assert len(result["documents"]) == 1
        assert result["documents"][0]["references"] == ["PRD-00000000000000000000000099"]
        assert result["edges"] == []


class TestGraphCommand:
    def test_generates_diagrams(self, adr_project):
        assert run(argparse.Namespace()) == 0
        content = (adr_project / "index.md").read_text()
        assert "## Decision Timeline" in content
        assert "## Status Distribution" in content
        assert "```mermaid" in content

    def test_preserves_table_above_marker(self, adr_project):
        assert run(argparse.Namespace()) == 0
        content = (adr_project / "index.md").read_text()
        header = content[: content.index(GRAPH_MARKER)]
        assert "ADR-00000000000000000000000001" in header
        assert "ADR-00000000000000000000000002" in header
        assert "| ADR |" in header

    def test_supersede_chain_generated(self, adr_project):
        assert run(argparse.Namespace()) == 0
        content = (adr_project / "index.md").read_text()
        assert "## Decision Chain" in content
        assert "superseded by" in content

    def test_no_supersede_chain_when_none(self, single_adr_project):
        assert run(argparse.Namespace()) == 0
        content = (single_adr_project / "index.md").read_text()
        assert "## Decision Chain" not in content

    def test_status_pie_chart(self, single_adr_project):
        assert run(argparse.Namespace()) == 0
        content = (single_adr_project / "index.md").read_text()
        assert "pie title ADR Status Distribution" in content
        assert '"accepted" : 1' in content

    def test_timeline_includes_docs(self, adr_project):
        assert run(argparse.Namespace()) == 0
        content = (adr_project / "index.md").read_text()
        assert "ADR-00000000000000000000000001" in content
        assert "ADR-00000000000000000000000002" in content
        assert "2026-04-01" in content

    def test_idempotent(self, adr_project):
        """Running graph twice produces identical output."""
        run(argparse.Namespace())
        first = (adr_project / "index.md").read_text()
        run(argparse.Namespace())
        second = (adr_project / "index.md").read_text()
        assert first == second


class TestGraphWithoutMarker:
    def test_auto_regenerates_index_when_marker_missing(self, project_dir, monkeypatch):
        """graph auto-runs index if the marker is missing from index.md."""
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
        # Write an index WITHOUT the marker (simulating old/manual index)
        (d / "index.md").write_text("# ADRs\n\nSome hand-written content.\n")
        assert run(argparse.Namespace()) == 0
        content = (d / "index.md").read_text()
        assert GRAPH_MARKER in content
        assert "```mermaid" in content

    def test_fails_when_no_index_file(self, project_dir, monkeypatch):
        """graph fails if index.md doesn't exist and there are docs."""
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
        # No index.md at all
        assert run(argparse.Namespace()) == 1


class TestGraphEmpty:
    def test_no_docs_skips(self, project_dir, monkeypatch):
        """graph skips types with no documents."""
        monkeypatch.chdir(project_dir)
        index_run(argparse.Namespace())
        assert run(argparse.Namespace()) == 0
