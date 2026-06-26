"""Report progress across all documents by counting checkbox items."""

import argparse
import subprocess

from decree.checklists import count_primary_checkboxes, parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root
from decree.identity import require_doc_id
from decree.log import error, info, success
from decree.parser import load_all_types
from decree.sprints import SprintLedgerError, SprintScope, select_sprint_scope


def _count_checkboxes(body: str) -> tuple[int, int]:
    """Count completed/total primary checkboxes in a markdown body."""
    return count_primary_checkboxes(body)


def _doc_counts(doc) -> tuple[int, int, int, int]:
    """Return primary done/total and deferred done/total for one document."""
    root = get_project_root()
    type_name = doc.doc_type.name if doc.doc_type else "adr"
    cfg = load_report_config(root, type_name)
    parsed = parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    return parsed.primary_done, parsed.primary_total, parsed.deferred_done, parsed.deferred_total


def _bar(done: int, total: int, width: int = 10) -> str:
    """Render a progress bar: ██████░░░░"""
    if total == 0:
        return "░" * width
    filled = round(done / total * width)
    return "█" * filled + "░" * (width - filled)


def _pct(done: int, total: int) -> str:
    """Render percentage string."""
    if total == 0:
        return "  —"
    return f"{done / total * 100:3.0f}%"


def _scope_docs(docs: list, args: argparse.Namespace | None) -> SprintScope:
    if args is None:
        return SprintScope(label="all documents", all_documents=tuple(docs))

    doc_id = getattr(args, "doc", None)
    if doc_id:
        doc_id = require_doc_id(doc_id)
        selected = [d for d in docs if d.doc_id == doc_id]
        if not selected:
            raise ValueError(f"document not found: {doc_id}")
        return SprintScope(label=f"doc {doc_id}", all_documents=tuple(selected))

    chain_id = getattr(args, "chain", None)
    if chain_id:
        chain_id = require_doc_id(chain_id)
        ids = _connected_doc_ids(docs, chain_id)
        if not ids:
            raise ValueError(f"chain root not found: {chain_id}")
        return SprintScope(label=f"chain {chain_id}", all_documents=tuple(d for d in docs if d.doc_id in ids))

    governs = getattr(args, "governs", None)
    if governs:
        selected = [d for d in docs if _doc_governs_path(d, governs)]
        return SprintScope(label=f"governs {governs}", all_documents=tuple(selected))

    if getattr(args, "changed", False):
        base = getattr(args, "base", None)
        if not base:
            raise ValueError("--changed requires --base REF")
        changed_paths = _changed_paths(base)
        root = get_project_root()
        selected = []
        for doc in docs:
            try:
                rel = str(doc.path.relative_to(root))
            except ValueError:
                rel = str(doc.path)
            if rel in changed_paths:
                selected.append(doc)
        return SprintScope(label=f"changed docs since {base}", all_documents=tuple(selected))

    try:
        sprint_scope = select_sprint_scope(docs, args)
    except SprintLedgerError as e:
        raise ValueError(str(e)) from e
    if sprint_scope is not None:
        return sprint_scope
    return SprintScope(label="all documents", all_documents=tuple(docs))


def _connected_doc_ids(docs: list, start_id: str) -> set[str]:
    by_id = {d.doc_id: d for d in docs}
    if start_id not in by_id:
        return set()

    adjacency: dict[str, set[str]] = {d.doc_id: set() for d in docs}
    for d in docs:
        refs = set(d.meta.references or [])
        if d.meta.supersedes:
            refs.add(d.meta.supersedes)
        if d.meta.superseded_by:
            refs.add(d.meta.superseded_by)
        for ref in refs:
            if ref not in adjacency:
                continue
            adjacency[d.doc_id].add(ref)
            adjacency[ref].add(d.doc_id)

    seen = {start_id}
    frontier = [start_id]
    while frontier:
        current = frontier.pop()
        for nxt in adjacency.get(current, set()):
            if nxt in seen:
                continue
            seen.add(nxt)
            frontier.append(nxt)
    return seen


