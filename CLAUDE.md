# decree

Software decision lifecycle toolkit — manage PRDs, ADRs, and SPECs with cross-type references, status enforcement, C4 architecture validation, and progress tracking.

## Document Model

![Decree document model](docs/model.png)

PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation. See `src/decree/model_diagram.py` to regenerate.

## Quick Reference

```bash
decree new prd "Feature X"              # create PRD
decree new adr "Use Redis"              # create ADR
decree new spec "Cache Layer"           # create SPEC
decree status PRD-001 approve           # transition status
decree lint                             # validate all types + cross-refs + C4
decree index                            # regenerate per-type indexes
decree progress                         # checkbox completion tracking
decree graph                            # Mermaid diagrams + C4 container view
```

## Architecture

```
src/decree/
  doctypes.py       ← DocType dataclass (prefix, statuses, transitions, warn_on_reference, c4)
  config.py         ← loads [types.*] from decree.toml
  parser.py         ← DocFrontmatter + DocDocument (Pydantic v2, type-parameterized)
  validators.py     ← cross-file integrity + cross-type reference validation
  c4.py             ← C4Config, validate_c4(), generate_c4_container() (opt-in)
  cli.py            ← argparse: decree entry point
  commands/         ← new, status, lint, index, graph, progress
  templates/        ← per-type markdown templates
  examples/         ← bundled PRD/ADR/SPEC examples for init scaffolding
  model_diagram.py  ← Graphviz DOT generator for the document model
```

## Config

All config lives in `decree.toml` (not pyproject.toml). Schema:

```toml
[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
# ... statuses, transitions, actions, warn_on_reference, required_sections

# Opt-in C4 architecture support
[types.spec.c4]
enabled = true
id_field = "id"
levels = ["system", "container", "component"]
```

## C4 Architecture Support

When `[types.spec.c4]` is configured, decree validates C4 metadata in spec frontmatter:

```yaml
---
status: approved
date: 2026-04-05
references: [PRD-001, ADR-0001]

id: demand_model
c4_type: container
c4_name: Demand Model
c4_tech: Python / scipy
parent: markdown_optimization_poc
depends-on: ["data_preparation"]
---
```

`decree lint` checks: field presence, c4_type validity, parent/depends-on resolution, duplicate C4 ids, dead node filtering.

`decree graph` generates C4Container Mermaid diagrams.

Key distinction: `references` is decree's document chain (SPEC references ADR). `depends-on` is C4's component chain (demand_model depends on data_preparation). Different concepts, coexist in same frontmatter.

## Key Design Decisions

- `warn_on_reference` (dead statuses) != `terminal_statuses` — "implemented" is terminal but healthy to reference
- Cross-type references in YAML frontmatter: `references: [PRD-001, ADR-0001]`
- Staleness is direct-only, not transitive
- Circular references allowed, self-references flagged
- C4 is coupled (in `c4.py`), not pluggable (ADR-0001)
- `config.py` is the single source of truth for format rules
- `parser.py` is the only module that touches document files on disk

## Dogfooding

Decree manages its own decisions in `decree/`:
- PRD-001: C4 Architecture Support
- ADR-0001: Coupled C4 module vs plugin architecture
- SPEC-001: C4 validation and diagram generation

## Running

```bash
uv run pytest                    # run tests (160 total)
uv run decree lint               # validate docs
uv run decree progress           # checkbox tracking
uv tool install -e .             # install globally
```
