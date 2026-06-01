# src/decree/AGENTS.md

Applies to Python package code under `src/decree/`.

Read [../../AGENTS.md](../../AGENTS.md) first. Read this file when changing
implementation code.

## Architecture Rules

- `config.py` owns `decree.toml` loading and project-root discovery.
- `parser.py` owns source decision-document reads and writes.
- `validators.py` stays pure: inputs are parsed documents, outputs are error
  strings.
- `cli.py` owns argparse registration and dispatch only.
- `commands/*` owns command behavior. See [commands/AGENTS.md](commands/AGENTS.md).
- `index_db.py` owns the SQLite query cache schema and sync logic.
- `llm_io.py` owns LLM model resolution, Claude Code subprocess routing, and
  shared JSON parsing.
- `version.py` owns package version reads from installed metadata.

## Invariants

- Canonical document IDs are frontmatter `TYPE-ULID`.
- Legacy numeric IDs are migration input only.
- Runtime code must not derive identity from filenames.
- Query commands must fail closed on missing or stale indexes.
- Generated artifacts are explicit: index rebuild, markdown index regenerate,
  graph generation, and report regeneration are separate commands.
- LLM-backed behavior must expose provider choice and per-call errors.

## Output Rules

- Human diagnostics go to stderr through `log.py`.
- Machine-readable output goes to stdout.
- `--json` output must remain stable for agents.
- Do not add progress text to stdout for JSON commands.

## Before Editing

Run a scoped governance lookup for the file you will change:

```bash
uv run decree why src/decree/parser.py
uv run decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX
```

If no decision governs the file, say so explicitly in your handoff. Do not
invent a governing SPEC.

## Testing

Prefer a targeted test first:

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_queries.py -q
```

Then run full validation from [../../AGENTS.md](../../AGENTS.md) before handoff.
