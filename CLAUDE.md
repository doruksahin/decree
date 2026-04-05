# decree

Software decision lifecycle toolkit — manage PRDs, ADRs, and SPECs with cross-type references, status enforcement, and validation.

## Document Model

![Decree document model](docs/model.png)

PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation. See `src/decree/model_diagram.py` to regenerate.

## Quick Reference

```bash
# Multi-type CLI (primary)
decree new prd "Feature X"              # create PRD
decree new adr "Use Redis"              # create ADR
decree new spec "Cache Layer"           # create SPEC
decree status PRD-001 approve           # transition status
decree lint                             # validate all types + cross-refs
decree index                            # regenerate per-type indexes
decree progress                         # checkbox completion tracking
decree graph                            # Mermaid diagrams

# Backward-compat ADR CLI
adr new "title"                         # create ADR (same as decree new adr)
adr status accept ADR-0004              # transition (ADR-only syntax)
adr lint                                # validate ADRs only
```

## Architecture

```
src/decree/
  doctypes.py       ← DocType dataclass (prefix, statuses, transitions, warn_on_reference)
  config.py         ← loads [types.*] from decree.toml
  parser.py         ← DocFrontmatter + DocDocument (Pydantic v2, type-parameterized)
  validators.py     ← cross-file integrity + cross-type reference validation
  scanner.py        ← (not yet) reference scanning
  cli.py            ← argparse: decree (multi-type) + adr (backward compat)
  commands/         ← new, status, lint, index, graph, progress
  templates/        ← per-type markdown templates
  examples/         ← bundled PRD/ADR/SPEC examples for init scaffolding
  model_diagram.py  ← Graphviz DOT generator for the document model
```

## Key Design Decisions

- `warn_on_reference` (dead statuses) != `terminal_statuses` — "implemented" is terminal but healthy to reference
- Cross-type references in YAML frontmatter: `references: [PRD-001, ADR-0001]`
- Staleness is direct-only, not transitive
- Circular references allowed, self-references flagged
- `config.py` is the single source of truth for format rules
- `parser.py` is the only module that touches document files on disk

## Running

```bash
uv run pytest                    # run tests (142 total)
uv run decree lint               # validate docs
uv run decree progress           # checkbox tracking
uv tool install -e .             # install globally
```
