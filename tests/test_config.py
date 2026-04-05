"""Tests for decree.config — core defaults and project override loading."""

import pytest
from pathlib import Path

from decree.config import load_doc_types, find_doc_type

from decree.config import (
    STATUSES, VALID_TRANSITIONS, STATUS_FIELD_REQUIREMENTS,
    MADR_REQUIRED_SECTIONS, OPTIONAL_SECTIONS, MADR_SECTION_DESCRIPTIONS,
    FILENAME_RE, SLUG_RE, ADR_REF_RE,
    get_project_root,
)


class TestCoreDefaults:
    def test_statuses(self):
        assert "proposed" in STATUSES
        assert "accepted" in STATUSES
        assert len(STATUSES) == 5

    def test_transitions_cover_all_statuses(self):
        assert set(VALID_TRANSITIONS) == set(STATUSES)

    def test_status_field_requirements_cover_all_statuses(self):
        assert set(STATUS_FIELD_REQUIREMENTS) == set(STATUSES)

    def test_superseded_requires_link(self):
        assert "superseded-by" in STATUS_FIELD_REQUIREMENTS["superseded"]

    def test_madr_required_sections(self):
        assert "Context and Problem Statement" in MADR_REQUIRED_SECTIONS
        assert "Considered Options" in MADR_REQUIRED_SECTIONS
        assert "Decision Outcome" in MADR_REQUIRED_SECTIONS

    def test_filename_re(self):
        assert FILENAME_RE.match("0001-test-slug.md")
        assert not FILENAME_RE.match("ADR-TEMPLATE.md")
        assert not FILENAME_RE.match("readme.md")
        assert not FILENAME_RE.match("ADR-0001-test-slug.md")

    def test_adr_ref_re(self):
        assert ADR_REF_RE.match("ADR-0001")
        assert not ADR_REF_RE.match("0001")
        assert not ADR_REF_RE.match("ADR-0001-slug.md")


class TestProjectConfig:
    def test_get_project_root(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        assert get_project_root() == project_dir

    def test_get_project_root_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="decree.toml not found"):
            get_project_root()

    def test_load_doc_types_adr(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        types = load_doc_types()
        assert len(types) == 1
        adr = types[0]
        assert adr.name == "adr"
        assert adr.dir == "docs/adr"

    def test_load_doc_types_required_sections(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        types = load_doc_types()
        adr = types[0]
        assert "Context and Problem Statement" in adr.required_sections
        assert "Consequences" in adr.required_sections
        assert "Affected Files" in adr.required_sections


class TestLoadDocTypes:
    def test_from_types_section(self, tmp_path, monkeypatch):
        """[types.*] loads multiple types."""
        (tmp_path / "decree.toml").write_text("""\
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
required_sections = ["Context and Problem Statement"]

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []

[types.adr.actions]
accept = "accepted"
reject = "rejected"

[types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = ["Problem Statement", "Requirements"]

[types.prd.transitions]
draft = ["approved"]
approved = []

[types.prd.actions]
approve = "approved"
""")
        monkeypatch.chdir(tmp_path)
        types = load_doc_types()
        assert len(types) == 2
        names = {t.name for t in types}
        assert names == {"adr", "prd"}

    def test_no_types_raises(self, tmp_path, monkeypatch):
        """If no [types.*] sections, raises ValueError."""
        (tmp_path / "decree.toml").write_text("")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="no \\[types\\.\\*\\] sections"):
            load_doc_types()

    def test_no_decree_toml_raises(self, tmp_path, monkeypatch):
        """If no decree.toml, raises FileNotFoundError."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="decree.toml not found"):
            load_doc_types()

    def test_validates_transitions_match_statuses(self, tmp_path, monkeypatch):
        """Transitions must only reference defined statuses."""
        (tmp_path / "decree.toml").write_text("""\
[types.bad]
dir = "docs/bad"
prefix = "BAD"
digits = 3
initial_status = "draft"
statuses = ["draft", "done"]
required_sections = []

[types.bad.transitions]
draft = ["nonexistent"]
done = []

[types.bad.actions]
finish = "done"
""")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="nonexistent"):
            load_doc_types()

    def test_find_by_prefix(self, tmp_path, monkeypatch):
        """Can look up a type by its prefix."""
        (tmp_path / "decree.toml").write_text("""\
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted"]
required_sections = []

[types.adr.transitions]
proposed = ["accepted"]
accepted = []

[types.adr.actions]
accept = "accepted"

[types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = []

[types.prd.transitions]
draft = ["approved"]
approved = []

[types.prd.actions]
approve = "approved"
""")
        monkeypatch.chdir(tmp_path)
        assert find_doc_type("ADR-0001").name == "adr"
        assert find_doc_type("PRD-001").name == "prd"
