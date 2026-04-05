"""Tests for decree.config — core defaults and project override loading."""

import pytest
from pathlib import Path

from decree.config import load_doc_types, find_doc_type

from decree.config import (
    STATUSES, VALID_TRANSITIONS, STATUS_FIELD_REQUIREMENTS,
    MADR_REQUIRED_SECTIONS, OPTIONAL_SECTIONS, MADR_SECTION_DESCRIPTIONS,
    FILENAME_RE, SLUG_RE, ADR_REF_RE,
    get_project_root, get_adr_dir, get_required_sections,
    get_section_descriptions, get_template_path,
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

    def test_get_adr_dir(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        assert get_adr_dir() == project_dir / "docs" / "adr"

    def test_get_required_sections_includes_project(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        sections = get_required_sections()
        assert "Context and Problem Statement" in sections
        assert "Consequences" in sections
        assert "Affected Files" in sections

    def test_get_required_sections_without_project_config(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "bare"\n')
        monkeypatch.chdir(tmp_path)
        sections = get_required_sections()
        assert sections == MADR_REQUIRED_SECTIONS

    def test_get_template_path_default(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        path = get_template_path()
        assert path.name == "madr-v4.md"

    def test_get_template_path_custom(self, project_dir, monkeypatch):
        monkeypatch.chdir(project_dir)
        custom = project_dir / "my-template.md"
        custom.write_text("---\nstatus: proposed\n---\n# Custom\n")
        pyproject = project_dir / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n\n'
            '[tool.adr]\n'
            'template = "my-template.md"\n'
        )
        path = get_template_path()
        assert path == custom


class TestLoadDocTypes:
    def test_from_tool_doc(self, tmp_path, monkeypatch):
        """[tool.doc.types.*] loads multiple types."""
        (tmp_path / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
required_sections = ["Context and Problem Statement"]

[tool.doc.types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []

[tool.doc.types.adr.actions]
accept = "accepted"
reject = "rejected"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = ["Problem Statement", "Requirements"]

[tool.doc.types.prd.transitions]
draft = ["approved"]
approved = []

[tool.doc.types.prd.actions]
approve = "approved"
""")
        monkeypatch.chdir(tmp_path)
        types = load_doc_types()
        assert len(types) == 2
        names = {t.name for t in types}
        assert names == {"adr", "prd"}

    def test_fallback_to_tool_adr(self, tmp_path, monkeypatch):
        """If no [tool.doc], falls back to [tool.adr] → single ADR type."""
        (tmp_path / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.adr]
adr_dir = "my/adrs"
project_sections = ["Consequences"]
""")
        monkeypatch.chdir(tmp_path)
        types = load_doc_types()
        assert len(types) == 1
        assert types[0].name == "adr"
        assert types[0].dir == "my/adrs"
        assert "Consequences" in types[0].required_sections

    def test_no_config_returns_adr_default(self, tmp_path, monkeypatch):
        """If no [tool.doc] and no [tool.adr], returns ADR_DEFAULT."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        monkeypatch.chdir(tmp_path)
        types = load_doc_types()
        assert len(types) == 1
        assert types[0].name == "adr"
        assert types[0].prefix == "ADR"

    def test_validates_transitions_match_statuses(self, tmp_path, monkeypatch):
        """Transitions must only reference defined statuses."""
        (tmp_path / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.doc.types.bad]
dir = "docs/bad"
prefix = "BAD"
digits = 3
initial_status = "draft"
statuses = ["draft", "done"]
required_sections = []

[tool.doc.types.bad.transitions]
draft = ["nonexistent"]
done = []

[tool.doc.types.bad.actions]
finish = "done"
""")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="nonexistent"):
            load_doc_types()

    def test_find_by_prefix(self, tmp_path, monkeypatch):
        """Can look up a type by its prefix."""
        (tmp_path / "pyproject.toml").write_text("""\
[project]
name = "test"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted"]
required_sections = []

[tool.doc.types.adr.transitions]
proposed = ["accepted"]
accepted = []

[tool.doc.types.adr.actions]
accept = "accepted"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = []

[tool.doc.types.prd.transitions]
draft = ["approved"]
approved = []

[tool.doc.types.prd.actions]
approve = "approved"
""")
        monkeypatch.chdir(tmp_path)
        assert find_doc_type("ADR-0001").name == "adr"
        assert find_doc_type("PRD-001").name == "prd"
