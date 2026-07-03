"""Tests for `decree migrate sprint-ledger`, v1 detection, and store robustness."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from decree.commands import lint, migrate, new, sprint
from decree.sprints import load_view, validate_ledger

SPRINT_CLOSED = "SPRINT-00000000000000000000000001"
SPRINT_ACTIVE = "SPRINT-00000000000000000000000002"
SPEC_COMPLETED = "SPEC-00000000000000000000000001"
SPEC_CARRY = "SPEC-00000000000000000000000002"
SPEC_FRESH = "SPEC-00000000000000000000000003"
SPEC_BACKLOG = "SPEC-00000000000000000000000004"
SPEC_DRAFT = "SPEC-00000000000000000000000005"
SPEC_MISMATCH = "SPEC-00000000000000000000000007"

V1_DETECTED = "sprint ledger v1 detected; run `decree migrate sprint-ledger`"

COMPLETED_OUTCOME = {
    "kind": "completed",
    "at": "2026-06-15",
    "evidence": {"commits": ["abc1234"]},
    "snapshot": {
        "status": "implemented",
        "primary_done": 1,
        "primary_total": 1,
        "deferred_done": 0,
        "deferred_total": 0,
    },
}
CARRIED_OVER_OUTCOME = {
    "kind": "carried_over",
    "at": "2026-06-15",
    "reason": "larger than expected",
    "to_sprint": SPRINT_ACTIVE,
    "snapshot": {
        "status": "approved",
        "primary_done": 0,
        "primary_total": 1,
        "deferred_done": 0,
        "deferred_total": 0,
    },
}


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


def _migrate_args(**overrides):
    data = {"dry_run": False, "apply": False, "project": None}
    data.update(overrides)
    return argparse.Namespace(**data)


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _write_v1_project(root: Path) -> None:
    """Dogfood-shaped v1 monolith: one closed sprint (carried_over + completed),
    an active sprint with a carryover and a fresh item, backlog, and draft pool."""
    _write_config(root)
    _write_doc(root, SPEC_COMPLETED, "spec", "implemented", "## Acceptance Criteria\n\n- [x] Done\n")
    _write_doc(root, SPEC_CARRY, "spec", "approved", "## Acceptance Criteria\n\n- [ ] Todo\n")
    _write_doc(root, SPEC_FRESH, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Todo\n")
    _write_doc(root, SPEC_BACKLOG, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Later\n")
    _write_doc(root, SPEC_DRAFT, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Someday\n")
    (root / "decree" / "sprints").mkdir()
    (root / "decree" / "sprints" / "ledger.yaml").write_text(
        f"""\
schema: decree.sprints.v1
mode: enabled
state: active
active: {SPRINT_ACTIVE}
paused: null
sprints:
  - id: {SPRINT_CLOSED}
    name: Sprint 1
    status: closed
    started: 2026-06-01
    closed: 2026-06-15
    items:
      - document: {SPEC_COMPLETED}
        kind: execution
        source: new
        added: 2026-06-02
        outcome:
          kind: completed
          at: 2026-06-15
          evidence:
            commits:
              - abc1234
          snapshot:
            status: implemented
            primary_done: 1
            primary_total: 1
            deferred_done: 0
            deferred_total: 0
      - document: {SPEC_CARRY}
        kind: execution
        source: manual
        added: 2026-06-03
        outcome:
          kind: carried_over
          at: 2026-06-15
          reason: larger than expected
          to_sprint: {SPRINT_ACTIVE}
          snapshot:
            status: approved
            primary_done: 0
            primary_total: 1
            deferred_done: 0
            deferred_total: 0
  - id: {SPRINT_ACTIVE}
    name: Sprint 2
    status: active
    started: 2026-06-15
    closed: null
    items:
      - document: {SPEC_CARRY}
        kind: execution
        source: carryover
        added: 2026-06-15
        carryover_from: {SPRINT_CLOSED}
      - document: {SPEC_FRESH}
        kind: execution
        source: new
        added: 2026-06-16
backlog:
  - document: {SPEC_BACKLOG}
    kind: execution
    source: manual
    added: 2026-06-10
    since: 2026-06-10
    reason: deprioritized for the carryover
    review_after: 2099-01-01
