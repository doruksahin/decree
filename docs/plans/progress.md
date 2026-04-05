# Multi-Doctype Implementation Progress

## Status: Tasks 1-4 complete. Tasks 5-10 remaining.

---

## Completed Tasks

### Task 1 ✅ — DocType dataclass
- Created `src/decree/doctypes.py`
- Created `tests/test_doctypes.py` (13 tests passing)

### Task 2 ✅ — Load DocTypes from pyproject.toml
- Added `load_doc_types()`, `find_doc_type()`, `_build_doc_type()`, `_adr_from_legacy_config()`, `_parse_field_requirements()` to `src/decree/config.py`
- Updated `tests/conftest.py` to clear `load_doc_types` cache
- Added `TestLoadDocTypes` class to `tests/test_config.py` (5 new tests)

### Task 3 ✅ — Generalize parser
- `src/decree/parser.py` completely rewritten:
  - `DocFrontmatter` (replaces `ADRFrontmatter`, which is kept as alias)
  - Context-aware status validation via `field_validator` + `ValidationInfo`
  - Added `references: list[str] | None = None` field
  - `DocDocument` (replaces `ADRDocument`, which is kept as alias)
  - `doc_type=None` default — backward compat
  - `doc_id` property uses `doc_type.format_id()` when set, else ADR-style
  - `adr_id` alias for `doc_id`
  - `missing_sections` uses `doc_type.required_sections` when set, else `get_required_sections()`
  - New `load_all_types()` function
  - Updated `find_by_id()` auto-detects type
  - New `next_number(doc_type)` + kept `next_adr_number()` alias
  - `evolve(doc_type=None, **overrides)` accepts optional doc_type

### Task 4 ✅ — Generalize new command
- Created `src/decree/templates/prd.md`
- Created `src/decree/templates/spec.md`
- Updated `src/decree/template.py` — `render_template()` accepts `doc_type=None`
- Updated `src/decree/commands/new.py` — resolves `args.doc_type` → DocType, uses type's dir/digits/initial_status/template

---

## Remaining Tasks

### Task 5 — Generalize status command

**File:** `src/decree/commands/status.py`

Key changes:
1. Use `doc_id = getattr(args, 'doc_id', None) or getattr(args, 'adr_id', None)` (support both old and new arg names)
2. Call `find_doc_type(doc_id)` to get DocType
3. Look up `action → target_status` from `doc_type.actions` (instead of hardcoded `STATUS_ACTION_MAP`)
4. Use `doc_type.transitions` instead of `VALID_TRANSITIONS`
5. Supersede logic only when `target_status == "superseded"` and doc_type has supersede semantics (i.e., `"supersedes"` key in doc_type.actions)
6. Call `doc.meta.evolve(doc_type=doc_type, ...)` to pass context

**Backward compat:** Existing tests use `args.adr_id`. The `getattr` fallback handles this.

**New test in `tests/test_status.py`:**
```python
def _prd_project(tmp_path):
    """Set up a project with PRD type configured."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved"]

[tool.doc.types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = []

[tool.doc.types.prd.actions]
submit = "review"
approve = "approved"
""")
    (tmp_path / "docs" / "prd").mkdir(parents=True)
    return tmp_path

def test_status_transition_prd(monkeypatch, tmp_path):
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    prd_dir = proj / "docs" / "prd"
    (prd_dir / "001-user-auth.md").write_text(
        "---\nstatus: draft\ndate: 2026-04-05\n---\n# PRD-001 User Auth\n\n## Problem Statement\n\n## Requirements\n\n## Success Criteria\n"
    )
    args = argparse.Namespace(action="submit", doc_id="PRD-001", target_id=None)
    result = run(args)
    assert result == 0
    import frontmatter
    post = frontmatter.load(str(prd_dir / "001-user-auth.md"))
    assert post["status"] == "review"

def test_status_invalid_transition_prd(monkeypatch, tmp_path):
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    prd_dir = proj / "docs" / "prd"
    (prd_dir / "001-user-auth.md").write_text(
        "---\nstatus: draft\ndate: 2026-04-05\n---\n# PRD-001 User Auth\n"
    )
    args = argparse.Namespace(action="approve", doc_id="PRD-001", target_id=None)
    result = run(args)
    assert result == 1  # draft → approved not valid
```

---

