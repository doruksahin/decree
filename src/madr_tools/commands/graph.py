"""Generate Mermaid diagrams from ADR metadata."""
import argparse

from madr_tools.log import info, success
from madr_tools.parser import load_all


STATUS_COLORS = {
    "accepted": "#2ea043",
    "proposed": "#d29922",
    "rejected": "#f85149",
    "deprecated": "#8b949e",
    "superseded": "#8b949e",
}

STATUS_ICONS = {
    "accepted": "✅",
    "proposed": "📝",
    "rejected": "❌",
    "deprecated": "📦",
    "superseded": "🔄",
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
            lines.append(f"        {doc.adr_id} {icon} : {doc.title}")

    return "\n".join(lines)


def _supersede_graph(docs: list) -> str | None:
    """Generate a Mermaid flowchart of supersede relationships."""
    edges = []
    nodes = set()

    for doc in docs:
        nodes.add(doc.adr_id)
        if doc.meta.supersedes:
            edges.append((doc.meta.supersedes, doc.adr_id))
        if doc.meta.superseded_by:
            edges.append((doc.adr_id, doc.meta.superseded_by))

    # Deduplicate edges
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

    output_parts = []

    # Timeline
    timeline = _timeline(docs)
    output_parts.append("## Decision Timeline\n")
    output_parts.append(f"```mermaid\n{timeline}\n```\n")
    info(prefix, "generated timeline diagram")

    # Supersede graph
    graph = _supersede_graph(docs)
    if graph:
        output_parts.append("## Decision Chain\n")
        output_parts.append(f"```mermaid\n{graph}\n```\n")
        info(prefix, "generated supersede graph")
    else:
        info(prefix, "no supersede relationships — skipping decision chain")

    # Status pie
    pie = _status_summary(docs)
    output_parts.append("## Status Distribution\n")
    output_parts.append(f"```mermaid\n{pie}\n```\n")
    info(prefix, "generated status distribution")

    print("\n".join(output_parts))
    success(f"generated diagrams for {len(docs)} ADRs")
    return 0
