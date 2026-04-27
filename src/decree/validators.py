"""Validation functions for decree documents."""

from pathlib import Path


def validate_sections(doc) -> list[str]:
    """Check required sections are present. Returns list of error messages."""
    return [f'missing section "{s}"' for s in doc.missing_sections]


def validate_cross_file_integrity(docs: list) -> list[str]:
    """Check supersede symmetry and duplicate IDs. Returns list of error messages."""
    errors: list[str] = []
    docs_by_id: dict = {}

    # Duplicate ID detection
    for doc in docs:
        doc_id = doc.doc_id
        if doc_id in docs_by_id:
            errors.append(
                f"DUPLICATE-ID: {doc_id} claimed by both "
                f"{docs_by_id[doc_id].path.name} and {doc.path.name}"
            )
        else:
            docs_by_id[doc_id] = doc

    # Supersede symmetry
    for doc in docs:
        if doc.meta.superseded_by:
            tid = doc.meta.superseded_by
            if tid not in docs_by_id:
                errors.append(f"{doc.doc_id}: superseded-by {tid} does not exist")
            elif docs_by_id[tid].meta.supersedes != doc.doc_id:
                errors.append(
                    f"CROSS-FILE: {doc.doc_id} has superseded-by {tid}, "
                    f"but {tid} has no supersedes {doc.doc_id}"
                )

        if doc.meta.supersedes:
            tid = doc.meta.supersedes
            if tid not in docs_by_id:
                errors.append(f"{doc.doc_id}: supersedes {tid} does not exist")
            elif docs_by_id[tid].meta.status != "superseded":
                errors.append(
                    f"CROSS-FILE: {doc.doc_id} supersedes {tid}, "
                    f"but {tid} has status '{docs_by_id[tid].meta.status}'"
                )

    return errors


def validate_cross_type_references(docs: list) -> list[str]:
    """Check references: existence, self-refs, and warn_on_reference statuses."""
    errors = []
    docs_by_id = {d.doc_id: d for d in docs}

    for doc in docs:
        if not doc.meta.references:
            continue
        for ref_id in doc.meta.references:
            if ref_id == doc.doc_id:
                errors.append(f"CROSS-TYPE: {doc.doc_id} references itself (self-reference)")
            elif ref_id not in docs_by_id:
                errors.append(f"CROSS-TYPE: {doc.doc_id} references {ref_id} which does not exist")
            else:
                target = docs_by_id[ref_id]
                # Guard: doc_type is None only for legacy ADR-only path where documents
                # are loaded without a DocType. In practice, lint always passes doc_type
                # (it iterates load_doc_types()). The guard prevents AttributeError if
                # someone calls this function with legacy-loaded documents directly.
                if target.doc_type is not None and target.meta.status in target.doc_type.warn_on_reference:
                    errors.append(
                        f"CROSS-TYPE: {doc.doc_id} references {ref_id} "
                        f"(status: {target.meta.status})"
                    )

    return errors


def validate_attachments_exist(docs: list, project_root: Path) -> list[str]:
    """Check that attachment file paths exist on disk. Opt-in via --check-attachments."""
    errors: list[str] = []
    for doc in docs:
        if not doc.meta.attachments:
            continue
        for path_str in doc.meta.attachments:
            if not (project_root / path_str).exists():
                errors.append(f"{doc.doc_id}: attachment '{path_str}' does not exist")
    return errors
