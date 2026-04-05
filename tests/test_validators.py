"""Tests for decree.validators — pure validation functions."""
import pytest
from datetime import date
from pathlib import Path

from decree.parser import DocFrontmatter, DocDocument
from decree.validators import validate_sections, validate_cross_file_integrity
from decree.doctypes import ADR_DEFAULT


def _make_doc(adr_id_num="0001", status="proposed", body="# T\n", **fm_kwargs):
    meta = DocFrontmatter(status=status, date=date(2026, 4, 2), **fm_kwargs)
    return DocDocument(path=Path(f"/fake/{adr_id_num}-test.md"), meta=meta, body=body, doc_type=ADR_DEFAULT)


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
