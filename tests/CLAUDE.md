# tests

## Running

```bash
uv run pytest -q              # all tests
uv run pytest tests/test_graph.py -v  # single file
uv run pytest -k supersede    # by keyword
```

## Test Map

| File | Covers | Key details |
|------|--------|-------------|
| [test_parser.py](test_parser.py) | `parser.py` | Frontmatter parsing, Pydantic validation, `raw_metadata` |
| [test_validators.py](test_validators.py) | `validators.py` | Cross-type refs, self-refs, stale refs, dangling refs, attachments |
| [test_c4.py](test_c4.py) | `c4.py` | C4 hierarchy, duplicate ids, parent/depends-on, diagram generation |
| [test_config.py](test_config.py) | `config.py` | Config loading, transition validation, project root discovery |
| [test_new.py](test_new.py) | `commands/new.py` | Document creation, auto-numbering, frontmatter stamping |
| [test_status.py](test_status.py) | `commands/status.py` | Lifecycle transitions, supersede bidirectional linking |
| [test_lint.py](test_lint.py) | `commands/lint.py` | End-to-end lint command |
| [test_index.py](test_index.py) | `commands/index.py` | Index generation, sorting, marker presence |
| [test_graph.py](test_graph.py) | `commands/graph.py` | Diagram generation, marker handling, idempotency |
| [test_progress.py](test_progress.py) | `commands/progress.py` | Checkbox counting, progress bars |
| [test_integration.py](test_integration.py) | Multi-module | Cross-cutting scenarios across types |
| [test_smoke_scenarios.py](test_smoke_scenarios.py) | Full lifecycle | Uses [scenarios.py](scenarios.py) fixtures — realistic "Team Billing" SaaS lifecycle |
| [test_cli.py](test_cli.py) | `cli.py` | CLI argument parsing, help output |
| [test_doctypes.py](test_doctypes.py) | `doctypes.py` | DocType dataclass, ID formatting, regex patterns |
| [test_template.py](test_template.py) | `template.py` | Template rendering, section appending |

## Fixtures

### `conftest.py`

- **`project_dir`** — temp directory with `decree.toml` (ADR-only config) and empty `docs/adr/`. Most tests use this as their base.
- **`reset_caches`** (autouse) — clears `lru_cache` on `get_project_root()` and `load_doc_types()` between every test. Without this, tests leak config state.

### `scenarios.py`

Large fixture library modeling a realistic multi-type project ("Team Billing" for a SaaS company). Provides pre-built document sets for:

- Happy path with PRD → ADR → SPEC chain
- Supersede chains (ADR-00000000000000000000000002 superseded by ADR-00000000000000000000000003)
- Circular references (co-dependent SPECs)
- Dangling references, stale references, self-references
- Multi-type cross-references

Each scenario fixture writes files to `tmp_path` and returns the project directory.

## Conventions

- All tests use `tmp_path` (pytest built-in) — no filesystem side effects
- Tests that need `decree.toml` must `monkeypatch.chdir(project_dir)` because `config.py` walks up from cwd
- Test names follow `test_<what_it_checks>` pattern
- No mocking of file I/O — tests write real files to temp dirs
