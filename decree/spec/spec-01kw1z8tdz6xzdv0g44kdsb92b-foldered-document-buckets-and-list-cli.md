---
date: '2026-06-26'
governs:
- src/decree/buckets.py
- src/decree/parser.py
- src/decree/cli.py
- src/decree/commands/new.py
- src/decree/commands/list_docs.py
- src/decree/commands/progress.py
- src/decree/commands/ddd.py
- src/decree/commands/lint.py
- src/decree/commands/index.py
- src/decree/commands/graph.py
- src/decree/commands/mcp_server.py
- tests
- tests/test_cli.py
- tests/test_index.py
- tests/test_list_docs.py
- tests/test_new.py
- tests/test_parser.py
- tests/test_sprint.py
- docs/index.md
- docs/usage.md
id: SPEC-01KW1Z8TDZ6XZDV0G44KDSB92B
references:
- PRD-01KW1Z5ZYPQGB8E35RWP3CA9R3
- ADR-01KW1Z7GGGQMRNN9W1KCDRD70T
status: implemented
---

# SPEC-01KW1Z8TDZ6XZDV0G44KDSB92B Foldered Document Buckets and List CLI

## Overview

Add optional nested bucket support under each configured document type
directory. Buckets are physical folders used for navigation and listing, not a
new decision relationship.

The first implementation slice must make recursive document discovery safe,
add bucket-aware document creation, and add a list/tree CLI that helps users see
the corpus by concern or feature. Existing flat corpora must continue to work
without migration.

## Technical Design

### Bucket Model

A bucket is the repo-relative path between a configured type directory and a
canonical document filename.

Examples:

- `decree/prd/prd-...md` has bucket `.`.
- `decree/prd/sprint/prd-...md` has bucket `sprint`.
- `decree/spec/provenance/indexing/spec-...md` has bucket
  `provenance/indexing`.

Bucket names are path segments, not IDs. They must be lowercase slug-like path
segments and must reject absolute paths, `..`, empty segments, generated
directories, and hidden directories.

### Recursive Document Loading

The parser should load documents recursively below each configured type
directory instead of only `type_dir.glob("*.md")`.

Source discovery must:

- include canonical markdown filenames matching the type prefix and ULID,
- skip every `index.md`,
- skip `reports/` and other generated completion-report paths,
- skip hidden directories,
- keep deterministic ordering by relative path,
- keep `DocDocument.path` as the actual nested path.

All existing callers that use `load_all`, `load_all_types`, or `find_by_id`
should inherit recursive discovery. `find_by_id` must search recursively and
still fail if duplicate filenames contain the same ID.

### New Document Creation

Add `--bucket PATH` to `decree new`.

Behavior:

- absent `--bucket`: write to the configured type root, preserving current
  behavior;
- present `--bucket sprint`: write to `type_dir/sprint/`;
- invalid bucket path: fail before writing the document;
- bucket directory is created if needed;
- filename remains `type-ulid-slug.md`.

Sprint behavior remains independent. A new SPEC created with `--bucket` still
follows sprint-mode destination rules: active sprint by default, or
`--backlog`/`--draft-pool` when requested.

### List CLI

Add `decree list` as a read-only corpus browser.

Initial flags:

- `decree list`: grouped by type, flat summary.
- `decree list --tree`: grouped by bucket, then type.
- `decree list prd|adr|spec`: limit to one configured type.
- `decree list --bucket PATH`: limit to one bucket.
- `decree list --status STATUS`: filter by status.
- `decree list --with-progress`: include primary checkbox counts for documents
  that have checkboxes.
- `decree list --json`: emit a stable machine-readable payload.

Human output should make bucket structure visible without implying relationship
edges.

### Indexes and Existing Commands

The per-type generated `index.md` tables may remain flat in v1, but they must
include nested documents. If a bucket column is added, it must be deterministic
and empty/root-safe.

`decree lint`, `decree progress --corpus`, `decree ddd --corpus`,
`decree index rebuild`, `decree index verify`, `decree graph`, MCP progress,
and query commands should see nested documents exactly as they see flat
documents today.

### Non-Goals

This SPEC does not add automatic bucket inference, move commands, bucket rename
commands, bucket-specific ownership, or bucket-derived governance.

## Testing Strategy

Add focused tests around parser discovery, new document placement, list output,
and existing command compatibility.

Test fixtures should include a mixed corpus:

- flat PRD/ADR/SPEC documents;
- nested documents under at least two buckets;
- generated `index.md`;
- `reports/` subdirectories;
- a cross-bucket reference.

Run targeted tests for parser/new/list first, then full `decree lint`,
`decree progress --corpus`, `decree index rebuild`, and `decree index verify`.

## Acceptance Criteria

- [x] Recursive parser discovery loads canonical documents under nested buckets
  while skipping `index.md`, `reports/`, hidden directories, and non-canonical
  markdown files.
- [x] `find_by_id` resolves a document in a nested bucket and still rejects
  duplicate matches for the same ID.
- [x] `decree new prd "Title" --bucket sprint` writes a canonical document
  under `decree/prd/sprint/` and creates the bucket directory when needed.
- [x] `decree new` rejects unsafe bucket values, including absolute paths,
  `..`, empty segments, hidden segments, and generated directories.
- [x] `decree new spec --bucket bucket-name` composes correctly with sprint
  active/backlog/draft-pool destination rules.
- [x] `decree list --tree` groups documents by bucket and type in deterministic
  order.
- [x] `decree list --bucket sprint --with-progress` filters to that bucket and
  shows checkbox progress for documents with primary acceptance criteria.
- [x] `decree list --json` emits bucket, type, id, title, status, path,
  references, and progress fields.
- [x] `decree lint` validates cross-bucket references and preserves existing
  flat-corpus behavior.
- [x] `decree progress --corpus`, `decree ddd --corpus`, MCP progress, and
  index rebuild/verify include nested documents.
- [x] Generated per-type `index.md` tables include nested documents without
  parsing generated report files as source documents.
- [x] Public docs explain that buckets are navigation-only and do not imply
  governance, sprint membership, references, or supersession.

### Deferred (v2)

- [ ] `decree move --bucket PATH DOC_ID` for safe document relocation.
- [ ] Bucket rename/refactor command.
- [ ] Optional bucket descriptions or README files.
- [ ] Bucket-aware web or TUI navigation.
