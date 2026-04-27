# Changelog

All notable changes to Decree are documented here.

## Unreleased

- Remove vestigial hardcoded constants from `config.py` (now sourced from `ADR_DEFAULT` and `decree.toml`)
- Fix `adr index` typo in generated index files
- Fix silent `"adr"` fallback in `new` command
- Add pyproject.toml metadata (authors, classifiers, URLs)

## v1.0.0 — Multi-doctype Decree

Renamed from `madr-tools` to `decree`. Full rewrite as a general-purpose
document lifecycle toolkit.

- **Multi-doctype support** -- PRD, ADR, SPEC with independent lifecycles
- **`decree.toml` config** -- all types, statuses, transitions, and sections driven by TOML
- **Cross-type references** -- lint detects dangling and stale refs across doc types
- **C4 architecture support** -- opt-in C4 level tracking per document type
- **Progress tracking** -- `decree progress` reports checkbox completion across all docs
- **Model diagram** -- `decree model` generates PRD/ADR/SPEC relationship diagrams
- **Graph command** -- Mermaid timeline, supersede chain, and status pie charts
- **Claude Code skills** -- `/decree:prd`, `/decree:adr`, `/decree:spec`, `/decree:lint`, `/decree:init`, `/decree:ddd`

## v0.x — madr-tools

Initial single-type ADR management tool based on MADR v4.0.0.

- `new` -- create ADR with auto-numbering and slug
- `status` -- enforce lifecycle transitions (proposed/accepted/rejected/deprecated/superseded)
- `lint` -- frontmatter validation, required sections, supersede symmetry
- `index` -- auto-generated markdown table from frontmatter
- Pydantic-validated frontmatter, python-frontmatter I/O
