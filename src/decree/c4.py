"""C4 architecture validation and diagram generation.

Opt-in module: activated when a doc type has [types.*.c4] configured.
Validates hierarchy (parent), dependencies (depends-on), field presence,
and generates Mermaid C4Container diagrams.

See: decree/spec/001-c4-validation-and-diagram-generation.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parser import DocDocument


@dataclass(frozen=True)
class C4Config:
    """Configuration for C4 architecture support on a doc type."""

    enabled: bool
    id_field: str = "id"
    levels: tuple[str, ...] = ("system", "container", "component")


# ── Validation ───────────────────────────────────────────────


def validate_c4(docs: list[DocDocument], c4_config: C4Config) -> list[str]:
    """Validate C4 metadata across all docs of a C4-enabled type.

    Checks:
    1. Required field presence (id, c4_type, c4_name)
    2. c4_type is one of configured levels
    3. No duplicate C4 ids
    4. parent resolves to another doc's C4 id
    5. depends-on entries resolve to other doc C4 ids

    Dead/superseded docs are filtered out before validation.
    """
    if not c4_config.enabled:
        return []

    errors: list[str] = []

    # Filter out dead docs
    alive = [d for d in docs if d.doc_type is None or d.meta.status not in d.doc_type.warn_on_reference]

    # Extract C4 metadata from raw frontmatter
    c4_docs: list[tuple[DocDocument, dict]] = []
    for doc in alive:
        raw = _get_raw_metadata(doc)
        c4_id = raw.get(c4_config.id_field)

        # Check required fields
        missing = []
        if not c4_id:
            missing.append(c4_config.id_field)
        if not raw.get("c4_type"):
            missing.append("c4_type")
        if not raw.get("c4_name"):
            missing.append("c4_name")

        if missing:
            errors.append(f"C4: {doc.doc_id}: missing required field(s): {', '.join(missing)}")
            continue

        # Check c4_type validity
        c4_type = raw["c4_type"]
        if c4_type not in c4_config.levels:
            errors.append(
                f"C4: {doc.doc_id} ({c4_id}): invalid c4_type '{c4_type}'. "
                f"Must be one of: {', '.join(c4_config.levels)}"
            )

        c4_docs.append((doc, raw))

    # Build C4 id index
    ids_seen: dict[str, str] = {}  # c4_id → doc_id
    for doc, raw in c4_docs:
        c4_id = raw[c4_config.id_field]
        if c4_id in ids_seen:
            errors.append(f"C4: duplicate id '{c4_id}' in {doc.doc_id} and {ids_seen[c4_id]}")
        else:
            ids_seen[c4_id] = doc.doc_id

    # Validate parent and depends-on references
    for doc, raw in c4_docs:
        c4_id = raw[c4_config.id_field]

        parent = raw.get("parent")
        if parent and parent not in ids_seen:
            errors.append(f"C4: {doc.doc_id} ({c4_id}): parent '{parent}' not found")

        depends_on = raw.get("depends-on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        for dep in depends_on:
            if dep not in ids_seen:
                errors.append(f"C4: {doc.doc_id} ({c4_id}): depends-on '{dep}' not found")

    return errors


# ── Diagram generation ───────────────────────────────────────


def generate_c4_container(docs: list[DocDocument], c4_config: C4Config) -> str | None:
    """Generate a Mermaid C4Container diagram.

    Groups containers by system parent. Shows depends-on edges.
    Returns None if no C4 docs found.
    """
    if not c4_config.enabled:
        return None

    # Filter out dead docs and extract metadata
    alive = [d for d in docs if d.doc_type is None or d.meta.status not in d.doc_type.warn_on_reference]

    c4_nodes: list[tuple[DocDocument, dict]] = []
    for doc in alive:
        raw = _get_raw_metadata(doc)
        if raw.get(c4_config.id_field) and raw.get("c4_type"):
            c4_nodes.append((doc, raw))

    if not c4_nodes:
        return None

    # Separate systems and containers/components
    systems = [(d, r) for d, r in c4_nodes if r["c4_type"] == "system"]
    non_systems = [(d, r) for d, r in c4_nodes if r["c4_type"] != "system"]

    # Build parent → children mapping
    children_of: dict[str, list[tuple[DocDocument, dict]]] = {}
    orphans: list[tuple[DocDocument, dict]] = []
    for doc, raw in non_systems:
        parent = raw.get("parent", "")
        if parent:
            children_of.setdefault(parent, []).append((doc, raw))
        else:
            orphans.append((doc, raw))

    lines = ["C4Container"]
    lines.append("    title Architecture — C4 Container View")
    lines.append("")

    # Render each system as a boundary
    for _, sys_raw in systems:
        sys_id = sys_raw[c4_config.id_field]
        sys_name = sys_raw.get("c4_name", sys_id)
        lines.append(f'    System_Boundary({_mermaid_id(sys_id)}, "{sys_name}") {{')
        for _, child_raw in children_of.get(sys_id, []):
            _render_container(lines, child_raw, c4_config, indent=8)
        lines.append("    }")
        lines.append("")

    # Render orphans (no parent)
    for _, raw in orphans:
        _render_container(lines, raw, c4_config, indent=4)

    lines.append("")

    # Render depends-on edges
    for _doc, raw in c4_nodes:
        c4_id = raw[c4_config.id_field]
        depends_on = raw.get("depends-on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        for dep in depends_on:
            lines.append(f'    Rel({_mermaid_id(dep)}, {_mermaid_id(c4_id)}, "depends on")')

    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────


def _get_raw_metadata(doc: DocDocument) -> dict:
    """Get the raw frontmatter dict from a document.

    Returns the raw metadata captured during initial parsing.
    DocFrontmatter only stores decree's own fields; C4 fields
    live in raw_metadata.
    """
    return doc.raw_metadata


def _render_container(lines: list[str], raw: dict, c4_config: C4Config, indent: int) -> None:
    """Render a single C4 container node."""
    c4_id = raw[c4_config.id_field]
    name = raw.get("c4_name", c4_id)
    tech = raw.get("c4_tech", "")
    pad = " " * indent
    lines.append(f'{pad}Container({_mermaid_id(c4_id)}, "{name}", "{tech}")')


def _mermaid_id(raw_id: str) -> str:
    """Convert a C4 id to a valid Mermaid node id."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)
