"""Completion-report generation.

When a document transitions to a terminal-success status (e.g., SPEC `implemented`),
decree writes a markdown completion report alongside the document. The report
captures the document chain, primary acceptance criteria, deferred / out-of-scope
items, and a generation timestamp.

The "primary vs. deferred" split is extracted here so PRD-01KT22NMRS4QGHSFDBZ858PP1T R6's coherence
gate can later reuse the same section-classification logic.
"""

from __future__ import annotations

import argparse
import os
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from decree.checklists import (
    DEFAULT_DEFERRED_SECTION_PATTERNS,
    CheckboxItem,
    ParsedAcs,
    SectionAcs,
)
from decree.checklists import (
    parse_checkboxes_by_section as _parse_checkboxes_by_section,
)
from decree.checklists import (
    section_is_deferred as _section_is_deferred,
)
from decree.log import error, info, success

__all__ = [
    "DEFAULT_DEFERRED_SECTION_PATTERNS",
    "CheckboxItem",
    "ParsedAcs",
    "SectionAcs",
    "_parse_checkboxes_by_section",
    "_section_is_deferred",
]

# ── Config reading ─────────────────────────────────────────────


@dataclass(frozen=True)
class CompletionReportConfig:
    enabled: bool
    location_template: str
    deferred_section_patterns: tuple[str, ...]
    require_for_terminal_status: bool


@dataclass(frozen=True)
class ReportRegeneration:
    """One regenerated, skipped, or dry-run completion report result."""

    doc_id: str
    path: Path | None
    action: str
    reason: str | None = None


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
    - {id}: the full document ID (e.g., "SPEC-01KT22NMRWENYKC3MGRA50M7GE")
    - {slug}: the slug portion of the filename after the canonical ID
    """
    if "{number_str}" in template:
        raise ValueError("report location variable {number_str} is no longer supported; use {id} instead")
    stem = doc.path.stem
    id_prefix = f"{doc.doc_id.lower()}-"
    if stem.startswith(id_prefix):
        slug = stem[len(id_prefix) :]
    else:
        raise ValueError(f"{doc.path}: filename must start with '{id_prefix}'")
    dir_str = doc.doc_type.dir if doc.doc_type else doc.path.parent.name
    rendered = template.format(
        dir=dir_str,
        id=doc.doc_id,
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

        all_docs = load_all_types()

    parsed = _parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    chain = _build_chain_for(doc, all_docs)

    when = datetime.now(UTC)
    body = _render_report(doc, chain, parsed, transitioned_to, when)

    out_path = resolve_report_path(doc, project_root, cfg.location_template)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


def regenerate_reports(
    project_root: Path,
    *,
    doc_ids: tuple[str, ...] = (),
    all_terminal: bool = False,
    existing_only: bool = False,
    dry_run: bool = False,
) -> tuple[ReportRegeneration, ...]:
    """Regenerate completion reports for explicit IDs or all terminal-success docs.

    `existing_only` is intentionally explicit. It is useful for refreshing committed
    report snapshots without creating new report files for older terminal docs that
    did not previously have a report.
    """
    from decree.parser import find_by_id, load_all_types

    all_docs = load_all_types()

    if all_terminal:
        targets = [doc for doc in all_docs if is_terminal_success(doc.doc_type, doc.meta.status)]
    else:
        targets = [find_by_id(doc_id) for doc_id in doc_ids]

    results: list[ReportRegeneration] = []
    for doc in targets:
        type_name = doc.doc_type.name if doc.doc_type else "adr"
        if not is_terminal_success(doc.doc_type, doc.meta.status):
            results.append(
                ReportRegeneration(
                    doc_id=doc.doc_id,
                    path=None,
                    action="skipped",
                    reason=f"status '{doc.meta.status}' is not terminal-success",
                )
            )
            continue

        cfg = load_report_config(project_root, type_name)
        if not cfg.enabled:
            results.append(
                ReportRegeneration(
                    doc_id=doc.doc_id,
                    path=None,
                    action="skipped",
                    reason=f"completion reports are disabled for type '{type_name}'",
                )
            )
            continue

        out_path = resolve_report_path(doc, project_root, cfg.location_template)
        if existing_only and not out_path.exists():
            results.append(
                ReportRegeneration(
                    doc_id=doc.doc_id,
                    path=out_path,
                    action="skipped",
                    reason="report does not already exist",
                )
            )
            continue

        if dry_run:
            results.append(ReportRegeneration(doc_id=doc.doc_id, path=out_path, action="would_write"))
            continue

        written = generate_report(doc, project_root, doc.meta.status, all_docs=all_docs)
        results.append(ReportRegeneration(doc_id=doc.doc_id, path=written, action="written"))

    return tuple(results)


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root from --project or cwd-walk."""
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return get_project_root()


def regenerate_run(args: argparse.Namespace) -> int:
    """`decree report regenerate` — refresh completion report snapshots."""
    prefix = "report"
    doc_ids = tuple(getattr(args, "doc_ids", ()) or ())
    all_terminal = bool(getattr(args, "all", False))

    if all_terminal and doc_ids:
        error(prefix, "pass either explicit DOC_ID values or --all, not both")
        return 1
    if not all_terminal and not doc_ids:
        error(prefix, "pass at least one DOC_ID, or use --all")
        return 1

    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error(prefix, str(e))
        return 1

    os.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    try:
        results = regenerate_reports(
            root,
            doc_ids=doc_ids,
            all_terminal=all_terminal,
            existing_only=bool(getattr(args, "existing_only", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
    except (FileNotFoundError, ValueError) as e:
        error(prefix, str(e))
        return 1

    skipped = 0
    written = 0
    would_write = 0
    for result in results:
        path = result.path.relative_to(root) if result.path and result.path.is_relative_to(root) else result.path
        if result.action == "written":
            written += 1
            info(prefix, f"wrote {result.doc_id} -> {path}")
        elif result.action == "would_write":
            would_write += 1
            info(prefix, f"would write {result.doc_id} -> {path}")
        else:
            skipped += 1
            info(prefix, f"skipped {result.doc_id}: {result.reason}")

    if getattr(args, "dry_run", False):
        success(f"report regenerate dry-run: would_write={would_write}, skipped={skipped}")
    else:
        success(f"report regenerate: written={written}, skipped={skipped}")

    return 0 if not doc_ids or skipped == 0 else 1


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
