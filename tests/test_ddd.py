"""Tests for `decree ddd` — phase detection across the lifecycle states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from decree.commands.ddd import (
    Chain,
    DocSummary,
    Phase,
    _detect_phase,
    _detect_phase_for_chain,
    assess,
    format_human,
    format_json,
    run,
)

# ── _detect_phase_for_chain unit tests ─────────────────────────


def _spec(id: str, status: str, done: int, total: int, refs: tuple[str, ...] = ()) -> DocSummary:
    return DocSummary(
        id=id, type="spec", status=status, title=id, progress_done=done, progress_total=total, references=refs
    )


def _adr(id: str, status: str, refs: tuple[str, ...] = ()) -> DocSummary:
    return DocSummary(id=id, type="adr", status=status, title=id, references=refs)


def _prd(id: str, status: str, refs: tuple[str, ...] = ()) -> DocSummary:
    return DocSummary(id=id, type="prd", status=status, title=id, references=refs)


class TestDetectPhaseForChain:
    def test_implementation_phase(self):
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(_spec("SPEC-00000000000000000000000001", "draft", 5, 10, refs=("ADR-00000000000000000000000001",)),),
        )
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, sug = result
        assert phase == Phase.IMPLEMENTATION
        assert sug.target_id == "SPEC-00000000000000000000000001"

    def test_completion_phase(self):
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(
                _spec("SPEC-00000000000000000000000001", "draft", 10, 10, refs=("ADR-00000000000000000000000001",)),
            ),
        )
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, sug = result
        assert phase == Phase.COMPLETION
        assert "implement" in sug.description.lower()

    def test_planning_phase(self):
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(_spec("SPEC-00000000000000000000000001", "draft", 0, 10, refs=("ADR-00000000000000000000000001",)),),
        )
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, _ = result
        assert phase == Phase.PLANNING

    def test_technical_design_phase(self):
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(),
        )
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, _ = result
        assert phase == Phase.TECHNICAL_DESIGN

    def test_architecture_decisions_phase(self):
        chain = Chain(prd=_prd("PRD-00000000000000000000000001", "approved"), adrs=(), specs=())
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, _ = result
        assert phase == Phase.ARCHITECTURE_DECISIONS

    def test_first_match_wins_implementation_over_design(self):
        """A chain with an in-flight SPEC reports IMPLEMENTATION even if there are ADRs without other SPECs."""
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(
                _adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),
                _adr("ADR-00000000000000000000000002", "accepted", refs=("PRD-00000000000000000000000001",)),
            ),
            specs=(
                _spec("SPEC-00000000000000000000000001", "draft", 5, 10, refs=("ADR-00000000000000000000000001",)),
            ),  # in-flight, refs only ADR-00000000000000000000000001
        )
        result = _detect_phase_for_chain(chain)
        assert result is not None
        phase, _ = result
        # IMPLEMENTATION wins over the fact that ADR-00000000000000000000000002 has no referencing SPEC.
        assert phase == Phase.IMPLEMENTATION

    def test_terminal_status_skipped(self):
        """An already-implemented SPEC at any progress doesn't trigger active phases."""
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(
                _spec(
                    "SPEC-00000000000000000000000001", "implemented", 10, 10, refs=("ADR-00000000000000000000000001",)
                ),
            ),
        )
        result = _detect_phase_for_chain(chain)
        # No active phase remains for this chain
        assert result is None


# ── _detect_phase aggregation tests ────────────────────────────


class TestDetectPhaseAggregation:
    def test_ideation_when_no_docs(self):
        phase, sugs = _detect_phase({"doc_count": 0}, ())
        assert phase == Phase.IDEATION
        assert len(sugs) == 1

    def test_done_when_all_terminal(self):
        chain = Chain(
            prd=_prd("PRD-00000000000000000000000001", "implemented"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(
                _spec(
                    "SPEC-00000000000000000000000001", "implemented", 10, 10, refs=("ADR-00000000000000000000000001",)
                ),
            ),
        )
        phase, _ = _detect_phase({"doc_count": 3}, (chain,))
        assert phase == Phase.DONE

    def test_implementation_outranks_architecture(self):
        """Across two chains, IMPLEMENTATION suggestions take priority over ARCHITECTURE_DECISIONS."""
        chain1 = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(_spec("SPEC-00000000000000000000000001", "draft", 5, 10, refs=("ADR-00000000000000000000000001",)),),
        )
        chain2 = Chain(
            prd=_prd("PRD-00000000000000000000000002", "approved"), adrs=(), specs=()
        )  # would be ARCHITECTURE_DECISIONS
        phase, _ = _detect_phase({"doc_count": 4}, (chain1, chain2))
        assert phase == Phase.IMPLEMENTATION

    def test_dedup_same_spec_across_chains(self):
        """A SPEC appearing in two chains produces one suggestion, not two."""
        shared_spec = _spec(
            "SPEC-00000000000000000000000001",
            "draft",
            5,
            10,
            refs=("ADR-00000000000000000000000001", "ADR-00000000000000000000000002"),
        )
        chain1 = Chain(
            prd=_prd("PRD-00000000000000000000000001", "approved"),
            adrs=(_adr("ADR-00000000000000000000000001", "accepted", refs=("PRD-00000000000000000000000001",)),),
            specs=(shared_spec,),
        )
        chain2 = Chain(
            prd=_prd("PRD-00000000000000000000000002", "approved"),
            adrs=(_adr("ADR-00000000000000000000000002", "accepted", refs=("PRD-00000000000000000000000002",)),),
            specs=(shared_spec,),
        )
        phase, sugs = _detect_phase({"doc_count": 5}, (chain1, chain2))
        assert phase == Phase.IMPLEMENTATION
        assert len(sugs) == 1
        assert sugs[0].target_id == "SPEC-00000000000000000000000001"


