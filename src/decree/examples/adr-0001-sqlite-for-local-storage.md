---
status: accepted
date: 2026-01-18
references: [PRD-001]
---

# ADR-0001 SQLite for Local Storage

## Context and Problem Statement

PRD-001 requires tasks to persist locally, survive crashes (atomic writes), and respond in sub-second time. We need to choose a storage backend that meets these constraints without requiring a server process.

Three realistic options exist for local CLI storage: a flat JSON file, SQLite, or an embedded key-value store (e.g., LevelDB). The choice affects data integrity guarantees, query flexibility, dependency footprint, and migration path if the tool grows.

## Decision Drivers

- Atomic writes required (PRD-001: "data is not lost on crash")
- Sub-second response for all operations
- Zero server processes — must work as a library, not a daemon
- JSON output support (PRD-001: machine-parseable output)
- Future filtering/sorting needs (by status, priority, due date)
- Dependency footprint — fewer external dependencies is better

## Considered Options

### Option A: Flat JSON file

Read entire file into memory, modify, write back.

- Good: zero dependencies, human-readable on disk, trivial to debug
- Bad: no atomic writes without careful temp-file-rename dance. Concurrent access corrupts data. Filtering requires loading everything into memory. At 10,000+ tasks, read/write becomes slow.
- Risk: crash during write = data loss. The temp-file-rename pattern fixes this but must be implemented correctly (fsync + rename is the only safe sequence on Linux).

### Option B: SQLite (via built-in sqlite3 module)

Single-file database with SQL query support.

- Good: atomic transactions (WAL mode), zero-dependency (Python ships sqlite3), SQL filtering/sorting for free, battle-tested at billions of deployments, single file easy to backup/move
- Bad: not human-readable on disk (binary format), slight learning curve for raw SQL (mitigated by a thin Python wrapper), schema migrations needed as the model evolves
- Risk: SQLite's WAL mode requires the filesystem to support shared-memory. NFS and some network drives break this. For a local CLI tool, this is acceptable.

### Option C: Embedded key-value store (LevelDB / LMDB)

Key-value semantics, fast reads and writes.

- Good: faster than SQLite for simple key-value lookups, good for append-heavy workloads
- Bad: external dependency (not in Python stdlib), no query language (filtering requires scanning all keys), harder to inspect data for debugging, fewer developers know the API
- Risk: over-engineered for a task list. Key-value is ideal for caches and logs, not structured records with multiple query patterns.

## Decision Outcome

**SQLite (Option B)**, because:

1. Atomic writes are guaranteed by SQLite's transaction model — we don't have to implement crash safety ourselves
2. Zero external dependencies — Python's `sqlite3` module is always available
3. SQL gives us filtering and sorting for free (`SELECT * FROM tasks WHERE priority = 'high' ORDER BY due_date`)
4. Single file is easy to backup (`cp tasks.db tasks.db.bak`) and move between machines
5. The performance ceiling is orders of magnitude beyond what a task CLI will ever need

The flat JSON approach (Option A) is tempting for simplicity but fails the atomic-write requirement without implementing the exact same crash-safety patterns that SQLite already provides. Option C solves a problem we don't have.

## Consequences

- Storage layer wraps `sqlite3` with a thin Python class — no ORM, no SQLAlchemy
- Schema versioning from day one: a `schema_version` table, checked on startup
- JSON output is produced by Python dict serialization, not by SQLite's JSON functions
- The `.task.db` file lives in the project root (like `.git/`) — add to `.gitignore`
- Users cannot hand-edit the database — provide `task export --json` for data portability

## Affected Files

- `src/task_cli/storage.py` — new file, SQLite wrapper
- `src/task_cli/models.py` — Task dataclass
- `tests/test_storage.py` — round-trip tests
- `.gitignore` — add `*.task.db`

## Validation Needed

1. Write a test that kills the process mid-write and verifies no data loss (WAL mode recovery)
2. Benchmark: 10,000 tasks, `task list --filter priority=high` completes in < 100ms
3. Verify `sqlite3` module is available in Python 3.11+ on both macOS and Linux (it is, but test in CI)
