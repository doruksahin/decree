"""Report progress across all documents by counting checkbox items."""

import argparse
import re

from decree.log import info, success
from decree.parser import load_all_types

# Matches GitHub-flavored markdown checkboxes: - [ ] or - [x] or - [X]
# Also handles * [ ] and indented checkboxes
_CHECKBOX_RE = re.compile(r"^[\s]*[-*]\s+\[([ xX])\]", re.MULTILINE)


def _count_checkboxes(body: str) -> tuple[int, int]:
    """Count (done, total) checkboxes in a markdown body.

    Checkboxes inside fenced code blocks (``` … ```) are skipped — they are
    illustrative examples in documentation, not real progress items. This
    mirrors SPEC-008's gate-2 code-fence rule (see
    `decree.commands.report._parse_checkboxes_by_section`).
    """
    done = 0
    total = 0
    in_code_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        m = _CHECKBOX_RE.match(line)
        if m:
            total += 1
            if m.group(1) in ("x", "X"):
                done += 1
    return done, total


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


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "progress"

    docs = load_all_types(strict=False)
    info(prefix, f"loaded {len(docs)} documents")

    if not docs:
        info(prefix, "no documents found")
        success("nothing to report")
        return 0

    # Group by type
    by_type: dict[str, list] = {}
    for doc in docs:
        type_name = doc.doc_type.name if doc.doc_type else "adr"
        by_type.setdefault(type_name, []).append(doc)

    total_done = 0
    total_items = 0
    rows: list[tuple[str, str, str, int, int]] = []

    for type_name in sorted(by_type):
        for doc in by_type[type_name]:
            done, total = _count_checkboxes(doc.body)
            total_done += done
            total_items += total
            rows.append((doc.doc_id, doc.title, doc.meta.status, done, total))

    # Calculate column widths
    id_width = max(len(r[0]) for r in rows)
    # Strip ID prefix from title for cleaner display
    title_width = min(max(len(r[1].replace(f"{r[0]} ", "")) for r in rows), 40)
    status_width = max(len(r[2]) for r in rows)

    # Print table
    for doc_id, title, status, done, total in rows:
        short_title = title.replace(f"{doc_id} ", "")
        if len(short_title) > title_width:
            short_title = short_title[: title_width - 3] + "..."
        bar = _bar(done, total)
        pct = _pct(done, total)
        count = f"({done}/{total})" if total > 0 else ""
        print(f"  {doc_id:<{id_width}}  {short_title:<{title_width}}  {status:<{status_width}}  {bar} {pct} {count}")

    # Summary
    print()
    if total_items > 0:
        overall_pct = total_done / total_items * 100
        success(f"{total_done}/{total_items} items complete ({overall_pct:.0f}%) across {len(docs)} documents")
    else:
        success(f"{len(docs)} documents, no checkbox items found")

    return 0
