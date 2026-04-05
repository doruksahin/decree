"""Tests for decree.parser — document frontmatter parsing and file I/O."""

import pytest
from datetime import date
from pathlib import Path

from decree.parser import DocFrontmatter, DocDocument, load, save, find_by_id, next_number
from decree.doctypes import ADR_DEFAULT


class TestDocFrontmatter:
    def test_valid_proposed(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        assert fm.status == "proposed"
        assert fm.date == date(2026, 4, 2)

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            DocFrontmatter(status="draft", date=date(2026, 4, 2))

    def test_superseded_requires_link(self):
        with pytest.raises(ValueError, match="requires field 'superseded-by'"):
            DocFrontmatter(status="superseded", date=date(2026, 4, 2))

    def test_superseded_with_link_ok(self):
        fm = DocFrontmatter(
            status="superseded", date=date(2026, 4, 2),
            **{"superseded-by": "ADR-0005"},
        )
        assert fm.superseded_by == "ADR-0005"

    def test_invalid_adr_ref(self):
        with pytest.raises(ValueError, match="must match format"):
            DocFrontmatter(
                status="superseded", date=date(2026, 4, 2),
                **{"superseded-by": "0005"},
            )

    def test_date_serializer(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        dumped = fm.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert dumped["date"] == "2026-04-02"

    def test_optional_fields_excluded(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        dumped = fm.model_dump(by_alias=True, exclude_none=True)
        assert "supersedes" not in dumped

    def test_evolve_changes_status(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        evolved = fm.evolve(status="accepted")
        assert evolved.status == "accepted"
        assert evolved.date == date(2026, 4, 2)  # preserved

    def test_evolve_adds_field(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        evolved = fm.evolve(status="superseded", **{"superseded-by": "ADR-0005"})
        assert evolved.status == "superseded"
        assert evolved.superseded_by == "ADR-0005"


class TestDocDocument:
    def _make_doc(self, filename="0001-test.md", body="# ADR-0001 Test Title\n\n## Context and Problem Statement\n\nText.\n"):
        meta = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        return DocDocument(path=Path(f"/fake/{filename}"), meta=meta, body=body, doc_type=ADR_DEFAULT)

    def test_doc_id(self):
        assert self._make_doc().doc_id == "ADR-0001"

    def test_adr_id_alias(self):
        assert self._make_doc().adr_id == "ADR-0001"

    def test_number(self):
        assert self._make_doc().number == 1

    def test_title_from_h1(self):
        assert self._make_doc().title == "ADR-0001 Test Title"

    def test_title_fallback(self):
        doc = self._make_doc(body="No heading.\n")
        assert doc.title == "0001-test"

    def test_sections(self):
        body = "# T\n\n## Context and Problem Statement\n\n## Considered Options\n"
        assert self._make_doc(body=body).sections == ["Context and Problem Statement", "Considered Options"]

    def test_missing_sections(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        from decree.config import load_doc_types
        adr_type = load_doc_types()[0]
        meta = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        body = "# T\n\n## Context and Problem Statement\n\nText.\n"
        doc = DocDocument(path=Path("/fake/0001-test.md"), meta=meta, body=body, doc_type=adr_type)
        missing = doc.missing_sections
        assert "Considered Options" in missing
        assert "Decision Outcome" in missing
        assert "Consequences" in missing
        assert "Context and Problem Statement" not in missing


class TestFileIO:
    def test_roundtrip(self, tmp_path):
        f = tmp_path / "0001-test.md"
        f.write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0001 Test\n")
        doc = load(f)
        assert doc.meta.status == "proposed"
        doc.meta = DocFrontmatter(status="accepted", date=doc.meta.date)
        save(doc)
        assert load(f).meta.status == "accepted"

    def test_save_excludes_empty_lists(self, tmp_path):
        f = tmp_path / "0001-clean.md"
        meta = DocFrontmatter(status="proposed", date=date(2026, 4, 2), deciders=[])
        doc = DocDocument(path=f, meta=meta, body="# T\n")
        save(doc)
        assert "deciders" not in f.read_text()

    def test_next_number_empty(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        assert next_number(ADR_DEFAULT) == 1

    def test_next_number_with_existing(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        adr_dir = project_dir / "docs" / "adr"
        (adr_dir / "0001-a.md").write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n# T\n")
        (adr_dir / "0003-b.md").write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n# T\n")
        assert next_number(ADR_DEFAULT) == 4

    def test_find_by_id(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        f = project_dir / "docs" / "adr" / "0001-test.md"
        f.write_text("---\nstatus: proposed\ndate: 2026-04-02\n---\n\n# ADR-0001 Test\n")
        assert find_by_id("ADR-0001").doc_id == "ADR-0001"

    def test_find_by_id_not_found(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        with pytest.raises(FileNotFoundError):
            find_by_id("ADR-0099")
