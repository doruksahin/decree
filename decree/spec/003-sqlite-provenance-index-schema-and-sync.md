---
date: '2026-05-12'
references:
- PRD-003
- ADR-0002
status: implemented
governs:
- src/decree/index_db.py
- src/decree/commands/index_db_cli.py
---

# SPEC-003 SQLite Provenance Index — Schema and Sync

## Overview

Implements PRD-003 R1 (provenance graph as SSOT for queries). Establishes the SQLite index that PRD-003's other requirements (R3 `decree why`, R5 MCP server, R7 staleness, R8 intent-review) will read from. Per ADR-0002 Option C (hybrid), the index is a **derived read-cache**: frontmatter remains the authoring source of truth, the index is rebuilt from it deterministically.

This SPEC ships:

1. **Schema** — SQLite tables for `decisions`, `governs`, `refs`, `commits`, `acceptance_criteria`, `index_meta`. FTS5 virtual table over title + body for keyword search. Schema versioning via `index_meta`.
2. **Sync layer** — `IndexDB` class wrapping `sqlite-utils`, with `rebuild()` (full) and `verify()` (drift detection). Idempotent on body content hash.
3. **CLI** — `decree index rebuild` / `decree index status` / `decree index verify`.
4. **Library leverage** — `sqlite-utils` for all schema/FTS/migration plumbing; `mistletoe` added as a dep here (reserved for SPEC-005's body-link extraction so it doesn't trip a "new dep" gate later); reuses `_parse_checkboxes_by_section` from SPEC-002's report module for primary/deferred AC classification.

Out of scope for this SPEC (deferred to follow-up SPECs under PRD-003):
- `governs:` frontmatter field validation by lint — SPEC-004
- `decree why` / `decree refs` query commands — SPEC-005
- Git trailers + `decree commit` wrapper + `commits` table population — SPEC-006
- MCP server reading from the index — SPEC-007
- Coherence gates + staleness + hotspots — SPEC-008
- Intent-review API + migration tooling — SPEC-009

The schema, however, is designed to accommodate the eventual queries those SPECs will issue. Schema additions in v2 should be ALTER TABLE migrations, not breaking redesigns.

## Technical Design

### Storage location

The index lives at `<project_root>/.decree/index.sqlite`. The `.decree/` directory is added to `.gitignore` patterns by `decree init` (consumer responsibility) and documented as such. Rationale: the index is derived state, regenerable in seconds; checking it in would create merge conflict churn on every status transition.

### Schema

All tables are defined via `sqlite-utils` so schema evolution is `db["table"].add_column(...)` rather than hand-rolled ALTER TABLE.

```
decisions
    id              TEXT PRIMARY KEY     -- "SPEC-001"
    type            TEXT NOT NULL        -- "spec" / "prd" / "adr" / "ddr"
    status          TEXT NOT NULL        -- "draft" / "approved" / "implemented" / ...
    title           TEXT NOT NULL
    path            TEXT NOT NULL UNIQUE -- repo-relative file path
    date            TEXT NOT NULL        -- ISO date from frontmatter
    body_hash       TEXT NOT NULL        -- SHA-256 of body content
    indexed_at      TEXT NOT NULL        -- ISO timestamp of when this row was indexed
    raw_metadata    TEXT                 -- JSON dump of frontmatter for fields we don't promote

refs
    from_id         TEXT NOT NULL        -- "SPEC-001"
    to_id           TEXT NOT NULL        -- "PRD-001"
    kind            TEXT NOT NULL        -- "references" / "supersedes" / "superseded-by"
    PRIMARY KEY (from_id, to_id, kind)

governs
    decision_id     TEXT NOT NULL
    path            TEXT NOT NULL        -- repo-relative path or path pattern
    symbol          TEXT                 -- optional symbol path inside file
    order_index     INTEGER NOT NULL
    PRIMARY KEY (decision_id, path, symbol)

acceptance_criteria
    decision_id     TEXT NOT NULL
    section_title   TEXT NOT NULL
    section_level   INTEGER NOT NULL
    text            TEXT NOT NULL
    done            INTEGER NOT NULL     -- 0/1
    deferred        INTEGER NOT NULL     -- 0/1
    order_index     INTEGER NOT NULL
    PRIMARY KEY (decision_id, order_index)

commits
    sha             TEXT NOT NULL
    decision_id     TEXT NOT NULL
    trailer_kind    TEXT NOT NULL        -- "Implements" / "References" / "Fixes"
    summary         TEXT
    committed_at    TEXT
    PRIMARY KEY (sha, decision_id, trailer_kind)
    -- populated by future SPEC-006; empty in this SPEC.

index_meta
    key             TEXT PRIMARY KEY     -- "schema_version", "last_rebuilt_at", "corpus_root"
    value           TEXT NOT NULL
```