def _doc_governs_path(doc, path: str) -> bool:
    normalized = path.rstrip("/")
    for entry in doc.meta.governs or []:
        governed = entry.split("#", 1)[0].rstrip("/")
        if normalized == governed or normalized.startswith(f"{governed}/"):
            return True
    return False


def _changed_paths(base: str) -> set[str]:
    commands = [
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    changed: set[str] = set()
    for cmd in commands:
        result = subprocess.run(cmd, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"git diff failed for base {base!r}: {detail}")
        changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return changed


def progress_for_scope(
    *,
    doc_id: str | None = None,
    chain_id: str | None = None,
    sprint_id: str | None = None,
    all_sprints: bool = False,
    backlog: bool = False,
    draft_pool: bool = False,
    corpus: bool = False,
    include_context: bool = False,
) -> dict:
    """Structured progress for one doc, a connected chain, or the whole corpus.

    Library counterpart of ``decree progress`` with no stdout — used by the MCP
    ``progress`` tool and any programmatic consumer (e.g. an agent host that
    snapshots acceptance-criteria completion before and after a session).
    Counts primary and deferred checkboxes per document and in aggregate,
    mirroring the ``--doc`` / ``--chain`` scoping of the CLI.

    Args:
        doc_id: Restrict to this single document id (wins over other scopes).
        chain_id: Restrict to every document transitively connected to this id
            via references / supersedes links.
        sprint_id: Restrict to one sprint when sprint mode is enabled.
        all_sprints: Include every sprint item.
        backlog: Include sprint backlog items.
        draft_pool: Include draft-pool items.
        corpus: Force the whole corpus even when sprint mode is enabled.
        include_context: In sprint scopes, include referenced context documents
            in the payload without counting them in aggregate task progress.

    Returns a JSON-serializable dict. Raises ``ValueError`` if a requested id
    is unknown (callers at the protocol boundary convert that to an error dict).
    """
    docs = load_all_types()
    args = argparse.Namespace(
        doc=doc_id,
        chain=chain_id,
        sprint=sprint_id,
        all_sprints=all_sprints,
        backlog=backlog,
        draft_pool=draft_pool,
        corpus=corpus,
        include_context=include_context,
        governs=None,
        changed=False,
        base=None,
    )
    selection = _scope_docs(docs, args)
    counted = _counted_docs(selection)

    documents: list[dict] = []
    context_documents: list[dict] = []
    primary_done = primary_total = deferred_done = deferred_total = 0
    for doc in sorted(counted, key=lambda d: d.doc_id):
        pdone, ptotal, ddone, dtotal = _doc_counts(doc)
        primary_done += pdone
        primary_total += ptotal
        deferred_done += ddone
        deferred_total += dtotal
        documents.append(_document_payload(doc, role=_role_for(selection, doc)))
    for doc in sorted(selection.context, key=lambda d: d.doc_id):
        context_documents.append(_document_payload(doc, role="context"))

    return {
        "scope": selection.label,
        "document_count": len(documents),
        "primary": {
            "done": primary_done,
            "total": primary_total,
            "percent": round(primary_done / primary_total * 100) if primary_total else None,
        },
        "deferred": {"done": deferred_done, "total": deferred_total},
        "documents": documents,
        "context_documents": context_documents,
    }


def _document_payload(doc, *, role: str | None = None) -> dict:
    pdone, ptotal, ddone, dtotal = _doc_counts(doc)
    payload = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "status": doc.meta.status,
        "primary": {
            "done": pdone,
            "total": ptotal,
            "percent": round(pdone / ptotal * 100) if ptotal else None,
        },
        "deferred": {"done": ddone, "total": dtotal},
    }
    if role:
        payload["role"] = role
    return payload


def _counted_docs(selection: SprintScope) -> tuple:
    if selection.all_documents:
        return selection.all_documents
    return selection.tasks + selection.planning


