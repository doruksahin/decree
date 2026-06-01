# src/decree/commands/AGENTS.md

Applies to command modules under `src/decree/commands/`.

## Command Shape

- Every command module exposes `run(args: argparse.Namespace) -> int`.
- Return `0` for success, `1` for user-facing failure, and `2` only when the
  command contract already documents a configuration error exit.
- Do not call `sys.exit()` in command modules.
- Register argparse options in `src/decree/cli.py`.
- Keep `--help` text explicit enough for an LLM agent to use without reading
  implementation code.

## State and Side Effects

- Use parsed documents from `parser.py`; do not reimplement frontmatter reads.
- Do not silently mutate generated artifacts as a side effect of unrelated
  commands.
- If a command writes files, document exactly which files it writes in help and
  docs.
- Batch commands should report per-item errors instead of hiding them.
- Query commands must not fall back to stale indexed data.

## Adding a Command

1. Create `src/decree/commands/<name>.py`.
2. Add a parser and dispatch entry in `src/decree/cli.py`.
3. Add tests in `tests/test_<name>.py`.
4. Update [../../../docs/usage.md](../../../docs/usage.md) and relevant
   capability docs.
5. Add a `changelog.d/` fragment if the command is user-visible.

## Existing Command Families

- `index_db_cli.py`: SQLite index rebuild/status/verify.
- `queries.py`: `why` and `refs`; index-backed governance queries.
- `intent_check.py`: pre-code plan governance.
- `intent_review.py`: post-code diff governance.
- `migrate.py`: explicit corpus migrations and LLM-assisted backfills.
- `report.py`: completion report snapshots.
- `commit.py`: git commit wrapper and trailer sync.

## Tests to Consider

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_<command>.py -q
uv run pytest tests/test_integration.py -q
```
