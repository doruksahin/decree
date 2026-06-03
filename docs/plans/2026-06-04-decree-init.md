# `decree init` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A deterministic, idempotent `decree init` that takes a project from zero to a working, **lint-clean** decree corpus (canonical `decree.toml` + type dirs + a worked PRD→ADR→SPEC example chain + a built index) in one run, reporting every action accountably (created / skipped-with-reason / would-create), with `--dry-run`, `--json`, `--no-examples`, `--project`.

**Architecture:** A new read-mostly command `src/decree/commands/init.py` + one CLI registration. It **copies bundled assets** (a canonical `decree.toml` + a consistent worked example chain under `src/decree/templates/init/`) into the target, creating only what's missing, then rebuilds the index. It reuses `log.py` (stderr reporting), `index_db_cli.rebuild_run`, and the same package-data access pattern as `new.py` (`Path(__file__).resolve().parent.parent / "templates" / "init"`). No interactivity, no LLM, **no new dependency**, no schema change. Purely additive.

**Tech Stack:** Python 3.11+, argparse, `shutil`/`pathlib`, the existing index machinery, pytest. Design: `docs/plans/2026-06-04-decree-init-design.md`.

---

## Phase 0 — Dogfood (optional, recommended): track as a SPEC

`decree new spec "decree init — deterministic idempotent scaffolder"`, fill Overview /
Technical Design / Testing Strategy from the design doc, `governs: [src/decree/commands/init.py]`,
acceptance criteria = the tasks below. `decree lint` clean; commit via
`decree commit --implements <SPEC>`. (Skip only if you want the feature without the dogfood record.)

---

## Phase 1 — The bundled assets (the "lints clean" contract lives here)

The canonical config and the example chain MUST be mutually consistent so the project
`init` produces passes `decree lint`. Author them together.

### Task 1.1: Create `src/decree/templates/init/decree.toml`

The canonical default config. `prd`/`adr`/`spec` types whose `statuses` and
`required_sections` are satisfied by the example docs in Task 1.2. Use a **minimal**
`required_sections` per type (only sections the example docs definitely contain) so lint
is satisfied:

```toml
[types.prd]
dir = "decree/prd"
prefix = "PRD"
initial_status = "draft"
statuses = ["draft", "approved", "implemented", "archived"]
required_sections = ["Problem Statement"]
[types.prd.transitions]
draft = ["approved"]
approved = ["implemented", "archived"]
implemented = ["archived"]
archived = []
[types.prd.actions]
approve = "approved"
implement = "implemented"
archive = "archived"

[types.adr]
dir = "decree/adr"
prefix = "ADR"
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["superseded"]
rejected = []
superseded = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
```

### Task 1.2: Create the worked example chain under `src/decree/templates/init/`

Three files (adapt the content of `src/decree/examples/{prd,adr,spec}-*.md`, with **pinned**
ULIDs and a leading "delete me" note in each body):
- `prd/prd-<ULID>-example-task-cli.md` — `status: approved`, has `## Problem Statement` (+ `## Requirements`, `## Success Criteria`).
- `adr/adr-<ULID>-example-storage.md` — `status: accepted`, `references: [<PRD-ULID>]`, MADR sections (`## Context and Problem Statement`, `## Considered Options`, `## Decision Outcome`).
- `spec/spec-<ULID>-example-storage-api.md` — `status: approved`, `references: [<PRD-ULID>, <ADR-ULID>]`, has `## Overview` (+ `## Technical Design`, `## Testing Strategy`).
Each body's first line after the title: `> Example scaffolded by \`decree init\` — delete this file (and its siblings) once you write your own.`

### Task 1.3 (test): the bundled assets lint clean together

**Test** `tests/test_init.py::test_bundled_assets_lint_clean`: copy `templates/init/decree.toml`
+ the three docs into a tmp dir (mirroring the target layout), run the **library** lint over
it (or `decree lint --project <tmp>` via subprocess), assert 0 errors and that the cross-refs
resolve. This pins the lints-clean contract before any command code exists.
**Commit:** `feat: bundled decree.toml + worked example chain for init`.

---

## Phase 2 — Core init logic (TDD), `src/decree/commands/init.py`

Pure-ish planning separated from IO so it's testable and `--dry-run` is trivial.

### Task 2.1: `plan_init(target) -> InitPlan`

Returns a list of planned actions without touching disk. Each action:
`Action(kind, target_path, action: "create"|"skip", reason: str|None)` for: the `decree.toml`,
each `decree/<type>/` dir, each example doc, and the index. Rules (from the design):
- `decree.toml` present → skip, reason "exists (types: …)"; absent → create.
- type dir present → skip; absent → create.
- example doc → create only if its type dir is **empty/absent**; if the type dir has docs →
  skip, reason "decree/<type>/ already has documents".
- index → always (re)build unless `--dry-run`.
**Tests:** empty target → all "create"; fully-present target → all "skip" with reasons;
partial (toml present, dirs absent) → mixed; non-empty `decree/spec/` → spec example "skip".

