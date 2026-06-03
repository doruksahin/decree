# src/decree

## Module Map

| Module | Role | Key rule |
|--------|------|----------|
| [config.py](config.py) | Loads `decree.toml`, discovers project root | Single source of truth for all format rules. Uses `lru_cache` — tests must call `cache_clear()` |
| [parser.py](parser.py) | `DocFrontmatter` + `DocDocument` (Pydantic v2) | **Only module that reads/writes document files.** All other modules receive parsed objects |
| [doctypes.py](doctypes.py) | `DocType` frozen dataclass | Defines canonical ID pattern, lifecycle, transitions. Migration-only numeric handling lives in `commands/migrate.py` |
| [validators.py](validators.py) | Cross-file integrity + cross-type references | Pure functions: take doc lists, return error strings. No file I/O |
| [c4.py](c4.py) | C4 validation + Mermaid C4Container diagrams | Opt-in: only activated when `[types.*.c4]` exists in config. Reads `raw_metadata` for C4 fields |
| [cli.py](cli.py) | argparse entry point | Dispatches to `commands/` modules |
| [log.py](log.py) | `info()`, `error()`, `success()`, `fail()` | All output goes to stderr. Stdout is reserved for machine-readable output |
| [template.py](template.py) | Fills template placeholders for `decree new` | Appends required sections not already in the template |
| [model_diagram.py](model_diagram.py) | Graphviz DOT generator for the document model | Output: `docs/model.png`. Run with `uv run python -m decree.model_diagram` |

## Commands

Each file in `commands/` is one CLI subcommand. All export a `run(args)` function returning an exit code.

| Command | File | Notes |
|---------|------|-------|
| `new` | [commands/new.py](commands/new.py) | Generates `TYPE-ULID`, slugifies title, stamps date; derived indexes are explicit |
| `status` | [commands/status.py](commands/status.py) | Enforces transition rules. Supersede links both docs bidirectionally |
| `lint` | [commands/lint.py](commands/lint.py) | Aggregates errors from `validators.py` + `c4.py`. `--check-attachments` is opt-in |
| `index` | [commands/index.py](commands/index.py) | Generates markdown table + `GRAPH_MARKER` per type. `graph.py` imports the marker from here |
| `graph` | [commands/graph.py](commands/graph.py) | Appends Mermaid diagrams below the marker. Auto-runs `index` if marker is missing |
| `progress` | [commands/progress.py](commands/progress.py) | Counts primary `- [x]` / `- [ ]` checkboxes, with all/doc/chain/changed/governs scopes and separate deferred counts |
| `ddd` | [commands/ddd.py](commands/ddd.py) | Lifecycle assessment and next action; supports doc/chain/changed/governs scopes |
| `report` | [commands/report.py](commands/report.py) | Explicit completion-report regeneration; no hidden refresh during lint |
| `commit` | [commands/commit.py](commands/commit.py) | Git commit wrapper for canonical `Implements:`/`Refs:`/`Fixes:` trailers |
| `health` / `stale` | [commands/health.py](commands/health.py) | Stale decisions, ungoverned hotspots, dead-governance (findings), advisory suggested-governance — reads `observed_governs`; never feeds `queries.py`. See [health-signals.md](../../docs/health-signals.md) |
| `why` / `refs` | [commands/queries.py](commands/queries.py) | SQLite-index-backed governance queries; never silently re-parse markdown |
| `mcp serve` | [commands/mcp_server.py](commands/mcp_server.py) | FastMCP server exposing `why`/`refs`/`stale`/`health`/`intent_check`/`intent_review`/`progress`/`report` as agent tools; thin wrappers over command cores, no duplicate query logic |

## Data Flow

```
decree.toml → config.py → DocType instances
                              ↓
document files → parser.py → DocDocument instances
                                    ↓
                           validators.py (cross-ref checks)
                           c4.py (C4 hierarchy checks)
                           commands/* (CLI operations)
```

## Conventions

- **No hardcoded doc types.** Runtime projects load document types from `decree.toml` via `config.py`. `ADR_DEFAULT` is only for direct parser/model construction when no project config is present.
- **`raw_metadata`** on `DocDocument` stores the full frontmatter dict. `DocFrontmatter` (Pydantic model) only captures decree's own fields. C4 fields and unknown fields live in `raw_metadata`.
- **Exit codes:** `0` = success, `1` = error. Commands return `int`, `cli.py` calls `sys.exit()`.
- **`GRAPH_MARKER`** is defined in `commands/index.py` and imported by `commands/graph.py` — single source of truth.
