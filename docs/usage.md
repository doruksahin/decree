# Usage Scenarios

For the structured capability map and recommended adoption sequence, see the
[Capability Index](index.md).

## CLI Commands

### `decree init`

Scaffold a directory into a working, lint-clean decree corpus in one run. It is
the recommended first command in a new project — no hand-editing `decree.toml`.

It creates, reporting every action with a reason:

- a canonical `decree.toml` (the `prd` / `adr` / `spec` trio),
- the `decree/<type>/` directories,
- a worked PRD→ADR→SPEC example chain (mutually consistent, so the project
  lints clean immediately — learn from it or delete it),
- a `.gitignore` rule for `.decree/` (the derived index cache is rebuildable and
  should not be committed),
- a built `.decree/index.sqlite` query cache.

```bash
decree init
decree lint   # the scaffolded project lints clean immediately
```

**Idempotent.** Re-running never overwrites your files: anything already
present is left untouched and reported as skipped with a reason. The only file
init ever *modifies* is `.gitignore`, and only by appending a missing `.decree/`
rule — never rewriting your existing lines. The index is a derived cache, so it
is *rebuilt* (not "created") on every run — it is never counted as a creation. A
re-run on a fully set-up project prints
`Already initialized — nothing to create (index refreshed).` and exits 0.

**Respects an existing config.** If a `decree.toml` is already present, init
leaves it untouched and scaffolds *its* declared types (at their configured
dirs) rather than imposing the default trio — so it never litters a custom
corpus with orphan `decree/prd|adr|spec` directories. A custom type with no
bundled example gets its directory but no seeded doc. If the existing
`decree.toml` is malformed, init reports it clearly (naming the file), leaves it
unchanged, and exits `2`.

Flags:

- `--dry-run` — report the plan without touching disk (index shown as
  *would rebuild*).
- `--json` — machine-readable report (`actions[]` with `created` / `skipped` /
  `wrote` / `appended` / `rebuilt`, plus a `summary.created` / `summary.skipped`
  that counts only real corpus file/dir creations — not the `.gitignore` or the
  index).
- `--no-examples` — scaffold the config and directories but seed no example docs.
- `--project DIR` — target another directory instead of the current one.

### `decree --version`

Print the installed package version. The value comes from package metadata,
whose source of truth is `[project].version` in `pyproject.toml`.

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

When sprint mode is enabled, `decree new spec "title"` adds the new SPEC to the
active sprint by default. During a paused sprint period, a new SPEC must be
placed explicitly:

```bash
decree new spec "Search API" --backlog --reason "not in the freeze window"
decree new spec "Experimental Parser" --draft-pool --reason "speculative design"
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

### `decree sprint`

Enable and manage optional sprint-scoped execution tracking. Sprint mode is off
until the repository has `decree/sprints/ledger.yaml`, created explicitly by:

```bash
decree sprint init "Sprint 1"
```

Once enabled, exactly one active sprint exists unless sprint mode is paused.
Use backlog or draft pool for work that should not enter the current sprint:

```bash
decree sprint status
decree sprint add SPEC-01KT22NMS0D19VMD8VPK4D2MNX
decree sprint add PRD-01KT22NMRTFTWFFARAN0PVEETA --kind planning
decree sprint backlog SPEC-01KT22NMS0D19VMD8VPK4D2MNX --reason "not ready for this sprint"
decree sprint draft-pool SPEC-01KT22NMS0D19VMD8VPK4D2MNX --reason "exploratory"
decree sprint pause --reason "summer freeze"
decree sprint resume "Sprint 2"
```

Close a sprint by providing an outcomes YAML file for every open active item:

```yaml
outcomes:
  SPEC-01KT22NMS0D19VMD8VPK4D2MNX:
    kind: carried_over
    reason: implementation started late
```

```bash
decree sprint rollover "Sprint 2" --outcomes sprint-outcomes.yaml
```

Completed outcomes are accepted only when the close-time acceptance-criteria
snapshot is 100% for primary criteria. Carryover is linear to the immediate
successor sprint and requires a reason.

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

Show progress summary across all document types. When sprint mode is enabled
and active, the default scope is the active sprint's execution/planning items.
Use `--corpus` to keep the old whole-corpus view. The output prints its scope.
For parallel work, prefer explicit scope flags:

```bash
decree progress --doc SPEC-01KT22NMS0D19VMD8VPK4D2MNX
decree progress --chain PRD-01KT22NMRTFTWFFARAN0PVEETA
decree progress --changed --base origin/main
decree progress --governs src/decree/parser.py
decree progress --sprint SPRINT-01KT22NMS0D19VMD8VPK4D2MNX
decree progress --backlog
decree progress --draft-pool
decree progress --all-sprints
decree progress --include-context
decree progress --corpus
```

Progress counts only primary checkbox sections. Deferred/out-of-scope sections
are reported separately so parallel work does not look blocked by explicit
future scope.

### `decree ddd`

Assess the current Decree Driven Development phase and print the next action.
The assessment includes a governance-drift hint — dead and suggested governance
counts (run `decree health` for detail). Scope it the same way as progress when
an agent or worktree owns one slice. With active sprint mode, the default scope
is the active sprint; use `--corpus` to assess every document.

```bash
decree ddd --doc SPEC-01KT22NMS0D19VMD8VPK4D2MNX
decree ddd --chain PRD-01KT22NMRTFTWFFARAN0PVEETA
decree ddd --changed --base origin/main
decree ddd --governs src/decree/parser.py
decree ddd --sprint SPRINT-01KT22NMS0D19VMD8VPK4D2MNX
decree ddd --backlog
decree ddd --corpus
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

