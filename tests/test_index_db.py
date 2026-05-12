"""Tests for the SQLite provenance index (SPEC-003)."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from decree.index_db import (
    INDEX_DIR_NAME,
    INDEX_FILENAME,
    SCHEMA_VERSION,
    DriftFinding,
    IndexDB,
    default_db_path,
)


# ── Fixtures ───────────────────────────────────────────────


def _minimal_decree_toml() -> str:
    return """\
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
[types.adr.status_field_requirements]
superseded = ["superseded-by"]

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


def _write_corpus(root: Path) -> None:
    """Three-doc corpus: PRD → ADR → SPEC with checkboxes (primary + deferred)."""
    (root / "decree.toml").write_text(_minimal_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "decree" / "prd" / "001-test.md").write_text(
        """---
status: approved
date: 2026-05-12
---

# PRD-001 Test PRD

## Problem Statement

Prose explaining the problem.
"""
    )
    (root / "decree" / "adr" / "0001-test.md").write_text(
        """---
status: accepted
date: 2026-05-12
references: [PRD-001]
---

# ADR-0001 Test ADR

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "001-test.md").write_text(
        """---
status: draft
date: 2026-05-12
references: [PRD-001, ADR-0001]
---

# SPEC-001 Test SPEC

## Overview

Prose.

## Acceptance Criteria

- [x] Primary item 1
- [ ] Primary item 2

## What this does NOT do (deferred)

- [ ] Future thing
"""
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _write_corpus(tmp_path)
    return tmp_path


# ── Schema ───────────────────────────────────────────────────


class TestSchema:
    def test_init_creates_all_tables(self, project: Path):
        db = IndexDB(default_db_path(project))
        db.init_schema()
        tables = set(db.db.table_names())
        for t in ("decisions", "refs", "governs", "acceptance_criteria", "commits", "index_meta", "decisions_fts"):
            assert t in tables, f"missing table: {t}"

    def test_decisions_columns(self, project: Path):
        db = IndexDB(default_db_path(project))
        db.init_schema()
        cols = {c.name for c in db.db["decisions"].columns}
        expected = {"id", "type", "status", "title", "path", "date", "body_hash", "indexed_at", "raw_metadata"}
        assert expected.issubset(cols)

    def test_refs_composite_primary_key(self, project: Path):
        db = IndexDB(default_db_path(project))
        db.init_schema()
        pks = db.db["refs"].pks
        assert set(pks) == {"from_id", "to_id", "kind"}

    def test_acceptance_criteria_has_deferred_column(self, project: Path):
        db = IndexDB(default_db_path(project))
        db.init_schema()
        cols = {c.name for c in db.db["acceptance_criteria"].columns}
        assert "deferred" in cols

    def test_fts_table_created(self, project: Path):
        db = IndexDB(default_db_path(project))
        db.init_schema()
        # FTS5 virtual table is queryable
        rows = list(db.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='decisions_fts'"))
        assert rows


# ── Rebuild ─────────────────────────────────────────────────


class TestRebuild:
    def test_rebuild_populates_decisions(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        stats = db.rebuild(project)
        assert stats.decisions == 3
        rows = list(db.db["decisions"].rows)
        ids = sorted(r["id"] for r in rows)
        assert ids == ["ADR-0001", "PRD-001", "SPEC-001"]

    def test_rebuild_populates_refs(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        refs = sorted((r["from_id"], r["to_id"], r["kind"]) for r in db.db["refs"].rows)
        # ADR-0001 → PRD-001, SPEC-001 → PRD-001, SPEC-001 → ADR-0001
        assert ("ADR-0001", "PRD-001", "references") in refs
        assert ("SPEC-001", "PRD-001", "references") in refs
        assert ("SPEC-001", "ADR-0001", "references") in refs

    def test_rebuild_classifies_acceptance_criteria(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        acs = list(db.db["acceptance_criteria"].rows)
        primary = [a for a in acs if a["deferred"] == 0]
        deferred = [a for a in acs if a["deferred"] == 1]
        assert len(primary) == 2  # Primary item 1 + 2
        assert len(deferred) == 1  # Future thing
        # Primary item 1 is done; Primary item 2 is not
        done_texts = {a["text"] for a in primary if a["done"]}
        assert "Primary item 1" in done_texts
        not_done_texts = {a["text"] for a in primary if not a["done"]}
        assert "Primary item 2" in not_done_texts

    def test_rebuild_idempotent(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        s1 = db.rebuild(project)
        s2 = db.rebuild(project)
        # Same row counts on the second rebuild
        assert s2.decisions == s1.decisions
        assert s2.refs == s1.refs
        assert s2.acceptance_criteria == s1.acceptance_criteria
        # Body hashes preserved
        hashes_before = {r["id"]: r["body_hash"] for r in db.db["decisions"].rows}
        db.rebuild(project)
        hashes_after = {r["id"]: r["body_hash"] for r in db.db["decisions"].rows}
        assert hashes_before == hashes_after

    def test_rebuild_does_not_wipe_commits(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        # Insert a fake commit row
        db.db["commits"].insert(
            {"sha": "abc123", "decision_id": "SPEC-001", "trailer_kind": "Implements", "summary": "test", "committed_at": "2026-05-12"},
            replace=True,
        )
        assert db.db["commits"].count == 1
        # Rebuild — should preserve the commits row
        db.rebuild(project)
        assert db.db["commits"].count == 1

    def test_body_hash_stable(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        h1 = {r["id"]: r["body_hash"] for r in db.db["decisions"].rows}
        db.rebuild(project)
        h2 = {r["id"]: r["body_hash"] for r in db.db["decisions"].rows}
        assert h1 == h2

    def test_rebuild_populates_governs_from_typed_field(self, monkeypatch, project: Path):
        """SPEC-004: rebuild reads governs off doc.meta.governs (typed) and splits #symbol."""
        monkeypatch.chdir(project)
        # Replace SPEC-001 with a governs block (paths must exist for parser to accept).
        (project / "src").mkdir()
        (project / "src" / "foo.py").touch()
        (project / "src" / "bar.py").touch()
        (project / "decree" / "spec" / "001-test.md").write_text(
            """---
status: draft
date: 2026-05-12
references: [PRD-001, ADR-0001]
governs:
  - src/foo.py
  - src/bar.py#baz
---

# SPEC-001 Test SPEC

## Overview

Prose.
"""
        )
        db = IndexDB(default_db_path(project))
        stats = db.rebuild(project)
        # Two governs rows for SPEC-001.
        rows = sorted(
            (r["decision_id"], r["path"], r["symbol"], r["order_index"])
            for r in db.db["governs"].rows
        )
        assert rows == [
            ("SPEC-001", "src/bar.py", "baz", 1),
            ("SPEC-001", "src/foo.py", "", 0),
        ]
        assert stats.governs == 2

    def test_rebuild_then_status(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        status = db.status()
        assert status.exists
        assert status.schema_version == SCHEMA_VERSION
        assert status.row_counts["decisions"] == 3


# ── Verify (drift detection) ───────────────────────────────────


class TestVerify:
    def test_verify_clean_after_rebuild(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        findings = db.verify(project)
        assert findings == []

    def test_verify_detects_body_drift(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)

        spec_path = project / "decree" / "spec" / "001-test.md"
        text = spec_path.read_text()
        spec_path.write_text(text + "\nAdded line after rebuild.\n")

        findings = db.verify(project)
        assert any(f.kind == "body_hash_mismatch" and f.decision_id == "SPEC-001" for f in findings)

    def test_verify_detects_missing_in_index(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        # Add a new spec after rebuild
        new_spec = project / "decree" / "spec" / "002-new.md"
        new_spec.write_text(
            """---
status: draft
date: 2026-05-12
references: [PRD-001]
---

# SPEC-002 New SPEC

## Overview

Prose.
"""
        )
        findings = db.verify(project)
        assert any(f.kind == "missing_in_index" and f.decision_id == "SPEC-002" for f in findings)

    def test_verify_detects_stale_in_index(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        # Remove a spec from disk after rebuild
        (project / "decree" / "spec" / "001-test.md").unlink()
        findings = db.verify(project)
        assert any(f.kind == "stale_in_index" and f.decision_id == "SPEC-001" for f in findings)

    def test_verify_index_missing(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        # Don't rebuild — no DB yet
        findings = db.verify(project)
        assert any(f.kind == "index_missing" for f in findings)


# ── FTS ─────────────────────────────────────────────────────


class TestFTS:
    def test_fts_match_returns_relevant(self, monkeypatch, project: Path):
        monkeypatch.chdir(project)
        db = IndexDB(default_db_path(project))
        db.rebuild(project)
        # Search for a body-only term — should hit SPEC-001
        rows = list(db.db.conn.execute("SELECT id FROM decisions_fts WHERE decisions_fts MATCH 'primary' "))
        ids = {r[0] for r in rows}
        assert "SPEC-001" in ids


# ── Storage location ───────────────────────────────────────────


class TestStorage:
    def test_default_db_path(self, tmp_path: Path):
        p = default_db_path(tmp_path)
        assert p == tmp_path / INDEX_DIR_NAME / INDEX_FILENAME

    def test_init_creates_parent_directory(self, tmp_path: Path):
        p = tmp_path / INDEX_DIR_NAME / INDEX_FILENAME
        assert not p.parent.exists()
        IndexDB(p).init_schema()
        assert p.parent.exists()


# ── CLI dispatch ───────────────────────────────────────────────


class TestCli:
    def test_rebuild_run(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import rebuild_run

        rc = rebuild_run(argparse.Namespace(project=None))
        assert rc == 0
        # Index file should exist
        assert (project / INDEX_DIR_NAME / INDEX_FILENAME).exists()

    def test_status_run_when_missing(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import status_run

        rc = status_run(argparse.Namespace(project=None))
        assert rc == 1

    def test_status_run_after_rebuild(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import rebuild_run, status_run

        rebuild_run(argparse.Namespace(project=None))
        rc = status_run(argparse.Namespace(project=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Schema version:" in out

    def test_verify_run_clean(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import rebuild_run, verify_run

        rebuild_run(argparse.Namespace(project=None))
        rc = verify_run(argparse.Namespace(project=None, json=False))
        assert rc == 0

    def test_verify_run_json(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import rebuild_run, verify_run

        rebuild_run(argparse.Namespace(project=None))
        rc = verify_run(argparse.Namespace(project=None, json=True))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data == []
        assert rc == 0

    def test_verify_run_reports_drift(self, monkeypatch, project: Path, capsys):
        monkeypatch.chdir(project)
        from decree.commands.index_db_cli import rebuild_run, verify_run

        rebuild_run(argparse.Namespace(project=None))
        # Mutate after rebuild
        (project / "decree" / "spec" / "001-test.md").write_text(
            "---\nstatus: draft\ndate: 2026-05-12\nreferences: [PRD-001]\n---\n\n# SPEC-001 Mutated\n\n## Overview\n\nChanged.\n"
        )
        rc = verify_run(argparse.Namespace(project=None, json=False))
        assert rc == 1
