---
date: '2026-06-01'
id: ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ
references:
- PRD-01KT22NMRTFTWFFARAN0PVEETA
status: accepted
---

# ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ Use Distributed Frontmatter IDs for Parallel Work

## Context and Problem Statement

Decree's original identity model couples document identity, filename ordering, and creation order:
`decree new` scans existing numeric filenames, chooses the next number, writes the file, then regenerates indexes.
That model is simple but hostile to parallel git worktrees and LLM agents. Two workers creating documents at the
same time can both choose the same next number. Even when git later reports the conflict, the agent has already
created ambiguous references.

The tool must support local-first, offline document creation with explicit rules. Backward compatibility with old
sequential corpora is less important than a clear, high-quality model for future projects.

## Decision Drivers

- Parallel branches and worktrees must create documents without coordination.
- Document references must be stable, explicit, and easy for LLMs to inspect.
- The normal parser must not hide missing metadata behind filename fallback.
- Migration must be auditable and deterministic.
- Generated indexes and reports must remain derived artifacts with explicit commands.

## Considered Options

- Keep sequential IDs and add a lock or reservation file. This preserves readability but does not work well across independent worktrees and still produces merge conflicts.
- Add random suffixes to sequential IDs. This reduces collisions but keeps two identity schemes in one string and makes the rules harder to explain.
- Use UUIDv4 filenames. This is collision-resistant but not time-sortable and is unnecessarily opaque for humans and agents.
- Use ULID-based frontmatter IDs. This is collision-resistant, locally generated, lexicographically sortable by creation time, and still compact enough for CLI output.
- Create temporary draft IDs and assign canonical sequential IDs at merge time. This keeps final IDs pretty but requires a complex merge protocol and causes reference churn.

## Decision Outcome

Chosen option: "Use ULID-based frontmatter IDs", because it removes the sequential allocation bottleneck while keeping IDs deterministic to validate, sortable for display, and explicit in each document.

Runtime backward compatibility with filename-derived IDs is rejected. Legacy projects should run an explicit migration that writes `id:` frontmatter, renames files, rewrites structured references, and leaves an old-to-new mapping report.
