# decree

Decree — software decision lifecycle toolkit (MADR v4.0.0 ADR management for CLI and LLMs).

## Quick Reference

```bash
adr new "title"                        # create ADR
adr status accept ADR-0004             # accept
adr status reject ADR-0004             # reject (terminal)
adr status deprecate ADR-0002          # deprecate (terminal)
adr status supersede ADR-0001 ADR-0005 # supersede with symmetric links
adr lint                               # validate all ADRs
adr index                              # regenerate index.md
```

## Docs

- [Usage Scenarios](docs/usage.md) — all commands, workflows, and integration points
- [Configuration](docs/configuration.md) — `pyproject.toml [tool.adr]` options
- [Architecture](docs/architecture.md) — module design, config as schema, pydantic boundary

## Key Rules

- `config.py` is the single source of truth for format rules
- `parser.py` is the only module that touches ADR files on disk
- Status transitions are enforced: `proposed → accepted | rejected`, `accepted → deprecated | superseded`
- Superseded ADRs must have symmetric links (A→B and B→A)
- Project-specific sections come from `pyproject.toml [tool.adr]`, not hardcoded
