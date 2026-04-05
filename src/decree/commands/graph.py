"""Generate Mermaid diagrams from ADR metadata.

Writes directly to docs/adr/index.md, preserving hand-authored content
above the GENERATED:adr-graph marker.
"""
import argparse

from decree.config import get_adr_dir
from decree.log import info, error, success, fail
from decree.parser import load_all


MARKER = "<!-- GENERATED:adr-graph — do not edit below this line -->"

STATUS_ICONS = {
    "accepted": "✅",
    "proposed": "📝",
    "rejected": "❌",
    "deprecated": "📦",
    "superseded": "🔄",
}

STATUS_COLORS = {
    "accepted": "#2ea043",
    "proposed": "#d29922",
    "rejected": "#f85149",
    "deprecated": "#8b949e",
    "superseded": "#8b949e",
}


def _timeline(docs: list) -> str:
    """Generate a Mermaid timeline diagram."""
    lines = ["timeline", "    title ADR Decision Timeline"]

    by_date: dict[str, list] = {}
    for doc in docs:
        key = str(doc.meta.date)
        by_date.setdefault(key, []).append(doc)

    for date_str in sorted(by_date):
        lines.append(f"    section {date_str}")
        for doc in by_date[date_str]:
            icon = STATUS_ICONS.get(doc.meta.status, "")
            # Strip ADR-NNNN prefix from title for cleaner display
            short_title = doc.title.replace(f"{doc.adr_id} ", "")
            lines.append(f"        {doc.adr_id} {icon} : {short_title}")

    return "\n".join(lines)


def _supersede_graph(docs: list) -> str | None:
    """Generate a Mermaid flowchart of supersede relationships."""
    edges = []

    for doc in docs:
        if doc.meta.supersedes:
            edges.append((doc.meta.supersedes, doc.adr_id))
        if doc.meta.superseded_by:
            edges.append((doc.adr_id, doc.meta.superseded_by))

    edges = list(set(edges))

    if not edges:
        return None

    lines = ["graph LR"]

    for doc in docs:
        status = doc.meta.status
        color = STATUS_COLORS.get(status, "#8b949e")
        short_title = doc.title.replace(f"{doc.adr_id} ", "")
        if len(short_title) > 40:
            short_title = short_title[:37] + "..."
        lines.append(f'    {doc.adr_id}["{doc.adr_id}<br/>{short_title}"]')
        lines.append(f"    style {doc.adr_id} fill:{color},color:#fff")

    for src, dst in edges:
        lines.append(f"    {src} -->|superseded by| {dst}")

    return "\n".join(lines)


def _status_summary(docs: list) -> str:
    """Generate a Mermaid pie chart of ADR statuses."""
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.meta.status] = counts.get(doc.meta.status, 0) + 1

    lines = ['pie title ADR Status Distribution']
    for status, count in sorted(counts.items()):
        lines.append(f'    "{status}" : {count}')

    return "\n".join(lines)


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "graph"

    docs = load_all(strict=False)
    info(prefix, f"loaded {len(docs)} ADRs")

    if not docs:
        info(prefix, "no ADRs found — nothing to graph")
        return 0

    # Read existing index and preserve content above marker
    index_file = get_adr_dir() / "index.md"
    if not index_file.exists():
        error(prefix, f"{index_file} not found")
        return 1

    content = index_file.read_text()
    if MARKER not in content:
        error(prefix, f"marker not found in {index_file}")
        error(prefix, f"expected: {MARKER}")
        fail("cannot regenerate — add marker to index.md first")
        return 1

    header = content[:content.index(MARKER)]

    # Generate diagrams
    parts = [MARKER, ""]

    timeline = _timeline(docs)
    parts.append("## Decision Timeline\n")
    parts.append(f"```mermaid\n{timeline}\n```\n")
    info(prefix, "generated timeline diagram")

    graph = _supersede_graph(docs)
    if graph:
        parts.append("## Decision Chain\n")
        parts.append(f"```mermaid\n{graph}\n```\n")
        info(prefix, "generated supersede graph")
    else:
        info(prefix, "no supersede relationships — skipping decision chain")

    pie = _status_summary(docs)
    parts.append("## Status Distribution\n")
    parts.append(f"```mermaid\n{pie}\n```\n")
    info(prefix, "generated status distribution")

    # Write back
    index_file.write_text(header + "\n".join(parts))
    info(prefix, f"wrote {index_file}")
    success(f"generated diagrams for {len(docs)} ADRs → {index_file}")
    return 0
