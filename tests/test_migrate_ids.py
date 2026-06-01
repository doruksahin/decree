"""Tests for `decree migrate ids`."""

import argparse

import frontmatter

from decree.commands import migrate


def _toml() -> str:
    return """\
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "superseded"]
warn_on_reference = ["superseded"]
required_sections = ["Context and Problem Statement"]

[types.adr.transitions]
proposed = ["accepted"]
accepted = ["superseded"]
superseded = []

[types.adr.actions]
accept = "accepted"
supersede = "superseded"

[types.adr.status_field_requirements]
superseded = ["superseded-by"]
"""


def _legacy_project(tmp_path):
    (tmp_path / "decree.toml").write_text(_toml())
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "reports").mkdir()
    (adr / "0001-old.md").write_text(
        """---
status: superseded
date: 2026-01-01
superseded-by: ADR-0002
---

# ADR-0001 Old

## Context and Problem Statement

Old.
"""
    )
    (adr / "0002-new.md").write_text(
        """---
status: accepted
date: 2026-01-02
references: [ADR-0001]
supersedes: ADR-0001
---

# ADR-0002 New

## Context and Problem Statement

New.
"""
    )
    (adr / "reports" / "ADR-0002.md").write_text("# ADR-0002 report\n\nRefs ADR-0001\n")
    return tmp_path


def _ids():
    yield "ADR-00000000000000000000000001"
    yield "ADR-00000000000000000000000002"


def test_migrate_ids_dry_run_does_not_write(tmp_path, monkeypatch):
    project = _legacy_project(tmp_path)
    ids = _ids()
    monkeypatch.setattr("decree.identity.generate_doc_id", lambda prefix: next(ids))

    rc = migrate.migrate_ids_run(argparse.Namespace(project=str(project), dry_run=True, apply=False))

    assert rc == 0
    assert (project / "docs" / "adr" / "0001-old.md").exists()
    assert not (project / "decree" / "migrations").exists()


def test_migrate_ids_apply_rewrites_docs_refs_reports_and_index(tmp_path, monkeypatch):
    project = _legacy_project(tmp_path)
    ids = _ids()
    monkeypatch.setattr("decree.identity.generate_doc_id", lambda prefix: next(ids))

    rc = migrate.migrate_ids_run(argparse.Namespace(project=str(project), dry_run=False, apply=True))

    assert rc == 0
    adr = project / "docs" / "adr"
    old_path = adr / "0001-old.md"
    new_path = adr / "adr-00000000000000000000000001-old.md"
    replacement = adr / "adr-00000000000000000000000002-new.md"
    assert not old_path.exists()
    assert new_path.exists()
    assert replacement.exists()

    post = frontmatter.load(str(replacement))
    assert post["id"] == "ADR-00000000000000000000000002"
    assert post["references"] == ["ADR-00000000000000000000000001"]
    assert post["supersedes"] == "ADR-00000000000000000000000001"
    assert "# ADR-00000000000000000000000002 New" in post.content

    assert not (adr / "reports" / "ADR-0002.md").exists()
    report = adr / "reports" / "ADR-00000000000000000000000002.md"
    assert report.exists()
    assert "ADR-00000000000000000000000001" in report.read_text()
    assert (adr / "index.md").exists()
    assert list((project / "decree" / "migrations").glob("*-id-migration.json"))
