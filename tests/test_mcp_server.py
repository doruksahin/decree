"""SPEC-007 — MCP server tests.

Direct function tests cover the tool happy-paths and error-shaped responses.
A protocol-level smoke test exercises FastMCP's `tools/list` + `tools/call`
plumbing in-process via the SDK's async API (no subprocess required).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from decree.commands import mcp_server
from decree.commands.mcp_server import mcp
from decree.index_db import IndexDB, default_db_path


# ── Corpus helpers ──────────────────────────────────────────


def _decree_toml() -> str:
    """Minimal three-type decree.toml. Mirrors tests/test_queries.py."""
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
[types.adr.status_field_requirements]
superseded = ["superseded-by"]

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


def _write_basic_corpus(root: Path) -> None:
    """A PRD + ADR + SPEC where SPEC-001 governs `src/foo.py`."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "001-test.md").write_text(
        """---
status: approved
date: 2026-05-10
---

# PRD-001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "adr" / "0001-test.md").write_text(
        """---
status: accepted
date: 2026-05-11
references: [PRD-001]
---

# ADR-0001 Test ADR

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "001-test.md").write_text(
        """---
status: implemented
date: 2026-05-12
references: [PRD-001, ADR-0001]
governs:
  - src/foo.py
---

# SPEC-001 Test SPEC

## Overview

Prose.
"""
    )


def _rebuild_index(root: Path, monkeypatch) -> IndexDB:
    monkeypatch.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    db = IndexDB(default_db_path(root))
    db.rebuild(root)
    return db


@pytest.fixture
def project_with_index(tmp_path: Path, monkeypatch) -> Path:
    _write_basic_corpus(tmp_path)
    _rebuild_index(tmp_path, monkeypatch)
    mcp_server._set_project_root(tmp_path)
    yield tmp_path
    mcp_server._set_project_root(None)  # type: ignore[arg-type]


@pytest.fixture
def project_without_index(tmp_path: Path, monkeypatch) -> Path:
    _write_basic_corpus(tmp_path)
    monkeypatch.chdir(tmp_path)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    mcp_server._set_project_root(tmp_path)
    yield tmp_path
    mcp_server._set_project_root(None)  # type: ignore[arg-type]


# ── Direct tool-function tests ──────────────────────────────


class TestWhyTool:
    def test_exact_match(self, project_with_index: Path) -> None:
        result = mcp_server.why("src/foo.py")
        assert result["query"] == "src/foo.py"
        assert result["match_count"] == 1
        assert result["matches"][0]["decision_id"] == "SPEC-001"
        assert result["matches"][0]["match_kind"] == "exact"
        assert result["matches"][0]["type"] == "spec"
        assert result["matches"][0]["status"] == "implemented"
        assert "error" not in result

    def test_no_match_abstains(self, project_with_index: Path) -> None:
        result = mcp_server.why("src/nonexistent.py")
        assert result["match_count"] == 0
        assert result["matches"] == []
        assert "error" not in result

    def test_index_missing_returns_error_response(
        self, project_without_index: Path
    ) -> None:
        result = mcp_server.why("src/foo.py")
        assert result == {
            "error": "index not found",
            "hint": "Run `decree index rebuild` to build the index, then retry.",
        }


