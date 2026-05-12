"""Tests for decree.validators — pure validation functions."""

from datetime import date
from pathlib import Path

from decree.doctypes import ADR_DEFAULT
from decree.parser import DocDocument, DocFrontmatter
from decree.validators import (
    validate_attachments_exist,
    validate_cross_file_integrity,
    validate_governs_paths,
    validate_sections,
)


def _make_doc(adr_id_num="0001", status="proposed", body="# T\n", **fm_kwargs):
    meta = DocFrontmatter(status=status, date=date(2026, 4, 2), **fm_kwargs)
    return DocDocument(
        path=Path(f"/fake/{adr_id_num}-test.md"),
        meta=meta,
        body=body,
        doc_type=ADR_DEFAULT,
    )


class TestValidateSections:
    def test_all_present(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        body = (
            "# T\n\n"
            "## Context and Problem Statement\n\n"
            "## Considered Options\n\n"
            "## Decision Outcome\n\n"
            "## Consequences\n\n"
            "## Affected Files\n\n"
            "## Validation Needed\n"
        )
        assert validate_sections(_make_doc(body=body)) == []

    def test_missing_reported(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        body = "# T\n\n## Context and Problem Statement\n"
        errors = validate_sections(_make_doc(body=body))
        assert any("Considered Options" in e for e in errors)
        assert any("Decision Outcome" in e for e in errors)


class TestCrossFileIntegrity:
    def test_symmetric_supersede_ok(self):
        old = _make_doc("0001", "superseded", **{"superseded-by": "ADR-0002"})
        new = _make_doc("0002", "proposed", supersedes="ADR-0001")
        assert validate_cross_file_integrity([old, new]) == []

    def test_asymmetric_supersede_error(self):
        old = _make_doc("0001", "superseded", **{"superseded-by": "ADR-0002"})
        new = _make_doc("0002", "proposed")  # missing supersedes
        errors = validate_cross_file_integrity([old, new])
        assert len(errors) == 1
        assert "CROSS-FILE" in errors[0]

    def test_missing_target_error(self):
        old = _make_doc("0001", "superseded", **{"superseded-by": "ADR-0099"})
        errors = validate_cross_file_integrity([old])
        assert any("does not exist" in e for e in errors)


class TestValidateGovernsPaths:
    """SPEC-004: lint reports a clear error per missing governs path."""

    def _governs_doc(self, tmp_path, governs):
        meta = DocFrontmatter(status="proposed", date=date(2026, 4, 2), governs=governs)
        doc_path = tmp_path / "docs" / "adr" / "0001-test.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        return DocDocument(path=doc_path, meta=meta, body="# T\n", doc_type=ADR_DEFAULT)

    def test_all_paths_exist(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").touch()
        doc = self._governs_doc(tmp_path, ["src/foo.py"])
        assert validate_governs_paths([doc], tmp_path) == []

    def test_missing_path_reported(self, tmp_path):
        doc = self._governs_doc(tmp_path, ["src/missing.py"])
        errors = validate_governs_paths([doc], tmp_path)
        assert len(errors) == 1
        assert "governs path does not exist: src/missing.py" in errors[0]
        assert "0001-test.md" in errors[0]

    def test_symbol_form_validates_path_only(self, tmp_path):
        """`path#symbol`: path must exist; symbol after `#` is preserved but not checked."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").touch()
        # Path exists, but the symbol `nonexistent_func` is NOT validated — should pass.
        doc = self._governs_doc(tmp_path, ["src/foo.py#nonexistent_func"])
        assert validate_governs_paths([doc], tmp_path) == []

    def test_symbol_form_with_missing_path_reports_path(self, tmp_path):
        doc = self._governs_doc(tmp_path, ["src/missing.py#whatever"])
        errors = validate_governs_paths([doc], tmp_path)
        assert len(errors) == 1
        # The error reports only the path part, not the full entry.
        assert "src/missing.py" in errors[0]
        assert "#whatever" not in errors[0]

    def test_absent_governs_no_errors(self, tmp_path):
        meta = DocFrontmatter(status="proposed", date=date(2026, 4, 2))
        doc_path = tmp_path / "docs" / "adr" / "0001-test.md"
        doc_path.parent.mkdir(parents=True)
        doc = DocDocument(path=doc_path, meta=meta, body="# T\n", doc_type=ADR_DEFAULT)
        assert validate_governs_paths([doc], tmp_path) == []

    def test_multiple_partial_missing(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").touch()
        doc = self._governs_doc(tmp_path, ["src/a.py", "src/b.py"])
        errors = validate_governs_paths([doc], tmp_path)
        assert len(errors) == 1
        assert "src/b.py" in errors[0]

    def test_directory_path_counts_as_existing(self, tmp_path):
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        doc = self._governs_doc(tmp_path, ["src/pkg"])
        assert validate_governs_paths([doc], tmp_path) == []


class TestValidateAttachments:
    def test_existing_file_passes(self, tmp_path):
        f = tmp_path / ".stitch" / "overview.png"
        f.parent.mkdir(parents=True)
        f.touch()
        doc = _make_doc(attachments=[".stitch/overview.png"])
        assert validate_attachments_exist([doc], tmp_path) == []

    def test_missing_file_errors(self, tmp_path):
        doc = _make_doc(attachments=[".stitch/missing.png"])
        errors = validate_attachments_exist([doc], tmp_path)
        assert len(errors) == 1
        assert "does not exist" in errors[0]
        assert "missing.png" in errors[0]

    def test_no_attachments_passes(self, tmp_path):
        doc = _make_doc()
        assert validate_attachments_exist([doc], tmp_path) == []

    def test_multiple_partial_missing(self, tmp_path):
        existing = tmp_path / "a.png"
        existing.touch()
        doc = _make_doc(attachments=["a.png", "b.png"])
        errors = validate_attachments_exist([doc], tmp_path)
        assert len(errors) == 1
        assert "b.png" in errors[0]
