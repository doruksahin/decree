"""Generate Mermaid diagrams from document metadata.

Writes directly to each type's index.md, preserving hand-authored content
above the GENERATED marker.
"""

import argparse

from decree.log import error, fail, info, success

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


def _timeline(docs: list, doc_type) -> str:
    """Generate a Mermaid timeline diagram."""
    type_upper = doc_type.name.upper()
    lines = ["timeline", f"    title {type_upper} Decision Timeline"]

    by_date: dict[str, list] = {}
    for doc in docs:
        key = str(doc.meta.date)
        by_date.setdefault(key, []).append(doc)

    for date_str in sorted(by_date):
        lines.append(f"    section {date_str}")
        for doc in by_date[date_str]:
            icon = STATUS_ICONS.get(doc.meta.status, "")
            short_title = doc.title.replace(f"{doc.doc_id} ", "")
            lines.append(f"        {doc.doc_id} {icon} : {short_title}")

    return "\n".join(lines)


def _supersede_graph(docs: list) -> str | None:
    """Generate a Mermaid flowchart of supersede relationships."""
    edges = []

    for doc in docs:
        if doc.meta.supersedes:
            edges.append((doc.meta.supersedes, doc.doc_id))
        if doc.meta.superseded_by:
            edges.append((doc.doc_id, doc.meta.superseded_by))

    edges = list(set(edges))

    if not edges:
        return None

    lines = ["graph LR"]

    for doc in docs:
        status = doc.meta.status
        color = STATUS_COLORS.get(status, "#8b949e")
        short_title = doc.title.replace(f"{doc.doc_id} ", "")
        if len(short_title) > 40:
            short_title = short_title[:37] + "..."
        lines.append(f'    {doc.doc_id}["{doc.doc_id}<br/>{short_title}"]')
        lines.append(f"    style {doc.doc_id} fill:{color},color:#fff")

    for src, dst in edges:
        lines.append(f"    {src} -->|superseded by| {dst}")

    return "\n".join(lines)


def _status_summary(docs: list, doc_type) -> str:
    """Generate a Mermaid pie chart of document statuses."""
    type_upper = doc_type.name.upper()
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.meta.status] = counts.get(doc.meta.status, 0) + 1

    lines = [f"pie title {type_upper} Status Distribution"]
    for status, count in sorted(counts.items()):
        lines.append(f'    "{status}" : {count}')

    return "\n".join(lines)


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "graph"
    from decree.config import get_project_root, load_doc_types
    from decree.parser import load_all

    doc_types = load_doc_types()
    total_diagrams = 0

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue

        docs = load_all(strict=False, doc_type=dt)
        info(prefix, f"loaded {len(docs)} {dt.name.upper()} documents")

        if not docs:
            info(prefix, f"no {dt.name.upper()} documents found — skipping")
            continue

        index_file = type_dir / "index.md"
        if not index_file.exists():
            error(prefix, f"{index_file} not found")
            return 1

        content = index_file.read_text()
        if MARKER not in content:
            error(prefix, f"marker not found in {index_file}")
            error(prefix, f"expected: {MARKER}")
            fail("cannot regenerate — add marker to index.md first")
            return 1

        header = content[: content.index(MARKER)]

        # Generate diagrams
        parts = [MARKER, ""]

        timeline = _timeline(docs, dt)
        parts.append("## Decision Timeline\n")
        parts.append(f"```mermaid\n{timeline}\n```\n")
        info(prefix, f"generated timeline for {dt.name}")

        graph = _supersede_graph(docs)
        if graph:
            parts.append("## Decision Chain\n")
            parts.append(f"```mermaid\n{graph}\n```\n")
            info(prefix, f"generated supersede graph for {dt.name}")
        else:
            info(
                prefix,
                f"no supersede relationships for {dt.name} — skipping decision chain",
            )

        pie = _status_summary(docs, dt)
        parts.append("## Status Distribution\n")
        parts.append(f"```mermaid\n{pie}\n```\n")
        info(prefix, f"generated status distribution for {dt.name}")

        # C4 diagram (if configured for this type)
        if dt.c4 and dt.c4.enabled:
            from decree.c4 import generate_c4_container

            c4_diagram = generate_c4_container(docs, dt.c4)
            if c4_diagram:
                parts.append("## C4 Container View\n")
                parts.append(f"```mermaid\n{c4_diagram}\n```\n")
                info(prefix, f"generated C4 container diagram for {dt.name}")

        index_file.write_text(header + "\n".join(parts))
        info(prefix, f"wrote {index_file}")
        total_diagrams += 1

    success(f"generated diagrams for {total_diagrams} type(s)")
    return 0
