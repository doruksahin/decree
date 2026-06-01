# Usage Scenarios

## CLI Commands

### `decree new adr "title"`

Create a new document from template. Generates a local `TYPE-ULID` document ID,
generates a slug, stamps today's date, and appends required sections from
`decree.toml`.

`decree new` does not regenerate indexes or reports. Run `decree index
regenerate` explicitly when you want derived markdown tables refreshed.

```bash
decree new adr "Use PuLP Solver"
# creates decree/adr/adr-01kt22nmrv8zfmdkv0wnfngmcj-use-pulp-solver.md
```

### `decree status ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ accept`

Transition a proposed ADR to accepted.

### `decree status ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ reject`

Transition a proposed ADR to rejected (terminal).

### `decree status ADR-01KT22NMRV7GMAXKWSBEEN68KE deprecate`

Transition an accepted ADR to deprecated (terminal).

### `decree status ADR-01KT22NMRV7GMAXKWSBEEN68KE supersede ADR-01KT22NMRV9CP14X5982JJH161`

Mark one ADR as superseded by another. Sets symmetric links on both files:
- the old ADR gets `superseded-by: <replacement-id>` and `status: superseded`
- the replacement ADR gets `supersedes: <old-id>`

### `decree lint`

Validate all documents. Per-file checks: frontmatter validity, required sections. Cross-file checks: supersede symmetry, referenced documents exist. Exit 1 on any error.

Output format: `{filepath}: {message}` — one line per error, machine-parseable.

### `decree index regenerate`

Regenerate per-type `index.md` markdown tables from frontmatter. Grouped by status.

### `decree index rebuild`

Rebuild `.decree/index.sqlite`, the derived query cache used by `decree why`,
`decree refs`, MCP tools, intent-review/check, health, and retrieval eval.
Git trailers with non-canonical IDs are reported as warnings and ignored; they
are not converted implicitly.

### `decree index status`

Show schema version, rebuild timestamp, and row counts for `.decree/index.sqlite`.

### `decree index verify`

Compare on-disk frontmatter with `.decree/index.sqlite`. Exit 1 when the index
is missing, stale, or missing a document. Run `decree index rebuild` to refresh.

### `decree progress`

Show progress summary across all document types. The output prints its scope.
For parallel work, prefer explicit scope flags:

```bash
decree progress --doc SPEC-01KT22NMS0D19VMD8VPK4D2MNX
decree progress --chain PRD-01KT22NMRTFTWFFARAN0PVEETA
decree progress --changed --base origin/main
decree progress --governs src/decree/parser.py
```

Progress counts only primary checkbox sections. Deferred/out-of-scope sections
are reported separately so parallel work does not look blocked by explicit
future scope.

### `decree ddd`

Assess the current Decree Driven Development phase and print the next action.
Scope it the same way as progress when an agent or worktree owns one slice:

```bash
decree ddd --doc SPEC-01KT22NMS0D19VMD8VPK4D2MNX
decree ddd --chain PRD-01KT22NMRTFTWFFARAN0PVEETA
decree ddd --changed --base origin/main
decree ddd --governs src/decree/parser.py
```

### `decree report regenerate SPEC-01KT22NMS0KTWGNKB36RR7K0JR`

Regenerate completion report snapshots from current frontmatter and checkbox
state. Reports are not silently refreshed by lint; use this command after
editing acceptance criteria on an already-implemented document.

Use `decree report regenerate --all --existing-only` to refresh committed report
files without creating new reports for older terminal documents.

### `decree migrate ids`

Convert legacy numeric filename-derived corpora to explicit `TYPE-ULID`
frontmatter IDs.

```bash
decree migrate ids --dry-run
decree migrate ids --apply
```

Dry-run prints the old-to-new mapping without writing. Apply writes `id:`,
rewrites structured references, renames document files and report snapshots,
regenerates indexes, and stores a mapping JSON in `decree/migrations/`.

### `decree graph`

Generate a dependency/reference graph across documents.

### `decree why src/decree/parser.py`

Query the SQLite index for decisions whose `governs:` entries cover a path.
Run `decree index rebuild` first. `why` does not auto-rebuild the cache and
exits 1 if the index is missing or stale.

### `decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX`

Query the reverse graph for one decision: references, reverse references,
governed paths, supersede chain, and indexed git trailers.
Like `why`, it fails closed when the index is missing or stale.

### `decree commit -m "message"`

Wrap `git commit` and add structural `Implements:`, `Refs:`, and `Fixes:`
trailers. Without explicit `--implements`, it infers the active SPEC from
staged paths and the SQLite index. If the index is missing, it fails closed:
run `decree index rebuild`, pass `--implements`, or pass `--no-infer`.

### `decree health`

Report stale decisions and ungoverned hotspots using the SQLite index and git
history. `decree stale` is an alias.

### `decree intent-review`

Review a diff against governed decisions before code review. Accepts a diff
file, stdin (`--diff -`), or `--diff-base REF`.

### `decree intent-check`

Review a proposed plan and planned file list before implementation starts.

### `decree mcp serve`

Expose decree query tools over Model Context Protocol stdio for LLM agents.

### `decree retrieval-eval`

Run labeled-query retrieval evaluation against `.decree/index.sqlite`. Use
`--calibrate` to write calibration files before running calibrated methods.

## Integration Points

### Pre-commit hook

Runs `decree lint` + `decree index regenerate` when document files are staged.
Auto-stages regenerated markdown indexes.

```bash
# add to .githooks/pre-commit (before final exit)
DOC_STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep '\.md$' || true)
if [ -n "$DOC_STAGED" ]; then
    uv run decree lint || { echo "decree lint failed."; exit 1; }
    uv run decree index regenerate
    git add decree/*/index.md
fi
```

### LLM (Claude Code, Cursor, Copilot)

LLMs should read [LLM Agent Integration](llm-agent-integration.md) for the
command loop, explicit model-resolution chain, and fallback policy. They create
and transition documents via CLI where possible; if they edit frontmatter
directly, they must run `decree lint` and `decree index rebuild` afterwards.

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
git add decree/adr/
git commit -m "docs(adr): propose Redis for caching"
```

### Accepting after discussion

```bash
decree status ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ accept
git add decree/adr/
git commit -m "docs(adr): accept Redis caching ADR"
```

### Replacing a decision

```bash
decree new adr "Use Valkey instead of Redis"
decree status ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ supersede ADR-01KT22NMRV9CP14X5982JJH161
git add decree/adr/
git commit -m "docs(adr): supersede Redis with Valkey"
```

### Validating before merge

```bash
decree lint  # exit 0 = clean, exit 1 = errors
```

### Onboarding someone

Point them to the index file for a given document type — auto-generated table of all documents with status, date, and supersede links.