### `decree migrate governs`

Backfill `governs:` frontmatter for an existing corpus. Use this when adopting
decree in a project that already has decisions but does not yet say which files
or directories each decision owns.

```bash
decree migrate governs --analyze --json > governs-analysis.json
decree migrate governs --apply-suggestions governs-suggestions.json
decree migrate governs --apply-suggestions governs-suggestions.json --apply --yes
```

Core decree does not call an LLM. `--analyze --json` emits
`decree.governs-analysis.v1` for an external agent/skill. That agent writes a
`decree.governs-suggestions.v1` file. `--apply-suggestions` validates schema,
document IDs, repo-relative paths, duplicates, and on-disk existence before
rendering a unified diff. It writes only when `--apply` is passed and
confirmed.

Invalid suggestions are reported explicitly and block writes. Documents that
already have `governs:` are skipped instead of overwritten silently. See
[LLM Agent Integration](llm-agent-integration.md) for the agent-side contract.

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

Report four git-derived coherence signals using the SQLite index and git
history: **stale decisions**, **ungoverned hotspots**, **dead governance**
(declared `governs:` paths no trailer-linked commit ever touched), and advisory
**suggested governance** (files a decision's own commits repeat-touch but it does
not declare). `decree stale` is an alias. Exit 1 on stale/ungoverned/dead
findings; suggested governance is advisory (exit 0) and never feeds `why`. See
[health-signals.md](health-signals.md) for the detect → interpret → act flow.

```bash
decree health
decree health --json
decree health --threshold-commits 10 --threshold-days 30
```

### `decree intent-review`

Review a diff against governed decisions before code review. Accepts a diff
file, stdin (`--diff -`), or `--diff-base REF`.

### `decree intent-check`

Review a proposed plan and planned file list before implementation starts.
Run this before coding when an agent knows which files it will touch:

```bash
decree intent-check \
  --plan "Change token refresh storage" \
  --files src/auth/tokens.py tests/test_tokens.py
```

When other agent sessions are running in parallel, pass their planned paths so
intent-check also reports `live_conflicts` (files another live session is about
to write) and emits an `isolate_session` recommendation:

```bash
decree intent-check \
  --plan "Edit the canvas" \
  --files src/canvas.tsx \
  --other-active-files '{"session-b": ["src/canvas.tsx"]}'
```

In a governed session, pass `--under <decision>` to either command. When a
planned/changed file is one that decision's own commits repeat-touch (>=2) but it
does not declare, the report adds an advisory `governs_gaps` list and a
`declare_governs` recommendation — the point-of-change counterpart to
`decree health`'s suggested governance (see [health-signals.md](health-signals.md)).
For `intent-review` this needs a structured diff (`--diff`/`--diff-base`). An
unknown `--under` id exits 2.

```bash
decree intent-check  --plan "..." --files src/foo.py --under SPEC-01KT... --json
decree intent-review --diff-base origin/main          --under SPEC-01KT... --json
```

`intent-check` is deterministic. It reports structural conflicts; semantic LLM
judging can be implemented by an agent/skill that post-processes `--json`
output.

### `decree commit-check`

Report — and gate CI on — the **trailer coverage** of a change: of the files a
diff touches that are governed by an *in-flight* decision, how many carry a
matching `Implements:/Refs:/Fixes:` trailer linking them to that decision.
Advisory by default; `--strict` (require 100%) or `--min-coverage N` (ratchet for
gradual adoption) turns uncovered changes into exit 1.

```bash
# CI: gate the PR's net diff (gathers trailers across the commit range — squash-safe)
decree commit-check --diff-base origin/main --strict

# candidate-message mode (the input a commit-msg hook hands you)
decree commit-check --message "$1" --strict --json
```

It reads only the declared `governs:` layer (via `why`), never git history as
truth; it writes nothing and runs no model. It is **coverage you can gate, not a
guarantee** — `git commit --no-verify` and CI overrides exist, so it measures and
enforces where you run it; it cannot make the commit→decision link true.

