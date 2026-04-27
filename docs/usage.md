# Usage Scenarios

## CLI Commands

### `decree new adr "title"`

Create a new document from template. Auto-numbers, generates slug, stamps today's date, appends required sections from `decree.toml`, regenerates index.

```bash
decree new adr "Use PuLP Solver"
# creates decree/adr/ADR-0001-use-pulp-solver.md
```

### `decree status accept ADR-0004`

Transition a proposed ADR to accepted.

### `decree status reject ADR-0004`

Transition a proposed ADR to rejected (terminal).

### `decree status deprecate ADR-0002`

Transition an accepted ADR to deprecated (terminal).

### `decree status supersede ADR-0001 ADR-0005`

Mark ADR-0001 as superseded by ADR-0005. Sets symmetric links on both files:
- ADR-0001 gets `superseded-by: ADR-0005` and `status: superseded`
- ADR-0005 gets `supersedes: ADR-0001`

### `decree lint`

Validate all documents. Per-file checks: frontmatter validity, required sections. Cross-file checks: supersede symmetry, referenced documents exist. Exit 1 on any error.

Output format: `{filepath}: {message}` — one line per error, machine-parseable.

### `decree index`

Regenerate index tables from frontmatter. Grouped by status.

### `decree progress`

Show progress summary across all document types — counts by status, completion percentages.

### `decree graph`

Generate a dependency/reference graph across documents.

## Integration Points

### Pre-commit hook

Runs `decree lint` + `decree index` when document files are staged. Auto-stages regenerated index.

```bash
# add to .githooks/pre-commit (before final exit)
DOC_STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$' || true)
if [ -n "$DOC_STAGED" ]; then
    uv run decree lint || { echo "decree lint failed."; exit 1; }
    uv run decree index
    git add decree/*/index.md
fi
```

### LLM (Claude Code, Cursor, Copilot)

LLMs read `CLAUDE.md` for quick reference and `config.py` for the full format contract. They create and transition documents via CLI — never edit frontmatter manually.

### CI

`decree lint` returns exit code 1 on failure. Wire into any CI pipeline:

```yaml
- run: uv run decree lint
```

### New project adoption

```bash
uv add decree  # or git+https://github.com/...
```

Create a `decree.toml` in your project root:

```toml
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
```

See [Configuration](configuration.md) for all options.

## Typical Workflows

### Proposing a decision

```bash
decree new adr "Use Redis for caching"
# edit the generated file
git add decree/adr/ADR-0004-use-redis-for-caching.md
git commit -m "docs(adr): propose Redis for caching"
```

### Accepting after discussion

```bash
decree status accept ADR-0004
git add decree/adr/
git commit -m "docs(adr): accept ADR-0004 Redis for caching"
```

### Replacing a decision

```bash
decree new adr "Use Valkey instead of Redis"
decree status supersede ADR-0004 ADR-0005
git add decree/adr/
git commit -m "docs(adr): supersede ADR-0004 with ADR-0005 Valkey"
```

### Validating before merge

```bash
decree lint  # exit 0 = clean, exit 1 = errors
```

### Onboarding someone

Point them to the index file for a given document type — auto-generated table of all documents with status, date, and supersede links.