### Task 6 — Generalize lint + cross-type validation

**Files:** `src/decree/validators.py`, `src/decree/commands/lint.py`

#### validators.py changes:

1. **Update `validate_sections(doc)`** — delegate to `doc.missing_sections`:
```python
def validate_sections(doc) -> list[str]:
    return [f'missing section "{s}"' for s in doc.missing_sections]
```

2. **Update `validate_cross_file_integrity(docs)`** — add duplicate ID detection:
```python
def validate_cross_file_integrity(docs: list) -> list[str]:
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

    # Supersede symmetry (existing logic, use doc_id not adr_id)
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
```

3. **Add `validate_cross_type_references(docs)`**:
```python
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
                if target.doc_type is not None and target.meta.status in target.doc_type.warn_on_reference:
                    errors.append(
                        f"CROSS-TYPE: {doc.doc_id} references {ref_id} "
                        f"(status: {target.meta.status})"
                    )
    return errors
```

#### lint.py changes:

Rewrite `run()` to iterate all types + cross-type validation:
```python
def run(args=None) -> int:
    from decree.config import load_doc_types, get_project_root
    from decree.parser import load, load_all_types
    from decree.validators import validate_sections, validate_cross_file_integrity, validate_cross_type_references
    from pydantic import ValidationError

    prefix = "lint"
    doc_types = load_doc_types()
    all_docs = []
    errors = []
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

    if errors:
        print()
        for e in errors:
            print(e)
        from decree.log import fail
        fail(f"{total_files} documents checked. {len(errors)} errors.")
        return 1

    from decree.log import success
    success(f"{total_files} documents validated. 0 errors.")
    return 0
```

**IMPORTANT for existing tests:** Existing `test_lint.py` uses `project_dir` fixture which has `[tool.adr]` config. The new lint.py calls `load_doc_types()` which returns the ADR type from legacy config. This should work correctly.

---

### Task 7 — Generalize index command

**File:** `src/decree/commands/index.py`

Rewrite to iterate all types and generate one index file per type:
```python
def run(args=None) -> int:
    from decree.config import load_doc_types, get_project_root
    from decree.parser import load_all
    from decree.log import info, success

    prefix = "index"
    doc_types = load_doc_types()

    for dt in doc_types:
        type_dir = get_project_root() / dt.dir
        type_dir.mkdir(parents=True, exist_ok=True)

        docs = load_all(strict=False, doc_type=dt)
        info(prefix, f"loaded {len(docs)} {dt.name.upper()} documents")

        STATUS_ORDER = list(dt.statuses)  # use type's status order
        docs.sort(key=lambda d: (
            STATUS_ORDER.index(d.meta.status) if d.meta.status in STATUS_ORDER else 99,
            d.number
        ))

        type_upper = dt.name.upper()
        lines = [
            f"# {type_upper}s",
            "",
            f"> {type_upper} documents — auto-generated by `adr index`.",
            "",
            f"| {type_upper} | Title | Status | Date |",
            f"|{'-----|' * 4}",
        ]
        for doc in docs:
            lines.append(f"| {doc.doc_id} | {doc.title} | {doc.meta.status} | {doc.meta.date} |")
        lines.append("")

        index_file = type_dir / "index.md"
        index_file.write_text("\n".join(lines))
        info(prefix, f"wrote {index_file} — {len(docs)} documents")

    success(f"index regenerated for {len(doc_types)} type(s)")
    return 0
```

**IMPORTANT for existing tests:**
- `test_generates_index`: checks `(populated_adr_dir / "index.md").exists()` and content has ADR-0001 — the new code writes `docs/adr/index.md` ✓
- `test_accepted_before_proposed`: checks order in index — new code sorts by STATUS_ORDER ✓
- `test_empty_dir`: checks `(project_dir / "docs" / "adr" / "index.md").exists()` — new code creates index even for empty dir ✓

The old `get_adr_index_file()` is no longer used in index.py. That's fine.

---

### Task 8 — Generalize graph command

**File:** `src/decree/commands/graph.py`

The smoke tests don't test graph directly, so minimal changes needed. The main issue: `graph.py` currently calls `load_all()` (ADR-only) and writes to `docs/adr/index.md` with a marker.

For multi-type, it should still work for ADR-only projects. For multi-type projects, it can write to the first type's index or a top-level docs/index.md.

