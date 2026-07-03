"""Tests for decree.commands.generate_html."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from decree.commands import generate_html

SPEC_ID = "SPEC-00000000000000000000000001"
CLOSED_SPEC_ID = "SPEC-00000000000000000000000002"
CLOSED_SPRINT_ID = "SPRINT-00000000000000000000000001"
ACTIVE_SPRINT_ID = "SPRINT-00000000000000000000000002"


def _write_project(root: Path) -> None:
    (root / "decree.toml").write_text(
        """\
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
approve = "approved"
implement = "implemented"
"""
    )
    _write_spec(root, SPEC_ID, "Board", status="draft", criteria="- [x] Done\n- [ ] Todo")
    _write_spec(root, CLOSED_SPEC_ID, "History", status="implemented", criteria="- [x] Shipped")
    _write_v2_ledger(root)


def _write_spec(root: Path, spec_id: str, title: str, *, status: str, criteria: str) -> None:
    path = root / "decree" / "spec" / "delivery" / f"{spec_id.lower()}-{title.lower()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""\
---
id: {spec_id}
status: {status}
date: 2026-06-26
---

# {spec_id} {title}

## Overview

Text.

## Technical Design

Text.

## Testing Strategy

Text.

## Acceptance Criteria

{criteria}
"""
    )


def _write_v2_ledger(root: Path) -> None:
    """v2 directory store: state.yaml + one live file + one closed archive."""
    sprints = root / "decree" / "sprints"
    (sprints / "live").mkdir(parents=True)
    (sprints / "closed").mkdir()
    (sprints / "state.yaml").write_text(
        f"""\
schema: decree.sprints.v2
mode: enabled
state: active
active:
  id: {ACTIVE_SPRINT_ID}
  name: Sprint 2
  started: '2026-06-26'
"""
    )
    (sprints / "live" / f"{SPEC_ID}.yaml").write_text(
        f"""\
document: {SPEC_ID}
scope: active
kind: execution
source: manual
added: '2026-06-26'
"""
    )
    # Unquoted dates on purpose: outcome dates must be normalized to ISO
    # strings so the JSON board payload stays serializable.
    (sprints / "closed" / f"{CLOSED_SPRINT_ID}.yaml").write_text(
        f"""\
id: {CLOSED_SPRINT_ID}
name: Sprint 1
status: closed
started: 2026-06-01
closed: 2026-06-25
items:
  - document: {CLOSED_SPEC_ID}
    kind: execution
    source: manual
    added: 2026-06-01
    outcome:
      kind: completed
      at: 2026-06-25
      evidence:
        commits: []
      snapshot:
        status: implemented
        primary_done: 1
        primary_total: 1
        deferred_done: 0
        deferred_total: 0
"""
    )


def _args(**overrides):
    data = {"output": "board.html", "sprint": None}
    data.update(overrides)
    return argparse.Namespace(**data)


def _payload(html: str) -> dict:
    match = re.search(r'<script id="decree-data" type="application/json">(.*?)</script>', html, re.S)
    assert match is not None
    return json.loads(match.group(1))


def test_generate_html_writes_self_contained_board(tmp_path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert generate_html.run(_args()) == 0

    html = (tmp_path / "board.html").read_text()
    payload = _payload(html)
    assert payload["schema"] == "decree.board.v1"
    # Default selection is the active sprint even though closed history exists.
    assert payload["selected_sprint_id"] == ACTIVE_SPRINT_ID
    # Closed archives come first (ULID order); the synthesized active record is last.
    assert [record["id"] for record in payload["sprints"]] == [CLOSED_SPRINT_ID, ACTIVE_SPRINT_ID]

    closed = payload["sprints"][0]
    assert closed["status"] == "closed"
    assert closed["closed"] == "2026-06-25"
    assert closed["cards"][0]["document"] == CLOSED_SPEC_ID
    assert closed["cards"][0]["outcome"]["kind"] == "completed"
    assert closed["cards"][0]["outcome"]["at"] == "2026-06-25"
    assert closed["cards"][0]["column"] == "done"

    active = payload["sprints"][1]  # synthesized from state.yaml + live/
    assert active["status"] == "active"
    assert active["name"] == "Sprint 2"
    assert active["started"] == "2026-06-26"
    assert active["closed"] is None
    assert active["cards"][0]["document"] == SPEC_ID
    assert active["cards"][0]["column"] == "in_progress"
    assert active["cards"][0]["doc"]["bucket"] == "delivery"

    assert payload["backlog"] == []
    assert payload["draft_pool"] == []
    assert payload["documents"][0]["id"] == SPEC_ID
    assert payload["documents"][0]["bucket"] == "delivery"
    assert payload["documents"][0]["absolute_path"].endswith(f"{SPEC_ID.lower()}-board.md")
    assert payload["documents"][0]["file_url"].startswith("file://")
    assert payload["documents"][0]["folder_path"].endswith("decree/spec/delivery")
    assert payload["documents"][0]["folder_url"].startswith("file://")
    assert payload["documents"][0]["progress"]["primary"] == {"done": 1, "total": 2, "percent": 50}
    assert "<h1>" in payload["documents"][0]["markdown_html"]
    assert "Acceptance Criteria" in payload["documents"][0]["markdown_html"]
    assert payload["documents"][0]["markdown_source"].startswith(f"# {SPEC_ID} Board")
    assert "Sprint 1" in html
    assert "Sprint 2" in html
    assert "function renderSprint" in html
    assert "function openDocument" in html
    assert 'id="document-modal"' in html
    assert 'id="context-menu"' in html
    assert "data-open-doc" in html
    assert "data-doc-menu" in html
    assert 'data-context-action="copy-path"' in html
    assert "function copyText" in html
    assert "function showContextMenu" in html
    assert "Related PRDs &amp; ADRs" in html
    assert "function attr(value)" in html
    assert 'fillSelect(filters.bucket, "All buckets"' in html


def test_generate_html_honors_selected_closed_sprint(tmp_path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert generate_html.run(_args(sprint=CLOSED_SPRINT_ID, output="selected.html")) == 0

    payload = _payload((tmp_path / "selected.html").read_text())
    assert payload["selected_sprint_id"] == CLOSED_SPRINT_ID


def test_generate_html_rejects_unknown_sprint(tmp_path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert generate_html.run(_args(sprint="SPRINT-00000000000000000000000003")) == 1
    assert not (tmp_path / "board.html").exists()
