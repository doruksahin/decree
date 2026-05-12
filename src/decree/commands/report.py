"""Completion-report generation.

When a document transitions to a terminal-success status (e.g., SPEC `implemented`),
decree writes a markdown completion report alongside the document. The report
captures the document chain, primary acceptance criteria, deferred / out-of-scope
items, and a generation timestamp.

The "primary vs. deferred" split is extracted here so PRD-003 R6's coherence
gate can later reuse the same section-classification logic.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Default section-title patterns whose checkboxes are tracked as "deferred"
# instead of counting toward primary acceptance-criteria progress.
DEFAULT_DEFERRED_SECTION_PATTERNS = (
    "What this does NOT do",
    "Deferred",
    "Future work",
    "v2 backlog",
    "Out of scope",
)

# A heading line at any level (# … ######) — captures the title text after the hashes.
_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^[\s]*[-*]\s+\[([ xX])\]\s+(.+)$")


@dataclass(frozen=True)
class CheckboxItem:
    text: str
    done: bool
    section: str       # section title this checkbox belongs to (nearest heading above)
    section_level: int  # heading level of `section` (1-6)


@dataclass(frozen=True)
class SectionAcs:
    """All checkbox items in a section."""

    title: str
    level: int
    items: tuple[CheckboxItem, ...]

    @property
    def done(self) -> int:
        return sum(1 for i in self.items if i.done)

    @property
    def total(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class ParsedAcs:
    """Primary vs. deferred sections of a document, with the items inside each."""

    primary: tuple[SectionAcs, ...]
    deferred: tuple[SectionAcs, ...]

    @property
    def primary_done(self) -> int:
        return sum(s.done for s in self.primary)

    @property
    def primary_total(self) -> int:
        return sum(s.total for s in self.primary)

    @property
    def deferred_done(self) -> int:
        return sum(s.done for s in self.deferred)

    @property
    def deferred_total(self) -> int:
        return sum(s.total for s in self.deferred)


# ── Section classification ─────────────────────────────────────


def _section_is_deferred(section_title: str, patterns: tuple[str, ...]) -> bool:
    """Return True if the section title matches any of the deferred-section patterns.

    Matching is case-insensitive substring match — "What this does NOT do (deferred to v2)"
    matches the pattern "What this does NOT do".
    """
    title_lower = section_title.lower()
    return any(p.lower() in title_lower for p in patterns)


def _parse_checkboxes_by_section(body: str, deferred_patterns: tuple[str, ...]) -> ParsedAcs:
    """Walk the body, group checkboxes by their containing section, classify primary vs. deferred."""
    current_section: str = "(preamble)"
    current_level: int = 0
    items_by_section: list[tuple[str, int, list[CheckboxItem]]] = [(current_section, current_level, [])]

    for line in body.splitlines():
        h_match = _HEADING_RE.match(line)
        if h_match:
            hashes, title = h_match.group(1), h_match.group(2).strip()
            level = len(hashes)
            current_section = title
            current_level = level
            items_by_section.append((current_section, current_level, []))
            continue
        c_match = _CHECKBOX_RE.match(line)
        if c_match:
            mark, text = c_match.group(1), c_match.group(2).strip()
            done = mark in ("x", "X")
            items_by_section[-1][2].append(
                CheckboxItem(text=text, done=done, section=current_section, section_level=current_level)
            )

    # Build SectionAcs, dropping empty sections
    primary: list[SectionAcs] = []
    deferred: list[SectionAcs] = []

    # Track which sections are deferred — once a deferred parent is hit, all sub-sections
    # under it stay deferred too (so a "## Deferred" with "### sub-deferred" both count as deferred).
    deferred_ancestor_level: int | None = None
    for title, level, items in items_by_section:
        if deferred_ancestor_level is not None and level <= deferred_ancestor_level:
            deferred_ancestor_level = None  # left the deferred subtree
        is_deferred_by_self = _section_is_deferred(title, deferred_patterns)
        is_deferred_by_ancestor = deferred_ancestor_level is not None
        if is_deferred_by_self and deferred_ancestor_level is None:
            deferred_ancestor_level = level
        if not items:
            continue
        section = SectionAcs(title=title, level=level, items=tuple(items))
        if is_deferred_by_self or is_deferred_by_ancestor:
            deferred.append(section)
        else:
            primary.append(section)

    return ParsedAcs(primary=tuple(primary), deferred=tuple(deferred))


# ── Config reading ─────────────────────────────────────────────


@dataclass(frozen=True)
class CompletionReportConfig:
    enabled: bool
    location_template: str
    deferred_section_patterns: tuple[str, ...]
    require_for_terminal_status: bool


_DEFAULTS = CompletionReportConfig(
    enabled=True,
    # Default location: sibling `reports/` subdirectory so the report file
    # is NOT matched by the type's filename regex (which is non-recursive
    # and applies only to the top-level type_dir).
    location_template="{dir}/reports/{id}.md",
    deferred_section_patterns=DEFAULT_DEFERRED_SECTION_PATTERNS,
    require_for_terminal_status=False,
)


def load_report_config(project_root: Path, type_name: str) -> CompletionReportConfig:
    """Read [types.<type>.completion_report] from decree.toml, falling back to defaults."""
    decree_toml = project_root / "decree.toml"
    if not decree_toml.exists():
        return _DEFAULTS
    with open(decree_toml, "rb") as f:
        data = tomllib.load(f)
    cfg = data.get("types", {}).get(type_name, {}).get("completion_report", {})
    return CompletionReportConfig(
        enabled=cfg.get("enabled", _DEFAULTS.enabled),
        location_template=cfg.get("location", _DEFAULTS.location_template),
        deferred_section_patterns=tuple(cfg.get("deferred_sections", _DEFAULTS.deferred_section_patterns)),
        require_for_terminal_status=cfg.get("require_for_terminal_status", _DEFAULTS.require_for_terminal_status),
    )


# ── Path resolution ───────────────────────────────────────────


def resolve_report_path(doc, project_root: Path, template: str) -> Path:
    """Resolve a report-path template string against a document.

    Available substitution variables:
    - {dir}: the type's directory (e.g., "decree/spec")
    - {id}: the full document ID (e.g., "SPEC-001")
    - {number_str}: the zero-padded number from the filename stem (e.g., "001")
    - {slug}: the slug portion of the filename (e.g., "ddd-cli-completion-report-and-stop-hook")
    """
    stem = doc.path.stem  # e.g., "001-ddd-cli-completion-report-and-stop-hook"
    parts = stem.split("-", 1)
    number_str = parts[0]
    slug = parts[1] if len(parts) > 1 else ""
    dir_str = doc.doc_type.dir if doc.doc_type else doc.path.parent.name
    rendered = template.format(
        dir=dir_str,
        id=doc.doc_id,
        number_str=number_str,
        slug=slug,
    )
    candidate = Path(rendered)
    if candidate.is_absolute():
        return candidate
    return project_root / candidate


# ── Document chain reconstruction ──────────────────────────────


def _build_chain_for(doc, all_docs: list) -> list:
    """Walk up references to find the full PRD → ADR → SPEC chain ending at `doc`.

    Returns the chain as a list ordered from top of chain (e.g., the rooting PRD)
    down to `doc` itself.
    """
    by_id = {d.doc_id: d for d in all_docs}
    chain: list = [doc]
    seen: set = {doc.doc_id}
    cursor = doc
    while True:
        refs = cursor.meta.references or []
        if not refs:
            break
        # Find the first ancestor we can resolve and haven't seen
        next_doc = None
        for ref in refs:
            if ref in seen:
                continue
            if ref in by_id:
                next_doc = by_id[ref]
                break
        if next_doc is None:
            break
        chain.insert(0, next_doc)
        seen.add(next_doc.doc_id)
        cursor = next_doc
    return chain


# ── Report rendering ────────────────────────────────────────────


def _render_report(doc, chain: list, parsed: ParsedAcs, transitioned_to: str, when: datetime) -> str:
    """Render the completion report as markdown."""
    lines: list[str] = []
    lines.append(f"# {doc.doc_id} Completion Report")
    lines.append("")
    lines.append(f"**Document**: `{doc.path}`")
    lines.append(f"**Transitioned to `{transitioned_to}` on**: {when.strftime('%Y-%m-%d')}")
    lines.append(f"**Generated**: {when.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"**Total documents in chain**: {len(chain)}")
    lines.append("")

    # Document chain table
    lines.append("## Document chain")
    lines.append("")
    lines.append("| Type | ID | Status | Title |")
    lines.append("|---|---|---|---|")
    for d in chain:
        type_name = d.doc_type.name.upper() if d.doc_type else "?"
        lines.append(f"| {type_name} | {d.doc_id} | {d.meta.status} | {d.title} |")
    lines.append("")

    # Primary acceptance criteria
    lines.append(f"## Acceptance Criteria — primary ({parsed.primary_done}/{parsed.primary_total})")
    lines.append("")
    if not parsed.primary:
        lines.append("_No primary acceptance criteria found in this document._")
    else:
        for section in parsed.primary:
            lines.append(f"### {section.title} ({section.done}/{section.total})")
            lines.append("")
            for item in section.items:
                mark = "x" if item.done else " "
                lines.append(f"- [{mark}] {item.text}")
            lines.append("")

    # Deferred / out-of-scope
    if parsed.deferred:
        lines.append(f"## Deferred / Out of scope ({parsed.deferred_done}/{parsed.deferred_total})")
        lines.append("")
        for section in parsed.deferred:
            lines.append(f"### {section.title} ({section.done}/{section.total})")
            lines.append("")
            for item in section.items:
                mark = "x" if item.done else " "
                lines.append(f"- [{mark}] {item.text}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_This report was auto-generated by decree on a terminal-status transition._")
    return "\n".join(lines) + "\n"


def generate_report(doc, project_root: Path, transitioned_to: str, all_docs: list | None = None) -> Path | None:
    """Generate a completion report for `doc`. Returns the path written, or None if disabled."""
    type_name = doc.doc_type.name if doc.doc_type else "adr"
    cfg = load_report_config(project_root, type_name)
    if not cfg.enabled:
        return None

    if all_docs is None:
        from decree.parser import load_all_types

        all_docs = load_all_types(strict=False)

    parsed = _parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    chain = _build_chain_for(doc, all_docs)

    when = datetime.now(timezone.utc)
    body = _render_report(doc, chain, parsed, transitioned_to, when)

    out_path = resolve_report_path(doc, project_root, cfg.location_template)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


# ── Terminal-status detection ──────────────────────────────────


_TERMINAL_SUCCESS_STATUSES = {
    "prd": ("implemented",),
    "spec": ("implemented",),
    "adr": ("accepted",),
    # Other types default to "no terminal-success status" unless explicitly configured.
}


def is_terminal_success(doc_type, target_status: str) -> bool:
    """Heuristic: is `target_status` a terminal-success state for this type?

    For built-in PRD/SPEC/ADR types, uses the hard-coded map. For custom types,
    treats any status with no outgoing transitions as terminal-success — unless
    it's a known terminal-failure (warn_on_reference is a strong signal).
    """
    type_name = doc_type.name if doc_type else "adr"
    if type_name in _TERMINAL_SUCCESS_STATUSES:
        return target_status in _TERMINAL_SUCCESS_STATUSES[type_name]
    # Custom type: terminal (no outgoing transitions) AND not in warn_on_reference (not "dead")
    transitions = doc_type.transitions if doc_type else {}
    has_no_outgoing = not transitions.get(target_status, ())
    is_dead = target_status in (doc_type.warn_on_reference if doc_type else ())
    return has_no_outgoing and not is_dead
