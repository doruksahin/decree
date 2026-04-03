"""Pure validation functions — no I/O, no side effects."""

from .config import get_required_sections
from .parser import ADRDocument


def validate_sections(doc: ADRDocument) -> list[str]:
    """Check required sections are present. Returns list of error messages."""
    required = get_required_sections()
    present = set(doc.sections)
    return [
        f'missing section "{s}"'
        for s in required
        if s not in present
    ]


def validate_cross_file_integrity(docs: list[ADRDocument]) -> list[str]:
    """Check supersede symmetry and reference validity. Returns list of error messages."""
    errors: list[str] = []
    docs_by_id = {d.adr_id: d for d in docs}

    for doc in docs:
        if doc.meta.superseded_by:
            tid = doc.meta.superseded_by
            if tid not in docs_by_id:
                errors.append(f"{doc.adr_id}: superseded-by {tid} does not exist")
            elif docs_by_id[tid].meta.supersedes != doc.adr_id:
                errors.append(
                    f"CROSS-FILE: {doc.adr_id} has superseded-by {tid}, "
                    f"but {tid} has no supersedes {doc.adr_id}"
                )

        if doc.meta.supersedes:
            tid = doc.meta.supersedes
            if tid not in docs_by_id:
                errors.append(f"{doc.adr_id}: supersedes {tid} does not exist")
            elif docs_by_id[tid].meta.status != "superseded":
                errors.append(
                    f"CROSS-FILE: {doc.adr_id} supersedes {tid}, "
                    f"but {tid} has status '{docs_by_id[tid].meta.status}'"
                )

    return errors
