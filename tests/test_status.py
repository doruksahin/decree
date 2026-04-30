"""Tests for decree.commands.status."""

import argparse

import pytest

from decree.commands.status import run
from decree.parser import load


@pytest.fixture
def adr_env(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / "0001-test.md").write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0001 Test\n")
    return d


def test_accept(adr_env):
    assert run(argparse.Namespace(action="accept", doc_id="ADR-0001", target_id=None)) == 0
    assert load(adr_env / "0001-test.md").meta.status == "accepted"


def test_reject(adr_env):
    assert run(argparse.Namespace(action="reject", doc_id="ADR-0001", target_id=None)) == 0
    assert load(adr_env / "0001-test.md").meta.status == "rejected"


def test_invalid_transition(adr_env, capsys):
    run(argparse.Namespace(action="accept", doc_id="ADR-0001", target_id=None))
    result = run(argparse.Namespace(action="reject", doc_id="ADR-0001", target_id=None))
    assert result == 1
    assert "cannot transition" in capsys.readouterr().err


def test_terminal_status(adr_env, capsys):
    run(argparse.Namespace(action="reject", doc_id="ADR-0001", target_id=None))
    result = run(argparse.Namespace(action="accept", doc_id="ADR-0001", target_id=None))
    assert result == 1
    assert "terminal status" in capsys.readouterr().err


def test_supersede(adr_env):
    (adr_env / "0002-replacement.md").write_text(
        "---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0002 Replacement\n"
    )
    run(argparse.Namespace(action="accept", doc_id="ADR-0001", target_id=None))
    assert run(argparse.Namespace(action="supersede", doc_id="ADR-0001", target_id="ADR-0002")) == 0
    old = load(adr_env / "0001-test.md")
    assert old.meta.status == "superseded"
    assert old.meta.superseded_by == "ADR-0002"
    new = load(adr_env / "0002-replacement.md")
    assert new.meta.supersedes == "ADR-0001"
