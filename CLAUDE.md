# decree

Software decision lifecycle toolkit — PRDs, ADRs, SPECs with cross-type references, status enforcement, and validation.

## Quick Reference

```bash
decree new prd "Feature X"        # create PRD
decree new adr "Use Redis"        # create ADR
decree new spec "Cache Layer"     # create SPEC
decree status PRD-001 approve     # transition status
decree lint                       # validate all types + cross-refs
decree lint --check-attachments   # also validate attachment paths
decree index                      # regenerate per-type indexes
decree graph                      # Mermaid diagrams in index.md
decree progress                   # checkbox completion tracking
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for module responsibilities.

```
src/decree/
  config.py      ← loads decree.toml, single source of truth
  parser.py      ← DocFrontmatter + DocDocument (Pydantic v2), only module that reads files
  validators.py  ← cross-file integrity + cross-type reference validation
  cli.py         ← argparse entry point
  commands/      ← one module per command (new, status, lint, index, graph, progress)
```

Details: [src/decree/CLAUDE.md](src/decree/CLAUDE.md)

## Config

All config in `decree.toml` (not pyproject.toml). See [docs/configuration.md](docs/configuration.md) for full schema.

## Key Design Decisions

- `config.py` is the single source of truth for format rules
- `parser.py` is the only module that touches document files on disk
- `warn_on_reference` (dead statuses) != terminal statuses — "implemented" is terminal but healthy to reference
- Staleness is direct-only, not transitive
- C4 is coupled in `c4.py`, not pluggable ([decree/adr/0001-coupled-c4-module-vs-plugin-architecture.md](decree/adr/0001-coupled-c4-module-vs-plugin-architecture.md))

## Development

```bash
uv run pytest -q               # 175 tests
uv run ruff check src/ tests/  # lint
uv run ruff format src/ tests/ # format
lychee '**/*.md'                # link check
uv run decree lint              # validate dogfood docs
```

Pre-commit runs ruff, lychee, and pytest automatically. CI runs the same on Python 3.11-3.13.

## Testing

See [tests/CLAUDE.md](tests/CLAUDE.md) for test conventions and fixtures.

## Dogfooding

Decree manages its own decisions in `decree/`:

- [PRD-001](decree/prd/001-c4-architecture-support.md): C4 Architecture Support
- [ADR-0001](decree/adr/0001-coupled-c4-module-vs-plugin-architecture.md): Coupled C4 module vs plugin architecture
- [SPEC-001](decree/spec/001-c4-validation-and-diagram-generation.md): C4 validation and diagram generation
