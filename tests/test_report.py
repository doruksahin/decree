"""Tests for completion-report generation."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from decree.commands.report import (
    DEFAULT_DEFERRED_SECTION_PATTERNS,
    _parse_checkboxes_by_section,
    _section_is_deferred,
    generate_report,
    is_terminal_success,
    load_report_config,
    regenerate_reports,
    regenerate_run,
    resolve_report_path,
)

# ── Section classification ──────────────────────────────────────


class TestSectionIsDeferred:
    def test_exact_match(self):
        assert _section_is_deferred("Deferred", DEFAULT_DEFERRED_SECTION_PATTERNS)

    def test_case_insensitive(self):
        assert _section_is_deferred("DEFERRED", DEFAULT_DEFERRED_SECTION_PATTERNS)

    def test_substring_match(self):
        assert _section_is_deferred("What this does NOT do (deferred to v2)", DEFAULT_DEFERRED_SECTION_PATTERNS)

    def test_primary_section_not_deferred(self):
        assert not _section_is_deferred("Acceptance Criteria", DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert not _section_is_deferred("Overview", DEFAULT_DEFERRED_SECTION_PATTERNS)

    def test_custom_patterns(self):
        assert _section_is_deferred("Backlog", ("Backlog",))
        assert not _section_is_deferred("Backlog", ("Future",))


# ── Section parsing ───────────────────────────────────────────────


class TestParseCheckboxesBySection:
    def test_simple_primary_only(self):
        body = """# Title

## Acceptance Criteria

- [x] Done
- [ ] Todo
"""
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 2 and p.primary_done == 1
        assert p.deferred_total == 0

    def test_deferred_section_separated(self):
        body = """# Title

## Acceptance Criteria

- [x] Done
- [ ] Todo

## What this does NOT do (deferred to v2)

- [ ] Some future thing
"""
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 2 and p.primary_done == 1
        assert p.deferred_total == 1 and p.deferred_done == 0

    def test_multiple_primary_sections(self):
        body = """# Title

## Section A

- [x] A1
- [ ] A2

## Section B

- [x] B1
- [x] B2
"""
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 4 and p.primary_done == 3
        assert len(p.primary) == 2

    def test_nested_deferred_subsection(self):
        body = """# Title

## Deferred

### Sub-deferred

- [ ] Future thing

### Another sub

- [ ] Also future
"""
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 0
        assert p.deferred_total == 2

    def test_returns_to_primary_after_deferred(self):
        """A primary section after a deferred section is correctly classified as primary."""
        body = """# Title

## Primary 1

- [x] Done

## Deferred

- [ ] Future

## Primary 2

- [x] Also done
"""
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 2 and p.primary_done == 2
        assert p.deferred_total == 1

    def test_no_checkboxes(self):
        body = "# Title\n\n## Section\n\nJust prose."
        p = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert p.primary_total == 0
        assert p.deferred_total == 0


# ── Config loading ───────────────────────────────────────────────


class TestLoadReportConfig:
    def test_defaults_when_no_config(self, tmp_path: Path):
        (tmp_path / "decree.toml").write_text(
            """[types.spec]
prefix = 'SPEC'
digits = 3
dir = 'decree/spec'
initial_status = 'draft'
statuses = ['draft']
[types.spec.transitions]
draft = []
[types.spec.actions]
"""
        )
        cfg = load_report_config(tmp_path, "spec")
        assert cfg.enabled is True
        assert cfg.require_for_terminal_status is False

    def test_overrides(self, tmp_path: Path):
        (tmp_path / "decree.toml").write_text(
            """[types.spec]
prefix = 'SPEC'
digits = 3
dir = 'decree/spec'
initial_status = 'draft'
statuses = ['draft']
[types.spec.transitions]
draft = []
[types.spec.actions]

[types.spec.completion_report]
enabled = false
require_for_terminal_status = true
location = "reports/{id}.md"
deferred_sections = ["Backlog", "Notes"]
"""
        )
        cfg = load_report_config(tmp_path, "spec")
        assert cfg.enabled is False
        assert cfg.require_for_terminal_status is True
        assert cfg.location_template == "reports/{id}.md"
        assert cfg.deferred_section_patterns == ("Backlog", "Notes")


# ── End-to-end report generation ──────────────────────────────────


@pytest.fixture
def spec_corpus(tmp_path: Path) -> Path:
    """A small corpus with a SPEC-00000000000000000000000001 ready to be implemented."""
    (tmp_path / "decree.toml").write_text(
        """[types.prd]
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
    )
    (tmp_path / "decree" / "prd").mkdir(parents=True)
    (tmp_path / "decree" / "spec").mkdir(parents=True)
    (tmp_path / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-12
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

prose
"""
    )
    (tmp_path / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: approved
date: 2026-05-12
references: [PRD-00000000000000000000000001]
---

# SPEC-00000000000000000000000001 Test SPEC

## Overview

prose

## Acceptance Criteria

- [x] Primary 1
- [x] Primary 2

## What this does NOT do (deferred to v2)

- [ ] Future thing
"""
    )
    return tmp_path


