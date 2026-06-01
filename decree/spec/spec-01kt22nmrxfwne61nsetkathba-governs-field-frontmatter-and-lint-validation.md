---
date: '2026-05-12'
id: SPEC-01KT22NMRXFWNE61NSETKATHBA
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRXFWNE61NSETKATHBA governs Field — Frontmatter and Lint Validation

## Overview

Implements PRD-01KT22NMRS4QGHSFDBZ858PP1T R2 (file-level `governs:` frontmatter field on any configured type). Promotes `governs:` from a free-form raw-metadata key to a typed, validated, lint-checked frontmatter field. Symbol-level resolution (`path#symbol`) is parsed and stored but not validated against the working tree — that's the v2 backlog (tree-sitter / LSP).

This SPEC ships:

1. **Typed field on `DocFrontmatter`** — `governs: list[str] | None`, accepting entries like `"src/decree/c4.py"` or `"src/decree/c4.py#validate_c4"`.
2. **Pydantic validation** — entry must be a string; the path part must be repo-relative (no leading `/` allowed, no `..` traversal).
3. **Lint validation** — `decree lint` reports a clear error per missing path. Symbol part (after `#`) is preserved but not checked in v1.
4. **IndexDB integration** — `IndexDB.rebuild()` reads from `doc.meta.governs` instead of `raw_metadata.get("governs")`. Behavior is unchanged for documents that already had governs (it was being parsed off raw_metadata); behavior is now correct for documents that don't have it (no crash, no extra logic).

## Technical Design

### Frontmatter field

```yaml
---
status: approved
date: 2026-05-12
references: [PRD-01KT22NMRS4QGHSFDBZ858PP1T]
governs:
  - src/decree/c4.py
  - src/decree/parser.py#DocFrontmatter
  - apps/desktop/src/renderer/src/features/playgrounds/
---
```

The field is **optional**. Documents without it parse exactly as before. Each entry's syntax:

```
<repo-relative-path>             # v1: file or directory; lint validates existence
<repo-relative-path>#<symbol>    # symbol path is preserved, NOT validated in v1
```

`DocFrontmatter` extends as follows (in `src/decree/parser.py`):

```python
class DocFrontmatter(BaseModel):
    # ... existing fields ...
    governs: list[str] | None = None

    @field_validator("governs")
    @classmethod
    def governs_syntax(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for entry in v:
            if not isinstance(entry, str):
                raise ValueError(f"governs entries must be strings; got {type(entry).__name__}: {entry!r}")
            path_part = entry.split("#", 1)[0]
            if not path_part:
                raise ValueError(f"governs entry has empty path: {entry!r}")
            if path_part.startswith("/"):
                raise ValueError(f"governs path must be repo-relative (no leading '/'): {entry!r}")
            if ".." in path_part.split("/"):
                raise ValueError(f"governs path must not contain '..' segments: {entry!r}")
        return v
```

### Lint integration

A new validator `validate_governs_paths(docs, project_root)` in `src/decree/validators.py` returns a list of error strings, one per missing path. Called from `lint.run()` after the existing cross-type-reference validation, before C4 validation.

```python
def validate_governs_paths(docs: list[DocDocument], project_root: Path) -> list[str]:
    """For each doc's governs: list, verify each path part exists in the working tree.
    Returns a list of error strings (one per missing entry)."""
```

Error format (consistent with existing decree lint output):

```
decree/spec/spec-<ulid>-foo.md: governs path does not exist: src/api/missing.py
```

Symbol-level entries (`path#symbol`) are validated only on the path part. The symbol is preserved on `governs` for future use by SPEC-01KT22NMRXWCS5TK5VC1FT6JER query commands.

### IndexDB read-path migration

`IndexDB.rebuild()` currently parses `governs` off `raw_metadata`. With this SPEC, `doc.meta.governs` is the canonical field. Rebuild uses `doc.meta.governs or []` (the field defaults to `None`).

This is purely a code-path consolidation — behavior is identical for documents that already had a `governs:` block. The IndexDB tests already exercise this path; they continue to pass.

### Files touched

- **Modify**: `src/decree/parser.py` — add `governs: list[str] | None` field and validator to `DocFrontmatter`.
- **Modify**: `src/decree/validators.py` — add `validate_governs_paths()`.
- **Modify**: `src/decree/commands/lint.py` — call `validate_governs_paths()`.
- **Modify**: `src/decree/index_db.py` — read from `doc.meta.governs` instead of `raw_metadata["governs"]`.
- **Modify**: `tests/test_parser.py` — frontmatter validation tests for governs.
- **Modify**: `tests/test_validators.py` — `validate_governs_paths` unit tests.
- **Modify**: `tests/test_lint.py` — integration: lint reports missing-path errors.
- **Modify**: `tests/test_index_db.py` — verify governs continues to populate from typed field.

### What this SPEC does NOT do