class TestRefsTool:
    def test_known_decision_returns_full_report(self, project_with_index: Path) -> None:
        result = mcp_server.refs("SPEC-001")
        assert result["decision_id"] == "SPEC-001"
        assert result["metadata"]["type"] == "spec"
        assert result["metadata"]["status"] == "implemented"
        assert "Test SPEC" in result["metadata"]["title"]
        # SPEC-001 references PRD-001 and ADR-0001
        forward_to_ids = {r["to_id"] for r in result["forward_refs"]}
        assert forward_to_ids == {"PRD-001", "ADR-0001"}
        # SPEC-001 governs src/foo.py
        govern_paths = {g["path"] for g in result["governs"]}
        assert "src/foo.py" in govern_paths
        # Sub-arrays exist with correct shapes
        assert isinstance(result["reverse_refs"], list)
        assert isinstance(result["supersedes_chain"], list)
        assert isinstance(result["commits"], list)

    def test_unknown_decision_returns_error_response(
        self, project_with_index: Path
    ) -> None:
        result = mcp_server.refs("SPEC-999")
        assert result == {
            "error": "unknown decision id",
            "decision_id": "SPEC-999",
        }

    def test_index_missing_returns_error_response(
        self, project_without_index: Path
    ) -> None:
        result = mcp_server.refs("SPEC-001")
        assert result == {
            "error": "index not found",
            "hint": "Run `decree index rebuild` to build the index, then retry.",
        }


# ── Tool registry ───────────────────────────────────────────


class TestToolRegistry:
    def test_exactly_two_tools_registered(self) -> None:
        tools = mcp._tool_manager.list_tools()
        names = sorted(t.name for t in tools)
        assert names == ["refs", "why"], (
            f"Expected exactly the v1 tool set; got {names}. "
            "SPEC-007 ships only `why` and `refs`."
        )

    def test_why_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["why"].description or ""
        # Each tool docstring must follow the 5-section structure
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc

    def test_refs_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["refs"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc

    def test_arg_schemas(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        why_schema = tools["why"].parameters
        assert why_schema["properties"]["path"]["type"] == "string"
        assert "path" in why_schema["required"]

        refs_schema = tools["refs"].parameters
        assert refs_schema["properties"]["decision_id"]["type"] == "string"
        assert "decision_id" in refs_schema["required"]


# ── Protocol-level smoke test (in-process FastMCP) ──────────


class TestProtocol:
    def test_tools_list_via_fastmcp(self) -> None:
        """Round-trip `list_tools` via the async FastMCP API."""

        async def go():
            return await mcp.list_tools()

        tools = asyncio.run(go())
        names = sorted(t.name for t in tools)
        assert names == ["refs", "why"]

        why_tool = next(t for t in tools if t.name == "why")
        # MCP protocol exposes inputSchema (a JSON Schema dict)
        assert why_tool.inputSchema["properties"]["path"]["type"] == "string"
        assert "path" in why_tool.inputSchema["required"]

        refs_tool = next(t for t in tools if t.name == "refs")
        assert refs_tool.inputSchema["properties"]["decision_id"]["type"] == "string"
        assert "decision_id" in refs_tool.inputSchema["required"]

    def test_tools_call_why_via_fastmcp(self, project_with_index: Path) -> None:
        """Round-trip `call_tool('why', ...)` via the async FastMCP API.

        FastMCP's `call_tool` returns a list of ContentBlock items with the
        tool's structured response serialized as a JSON text block. Parsing
        that JSON is how an MCP client actually consumes a tool response.
        """

        async def go():
            return await mcp.call_tool("why", {"path": "src/foo.py"})

        result = asyncio.run(go())
        assert isinstance(result, list)
        # First content block holds the JSON payload
        text_blocks = [b for b in result if getattr(b, "type", None) == "text"]
        assert text_blocks, f"Expected a text content block, got {result!r}"
        payload = json.loads(text_blocks[0].text)
        assert payload["query"] == "src/foo.py"
        assert payload["match_count"] == 1
        assert payload["matches"][0]["decision_id"] == "SPEC-001"

    def test_tools_call_refs_via_fastmcp(self, project_with_index: Path) -> None:
        async def go():
            return await mcp.call_tool("refs", {"decision_id": "SPEC-001"})

        result = asyncio.run(go())
        text_blocks = [b for b in result if getattr(b, "type", None) == "text"]
        assert text_blocks
        payload = json.loads(text_blocks[0].text)
        assert payload["decision_id"] == "SPEC-001"
        assert payload["metadata"]["type"] == "spec"
