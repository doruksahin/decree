"""SPEC-00000000000000000000000007 — MCP server tests.

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
    """A PRD + ADR + SPEC where SPEC-00000000000000000000000001 governs `src/foo.py`."""
    (root / "decree.toml").write_text(_decree_toml())
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "foo.py").touch()

    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        """---
id: PRD-00000000000000000000000001
status: approved
date: 2026-05-10
---

# PRD-00000000000000000000000001 Test PRD

## Problem Statement

Prose.
"""
    )
    (root / "decree" / "adr" / "adr-00000000000000000000000001-test.md").write_text(
        """---
id: ADR-00000000000000000000000001
status: accepted
date: 2026-05-11
references: [PRD-00000000000000000000000001]
---

# ADR-00000000000000000000000001 Test ADR

## Context and Problem Statement

Prose.
"""
    )
    (root / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001, ADR-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Test SPEC

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


def _write_threshold_zero_calibration(root: Path) -> None:
    from decree.eval.calibration import Calibration, save_calibration

    cal_dir = root / "eval" / "calibrations"
    cal_dir.mkdir(parents=True)
    save_calibration(
        Calibration(
            method_name="keyword-v1",
            target_precision=0.0,
            threshold=0.0,
            gate_weights={},
            calibrated_at="2026-05-12T00:00:00+00:00",
            n_calibration_queries=1,
        ),
        cal_dir / "keyword-v1.json",
    )


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


@pytest.fixture
def project_with_stale_index(project_with_index: Path) -> Path:
    (project_with_index / "decree" / "spec" / "spec-00000000000000000000000001-test.md").write_text(
        """---
id: SPEC-00000000000000000000000001
status: implemented
date: 2026-05-12
references: [PRD-00000000000000000000000001, ADR-00000000000000000000000001]
governs:
  - src/foo.py
---

# SPEC-00000000000000000000000001 Test SPEC

## Overview

