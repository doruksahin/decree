"""SPEC-00000000000000000000000010 tests — `decree migrate audit-coherence`."""

from __future__ import annotations

import argparse
import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


def _three_type_toml(extra: str = "") -> str:
    """Same shape as tests/test_coherence.py's _three_type_toml — keep in sync."""
    base = """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Problem Statement"]
[types.prd.transitions]
draft = ["approved"]
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
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

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
    return base + extra


def _write_corpus(root: Path, extra_toml: str = "") -> None:
    (root / "decree.toml").write_text(_three_type_toml(extra_toml))
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True, exist_ok=True)


def _doc_id(prefix: str, name: str) -> str:
    return f"{prefix}-{int(name.split('-', 1)[0]):026d}"


def _filename(prefix: str, name: str) -> str:
    return f"{_doc_id(prefix, name).lower()}-{name.split('-', 1)[1]}.md"


def _spec(root: Path, name: str, status: str, body_acs: str) -> None:
    doc_id = _doc_id("SPEC", name)
    (root / "decree" / "spec" / _filename("SPEC", name)).write_text(
        f"""---
id: {doc_id}
status: {status}
date: 2026-05-10
---

# {doc_id} title

## Overview

Prose.

## v1 Acceptance Criteria

{body_acs}
"""
    )


def _prd(root: Path, name: str, status: str, d: date) -> None:
    doc_id = _doc_id("PRD", name)
    (root / "decree" / "prd" / _filename("PRD", name)).write_text(
        f"""---
id: {doc_id}
status: {status}
date: {d.isoformat()}
---

# {doc_id} title

## Problem Statement

