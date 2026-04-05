# Configuration

All configuration lives in the consuming project's `pyproject.toml` under `[tool.adr]`.

## Options

```toml
[tool.adr]
# Directory where ADR files live (relative to project root)
# Default: "docs/adr"
adr_dir = "docs/adr"

# Project-specific required sections appended after MADR v4 standard sections
# Default: [] (only MADR v4 sections enforced)
project_sections = [
    "Consequences",
    "Affected Files",
    "Validation Needed",
]

# Custom template file (relative to project root)
# Default: bundled MADR v4 template
# template = "templates/my-adr-template.md"

[tool.adr.project_section_descriptions]
# LLM-facing descriptions for project sections.
# Used by `adr new` to populate section guidance text.
Consequences = "Good, bad, and neutral consequences of this decision."
"Affected Files" = "Paths relative to project root, one per bullet."
"Validation Needed" = "What evidence or check is required before implementation?"
```

## Zero-config

If `[tool.adr]` is absent, decree uses defaults:
- ADR directory: `docs/adr`
- Required sections: MADR v4 standard only (Context and Problem Statement, Considered Options, Decision Outcome)
- Template: bundled default

## MADR v4 Standard Sections (always enforced)

These are hardcoded in the package and cannot be removed:

1. Context and Problem Statement
2. Considered Options
3. Decision Outcome

## Status Lifecycle (not configurable)

```
proposed → accepted | rejected
accepted → deprecated | superseded
rejected    (terminal)
deprecated  (terminal)
superseded  (terminal)
```

## Custom Templates

Override the default template by setting `template` in `[tool.adr]`:

```toml
[tool.adr]
template = "templates/my-adr-template.md"
```

Templates use `__VARIABLE__` placeholders (not `{braces}`):
- `__NUMBER__` — zero-padded ADR number (e.g. `0004`)
- `__TITLE__` — raw title from CLI argument
- `__SLUG__` — slugified title (e.g. `use-pulp-solver`)
- `__DATE__` — today's date in ISO 8601 (e.g. `2026-04-02`)

Project sections from `[tool.adr] project_sections` are appended after the template content by the `new` command.
