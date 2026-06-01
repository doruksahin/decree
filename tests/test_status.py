"""Tests for decree.commands.status."""

import argparse

import pytest

from decree.commands.status import run
from decree.parser import load

ADR_1 = "ADR-00000000000000000000000001"
ADR_2 = "ADR-00000000000000000000000002"
ADR_1_FILE = "adr-00000000000000000000000001-test.md"
ADR_2_FILE = "adr-00000000000000000000000002-replacement.md"


@pytest.fixture
def adr_env(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    d = project_dir / "docs" / "adr"
    (d / ADR_1_FILE).write_text(f"---\nid: {ADR_1}\nstatus: proposed\ndate: 2026-04-02\n---\n\n# {ADR_1} Test\n")
    return d


def test_accept(adr_env):
    assert run(argparse.Namespace(action="accept", doc_id=ADR_1, target_id=None)) == 0
    assert load(adr_env / ADR_1_FILE).meta.status == "accepted"


def test_reject(adr_env):
    assert run(argparse.Namespace(action="reject", doc_id=ADR_1, target_id=None)) == 0
    assert load(adr_env / ADR_1_FILE).meta.status == "rejected"


def test_invalid_transition(adr_env, capsys):
    run(argparse.Namespace(action="accept", doc_id=ADR_1, target_id=None))
    result = run(argparse.Namespace(action="reject", doc_id=ADR_1, target_id=None))
    assert result == 1
    assert "cannot transition" in capsys.readouterr().err


def test_terminal_status(adr_env, capsys):
    run(argparse.Namespace(action="reject", doc_id=ADR_1, target_id=None))
    result = run(argparse.Namespace(action="accept", doc_id=ADR_1, target_id=None))
    assert result == 1
    assert "terminal status" in capsys.readouterr().err


def test_supersede(adr_env):
    (adr_env / ADR_2_FILE).write_text(
        f"---\nid: {ADR_2}\nstatus: proposed\ndate: 2026-04-02\n---\n\n# {ADR_2} Replacement\n"
    )
    run(argparse.Namespace(action="accept", doc_id=ADR_1, target_id=None))
    assert run(argparse.Namespace(action="supersede", doc_id=ADR_1, target_id=ADR_2)) == 0
    old = load(adr_env / ADR_1_FILE)
    assert old.meta.status == "superseded"
    assert old.meta.superseded_by == ADR_2
    new = load(adr_env / ADR_2_FILE)
    assert new.meta.supersedes == ADR_1
