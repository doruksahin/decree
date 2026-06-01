"""Tests for provider-free `decree migrate governs` analyze/apply flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import frontmatter
import pytest

from decree.commands.migrate import GOVERNS_SUGGESTIONS_SCHEMA


def _three_type_toml() -> str:
    return """\
[types.prd]
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

[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

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


def _write_corpus(root: Path) -> None:
    (root / "decree.toml").write_text(_three_type_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True, exist_ok=True)


def _doc_id(prefix: str, name: str) -> str:
    return f"{prefix}-{int(name.split('-', 1)[0]):026d}"


def _filename(prefix: str, name: str) -> str:
    return f"{_doc_id(prefix, name).lower()}-{name.split('-', 1)[1]}.md"


def _spec(root: Path, name: str, *, governs: list[str] | None = None) -> Path:
    gov_line = ""
    if governs is not None:
        gov_line = "governs:\n" + "".join(f"- {p}\n" for p in governs)
    doc_id = _doc_id("SPEC", name)
    path = root / "decree" / "spec" / _filename("SPEC", name)
    path.write_text(
        f"""---
id: {doc_id}
status: draft
date: 2026-05-10
{gov_line}---

# {doc_id} title

## Overview

Some technical design here.

### Files touched

- src/decree/foo.py
- src/decree/bar.py

## v1 Acceptance Criteria

- [ ] something
"""
    )
    return path


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch):
    _write_corpus(tmp_path)
    monkeypatch.chdir(tmp_path)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    (tmp_path / "src" / "decree").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "decree" / "foo.py").write_text("# stub\n")
    (tmp_path / "src" / "decree" / "bar.py").write_text("# stub\n")
    yield tmp_path
    get_project_root.cache_clear()
    load_doc_types.cache_clear()


def _load_docs(root: Path) -> list:
    from decree.config import get_project_root, load_doc_types
    from decree.parser import load_all_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return load_all_types()


def _suggestions_file(root: Path, *items: dict) -> Path:
    path = root / "suggestions.json"
    path.write_text(json.dumps({"schema": GOVERNS_SUGGESTIONS_SCHEMA, "suggestions": list(items)}))
    return path