x
"""
    )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch):
    _write_corpus(tmp_path)
    monkeypatch.chdir(tmp_path)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    yield tmp_path
    get_project_root.cache_clear()
    load_doc_types.cache_clear()


# ─── library API ──────────────────────────────────────────────────────────


class TestAuditCoherenceLibrary:
    def test_clean_corpus_no_findings(self, corpus: Path):
        # Spec in draft + a fresh, referenced PRD → nothing flagged.
        _spec(corpus, "001-foo", "draft", "- [ ] not done yet\n")
        from decree.commands.migrate import audit_coherence

        report = audit_coherence(corpus)
        assert report.total == 0
        assert report.findings == ()

    def test_terminal_status_violations_reported(self, corpus: Path):
        # No need to enable the gate in decree.toml — audit forces it on.
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        _spec(corpus, "002-bar", "implemented", "- [x] one\n- [ ] two\n- [ ] three\n")
        from decree.commands.migrate import audit_coherence

        report = audit_coherence(corpus, gates=["terminal_status_progress"])
        assert report.total == 2
        assert report.by_gate == {"terminal_status_progress": 2}
        gates = {f.gate for f in report.findings}
        assert gates == {"terminal_status_progress"}
        for f in report.findings:
            assert f.severity == "error"
            assert "primary AC progress" in f.message
            assert f.suggested_fix is not None

    def test_unreferenced_active_violation_reported(self, corpus: Path):
        # PRD approved 60 days ago, no SPEC references → flagged.
        old = date.today() - timedelta(days=60)
        # The gate's defaults require active_statuses to be set or default to
        # {approved, accepted}. We force the audit on via gates=[…].
        _prd(corpus, "001-foo", "approved", old)
        from decree.commands.migrate import audit_coherence

        report = audit_coherence(corpus, gates=["unreferenced_active"])
        assert report.total == 1
        assert report.by_gate == {"unreferenced_active": 1}
        f = report.findings[0]
        assert f.doc_id == "PRD-00000000000000000000000001"
        assert f.gate == "unreferenced_active"
        assert f.severity == "error"

    def test_gate_filter_limits_scope(self, corpus: Path):
        # Both kinds of violations present.
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        _prd(corpus, "001-bar", "approved", date.today() - timedelta(days=60))
        from decree.commands.migrate import audit_coherence

        only_t = audit_coherence(corpus, gates=["terminal_status_progress"])
        only_u = audit_coherence(corpus, gates=["unreferenced_active"])
        assert only_t.by_gate.keys() == {"terminal_status_progress"}
        assert only_u.by_gate.keys() == {"unreferenced_active"}
        # Each gate sees only its own findings.
        assert all(f.gate == "terminal_status_progress" for f in only_t.findings)
        assert all(f.gate == "unreferenced_active" for f in only_u.findings)

    def test_exceptions_demote_to_info(self, corpus: Path):
        _write_corpus(
            corpus,
            extra_toml=(
                '\n[types.spec.coherence_exceptions]\nterminal_status_progress = ["SPEC-00000000000000000000000001"]\n'
            ),
        )
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        _spec(corpus, "002-bar", "implemented", "- [x] one\n- [ ] two\n")
        from decree.commands.migrate import audit_coherence

        report = audit_coherence(corpus, gates=["terminal_status_progress"])
        # Two findings emitted, but only one counts as error (SPEC-00000000000000000000000002).
        # SPEC-00000000000000000000000001 is demoted to severity="info" via the exception.
        sevs_by_id = {f.doc_id: f.severity for f in report.findings}
        assert sevs_by_id["SPEC-00000000000000000000000001"] == "info"
        assert sevs_by_id["SPEC-00000000000000000000000002"] == "error"
        # Aggregate totals exclude info findings.
        assert report.total == 1
        assert report.by_gate == {"terminal_status_progress": 1}

    def test_unknown_gate_raises(self, corpus: Path):
        from decree.commands.migrate import audit_coherence

        with pytest.raises(ValueError, match="Unknown gate"):
            audit_coherence(corpus, gates=["does_not_exist"])


# ─── CLI handler ──────────────────────────────────────────────────────────


def _args(project: Path, **overrides) -> argparse.Namespace:
    base = {
        "project": str(project),
        "gate": None,
        "fix": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestAuditCoherenceCLI:
    def test_clean_corpus_exits_zero(self, corpus: Path, capsys):
        _spec(corpus, "001-foo", "draft", "- [ ] todo\n")
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus))
        out = capsys.readouterr().out
        assert rc == 0
        assert "no findings" in out

    def test_findings_exit_one(self, corpus: Path, capsys):
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus))
        out = capsys.readouterr().out
        assert rc == 1
        assert "primary AC progress" in out
        assert "terminal_status_progress" in out

    def test_json_output_is_schema_stable(self, corpus: Path, capsys):
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus, json=True))
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 1
        assert set(payload.keys()) >= {"total", "by_gate", "by_type", "findings"}
        assert payload["total"] == 1
        finding = payload["findings"][0]
        assert set(finding.keys()) == {
            "doc_path",
            "doc_id",
            "gate",
            "severity",
            "message",
            "suggested_fix",
        }

    def test_gate_filter_arg(self, corpus: Path, capsys):
        # Mix two kinds of violations, ask for only one.
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        _prd(corpus, "001-bar", "approved", date.today() - timedelta(days=60))
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus, gate=["terminal_status_progress"], json=True))
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["by_gate"].keys() == {"terminal_status_progress"}

    def test_fix_mode_refuses_non_tty(self, corpus: Path, monkeypatch, capsys):
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        # Make stdin look like a non-TTY.
        fake_stdin = io.StringIO("")
        monkeypatch.setattr("sys.stdin", fake_stdin)
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus, fix=True))
        captured = capsys.readouterr()
        assert rc == 1
        # error() prints to stderr in decree.log
        assert "TTY" in captured.err or "tty" in captured.err.lower()

    def test_fix_mode_nothing_to_fix_exits_zero(self, corpus: Path, monkeypatch):
        # No findings → --fix is a no-op with exit 0 even without a TTY check
        # firing (we check TTY only when there are errors to walk).
        _spec(corpus, "001-foo", "draft", "- [ ] one\n")

        class _PsuedoTty(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setattr("sys.stdin", _PsuedoTty(""))
        from decree.commands.migrate import audit_coherence_run

        rc = audit_coherence_run(_args(corpus, fix=True))
        assert rc == 0


# ─── coherence_exceptions config parsing ──────────────────────────────────


class TestCoherenceExceptionsConfig:
    def test_block_parses_into_frozenset_map(self, corpus: Path):
        _write_corpus(
            corpus,
            extra_toml=(
                "\n[types.spec.coherence_exceptions]\n"
                'terminal_status_progress = ["SPEC-00000000000000000000000001", '
                '"SPEC-00000000000000000000000002"]\n'
            ),
        )
        from decree.config import get_project_root, load_coherence_exceptions, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        exc = load_coherence_exceptions()
        assert exc["spec"]["terminal_status_progress"] == frozenset(
            {"SPEC-00000000000000000000000001", "SPEC-00000000000000000000000002"}
        )

    def test_missing_block_returns_empty(self, corpus: Path):
        from decree.config import get_project_root, load_coherence_exceptions, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        exc = load_coherence_exceptions()
        # All types parsed, all empty dicts.
        assert set(exc.keys()) == {"prd", "adr", "spec"}
        assert all(v == {} for v in exc.values())

    def test_invalid_block_raises(self, corpus: Path):
        _write_corpus(
            corpus,
            extra_toml=('\n[types.spec.coherence_exceptions]\nterminal_status_progress = "not-a-list"\n'),
        )
        from decree.config import get_project_root, load_coherence_exceptions, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        with pytest.raises(ValueError, match="must be a list"):
            load_coherence_exceptions()

    def test_live_lint_skips_exception_listed_docs(self, corpus: Path):
        # Enable gate AND list SPEC-00000000000000000000000001 in exceptions → lint passes.
        _write_corpus(
            corpus,
            extra_toml=(
                "\n[types.spec.coherence]\n"
                "terminal_status_progress = true\n"
                "\n[types.spec.coherence_exceptions]\n"
                'terminal_status_progress = ["SPEC-00000000000000000000000001"]\n'
            ),
        )
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0

    def test_live_lint_still_flags_non_exception_docs(self, corpus: Path):
        _write_corpus(
            corpus,
            extra_toml=(
                "\n[types.spec.coherence]\n"
                "terminal_status_progress = true\n"
                "\n[types.spec.coherence_exceptions]\n"
                'terminal_status_progress = ["SPEC-00000000000000000000000001"]\n'
            ),
        )
        _spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        _spec(corpus, "002-bar", "implemented", "- [x] one\n- [ ] two\n")
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        from decree.commands import lint

        rc = lint.run()
        assert rc == 1
