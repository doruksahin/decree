"""Tests for decree.parser — document frontmatter parsing and file I/O."""

from datetime import date
from pathlib import Path

import pytest

from decree.doctypes import ADR_DEFAULT
from decree.parser import (
    DocDocument,
    DocFrontmatter,
    find_by_id,
    load,
    load_all,
    save,
)

ADR_1 = "ADR-00000000000000000000000001"
ADR_2 = "ADR-00000000000000000000000002"
ADR_3 = "ADR-00000000000000000000000003"
ADR_5 = "ADR-00000000000000000000000005"
ADR_99 = "ADR-00000000000000000000000099"
ADR_1_FILE = "adr-00000000000000000000000001-test.md"


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
            status="superseded",
            date=date(2026, 4, 2),
            **{"superseded-by": ADR_5},
        )
        assert fm.superseded_by == ADR_5

    def test_invalid_adr_ref(self):
        with pytest.raises(ValueError, match="must match format"):
            DocFrontmatter(
                status="superseded",
                date=date(2026, 4, 2),
                **{"superseded-by": "0005"},
            )

    def test_references_require_canonical_ids(self):
        with pytest.raises(ValueError, match="TYPE-ULID"):
            DocFrontmatter(
                status="proposed",
                date=date(2026, 4, 2),
                references=["ADR-0001"],
            )

    def test_references_are_normalized(self):
        fm = DocFrontmatter(
            status="proposed",
            date=date(2026, 4, 2),
            references=["prd-00000000000000000000000001"],
        )
        assert fm.references == ["PRD-00000000000000000000000001"]

    def test_date_serializer(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        dumped = fm.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert dumped["date"] == "2026-04-02"

    def test_optional_fields_excluded(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        dumped = fm.model_dump(by_alias=True, exclude_none=True)
        assert "supersedes" not in dumped

    def test_attachments_roundtrip(self):
        fm = DocFrontmatter(
            status="proposed",
            date=date(2026, 4, 2),
            attachments=[".stitch/overview.png"],
        )
        dumped = fm.model_dump(by_alias=True, exclude_none=True)
        assert dumped["attachments"] == [".stitch/overview.png"]

    def test_attachments_none_excluded(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        dumped = fm.model_dump(by_alias=True, exclude_none=True)
        assert "attachments" not in dumped

    def test_evolve_changes_status(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        evolved = fm.evolve(status="accepted")
        assert evolved.status == "accepted"
        assert evolved.date == date(2026, 4, 2)  # preserved

    def test_evolve_adds_field(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        evolved = fm.evolve(status="superseded", **{"superseded-by": ADR_5})
        assert evolved.status == "superseded"
        assert evolved.superseded_by == ADR_5


class TestGovernsFrontmatter:
    """SPEC-00000000000000000000000004: governs is a typed list of path or path#symbol entries."""

    def test_well_formed_path(self):
        fm = DocFrontmatter(
            status="proposed",
            date=date(2026, 4, 2),
            governs=["src/decree/c4.py"],
        )
        assert fm.governs == ["src/decree/c4.py"]

    def test_symbol_form(self):
        fm = DocFrontmatter(
            status="proposed",
            date=date(2026, 4, 2),
            governs=["src/decree/parser.py#DocFrontmatter"],
        )
        assert fm.governs == ["src/decree/parser.py#DocFrontmatter"]

    def test_absent_field(self):
        fm = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        assert fm.governs is None

    def test_non_string_entry_rejected(self):
        # Pydantic's typed `list[str]` rejects non-string entries with `string_type`
        # before our custom validator runs. Either way, a non-string entry is rejected
        # with a clear error — which is what the SPEC AC requires.
        with pytest.raises(ValueError, match=r"(governs entries must be strings|valid string)"):
            DocFrontmatter(
                status="proposed",
                date=date(2026, 4, 2),
                governs=[123],  # type: ignore[list-item]
            )

    def test_leading_slash_rejected(self):
        with pytest.raises(ValueError, match="repo-relative"):
            DocFrontmatter(
                status="proposed",
                date=date(2026, 4, 2),
                governs=["/abs/path.py"],
            )

    def test_dotdot_segment_rejected(self):
        with pytest.raises(ValueError, match=r"'\.\.' segments"):
            DocFrontmatter(
                status="proposed",
                date=date(2026, 4, 2),
                governs=["../outside.py"],
            )

    def test_empty_path_part_rejected(self):
        with pytest.raises(ValueError, match="empty path"):
            DocFrontmatter(
                status="proposed",
                date=date(2026, 4, 2),
                governs=["#bar"],
            )


class TestDocDocument:
    def _make_doc(
        self,
        filename=ADR_1_FILE,
        body=f"# {ADR_1} Test Title\n\n## Context and Problem Statement\n\nText.\n",
    ):
        meta = DocFrontmatter(id=ADR_1, status="proposed", date=date(2026, 4, 2))
        return DocDocument(path=Path(f"/fake/{filename}"), meta=meta, body=body, doc_type=ADR_DEFAULT)

    def test_doc_id(self):
        assert self._make_doc().doc_id == ADR_1

    def test_title_from_h1(self):
        assert self._make_doc().title == "Test Title"

    def test_title_fallback(self):
        doc = self._make_doc(body="No heading.\n")
        assert doc.title == "adr-00000000000000000000000001-test"

    def test_sections(self):
        body = "# T\n\n## Context and Problem Statement\n\n## Considered Options\n"
        assert self._make_doc(body=body).sections == [
            "Context and Problem Statement",
            "Considered Options",
        ]

    def test_missing_sections(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        from decree.config import load_doc_types

        adr_type = load_doc_types()[0]
        meta = DocFrontmatter(id=ADR_1, status="proposed", date=date(2026, 4, 2))
        body = "# T\n\n## Context and Problem Statement\n\nText.\n"
        doc = DocDocument(path=Path(f"/fake/{ADR_1_FILE}"), meta=meta, body=body, doc_type=adr_type)
        missing = doc.missing_sections
        assert "Considered Options" in missing
        assert "Decision Outcome" in missing
        assert "Consequences" in missing
        assert "Context and Problem Statement" not in missing


class TestFileIO:
    def _write_doc(self, path: Path, doc_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nid: {doc_id}\nstatus: proposed\ndate: 2026-04-02\n---\n\n# {doc_id} Test\n")

    def test_roundtrip(self, tmp_path):
        f = tmp_path / ADR_1_FILE
        f.write_text(f"---\nid: {ADR_1}\nstatus: proposed\ndate: 2026-04-02\n---\n\n# {ADR_1} Test\n")
        doc = load(f)
        assert doc.meta.status == "proposed"
        doc.meta = DocFrontmatter(id=ADR_1, status="accepted", date=doc.meta.date)
        save(doc)
        assert load(f).meta.status == "accepted"

    def test_save_excludes_empty_lists(self, tmp_path):
        f = tmp_path / ADR_1_FILE
        meta = DocFrontmatter(id=ADR_1, status="proposed", date=date(2026, 4, 2), deciders=[])
        doc = DocDocument(path=f, meta=meta, body="# T\n")
        save(doc)
        assert "deciders" not in f.read_text()

    def test_find_by_id(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        f = project_dir / "docs" / "adr" / ADR_1_FILE
        f.write_text(f"---\nid: {ADR_1}\nstatus: proposed\ndate: 2026-04-02\n---\n\n# {ADR_1} Test\n")
        assert find_by_id(ADR_1).doc_id == ADR_1

    def test_load_all_discovers_nested_documents_and_skips_generated_paths(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        from decree.config import load_doc_types

        doc_type = load_doc_types()[0]
        type_dir = project_dir / "docs" / "adr"
        self._write_doc(type_dir / ADR_1_FILE, ADR_1)
        self._write_doc(type_dir / "platform" / f"{ADR_2.lower()}-nested.md", ADR_2)
        self._write_doc(type_dir / "reports" / f"{ADR_3.lower()}-report.md", ADR_3)
        self._write_doc(type_dir / ".hidden" / f"{ADR_5.lower()}-hidden.md", ADR_5)
        (type_dir / "platform" / "index.md").write_text("# generated\n")
        (type_dir / "platform" / "notes.md").write_text("# non-canonical\n")

        docs = load_all(doc_type=doc_type)

        assert [doc.doc_id for doc in docs] == [ADR_1, ADR_2]
        assert docs[1].path.parent.name == "platform"

    def test_find_by_id_resolves_nested_document_and_rejects_duplicates(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        type_dir = project_dir / "docs" / "adr"
        self._write_doc(type_dir / "platform" / f"{ADR_5.lower()}-nested.md", ADR_5)

        assert find_by_id(ADR_5).path == type_dir / "platform" / f"{ADR_5.lower()}-nested.md"

        self._write_doc(type_dir / f"{ADR_5.lower()}-root.md", ADR_5)
        with pytest.raises(ValueError, match="Multiple files match"):
            find_by_id(ADR_5)

    def test_find_by_id_not_found(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        with pytest.raises(FileNotFoundError):
            find_by_id(ADR_99)