### Task 2.2: `apply_init(plan, *, no_examples) -> AppliedResult`

Executes a plan: write `decree.toml` (copy bundled), `mkdir -p` dirs, copy example docs
(skip when `no_examples`), then call `index_db_cli.rebuild_run` against the target (construct
the minimal Namespace it needs — read its signature). Returns counts (created, skipped).
Never overwrites an existing file. **Tests:** apply into empty tmp → files exist on disk,
`.decree/index.sqlite` exists, `decree lint --project` clean; re-apply → no changes, 0 created.

---

## Phase 3 — CLI command + reporting + exit codes (TDD)

### Task 3.1: register `decree init` in `cli.py`

`add_parser("init", …)` with `--dry-run`, `--json`, `--no-examples`, `--project`; dispatch
`"init": init_cmd.run`. `run(args)` resolves target (`args.project` or cwd), builds the plan,
applies it unless `--dry-run`, prints the report, returns the exit code. **Test:** `decree init --help` works.

### Task 3.2: human report (stderr via `log.py`) + exit codes

Sectioned report (Config · Directories · Examples · Index) using `info`/`success`/`warn`,
a final summary line ("Created N, skipped M (already present)."), a **git note** when the
target isn't a git repo ("health/commit signals unavailable until you `git init`"), and a
"Next: decree lint · decree why <file>" hint. Exit `0` always on success (incl. fully-present
"nothing to do"); `2` on IO/config error. **Tests (end-to-end through `run`):** empty dir →
exit 0, files created, the report names each; re-run → exit 0, all skipped; `--dry-run` →
**no writes anywhere** (assert no files, no `.decree/`), report shows the plan; `--no-examples`
→ config + dirs + index only; non-git target → the git note appears.

### Task 3.3: `--json` stable contract (stdout)

```json
{ "target": "/abs/path",
  "actions": [{"kind":"config|dir|example|index","path":"…","action":"created|skipped|would-create","reason":null}],
  "summary": {"created": 6, "skipped": 0},
  "git": false, "dry_run": false, "exit": 0 }
```
JSON goes to **stdout** (machine contract); the human report stays on stderr. **Test:** asserts the shape for an empty-dir run and a dry-run.

**Commit (Phase 2+3):** `feat: decree init (deterministic, idempotent scaffolder + report)`.

---

## Phase 4 — Packaging, docs, changelog

### Task 4.1: verify the bundled init assets ship in the wheel

`uv build`, then in a clean venv install the wheel and run `decree init --dry-run` in a tmp
dir — assert it finds the bundled `templates/init/` assets (not just editable mode). If
hatchling doesn't include them, add `[tool.hatch.build.targets.wheel] force-include` / `include
= ["src/decree/templates/**/*"]` in `pyproject.toml`. (The existing `templates/*.md` already
ship, so this likely works as-is — but verify, since `init/` is a new subdir.)

### Task 4.2: docs

- `README.md` Quick Start — lead with `decree init` (one command to a working corpus), and
  include the canonical `decree.toml` is generated for you (close the maintainer's onboarding gap).
- `docs/usage.md` — a `### decree init` section (flags, idempotency, `--dry-run`/`--json`).
- `docs/index.md` integration sequence — step 1 becomes `decree init` (was "add decree.toml by hand").
- `docs/llm-agent-integration.md` — note `decree init --json` for agent-driven project setup.

### Task 4.3: Towncrier fragment

`changelog.d/+decree-init.feature`: "Add `decree init`: a deterministic, idempotent project
scaffolder that creates a canonical `decree.toml`, the type directories, a worked PRD→ADR→SPEC
example chain, and a built index — reporting every action (created / skipped-with-reason),
with `--dry-run`, `--json`, and `--no-examples`. The scaffolded project lints clean immediately."

**Gate (whole feature):** `uv run pytest -q`, `uv run ruff check/format`, `uv run decree lint`,
`uv run decree index rebuild && uv run decree index verify`, `lychee` — all green. Check off
the SPEC ACs; transition SPEC → implemented.

---

## Test matrix (all in `tests/test_init.py`)
1. bundled assets lint clean together (Phase 1).
2. empty dir → all created; `decree lint` clean; `why`/`refs`/`progress` resolve on the chain.
3. re-run on fully-initialized project → all skipped, exit 0.
4. `--dry-run` → writes nothing (no files, no `.decree/`); plan reported.
5. partial state (toml present, dirs absent) → only missing created.
6. non-empty `decree/spec/` → spec example skipped with reason.
7. `--no-examples` → config + dirs + index, no docs.
8. non-git target → succeeds, git-signals note in report.
9. `--json` shape stable (run + dry-run).
10. `--project PATH` targets another dir.

## Risk / backwards-compat
Purely additive: one new command module, one CLI registration, new bundled template assets,
doc edits, a changelog fragment. **No change** to any existing command, loader, or schema.
`init` never overwrites existing files and is safe to re-run. Cannot break existing users.

## Out of scope (YAGNI)
Interactive prompts / `--interactive`, template management, custom-type selection beyond the
default trio, any generator-library dependency.