class TestGenerateReport:
    def test_writes_report_file(self, monkeypatch, spec_corpus: Path):
        monkeypatch.chdir(spec_corpus)
        from decree.parser import find_by_id, load_all_types

        doc = find_by_id("SPEC-00000000000000000000000001")
        all_docs = load_all_types()
        report_path = generate_report(doc, spec_corpus, "implemented", all_docs=all_docs)
        assert report_path is not None
        assert report_path.exists()
        text = report_path.read_text()
        assert "SPEC-00000000000000000000000001 Completion Report" in text
        assert "primary (2/2)" in text
        assert "Deferred / Out of scope (0/1)" in text
        assert "PRD-00000000000000000000000001" in text  # chain reconstruction

    def test_disabled_skips_generation(self, monkeypatch, spec_corpus: Path):
        # Disable for the spec type
        toml = (spec_corpus / "decree.toml").read_text()
        toml += "\n[types.spec.completion_report]\nenabled = false\n"
        (spec_corpus / "decree.toml").write_text(toml)
        monkeypatch.chdir(spec_corpus)
        from decree.parser import find_by_id, load_all_types

        doc = find_by_id("SPEC-00000000000000000000000001")
        all_docs = load_all_types()
        result = generate_report(doc, spec_corpus, "implemented", all_docs=all_docs)
        assert result is None

    def test_custom_location(self, monkeypatch, spec_corpus: Path):
        toml = (spec_corpus / "decree.toml").read_text()
        toml += '\n[types.spec.completion_report]\nlocation = "reports/{id}.md"\n'
        (spec_corpus / "decree.toml").write_text(toml)
        monkeypatch.chdir(spec_corpus)
        from decree.parser import find_by_id, load_all_types

        doc = find_by_id("SPEC-00000000000000000000000001")
        all_docs = load_all_types()
        report_path = generate_report(doc, spec_corpus, "implemented", all_docs=all_docs)
        assert report_path == spec_corpus / "reports" / "SPEC-00000000000000000000000001.md"
        assert report_path.exists()

    def test_legacy_number_str_location_is_error(self, monkeypatch, spec_corpus: Path):
        monkeypatch.chdir(spec_corpus)
        from decree.parser import find_by_id

        doc = find_by_id("SPEC-00000000000000000000000001")

        with pytest.raises(ValueError, match="number_str"):
            resolve_report_path(doc, spec_corpus, "{dir}/reports/{number_str}.md")


class TestRegenerateReports:
    def test_regenerates_explicit_terminal_doc(self, monkeypatch, spec_corpus: Path):
        monkeypatch.chdir(spec_corpus)
        from decree.commands.status import run as status_run

        status_run(argparse.Namespace(doc_id="SPEC-00000000000000000000000001", action="implement", target_id=None))
        spec_path = spec_corpus / "decree" / "spec" / "spec-00000000000000000000000001-test.md"
        spec_path.write_text(spec_path.read_text().replace("- [x] Primary 2", "- [ ] Primary 2"))

        results = regenerate_reports(spec_corpus, doc_ids=("SPEC-00000000000000000000000001",))

        assert len(results) == 1
        assert results[0].action == "written"
        text = (spec_corpus / "decree" / "spec" / "reports" / "SPEC-00000000000000000000000001.md").read_text()
        assert "primary (1/2)" in text

    def test_existing_only_skips_missing_report(self, monkeypatch, spec_corpus: Path):
        monkeypatch.chdir(spec_corpus)
        spec_path = spec_corpus / "decree" / "spec" / "spec-00000000000000000000000001-test.md"
        spec_path.write_text(spec_path.read_text().replace("status: approved", "status: implemented"))

        results = regenerate_reports(spec_corpus, doc_ids=("SPEC-00000000000000000000000001",), existing_only=True)

        assert len(results) == 1
        assert results[0].action == "skipped"
        assert results[0].reason == "report does not already exist"
        assert not (spec_corpus / "decree" / "spec" / "reports" / "SPEC-00000000000000000000000001.md").exists()


