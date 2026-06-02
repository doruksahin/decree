# AGENTS.md

This is the first file an LLM agent should read before changing this
repository. Keep it short; follow the links only when your task touches that
area.

## Mission

Decree is a software decision lifecycle toolkit. It keeps product intent,
architecture decisions, implementation specs, governed code paths, git
trailers, and release notes in the same repository.

Primary user: developers and LLM agents that need to answer:

> Which decision explains this code, and is the planned change still aligned
> with that decision chain?

## First Commands

Run these before non-trivial work:

```bash
git status --short --branch
uv run decree lint
uv run decree progress
```

If you will touch code paths, also run a scoped governance check:

```bash
uv run decree why src/decree/cli.py
uv run decree intent-check --plan "Short plan" --files src/decree/cli.py
```

Use narrower progress scopes when working in parallel:

```bash
uv run decree progress --doc SPEC-01KT22NMS0D19VMD8VPK4D2MNX
uv run decree progress --changed --base origin/main
uv run decree progress --governs src/decree/parser.py
```

When several agent sessions touch the same tree, pass the others' planned files
so intent-check flags live overlaps before you start:

```bash
uv run decree intent-check --plan "Short plan" --files src/decree/parser.py \
  --other-active-files '{"other-session": ["src/decree/parser.py"]}'
```

## Progressive Disclosure

Read only the files relevant to your task:

| If you are doing... | Read |
|--------------------|------|
| General orientation | [docs/index.md](docs/index.md) |
| CLI usage or examples | [docs/usage.md](docs/usage.md) |
| Python implementation | [src/decree/AGENTS.md](src/decree/AGENTS.md) |
| CLI command implementation | [src/decree/commands/AGENTS.md](src/decree/commands/AGENTS.md) |
| Tests | [tests/AGENTS.md](tests/AGENTS.md) |
| PRD/ADR/SPEC dogfood docs | [decree/AGENTS.md](decree/AGENTS.md) |
| Public docs | [docs/AGENTS.md](docs/AGENTS.md) |
| Portable agent skills | [skills/AGENTS.md](skills/AGENTS.md) |
| Changelog/release notes | [changelog.d/AGENTS.md](changelog.d/AGENTS.md) and [docs/release.md](docs/release.md) |
| Release/versioning | [docs/release.md](docs/release.md) |
| Architecture overview | [docs/architecture.md](docs/architecture.md) |
| Project contribution rules | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Non-Negotiable Rules

- Do not hide behavior behind silent fallbacks.
- Do not auto-rebuild derived artifacts inside query commands.
- Do not hardcode PRD/ADR/SPEC assumptions into runtime code; document types
  come from `decree.toml`.
- Do not manually edit generated `decree/*/index.md` tables or report
  snapshots unless you are deliberately changing generated output fixtures.
- Do not manually edit `CHANGELOG.md` for normal development. Add a Towncrier
  fragment in `changelog.d/`.
- Do not claim governance when `decree why`, `decree refs`, or
  `intent-check` returns no match.
- Keep CLI help, docs, tests, and changelog fragments in sync with behavior.

## Standard Change Loop

1. Inspect current state with the first commands above.
2. Find the governing document for files you will touch.
3. Make the smallest coherent code/doc change.
4. Add or update tests for behavior changes.
5. Add one `changelog.d/` fragment for each user-visible change.
6. Run targeted tests first, then the full validation set.
7. Commit only after validation is clean.

## Validation

Use this before handing off work:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run decree lint
uv run decree index verify
lychee --config .lychee.toml --no-progress '**/*.md'
uv run towncrier build --draft --version 0.2.0
uv run pytest -q
uv run pre-commit run --all-files
```

If time is limited, report exactly which commands you ran and which remain.

## Commit Guidance

Use `decree commit` when committing from this repo:

```bash
uv run decree commit -m "type: short message" --no-infer
```

Use explicit `--implements ID` only when the commit actually implements a
specific SPEC. Use `--no-infer` for repo hygiene, docs, release, or tooling
commits that should not claim implementation.

Historical commits may contain old numeric trailers such as `SPEC-014`.
Current code warns and skips them; do not rewrite history just to remove those
warnings.
