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
            errors.append(f"DUPLICATE-ID: {doc_id} claimed by both {docs_by_id[doc_id].path.name} and {doc.path.name}")
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
                    f"CROSS-FILE: {doc.doc_id} has superseded-by {tid}, but {tid} has no supersedes {doc.doc_id}"
                )

        if doc.meta.supersedes:
            tid = doc.meta.supersedes
            if tid not in docs_by_id:
                errors.append(f"{doc.doc_id}: supersedes {tid} does not exist")
            elif docs_by_id[tid].meta.status != "superseded":
                errors.append(
                    f"CROSS-FILE: {doc.doc_id} supersedes {tid}, but {tid} has status '{docs_by_id[tid].meta.status}'"
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
                    errors.append(f"CROSS-TYPE: {doc.doc_id} references {ref_id} (status: {target.meta.status})")

    return errors


def validate_governs_paths(docs: list, project_root: Path) -> list[str]:
    """Per SPEC-01KT22NMRXFWNE61NSETKATHBA: for each doc's `governs:` list, verify each path part exists in the
    working tree at `project_root`. The symbol part (after `#`) is preserved but NOT
    validated in v1 — symbol-level resolution is deferred to v2 (tree-sitter / LSP).

    Returns a list of error strings, one per missing path, with format:
        <doc-path>: governs path does not exist: <path>
    """
    errors: list[str] = []
    for doc in docs:
        if not doc.meta.governs:
            continue
        try:
            rel_doc_path = doc.path.relative_to(project_root)
            doc_path_str = str(rel_doc_path)
        except ValueError:
            doc_path_str = str(doc.path)
        for entry in doc.meta.governs:
            path_part = entry.split("#", 1)[0]
            if not (project_root / path_part).exists():
                errors.append(f"{doc_path_str}: governs path does not exist: {path_part}")
    return errors


def validate_terminal_status_progress(
    docs: list,
    doc_types_by_name: dict,
    exceptions: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """SPEC-01KT22NMRYNFYM7EN80WS2HD6F Gate 1: terminal-status docs must have 100% primary AC progress.

    For each doc whose type has `coherence.terminal_status_progress = true` and whose
    status is a terminal-success state, parse primary vs. deferred ACs and emit an
    error if primary is not all done.

    Returns one error string per offending doc.

    SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR: `exceptions` maps type-name -> frozenset of doc_ids to skip for
    this gate. Listed docs are dropped before validation (no error emitted).
    """
    from decree.checklists import DEFAULT_DEFERRED_SECTION_PATTERNS, parse_checkboxes_by_section
    from decree.commands.report import is_terminal_success

    errors: list[str] = []
    exc = exceptions or {}
    for doc in docs:
        dt = doc_types_by_name.get(doc.doc_type.name) if doc.doc_type else None
        if dt is None:
            continue
        coh = getattr(dt, "coherence", None)
        if coh is None or not getattr(coh, "terminal_status_progress", False):
            continue
        if not is_terminal_success(dt, doc.meta.status):
            continue
        if doc.doc_id in exc.get(dt.name, frozenset()):
            continue
        patterns = tuple(coh.deferred_sections) or DEFAULT_DEFERRED_SECTION_PATTERNS
        parsed = parse_checkboxes_by_section(doc.body, patterns)
        total = parsed.primary_total
        done = parsed.primary_done
        if total == 0 or done == total:
            continue
        pct = round(done / total * 100) if total else 0
        # Use a short relative-to-cwd-style path; the lint loop already builds those
        # in its outer scope, but validators don't have project_root here. Print the
        # filename + parents — same shape as existing validators.
        try:
            display = "/".join(doc.path.parts[-3:])
        except Exception:
            display = doc.path.name
        errors.append(
            f"{display}: status '{doc.meta.status}' but primary AC progress is "
            f"{done}/{total} ({pct}%). Check remaining items or move them to a deferred section."
        )
    return errors


def validate_unreferenced_active(
    docs: list,
    doc_types_by_name: dict,
    exceptions: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """SPEC-01KT22NMRYNFYM7EN80WS2HD6F Gate 3: active-status docs with no inbound references after N days.

    For each doc whose type has `coherence.unreferenced_active = true`:
      - if status is in `active_statuses` (default: the type's `approved`/`accepted`
        statuses), AND
      - no other doc references this doc's id, AND
      - frontmatter date is more than `unreferenced_after_days` ago,
    emit an error.

    SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR: `exceptions` maps type-name -> frozenset of doc_ids to skip for
    this gate. Listed docs are dropped before validation (no error emitted).
    """
    from datetime import date as _date

    errors: list[str] = []
    exc = exceptions or {}
    today = _date.today()

    # Pre-compute inbound reference count per doc_id
    inbound: dict[str, int] = {}
    for d in docs:
        refs = d.meta.references or []
        for r in refs:
            inbound[r] = inbound.get(r, 0) + 1

    for doc in docs:
        dt = doc_types_by_name.get(doc.doc_type.name) if doc.doc_type else None
        if dt is None:
            continue
        coh = getattr(dt, "coherence", None)
        if coh is None or not getattr(coh, "unreferenced_active", False):
            continue
        if doc.doc_id in exc.get(dt.name, frozenset()):
            continue
        # Decide which statuses are "active" — explicit list wins; else heuristic
        # of any non-terminal status whose name suggests acceptance.
        active = set(coh.active_statuses) if coh.active_statuses else {"approved", "accepted"}
        if doc.meta.status not in active:
            continue
        if inbound.get(doc.doc_id, 0) > 0:
            continue
        # Date arithmetic: frontmatter date is a datetime.date already.
        d_date = doc.meta.date
        if not isinstance(d_date, _date):
            continue
        age_days = (today - d_date).days
        if age_days <= coh.unreferenced_after_days:
            continue
        try:
            display = "/".join(doc.path.parts[-3:])
        except Exception:
            display = doc.path.name
        errors.append(
            f"{display}: status '{doc.meta.status}' for {age_days} days with no referencing "
            f"document. Stalled? (threshold: {coh.unreferenced_after_days} days)"
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
