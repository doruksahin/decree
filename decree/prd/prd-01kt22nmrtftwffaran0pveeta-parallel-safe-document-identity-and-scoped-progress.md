---
date: '2026-06-01'
id: PRD-01KT22NMRTFTWFFARAN0PVEETA
status: implemented
---

# PRD-01KT22NMRTFTWFFARAN0PVEETA Parallel-Safe Document Identity and Scoped Progress

## Problem Statement

Decree previously derived document identity from legacy sequential numeric filenames.
That works in a single linear workflow, but it creates avoidable merge conflicts when multiple agents
or git worktrees create PRDs, ADRs, or SPECs in parallel. The same coupling also makes global progress
views noisy: an agent working on one branch sees every document in the corpus instead of the current
document, chain, changed set, or governed files it is responsible for.

The library is intended for LLM-heavy workflows, so the rules must be explicit and self-describing.
There should be no hidden fallback where a document sometimes gets its identity from the filename and
sometimes from metadata.

## Requirements

- Generate collision-resistant document IDs locally without coordinating through a central sequence.
- Store canonical document identity explicitly in frontmatter as `id: TYPE-...`.
- Treat missing or malformed `id` metadata as a validation error in normal operation.
- Provide an explicit migration command for legacy sequential corpora instead of runtime dual-mode compatibility.
- Keep generated artifacts explicit: creating a document must not silently regenerate indexes or reports.
- Let progress and DDD assessment run against useful scopes: a single document, a document chain, changed docs, or docs governing a path.
- Preserve LLM usability through clear CLI help, deterministic output, and documentation of responsibilities.

## Success Criteria

- Two branches or worktrees can create new documents concurrently without filename or ID collisions.
- `decree lint` rejects normal documents that lack `id:` after migration.
- `decree migrate ids --dry-run` reports an old-to-new mapping without modifying files.
- `decree migrate ids --apply` rewrites IDs, filenames, structured references, reports, and indexes deterministically.
- `decree progress --doc`, `--chain`, `--changed`, and `--governs` show scoped results with the selected scope printed.
- The decree repository can dogfood the migration on its own corpus and pass lint, index verification, link checking, and tests.

## Scope

In scope: document identity generation, parser/config changes, migration tooling, scoped progress, scoped DDD assessment, CLI documentation, repository migration, and tests.

Out of scope: preserving old sequential IDs as a runtime compatibility mode, automatic rewriting of arbitrary prose mentions, and cross-repository central ID reservation services.
