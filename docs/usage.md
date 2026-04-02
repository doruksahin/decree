# Usage Scenarios

## CLI Commands

### `adr new "title"`

Create a new ADR from template. Auto-numbers, generates slug, stamps today's date, appends project sections from `[tool.adr]`, regenerates index.

```bash
adr new "Use PuLP Solver"
# creates docs/adr/ADR-0001-use-pulp-solver.md
```

### `adr status accept ADR-0004`

Transition a proposed ADR to accepted.

### `adr status reject ADR-0004`

Transition a proposed ADR to rejected (terminal).

### `adr status deprecate ADR-0002`

Transition an accepted ADR to deprecated (terminal).

### `adr status supersede ADR-0001 ADR-0005`

Mark ADR-0001 as superseded by ADR-0005. Sets symmetric links on both files:
- ADR-0001 gets `superseded-by: ADR-0005` and `status: superseded`
- ADR-0005 gets `supersedes: ADR-0001`

### `adr lint`

Validate all ADRs. Per-file checks: frontmatter validity, required sections. Cross-file checks: supersede symmetry, referenced ADRs exist. Exit 1 on any error.

Output format: `{filepath}: {message}` — one line per error, machine-parseable.

### `adr index`

Regenerate `docs/adr/index.md` table from frontmatter. Grouped by status: accepted first, then proposed, then deprecated/superseded/rejected.

## Integration Points

### Pre-commit hook

Runs `adr lint` + `adr index` when ADR files are staged. Auto-stages regenerated index.

```bash
# add to .githooks/pre-commit (before final exit)
ADR_STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep '^docs/adr/ADR-.*\.md$' || true)
if [ -n "$ADR_STAGED" ]; then
    uv run adr lint || { echo "ADR lint failed."; exit 1; }
    uv run adr index
    git add docs/adr/index.md
fi
```

### LLM (Claude Code, Cursor, Copilot)

LLMs read `CLAUDE.md` for quick reference and `config.py` for the full format contract. They create and transition ADRs via CLI — never edit frontmatter manually.

### CI

`adr lint` returns exit code 1 on failure. Wire into any CI pipeline:

```yaml
- run: uv run adr lint
```

### New project adoption

```bash
uv add madr-tools  # or git+https://github.com/...
```

Add to `pyproject.toml`:

```toml
[tool.adr]
project_sections = ["Consequences", "Affected Files"]
```

See [Configuration](configuration.md) for all options.

## Typical Workflows

### Proposing a decision

```bash
adr new "Use Redis for caching"
# edit the generated file
git add docs/adr/ADR-0004-use-redis-for-caching.md
git commit -m "docs(adr): propose Redis for caching"
```

### Accepting after discussion

```bash
adr status accept ADR-0004
git add docs/adr/
git commit -m "docs(adr): accept ADR-0004 Redis for caching"
```

### Replacing a decision

```bash
adr new "Use Valkey instead of Redis"
adr status supersede ADR-0004 ADR-0005
git add docs/adr/
git commit -m "docs(adr): supersede ADR-0004 with ADR-0005 Valkey"
```

### Validating before merge

```bash
adr lint  # exit 0 = clean, exit 1 = errors
```

### Onboarding someone

Point them to `docs/adr/index.md` — auto-generated table of all decisions with status, date, and supersede links.
