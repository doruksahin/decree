# `decree init` — Design

**Date:** 2026-06-04
**Status:** Approved (brainstorming → ready for implementation plan)
**Goal:** A deterministic, idempotent, highly-accountable setup command that gets a
project from zero to a working, lint-clean decree corpus in one run — closing the
first-10-minutes onboarding gap for non-Claude-Code users.

## Decisions (locked with the user)

| Decision | Choice |
|----------|--------|
| Interaction model | **Deterministic + idempotent** — no prompts, sensible defaults, `--dry-run`, flags. Agent/CI-callable, fits decree's brand. No new dependency. |
| Seed content | **The worked PRD→ADR→SPEC chain** from `src/decree/examples/` (cross-referenced), seeded only into empty type dirs. |
| Generator library | **None.** Compose decree's own machinery (`template.render_template`, `log.py`, the bundled `examples/`). Questionary/Rich/Copier rejected — heavy deps + the "template-management machinery" the maintainer warned against. |

## What it does (idempotent, never overwrites)

Walks the target (`cwd`, or `--project PATH`) and ensures each piece exists, creating
only what's missing:

1. **`decree.toml`** — a canonical config defining `prd`/`adr`/`spec` (dirs, statuses,
   transitions, actions, required sections). Written only if absent. If a `decree.toml`
   already exists, it is **left unchanged** and the report notes the types it defines.
2. **Type directories** — `decree/prd/`, `decree/adr/`, `decree/spec/`.
3. **The worked example chain** — copy decree's bundled example docs (a PRD, an ADR
   referencing it, a SPEC referencing both), each marked as an example to delete. Seeded
   **only into empty type dirs** — never added alongside a user's real docs.
4. **`.decree/index.sqlite`** — rebuilt at the end so queries work immediately.

## Hard guarantee — the result lints clean

The project `init` produces must pass `decree lint` the instant it finishes: the canonical
`decree.toml` and the seeded docs are mutually consistent (every seeded doc's `status` is
valid, its required sections are present, and its cross-references resolve). `decree why`,
`decree refs`, and `decree progress` all work immediately on the seeded chain. This is an
explicit acceptance criterion and a test.

## Accountability — the core requirement

Every item reports its outcome — **created / already-present (skipped) / would-create** —
sectioned (Config · Directories · Examples · Index), ending with an honest summary, e.g.:

```
decree init — /path/to/project

Config:
  ✓ created decree.toml (types: prd, adr, spec)
Directories:
  ✓ created decree/prd/
  ✓ created decree/adr/
  • decree/spec/ already exists — left unchanged
Examples:
  ✓ seeded decree/prd/prd-…-example.md
  ✓ seeded decree/adr/adr-…-example.md
  • decree/spec/ already has documents — example not seeded
Index:
  ✓ rebuilt .decree/index.sqlite

Created 5, skipped 2 (already present). Not a git repo — health/commit signals are
unavailable until you `git init`. Next: decree lint · decree why <file>.
```

It **states why** it skipped (existing config's types, non-empty type dir, etc.). Flags:
- **`--dry-run`** — report exactly what it *would* do; write nothing.
- **`--json`** — the same report as a stable machine contract (agent/CI consumable,
  consistent with decree's other commands). Shape: per-item `{target, action: created|skipped|would-create, reason?}` + a `summary {created, skipped}` + `git: bool`.
- **`--no-examples`** — config + dirs + index only.
- **`--project PATH`** — operate on a target other than cwd.

## Exit codes (decree's contract)

- `0` — success, **including a fully-already-initialized project** ("nothing to do"). Never
  non-zero just because things already existed (idempotent).
- `2` — config / IO error (unwritable target, malformed bundled template, etc.).

## Edge cases (must be handled + reported accountably)

- `decree.toml` exists (any types) → left unchanged; report its types.
- Some type dirs exist, others missing → create only the missing; skip + report existing.
- A type dir is non-empty → its example is **not** seeded; report the reason.
- Target is not a git repo → still succeeds; report that git-derived signals are unavailable.
- `--dry-run` → no writes anywhere (including no index rebuild); report the full plan.

## Architecture

- New `src/decree/commands/init.py` (`run(args)`), one `add_parser("init", …)` + dispatch
  entry in `cli.py`. Reuses `template.render_template`, `log.py` (info/success/warn/error),
  `config.get_project_root`/path helpers, and reads the bundled `src/decree/examples/`
  chain as the seed source (packaged with decree). The canonical `decree.toml` lives as a
  bundled template (e.g. `src/decree/templates/init/decree.toml`) so config and examples
  stay versioned together and consistent.
- No interactivity, no LLM, no new runtime dependency. Purely additive — no change to any
  existing command, loader, or schema.

## Testing

- empty dir → everything created; `decree lint` clean; `why`/`refs`/`progress` resolve on the chain.
- re-run on a fully-initialized project → all skipped, exit 0, "nothing to do."
- `--dry-run` → writes nothing (no files, no index); reports the plan.
- partial state (toml present, dirs missing) → creates only the missing, skips the rest.
- non-empty type dir → example skipped with the stated reason.
- non-git target → succeeds, reports git-signals-unavailable note.
- `--no-examples` → config + dirs + index, no docs.
- `--json` → stable shape per the contract above.

## Out of scope (YAGNI)

Interactive prompts / a `--interactive` mode (revisit only if users ask), template
management (`decree template list`), custom-type selection beyond the default trio
(users edit `decree.toml`), and any generator-library dependency.
