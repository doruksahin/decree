"""Report progress across all documents by counting checkbox items."""

import argparse
import subprocess

from decree.checklists import count_primary_checkboxes, parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root
from decree.identity import require_doc_id
from decree.log import error, info, success
from decree.parser import load_all_types


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


def _scope_docs(docs: list, args: argparse.Namespace | None) -> tuple[list, str]:
    if args is None:
        return docs, "all documents"

    doc_id = getattr(args, "doc", None)
    if doc_id:
        doc_id = require_doc_id(doc_id)
        selected = [d for d in docs if d.doc_id == doc_id]
        if not selected:
            raise ValueError(f"document not found: {doc_id}")
        return selected, f"doc {doc_id}"

    chain_id = getattr(args, "chain", None)
    if chain_id:
        chain_id = require_doc_id(chain_id)
        ids = _connected_doc_ids(docs, chain_id)
        if not ids:
            raise ValueError(f"chain root not found: {chain_id}")
        return [d for d in docs if d.doc_id in ids], f"chain {chain_id}"

    governs = getattr(args, "governs", None)
    if governs:
        selected = [d for d in docs if _doc_governs_path(d, governs)]
        return selected, f"governs {governs}"

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
        return selected, f"changed docs since {base}"

    return docs, "all documents"


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


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "progress"

    try:
        docs = load_all_types()
        info(prefix, f"loaded {len(docs)} documents")
        docs, scope_label = _scope_docs(docs, args)
    except ValueError as e:
        error(prefix, str(e))
        return 1
    except Exception as e:
        error(prefix, f"failed to load documents: {e}")
        return 1
    info(prefix, f"scope: {scope_label}")

    if not docs:
        info(prefix, "no documents found for selected scope")
        success("nothing to report")
        return 0

    # Group by type
    by_type: dict[str, list] = {}
    for doc in docs:
        type_name = doc.doc_type.name if doc.doc_type else "adr"
        by_type.setdefault(type_name, []).append(doc)

    total_done = 0
    total_items = 0
    deferred_done = 0
    deferred_items = 0
    rows: list[tuple[str, str, str, int, int, int, int]] = []

    for type_name in sorted(by_type):
        for doc in by_type[type_name]:
            done, total, deferred_d, deferred_t = _doc_counts(doc)
            total_done += done
            total_items += total
            deferred_done += deferred_d
            deferred_items += deferred_t
            rows.append((doc.doc_id, doc.title, doc.meta.status, done, total, deferred_d, deferred_t))

    # Calculate column widths
    id_width = max(len(r[0]) for r in rows)
    # Strip ID prefix from title for cleaner display
    title_width = min(max(len(r[1].replace(f"{r[0]} ", "")) for r in rows), 40)
    status_width = max(len(r[2]) for r in rows)

    # Print table
    print(f"Scope: {scope_label}")
    print()
    for doc_id, title, status, done, total, deferred_d, deferred_t in rows:
        short_title = title.replace(f"{doc_id} ", "")
        if len(short_title) > title_width:
            short_title = short_title[: title_width - 3] + "..."
        bar = _bar(done, total)
        pct = _pct(done, total)
        count = f"({done}/{total} primary)" if total > 0 else ""
        if deferred_t > 0:
            count = f"{count}; deferred {deferred_d}/{deferred_t}".lstrip("; ")
        print(f"  {doc_id:<{id_width}}  {short_title:<{title_width}}  {status:<{status_width}}  {bar} {pct} {count}")

    # Summary
    print()
    if total_items > 0:
        overall_pct = total_done / total_items * 100
        success(f"{total_done}/{total_items} primary items complete ({overall_pct:.0f}%) across {len(docs)} documents")
    else:
        success(f"{len(docs)} documents, no checkbox items found")
    if deferred_items > 0:
        info(prefix, f"{deferred_done}/{deferred_items} deferred items separated from primary progress")

    if scope_label == "all documents":
        info(prefix, "use --doc ID, --chain ID, --changed --base REF, or --governs PATH to narrow parallel work")

    return 0