def _args(corpus: Path, **overrides) -> argparse.Namespace:
    base = {
        "project": str(corpus),
        "analyze": False,
        "apply_suggestions": None,
        "apply": False,
        "dry_run": False,
        "only": None,
        "yes": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestAnalyzeGoverns:
    def test_analysis_contract_includes_candidate_paths(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import analyze_governs

        payload = analyze_governs(_load_docs(corpus), corpus)
        assert payload["schema"] == "decree.governs-analysis.v1"
        doc = payload["documents"][0]
        assert doc["document_id"] == "SPEC-00000000000000000000000001"
        assert doc["needs_governs"] is True
        assert doc["candidate_paths"] == ["src/decree/foo.py", "src/decree/bar.py"]
        assert "body_excerpt" in doc

    def test_analysis_marks_existing_governs(self, corpus: Path):
        _spec(corpus, "001-foo", governs=["src/decree/foo.py"])
        from decree.commands.migrate import analyze_governs

        doc = analyze_governs(_load_docs(corpus), corpus)["documents"][0]
        assert doc["needs_governs"] is False
        assert doc["existing_governs"] == ["src/decree/foo.py"]


class TestLoadGovernsSuggestions:
    def test_valid_suggestions_are_validated(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import load_governs_suggestions

        path = _suggestions_file(
            corpus,
            {
                "document_id": "SPEC-00000000000000000000000001",
                "governs": ["src/decree/foo.py"],
                "confidence": "high",
                "rationale": "listed in Files touched",
            },
        )
        suggestions = load_governs_suggestions(path, _load_docs(corpus), corpus)
        assert suggestions[0].proposed_governs == ("src/decree/foo.py",)
        assert suggestions[0].verified_paths == ("src/decree/foo.py",)
        assert suggestions[0].error is None

    def test_invalid_paths_are_errors_not_silent_drops(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import load_governs_suggestions

        path = _suggestions_file(
            corpus,
            {
                "document_id": "SPEC-00000000000000000000000001",
                "governs": ["/abs.py", "../escape.py", "src/decree/missing.py", "src/decree/foo.py"],
            },
        )
        suggestion = load_governs_suggestions(path, _load_docs(corpus), corpus)[0]
        assert suggestion.proposed_governs == ()
        assert suggestion.error is not None
        assert "invalid governs entry" in suggestion.error
        assert "does not exist" in suggestion.error

    def test_schema_must_match(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import load_governs_suggestions

        path = corpus / "bad.json"
        path.write_text(json.dumps({"schema": "wrong", "suggestions": []}))
        with pytest.raises(ValueError, match="suggestions schema"):
            load_governs_suggestions(path, _load_docs(corpus), corpus)


class TestApplyGoverns:
    def test_writes_frontmatter_from_valid_external_suggestions(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import apply_governs, load_governs_suggestions

        path = _suggestions_file(
            corpus,
            {"document_id": "SPEC-00000000000000000000000001", "governs": ["src/decree/foo.py"]},
        )
        suggestions = load_governs_suggestions(path, _load_docs(corpus), corpus)
        result = apply_governs(suggestions, corpus, dry_run=False)[0]
        assert result.wrote is True
        doc_path = corpus / "decree" / "spec" / "spec-00000000000000000000000001-foo.md"
        assert frontmatter.loads(doc_path.read_text())["governs"] == ["src/decree/foo.py"]

    def test_dry_run_does_not_write(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import apply_governs, load_governs_suggestions

        doc_path = corpus / "decree" / "spec" / "spec-00000000000000000000000001-foo.md"
        original = doc_path.read_text()
        path = _suggestions_file(
            corpus,
            {"document_id": "SPEC-00000000000000000000000001", "governs": ["src/decree/foo.py"]},
        )
        suggestions = load_governs_suggestions(path, _load_docs(corpus), corpus)
        result = apply_governs(suggestions, corpus, dry_run=True)[0]
        assert result.skipped_reason == "dry-run"
        assert doc_path.read_text() == original


class TestGovernsRun:
    def test_analyze_json_output(self, corpus: Path, capsys):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import governs_run

        rc = governs_run(_args(corpus, analyze=True, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["schema"] == "decree.governs-analysis.v1"
        assert payload["documents"][0]["candidate_paths"] == ["src/decree/foo.py", "src/decree/bar.py"]

    def test_apply_suggestions_json_writes_with_yes(self, corpus: Path, capsys):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import governs_run

        path = _suggestions_file(
            corpus,
            {"document_id": "SPEC-00000000000000000000000001", "governs": ["src/decree/foo.py"]},
        )
        rc = governs_run(_args(corpus, apply_suggestions=str(path), apply=True, yes=True, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["schema"] == "decree.governs-apply.v1"
        assert payload["apply"][0]["wrote"] is True

    def test_invalid_suggestion_returns_one_and_does_not_write(self, corpus: Path, capsys):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import governs_run

        path = _suggestions_file(
            corpus,
            {"document_id": "SPEC-00000000000000000000000001", "governs": ["src/decree/missing.py"]},
        )
        rc = governs_run(_args(corpus, apply_suggestions=str(path), apply=True, yes=True, json=True))
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["apply"] is None
        doc_path = corpus / "decree" / "spec" / "spec-00000000000000000000000001-foo.md"
        assert "governs" not in frontmatter.loads(doc_path.read_text())

    def test_no_docs_returns_two(self, corpus: Path):
        from decree.commands.migrate import governs_run

        rc = governs_run(_args(corpus, analyze=True, only=["DOES-NOT-EXIST"]))
        assert rc == 2