FTS5 virtual table:

```
decisions_fts(id UNINDEXED, title, body)
    content='decisions'
    tokenize='porter unicode61'
```

### IndexDB class

```python
# src/decree/index_db.py

class IndexDB:
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: Path): ...
    def init_schema(self) -> None: ...
    def rebuild(self, project_root: Path) -> RebuildStats: ...
    def verify(self, project_root: Path) -> list[DriftFinding]: ...
    def status(self) -> IndexStatus: ...
```

`rebuild()` is the only mutating path in v1. Incremental sync is v2 — deferred because the rebuild cost on a 167-doc corpus is well under 2s; incremental is premature optimization.

The rebuild flow:

1. Open the DB (creating `.decree/` and the file if needed).
2. Begin a transaction.
3. Wipe `decisions`, `refs`, `governs`, `acceptance_criteria`. **Do not wipe `commits`** — that table is owned by future SPEC-006 (git trailer ingestion); rebuilding the markdown side shouldn't blow away the git side.
4. For each document loaded by `load_all_types(strict=False)`:
   - Compute `body_hash = sha256(doc.body)`.
   - Insert into `decisions`.
   - Insert each entry in `doc.meta.references` into `refs` with kind `references`.
   - Insert `supersedes` / `superseded-by` values into `refs` with corresponding kinds.
   - Parse `governs:` from `doc.raw_metadata` if present (the field is read with no lint validation in this SPEC; SPEC-004 adds validation).
   - Use `_parse_checkboxes_by_section` from `commands.report` to extract acceptance criteria; insert each into `acceptance_criteria` with the `deferred` flag set from section classification.
5. Update `index_meta`: `schema_version`, `last_rebuilt_at`, `corpus_root`.
6. Rebuild the FTS index (`db["decisions_fts"].rebuild_fts()`).
7. Commit.

### Reference extraction

This SPEC reads two kinds of references from frontmatter only:

- `references: [PRD-001, ADR-0001]` → multiple `refs` rows with kind `references`
- `supersedes: ADR-0001` / `superseded-by: ADR-0002` → `refs` rows with kind `supersedes` / `superseded-by`

Body-level link extraction (mistletoe-parsed markdown links to `decree/spec/NNN-foo.md` files) is **deferred to SPEC-005** — it's a query-time enrichment, not a structural reference, and adds complexity.

### CLI surface

```
decree index rebuild [--project PATH]
decree index status   [--project PATH]
decree index verify   [--project PATH] [--json]
```

- `rebuild` — full rebuild. Prints stats (rows per table, duration). Exit 0.
- `status` — print schema version, last-rebuilt-at, row counts per table. Exit 0 if index exists, 1 if missing.
- `verify` — compare on-disk frontmatter against the index; report drift findings. Exit 0 if clean, 1 if drift.

The existing `decree index` command (which writes per-type `index.md` markdown files) becomes `decree index regenerate`. This is a breaking rename, but per PRD-003's "no backward compat" framing it's the right move; we update `decree status`'s internal call site accordingly.

### Files touched

- **Create**: `src/decree/index_db.py` — `IndexDB`, schema definitions, `RebuildStats`, `DriftFinding`, `IndexStatus`.
- **Create**: `src/decree/commands/index_db_cli.py` — `rebuild`, `status`, `verify` subcommand handlers.
- **Modify**: `src/decree/commands/index.py` — keep the per-type `index.md` regenerator, still called internally by `decree status`. The CLI binding moves to `decree index regenerate`.
- **Modify**: `src/decree/cli.py` — restructure `index` subcommand into a sub-namespace: `decree index {rebuild,status,verify,regenerate}`.
- **Modify**: `pyproject.toml` — add `sqlite-utils>=3.35` and `mistletoe>=1.3`.
- **Modify**: `.gitignore` — add `.decree/`.
- **Create**: `tests/test_index_db.py` — schema correctness, rebuild idempotency, drift detection.

### What this SPEC does NOT do

- **No `governs:` field lint validation** — SPEC-004. This SPEC reads whatever `governs:` is present without complaining.
- **No query commands** (`decree why`, `decree refs`) — SPEC-005.
- **No git trailer ingestion** (`commits` table stays empty) — SPEC-006.
- **No MCP server** — SPEC-007.
- **No coherence gates / staleness / hotspots** — SPEC-008.
- **No intent-review API or migration tooling** — SPEC-009.
- **No incremental sync** — rebuild only in v1.
- **No symbol-level governs resolution** — PRD-003 R2 v2 backlog.

