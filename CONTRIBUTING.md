# Contributing to Decree

## Development Setup

```bash
# Clone and install
git clone https://github.com/doruksahin/decree.git
cd decree
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Running Tests

```bash
uv run pytest -v
```

Tests live in `tests/`. The `conftest.py` fixture creates a temporary project
with a `decree.toml` so tests don't need a real project directory.

## Adding a New Document Type

1. Add a `[types.<name>]` section to `decree.toml` with prefix, statuses,
   transitions, and actions.
2. Optionally add a template in `src/decree/templates/<name>.md`.
3. Register the template path in `src/decree/commands/new.py` (`_TYPE_TEMPLATES`).
4. Add tests covering the new type's lifecycle.

See the existing `adr`, `prd`, and `spec` type configs in the example
`decree.toml` for reference.

## Pull Request Guidelines

- Run `uv run pytest -v` and confirm all tests pass before opening a PR.
- Keep commits focused -- one logical change per commit.
- Update `CHANGELOG.md` under an `## Unreleased` heading.
- If you change CLI behavior, update the `--help` text in `cli.py`.

## Code Style

- Type hints on all public functions.
- Pydantic models for validated data, dataclasses for value objects.
- No `as` casts -- use type guards or Zod-style validation.
- Config-driven behavior -- add TOML fields, not hardcoded constants.
