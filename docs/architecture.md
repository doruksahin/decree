# Architecture

## Module Map

```
src/decree/
├── config.py           ← single source of truth (core defaults + decree.toml loading)
├── doctypes.py         ← DocType dataclass — one instance per [types.*] section
├── identity.py         ← TYPE-ULID generation, validation, and filename construction
├── parser.py           ← ONLY module that touches document files on disk
├── validators.py       ← per-file and cross-file validation logic
├── template.py         ← template rendering with __VARIABLE__ placeholders
├── log.py              ← logging configuration
├── c4.py               ← C4 model diagram config and generation
├── model_diagram.py    ← document relationship diagram generation
├── cli.py              ← argparse entry point, dispatches to commands
├── commands/
│   ├── new.py          ← create document from template
│   ├── status.py       ← enforce lifecycle transitions
│   ├── lint.py         ← validate all documents (per-file + cross-file)
│   ├── index.py        ← explicit index.md regeneration
│   ├── index_db_cli.py ← explicit SQLite index rebuild/status/verify
│   ├── migrate.py      ← explicit corpus migrations and dry-run audits
│   ├── progress.py     ← scoped progress summary across document types
│   └── graph.py        ← dependency/reference graph generation
├── templates/
│   └── madr-v4.md      ← default MADR v4 template
└── examples/           ← example decree.toml and document files
```

## Design Principles

### Config as schema

`config.py` is the schema — no JSON schema file. Core MADR v4 rules are hardcoded tuples. Multi-type document configuration is loaded at runtime from `decree.toml` via `[types.*]` sections. Each type becomes a `DocType` instance in `doctypes.py`. Defensive asserts at import time catch drift between related constants.

### Pydantic at the boundary

`DocFrontmatter` (pydantic model) validates YAML frontmatter at the deserialization boundary in `parser.py`. All status enum checks, document ref format validation, and status-field invariants happen here. Config module uses bare tuples — no pydantic for static constants.

### Single I/O module

`parser.py` is the only module that reads/writes document files. Commands never call `open()` or `frontmatter.load()` directly. When `python-frontmatter` changes its API, you fix one file.

### Command interface

Every command module exposes `run(args: Namespace) -> int`. CLI dispatches to them. Generated artifacts are explicit: `decree index rebuild` refreshes the SQLite query cache, `decree index regenerate` refreshes markdown tables, and `decree report regenerate` refreshes report snapshots. Document creation does not silently refresh indexes.

## Data Flow

```
decree.toml [types.*]
        |
    config.py (loads doc type definitions)
        |
    doctypes.py (DocType instances)
        |
    parser.py (validates frontmatter, reads/writes files)
        |
    commands/ (new, status, lint, index, progress, graph)
        |
    cli.py (argparse dispatch)
        |
    `decree` CLI entry point
```

## Dependencies

| Library | Purpose | Why not stdlib |
|---------|---------|----------------|
| `pydantic>=2` | Frontmatter validation at parse boundary | Runtime validation with clear error messages |
| `python-frontmatter` | Parse markdown + YAML header | No stdlib equivalent for this exact task |
| `python-slugify` | Unicode-safe filename slug generation | Handles accented chars, non-Latin scripts |

## Review History

The early design went through multiple review rounds before implementation. Current behavior is defined by this repository's canonical PRD/ADR/SPEC corpus under `decree/`, not by historical implementation-plan notes.