Decisions and tickets are **orthogonal**: the `Implements:` trailer is a bottom
line (`git interpret-trailers`) that composes *below* your Conventional-Commits
subject and *alongside* `Change-Id`/`Signed-off-by`. decree never reads or maps
ticket IDs — a ticket is not a decision.

decree does not install a git hook (that's the harness's responsibility). To
enforce locally, opt in with a one-line `commit-msg` hook:

```sh
# .git/hooks/commit-msg  (chmod +x)
#!/bin/sh
exec decree commit-check --message "$1" --strict
```

### `decree mcp serve`

Expose decree's query and analysis API over Model Context Protocol stdio for LLM
agents. Tools (all return JSON; read-only except `report`): `why`, `refs`,
`stale`, `health`, `intent_check` (accepts `other_active_files` for
parallel-session `live_conflicts`), `intent_review`, `commit_check`
(deterministic trailer-coverage gate), `progress`, and `report`
(`dry_run` supported).

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

### Gate decree in a consumer repo

In a project that *uses* decree (rather than decree's own repo), gate the corpus
with `decree lint`. decree is **not on PyPI** (the name belongs to an unrelated
project), so install it from the repository:

```bash
uv tool install git+https://github.com/doruksahin/decree   # standalone tool
# or, as a project dependency:  uv add git+https://github.com/doruksahin/decree
```

**Recipe A — hand-rolled git hook (no framework).** Activate once with
`git config core.hooksPath .githooks`, then:

```sh
# .githooks/pre-commit
changed=$(git diff --cached --name-only)
if printf '%s\n' "$changed" | grep -Eq '^(decree/|decree\.toml$)'; then
    command -v decree >/dev/null 2>&1 || {
        echo "install decree: uv tool install git+https://github.com/doruksahin/decree" >&2
        exit 1
    }
    decree lint
fi
```

**Recipe B — the `pre-commit` framework.** Use a `language: system` local hook so
it runs the already-installed `decree` (avoid `additional_dependencies` with a
`git+` URL — it drags decree's full dependency tree into pre-commit's isolated
venv on every cold run):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: decree-lint
        name: decree lint
        entry: decree lint
        language: system
        files: '^(decree/|decree\.toml$)'
        pass_filenames: false
```

**CI (the authoritative gate).** A local hook is bypassable and depends on each
dev having decree installed, so mirror it in CI:

```yaml
- uses: astral-sh/setup-uv@v6
- run: |
    uv tool install git+https://github.com/doruksahin/decree
    echo "$HOME/.local/bin" >> "$GITHUB_PATH"
- run: decree lint
- run: decree index rebuild   # the index is a derived cache; proves the corpus indexes cleanly
```

### LLM (Claude Code, Cursor, Copilot)

LLMs should read [LLM Agent Integration](llm-agent-integration.md) for the
command loop, explicit JSON contracts, and failure policy. They create
and transition documents via CLI where possible; if they edit frontmatter
directly, they must run `decree lint` and `decree index rebuild` afterwards.

### Link checks

This repository checks markdown links with
[lychee](https://github.com/lycheeverse/lychee). The config keeps
`offline = false`, so external links are actually checked.

```bash
lychee --config .lychee.toml --no-progress '**/*.md'
```

### Changelog fragments

This repository tracks release notes with
[Towncrier](https://github.com/twisted/towncrier). Do not edit
`CHANGELOG.md` directly for normal development. Add one fragment per
user-visible change:

```bash
uv run towncrier create +.feature --content "Add governed lookup for auth files."
uv run towncrier check --staged
```

Preview release notes before publishing:

```bash
uv run towncrier build --draft --version X.Y.Z
```

### CI

`decree lint` returns exit code 1 on failure. Wire into any CI pipeline:

```yaml
- run: uv run decree lint
```

### New project adoption

The package name `decree` on PyPI is an unrelated third-party project, so install
from the repository:

```bash
uv add git+https://github.com/doruksahin/decree
```

Then scaffold the project in one command — no hand-editing `decree.toml`:

```bash
decree init   # canonical decree.toml + type dirs + worked example chain + index
decree lint   # the scaffolded project lints clean immediately
```

See [`decree init`](#decree-init) for the idempotency contract and
`--dry-run` / `--json` / `--no-examples` / `--project` flags.

To tailor the config by hand instead, a minimal `decree.toml` looks like:

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

### Auditing governance drift

```bash
decree index rebuild
decree health --json   # stale + ungoverned + dead governance (findings); suggested governance (advisory)
```

Act on each finding: update stale decisions, write ADRs for ungoverned hotspots,
fix or repoint dead `governs:` paths, and consider adding suggested paths to a
decision's `governs:`. See [health-signals.md](health-signals.md) for the full
detect → interpret → act flow.

### Onboarding someone

Point them to the index file for a given document type — auto-generated table of all documents with status, date, and supersede links.
