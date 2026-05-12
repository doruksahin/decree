"""Tests for decree.commands.lint."""

import argparse

import pytest

from decree.commands.lint import run

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


def test_governs_missing_path_fails(adr_env, project_dir, capsys):
    """SPEC-004: lint reports governs path-not-found errors with the exact format."""
    (adr_env / "0001-test.md").write_text(
        "---\n"
        "status: proposed\n"
        "date: 2026-04-02\n"
        "governs:\n"
        "  - src/api/missing.py\n"
        "---\n\n" + VALID_BODY
    )
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "governs path does not exist: src/api/missing.py" in out
    assert "0001-test.md" in out


def test_governs_existing_path_passes(adr_env, project_dir):
    """A governs path that exists in the working tree passes lint."""
    (project_dir / "src" / "api").mkdir(parents=True)
    (project_dir / "src" / "api" / "real.py").touch()
    (adr_env / "0001-test.md").write_text(
        "---\n"
        "status: proposed\n"
        "date: 2026-04-02\n"
        "governs:\n"
        "  - src/api/real.py\n"
        "  - src/api/real.py#some_symbol\n"
        "---\n\n" + VALID_BODY
    )
    assert run(argparse.Namespace()) == 0


def test_governs_mix_of_valid_and_invalid_reports_all(adr_env, project_dir, capsys):
    """When multiple governs entries are present, all missing ones are reported."""
    (project_dir / "src").mkdir()
    (project_dir / "src" / "exists.py").touch()
    (adr_env / "0001-test.md").write_text(
        "---\n"
        "status: proposed\n"
        "date: 2026-04-02\n"
        "governs:\n"
        "  - src/exists.py\n"
        "  - src/missing_a.py\n"
        "  - src/missing_b.py\n"
        "---\n\n" + VALID_BODY
    )
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "src/missing_a.py" in out
    assert "src/missing_b.py" in out
    assert "src/exists.py" not in out
