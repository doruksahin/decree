"""Tests for SPEC-00000000000000000000000005 — `decree why` and `decree refs` queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from decree.commands.queries import (
    MatchKind,
    refs,
    refs_run,
    why,
    why_run,
)
from decree.index_db import IndexDB, default_db_path

# ── Fixtures ───────────────────────────────────────────────


def _decree_toml() -> str:
    """Minimal three-type decree.toml. Mirrors tests/test_index_db.py."""
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


def _write_basic_corpus(root: Path) -> None:
    """A PRD + ADR + SPEC where SPEC governs `src/foo.py`."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "adr" / "adr-00000000000000000000000001-test.md").write_text(
        """---
id: ADR-00000000000000000000000001
status: accepted
date: 2026-05-11
references: [PRD-00000000000000000000000001]
---

# ADR-00000000000000000000000001 Test ADR

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001, ADR-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Test SPEC

## Overview

Prose.
"""
    )


def _write_prefix_corpus(root: Path) -> None:
    """A SPEC governing the directory `src/api/`."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src" / "api").mkdir(parents=True)
    (root / "src" / "api" / "handlers.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/api/
---

# SPEC-00000000000000000000000001 Dir SPEC

## Overview

Prose.
"""
    )


def _write_two_specs_same_file(root: Path) -> None:
    """Two SPECs governing `src/foo.py` — one implemented (newer), one draft (older)."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    # Draft SPEC — newer date but lower status priority
    (root / "decree" / "spec" / "spec-00000000000000000000000002-draft.md").write_text(
        """---
id: SPEC-00000000000000000000000002
status: draft
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000002 Draft

## Overview

Prose.
"""
    )
    # Implemented SPEC — older date but terminal-success
    (root / "decree" / "spec" / "spec-00000000000000000000000001-impl.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-01
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Implemented

## Overview

Prose.
"""
    )


def _write_recency_corpus(root: Path) -> None:
    """Two SPECs same status, different date — newer should win."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-old.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-01
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Old

## Overview

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000002-new.md").write_text(
        """---
id: SPEC-00000000000000000000000002
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000002 New

## Overview

Prose.
"""
    )


def _write_supersedes_chain(root: Path) -> None:
    """Write ADR-1 <- ADR-2 <- ADR-3 supersede chain."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)

    (root / "decree" / "adr" / "adr-00000000000000000000000003-c.md").write_text(
        """---
id: ADR-00000000000000000000000003
status: accepted
date: 2026-05-12
supersedes: ADR-00000000000000000000000002
---

# ADR-00000000000000000000000003 Newest

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "adr" / "adr-00000000000000000000000002-b.md").write_text(
        """---
id: ADR-00000000000000000000000002
status: superseded
date: 2026-05-11
supersedes: ADR-00000000000000000000000001
superseded-by: ADR-00000000000000000000000003
---

# ADR-00000000000000000000000002 Middle

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "adr" / "adr-00000000000000000000000001-a.md").write_text(
        """---
id: ADR-00000000000000000000000001
status: superseded
date: 2026-05-10
superseded-by: ADR-00000000000000000000000002
---

# ADR-00000000000000000000000001 Oldest

## Context and Problem Statement

Prose.
"""
    )