Mutated after index rebuild.
"""
    )
    return project_with_index


# ── Direct tool-function tests ──────────────────────────────


class TestWhyTool:
    def test_exact_match(self, project_with_index: Path) -> None:
        result = mcp_server.why("src/foo.py")
        assert result["query"] == "src/foo.py"
        assert result["match_count"] == 1
        assert result["matches"][0]["decision_id"] == "SPEC-00000000000000000000000001"
        assert result["matches"][0]["match_kind"] == "exact"
        assert result["matches"][0]["type"] == "spec"
        assert result["matches"][0]["status"] == "implemented"
        assert "error" not in result

    def test_no_match_abstains(self, project_with_index: Path) -> None:
        result = mcp_server.why("src/nonexistent.py")
        assert result["match_count"] == 0
        assert result["matches"] == []
        assert "error" not in result

    def test_index_missing_returns_error_response(self, project_without_index: Path) -> None:
        result = mcp_server.why("src/foo.py")
        assert result == {
            "error": "index not found",
            "hint": "Run `decree index rebuild` to build the index, then retry.",
        }

    def test_stale_index_returns_error_response(self, project_with_stale_index: Path) -> None:
        result = mcp_server.why("src/foo.py")
        assert result["error"] == "index stale"
        assert result["drift_findings"] >= 1
        assert result["hint"] == "Run `decree index rebuild` before querying."


class TestRefsTool:
    def test_known_decision_returns_full_report(self, project_with_index: Path) -> None:
        result = mcp_server.refs("SPEC-00000000000000000000000001")
        assert result["decision_id"] == "SPEC-00000000000000000000000001"
        assert result["metadata"]["type"] == "spec"
        assert result["metadata"]["status"] == "implemented"
        assert "Test SPEC" in result["metadata"]["title"]
        # SPEC-00000000000000000000000001 references PRD-00000000000000000000000001 and ADR-00000000000000000000000001
        forward_to_ids = {r["to_id"] for r in result["forward_refs"]}
        assert forward_to_ids == {"PRD-00000000000000000000000001", "ADR-00000000000000000000000001"}
        # SPEC-00000000000000000000000001 governs src/foo.py
        govern_paths = {g["path"] for g in result["governs"]}
        assert "src/foo.py" in govern_paths
        # Sub-arrays exist with correct shapes
        assert isinstance(result["reverse_refs"], list)
        assert isinstance(result["supersedes_chain"], list)
        assert isinstance(result["commits"], list)

    def test_unknown_decision_returns_error_response(self, project_with_index: Path) -> None:
        result = mcp_server.refs("SPEC-00000000000000000000000999")
        assert result == {
            "error": "unknown decision id",
            "decision_id": "SPEC-00000000000000000000000999",
        }

    def test_index_missing_returns_error_response(self, project_without_index: Path) -> None:
        result = mcp_server.refs("SPEC-00000000000000000000000001")
        assert result == {
            "error": "index not found",
            "hint": "Run `decree index rebuild` to build the index, then retry.",
        }

    def test_stale_index_returns_error_response(self, project_with_stale_index: Path) -> None:
        result = mcp_server.refs("SPEC-00000000000000000000000001")
        assert result["error"] == "index stale"
        assert result["drift_findings"] >= 1
        assert result["hint"] == "Run `decree index rebuild` before querying."


# ── Tool registry ───────────────────────────────────────────


class TestProgressTool:
    def test_all_documents(self, project_with_index: Path) -> None:
        result = mcp_server.progress()
        assert "error" not in result
        assert result["scope"] == "all documents"
        assert result["document_count"] >= 1
        assert set(result["primary"].keys()) == {"done", "total", "percent"}
        assert isinstance(result["documents"], list)

    def test_single_doc_scope(self, project_with_index: Path) -> None:
        result = mcp_server.progress(doc_id="SPEC-00000000000000000000000001")
        assert "error" not in result
        assert result["scope"] == "doc SPEC-00000000000000000000000001"
        assert result["document_count"] == 1
        assert result["documents"][0]["doc_id"] == "SPEC-00000000000000000000000001"

    def test_unknown_doc_returns_error(self, project_with_index: Path) -> None:
        result = mcp_server.progress(doc_id="SPEC-00000000000000000000000999")
        assert "error" in result

    def test_tool_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["progress"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc


class TestReportTool:
    def test_dry_run_does_not_write(self, project_with_index: Path) -> None:
        result = mcp_server.report(doc_ids=["SPEC-00000000000000000000000001"], dry_run=True)
        assert "error" not in result
        assert result["dry_run"] is True
        assert result["written"] == []

    def test_tool_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["report"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc


class TestIntentCheckLiveConflicts:
    def test_other_active_files_surfaces_live_conflict(self, project_with_index: Path) -> None:
        result = mcp_server.intent_check(
            "Touch foo",
            ["src/foo.py"],
            other_active_files={"session-b": ["src/foo.py"]},
        )
        assert "error" not in result
        assert result["live_conflicts"] == [{"path": "src/foo.py", "session_ids": ["session-b"]}]
        assert any(a["action"] == "isolate_session" for a in result["recommended_actions"])

    def test_single_session_mode_has_empty_live_conflicts(self, project_with_index: Path) -> None:
        result = mcp_server.intent_check("Touch foo", ["src/foo.py"])
        assert "error" not in result
        assert result["live_conflicts"] == []


class TestToolRegistry:
    def test_exactly_nine_tools_registered(self) -> None:
        # SPEC-14 added `intent_check`; the agentkith integration added the
        # closeout tools `progress` and `report`; SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J
        # (commit-check Phase 3) added `commit_check`.
        tools = mcp._tool_manager.list_tools()
        names = sorted(t.name for t in tools)
        assert names == [
            "commit_check",
            "health",
            "intent_check",
            "intent_review",
            "progress",
            "refs",
            "report",
            "stale",
            "why",
        ], f"Expected the full decree MCP tool set; got {names}."

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
        # Full decree MCP tool set (incl. closeout progress/report + commit_check).
        assert names == [
            "commit_check",
            "health",
            "intent_check",
            "intent_review",
            "progress",
            "refs",
            "report",
            "stale",
            "why",
        ]

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
        assert payload["matches"][0]["decision_id"] == "SPEC-00000000000000000000000001"

    def test_tools_call_refs_via_fastmcp(self, project_with_index: Path) -> None:
        async def go():
            return await mcp.call_tool("refs", {"decision_id": "SPEC-00000000000000000000000001"})

        result = asyncio.run(go())
        text_blocks = [b for b in result if getattr(b, "type", None) == "text"]
        assert text_blocks
        payload = json.loads(text_blocks[0].text)
        assert payload["decision_id"] == "SPEC-00000000000000000000000001"
        assert payload["metadata"]["type"] == "spec"


# ── SPEC-00000000000000000000000008: stale + health tools ──────────────────────────


def _git_init_and_commit(repo: Path) -> None:
    """Bootstrap a tiny git repo with a single initial commit."""
    import subprocess

    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


class TestStaleTool:
    def test_no_git_returns_error_response(self, project_with_index: Path) -> None:
        result = mcp_server.stale()
        assert result == {
            "error": "not a git repository",
            "hint": "decree stale needs git history; initialize the project as a git repo first.",
        }

    def test_returns_empty_list_for_clean_repo(self, project_with_index: Path, monkeypatch) -> None:
        _git_init_and_commit(project_with_index)
        result = mcp_server.stale(threshold_commits=10)
        assert "stale_decisions" in result
        assert result["stale_decisions"] == []
        assert result["threshold_commits"] == 10

    def test_index_missing_returns_error_response(self, project_without_index: Path) -> None:
        result = mcp_server.stale()
        assert result["error"] == "index not found"


class TestHealthTool:
    def test_no_git_returns_error_response(self, project_with_index: Path) -> None:
        result = mcp_server.health()
        assert result == {
            "error": "not a git repository",
            "hint": "decree health needs git history; initialize the project as a git repo first.",
        }

    def test_returns_combined_report(self, project_with_index: Path, monkeypatch) -> None:
        _git_init_and_commit(project_with_index)
        result = mcp_server.health(threshold_commits=10, threshold_days=30)
        # The MCP payload mirrors `decree health --json` (no divergence): the v1/v2
        # governance signals reach agents through the same keys.
        assert set(result.keys()) >= {
            "stale_decisions",
            "ungoverned_hotspots",
            "dead_governance",
            "missing_governance",
            "unobserved_decisions",
            "observed_as_of",
            "threshold_commits",
            "threshold_days",
        }
        assert isinstance(result["dead_governance"], list)
        assert isinstance(result["missing_governance"], list)
        assert result["threshold_commits"] == 10
        assert result["threshold_days"] == 30

    def test_index_missing_returns_error_response(self, project_without_index: Path) -> None:
        result = mcp_server.health()
        assert result["error"] == "index not found"


class TestSpec008Docstrings:
    def test_stale_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["stale"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc

    def test_health_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["health"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc


class TestIntentReviewTool:
    def test_by_changed_paths(self, project_with_index: Path) -> None:
        result = mcp_server.intent_review(changed_paths=["src/foo.py"])
        assert "error" not in result
        assert result["changed_paths"] == ["src/foo.py"]
        assert len(result["governing_decisions"]) == 1
        assert result["governing_decisions"][0]["decision_id"] == "SPEC-00000000000000000000000001"

    def test_by_diff_string(self, project_with_index: Path) -> None:
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "index 0000000..1111111 100644\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -0,0 +1 @@\n"
            "+x = 1\n"
        )
        result = mcp_server.intent_review(diff=diff)
        assert "error" not in result
        assert result["changed_paths"] == ["src/foo.py"]
        assert len(result["governing_decisions"]) == 1

    def test_changed_paths_wins_when_both_given(self, project_with_index: Path) -> None:
        # Pass an empty diff but explicit changed_paths — paths should win.
        result = mcp_server.intent_review(
            diff="diff --git a/unrelated.py b/unrelated.py\n",
            changed_paths=["src/foo.py"],
        )
        assert result["changed_paths"] == ["src/foo.py"]

    def test_index_missing_returns_error_response(self, project_without_index: Path) -> None:
        result = mcp_server.intent_review(changed_paths=["src/foo.py"])
        assert result["error"] == "index not found"

    def test_intent_review_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["intent_review"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc


# ── SPEC-00000000000000000000000013 — with_abstention on MCP tools ────────────────


class TestWithAbstentionMcp:
    def test_why_with_abstention_signals_present(self, project_with_index: Path) -> None:
        _write_threshold_zero_calibration(project_with_index)
        result = mcp_server.why("src/foo.py", with_abstention=True)
        # Even when the answer is high-confidence (and so not abstained),
        # the calibrated-assessment fields are merged in.
        assert "abstained" in result
        assert "composite_score" in result
        assert "signals" in result
        # All 7 gates surface their scores.
        assert set(result["signals"].keys()) >= {
            "dominance",
            "identifier-citation",
            "hedge-phrase",
            "status",
            "recency",
            "coverage",
            "authorship",
        }

    def test_refs_with_abstention_returns_full_when_confident(self, project_with_index: Path) -> None:
        _write_threshold_zero_calibration(project_with_index)
        # SPEC-00000000000000000000000001 exists; decision_id-as-concept-query is high-confidence enough.
        result = mcp_server.refs("SPEC-00000000000000000000000001", with_abstention=True)
        assert "decision_id" in result
        if "metadata" in result:
            assert result["decision_id"] == "SPEC-00000000000000000000000001"

    def test_why_arg_schema_includes_with_abstention(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        props = tools["why"].parameters["properties"]
        assert "with_abstention" in props
        # boolean type
        assert props["with_abstention"]["type"] == "boolean"

    def test_refs_arg_schema_includes_with_abstention(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        props = tools["refs"].parameters["properties"]
        assert "with_abstention" in props
        assert props["with_abstention"]["type"] == "boolean"


# ── SPEC-00000000000000000000000014 — intent_check MCP tool ────────────────────────


class TestIntentCheckTool:
    def test_minimal_call_returns_report_shape(self, project_with_index: Path) -> None:
        result = mcp_server.intent_check(
            plan="Plan to touch src/foo.py",
            planned_files=["src/foo.py"],
        )
        assert "error" not in result
        # Schema-stable keys present (SPEC-00000000000000000000000014 IntentCheckReport).
        for key in (
            "plan",
            "planned_files",
            "governing_decisions",
            "stale_governance",
            "unchecked_acceptance_criteria",
            "conflicts",
            "abstention",
            "recommended_actions",
        ):
            assert key in result, f"missing key {key!r} in MCP intent_check payload"
        assert result["planned_files"] == ["src/foo.py"]
        assert len(result["governing_decisions"]) == 1
        assert result["governing_decisions"][0]["decision_id"] == "SPEC-00000000000000000000000001"

    def test_with_abstention_routes_through_calibrated(self, project_with_index: Path) -> None:
        # An ungoverned path should produce empty governance and (when the
        # calibration JSON is absent on disk) leave abstention None — but the
        # key must still exist in the payload.
        result = mcp_server.intent_check(
            plan="Touch an ungoverned file",
            planned_files=["src/never_governed.py"],
            with_abstention=True,
        )
        assert "error" not in result
        assert result["governing_decisions"] == []
        # `abstention` key is always present in the dict; it may be None when
        # there's no calibration on disk in the test sandbox.
        assert "abstention" in result

    def test_intent_check_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["intent_check"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc


# ── SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J: commit_check tool (Phase 3) ──────────────
#
# The `commit_check` MCP tool must return the EXACT payload the CLI emits with
# `--json`, so the two can never diverge. These tests build a real git+decree
# corpus (the CLI path shells out to git for the trailer range) and assert
# parity plus the gate exit codes.


def _commit_check_toml() -> str:
    return """\
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


