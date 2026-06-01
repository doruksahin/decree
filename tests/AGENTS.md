# tests/AGENTS.md

Applies to tests under `tests/`.

Read [../AGENTS.md](../AGENTS.md) first. This file explains test conventions.

## Test Principles

- Use `tmp_path` for filesystem work.
- Tests that need a project root should `monkeypatch.chdir(project_dir)`.
- Do not write outside pytest temporary directories.
- Prefer real file I/O over mocks for decree documents.
- Keep command tests close to the command module they cover.
- When adding cached functions, clear them in the autouse `reset_caches`
  fixture in `conftest.py`.

## Targeted Runs

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_parser.py -q
uv run pytest tests/test_queries.py -q
uv run pytest -k supersede
```

Run the full suite before final handoff:

```bash
uv run pytest -q
```

## Coverage Map

- CLI parsing and `--help`: `test_cli.py`.
- Config loading and root discovery: `test_config.py`.
- Frontmatter parsing and raw metadata: `test_parser.py`.
- Cross-reference validation: `test_validators.py`.
- Document creation: `test_new.py`.
- Lifecycle transitions: `test_status.py`.
- SQLite index and git trailers: `test_index_db.py`.
- `why` / `refs`: `test_queries.py`.
- LLM provider behavior: `test_llm_io.py`.
- Migrations: `test_migrate_ids.py`, `test_migrate_governs.py`,
  `test_migrate_audit.py`.
- Planning and review guards: `test_intent_check.py`,
  `test_intent_review.py`.
- Release/version CLI behavior: `test_cli.py`.

The older [CLAUDE.md](CLAUDE.md) file has a broader fixture map. Prefer this
AGENTS file for current rules and use CLAUDE.md only for extra detail.