# ── End-to-end CLI fixture tests ──────────────────────────────


@pytest.fixture
def empty_corpus(tmp_path: Path) -> Path:
    """A decree project with no documents — Phase IDEATION."""
    (tmp_path / "decree.toml").write_text(_minimal_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (tmp_path / "decree" / sub).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def prd_only_corpus(tmp_path: Path) -> Path:
    """PRD exists, no ADRs — Phase ARCHITECTURE_DECISIONS."""
    (tmp_path / "decree.toml").write_text(_minimal_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (tmp_path / "decree" / sub).mkdir(parents=True)
    (tmp_path / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        _prd_doc(status="approved", title="Test PRD")
    )
    return tmp_path


@pytest.fixture
def in_flight_corpus(tmp_path: Path) -> Path:
    """SPEC in progress — Phase IMPLEMENTATION."""
    (tmp_path / "decree.toml").write_text(_minimal_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (tmp_path / "decree" / sub).mkdir(parents=True)
    (tmp_path / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        _prd_doc(status="approved", title="Test PRD")
    )
    (tmp_path / "decree" / "adr" / "adr-00000000000000000000000001-test.md").write_text(
        _adr_doc(status="accepted", title="Test ADR", references=["PRD-00000000000000000000000001"])
    )
    (tmp_path / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        _spec_doc(status="draft", title="Test SPEC", references=["ADR-00000000000000000000000001"], done=2, total=5)
    )
    return tmp_path


def _minimal_decree_toml() -> str:
    return """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Problem Statement"]
[types.prd.transitions]
draft = ["review", "approved"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []
[types.prd.actions]
approve = "approved"
implement = "implemented"

[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
warn_on_reference = ["rejected"]
required_sections = ["Context and Problem Statement"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
"""


def _prd_doc(*, status: str, title: str, references: list[str] | None = None) -> str:
    refs = f"references: [{', '.join(references)}]\n" if references else ""
    return f"""---
id: PRD-00000000000000000000000001
status: {status}
date: 2026-05-12
{refs}---

# PRD-00000000000000000000000001 {title}

## Problem Statement

Some prose.
"""


def _adr_doc(*, status: str, title: str, references: list[str] | None = None) -> str:
    refs = f"references: [{', '.join(references)}]\n" if references else ""
    return f"""---
id: ADR-00000000000000000000000001
status: {status}
date: 2026-05-12
{refs}---

# ADR-00000000000000000000000001 {title}

## Context and Problem Statement

Some prose.
"""


def _spec_doc(*, status: str, title: str, done: int, total: int, references: list[str] | None = None) -> str:
    refs = f"references: [{', '.join(references)}]\n" if references else ""
    boxes = "\n".join(
        [f"- [x] Item {i}" for i in range(done)] + [f"- [ ] Item {i + done}" for i in range(total - done)]
    )
    return f"""---
id: SPEC-00000000000000000000000001
status: {status}
date: 2026-05-12
{refs}---

# SPEC-00000000000000000000000001 {title}

## Overview

Some prose.

## Acceptance criteria

{boxes}
"""


class TestAssessE2E:
    def test_empty_corpus_is_ideation(self, monkeypatch, empty_corpus: Path):
        monkeypatch.chdir(empty_corpus)
        a = assess()
        assert a.phase == Phase.IDEATION

    def test_prd_only_is_architecture_decisions(self, monkeypatch, prd_only_corpus: Path):
        monkeypatch.chdir(prd_only_corpus)
        a = assess()
        assert a.phase == Phase.ARCHITECTURE_DECISIONS

    def test_in_flight_is_implementation(self, monkeypatch, in_flight_corpus: Path):
        monkeypatch.chdir(in_flight_corpus)
        a = assess()
        assert a.phase == Phase.IMPLEMENTATION
        assert a.documents == {"prd": 1, "adr": 1, "spec": 1}
        assert a.progress["completed"] == 2
        assert a.progress["total"] == 5
        assert a.progress["percent"] == 40

    def test_chains_built_correctly(self, monkeypatch, in_flight_corpus: Path):
        monkeypatch.chdir(in_flight_corpus)
        a = assess()
        assert len(a.chains) == 1
        c = a.chains[0]
        assert c.prd is not None and c.prd.id == "PRD-00000000000000000000000001"
        assert len(c.adrs) == 1 and c.adrs[0].id == "ADR-00000000000000000000000001"
        assert len(c.specs) == 1 and c.specs[0].id == "SPEC-00000000000000000000000001"

    def test_governs_scope(self, monkeypatch, in_flight_corpus: Path):
        spec_path = in_flight_corpus / "decree" / "spec" / "spec-00000000000000000000000001-test.md"
        spec_path.write_text(
            spec_path.read_text().replace("date: 2026-05-12\n", "date: 2026-05-12\ngoverns: [src/foo.py]\n")
        )
        monkeypatch.chdir(in_flight_corpus)

        a = assess(governs_path="src/foo.py")

        assert a.scope == "governs src/foo.py"
        assert a.documents == {"spec": 1}


class TestFormatters:
    def test_human_includes_phase(self, monkeypatch, in_flight_corpus: Path):
        monkeypatch.chdir(in_flight_corpus)
        a = assess()
        out = format_human(a)
        assert "IMPLEMENTATION" in out
        assert "PRD-00000000000000000000000001" in out
        assert "SPEC-00000000000000000000000001" in out

    def test_quiet_omits_chains(self, monkeypatch, in_flight_corpus: Path):
        monkeypatch.chdir(in_flight_corpus)
        a = assess()
        out = format_human(a, quiet=True)
        assert "Document chains:" not in out
        assert "IMPLEMENTATION" in out

    def test_json_is_valid_json(self, monkeypatch, in_flight_corpus: Path):
        monkeypatch.chdir(in_flight_corpus)
        a = assess()
        out = format_json(a)
        data = json.loads(out)
        assert data["phase"] == "implementation"
        assert data["progress"]["percent"] == 40
        assert len(data["chains"]) == 1


class TestRun:
    def test_exit_code_zero_on_healthy(self, monkeypatch, in_flight_corpus: Path, capsys):
        monkeypatch.chdir(in_flight_corpus)
        args = argparse.Namespace(
            json=False, quiet=False, project=None, doc=None, chain=None, governs=None, changed=False, base=None
        )
        rc = run(args)
        assert rc == 0

    def test_json_flag_produces_json(self, monkeypatch, in_flight_corpus: Path, capsys):
        monkeypatch.chdir(in_flight_corpus)
        args = argparse.Namespace(
            json=True, quiet=False, project=None, doc=None, chain=None, governs=None, changed=False, base=None
        )
        rc = run(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["phase"] == "implementation"
        assert rc == 0

    def test_project_flag_resolves_path(self, monkeypatch, in_flight_corpus: Path, capsys, tmp_path):
        # cd somewhere else; ensure --project still works
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        args = argparse.Namespace(
            json=False,
            quiet=False,
            project=str(in_flight_corpus),
            doc=None,
            chain=None,
            governs=None,
            changed=False,
            base=None,
        )
        rc = run(args)
        out = capsys.readouterr().out
        assert "IMPLEMENTATION" in out
        assert rc == 0

    def test_invalid_doc_scope_is_error(self, monkeypatch, in_flight_corpus: Path, capsys):
        monkeypatch.chdir(in_flight_corpus)
        args = argparse.Namespace(
            json=False, quiet=True, project=None, doc="SPEC-001", chain=None, changed=False, base=None
        )

        rc = run(args)

        assert rc == 1
        assert "TYPE-ULID" in capsys.readouterr().err

    def test_missing_doc_scope_is_error(self, monkeypatch, in_flight_corpus: Path, capsys):
        monkeypatch.chdir(in_flight_corpus)
        args = argparse.Namespace(
            json=False,
            quiet=True,
            project=None,
            doc="SPEC-00000000000000000000000099",
            chain=None,
            changed=False,
            base=None,
        )

        rc = run(args)

        assert rc == 1
        assert "document not found" in capsys.readouterr().err
