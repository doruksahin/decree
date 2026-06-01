---
date: '2026-06-01'
governs:
- src/decree/identity.py
- src/decree/parser.py
- src/decree/commands/new.py
- src/decree/commands/migrate.py
- src/decree/commands/progress.py
- src/decree/commands/ddd.py
- src/decree/cli.py
id: SPEC-01KT22NMS0D19VMD8VPK4D2MNX
references:
- PRD-01KT22NMRTFTWFFARAN0PVEETA
- ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ
status: implemented
---

# SPEC-01KT22NMS0D19VMD8VPK4D2MNX Parallel-Safe Document Identity and Scoped Progress

## Overview

Replace decree's sequential filename-derived identity model with explicit ULID-based frontmatter IDs and add scoped progress/DDD views for parallel agent workflows.

Normal command operation requires each document to include `id: TYPE-ULID`. Legacy numeric IDs are handled only by `decree migrate ids`, which reads the old corpus, produces a deterministic mapping, rewrites structured references, renames files, and regenerates derived artifacts.

## Technical Design

Add a focused `decree.identity` module responsible for ID generation, validation, filename construction, and filename parsing. It implements ULID generation without a new runtime dependency.

Update `DocFrontmatter` to require `id`. `DocDocument.doc_id` returns `meta.id`, not a value inferred from the filename. The loader validates that the filename begins with the lower-case document ID and that the ID matches the configured type prefix. Missing IDs are fatal in normal parser paths.

Update document templates and `decree new` so new documents include `id:` and are written to `{id-lower}-{slug}.md`. `decree new` stops regenerating indexes automatically; users must call `decree index regenerate` explicitly.

Add `decree migrate ids` under the existing `migrate` namespace. It has `--dry-run` and `--apply`. The migration reads legacy numeric filenames without using the normal strict parser, creates a mapping from old IDs to new ULID IDs, rewrites structured frontmatter references (`id`, `references`, `supersedes`, `superseded-by`), renames document files and report snapshots, updates generated indexes, and writes a JSON mapping report under `decree/migrations/`.

Update `decree progress` with explicit scope flags:

- `--doc ID` shows one document.
- `--chain ID` shows the referenced document chain connected to a PRD/ADR/SPEC.
- `--changed --base REF` shows documents added or modified relative to a git base.
- `--governs PATH` shows documents whose `governs:` entries cover a path.

Update `decree ddd` with the same document, chain, and changed scopes so agents can reason about the work in their branch instead of the whole corpus. Every scoped command prints the selected scope.

## Testing Strategy

Use unit tests for ULID generation/validation, parser strictness, new document creation, migration dry-run/apply behavior, scoped progress filtering, and scoped DDD assessment. Keep a legacy fixture corpus in tests to prove migration can convert old numeric documents without enabling runtime fallback. Include a subprocess-based concurrency regression test that runs parallel `decree new` commands in one temporary project and verifies unique canonical IDs, lint health, and index verification.

Dogfood the migration on decree's own corpus in this branch and then run the full validation stack: unit tests, lint, index verification, link checking, pre-commit, and command-level smoke checks for scoped progress/DDD.

## Acceptance Criteria

- [x] `decree.identity` generates and validates `TYPE-ULID` IDs without new runtime dependencies.
- [x] Canonical new documents require `id:` frontmatter; legacy numeric files are isolated to the explicit migration/read path.
- [x] `decree new` writes `{id-lower}-{slug}.md`, includes `id:`, and does not regenerate indexes implicitly.
- [x] `decree migrate ids --dry-run` reports a complete legacy-to-ULID mapping without modifying files.
- [x] `decree migrate ids --apply` rewrites frontmatter IDs, structured references, filenames, reports, and indexes.
- [x] `decree progress` supports `--doc`, `--chain`, `--changed --base`, and `--governs` with explicit scope output.
- [x] `decree ddd` supports scoped assessment for at least `--doc`, `--chain`, and `--changed --base`.
- [x] CLI help and docs explain identity rules, migration behavior, generated artifact responsibility, and scoped commands.
- [x] Tests cover identity generation, parser behavior, migration, scoped progress, and scoped DDD.
- [x] The decree repository dogfoods the new identity model and passes the full validation stack.
- [x] Regression tests cover parallel `decree new` processes and explicit overwrite refusal on filename collision.
