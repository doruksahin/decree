"""Generate Mermaid diagrams from document metadata.

Writes directly to each type's index.md, preserving hand-authored content
above the GENERATED marker.
"""

import argparse

from decree.commands.index import GRAPH_MARKER
from decree.log import error, info, success

_LEGACY_MARKER = "<!-- GENERATED:adr-graph — do not edit below this line -->"

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


def graph_json() -> dict:
    """Assemble the full decision graph as JSON: documents + reference edges.

    A stable, ULID-aware machine contract for external consumers (e.g. an editor
    or app that renders the corpus). Each document carries its id, type, clean
    title, project-relative path, and the ids it references; ``edges`` are the
    valid cross-document references (a reference whose target is not a known
    document id is dropped, mirroring graph rendering). Pure read; touches no
    index.md.
    """
    from decree.config import get_project_root, load_doc_types
    from decree.parser import load_all

    root = get_project_root()
    loaded: list[tuple[str, object]] = []
    for dt in load_doc_types():
        type_dir = root / dt.dir
        if not type_dir.exists():
            continue
        for doc in load_all(doc_type=dt):
            loaded.append((dt.name, doc))

    known_ids = {doc.doc_id for _, doc in loaded}
    documents: list[dict] = []
    edges: list[dict] = []
    for type_name, doc in loaded:
        try:
            rel = str(doc.path.relative_to(root))
        except ValueError:
            rel = str(doc.path)
        title = doc.title
        id_prefix = f"{doc.doc_id} "
        if title.startswith(id_prefix):
            title = title[len(id_prefix) :]
        refs = list(doc.meta.references or [])
        documents.append(
            {
                "id": doc.doc_id,
                "type": type_name,
                "title": title,
                "relative_path": rel,
                "references": refs,
            }
        )
        for ref in refs:
            if ref in known_ids:
                edges.append({"from": doc.doc_id, "to": ref})

    documents.sort(key=lambda d: d["id"])
    edges.sort(key=lambda e: (e["from"], e["to"]))
    return {"documents": documents, "edges": edges}


def run(args: argparse.Namespace | None = None) -> int:
    prefix = "graph"
    if getattr(args, "json", False):
        import json

        print(json.dumps(graph_json(), indent=2, sort_keys=False))
        return 0

    from decree.config import get_project_root, load_doc_types
    from decree.parser import load_all

    doc_types = load_doc_types()
    total_diagrams = 0

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue

        docs = load_all(doc_type=dt)
        info(prefix, f"loaded {len(docs)} {dt.name.upper()} documents")

        if not docs:
            info(prefix, f"no {dt.name.upper()} documents found — skipping")
            continue

        index_file = type_dir / "index.md"
        if not index_file.exists():
            error(prefix, f"{index_file} not found — run `decree index` first")
            return 1

        content = index_file.read_text()

        # Find the marker — support both current and legacy names
        if GRAPH_MARKER in content:
            marker = GRAPH_MARKER
        elif _LEGACY_MARKER in content:
            marker = _LEGACY_MARKER
        else:
            # Index was generated before markers were added — regenerate it
            info(prefix, f"marker not found in {index_file} — running `decree index`")
            from decree.commands.index import run as index_run

            index_run(None)
            content = index_file.read_text()
            marker = GRAPH_MARKER

        header = content[: content.index(marker)]

        # Generate diagrams
        parts = [GRAPH_MARKER, ""]

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
