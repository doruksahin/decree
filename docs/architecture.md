# Architecture

## Module Map

```
src/madr_tools/
├── config.py        ← single source of truth (core defaults + project overrides)
├── parser.py        ← ONLY module that touches ADR files on disk
├── cli.py           ← argparse entry point, dispatches to commands
├── commands/
│   ├── new.py       ← create ADR from template
│   ├── status.py    ← enforce lifecycle transitions
│   ├── lint.py      ← validate all ADRs (per-file + cross-file)
│   └── index.py     ← generate index.md from frontmatter
└── templates/
    └── madr-v4.md   ← default MADR v4 template
```

## Design Principles

### Config as schema

`config.py` is the schema — no JSON schema file. Core MADR v4 rules are hardcoded tuples. Project-specific extensions are loaded at runtime from `pyproject.toml [tool.adr]`. Defensive asserts at import time catch drift between related constants.

### Pydantic at the boundary

`ADRFrontmatter` (pydantic model) validates YAML frontmatter at the deserialization boundary in `parser.py`. All status enum checks, ADR ref format validation, and status-field invariants happen here. Config module uses bare tuples — no pydantic for static constants.

### Single I/O module

`parser.py` is the only module that reads/writes ADR files. Commands never call `open()` or `frontmatter.load()` directly. When `python-frontmatter` changes its API, you fix one file.

### Command interface

Every command module exposes `run(args: Namespace) -> int`. CLI dispatches to them. Commands that need index regeneration call `index.run()` directly.

## Data Flow

```
pyproject.toml [tool.adr]
        ↓
    config.py (loads project overrides)
        ↓
    parser.py (validates frontmatter, reads/writes files)
        ↓
    commands/ (new, status, lint, index)
        ↓
    cli.py (argparse dispatch)
        ↓
    `adr` CLI entry point
```

## Dependencies

| Library | Purpose | Why not stdlib |
|---------|---------|----------------|
| `pydantic>=2` | Frontmatter validation at parse boundary | Runtime validation with clear error messages |
| `python-frontmatter` | Parse markdown + YAML header | No stdlib equivalent for this exact task |
| `python-slugify` | Unicode-safe filename slug generation | Handles accented chars, non-Latin scripts |

## Review History

This design went through 6 rounds of expert review before implementation. The design doc and review log live in the consuming project at `docs/plans/2026-04-02-adr-toolkit-design.md`.
