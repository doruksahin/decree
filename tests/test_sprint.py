"""Tests for sprint ledger behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from decree.commands import ddd, lint, mcp_server, new, progress, sprint
from decree.identity import require_doc_id, require_sprint_id
from decree.sprints import load_ledger, validate_ledger


def _write_config(root: Path) -> None:
    (root / "decree.toml").write_text(
        """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = []

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
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
warn_on_reference = ["rejected"]
required_sections = []

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []

[types.adr.actions]
accept = "accepted"
reject = "rejected"

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = []

[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
approve = "approved"
implement = "implemented"
"""
    )
    for name in ("prd", "adr", "spec"):
        (root / "decree" / name).mkdir(parents=True)


def _write_doc(
    root: Path,
    doc_id: str,
    type_name: str,
    status: str,
    body: str,
    *,
    date: str = "2026-01-01",
    references: tuple[str, ...] = (),
) -> Path:
    path = root / "decree" / type_name / f"{doc_id.lower()}-test.md"
    refs = "".join(f"- {ref}\n" for ref in references)
    refs_block = f"references:\n{refs}" if references else ""
    path.write_text(f"---\nid: {doc_id}\nstatus: {status}\ndate: {date}\n{refs_block}---\n# {doc_id} Test\n\n{body}\n")
    return path


def _new_args(**overrides):
    data = {
        "doc_type": "spec",
        "title": "New Capability",
        "backlog": False,
        "draft_pool": False,
        "reason": None,
        "bucket": "sprint-work",
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _progress_args(**overrides):
    data = {
        "json": True,
        "doc": None,
        "chain": None,
        "governs": None,
        "changed": False,
        "base": None,
        "sprint": None,
        "all_sprints": False,
        "backlog": False,
        "draft_pool": False,
        "corpus": False,
        "include_context": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def test_sprint_identity_is_separate_from_document_identity() -> None:
    sprint_id = "SPRINT-00000000000000000000000001"
    assert require_sprint_id(sprint_id) == sprint_id
    try:
        require_doc_id(sprint_id)
    except ValueError as e:
        assert "TYPE-ULID" in str(e)
    else:  # pragma: no cover - defensive assertion shape
        raise AssertionError("SPRINT IDs must not validate as document IDs")


def test_init_creates_active_ledger(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0

    ledger = load_ledger()
    assert ledger.state == "active"
    assert ledger.active_sprint is not None
    assert ledger.active_sprint.name == "Sprint 1"
    assert ledger.active_sprint.id.startswith("SPRINT-")


def test_new_spec_defaults_to_active_sprint(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert new.run(_new_args()) == 0

    ledger = load_ledger()
    assert ledger.active_sprint is not None
    assert len(ledger.active_sprint.items) == 1
    item = ledger.active_sprint.items[0]
    assert item.source == "new"
    assert item.kind == "execution"
    assert list((tmp_path / "decree" / "spec" / "sprint-work").glob(f"{item.document.lower()}-*.md"))


def test_new_spec_bucket_composes_with_active_sprint_default(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert new.run(_new_args(bucket="delivery-api")) == 0

    ledger = load_ledger()
    assert ledger.active_sprint is not None
    item = ledger.active_sprint.items[0]
    assert item.source == "new"
    assert list((tmp_path / "decree" / "spec" / "delivery-api").glob(f"{item.document.lower()}-*.md"))


def test_new_spec_requires_explicit_destination_when_paused(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))
    assert sprint.run(argparse.Namespace(sprint_action="pause", reason="summer freeze")) == 0

    assert new.run(_new_args(title="Blocked Spec")) == 1
    assert list((tmp_path / "decree" / "spec").rglob("*.md")) == []

    assert new.run(_new_args(title="Backlog Spec", backlog=True, reason="not for the paused window")) == 0
    ledger = load_ledger()
    assert ledger.state == "paused"
    assert len(ledger.backlog) == 1
    assert ledger.backlog[0].reason == "not for the paused window"

    assert new.run(_new_args(title="Draft Spec", draft_pool=True, reason="speculative")) == 0
    ledger = load_ledger()
    assert len(ledger.draft_pool) == 1
    assert ledger.draft_pool[0].reason == "speculative"

    assert sprint.run(argparse.Namespace(sprint_action="resume", name="Sprint 2")) == 0
    ledger = load_ledger()
    assert ledger.state == "active"
    assert ledger.active_sprint is not None
    assert ledger.active_sprint.name == "Sprint 2"


def test_prd_requires_planning_kind_for_sprint_membership(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    prd_id = "PRD-00000000000000000000000001"
    _write_doc(tmp_path, prd_id, "prd", "approved", "## Requirements\n\n- [ ] Plan\n")
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert sprint.run(argparse.Namespace(sprint_action="add", document=prd_id, kind=None)) == 1
    assert sprint.run(argparse.Namespace(sprint_action="add", document=prd_id, kind="planning")) == 0

    ledger = load_ledger()
    assert ledger.active_sprint is not None
    assert ledger.active_sprint.items[0].kind == "planning"


def test_lint_rejects_completed_outcome_without_100_percent_snapshot(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(
        tmp_path,
        spec_id,
        "spec",
        "approved",
        "## Acceptance Criteria\n\n- [x] Done\n- [ ] Not done\n",
    )
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: paused
active: null
paused:
  since: 2026-06-26
  reason: freeze
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: closed
    started: 2026-06-26
    closed: 2026-06-26
    items:
      - document: {spec_id}
        kind: execution
        source: manual
        added: 2026-06-26
        outcome:
          kind: completed
          at: 2026-06-26
          snapshot:
            status: approved
            primary_done: 1
            primary_total: 2
            deferred_done: 0
            deferred_total: 0
backlog: []
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)

    assert lint.run(argparse.Namespace(check_attachments=False)) == 1
    assert "completed outcome requires snapshot primary progress at 100%" in capsys.readouterr().out


def test_validate_ledger_rejects_post_init_spec_outside_any_sprint_scope(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Do it\n", date="2026-06-26")
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        """\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items: []
backlog: []
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any("must be in active sprint, backlog, or draft_pool" in e for e in result.errors)


def test_validate_ledger_rejects_duplicate_live_membership_and_warns_on_old_backlog(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Do it\n", date="2026-06-26")
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {spec_id}
        kind: execution
        source: manual
        added: 2026-06-26
backlog:
  - document: {spec_id}
    kind: execution
    source: manual
    since: 2026-01-01
    added: 2026-01-01
    reason: old item
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any("live document appears in both active sprint" in e for e in result.errors)
    assert any("backlog item is" in w for w in result.warnings)


def test_progress_defaults_to_active_sprint_and_mcp_matches(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    old_spec = "SPEC-00000000000000000000000001"
    active_spec = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, old_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Old\n", date="2026-01-01")
    _write_doc(tmp_path, active_spec, "spec", "draft", "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n")
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {active_spec}
        kind: execution
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)

    assert progress.run(_progress_args()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"].startswith("active sprint")
    assert payload["document_count"] == 1
    assert payload["documents"][0]["doc_id"] == active_spec
    assert payload["primary"] == {"done": 1, "total": 2, "percent": 50}

    mcp_payload = mcp_server.progress()
    assert mcp_payload["scope"] == payload["scope"]
    assert mcp_payload["primary"] == payload["primary"]

    assert progress.run(_progress_args(corpus=True)) == 0
    corpus_payload = json.loads(capsys.readouterr().out)
    assert corpus_payload["scope"] == "all documents"
    assert corpus_payload["document_count"] == 2


def test_progress_include_context_and_human_sections(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    prd_id = "PRD-00000000000000000000000001"
    adr_id = "ADR-00000000000000000000000001"
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, prd_id, "prd", "approved", "## Requirements\n\n- [ ] Context\n")
    _write_doc(tmp_path, adr_id, "adr", "accepted", "## Decision Outcome\n\nAccepted.\n", references=(prd_id,))
    _write_doc(
        tmp_path,
        spec_id,
        "spec",
        "draft",
        "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n",
        date="2026-06-26",
        references=(prd_id, adr_id),
    )
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {spec_id}
        kind: execution
        source: manual
        added: 2026-06-26
      - document: {prd_id}
        kind: planning
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)

    assert progress.run(_progress_args(json=False, include_context=True)) == 0
    output = capsys.readouterr().out
    assert "Tasks:" in output
    assert "Planning:" in output
    assert "Context:" in output
    assert adr_id in output

    assert progress.run(_progress_args(include_context=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["document_count"] == 2
    assert payload["context_documents"][0]["doc_id"] == adr_id


def test_ddd_defaults_to_active_sprint_with_context(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    prd_id = "PRD-00000000000000000000000001"
    adr_id = "ADR-00000000000000000000000001"
    active_spec = "SPEC-00000000000000000000000001"
    old_spec = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, prd_id, "prd", "approved", "## Requirements\n\n- [ ] Context\n")
    _write_doc(tmp_path, adr_id, "adr", "accepted", "## Decision Outcome\n\nAccepted.\n", references=(prd_id,))
    _write_doc(
        tmp_path,
        active_spec,
        "spec",
        "draft",
        "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n",
        date="2026-06-26",
        references=(prd_id, adr_id),
    )
    _write_doc(tmp_path, old_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Old\n", date="2026-01-01")
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {active_spec}
        kind: execution
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
"""
    )
    monkeypatch.chdir(tmp_path)

    assessment = ddd.assess()

    assert assessment.scope.startswith("active sprint")
    assert assessment.documents == {"adr": 1, "prd": 1, "spec": 1}
    assert assessment.progress["completed"] == 1
    assert assessment.progress["total"] == 2
    assert assessment.suggested_actions[0].target_id == active_spec


def test_rollover_completed_snapshot_is_stable_after_document_changes(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    spec_path = _write_doc(
        tmp_path,
        spec_id,
        "spec",
        "approved",
        "## Acceptance Criteria\n\n- [x] Done\n",
        date="2026-06-26",
    )
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {spec_id}
        kind: execution
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
"""
    )
    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: completed\n")
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    ledger = load_ledger()
    assert ledger.state == "active"
    assert ledger.active_sprint is not None
    assert ledger.active_sprint.name == "Sprint 2"
    assert ledger.sprints[0].status == "closed"
    assert ledger.sprints[0].items[0].outcome["snapshot"]["primary_done"] == 1

    spec_path.write_text(spec_path.read_text().replace("- [x] Done", "- [ ] Done"))
    ledger = load_ledger()
    assert ledger.sprints[0].items[0].outcome["snapshot"]["primary_done"] == 1


def test_rollover_carryover_requires_reason_and_creates_successor_item(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(
        tmp_path,
        spec_id,
        "spec",
        "approved",
        "## Acceptance Criteria\n\n- [ ] Todo\n",
        date="2026-06-26",
    )
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: SPRINT-00000000000000000000000001
paused: null
sprints:
  - id: SPRINT-00000000000000000000000001
    name: Sprint 1
    status: active
    started: 2026-06-26
    closed: null
    items:
      - document: {spec_id}
        kind: execution
        source: manual
        added: 2026-06-26
backlog: []
draft_pool: []
"""
    )
    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: carried_over\n")
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 1

    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: carried_over\n    reason: larger than expected\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    ledger = load_ledger()
    assert ledger.active_sprint is not None
    assert ledger.active_sprint.items[0].document == spec_id
    assert ledger.active_sprint.items[0].source == "carryover"
    assert ledger.active_sprint.items[0].carryover_from == "SPRINT-00000000000000000000000001"
