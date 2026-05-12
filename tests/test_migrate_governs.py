"""SPEC-011 tests — `decree migrate governs` LLM-assisted backfill.

No live LLM API calls. All tests mock `litellm.completion` via
`unittest.mock.patch`. Mock returns a `SimpleNamespace` shaped like the
litellm response object (`.choices[0].message.content`).
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frontmatter
import pytest


# ─── corpus helpers ───────────────────────────────────────────────────────


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


def _spec(root: Path, name: str, *, governs: list[str] | None = None) -> Path:
    """Write a SPEC; if `governs` is None, omit the field entirely."""
    gov_line = ""
    if governs is not None:
        gov_line = "governs:\n" + "".join(f"- {p}\n" for p in governs)
    path = root / "decree" / "spec" / f"{name}.md"
    path.write_text(
        f"""---
status: draft
date: 2026-05-10
{gov_line}---

# SPEC-{name[:3]} title

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
    # Pre-create some target files so we have something to mark "verified".
    (tmp_path / "src" / "decree").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "decree" / "foo.py").write_text("# stub\n")
    (tmp_path / "src" / "decree" / "bar.py").write_text("# stub\n")
    yield tmp_path
    get_project_root.cache_clear()
    load_doc_types.cache_clear()


def _llm_response(payload: dict | str) -> SimpleNamespace:
    """Shape a fake litellm response. Accepts dict (will JSON-dump) or str."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _load_docs(root: Path) -> list:
    """Load all docs at root (mirroring the CLI's loading path)."""
    from decree.config import get_project_root, load_doc_types
    from decree.parser import load_all_types

    cwd = Path.cwd()
    import os

    os.chdir(root)
    try:
        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        return load_all_types(strict=False)
    finally:
        os.chdir(cwd)


# ─── suggest_governs (library API) ────────────────────────────────────────


class TestSuggestGovernsLibrary:
    def test_clean_parse(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        fake = _llm_response(
            {
                "governs": ["src/decree/foo.py", "src/decree/bar.py"],
                "confidence": "high",
                "rationale": "Both files are listed under Files touched.",
            }
        )
        with patch("litellm.completion", return_value=fake) as m:
            results = suggest_governs(docs, "claude-3-5-sonnet-latest", corpus)
        assert m.call_count == 1
        assert len(results) == 1
        r = results[0]
        assert r.doc_id == "SPEC-001"
        assert r.proposed_governs == ("src/decree/foo.py", "src/decree/bar.py")
        assert r.confidence == "high"
        assert r.verified_paths == ("src/decree/foo.py", "src/decree/bar.py")
        assert r.unverified_paths == ()
        assert r.error is None

    def test_invalid_paths_dropped(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        fake = _llm_response(
            {
                "governs": [
                    "/abs/path.py",  # absolute → drop
                    "../escapes.py",  # contains .. → drop
                    "",  # empty → drop
                    42,  # not a string → drop
                    "src/decree/foo.py",  # keep
                ],
                "confidence": "medium",
                "rationale": "",
            }
        )
        with patch("litellm.completion", return_value=fake):
            results = suggest_governs(docs, "x", corpus)
        assert results[0].proposed_governs == ("src/decree/foo.py",)

    def test_missing_path_unverified(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        fake = _llm_response(
            {
                "governs": ["src/decree/foo.py", "src/decree/does_not_exist.py"],
                "confidence": "low",
                "rationale": "guessing on the second one",
            }
        )
        with patch("litellm.completion", return_value=fake):
            results = suggest_governs(docs, "x", corpus)
        r = results[0]
        assert r.verified_paths == ("src/decree/foo.py",)
        assert r.unverified_paths == ("src/decree/does_not_exist.py",)
        # Both are still in the proposed list, in original order.
        assert r.proposed_governs == (
            "src/decree/foo.py",
            "src/decree/does_not_exist.py",
        )

    def test_empty_proposal(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        fake = _llm_response({"governs": [], "confidence": "low", "rationale": "nothing"})
        with patch("litellm.completion", return_value=fake):
            results = suggest_governs(docs, "x", corpus)
        assert results[0].proposed_governs == ()
        assert results[0].error is None

    def test_llm_error_isolated(self, corpus: Path):
        _spec(corpus, "001-foo")
        _spec(corpus, "002-bar")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        good = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        side_effect = [RuntimeError("simulated 500"), good]
        with patch("litellm.completion", side_effect=side_effect):
            results = suggest_governs(docs, "x", corpus)
        errs = [r for r in results if r.error]
        oks = [r for r in results if not r.error]
        assert len(errs) == 1
        assert len(oks) == 1
        assert "simulated 500" in errs[0].error
        # The good doc still produced a valid suggestion.
        assert oks[0].proposed_governs == ("src/decree/foo.py",)

    def test_skip_existing_governs(self, corpus: Path):
        _spec(corpus, "001-foo", governs=["src/decree/foo.py"])
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        with patch("litellm.completion") as m:
            results = suggest_governs(docs, "x", corpus)
        # No LLM call for docs that already have governs.
        assert m.call_count == 0
        assert results[0].current_governs == ("src/decree/foo.py",)
        assert results[0].proposed_governs == ()
        assert "already has governs" in results[0].rationale

    def test_strips_markdown_code_fences(self, corpus: Path):
        """Some providers return ```json ... ``` even with response_format set."""
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs

        docs = _load_docs(corpus)
        fenced = (
            '```json\n{"governs": ["src/decree/foo.py"], '
            '"confidence": "high", "rationale": "ok"}\n```'
        )
        fake = _llm_response(fenced)
        with patch("litellm.completion", return_value=fake):
            results = suggest_governs(docs, "x", corpus)
        assert results[0].proposed_governs == ("src/decree/foo.py",)


# ─── apply_governs (library API) ──────────────────────────────────────────


class TestApplyGoverns:
    def test_writes_frontmatter(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import apply_governs, suggest_governs

        docs = _load_docs(corpus)
        fake = _llm_response(
            {
                "governs": ["src/decree/foo.py", "src/decree/bar.py"],
                "confidence": "high",
                "rationale": "ok",
            }
        )
        with patch("litellm.completion", return_value=fake):
            suggestions = suggest_governs(docs, "x", corpus)

        results = apply_governs(suggestions, corpus, dry_run=False)
        assert results[0].wrote is True
        # Round-trip parse confirms the field landed.
        doc_path = corpus / "decree" / "spec" / "001-foo.md"
        loaded = frontmatter.loads(doc_path.read_text())
        assert loaded["governs"] == ["src/decree/foo.py", "src/decree/bar.py"]
        # Body preserved.
        assert "## Overview" in loaded.content

    def test_dry_run_does_not_write(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import apply_governs, suggest_governs

        docs = _load_docs(corpus)
        original_text = (
            corpus / "decree" / "spec" / "001-foo.md"
        ).read_text()
        fake = _llm_response(
            {
                "governs": ["src/decree/foo.py"],
                "confidence": "high",
                "rationale": "ok",
            }
        )
        with patch("litellm.completion", return_value=fake):
            suggestions = suggest_governs(docs, "x", corpus)
        results = apply_governs(suggestions, corpus, dry_run=True)
        assert results[0].wrote is False
        assert results[0].skipped_reason == "dry-run"
        assert (
            corpus / "decree" / "spec" / "001-foo.md"
        ).read_text() == original_text

    def test_skips_when_proposed_empty(self, corpus: Path):
        _spec(corpus, "001-foo", governs=["src/decree/foo.py"])
        from decree.commands.migrate import apply_governs, suggest_governs

        docs = _load_docs(corpus)
        with patch("litellm.completion"):
            suggestions = suggest_governs(docs, "x", corpus)
        results = apply_governs(suggestions, corpus, dry_run=False)
        assert results[0].wrote is False
        assert "already has governs" in (results[0].skipped_reason or "")


# ─── resolve_model ────────────────────────────────────────────────────────


class TestResolveModel:
    def test_args_wins(self, monkeypatch):
        monkeypatch.setenv("DECREE_LLM_MODEL", "env-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        from decree.commands.migrate import resolve_model

        ns = argparse.Namespace(model="explicit-model")
        assert resolve_model(ns) == "explicit-model"

    def test_env_wins_over_default(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.setenv("DECREE_LLM_MODEL", "env-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        from decree.commands.migrate import resolve_model

        ns = argparse.Namespace(model=None)
        assert resolve_model(ns) == "env-model"

    def test_anthropic_default(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        from decree.commands.migrate import resolve_model

        ns = argparse.Namespace(model=None)
        assert resolve_model(ns) == "claude-3-5-sonnet-latest"

    def test_openai_default(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        from decree.commands.migrate import resolve_model

        ns = argparse.Namespace(model=None)
        assert resolve_model(ns) == "gpt-4o-mini"

    def test_no_key_exits(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from decree.commands.migrate import resolve_model

        ns = argparse.Namespace(model=None)
        with pytest.raises(SystemExit):
            resolve_model(ns)


# ─── suggest_governs_run (CLI handler) ────────────────────────────────────


def _args(corpus: Path, **overrides) -> argparse.Namespace:
    base = {
        "project": str(corpus),
        "suggest": True,
        "apply": False,
        "model": "fake-model",
        "dry_run": False,
        "only": None,
        "yes": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestSuggestGovernsRun:
    def test_only_filter(self, corpus: Path, capsys):
        _spec(corpus, "001-foo")
        _spec(corpus, "002-bar")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        with patch("litellm.completion", return_value=fake) as m:
            rc = suggest_governs_run(_args(corpus, only=["SPEC-001"]))
        assert rc == 0
        # Only one LLM call — for SPEC-001.
        assert m.call_count == 1

    def test_json_output_schema(self, corpus: Path, capsys):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(_args(corpus, json=True))
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 0
        assert payload["model"] == "fake-model"
        assert payload["apply"] is None
        assert len(payload["suggestions"]) == 1
        s = payload["suggestions"][0]
        assert set(s.keys()) >= {
            "doc_id",
            "doc_path",
            "current_governs",
            "proposed_governs",
            "confidence",
            "rationale",
            "verified_paths",
            "unverified_paths",
            "error",
        }
        assert s["proposed_governs"] == ["src/decree/foo.py"]

    def test_apply_with_yes_writes(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(
                _args(corpus, apply=True, yes=True, json=True)
            )
        assert rc == 0
        loaded = frontmatter.loads(
            (corpus / "decree" / "spec" / "001-foo.md").read_text()
        )
        assert loaded["governs"] == ["src/decree/foo.py"]

    def test_apply_dry_run_no_write(self, corpus: Path):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        original = (corpus / "decree" / "spec" / "001-foo.md").read_text()
        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(
                _args(corpus, apply=True, yes=True, dry_run=True, json=True)
            )
        assert rc == 0
        assert (
            corpus / "decree" / "spec" / "001-foo.md"
        ).read_text() == original

    def test_apply_interactive_yes(self, corpus: Path, monkeypatch):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        # Make stdin look like a TTY and inject 'y'.
        monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "y")
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(_args(corpus, apply=True))
        assert rc == 0
        loaded = frontmatter.loads(
            (corpus / "decree" / "spec" / "001-foo.md").read_text()
        )
        assert loaded["governs"] == ["src/decree/foo.py"]

    def test_apply_interactive_no(self, corpus: Path, monkeypatch):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        original = (corpus / "decree" / "spec" / "001-foo.md").read_text()
        monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(_args(corpus, apply=True))
        assert rc == 0
        assert (
            corpus / "decree" / "spec" / "001-foo.md"
        ).read_text() == original

    def test_apply_non_tty_without_yes_refused(self, corpus: Path, monkeypatch):
        _spec(corpus, "001-foo")
        from decree.commands.migrate import suggest_governs_run

        fake = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        original = (corpus / "decree" / "spec" / "001-foo.md").read_text()
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        with patch("litellm.completion", return_value=fake):
            rc = suggest_governs_run(_args(corpus, apply=True))
        # Confirmation refused → file untouched. Exit 0 (no LLM/apply errors).
        assert rc == 0
        assert (
            corpus / "decree" / "spec" / "001-foo.md"
        ).read_text() == original

    def test_partial_failure_returns_one(self, corpus: Path):
        _spec(corpus, "001-foo")
        _spec(corpus, "002-bar")
        from decree.commands.migrate import suggest_governs_run

        good = _llm_response(
            {"governs": ["src/decree/foo.py"], "confidence": "high", "rationale": "ok"}
        )
        with patch(
            "litellm.completion",
            side_effect=[RuntimeError("boom"), good],
        ):
            rc = suggest_governs_run(_args(corpus, json=True))
        assert rc == 1

    def test_no_docs_returns_two(self, corpus: Path):
        from decree.commands.migrate import suggest_governs_run

        with patch("litellm.completion"):
            rc = suggest_governs_run(_args(corpus, only=["DOES-NOT-EXIST"]))
        assert rc == 2


# ─── end-to-end integration ───────────────────────────────────────────────


class TestIntegration:
    def test_full_corpus_suggest_apply_yes(self, corpus: Path):
        _spec(corpus, "001-foo")
        _spec(corpus, "002-bar")
        _spec(corpus, "003-baz", governs=["src/decree/foo.py"])
        from decree.commands.migrate import suggest_governs_run

        good = _llm_response(
            {
                "governs": ["src/decree/foo.py", "src/decree/bar.py"],
                "confidence": "high",
                "rationale": "Both listed under Files touched.",
            }
        )
        # Two calls expected (SPEC-001 and SPEC-002; SPEC-003 already has governs).
        with patch(
            "litellm.completion", side_effect=[good, good]
        ) as m:
            rc = suggest_governs_run(
                _args(corpus, apply=True, yes=True, json=True)
            )
        assert rc == 0
        assert m.call_count == 2
        # SPEC-001 and SPEC-002 both written.
        for name in ("001-foo", "002-bar"):
            loaded = frontmatter.loads(
                (corpus / "decree" / "spec" / f"{name}.md").read_text()
            )
            assert loaded["governs"] == [
                "src/decree/foo.py",
                "src/decree/bar.py",
            ]
        # SPEC-003 untouched (single-element).
        loaded3 = frontmatter.loads(
            (corpus / "decree" / "spec" / "003-baz.md").read_text()
        )
        assert loaded3["governs"] == ["src/decree/foo.py"]
