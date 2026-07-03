"""Manage the sprint directory store."""

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
    complete_item,
    drop_item,
    init_ledger,
    load_outcomes_file,
    load_view,
    pause_ledger,
    resume_ledger,
    rollover_ledger,
    sprint_mode_enabled,
)


def run(args: argparse.Namespace) -> int:
    action = args.sprint_action
    try:
        if action == "init":
            state = init_ledger(args.name)
            active = state.active or {}
            info("sprint", f"initialized {active.get('id')}: {active.get('name')}")
            success("sprint mode enabled")
            return 0
        if action == "status":
            return _status()
        if action == "pause":
            state = pause_ledger(args.reason)
            reason = state.paused["reason"] if state.paused else ""
            info("sprint", f"paused: {reason}")
            success("sprint mode paused")
            return 0
        if action == "resume":
            state = resume_ledger(args.name)
            active = state.active or {}
            info("sprint", f"active {active.get('id')}: {active.get('name')}")
            success("sprint mode resumed")
            return 0
        if action == "add":
            kind = _resolve_kind(args.document, args.kind)
            item = add_to_active_sprint(args.document, kind=kind, source="manual")
            info("sprint", f"added {item.document} to active sprint as {kind}")
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
        if action == "complete":
            item = complete_item(args.document, commits=tuple(args.commit or ()))
            snapshot = (item.outcome or {}).get("snapshot", {})
            info(
                "sprint",
                f"recorded completed outcome for {item.document} "
                f"(primary {snapshot.get('primary_done', 0)}/{snapshot.get('primary_total', 0)})",
            )
            success("sprint item completed")
            return 0
        if action == "drop":
            item = drop_item(args.document, reason=args.reason)
            reason = (item.outcome or {}).get("reason", "")
            info("sprint", f"recorded dropped outcome for {item.document}: {reason}")
            success("sprint item dropped")
            return 0
        if action == "rollover":
            outcomes = load_outcomes_file(Path(args.outcomes))
            docs = load_all_types()
            state = rollover_ledger(args.name, outcomes, docs)
            active = state.active or {}
            info("sprint", f"rolled over to {active.get('id')}: {active.get('name')}")
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
    view = load_view()
    state = view.state
    print(f"Sprint mode: {state.state}")
    if state.active:
        print(f"Active: {state.active.get('id')} {state.active.get('name')} ({len(view.active_items)} items)")
        open_items = view.active_open_items
        _print_items("Tasks", [item for item in open_items if item.kind == "execution"])
        _print_items("Planning", [item for item in open_items if item.kind == "planning"])
        done_items = view.active_done_items
        if done_items:
            print()
            print("Done (awaiting rollover):")
            for item in done_items:
                kind = (item.outcome or {}).get("kind", "resolved")
                print(f"  {item.document} ({kind})")
    if state.paused:
        print(f"Paused since: {state.paused.get('since')}")
        print(f"Reason: {state.paused.get('reason')}")
    print(f"Backlog: {len(view.backlog_items)} items")
    print(f"Draft pool: {len(view.draft_pool_items)} items")
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
