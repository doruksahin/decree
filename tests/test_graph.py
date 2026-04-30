"""Tests for decree.commands.graph."""

import argparse

import pytest

from decree.commands.graph import run
from decree.commands.index import GRAPH_MARKER
from decree.commands.index import run as index_run


@pytest.fixture
def adr_project(project_dir, monkeypatch):
    """Project with two ADRs — one superseding the other."""
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "0001-first.md").write_text(
        "---\nstatus: superseded\ndate: 2026-04-01\nsuperseded-by: ADR-0002\n---\n\n# ADR-0001 First Decision\n"
    )
    (d / "0002-second.md").write_text(
        "---\nstatus: accepted\ndate: 2026-04-02\nsupersedes: ADR-0001\n---\n\n# ADR-0002 Second Decision\n"
    )
    # Generate index first (includes marker)
    index_run(argparse.Namespace())
    return d


@pytest.fixture
def single_adr_project(project_dir, monkeypatch):
    """Project with a single ADR — no supersede relationships."""
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "0001-first.md").write_text("---\nstatus: accepted\ndate: 2026-04-01\n---\n\n# ADR-0001 First Decision\n")
    index_run(argparse.Namespace())
    return d


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
        assert "ADR-0001" in header
        assert "ADR-0002" in header
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
        assert "ADR-0001" in content
        assert "ADR-0002" in content
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
        (d / "0001-first.md").write_text("---\nstatus: accepted\ndate: 2026-04-01\n---\n\n# ADR-0001 First Decision\n")
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
        (d / "0001-first.md").write_text("---\nstatus: accepted\ndate: 2026-04-01\n---\n\n# ADR-0001 First Decision\n")
        # No index.md at all
        assert run(argparse.Namespace()) == 1


class TestGraphEmpty:
    def test_no_docs_skips(self, project_dir, monkeypatch):
        """graph skips types with no documents."""
        monkeypatch.chdir(project_dir)
        index_run(argparse.Namespace())
        assert run(argparse.Namespace()) == 0