def _cc_git(cwd: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _cc_write_spec(project: Path, spec_id: str, status: str, governs: list[str]) -> None:
    governs_yaml = "\n".join(f"  - {p}" for p in governs)
    (project / "decree" / "spec" / f"{spec_id.lower()}-test.md").write_text(
        f"---\nid: {spec_id}\nstatus: {status}\ndate: 2026-05-12\ngoverns:\n{governs_yaml}\n---\n\n"
        f"# {spec_id} Test SPEC\n\n## Overview\n\nProse.\n"
    )


def _cc_commit_file(project: Path, rel: str, msg: str) -> str:
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("content\n")
    _cc_git(project, "add", rel)
    _cc_git(project, "commit", "-m", msg)
    return _cc_git(project, "rev-parse", "HEAD").strip()


@pytest.fixture
def commit_check_project(tmp_path: Path, monkeypatch) -> Path:
    """A tmp dir that is a git repo, a decree project, and has a built index."""
    _cc_git(tmp_path, "init")
    _cc_git(tmp_path, "config", "user.email", "test@example.com")
    _cc_git(tmp_path, "config", "user.name", "Test")
    _cc_git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "decree.toml").write_text(_commit_check_toml())
    (tmp_path / "decree" / "spec").mkdir(parents=True)
    return tmp_path


