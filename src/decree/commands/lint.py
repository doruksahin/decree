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
    total_files = 0

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue
        paths = sorted(p for p in type_dir.glob("[0-9]*.md") if dt.filename_re.match(p.name))
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

    # governs: path existence (SPEC-004)
    governs_errors = validate_governs_paths(all_docs, get_project_root())
    errors.extend(governs_errors)

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
                    rel_expected = expected.relative_to(get_project_root()) if expected.is_relative_to(get_project_root()) else expected
                    errors.append(f"{rel_doc}: status '{doc.meta.status}' requires completion report at {rel_expected}")

    if errors:
        print()
        for e in errors:
            print(e)
        fail(f"{total_files} documents checked. {len(errors)} errors.")
        return 1

    success(f"{total_files} documents validated. 0 errors.")
    return 0