- Symbol-level validation. Entries like `src/foo.py#bar` have their path part validated but the `bar` symbol is not resolved. That's PRD-01KT22NMRS4QGHSFDBZ858PP1T R2 v2 (tree-sitter / LSP).
- Glob pattern resolution. An entry like `src/api/**` is treated as a literal path that must exist. Glob support is a future enhancement.
- Migration tooling. PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 (`decree migrate governs --analyze/--apply-suggestions`) ships in its own SPEC.
- Wildcard / fuzzy matching of paths. Exact path match only.

## Testing Strategy

### Unit tests

- **`tests/test_parser.py`**:
  - `governs: ["src/foo.py"]` parses correctly.
  - `governs: ["src/foo.py#bar"]` parses correctly.
  - `governs: null` and absence both parse to `None`.
  - Non-string entry raises `ValidationError`.
  - Path with leading `/` raises `ValidationError`.
  - Path with `..` segment raises `ValidationError`.
  - Empty path part (e.g., `"#bar"`) raises `ValidationError`.

- **`tests/test_validators.py`**:
  - `validate_governs_paths` returns empty list when all paths exist.
  - Returns one error per missing path.
  - Validates path part only when entry is `path#symbol` (the symbol part is not checked).
  - Documents without `governs` are ignored (no errors).

### Integration tests

- **`tests/test_lint.py`**:
  - A doc with `governs: ["src/foo.py"]` where the file exists → lint passes.
  - A doc with `governs: ["src/missing.py"]` → lint fails with the exact error string.
  - Multiple docs with governs entries, mix of valid and invalid → all errors reported.

- **`tests/test_index_db.py`**:
  - Adding `governs: ["src/foo.py", "src/bar.py#baz"]` to a fixture doc results in two rows in the `governs` table after rebuild, with the symbol column populated for the second.

### Dogfood validation

- After implementation, the implementer should add `governs: ["src/decree/index_db.py", "src/decree/commands/index_db_cli.py"]` to SPEC-01KT22NMRX176PCT00SKJ9G2AQ's frontmatter and `governs: ["src/decree/commands/ddd.py", "src/decree/commands/hook.py", "src/decree/commands/report.py"]` to SPEC-01KT22NMRW79Y92MKZT807B2J1. Then `decree lint` must pass and `decree index rebuild && decree index status` should show `governs > 0` rows.

## v1 Acceptance Criteria

### Frontmatter typing

- [x] `DocFrontmatter` (in `src/decree/parser.py`) gains a `governs: list[str] | None = None` field.
- [x] Pydantic validator rejects non-string entries with a clear error.
- [x] Pydantic validator rejects paths with leading `/` (absolute) with a clear error.
- [x] Pydantic validator rejects paths containing `..` segments with a clear error.
- [x] Pydantic validator rejects entries with empty path part (e.g., `#bar`).

### Lint validation

- [x] `validate_governs_paths(docs, project_root)` exists in `src/decree/validators.py`.
- [x] `decree lint` calls it and surfaces each missing path as a distinct error line.
- [x] Error format: `<doc-path>: governs path does not exist: <path>`.
- [x] Symbol-level entries (`path#symbol`): the path part is validated; the symbol part is not checked.
- [x] Documents without `governs:` contribute zero errors.

### IndexDB consolidation

- [x] `IndexDB.rebuild()` reads from `doc.meta.governs` (typed field), not `raw_metadata["governs"]`.
- [x] Existing 26 index_db tests continue to pass.
- [x] Adding `governs:` to a fixture doc results in expected rows in the `governs` table after rebuild.

### Dogfood

- [x] SPEC-01KT22NMRX176PCT00SKJ9G2AQ's frontmatter is updated to include `governs:` paths for the files it ships (e.g., `src/decree/index_db.py`).
- [x] SPEC-01KT22NMRW79Y92MKZT807B2J1's frontmatter is updated similarly.
- [x] `decree lint` passes after dogfood update.
- [x] `decree index rebuild` followed by `decree index status` shows `governs > 0`.

### Tests

- [x] All new tests added per the Testing Strategy section.
- [x] Full test suite continues to pass (no regressions in the 261-test baseline).

## What this does NOT do (deferred)

- [ ] Symbol-level path resolution / validation — v2 (tree-sitter / LSP).
- [ ] Glob pattern expansion (e.g., `src/api/**`) — future.
- [ ] Migration tooling to backfill `governs:` from existing prose-described "affected files" — PRD-01KT22NMRS4QGHSFDBZ858PP1T R9 (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6).
- [ ] Lint of governs across the jira-task-to-md corpus (167 docs without any governs today) — deferred until SPEC-01KT22NMRYRZQ59EC88VJ5R0N6's migration ships.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R2 — the requirement this SPEC implements.
- ADR-01KT22NMRV9CP14X5982JJH161 — the architectural constraint (index reads from doc.meta.*).
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ — the IndexDB which already reads `governs` off raw_metadata and needs to be migrated to the typed field.