def _cc_index(project: Path, monkeypatch) -> None:
    monkeypatch.chdir(project)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    db = IndexDB(default_db_path(project))
    db.rebuild(project)


def _cli_json(project: Path, capsys, **kw) -> dict:
    """Run the CLI `commit_check_run` with `--json` and return the parsed payload."""
    import argparse
    import os

    from decree.commands.commit_check import commit_check_run

    base = {
        "diff": None,
        "diff_base": None,
        "message": None,
        "strict": False,
        "min_coverage": None,
        "json": True,
        "project": str(project),
    }
    base.update(kw)
    cwd = os.getcwd()
    os.chdir(project)
    try:
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        commit_check_run(argparse.Namespace(**base))
    finally:
        os.chdir(cwd)
    return json.loads(capsys.readouterr().out)


class TestCommitCheckTool:
    def test_mcp_payload_equals_cli_json(self, commit_check_project: Path, capsys, monkeypatch) -> None:
        """Parity: the MCP tool return value EQUALS the CLI `--json` payload."""
        project = commit_check_project
        # In-flight SPEC governs src/a.py; a covered + an uncovered governed path.
        _cc_write_spec(project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _cc_write_spec(project, "SPEC-00000000000000000000000002", "approved", ["src/b.py"])
        _cc_index(project, monkeypatch)
        base = _cc_commit_file(project, "seed.txt", "base")
        _cc_commit_file(
            project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        _cc_commit_file(project, "src/b.py", "feat: b (no trailer)")

        cli_payload = _cli_json(project, capsys, diff_base=base)

        mcp_server._set_project_root(project)
        try:
            monkeypatch.chdir(project)
            mcp_payload = mcp_server.commit_check(diff_base=base)
        finally:
            mcp_server._set_project_root(None)  # type: ignore[arg-type]

        assert mcp_payload == cli_payload
        # Sanity on the underlying corpus: 1/2 covered, advisory exit 0.
        assert mcp_payload["coverage"] == {"covered": 1, "total": 2, "fraction": 0.5}
        assert mcp_payload["mode"] == "diff-base"
        assert mcp_payload["exit"] == 0

    def test_covered_case_exit_zero(self, commit_check_project: Path, monkeypatch) -> None:
        project = commit_check_project
        _cc_write_spec(project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _cc_index(project, monkeypatch)
        base = _cc_commit_file(project, "seed.txt", "base")
        _cc_commit_file(
            project,
            "src/a.py",
            "feat: a\n\nImplements: SPEC-00000000000000000000000001\n",
        )
        mcp_server._set_project_root(project)
        try:
            monkeypatch.chdir(project)
            payload = mcp_server.commit_check(diff_base=base, strict=True)
        finally:
            mcp_server._set_project_root(None)  # type: ignore[arg-type]
        assert payload["coverage"] == {"covered": 1, "total": 1, "fraction": 1.0}
        assert payload["uncovered"] == []
        assert payload["exit"] == 0

    def test_uncovered_strict_exit_one(self, commit_check_project: Path, monkeypatch) -> None:
        project = commit_check_project
        _cc_write_spec(project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _cc_index(project, monkeypatch)
        base = _cc_commit_file(project, "seed.txt", "base")
        _cc_commit_file(project, "src/a.py", "feat: a (no trailer)")
        mcp_server._set_project_root(project)
        try:
            monkeypatch.chdir(project)
            payload = mcp_server.commit_check(diff_base=base, strict=True)
        finally:
            mcp_server._set_project_root(None)  # type: ignore[arg-type]
        assert payload["strict"] is True
        assert len(payload["uncovered"]) == 1
        assert payload["uncovered"][0]["decision_id"] == "SPEC-00000000000000000000000001"
        assert payload["exit"] == 1

    def test_message_mode_requires_message_for_diff_paths(self, commit_check_project: Path, monkeypatch) -> None:
        # changed_paths supply paths; without a message there is no trailer source.
        project = commit_check_project
        _cc_write_spec(project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        _cc_index(project, monkeypatch)
        mcp_server._set_project_root(project)
        try:
            monkeypatch.chdir(project)
            payload = mcp_server.commit_check(changed_paths=["src/a.py"])
        finally:
            mcp_server._set_project_root(None)  # type: ignore[arg-type]
        assert "error" in payload
        assert payload["exit"] == 2

    def test_index_missing_returns_error_response(self, commit_check_project: Path, monkeypatch) -> None:
        # No index built.
        project = commit_check_project
        _cc_write_spec(project, "SPEC-00000000000000000000000001", "approved", ["src/a.py"])
        mcp_server._set_project_root(project)
        try:
            monkeypatch.chdir(project)
            payload = mcp_server.commit_check(message="ignored")
        finally:
            mcp_server._set_project_root(None)  # type: ignore[arg-type]
        assert payload == {
            "error": "index not found",
            "hint": "Run `decree index rebuild` to build the index, then retry.",
        }

    def test_commit_check_has_full_docstring(self) -> None:
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        desc = tools["commit_check"].description or ""
        assert "Args:" in desc
        assert "Returns:" in desc
        assert "When to call:" in desc
        assert "When not to call:" in desc
