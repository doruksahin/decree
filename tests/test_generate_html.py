"""Tests for decree.commands.generate_html."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from decree.commands import generate_html

SPEC_ID = "SPEC-00000000000000000000000001"
SPRINT_ID = "SPRINT-00000000000000000000000001"


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
    spec_path = root / "decree" / "spec" / "delivery" / f"{SPEC_ID.lower()}-board.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        f"""\
---
id: {SPEC_ID}
status: draft
date: 2026-06-26
---

# {SPEC_ID} Board

## Overview

Text.

## Technical Design

Text.

## Testing Strategy

Text.

## Acceptance Criteria

- [x] Done
- [ ] Todo
"""
    )
    ledger_dir = root / "decree" / "sprints"
    ledger_dir.mkdir()
    (ledger_dir / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: {SPRINT_ID}
paused: null
sprints:
  - id: {SPRINT_ID}
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {SPEC_ID}
        kind: execution
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
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
    assert payload["selected_sprint_id"] == SPRINT_ID
    assert payload["sprints"][0]["cards"][0]["document"] == SPEC_ID
    assert payload["sprints"][0]["cards"][0]["column"] == "in_progress"
    assert payload["sprints"][0]["cards"][0]["doc"]["bucket"] == "delivery"
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


def test_generate_html_honors_selected_sprint(tmp_path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert generate_html.run(_args(sprint=SPRINT_ID, output="selected.html")) == 0

    payload = _payload((tmp_path / "selected.html").read_text())
    assert payload["selected_sprint_id"] == SPRINT_ID


def test_generate_html_rejects_unknown_sprint(tmp_path, monkeypatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert generate_html.run(_args(sprint="SPRINT-00000000000000000000000002")) == 1
    assert not (tmp_path / "board.html").exists()