def _rebuild_index(root: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    db = IndexDB(default_db_path(root))
    db.rebuild(root)
    return db


@pytest.fixture
def basic_db(tmp_path: Path, monkeypatch) -> IndexDB:
    _write_basic_corpus(tmp_path)
    return _rebuild_index(tmp_path, monkeypatch)


@pytest.fixture
def basic_project(tmp_path: Path, monkeypatch) -> Path:
    _write_basic_corpus(tmp_path)
    _rebuild_index(tmp_path, monkeypatch)
    return tmp_path


# ── why() — unit tests ─────────────────────────────────────


class TestWhyMatching:
    def test_exact_match(self, basic_db: IndexDB):
        results = why(basic_db, "src/foo.py")
        assert len(results) == 1
        assert results[0].decision_id == "SPEC-00000000000000000000000001"
        assert results[0].match_kind == MatchKind.EXACT
        assert results[0].matched_path == "src/foo.py"

    def test_prefix_match(self, tmp_path: Path, monkeypatch):
        _write_prefix_corpus(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        results = why(db, "src/api/handlers.py")
        assert len(results) == 1
        assert results[0].decision_id == "SPEC-00000000000000000000000001"
        assert results[0].match_kind == MatchKind.PREFIX
        assert results[0].matched_path == "src/api/"

    def test_no_match(self, basic_db: IndexDB):
        results = why(basic_db, "unrelated/path.py")
        assert results == []

    def test_symbol_stripped(self, basic_db: IndexDB):
        results = why(basic_db, "src/foo.py#bar")
        assert len(results) == 1
        assert results[0].decision_id == "SPEC-00000000000000000000000001"
        assert results[0].symbol == "bar"

    def test_exact_wins_over_prefix(self, tmp_path: Path, monkeypatch):
        """If both an exact and a prefix match exist for the same decision, exact wins."""
        (tmp_path / "decree.toml").write_text(_decree_toml())
        for sub in ("prd", "adr", "spec"):
            (tmp_path / "decree" / sub).mkdir(parents=True)
        (tmp_path / "src" / "api").mkdir(parents=True)
        (tmp_path / "src" / "api" / "x.py").touch()
        (tmp_path / "decree" / "prd" / "prd-00000000000000000000000001-x.md").write_text(
            "---\n"
            "id: PRD-00000000000000000000000001\n"
            "status: approved\n"
            "date: 2026-05-10\n"
            "---\n\n"
            "# PRD-00000000000000000000000001\n\n"
            "## Problem Statement\n\n"
            "x.\n"
        )
        (tmp_path / "decree" / "spec" / "spec-00000000000000000000000001-x.md").write_text(
            """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/api/
  - src/api/x.py
---

# SPEC-00000000000000000000000001 Both

## Overview

Prose.
"""
        )
        db = _rebuild_index(tmp_path, monkeypatch)
        results = why(db, "src/api/x.py")
        # Only one row for SPEC-00000000000000000000000001 — exact wins
        assert len(results) == 1
        assert results[0].match_kind == MatchKind.EXACT


class TestWhyOrdering:
    def test_status_priority(self, tmp_path: Path, monkeypatch):
        _write_two_specs_same_file(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        results = why(db, "src/foo.py")
        assert len(results) == 2
        # Implemented (terminal-success) sorts before draft (active)
        assert results[0].decision_id == "SPEC-00000000000000000000000001"
        assert results[0].status == "implemented"
        assert results[1].decision_id == "SPEC-00000000000000000000000002"
        assert results[1].status == "draft"

    def test_recency_tiebreak(self, tmp_path: Path, monkeypatch):
        _write_recency_corpus(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        results = why(db, "src/foo.py")
        assert len(results) == 2
        # Same status; newer date first
        assert results[0].decision_id == "SPEC-00000000000000000000000002"
        assert results[0].date == "2026-05-12"
        assert results[1].decision_id == "SPEC-00000000000000000000000001"


# ── why_run — CLI tests ────────────────────────────────────


class TestWhyCli:
    def test_human_output(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = why_run(argparse.Namespace(path="src/foo.py", json=False, project=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert "SPEC-00000000000000000000000001" in out
        assert "exact" in out

    def test_json_output(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = why_run(argparse.Namespace(path="src/foo.py", json=True, project=None))
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["query"] == "src/foo.py"
        assert data["match_count"] == 1
        assert data["matches"][0]["decision_id"] == "SPEC-00000000000000000000000001"
        assert data["matches"][0]["match_kind"] == "exact"
        assert data["matches"][0]["type"] == "spec"
        assert data["matches"][0]["status"] == "implemented"

    def test_no_match_exit_zero(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = why_run(argparse.Namespace(path="not/governed.py", json=False, project=None))
        assert rc == 0  # Abstention is not an error

    def test_missing_index_exit_one(self, tmp_path: Path, monkeypatch, capsys):
        # decree.toml exists but no .decree/index.sqlite
        (tmp_path / "decree.toml").write_text(_decree_toml())
        for sub in ("prd", "adr", "spec"):
            (tmp_path / "decree" / sub).mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        rc = why_run(argparse.Namespace(path="src/foo.py", json=False, project=None))
        assert rc == 1
        err = capsys.readouterr().err
        assert "decree index rebuild" in err

    def test_stale_index_exit_one(self, basic_project: Path, monkeypatch, capsys):
        # Mutate a doc after rebuild to induce drift
        (basic_project / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
            """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001, ADR-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Test SPEC

## Overview

Mutated content.
"""
        )
        monkeypatch.chdir(basic_project)
        rc = why_run(argparse.Namespace(path="src/foo.py", json=False, project=None))
        assert rc == 1
        err = capsys.readouterr().err
        assert "stale" in err.lower()
        assert "decree index rebuild" in err


# ── refs() — unit tests ────────────────────────────────────


class TestRefs:
    def test_forward_refs(self, basic_db: IndexDB):
        report = refs(basic_db, "SPEC-00000000000000000000000001")
        assert report is not None
        ids = {r.to_id for r in report.forward_refs}
        assert "PRD-00000000000000000000000001" in ids
        assert "ADR-00000000000000000000000001" in ids

    def test_reverse_refs(self, basic_db: IndexDB):
        report = refs(basic_db, "PRD-00000000000000000000000001")
        assert report is not None
        ids = {r.from_id for r in report.reverse_refs}
        # Both ADR-1 and SPEC-1 reference PRD-1.
        assert "ADR-00000000000000000000000001" in ids
        assert "SPEC-00000000000000000000000001" in ids

    def test_governs(self, tmp_path: Path, monkeypatch):
        # SPEC governing two paths
        (tmp_path / "decree.toml").write_text(_decree_toml())
        for sub in ("prd", "adr", "spec"):
            (tmp_path / "decree" / sub).mkdir(parents=True)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").touch()
        (tmp_path / "src" / "b.py").touch()
        (tmp_path / "decree" / "prd" / "prd-00000000000000000000000001-x.md").write_text(
            "---\n"
            "id: PRD-00000000000000000000000001\n"
            "status: approved\n"
            "date: 2026-05-10\n"
            "---\n\n"
            "# PRD-00000000000000000000000001\n\n"
            "## Problem Statement\n\n"
            "x.\n"
        )
        (tmp_path / "decree" / "spec" / "spec-00000000000000000000000001-x.md").write_text(
            """---
id: SPEC-00000000000000000000000001
status: draft
date: 2026-05-12
references: [PRD-00000000000000000000000001]
governs:
  - src/a.py
  - src/b.py
---

# SPEC-00000000000000000000000001 X

## Overview

Prose.
"""
        )
        db = _rebuild_index(tmp_path, monkeypatch)
        report = refs(db, "SPEC-00000000000000000000000001")
        assert report is not None
        paths = sorted(g.path for g in report.governs)
        assert paths == ["src/a.py", "src/b.py"]

    def test_commits_empty(self, basic_db: IndexDB):
        report = refs(basic_db, "SPEC-00000000000000000000000001")
        assert report is not None
        assert report.commits == ()

    def test_supersedes_chain(self, tmp_path: Path, monkeypatch):
        _write_supersedes_chain(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = refs(db, "ADR-00000000000000000000000001")
        assert report is not None
        # Full chain oldest → newest
        assert report.supersedes_chain == (
            "ADR-00000000000000000000000001",
            "ADR-00000000000000000000000002",
            "ADR-00000000000000000000000003",
        )

    def test_supersedes_chain_from_middle(self, tmp_path: Path, monkeypatch):
        _write_supersedes_chain(tmp_path)
        db = _rebuild_index(tmp_path, monkeypatch)
        report = refs(db, "ADR-00000000000000000000000002")
        assert report is not None
        # Walks both directions
        assert report.supersedes_chain == (
            "ADR-00000000000000000000000001",
            "ADR-00000000000000000000000002",
            "ADR-00000000000000000000000003",
        )

    def test_unknown_decision_returns_none(self, basic_db: IndexDB):
        assert refs(basic_db, "PRD-00000000000000000000000999") is None

    def test_metadata(self, basic_db: IndexDB):
        report = refs(basic_db, "SPEC-00000000000000000000000001")
        assert report is not None
        assert report.metadata.title == "Test SPEC"
        assert report.metadata.status == "implemented"
        assert report.metadata.type == "spec"
        assert len(report.metadata.body_hash) == 64  # sha256 hex


# ── refs_run — CLI tests ────────────────────────────────────


class TestRefsCli:
    def test_human_output(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = refs_run(argparse.Namespace(decision_id="SPEC-00000000000000000000000001", json=False, project=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert "SPEC-00000000000000000000000001" in out
        assert "Forward refs" in out
        assert "PRD-00000000000000000000000001" in out

    def test_json_output(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = refs_run(argparse.Namespace(decision_id="SPEC-00000000000000000000000001", json=True, project=None))
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["decision_id"] == "SPEC-00000000000000000000000001"
        # Schema-stable keys
        for key in ("metadata", "forward_refs", "reverse_refs", "supersedes_chain", "governs", "commits"):
            assert key in data
        assert data["commits"] == []
        ids = {r["to_id"] for r in data["forward_refs"]}
        assert "PRD-00000000000000000000000001" in ids

    def test_unknown_id_exits_one(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        rc = refs_run(argparse.Namespace(decision_id="PRD-00000000000000000000000999", json=False, project=None))
        assert rc == 1
        err = capsys.readouterr().err
        assert "unknown" in err.lower()

    def test_missing_index_exit_one(self, tmp_path: Path, monkeypatch, capsys):
        (tmp_path / "decree.toml").write_text(_decree_toml())
        for sub in ("prd", "adr", "spec"):
            (tmp_path / "decree" / sub).mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        rc = refs_run(argparse.Namespace(decision_id="SPEC-00000000000000000000000001", json=False, project=None))
        assert rc == 1
        err = capsys.readouterr().err
        assert "decree index rebuild" in err


# ── Integration: end-to-end via the CLI dispatch ───────────


class TestIntegration:
    def test_end_to_end_why(self, basic_project: Path, monkeypatch, capsys):
        """Calling main() end-to-end mirrors what a user sees."""
        monkeypatch.chdir(basic_project)
        monkeypatch.setattr("sys.argv", ["decree", "why", "src/foo.py"])
        from decree.cli import main

        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "SPEC-00000000000000000000000001" in out

    def test_end_to_end_refs_json(self, basic_project: Path, monkeypatch, capsys):
        monkeypatch.chdir(basic_project)
        monkeypatch.setattr("sys.argv", ["decree", "refs", "SPEC-00000000000000000000000001", "--json"])
        from decree.cli import main

        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["decision_id"] == "SPEC-00000000000000000000000001"
