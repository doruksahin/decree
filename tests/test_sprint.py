"""Tests for sprint directory-store (v2) behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from decree.commands import ddd, lint, mcp_server, new, progress, sprint
from decree.identity import require_doc_id, require_sprint_id
from decree.sprints import SprintLedgerError, complete_item, drop_item, load_view, validate_ledger

SPRINT_1 = "SPRINT-00000000000000000000000001"


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


def _write_v2_ledger(
    root: Path,
    *,
    state: dict | None = None,
    live: list[dict] = (),
    closed: list[dict] = (),
) -> None:
    """Write a v2 sprint directory store: state.yaml + live/*.yaml + closed/*.yaml.

    Each ``live`` entry is the file's mapping; the filename defaults to
    ``<document>.yaml`` and can be overridden with a ``_filename`` key.
    """
    sprints_dir = root / "decree" / "sprints"
    (sprints_dir / "live").mkdir(parents=True, exist_ok=True)
    (sprints_dir / "closed").mkdir(parents=True, exist_ok=True)
    if state is None:
        state = {"state": "active", "active": {"id": SPRINT_1, "name": "Sprint 1", "started": "2026-06-26"}}
    payload = {"schema": "decree.sprints.v2", "mode": "enabled", **state}
    (sprints_dir / "state.yaml").write_text(yaml.safe_dump(payload, sort_keys=False))
    for entry in live:
        entry = dict(entry)
        filename = entry.pop("_filename", f"{entry['document']}.yaml")
        (sprints_dir / "live" / filename).write_text(yaml.safe_dump(entry, sort_keys=False))
    for record in closed:
        (sprints_dir / "closed" / f"{record['id']}.yaml").write_text(yaml.safe_dump(record, sort_keys=False))


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


def test_init_creates_active_state_and_store_directories(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0

    assert (tmp_path / "decree" / "sprints" / "state.yaml").exists()
    assert (tmp_path / "decree" / "sprints" / "live").is_dir()
    assert (tmp_path / "decree" / "sprints" / "closed").is_dir()
    view = load_view()
    assert view.state.state == "active"
    assert view.state.active is not None
    assert view.state.active["name"] == "Sprint 1"
    assert require_sprint_id(view.state.active["id"]) == view.state.active["id"]
    assert view.state.active["started"]
    assert view.live == {}
    assert view.closed == ()

    # A second init must refuse: state.yaml already exists.
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1 again")) == 1


def test_new_spec_defaults_to_active_sprint(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert new.run(_new_args()) == 0

    view = load_view()
    assert len(view.active_items) == 1
    item = view.active_items[0]
    assert item.scope == "active"
    assert item.source == "new"
    assert item.kind == "execution"
    assert item.outcome is None
    assert (tmp_path / "decree" / "sprints" / "live" / f"{item.document}.yaml").exists()
    assert list((tmp_path / "decree" / "spec" / "sprint-work").glob(f"{item.document.lower()}-*.md"))


def test_new_spec_bucket_composes_with_active_sprint_default(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert new.run(_new_args(bucket="delivery-api")) == 0

    view = load_view()
    item = view.active_items[0]
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
    view = load_view()
    assert view.state.state == "paused"
    assert len(view.backlog_items) == 1
    assert view.backlog_items[0].reason == "not for the paused window"

    assert new.run(_new_args(title="Draft Spec", draft_pool=True, reason="speculative")) == 0
    view = load_view()
    assert len(view.draft_pool_items) == 1
    assert view.draft_pool_items[0].reason == "speculative"

    assert sprint.run(argparse.Namespace(sprint_action="resume", name="Sprint 2")) == 0
    view = load_view()
    assert view.state.state == "active"
    assert view.state.active is not None
    assert view.state.active["name"] == "Sprint 2"


def test_prd_requires_planning_kind_for_sprint_membership(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    prd_id = "PRD-00000000000000000000000001"
    _write_doc(tmp_path, prd_id, "prd", "approved", "## Requirements\n\n- [ ] Plan\n")
    monkeypatch.chdir(tmp_path)
    sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1"))

    assert sprint.run(argparse.Namespace(sprint_action="add", document=prd_id, kind=None)) == 1
    assert sprint.run(argparse.Namespace(sprint_action="add", document=prd_id, kind="planning")) == 0

    view = load_view()
    assert view.active_items[0].kind == "planning"


def test_move_promotes_backlog_item_to_active_by_rewriting_one_live_file(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    target = "SPEC-00000000000000000000000001"
    sibling = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, target, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Promote\n")
    _write_doc(tmp_path, sibling, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Keep\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {
                "document": target,
                "scope": "backlog",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
                "since": "2026-06-26",
                "reason": "next sprint",
            },
            {"document": sibling, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    sprints_dir = tmp_path / "decree" / "sprints"
    state_before = (sprints_dir / "state.yaml").read_bytes()
    sibling_before = (sprints_dir / "live" / f"{sibling}.yaml").read_bytes()
    target_before = (sprints_dir / "live" / f"{target}.yaml").read_bytes()

    assert sprint.run(argparse.Namespace(sprint_action="move", document=target, to="active", reason=None)) == 0

    assert (sprints_dir / "state.yaml").read_bytes() == state_before
    assert (sprints_dir / "live" / f"{sibling}.yaml").read_bytes() == sibling_before
    assert (sprints_dir / "live" / f"{target}.yaml").read_bytes() != target_before
    item = load_view().live[target]
    assert item.scope == "active"
    assert item.reason is None
    assert item.since is None
    assert item.review_after is None


def test_move_active_item_to_backlog_requires_reason(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Defer\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="move", document=spec_id, to="backlog", reason=None)) == 1
    assert "reason is required" in capsys.readouterr().err
    assert load_view().live[spec_id].scope == "active"

    assert sprint.run(argparse.Namespace(sprint_action="move", document=spec_id, to="backlog", reason="blocked")) == 0
    item = load_view().live[spec_id]
    assert item.scope == "backlog"
    assert item.reason == "blocked"
    assert item.since


def test_move_refuses_resolved_active_item(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    complete_item(spec_id)

    assert sprint.run(argparse.Namespace(sprint_action="move", document=spec_id, to="backlog", reason="reopen")) == 1
    assert "already has a resolved live record (completed)" in capsys.readouterr().err
    assert load_view().live[spec_id].scope == "active"


def test_complete_writes_outcome_into_only_its_own_live_file(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    done_spec = "SPEC-00000000000000000000000001"
    open_spec = "SPEC-00000000000000000000000002"
    backlog_spec = "SPEC-00000000000000000000000003"
    _write_doc(tmp_path, done_spec, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_doc(tmp_path, open_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Todo\n")
    _write_doc(tmp_path, backlog_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Later\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": done_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {"document": open_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {
                "document": backlog_spec,
                "scope": "backlog",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
                "since": "2026-06-26",
                "reason": "next sprint",
            },
        ],
    )
    monkeypatch.chdir(tmp_path)
    sprints_dir = tmp_path / "decree" / "sprints"
    state_before = (sprints_dir / "state.yaml").read_bytes()
    sibling_before = (sprints_dir / "live" / f"{open_spec}.yaml").read_bytes()
    backlog_before = (sprints_dir / "live" / f"{backlog_spec}.yaml").read_bytes()
    target_before = (sprints_dir / "live" / f"{done_spec}.yaml").read_bytes()

    args = argparse.Namespace(sprint_action="complete", document=done_spec, commit=["abc1234", "def5678"])
    assert sprint.run(args) == 0

    # Only the completed item's own live file changed.
    assert (sprints_dir / "state.yaml").read_bytes() == state_before
    assert (sprints_dir / "live" / f"{open_spec}.yaml").read_bytes() == sibling_before
    assert (sprints_dir / "live" / f"{backlog_spec}.yaml").read_bytes() == backlog_before
    assert (sprints_dir / "live" / f"{done_spec}.yaml").read_bytes() != target_before

    view = load_view()
    outcome = view.live[done_spec].outcome
    assert outcome is not None
    assert outcome["kind"] == "completed"
    assert outcome["evidence"] == {"commits": ["abc1234", "def5678"]}
    assert outcome["snapshot"]["status"] == "approved"
    assert outcome["snapshot"]["primary_done"] == 1
    assert outcome["snapshot"]["primary_total"] == 1
    assert view.active_open_items == (view.live[open_spec],)

    capsys.readouterr()
    assert sprint.run(argparse.Namespace(sprint_action="status")) == 0
    status_out = capsys.readouterr().out
    assert "Done (awaiting rollover):" in status_out
    assert f"  {done_spec} (completed)" in status_out


def test_complete_refuses_below_100_percent_primary_criteria(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="complete", document=spec_id, commit=None)) == 1
    assert f"{spec_id} cannot be completed unless primary acceptance criteria are 100%" in capsys.readouterr().err
    assert load_view().live[spec_id].outcome is None


def test_complete_records_outcome_for_planning_item(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    prd_id = "PRD-00000000000000000000000001"
    _write_doc(tmp_path, prd_id, "prd", "approved", "## Requirements\n\n- [x] Plan\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": prd_id, "scope": "active", "kind": "planning", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="complete", document=prd_id, commit=None)) == 0

    item = load_view().live[prd_id]
    assert item.kind == "planning"
    assert item.outcome is not None
    assert item.outcome["kind"] == "completed"
    assert item.outcome["snapshot"]["primary_done"] == 1


def test_complete_refuses_resolved_and_non_active_items(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    done_spec = "SPEC-00000000000000000000000001"
    backlog_spec = "SPEC-00000000000000000000000002"
    outside_spec = "SPEC-00000000000000000000000003"
    _write_doc(tmp_path, done_spec, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_doc(tmp_path, backlog_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Later\n")
    _write_doc(tmp_path, outside_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Elsewhere\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": done_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {
                "document": backlog_spec,
                "scope": "backlog",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
                "since": "2026-06-26",
                "reason": "next sprint",
            },
        ],
    )
    monkeypatch.chdir(tmp_path)
    complete_item(done_spec)

    with pytest.raises(SprintLedgerError) as already:
        complete_item(done_spec)
    assert str(already.value) == f"{done_spec} already has a recorded outcome (completed)"

    with pytest.raises(SprintLedgerError) as wrong_scope:
        complete_item(backlog_spec)
    assert str(wrong_scope.value) == f"{backlog_spec} is in backlog, not the active sprint"

    with pytest.raises(SprintLedgerError) as missing:
        complete_item(outside_spec)
    assert str(missing.value) == f"{outside_spec} is not an active sprint item"


def test_terminal_status_after_complete_keeps_ledger_valid(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n", date="2026-06-26")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    complete_item(spec_id)
    # Move the document to a terminal status AFTER the mid-sprint completion.
    _write_doc(tmp_path, spec_id, "spec", "implemented", "## Acceptance Criteria\n\n- [x] Done\n", date="2026-06-26")

    result = validate_ledger(tmp_path, load_all_types())

    assert result.errors == ()


def test_drop_requires_reason_and_records_outcome(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Todo\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SprintLedgerError) as no_reason:
        drop_item(spec_id, reason="   ")
    assert str(no_reason.value) == "reason is required"
    assert load_view().live[spec_id].outcome is None

    assert sprint.run(argparse.Namespace(sprint_action="drop", document=spec_id, reason="descoped")) == 0
    outcome = load_view().live[spec_id].outcome
    assert outcome is not None
    assert outcome["kind"] == "dropped"
    assert outcome["reason"] == "descoped"
    assert outcome["snapshot"]["primary_total"] == 1  # audit snapshot recorded even below 100%


def test_pause_refuses_open_items_then_folds_resolved_into_archive(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="pause", reason="summer freeze")) == 1
    assert "cannot pause with open active-sprint items; complete, drop, or rollover them first" in (
        capsys.readouterr().err
    )
    assert load_view().state.state == "active"
    assert not (tmp_path / "decree" / "sprints" / "closed" / f"{SPRINT_1}.yaml").exists()

    complete_item(spec_id)
    assert sprint.run(argparse.Namespace(sprint_action="pause", reason="summer freeze")) == 0

    assert (tmp_path / "decree" / "sprints" / "closed" / f"{SPRINT_1}.yaml").exists()
    view = load_view()
    assert view.state.state == "paused"
    assert view.state.paused is not None
    assert view.state.paused["reason"] == "summer freeze"
    assert view.live == {}
    assert len(view.closed) == 1
    record = view.closed[0]
    assert record.id == SPRINT_1
    assert record.status == "closed"
    assert record.items[0].document == spec_id
    assert record.items[0].outcome is not None
    assert record.items[0].outcome["kind"] == "completed"


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
    _write_v2_ledger(
        tmp_path,
        state={"state": "paused", "paused": {"since": "2026-06-26", "reason": "freeze"}},
        closed=[
            {
                "id": SPRINT_1,
                "name": "Sprint 1",
                "status": "closed",
                "started": "2026-06-26",
                "closed": "2026-06-26",
                "items": [
                    {
                        "document": spec_id,
                        "kind": "execution",
                        "source": "manual",
                        "added": "2026-06-26",
                        "outcome": {
                            "kind": "completed",
                            "at": "2026-06-26",
                            "snapshot": {
                                "status": "approved",
                                "primary_done": 1,
                                "primary_total": 2,
                                "deferred_done": 0,
                                "deferred_total": 0,
                            },
                        },
                    }
                ],
            }
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert lint.run(argparse.Namespace(check_attachments=False)) == 1
    assert "completed outcome requires snapshot primary progress at 100%" in capsys.readouterr().out


def test_validate_ledger_rejects_post_init_spec_outside_any_sprint_scope(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Do it\n", date="2026-06-26")
    _write_v2_ledger(tmp_path)
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any("must be in active sprint, backlog, or draft_pool" in e for e in result.errors)


def test_validate_ledger_rejects_colliding_live_documents_and_warns_on_old_backlog(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    spec_id = "SPEC-00000000000000000000000001"
    other_id = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, spec_id, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Do it\n", date="2026-06-26")
    # Two live files whose `document` fields collide: structurally possible only
    # through a filename<->document mismatch (e.g. a bad merge resolution).
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {
                "_filename": f"{other_id}.yaml",
                "document": spec_id,
                "scope": "backlog",
                "kind": "execution",
                "source": "manual",
                "added": "2026-01-01",
                "since": "2026-01-01",
                "reason": "old item",
            },
        ],
    )
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any(f"filename stem must equal document field {spec_id}" in e for e in result.errors)
    assert any("live document appears in both active sprint and backlog" in e for e in result.errors)
    assert any("backlog item is" in w for w in result.warnings)


def test_validate_ledger_reports_malformed_store_files_instead_of_crashing(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    _write_v2_ledger(tmp_path)
    sprints_dir = tmp_path / "decree" / "sprints"
    (sprints_dir / "live" / "SPEC-00000000000000000000000001.yaml").write_text("{invalid: yaml: [")
    (sprints_dir / "closed" / f"{SPRINT_1}.yaml").write_text("- just\n- a list\n")
    monkeypatch.chdir(tmp_path)
    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any("live/SPEC-00000000000000000000000001.yaml: invalid YAML" in e for e in result.errors)
    assert any(f"closed/{SPRINT_1}.yaml: expected mapping" in e for e in result.errors)


def test_v1_ledger_detected_surfaces_migrate_hint(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text("schema: decree.sprints.v1\n")
    monkeypatch.chdir(tmp_path)

    assert lint.run(argparse.Namespace(check_attachments=False)) == 1
    assert "sprint ledger v1 detected; run `decree migrate sprint-ledger`" in capsys.readouterr().out

    assert sprint.run(argparse.Namespace(sprint_action="status")) == 1
    assert "sprint ledger v1 detected; run `decree migrate sprint-ledger`" in capsys.readouterr().err

    assert new.run(_new_args()) == 1
    assert "sprint ledger v1 detected; run `decree migrate sprint-ledger`" in capsys.readouterr().err
    assert list((tmp_path / "decree" / "spec").rglob("*.md")) == []


def test_progress_defaults_to_active_sprint_and_mcp_matches(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    old_spec = "SPEC-00000000000000000000000001"
    active_spec = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, old_spec, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Old\n", date="2026-01-01")
    _write_doc(tmp_path, active_spec, "spec", "draft", "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {
                "document": active_spec,
                "scope": "active",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
            },
        ],
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


def test_progress_default_scope_excludes_resolved_items_but_active_sprint_id_includes_them(
    tmp_path, monkeypatch, capsys
) -> None:
    _write_config(tmp_path)
    done_spec = "SPEC-00000000000000000000000001"
    open_spec = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, done_spec, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_doc(tmp_path, open_spec, "spec", "draft", "## Acceptance Criteria\n\n- [x] Done\n- [ ] Todo\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": done_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {"document": open_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    complete_item(done_spec)

    assert progress.run(_progress_args()) == 0
    default_payload = json.loads(capsys.readouterr().out)
    assert default_payload["document_count"] == 1
    assert default_payload["documents"][0]["doc_id"] == open_spec

    assert progress.run(_progress_args(sprint=SPRINT_1)) == 0
    sprint_payload = json.loads(capsys.readouterr().out)
    assert sprint_payload["document_count"] == 2
    assert {doc["doc_id"] for doc in sprint_payload["documents"]} == {done_spec, open_spec}


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
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {"document": prd_id, "scope": "active", "kind": "planning", "source": "manual", "added": "2026-06-26"},
        ],
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
    _write_v2_ledger(
        tmp_path,
        live=[
            {
                "document": active_spec,
                "scope": "active",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
            },
        ],
    )
    monkeypatch.chdir(tmp_path)

    assessment = ddd.assess()

    assert assessment.scope.startswith("active sprint")
    assert assessment.documents == {"adr": 1, "prd": 1, "spec": 1}
    assert assessment.progress["completed"] == 1
    assert assessment.progress["total"] == 2
    assert assessment.suggested_actions[0].target_id == active_spec


def test_rollover_covers_open_items_only_and_folds_resolved_outcomes_verbatim(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    done_spec = "SPEC-00000000000000000000000001"
    open_spec = "SPEC-00000000000000000000000002"
    _write_doc(tmp_path, done_spec, "spec", "approved", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_doc(tmp_path, open_spec, "spec", "approved", "## Acceptance Criteria\n\n- [x] Also done\n")
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": done_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
            {"document": open_spec, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    monkeypatch.chdir(tmp_path)
    complete_item(done_spec, commits=("cafe123",), today="2026-07-01")
    resolved_outcome = load_view().live[done_spec].outcome

    both = tmp_path / "both.yaml"
    both.write_text(f"outcomes:\n  {done_spec}:\n    kind: completed\n  {open_spec}:\n    kind: completed\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(both))) == 1
    assert f"outcomes include document(s) not open in active sprint: {done_spec}" in capsys.readouterr().err

    empty = tmp_path / "empty.yaml"
    empty.write_text("outcomes: {}\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(empty))) == 1
    assert f"outcomes missing active sprint item(s): {open_spec}" in capsys.readouterr().err

    open_only = tmp_path / "open-only.yaml"
    open_only.write_text(f"outcomes:\n  {open_spec}:\n    kind: completed\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(open_only))) == 0

    view = load_view()
    assert view.state.active is not None
    assert view.state.active["name"] == "Sprint 2"
    assert view.live == {}
    folded = {item.document: item for item in view.closed[0].items}
    assert folded[done_spec].outcome == resolved_outcome  # pre-resolved outcome folds verbatim
    assert folded[done_spec].outcome is not None
    assert folded[done_spec].outcome["at"] == "2026-07-01"
    assert folded[done_spec].outcome["evidence"] == {"commits": ["cafe123"]}
    assert folded[open_spec].outcome is not None
    assert folded[open_spec].outcome["kind"] == "completed"
    assert folded[open_spec].outcome["evidence"] == {"commits": []}


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
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: completed\n")
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    view = load_view()
    assert view.state.state == "active"
    assert view.state.active is not None
    assert view.state.active["name"] == "Sprint 2"
    assert view.closed[0].status == "closed"
    assert view.closed[0].items[0].outcome["snapshot"]["primary_done"] == 1

    spec_path.write_text(spec_path.read_text().replace("- [x] Done", "- [ ] Done"))
    view = load_view()
    assert view.closed[0].items[0].outcome["snapshot"]["primary_done"] == 1


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
    _write_v2_ledger(
        tmp_path,
        live=[
            {"document": spec_id, "scope": "active", "kind": "execution", "source": "manual", "added": "2026-06-26"},
        ],
    )
    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: carried_over\n")
    monkeypatch.chdir(tmp_path)

    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 1

    outcomes.write_text(f"outcomes:\n  {spec_id}:\n    kind: carried_over\n    reason: larger than expected\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    view = load_view()
    assert view.state.active is not None
    carryover = view.live[spec_id]
    assert carryover.scope == "active"
    assert carryover.source == "carryover"
    assert carryover.carryover_from == SPRINT_1
    assert view.closed[0].items[0].outcome["to_sprint"] == view.state.active["id"]


def test_init_and_rollover_acquire_ledger_lock(tmp_path, monkeypatch) -> None:
    fcntl = pytest.importorskip("fcntl")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(fcntl, "flock", lambda fd, operation: calls.append(operation))

    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0
    assert calls == [fcntl.LOCK_EX]
    assert (tmp_path / ".decree" / "sprints.lock").exists()

    calls.clear()
    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text("outcomes: {}\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    assert calls == [fcntl.LOCK_EX]


def _backlog_ledger(tmp_path, target: str) -> None:
    _write_v2_ledger(
        tmp_path,
        live=[
            {
                "document": target,
                "scope": "backlog",
                "kind": "execution",
                "source": "manual",
                "added": "2026-06-26",
                "since": "2026-06-26",
                "reason": "next sprint",
            },
        ],
    )


def test_drop_removes_a_backlog_item(tmp_path, monkeypatch) -> None:
    # A backlog item must be droppable — e.g. work that shipped and reached a
    # terminal status, which cannot remain live sprint membership.
    _write_config(tmp_path)
    target = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, target, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Later\n")
    _backlog_ledger(tmp_path, target)
    monkeypatch.chdir(tmp_path)

    updated = drop_item(target, reason="shipped; no longer sprint-planned")

    assert updated.outcome is not None
    assert updated.outcome["kind"] == "dropped"


def test_complete_still_rejects_a_backlog_item(tmp_path, monkeypatch) -> None:
    # Completing work remains an active-sprint concept; backlog stays rejected.
    _write_config(tmp_path)
    target = "SPEC-00000000000000000000000001"
    _write_doc(tmp_path, target, "spec", "draft", "## Acceptance Criteria\n\n- [x] Done\n")
    _backlog_ledger(tmp_path, target)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SprintLedgerError):
        complete_item(target)