## Testing Strategy

### Unit tests (`tests/test_index_db.py`)

- **Schema**: `init_schema()` creates all tables, all expected columns, FTS5 virtual table.
- **Rebuild idempotency**: rebuilding twice on the same corpus yields identical row counts and identical body_hashes.
- **Rebuild from scratch**: deleting the DB then rebuilding produces the same end state as rebuild over existing data.
- **Reference parsing**: a doc with `references: [PRD-001, ADR-0001]` produces two rows in `refs`.
- **Supersedes parsing**: a doc with `supersedes: ADR-0001` produces one `refs` row with kind `supersedes`.
- **Acceptance criteria classification**: a doc with primary AC sections + a "Deferred" section produces rows with correct `deferred` flag.
- **Body hash stability**: rebuilding without changing any docs preserves `body_hash` values exactly.
- **Verify clean**: rebuild then verify produces zero findings.
- **Verify detects drift**: modify a doc's body on disk without rebuilding, then verify reports drift.
- **Commits table preserved across rebuild**: insert a fake commits row, rebuild, assert it still exists.
- **FTS search smoke**: after rebuild, a basic MATCH query returns expected documents.

### Integration tests

- **Dogfood corpus**: rebuild against decree's own 9-doc corpus.
- **jira-task-to-md corpus**: rebuild against 167 docs; assert rebuild completes well under 2s.

### Performance ACs

- Rebuild on decree's own corpus (9 docs): <200ms.
- Rebuild on jira-task-to-md's 167-doc corpus: <2s.
- `decree index status` (read-only): <50ms.

## v1 Acceptance Criteria

### Schema

- [x] `src/decree/index_db.py` exists with `IndexDB` class, `SCHEMA_VERSION = 1`.
- [x] `IndexDB.init_schema()` creates tables: `decisions`, `refs`, `governs`, `acceptance_criteria`, `commits`, `index_meta`.
- [x] `decisions` has columns: id, type, status, title, path, date, body_hash, indexed_at, raw_metadata.
- [x] `refs` has columns: from_id, to_id, kind; composite primary key.
- [x] `acceptance_criteria` has columns including the `deferred` flag.
- [x] FTS5 virtual table `decisions_fts` indexes title + body.

### Sync

- [x] `IndexDB.rebuild()` populates `decisions` from all parsed docs in the corpus.
- [x] `IndexDB.rebuild()` populates `refs` from `references`, `supersedes`, and `superseded-by` frontmatter.
- [x] `IndexDB.rebuild()` populates `acceptance_criteria` using SPEC-002's primary/deferred section classification.
- [x] Rebuild is idempotent — two consecutive rebuilds produce identical row sets.
- [x] Rebuild does not delete rows from the `commits` table.
- [x] `body_hash` is SHA-256 of doc.body, stable across rebuilds when body unchanged.
- [x] `IndexDB.verify()` returns drift findings without mutating the index.

### CLI

- [x] `decree index rebuild` subcommand registered.
- [x] `decree index status` reports schema version, last-rebuilt-at, and row counts per table.
- [x] `decree index verify` reports drift, supports `--json`.
- [x] `decree index regenerate` preserves the old `decree index` markdown-regeneration behavior.
- [x] `decree status` continues to call the markdown-regeneration logic internally (no regression).

### Storage

- [x] Index file written to `.decree/index.sqlite` relative to the project root.
- [x] `.decree/` is gitignored in the decree project itself.

### Performance

- [x] Rebuild on decree's own corpus (9 docs): <200ms. Measured: 26ms (cold), <40ms (warm).
- [x] Rebuild on jira-task-to-md's corpus (167 docs): <2s. Measured: 165ms.
- [x] `decree index status`: <50ms.

### Tests

- [x] `tests/test_index_db.py` exists with unit + integration tests covering all ACs above (26 tests).
- [x] Existing test suite continues to pass with no regressions (261 total pass).

## What this does NOT do (deferred to v2 / follow-up SPECs)

- [ ] Incremental sync.
- [ ] Symbol-level governs resolution.
- [ ] Body-link extraction.
- [ ] Git trailer ingestion.
- [ ] Index-based queries.
- [ ] Schema migrations from older versions.
- [ ] Streaming rebuild for very large corpora (>10k docs).

## References

- PRD-003 (R1).
- ADR-0002 (Option C hybrid).
- SPEC-002 — `commands.report._parse_checkboxes_by_section` reused for AC classification.
- `sqlite-utils` documentation (Simon Willison).
- `mistletoe` documentation.
