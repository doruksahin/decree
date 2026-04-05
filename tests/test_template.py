"""Tests for decree.template — pure template rendering."""
from decree.template import render_template


def test_replaces_placeholders():
    raw = "---\nstatus: proposed\ndate: __DATE__\n---\n\n# ADR-__NUMBER__ __TITLE__\n"
    result = render_template(raw, number=1, title="Use PuLP", slug="use-pulp", today="2026-04-02")
    assert "date: 2026-04-02" in result
    assert "# ADR-0001 Use PuLP" in result


def test_appends_project_sections(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    raw = "---\nstatus: proposed\ndate: __DATE__\n---\n\n# ADR-__NUMBER__ __TITLE__\n"
    result = render_template(raw, number=1, title="Test", slug="test", today="2026-04-02")
    assert "## Consequences" in result
    assert "## Affected Files" in result
    assert "## Validation Needed" in result


def test_no_project_sections_without_config(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "bare"\n')
    monkeypatch.chdir(tmp_path)
    raw = "# ADR-__NUMBER__ __TITLE__\n"
    result = render_template(raw, number=1, title="Test", slug="test", today="2026-04-02")
    assert "## Consequences" not in result
