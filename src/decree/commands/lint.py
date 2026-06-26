"""Validate all documents: frontmatter, sections, cross-file integrity, cross-type references."""

import argparse

from pydantic import ValidationError

from decree.log import fail, success
from decree.validators import (
    validate_cross_file_integrity,
    validate_cross_type_references,
    validate_governs_paths,
    validate_sections,
)


def run(args: argparse.Namespace | None = None) -> int:
    from decree.config import get_project_root, load_doc_types
    from decree.parser import load

    doc_types = load_doc_types()
    all_docs = []
    errors: list[str] = []
    info_lines: list[str] = []  # SPEC-01KT22NMRYNFYM7EN80WS2HD6F gate 2: informational, non-error output
    total_files = 0

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue
        paths = sorted(p for p in type_dir.glob("*.md") if p.name != "index.md")
        total_files += len(paths)
        type_docs = []

        for path in paths:
            rel = path.relative_to(get_project_root())
            try:
                doc = load(path, doc_type=dt)
            except ValidationError as e:
                for err in e.errors():
                    errors.append(f"{rel}: {err['msg']}")
                continue
            except Exception as e:
                errors.append(f"{rel}: {e}")
                continue

            type_docs.append(doc)
            all_docs.append(doc)
            section_errors = validate_sections(doc)
            for msg in section_errors:
                errors.append(f"{rel}: {msg}")

        cross_errors = validate_cross_file_integrity(type_docs)
        errors.extend(cross_errors)

    # Cross-type reference validation
    cross_type_errors = validate_cross_type_references(all_docs)
    errors.extend(cross_type_errors)

    # governs: path existence (SPEC-01KT22NMRXFWNE61NSETKATHBA)
    governs_errors = validate_governs_paths(all_docs, get_project_root())
    errors.extend(governs_errors)

    # Optional sprint ledger validation. Sprint mode is disabled until the
    # ledger exists, so existing projects keep their current lint behavior.
    from decree.sprints import validate_ledger

    sprint_validation = validate_ledger(get_project_root(), all_docs)
    errors.extend(f"{e}" for e in sprint_validation.errors)
    info_lines.extend(f"SPRINT WARNING: {w}" for w in sprint_validation.warnings)

    # SPEC-01KT22NMRYNFYM7EN80WS2HD6F coherence gates — opt-in per-type
    doc_types_by_name = {dt.name: dt for dt in doc_types}
    any_coherence_enabled = any(getattr(dt, "coherence", None) is not None for dt in doc_types)
    if any_coherence_enabled:
        from decree.config import load_coherence_exceptions
        from decree.validators import (
            validate_terminal_status_progress,
            validate_unreferenced_active,
        )

        # SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR: per-type, per-gate exception lists honoured by the live gate.
        exceptions_by_type = load_coherence_exceptions()
        exc_terminal = {
            t: exceptions_by_type.get(t, {}).get("terminal_status_progress", frozenset()) for t in exceptions_by_type
        }
        exc_unref = {
            t: exceptions_by_type.get(t, {}).get("unreferenced_active", frozenset()) for t in exceptions_by_type
        }
        errors.extend(validate_terminal_status_progress(all_docs, doc_types_by_name, exceptions=exc_terminal))
        errors.extend(validate_unreferenced_active(all_docs, doc_types_by_name, exceptions=exc_unref))

        # SPEC-01KT22NMRYNFYM7EN80WS2HD6F Gate 2: when both primary and deferred ACs exist, surface the
        # split as an informational line (not an error). Only for types that have
        # `deferred_sections_separated = true`.
        from decree.checklists import DEFAULT_DEFERRED_SECTION_PATTERNS, parse_checkboxes_by_section

        for doc in all_docs:
            dt = doc_types_by_name.get(doc.doc_type.name) if doc.doc_type else None
            if dt is None:
                continue
            coh = getattr(dt, "coherence", None)
            if coh is None or not getattr(coh, "deferred_sections_separated", False):
                continue
            patterns = tuple(coh.deferred_sections) or DEFAULT_DEFERRED_SECTION_PATTERNS
            parsed = parse_checkboxes_by_section(doc.body, patterns)
            if parsed.primary_total > 0 and parsed.deferred_total > 0:
                try:
                    rel_doc = doc.path.relative_to(get_project_root())
                except ValueError:
                    rel_doc = doc.path
                info_lines.append(
                    f"{rel_doc}: {parsed.deferred_total} deferred-section ACs separated "
                    f"from primary (counted independently)."
                )

    # Attachment file existence (opt-in)
    if getattr(args, "check_attachments", False):
        from decree.validators import validate_attachments_exist

        errors.extend(validate_attachments_exist(all_docs, get_project_root()))

    # C4 validation (per type, only if c4 is configured)
    for dt in doc_types:
        if dt.c4 and dt.c4.enabled:
            from decree.c4 import validate_c4

            type_docs = [d for d in all_docs if d.doc_type == dt]
            c4_errors = validate_c4(type_docs, dt.c4)
            errors.extend(c4_errors)

    # Completion-report existence check (opt-in via [types.*.completion_report.require_for_terminal_status])
    from decree.commands.report import is_terminal_success, load_report_config, resolve_report_path

    for dt in doc_types:
        cfg = load_report_config(get_project_root(), dt.name)
        if not cfg.require_for_terminal_status:
            continue
        type_docs = [d for d in all_docs if d.doc_type == dt]
        for doc in type_docs:
            if is_terminal_success(dt, doc.meta.status):
                expected = resolve_report_path(doc, get_project_root(), cfg.location_template)
                if not expected.exists():
                    rel_doc = doc.path.relative_to(get_project_root())
                    rel_expected = (
                        expected.relative_to(get_project_root())
                        if expected.is_relative_to(get_project_root())
                        else expected
                    )
                    errors.append(f"{rel_doc}: status '{doc.meta.status}' requires completion report at {rel_expected}")

    # Emit informational (non-error) output before the errors block.
    if info_lines:
        print()
        for line in info_lines:
            print(line)

    if errors:
        print()
        for e in errors:
            print(e)
        fail(f"{total_files} documents checked. {len(errors)} errors.")
        return 1

    success(f"{total_files} documents validated. 0 errors.")
    return 0