draft_pool:
  - document: {SPEC_DRAFT}
    kind: execution
    added: 2026-06-11
    reason: speculative idea
"""
    )


def test_migrate_apply_converts_dogfood_shaped_v1_ledger(tmp_path, monkeypatch) -> None:
    _write_v1_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert migrate.migrate_sprint_ledger_run(_migrate_args(apply=True)) == 0

    sprints_dir = tmp_path / "decree" / "sprints"
    assert not (sprints_dir / "ledger.yaml").exists()
    assert (sprints_dir / "state.yaml").exists()
    assert sorted(path.name for path in (sprints_dir / "live").glob("*.yaml")) == sorted(
        f"{doc}.yaml" for doc in (SPEC_CARRY, SPEC_FRESH, SPEC_BACKLOG, SPEC_DRAFT)
    )
    assert [path.name for path in (sprints_dir / "closed").glob("*.yaml")] == [f"{SPRINT_CLOSED}.yaml"]

    view = load_view(tmp_path)
    assert view.state.state == "active"
    assert view.state.active == {"id": SPRINT_ACTIVE, "name": "Sprint 2", "started": "2026-06-15"}
    assert view.state.paused is None

    carry = view.live[SPEC_CARRY]
    assert (carry.scope, carry.kind, carry.source, carry.added) == ("active", "execution", "carryover", "2026-06-15")
    assert carry.carryover_from == SPRINT_CLOSED
    assert (carry.since, carry.reason, carry.review_after, carry.outcome) == (None, None, None, None)

    fresh = view.live[SPEC_FRESH]
    assert (fresh.scope, fresh.kind, fresh.source, fresh.added) == ("active", "execution", "new", "2026-06-16")
    assert (fresh.carryover_from, fresh.outcome) == (None, None)

    backlog = view.live[SPEC_BACKLOG]
    assert (backlog.scope, backlog.kind, backlog.source) == ("backlog", "execution", "manual")
    assert backlog.added == "2026-06-10"
    assert backlog.since == "2026-06-10"
    assert backlog.reason == "deprioritized for the carryover"
    assert backlog.review_after == "2099-01-01"
    assert backlog.outcome is None

    draft = view.live[SPEC_DRAFT]
    assert (draft.scope, draft.kind, draft.added) == ("draft_pool", "execution", "2026-06-11")
    assert draft.reason == "speculative idea"
    assert draft.outcome is None

    assert len(view.closed) == 1
    record = view.closed[0]
    assert (record.id, record.name, record.status) == (SPRINT_CLOSED, "Sprint 1", "closed")
    assert (record.started, record.closed) == ("2026-06-01", "2026-06-15")
    assert [item.document for item in record.items] == [SPEC_COMPLETED, SPEC_CARRY]
    completed = record.items[0]
    assert (completed.kind, completed.source, completed.added) == ("execution", "new", "2026-06-02")
    assert completed.carryover_from is None
    assert completed.outcome == COMPLETED_OUTCOME
    carried = record.items[1]
    assert (carried.kind, carried.source, carried.added) == ("execution", "manual", "2026-06-03")
    assert carried.outcome == CARRIED_OVER_OUTCOME

    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())
    assert result.errors == ()
    assert result.warnings == ()


def test_migrate_dry_run_prints_plan_and_writes_nothing(tmp_path, monkeypatch, capsys) -> None:
    _write_v1_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    before = _tree_snapshot(tmp_path)

    assert migrate.migrate_sprint_ledger_run(_migrate_args(dry_run=True)) == 0

    out = capsys.readouterr().out
    assert "migrate sprint-ledger: 1 closed sprint(s), 4 live item(s), state: active" in out
    assert "create decree/sprints/state.yaml" in out
    assert f"create decree/sprints/live/{SPEC_CARRY}.yaml" in out
    assert f"create decree/sprints/live/{SPEC_FRESH}.yaml" in out
    assert f"create decree/sprints/live/{SPEC_BACKLOG}.yaml" in out
    assert f"create decree/sprints/live/{SPEC_DRAFT}.yaml" in out
    assert f"create decree/sprints/closed/{SPRINT_CLOSED}.yaml" in out
    assert "remove decree/sprints/ledger.yaml" in out
    assert _tree_snapshot(tmp_path) == before


def test_migrate_without_v1_ledger_exits_2(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert migrate.migrate_sprint_ledger_run(_migrate_args(apply=True)) == 2
    assert "no v1 sprint ledger found at decree/sprints/ledger.yaml; nothing to migrate" in capsys.readouterr().err

    # Guards apply to --dry-run too.
    assert migrate.migrate_sprint_ledger_run(_migrate_args(dry_run=True)) == 2


def test_migrate_with_v2_already_present_exits_2(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0

    assert migrate.migrate_sprint_ledger_run(_migrate_args(apply=True)) == 2
    message = "sprint ledger v2 already present at decree/sprints/state.yaml; nothing to migrate"
    assert message in capsys.readouterr().err


def test_migrate_second_apply_exits_2(tmp_path, monkeypatch, capsys) -> None:
    _write_v1_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert migrate.migrate_sprint_ledger_run(_migrate_args(apply=True)) == 0
    assert migrate.migrate_sprint_ledger_run(_migrate_args(apply=True)) == 2
    assert "sprint ledger v2 already present" in capsys.readouterr().err


def test_v1_ledger_detection_blocks_lint_sprint_status_and_new_spec(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path)
    (tmp_path / "decree" / "sprints").mkdir()
    (tmp_path / "decree" / "sprints" / "ledger.yaml").write_text(
        "schema: decree.sprints.v1\nmode: enabled\nstate: active\n"
    )
    monkeypatch.chdir(tmp_path)

    assert lint.run(argparse.Namespace(check_attachments=False)) == 1
    assert V1_DETECTED in capsys.readouterr().out

    assert sprint.run(argparse.Namespace(sprint_action="status")) == 1
    assert V1_DETECTED in capsys.readouterr().err

    assert new.run(_new_args()) == 1
    assert V1_DETECTED in capsys.readouterr().err
    assert list((tmp_path / "decree" / "spec").rglob("*.md")) == []


def test_validate_ledger_reports_malformed_and_mismatched_live_files(tmp_path, monkeypatch) -> None:
    _write_config(tmp_path)
    _write_doc(tmp_path, SPEC_MISMATCH, "spec", "draft", "## Acceptance Criteria\n\n- [ ] Todo\n")
    monkeypatch.chdir(tmp_path)
    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0

    live_dir = tmp_path / "decree" / "sprints" / "live"
    malformed = "SPEC-00000000000000000000000009.yaml"
    (live_dir / malformed).write_text("- not\n- a mapping\n")
    mismatched = "SPEC-00000000000000000000000008.yaml"
    (live_dir / mismatched).write_text(
        f"document: {SPEC_MISMATCH}\nscope: active\nkind: execution\nsource: manual\nadded: '2026-07-01'\n"
    )

    from decree.parser import load_all_types

    result = validate_ledger(tmp_path, load_all_types())

    assert any(f"decree/sprints/live/{malformed}: expected mapping" in e for e in result.errors)
    mismatch_message = f"decree/sprints/live/{mismatched}: filename stem must equal document field {SPEC_MISMATCH}"
    assert any(mismatch_message in e for e in result.errors)


def test_init_and_rollover_acquire_sprint_directory_lock(tmp_path, monkeypatch) -> None:
    fcntl = pytest.importorskip("fcntl")
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    calls: list[int] = []
    real_flock = fcntl.flock

    def recording_flock(fd, operation):
        calls.append(operation)
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", recording_flock)

    assert sprint.run(argparse.Namespace(sprint_action="init", name="Sprint 1")) == 0
    assert (tmp_path / ".decree" / "sprints.lock").exists()
    assert calls.count(fcntl.LOCK_EX) == 1

    outcomes = tmp_path / "outcomes.yaml"
    outcomes.write_text("outcomes: {}\n")
    assert sprint.run(argparse.Namespace(sprint_action="rollover", name="Sprint 2", outcomes=str(outcomes))) == 0
    assert calls.count(fcntl.LOCK_EX) == 2