**Minimal change:** Update to use `load_all_types()` but still write to `docs/adr/index.md` for backward compat. Add cross-type edges from `references` field.

Actually, the graph command has issues because:
1. It calls `load_all(strict=False)` — this still works (returns ADR docs)
2. It uses `doc.adr_id` — this still works (adr_id is alias for doc_id)
3. It writes to `docs/adr/index.md` with a marker

For simplicity, keep graph mostly unchanged. Just update `load_all()` call to handle the multi-type case by loading all types. But the graph writes to `docs/adr/index.md` which may not exist in a multi-type project.

**Recommended approach:** Keep graph backward compatible for ADR-only projects. For multi-type, it writes cross-type Mermaid to `docs/adr/index.md` if it exists.

Actually, since `test_graph.py` doesn't exist yet and smoke tests don't test graph, just update `load_all()` → `load_all_types()` and use `doc.doc_id` instead of `doc.adr_id`. But the marker-based index.md approach needs the ADR index to exist.

**Simplest fix:** Try `docs/adr/index.md` first; if not found, try the first type's dir. If still not found, skip with info message (don't error).

---

### Task 9 — doc CLI entry point

**File:** `src/decree/cli.py`

Add `doc_main()`:
```python
def doc_main() -> int:
    """Multi-type document CLI."""
    parser = argparse.ArgumentParser(prog="doc", description="Structured document management toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_new = subparsers.add_parser("new")
    p_new.add_argument("doc_type", help="Document type (adr, prd, spec, ...)")
    p_new.add_argument("title", help="Title of the document")

    p_status = subparsers.add_parser("status")
    p_status.add_argument("doc_id", help="Document ID (e.g., ADR-0001, PRD-001)")
    p_status.add_argument("action", help="Action to perform (e.g., accept, approve)")
    p_status.add_argument("target_id", nargs="?", default=None)

    subparsers.add_parser("lint")
    subparsers.add_parser("index")
    subparsers.add_parser("graph")

    args = parser.parse_args()
    commands = {"new": new.run, "status": status.run, "lint": lint.run, "index": index.run, "graph": graph.run}
    return commands[args.command](args)
```

Also update `pyproject.toml`:
```toml
[project.scripts]
adr = "decree.cli:main"
doc = "decree.cli:doc_main"
```

---

### Task 10 — End-to-end integration test

**File:** `tests/test_integration.py`

See the plan at `docs/plans/2026-04-05-multi-doctype.md` lines 1216-1272 for the full test code. It tests the complete lifecycle using `new`, `status`, and `lint` commands together.

---

## Acceptance Criteria

All 40 smoke tests in `tests/test_smoke_scenarios.py` must pass.
All 82 existing tests (as of Tasks 1-4) must still pass.

Run: `uv run pytest -v 2>&1 | tail -30`

## Key Design Decisions (DO NOT CHANGE)

- `warn_on_reference` (dead statuses) != `terminal_statuses`
- Circular references: ALLOWED
- Reference direction: NOT ENFORCED
- Staleness propagation: DIRECT ONLY (not transitive)
- Self-references: FLAGGED as errors
- Duplicate IDs: FLAGGED as errors
- "implemented" is terminal but NOT in warn_on_reference

## Error Message Format Requirements (smoke tests check these)

- Stale ref: `"CROSS-TYPE: {doc_id} references {ref_id} (status: {status})"`
  - Must contain "superseded", "rejected", "deprecated", "archived" etc. in message
- Dangling ref: `"CROSS-TYPE: {doc_id} references {ref_id} which does not exist"`
  - Must contain "does not exist"
- Self-ref: `"CROSS-TYPE: {doc_id} references itself (self-reference)"`
  - Must contain "self" (case insensitive)
- Duplicate ID: `"DUPLICATE-ID: {doc_id} claimed by both {file1} and {file2}"`
  - Must contain doc_id and "duplicate" (case insensitive)
- Supersede asymmetry: `"CROSS-FILE: {doc_id} has superseded-by {tid}, but {tid} has no supersedes {doc_id}"`
  - Must contain both doc IDs
- Missing superseded-by target: `"{doc_id}: superseded-by {tid} does not exist"`
  - Must contain "does not exist"
- Missing section: `"{rel}: missing section \"{section}\""`
  - Must contain "missing section"
