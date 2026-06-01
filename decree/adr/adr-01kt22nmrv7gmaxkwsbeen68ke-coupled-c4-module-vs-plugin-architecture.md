---
date: 2026-04-05
id: ADR-01KT22NMRV7GMAXKWSBEEN68KE
references:
- PRD-01KT22NMRR63TXR7NX5XYRG5FK
status: accepted
---

# ADR-01KT22NMRV7GMAXKWSBEEN68KE Coupled C4 Module vs Plugin Architecture

## Context and Problem Statement

PRD-01KT22NMRR63TXR7NX5XYRG5FK requires decree to validate C4 architecture metadata on SPECs. The question is how to integrate this: as a tightly coupled module in decree's core, or as a pluggable extension system that could support C4 and future metadata schemes.

Decree is ~4100 lines with 3 dependencies, used by one team. The C4 feature is ~200-300 lines of new code.

## Decision Drivers

- Decree has exactly one consumer for C4 support today
- Plugin architectures require stable public APIs before there's a second use case to validate against
- C4 is a well-defined, stable model — not a moving target
- LLMs reading decree.toml need to immediately understand what C4 means
- The cost of extracting a coupled module later (~2 hours) is far less than building a plugin system now (~weeks)

## Considered Options

### Option A: Coupled C4 module (`c4.py`)

All C4 code in `src/decree/c4.py` — validation functions and diagram generation. Called from `lint.py` and `graph.py`. Config: `[types.spec.c4]` section in decree.toml.

- Good: minimal code, immediate value, easy to understand, easy to extract later if needed
- Good: LLMs see `[types.spec.c4] enabled = true` and know exactly what it means
- Bad: if a second architecture model appears, refactoring is needed
- Risk: very low — extraction to a plugin is a 2-hour task with 200 lines of isolated code

### Option B: Plugin architecture with extension points

Three entry points: `decree.validators`, `decree.diagrams`, `decree.frontmatter`. Plugins register custom validators, diagram generators, and frontmatter field definitions.

- Good: fully extensible, future-proof for unknown use cases
- Bad: designing 3 stable public APIs for one consumer is premature
- Bad: plugin discovery/loading adds complexity and failure modes
- Bad: LLMs must understand the plugin system to use C4, instead of just reading config
- Risk: high — wrong abstractions become load-bearing before validated

### Option C: External hooks (post_lint, post_graph scripts)

Decree runs external scripts after its own checks. Config: `[hooks] post_lint = ["python scripts/lint_spec_contracts.py"]`.

- Good: zero changes to decree core
- Bad: two tools, two error formats, two mental models
- Bad: external scripts become permanent dependencies instead of migration scaffolding
- Risk: medium — scripts drift from decree's conventions over time

## Decision Outcome

**Option A: Coupled C4 module.** Because:

1. One consumer, ~200 lines of code. A plugin system for this is over-engineering.
2. Extraction cost if needed later: 2 hours. Plugin system cost now: weeks.
3. `[types.spec.c4] enabled = true` in config is immediately legible to LLMs and humans.
4. The structural concession: C4 code lives in its own file (`c4.py`), not mixed into `validators.py`. This gives isolation without framework overhead.