def _role_for(selection: SprintScope, doc) -> str | None:
    if selection.all_documents:
        return None
    if doc in selection.planning:
        return "planning"
    return "task"


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "progress"

    if getattr(args, "json", False):
        import json

        try:
            payload = progress_for_scope(
                doc_id=getattr(args, "doc", None),
                chain_id=getattr(args, "chain", None),
                sprint_id=getattr(args, "sprint", None),
                all_sprints=getattr(args, "all_sprints", False),
                backlog=getattr(args, "backlog", False),
                draft_pool=getattr(args, "draft_pool", False),
                corpus=getattr(args, "corpus", False),
                include_context=getattr(args, "include_context", False),
            )
        except ValueError as e:
            error(prefix, str(e))
            return 1
        print(json.dumps(payload, indent=2, sort_keys=False))
        return 0

    try:
        docs = load_all_types()
        info(prefix, f"loaded {len(docs)} documents")
        selection = _scope_docs(docs, args)
    except ValueError as e:
        error(prefix, str(e))
        return 1
    except Exception as e:
        error(prefix, f"failed to load documents: {e}")
        return 1
    info(prefix, f"scope: {selection.label}")
    docs = list(selection.selected_documents)

    if not docs:
        info(prefix, "no documents found for selected scope")
        success("nothing to report")
        return 0

    total_done = 0
    total_items = 0
    deferred_done = 0
    deferred_items = 0
    counted_docs = list(_counted_docs(selection))
    rows_by_group: list[tuple[str | None, list[tuple[str, str, str, int, int, int, int]]]] = []

    groups = _display_groups(selection)
    for group_name, group_docs, counted in groups:
        rows: list[tuple[str, str, str, int, int, int, int]] = []
        for doc in group_docs:
            done, total, deferred_d, deferred_t = _doc_counts(doc)
            if counted:
                total_done += done
                total_items += total
                deferred_done += deferred_d
                deferred_items += deferred_t
            rows.append((doc.doc_id, doc.title, doc.meta.status, done, total, deferred_d, deferred_t))
        if rows:
            rows_by_group.append((group_name, rows))

    # Calculate column widths
    all_rows = [row for _, rows in rows_by_group for row in rows]
    id_width = max(len(r[0]) for r in all_rows)
    # Strip ID prefix from title for cleaner display
    title_width = min(max(len(r[1].replace(f"{r[0]} ", "")) for r in all_rows), 40)
    status_width = max(len(r[2]) for r in all_rows)

    # Print table
    print(f"Scope: {selection.label}")
    print()
    for group_name, rows in rows_by_group:
        if group_name:
            print(f"{group_name}:")
        for doc_id, title, status, done, total, deferred_d, deferred_t in rows:
            short_title = title.replace(f"{doc_id} ", "")
            if len(short_title) > title_width:
                short_title = short_title[: title_width - 3] + "..."
            bar = _bar(done, total)
            pct = _pct(done, total)
            count = f"({done}/{total} primary)" if total > 0 else ""
            if deferred_t > 0:
                count = f"{count}; deferred {deferred_d}/{deferred_t}".lstrip("; ")
            print(
                f"  {doc_id:<{id_width}}  {short_title:<{title_width}}  {status:<{status_width}}  {bar} {pct} {count}"
            )
        if group_name:
            print()

    # Summary
    print()
    if total_items > 0:
        overall_pct = total_done / total_items * 100
        success(
            f"{total_done}/{total_items} primary items complete "
            f"({overall_pct:.0f}%) across {len(counted_docs)} documents"
        )
    else:
        success(f"{len(counted_docs)} documents, no checkbox items found")
    if deferred_items > 0:
        info(prefix, f"{deferred_done}/{deferred_items} deferred items separated from primary progress")

    if selection.label == "all documents":
        info(
            prefix,
            "use --doc ID, --chain ID, --changed --base REF, --governs PATH, or sprint scope flags to narrow work",
        )

    return 0


def _display_groups(selection: SprintScope) -> list[tuple[str | None, tuple, bool]]:
    if selection.all_documents:
        return [(None, tuple(sorted(selection.all_documents, key=lambda d: d.doc_id)), True)]
    return [
        ("Tasks", tuple(sorted(selection.tasks, key=lambda d: d.doc_id)), True),
        ("Planning", tuple(sorted(selection.planning, key=lambda d: d.doc_id)), True),
        ("Context", tuple(sorted(selection.context, key=lambda d: d.doc_id)), False),
    ]
