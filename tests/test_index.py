"""Tests for decree.commands.index."""
import argparse
import pytest
from decree.commands.index import run

@pytest.fixture
def populated_adr_dir(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "0001-first.md").write_text("---\nstatus: accepted\ndate: 2026-04-01\n---\n\n# ADR-0001 First Decision\n")
    (d / "0002-second.md").write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0002 Second Decision\n")
    (d / "TEMPLATE.md").write_text("# Template\n")
    return d

def test_generates_index(populated_adr_dir):
    assert run(argparse.Namespace()) == 0
    index = (populated_adr_dir / "index.md").read_text()
    assert "ADR-0001" in index
    assert "First Decision" in index
    assert "TEMPLATE" not in index

def test_accepted_before_proposed(populated_adr_dir):
    run(argparse.Namespace())
    index = (populated_adr_dir / "index.md").read_text()
    assert index.index("ADR-0001") < index.index("ADR-0002")

def test_empty_dir(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    assert run(argparse.Namespace()) == 0
    assert (project_dir / "docs" / "adr" / "index.md").exists()
