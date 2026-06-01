# Contributing to Decree

## Setup

```bash
git clone https://github.com/doruksahin/decree.git
cd decree
uv sync --group dev
brew install lychee  # or install lychee by another method and keep it on PATH
uv run pre-commit install
```

Pre-commit hooks run ruff (lint + format), lychee (online markdown link check), Towncrier fragment checks, and pytest on every commit.

## Development Loop

```bash
uv run pytest -q                                      # run tests
uv run ruff check src/ tests/                         # lint
uv run ruff format src/ tests/                        # format
lychee --config .lychee.toml --no-progress '**/*.md'  # online markdown link check
uv run decree lint                                    # validate dogfood docs
```

Pre-commit runs these checks locally. CI runs pytest on Python 3.11, 3.12, and 3.13, plus ruff, lychee, and Towncrier checks.

## Rules

### Config-driven, not hardcoded

All document type behavior comes from `decree.toml`. Don't add `if doc_type == "adr"` branches. Add a TOML field and read it in [config.py](src/decree/config.py).

### parser.py is the only source-document I/O module

Never call `open()`, `Path.read_text()`, or `frontmatter.load()` on source decision documents outside of [parser.py](src/decree/parser.py). Generated artifacts such as reports and indexes have their own command modules, but they should receive parsed `DocDocument` objects rather than reparsing source files.

### Validators are pure functions

[validators.py](src/decree/validators.py) takes document lists, returns error strings. No file I/O, no side effects. Keep it that way.

### Commands return exit codes

Every command in [commands/](src/decree/commands/) exports `run(args) -> int`. Return `0` for success, `1` for errors. Don't call `sys.exit()` from commands — that's `cli.py`'s job.

### GRAPH_MARKER has one owner

The marker string lives in [commands/index.py](src/decree/commands/index.py). [commands/graph.py](src/decree/commands/graph.py) imports it. Don't duplicate it.

### All output to stderr

Use [log.py](src/decree/log.py) (`info()`, `error()`, `success()`, `fail()`). Stdout is reserved for machine-readable output.

## Adding a New Document Type

No code changes needed. Add a `[types.<name>]` section to `decree.toml`:

```toml
[types.rfc]
dir = "docs/rfc"
prefix = "RFC"
initial_status = "draft"
statuses = ["draft", "review", "accepted", "rejected"]
warn_on_reference = ["rejected"]
required_sections = ["Problem", "Proposal", "Alternatives"]

[types.rfc.transitions]
draft = ["review"]
review = ["accepted", "rejected", "draft"]
accepted = []
rejected = []

[types.rfc.actions]
submit = "review"
accept = "accepted"
reject = "rejected"
```

Optionally add a template at `src/decree/templates/<name>.md` and set `template = "<name>.md"` in the config.

## Adding a New Command

1. Create `src/decree/commands/<name>.py` with a `run(args: Namespace) -> int` function.
2. Register it in [cli.py](src/decree/cli.py) — add a subparser and a dispatch entry.
3. Add tests in `tests/test_<name>.py`.

## Tests

All tests use `tmp_path` — no filesystem side effects. Tests that need a project must `monkeypatch.chdir()` because [config.py](src/decree/config.py) discovers `decree.toml` by walking up from cwd.

The `reset_caches` fixture in [conftest.py](tests/conftest.py) is autouse — it clears the `lru_cache` on `get_project_root()` and `load_doc_types()` between tests. If you add new cached functions, clear them there too.

See [tests/CLAUDE.md](tests/CLAUDE.md) for test map and fixture documentation.

## Pull Requests

- All checks must pass: `pytest`, `ruff check`, `ruff format --check`, `lychee --config .lychee.toml --no-progress '**/*.md'`
- Keep commits focused — one logical change per commit
- Add one Towncrier fragment in `changelog.d/` for each user-visible change
- If you change CLI behavior, update `--help` text in [cli.py](src/decree/cli.py)
- If you add/rename markdown files or sections, run `lychee --config .lychee.toml --no-progress '**/*.md'` to verify links

## Changelog Fragments

Do not edit `CHANGELOG.md` directly for normal development. Add a fragment:

```bash
uv run towncrier create +.feature --content "Add governed lookup for auth files."
uv run towncrier check --staged
```

See [changelog.d/AGENTS.md](changelog.d/AGENTS.md) and [docs/release.md](docs/release.md).

## Code Style

- Ruff with rules: E, F, I, UP, B, SIM, RUF. Line length 120. See [pyproject.toml](pyproject.toml) `[tool.ruff]`.
- Type hints on all public functions
- Pydantic models for validated data, dataclasses for value objects
- No hardcoded constants — add TOML fields in `decree.toml`
