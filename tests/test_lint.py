"""Tests for madr_tools.commands.lint."""
import argparse
import pytest
from madr_tools.commands.lint import run

VALID_BODY = (
    "# ADR-0001 Test\n\n"
    "## Context and Problem Statement\n\nText.\n\n"
    "## Considered Options\n\n- A\n\n"
    "## Decision Outcome\n\nChosen: A.\n\n"
    "## Consequences\n\n- Good: x\n\n"
    "## Affected Files\n\n- `f.py`\n\n"
    "## Validation Needed\n\nRun tests.\n"
)

@pytest.fixture
def adr_env(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    return project_dir / "docs" / "adr"

def test_valid_passes(adr_env):
    (adr_env / "0001-test.md").write_text(f"---\nstatus: proposed\ndate: 2026-04-02\n---\n\n{VALID_BODY}")
    assert run(argparse.Namespace()) == 0

def test_missing_section_fails(adr_env, capsys):
    (adr_env / "0001-test.md").write_text(
        "---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0001 Test\n\n## Context and Problem Statement\n\nText.\n"
    )
    assert run(argparse.Namespace()) == 1
    assert "missing section" in capsys.readouterr().out

def test_invalid_status_fails(adr_env, capsys):
    (adr_env / "0001-test.md").write_text(f"---\nstatus: draft\ndate: 2026-04-02\n---\n\n{VALID_BODY}")
    assert run(argparse.Namespace()) == 1
    assert "Invalid status" in capsys.readouterr().out

def test_supersede_symmetry(adr_env, capsys):
    (adr_env / "0001-old.md").write_text(
        "---\nstatus: superseded\ndate: 2026-04-01\nsuperseded-by: ADR-0002\n---\n\n" + VALID_BODY
    )
    (adr_env / "0002-new.md").write_text(
        f"---\nstatus: proposed\ndate: 2026-04-02\n---\n\n{VALID_BODY.replace('0001', '0002')}"
    )
    assert run(argparse.Namespace()) == 1
    assert "CROSS-FILE" in capsys.readouterr().out

def test_collects_all_errors(adr_env, capsys):
    (adr_env / "0001-bad.md").write_text("---\nstatus: draft\ndate: 2026-04-02\n---\n\n# T\n")
    (adr_env / "0002-bad.md").write_text("---\nstatus: nope\ndate: 2026-04-02\n---\n\n# T\n")
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "0001-bad" in out
    assert "0002-bad" in out

def test_empty_dir_passes(adr_env):
    assert run(argparse.Namespace()) == 0
