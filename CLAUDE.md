# decree

Software decision lifecycle toolkit — PRDs, ADRs, SPECs with cross-type references, status enforcement, and validation.

## Quick Reference

```bash
decree new prd "Feature X"        # create PRD
decree new adr "Use Redis"        # create ADR
decree new spec "Cache Layer"     # create SPEC
decree status PRD-01KT22NMRTFTWFFARAN0PVEETA approve  # transition status
decree lint                       # validate all types + cross-refs
decree lint --check-attachments   # also validate attachment paths
decree index regenerate           # regenerate per-type indexes
decree index rebuild              # rebuild SQLite query cache
decree graph                      # Mermaid diagrams in index.md
decree progress                   # checkbox completion tracking
decree progress --changed --base origin/main  # scoped progress for parallel work
decree ddd --governs src/foo.py   # scoped lifecycle guidance
decree why src/foo.py             # path -> governing decisions
decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX  # reverse graph for one decision
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for module responsibilities.

```
src/decree/
  config.py      ← loads decree.toml, single source of truth
  parser.py      ← DocFrontmatter + DocDocument (Pydantic v2), only module that reads files
  validators.py  ← cross-file integrity + cross-type reference validation
  cli.py         ← argparse entry point
  commands/      ← one module per command namespace (new, status, lint, index, graph, progress, ddd, report, queries, ...)
```

Details: [src/decree/CLAUDE.md](src/decree/CLAUDE.md)

## Config

All config in `decree.toml` (not pyproject.toml). See [docs/configuration.md](docs/configuration.md) for full schema.

## Key Design Decisions

- `config.py` is the single source of truth for format rules
- `parser.py` is the only module that touches document files on disk
- Canonical document IDs are frontmatter `TYPE-ULID`; `decree migrate ids` converts legacy numeric corpora.
- `warn_on_reference` (dead statuses) != terminal statuses — "implemented" is terminal but healthy to reference
- Staleness is direct-only, not transitive
- C4 is coupled in `c4.py`, not pluggable ([decree/adr/adr-01kt22nmrv7gmaxkwsbeen68ke-coupled-c4-module-vs-plugin-architecture.md](decree/adr/adr-01kt22nmrv7gmaxkwsbeen68ke-coupled-c4-module-vs-plugin-architecture.md))

## Development

```bash
uv run pytest -q                                      # tests
uv run ruff check src/ tests/                         # lint
uv run ruff format src/ tests/                        # format
lychee --config .lychee.toml --no-progress '**/*.md'  # online markdown link check
uv run decree lint                                    # validate dogfood docs
```

Pre-commit runs ruff, lychee, and pytest automatically. CI runs pytest on Python 3.11-3.13, plus ruff and lychee.

See [CONTRIBUTING.md](CONTRIBUTING.md) for developer guidelines — rules for adding commands, extending config, writing tests, and code style.

## Testing

See [tests/CLAUDE.md](tests/CLAUDE.md) for test conventions and fixtures.

## Dogfooding

Decree manages its own decisions in `decree/`:

- [PRD-01KT22NMRR63TXR7NX5XYRG5FK](decree/prd/prd-01kt22nmrr63txr7nx5xyrg5fk-c4-architecture-support.md): C4 Architecture Support
- [ADR-01KT22NMRV7GMAXKWSBEEN68KE](decree/adr/adr-01kt22nmrv7gmaxkwsbeen68ke-coupled-c4-module-vs-plugin-architecture.md): Coupled C4 module vs plugin architecture
- [SPEC-01KT22NMRWENYKC3MGRA50M7GE](decree/spec/spec-01kt22nmrwenykc3mgra50m7ge-c4-validation-and-diagram-generation.md): C4 validation and diagram generation
