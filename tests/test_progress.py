"""Tests for decree progress command."""

import io
import sys

from decree.commands.progress import _bar, _count_checkboxes, _pct, run


class TestCountCheckboxes:
    def test_empty(self):
        assert _count_checkboxes("") == (0, 0)

    def test_no_checkboxes(self):
        assert _count_checkboxes("# Title\n\nSome text.") == (0, 0)

    def test_unchecked(self):
        assert _count_checkboxes("- [ ] Todo item") == (0, 1)

    def test_checked_lowercase(self):
        assert _count_checkboxes("- [x] Done item") == (1, 1)

    def test_checked_uppercase(self):
        assert _count_checkboxes("- [X] Done item") == (1, 1)

    def test_mixed(self):
        body = "- [x] Done\n- [ ] Todo\n- [X] Also done\n- [ ] Another"
        assert _count_checkboxes(body) == (2, 4)

    def test_asterisk_bullets(self):
        body = "* [x] Done\n* [ ] Todo"
        assert _count_checkboxes(body) == (1, 2)

    def test_indented(self):
        body = "  - [x] Indented done\n  - [ ] Indented todo"
        assert _count_checkboxes(body) == (1, 2)

    def test_ignores_non_checkbox_brackets(self):
        body = "Some [text] in brackets\n- [ ] Real checkbox"
        assert _count_checkboxes(body) == (0, 1)

    def test_multiline_realistic(self):
        body = """# Spec

## Verification

- [x] Unit tests pass
- [x] Integration tests pass
- [ ] Performance benchmark
- [ ] Security audit

## Other

Some text here.
- [x] Another checked item
"""
        assert _count_checkboxes(body) == (3, 5)


class TestBar:
    def test_empty(self):
        assert _bar(0, 0) == "░" * 10

    def test_full(self):
        assert _bar(5, 5) == "█" * 10

    def test_half(self):
        assert _bar(5, 10) == "█████░░░░░"

    def test_custom_width(self):
        assert _bar(1, 2, width=4) == "██░░"


class TestPct:
    def test_zero(self):
        assert _pct(0, 0) == "  —"

    def test_hundred(self):
        assert _pct(5, 5) == "100%"

    def test_fifty(self):
        assert _pct(1, 2) == " 50%"


class TestProgressRun:
    def test_no_documents(self, tmp_path, monkeypatch):
        decree_toml = tmp_path / "decree.toml"
        decree_toml.write_text("""\
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
""")
        monkeypatch.chdir(tmp_path)
        result = run(None)
        assert result == 0

    def test_documents_with_checkboxes(self, tmp_path, monkeypatch):
        decree_toml = tmp_path / "decree.toml"
        decree_toml.write_text("""\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
warn_on_reference = []
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[types.prd.transitions]
draft = ["approved"]
approved = []

[types.prd.actions]
approve = "approved"
""")
        prd_dir = tmp_path / "decree" / "prd"
        prd_dir.mkdir(parents=True)
        (prd_dir / "001-test.md").write_text(
            "---\nstatus: draft\ndate: 2026-01-01\n---\n"
            "# PRD-001 Test\n\n## Problem Statement\n\nP.\n\n"
            "## Requirements\n\n- [x] Done\n- [ ] Todo\n\n"
            "## Success Criteria\n\n- [ ] Criterion\n"
        )
        monkeypatch.chdir(tmp_path)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            result = run(None)
        finally:
            sys.stdout = old_stdout

        assert result == 0
        output = captured.getvalue()
        assert "PRD-001" in output
        assert "(1/3)" in output
