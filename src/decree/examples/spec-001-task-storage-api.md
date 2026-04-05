---
status: approved
date: 2026-01-20
references: [PRD-001, ADR-0001]
---

# SPEC-001 Task Storage API

## Overview

Design the storage layer for the task CLI, implementing the SQLite backend chosen in ADR-0001 to satisfy the persistence and query requirements from PRD-001. This spec defines the schema, the Python API, and the error handling contract.

## Technical Design

### Schema

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'todo'
                        CHECK (status IN ('todo', 'doing', 'done')),
    priority    TEXT    DEFAULT 'med'
                        CHECK (priority IN ('low', 'med', 'high')),
    due_date    TEXT    DEFAULT NULL,  -- ISO 8601 date or NULL
    created_at  TEXT    NOT NULL,      -- ISO 8601 datetime
    updated_at  TEXT    NOT NULL       -- ISO 8601 datetime
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
```

Schema version starts at `1`. On startup, check `schema_version` table. If absent or outdated, run migrations sequentially. Never drop tables — only additive migrations.

### Python API

```python
class TaskStore:
    def __init__(self, db_path: Path):
        """Open or create the database. Run migrations if needed."""

    def add(self, title: str, priority: str = "med", due_date: str | None = None) -> Task:
        """Insert a task. Returns the created Task with assigned ID."""

    def get(self, task_id: int) -> Task:
        """Fetch by ID. Raises TaskNotFound if missing."""

    def list(self, status: str | None = None, priority: str | None = None,
             sort_by: str = "created_at") -> list[Task]:
        """Filter and sort. None means no filter on that field."""

    def update(self, task_id: int, **fields) -> Task:
        """Update specific fields. Raises TaskNotFound. Validates status/priority values."""

    def delete(self, task_id: int) -> None:
        """Hard delete. Raises TaskNotFound if missing."""
```

Every method that writes runs inside a `with self.conn:` transaction block — SQLite commits on exit, rolls back on exception. This is the crash-safety guarantee from ADR-0001.

### Error Handling

| Error | When | Behavior |
|-------|------|----------|
| `TaskNotFound` | `get`, `update`, `delete` with nonexistent ID | Raise. CLI prints "Task {id} not found." and exits 1. |
| `InvalidStatus` | `update(status="invalid")` | Raise before touching DB. CLI prints valid values. |
| `InvalidPriority` | Same pattern | Same pattern. |
| `DatabaseCorrupted` | Schema version missing or file unreadable | Raise. CLI prints "Database corrupted. Run `task repair` or restore from backup." |

No silent fallbacks. Every error surfaces to the user with a clear message and a suggested action.

### File Location

The database file is `.task.db` in the current working directory (closest ancestor with a `.git/` directory, or cwd if no git repo). This mirrors how tools like `.env` and `.eslintrc` work — project-scoped by convention.

Lookup order:
1. `$TASK_DB` environment variable (explicit override)
2. Walk up from cwd to find `.git/`, place `.task.db` beside it
3. Fall back to cwd

## Testing Strategy

### Unit tests (no filesystem)

- `TaskStore` with `:memory:` SQLite — test CRUD operations, filtering, sorting
- Schema migration: create v1 DB, run v2 migration, verify data preserved
- Error cases: `TaskNotFound`, `InvalidStatus`, `InvalidPriority`
- Concurrent access: two `TaskStore` instances on same file, verify WAL mode prevents corruption

### Integration tests (real filesystem)

- Create `.task.db` in tmp_path, add 100 tasks, verify persistence after re-open
- Kill-and-recover: write task, force-close connection (no commit), reopen — verify WAL recovery
- Performance: 10,000 tasks, `list(priority="high")` < 100ms (from ADR-0001 validation criteria)

### CLI tests (subprocess)

- `task add "Test" | task list` round-trip
- `task list --json | python -c "import json, sys; json.load(sys.stdin)"` — valid JSON
- Exit codes: 0 for success, 1 for not-found, 2 for invalid input