class TestRegenerateRun:
    def test_requires_target(self, capsys):
        rc = regenerate_run(
            argparse.Namespace(
                doc_ids=[],
                all=False,
                existing_only=False,
                dry_run=False,
                project=None,
            )
        )

        assert rc == 1
        assert "pass at least one DOC_ID" in capsys.readouterr().err

    def test_regenerates_via_cli_handler(self, monkeypatch, spec_corpus: Path):
        monkeypatch.chdir(spec_corpus)
        from decree.commands.status import run as status_run

        status_run(argparse.Namespace(doc_id="SPEC-00000000000000000000000001", action="implement", target_id=None))

        rc = regenerate_run(
            argparse.Namespace(
                doc_ids=["SPEC-00000000000000000000000001"],
                all=False,
                existing_only=False,
                dry_run=False,
                project=str(spec_corpus),
            )
        )

        assert rc == 0


# ── Status transition triggers report ──────────────────────────────


class TestStatusTransitionTriggersReport:
    def test_implement_transition_writes_report(self, monkeypatch, spec_corpus: Path, capsys):
        monkeypatch.chdir(spec_corpus)
        from decree.commands.status import run as status_run

        args = argparse.Namespace(doc_id="SPEC-00000000000000000000000001", action="implement", target_id=None)
        rc = status_run(args)
        assert rc == 0
        # Report file written to the sibling reports/ subdirectory by default
        assert (spec_corpus / "decree" / "spec" / "reports" / "SPEC-00000000000000000000000001.md").exists()


# ── Lint validation ──────────────────────────────────────────────


class TestLintRequiresReport:
    def test_lint_fails_when_implemented_has_no_report(self, monkeypatch, spec_corpus: Path):
        # Mark SPEC-00000000000000000000000001 as already implemented (without going through `decree status`
        # so no report is written), and enable require_for_terminal_status.
        spec_path = spec_corpus / "decree" / "spec" / "spec-00000000000000000000000001-test.md"
        text = spec_path.read_text()
        spec_path.write_text(text.replace("status: approved", "status: implemented"))
        toml = (spec_corpus / "decree.toml").read_text()
        toml += "\n[types.spec.completion_report]\nrequire_for_terminal_status = true\n"
        (spec_corpus / "decree.toml").write_text(toml)
        monkeypatch.chdir(spec_corpus)
        from decree.commands.lint import run as lint_run

        rc = lint_run(argparse.Namespace(check_attachments=False))
        assert rc == 1

    def test_lint_passes_with_report_present(self, monkeypatch, spec_corpus: Path):
        # Generate the report first (via implement transition), then lint
        monkeypatch.chdir(spec_corpus)
        from decree.commands.status import run as status_run

        status_run(argparse.Namespace(doc_id="SPEC-00000000000000000000000001", action="implement", target_id=None))

        toml = (spec_corpus / "decree.toml").read_text()
        toml += "\n[types.spec.completion_report]\nrequire_for_terminal_status = true\n"
        (spec_corpus / "decree.toml").write_text(toml)

        from decree.commands.lint import run as lint_run

        rc = lint_run(argparse.Namespace(check_attachments=False))
        assert rc == 0


# ── Terminal-status detection ─────────────────────────────────────


class TestIsTerminalSuccess:
    def _spec_type(self):
        from decree.doctypes import DocType

        return DocType(
            name="spec",
            prefix="SPEC",
            legacy_digits=3,
            dir="decree/spec",
            initial_status="draft",
            statuses=("draft", "approved", "implemented"),
            transitions={"draft": ("approved",), "approved": ("implemented",), "implemented": ()},
            actions={"approve": "approved", "implement": "implemented"},
        )

    def test_spec_implemented_is_terminal_success(self):
        assert is_terminal_success(self._spec_type(), "implemented")

    def test_spec_approved_is_not_terminal(self):
        assert not is_terminal_success(self._spec_type(), "approved")

    def test_custom_type_inferred_from_transitions(self):
        from decree.doctypes import DocType

        custom = DocType(
            name="ddr",
            prefix="DDR",
            legacy_digits=3,
            dir="decree/ddr",
            initial_status="proposed",
            statuses=("proposed", "accepted", "rejected"),
            transitions={"proposed": ("accepted", "rejected"), "accepted": (), "rejected": ()},
            actions={"accept": "accepted", "reject": "rejected"},
            warn_on_reference=("rejected",),
        )
        assert is_terminal_success(custom, "accepted")
        assert not is_terminal_success(custom, "rejected")  # dead, not terminal-success
