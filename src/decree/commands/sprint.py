"""Manage the sprint ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from decree.log import error, info, success
from decree.parser import find_by_id, load_all_types
from decree.sprints import (
    SprintLedgerError,
    add_to_active_sprint,
    add_to_backlog,
    add_to_draft_pool,
    init_ledger,
    load_ledger,
    load_outcomes_file,
    pause_ledger,
    resume_ledger,
    rollover_ledger,
    sprint_mode_enabled,
)


def run(args: argparse.Namespace) -> int:
    action = args.sprint_action
    try:
        if action == "init":
            ledger = init_ledger(args.name)
            active = ledger.active_sprint
            assert active is not None
            info("sprint", f"initialized {active.id}: {active.name}")
            success("sprint mode enabled")
            return 0
        if action == "status":
            return _status()
        if action == "pause":
            ledger = pause_ledger(args.reason)
            reason = ledger.paused["reason"] if ledger.paused else ""
            info("sprint", f"paused: {reason}")
            success("sprint mode paused")
            return 0
        if action == "resume":
            ledger = resume_ledger(args.name)
            active = ledger.active_sprint
            assert active is not None
            info("sprint", f"active {active.id}: {active.name}")
            success("sprint mode resumed")
            return 0
        if action == "add":
            kind = _resolve_kind(args.document, args.kind)
            ledger = add_to_active_sprint(args.document, kind=kind, source="manual")
            active = ledger.active_sprint
            assert active is not None
            info("sprint", f"added {args.document.upper()} to {active.id} as {kind}")
            success("sprint item added")
            return 0
        if action == "backlog":
            kind = _resolve_kind(args.document, args.kind)
            add_to_backlog(args.document, kind=kind, reason=args.reason, source="manual")
            info("sprint", f"backlogged {args.document.upper()} as {kind}")
            success("backlog item added")
            return 0
        if action in {"draft-pool", "draft"}:
            kind = _resolve_kind(args.document, args.kind)
            add_to_draft_pool(args.document, kind=kind, reason=args.reason)
            info("sprint", f"added {args.document.upper()} to draft pool as {kind}")
            success("draft-pool item added")
            return 0
        if action == "rollover":
            outcomes = load_outcomes_file(Path(args.outcomes))
            docs = load_all_types()
            ledger = rollover_ledger(args.name, outcomes, docs)
            active = ledger.active_sprint
            assert active is not None
            info("sprint", f"rolled over to {active.id}: {active.name}")
            success("sprint rolled over")
            return 0
        error("sprint", f"unknown sprint action: {action}")
        return 1
    except SprintLedgerError as e:
        error("sprint", str(e))
        return 1
    except Exception as e:
        error("sprint", f"failed: {e}")
        return 1


def _status() -> int:
    if not sprint_mode_enabled():
        info("sprint", "sprint mode disabled")
        print("Sprint mode: disabled")
        return 0
    ledger = load_ledger()
    print(f"Sprint mode: {ledger.state}")
    if ledger.active_sprint:
        active = ledger.active_sprint
        print(f"Active: {active.id} {active.name} ({len(active.items)} items)")
        _print_items("Tasks", [item for item in active.items if item.kind == "execution" and item.outcome is None])
        _print_items("Planning", [item for item in active.items if item.kind == "planning" and item.outcome is None])
    if ledger.paused:
        print(f"Paused since: {ledger.paused.get('since')}")
        print(f"Reason: {ledger.paused.get('reason')}")
    print(f"Backlog: {len(ledger.backlog)} items")
    print(f"Draft pool: {len(ledger.draft_pool)} items")
    success("sprint status reported")
    return 0


def _print_items(label: str, items: list) -> None:
    if not items:
        return
    print()
    print(f"{label}:")
    for item in items:
        print(f"  {item.document} ({item.source})")


def _resolve_kind(document: str, requested: str | None) -> str:
    kind = requested or "execution"
    if kind == "execution":
        doc = find_by_id(document)
        if doc.doc_type is None or doc.doc_type.name != "spec":
            raise SprintLedgerError(f"{document.upper()} can only be added as --kind planning")
    return kind
