"""Tests for decree.commands.lint."""

import argparse

import pytest

from decree.commands.lint import run

ADR_1 = "ADR-00000000000000000000000001"
ADR_2 = "ADR-00000000000000000000000002"


def _filename(doc_id: str, slug: str = "test") -> str:
    return f"{doc_id.lower()}-{slug}.md"


def _body(doc_id: str = ADR_1) -> str:
    return (
        f"# {doc_id} Test\n\n"
        "## Context and Problem Statement\n\nText.\n\n"
        "## Considered Options\n\n- A\n\n"
        "## Decision Outcome\n\nChosen: A.\n\n"
        "## Consequences\n\n- Good: x\n\n"
        "## Affected Files\n\n- `f.py`\n\n"
        "## Validation Needed\n\nRun tests.\n"
    )


VALID_BODY = _body()


def _doc(frontmatter: str, body: str = VALID_BODY, doc_id: str = ADR_1) -> str:
    return f"---\nid: {doc_id}\n{frontmatter}---\n\n{body}"


BROKEN_BODY = "# T\n\n## Context and Problem Statement\n\nText.\n\n"


@pytest.fixture
def adr_env(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    return project_dir / "docs" / "adr"


def test_valid_passes(adr_env):
    (adr_env / _filename(ADR_1)).write_text(_doc("status: proposed\ndate: 2026-04-02\n"))
    assert run(argparse.Namespace()) == 0


def test_missing_section_fails(adr_env, capsys):
    (adr_env / _filename(ADR_1)).write_text(_doc("status: proposed\ndate: 2026-04-02\n", body=BROKEN_BODY))
    assert run(argparse.Namespace()) == 1
    assert "missing section" in capsys.readouterr().out


def test_invalid_status_fails(adr_env, capsys):
    (adr_env / _filename(ADR_1)).write_text(_doc("status: draft\ndate: 2026-04-02\n"))
    assert run(argparse.Namespace()) == 1
    assert "Invalid status" in capsys.readouterr().out


def test_supersede_symmetry(adr_env, capsys):
    (adr_env / _filename(ADR_1, "old")).write_text(
        _doc("status: superseded\ndate: 2026-04-01\nsuperseded-by: ADR-00000000000000000000000002\n")
    )
    (adr_env / _filename(ADR_2, "new")).write_text(
        _doc("status: proposed\ndate: 2026-04-02\n", body=_body(ADR_2), doc_id=ADR_2)
    )
    assert run(argparse.Namespace()) == 1
    assert "CROSS-FILE" in capsys.readouterr().out


def test_collects_all_errors(adr_env, capsys):
    (adr_env / _filename(ADR_1, "bad")).write_text(_doc("status: draft\ndate: 2026-04-02\n", body="# T\n"))
    (adr_env / _filename(ADR_2, "bad")).write_text(_doc("status: nope\ndate: 2026-04-02\n", body="# T\n", doc_id=ADR_2))
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert _filename(ADR_1, "bad") in out
    assert _filename(ADR_2, "bad") in out


def test_empty_dir_passes(adr_env):
    assert run(argparse.Namespace()) == 0


def test_governs_missing_path_fails(adr_env, project_dir, capsys):
    """SPEC-00000000000000000000000004: lint reports governs path-not-found errors with the exact format."""
    (adr_env / _filename(ADR_1)).write_text(
        _doc("status: proposed\ndate: 2026-04-02\ngoverns:\n  - src/api/missing.py\n")
    )
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "governs path does not exist: src/api/missing.py" in out
    assert _filename(ADR_1) in out


def test_governs_existing_path_passes(adr_env, project_dir):
    """A governs path that exists in the working tree passes lint."""
    (project_dir / "src" / "api").mkdir(parents=True)
    (project_dir / "src" / "api" / "real.py").touch()
    (adr_env / _filename(ADR_1)).write_text(
        _doc("status: proposed\ndate: 2026-04-02\ngoverns:\n  - src/api/real.py\n  - src/api/real.py#some_symbol\n")
    )
    assert run(argparse.Namespace()) == 0


def test_governs_mix_of_valid_and_invalid_reports_all(adr_env, project_dir, capsys):
    """When multiple governs entries are present, all missing ones are reported."""
    (project_dir / "src").mkdir()
    (project_dir / "src" / "exists.py").touch()
    (adr_env / _filename(ADR_1)).write_text(
        _doc(
            "status: proposed\n"
            "date: 2026-04-02\n"
            "governs:\n"
            "  - src/exists.py\n"
            "  - src/missing_a.py\n"
            "  - src/missing_b.py\n"
        )
    )
    assert run(argparse.Namespace()) == 1
    out = capsys.readouterr().out
    assert "src/missing_a.py" in out
    assert "src/missing_b.py" in out
    assert "src/exists.py" not in out
