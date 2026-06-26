"""Generate a self-contained HTML board from decree documents and sprints."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mistletoe
from jinja2 import Environment, FileSystemLoader, select_autoescape

from decree.buckets import bucket_for_path
from decree.checklists import parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root
from decree.log import error, info, success
from decree.parser import DocDocument, load_all_types
from decree.sprints import SprintLedgerError, load_ledger, sprint_mode_enabled

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "html_board.html.j2"

COLUMNS = (
    ("planning", "Planning"),
    ("todo", "Todo"),
    ("in_progress", "In progress"),
    ("ready", "Ready"),
    ("done", "Done"),
    ("carried_over", "Carried over"),
    ("deferred", "Deferred"),
    ("dropped", "Dropped"),
    ("superseded", "Superseded"),
)


def run(args: argparse.Namespace) -> int:
    prefix = "generate-html"
    root = get_project_root()
    output = _resolve_output(root, getattr(args, "output", None))

    try:
        docs = load_all_types()
        payload = _board_payload(docs, selected_sprint_id=getattr(args, "sprint", None), root=root)
    except (SprintLedgerError, ValueError) as e:
        error(prefix, str(e))
        return 1
    except Exception as e:
        error(prefix, f"failed to build board payload: {e}")
        return 1

    template = Environment(
        loader=FileSystemLoader(str(TEMPLATE_PATH.parent)),
        autoescape=select_autoescape(("html", "j2")),
    ).get_template(TEMPLATE_PATH.name)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    html = template.render(payload=payload, payload_json=payload_json)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html.rstrip() + "\n")
    info(prefix, f"wrote {output}")
    print(output)
    success("html board generated")
    return 0


def _resolve_output(root: Path, value: str | None) -> Path:
    raw = value or "decree-board.html"
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path


def _board_payload(docs: list[DocDocument], *, selected_sprint_id: str | None, root: Path) -> dict[str, Any]:
    by_id = {doc.doc_id: doc for doc in docs}
    ledger = load_ledger(root) if sprint_mode_enabled(root) else None
    sprints = []
    backlog: list[dict[str, Any]] = []
    draft_pool: list[dict[str, Any]] = []
    active_sprint_id = None

    if ledger is not None:
        active_sprint_id = ledger.active
        sprints = [_sprint_payload(sprint, by_id, root) for sprint in ledger.sprints]
        backlog = [_item_card(item, by_id, root, default_column="backlog") for item in ledger.backlog]
        draft_pool = [_item_card(item, by_id, root, default_column="draft_pool") for item in ledger.draft_pool]

    available = {sprint["id"] for sprint in sprints}
    if selected_sprint_id is not None and selected_sprint_id not in available:
        raise ValueError(f"sprint not found: {selected_sprint_id}")
    selected = selected_sprint_id or active_sprint_id or (sprints[-1]["id"] if sprints else None)

    return {
        "schema": "decree.board.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "project_root": str(root),
        "selected_sprint_id": selected,
        "columns": [{"id": column_id, "label": label} for column_id, label in COLUMNS],
        "documents": [
            _document_record(doc, root) for doc in sorted(docs, key=lambda item: (item.doc_type.name, item.title))
        ],
        "sprints": sprints,
        "backlog": backlog,
        "draft_pool": draft_pool,
    }


def _sprint_payload(sprint: Any, by_id: dict[str, DocDocument], root: Path) -> dict[str, Any]:
    return {
        "id": sprint.id,
        "name": sprint.name,
        "status": sprint.status,
        "started": sprint.started,
        "closed": sprint.closed,
        "cards": [_item_card(item, by_id, root) for item in sprint.items],
    }


def _item_card(
    item: Any,
    by_id: dict[str, DocDocument],
    root: Path,
    *,
    default_column: str | None = None,
) -> dict[str, Any]:
    doc = by_id.get(item.document)
    progress = _progress_for_doc(doc, root)
    outcome = getattr(item, "outcome", None)
    return {
        "document": item.document,
        "kind": item.kind,
        "source": getattr(item, "source", None),
        "added": getattr(item, "added", None),
        "since": getattr(item, "since", None),
        "reason": getattr(item, "reason", None),
        "carryover_from": getattr(item, "carryover_from", None),
        "outcome": outcome,
        "column": default_column or _column_for(item.kind, progress, outcome),
        "doc": _doc_payload(doc, root),
        "progress": progress,
    }


def _column_for(kind: str, progress: dict[str, Any], outcome: dict[str, Any] | None) -> str:
    if outcome:
        kind_value = str(outcome.get("kind", "")).strip()
        if kind_value == "completed":
            return "done"
        if kind_value in {"carried_over", "deferred", "dropped", "superseded"}:
            return kind_value
    if kind == "planning":
        return "planning"
    primary = progress["primary"]
    if primary["total"] > 0 and primary["done"] == primary["total"]:
        return "ready"
    if primary["done"] > 0:
        return "in_progress"
    return "todo"


def _doc_payload(doc: DocDocument | None, root: Path) -> dict[str, Any]:
    if doc is None:
        return {
            "id": None,
            "type": None,
            "title": "(missing document)",
            "status": "missing",
            "bucket": None,
            "path": None,
            "absolute_path": None,
            "file_url": None,
            "folder_path": None,
            "folder_url": None,
            "references": [],
        }
    absolute_path = doc.path.resolve()
    folder_path = absolute_path.parent
    try:
        rel_path = absolute_path.relative_to(root).as_posix()
    except ValueError:
        rel_path = absolute_path.as_posix()
    type_dir = root / doc.doc_type.dir
    return {
        "id": doc.doc_id,
        "type": doc.doc_type.name,
        "title": doc.title,
        "status": doc.meta.status,
        "bucket": bucket_for_path(doc.path, type_dir),
        "path": rel_path,
        "absolute_path": absolute_path.as_posix(),
        "file_url": absolute_path.as_uri(),
        "folder_path": folder_path.as_posix(),
        "folder_url": folder_path.as_uri(),
        "references": list(doc.meta.references or []),
    }


def _document_record(doc: DocDocument, root: Path) -> dict[str, Any]:
    payload = _doc_payload(doc, root)
    payload["progress"] = _progress_for_doc(doc, root)
    payload["markdown_html"] = mistletoe.markdown(doc.body)
    payload["markdown_source"] = doc.body
    return payload


def _progress_for_doc(doc: DocDocument | None, root: Path) -> dict[str, Any]:
    if doc is None:
        return {
            "primary": {"done": 0, "total": 0, "percent": None},
            "deferred": {"done": 0, "total": 0},
        }
    cfg = load_report_config(root, doc.doc_type.name)
    parsed = parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    percent = round(parsed.primary_done / parsed.primary_total * 100) if parsed.primary_total else None
    return {
        "primary": {"done": parsed.primary_done, "total": parsed.primary_total, "percent": percent},
        "deferred": {"done": parsed.deferred_done, "total": parsed.deferred_total},
    }
