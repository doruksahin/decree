# Decree Capability Index

This is the entry point for integrating decree into a project or an LLM-agent
workflow.

Decree stores product intent, architecture decisions, implementation
blueprints, and code ownership links in the same repository as the code. The
core question it answers is:

> Which decision explains this code, and is the planned change still aligned
> with that decision chain?

## Operating Model

Decree is intentionally explicit:

- Authoring truth lives in markdown frontmatter and body sections.
- `.decree/index.sqlite` is a derived query cache. Rebuild it explicitly with
  `decree index rebuild`.
- Generated `index.md` tables are refreshed explicitly with
  `decree index regenerate`.
- Completion reports are snapshots. Refresh them explicitly with
  `decree report regenerate`.
- Query commands fail closed when the SQLite index is missing or stale. They do
  not silently rebuild or return best-effort stale answers.
- LLM calls are opt-in. Commands that need a model document their provider
  resolution chain and surface per-call failures.
- Legacy sequential IDs are migration input only. Runtime identity is the
  canonical frontmatter `TYPE-ULID`.

## Capability Map

| Capability | Primary commands | What it is for |
|------------|------------------|----------------|
| Document lifecycle | `decree new`, `decree status`, `decree lint` | Create PRDs, ADRs, SPECs, enforce valid status transitions, and validate references. |
| Parallel-safe identity | `decree new`, `decree migrate ids` | Generate distributed `TYPE-ULID` IDs and explicitly convert old numeric corpora. |
| Sprint execution tracking | `decree sprint`, `decree progress --corpus` | Optionally scope active work to a sprint ledger while keeping PRD/ADR/SPEC references as governance truth. |
| Scoped progress | `decree progress`, `decree ddd` | Track checkbox progress globally, by sprint, or by document, chain, changed files, governed path, backlog, or draft pool. |
| Governed-file lookup | `decree why`, `decree refs` | Ask which decisions govern a file and what depends on a decision. |
| Index maintenance | `decree index rebuild`, `decree index verify`, `decree index status` | Keep the SQLite query cache synchronized and auditable. |
| Generated tables and graphs | `decree index regenerate`, `decree graph` | Refresh document tables and Mermaid diagrams from frontmatter. |
| Commit provenance | `decree commit` | Add `Implements:`, `Refs:`, and `Fixes:` trailers to git commits and sync them into the index. |
| Governance & coherence drift | `decree health`, `decree stale` | Surface stale decisions, ungoverned hotspots, **dead governance** (declared paths no commit touched), and advisory **suggested governance** (repeat-touched but undeclared paths). See [health-signals.md](health-signals.md). |
| Pre-code planning guard | `decree intent-check` | Check a plan and planned file list against existing decisions before coding starts; pass other live sessions' files (`--other-active-files`) to flag parallel `live_conflicts`, or `--under <decision>` for advisory `governs_gaps`. |
| Post-code intent review | `decree intent-review` | Compare a diff against governed decisions before code review; `--under <decision>` adds advisory `governs_gaps`. |
| Agent-assisted adoption | `decree migrate governs` | Analyze missing `governs:` links and apply explicit external suggestions for an existing decision corpus. |
| Agent integration | `decree mcp serve`, Claude Code hook/plugin | Expose decree state to LLM agents through task-shaped tools and session-end snapshots. |
| Retrieval evaluation | `decree retrieval-eval` | Measure query quality with labeled data, baselines, and optional calibrated abstention. |
| Architecture modeling | `decree lint`, `decree graph` with `[types.<name>.c4]` | Validate and render C4 system/container/component relationships. |
| Package versioning | `decree --version` | Expose the installed package version from `pyproject.toml` metadata. |
| Changelog fragments | `uv run towncrier create`, `uv run towncrier build` | Capture release notes at change time and generate `CHANGELOG.md` at release time. |
| Release automation | `.github/workflows/release.yml` | Validate tag releases, build distributions, create GitHub Releases, and bump the Homebrew tap (not published to PyPI). |

## Integration Sequence

Use this sequence when adding decree to another application.

1. Install decree in the target project.

   The package name `decree` on PyPI belongs to an unrelated third-party
   project, so install decree from this repository:

   ```bash
   # as a project dependency
   uv add git+https://github.com/doruksahin/decree
   # or as a standalone tool
   uv tool install git+https://github.com/doruksahin/decree
   ```

2. Scaffold the project with `decree init`.

   ```bash
   decree init   # canonical decree.toml + PRD/ADR/SPEC dirs + worked example
                 # chain + .gitignore for the cache + built index; lints clean
   decree lint
   ```

   This generates the canonical `decree.toml` (PRD, ADR, and SPEC types) so you
   do not hand-edit config, and adds a `.gitignore` rule for the derived
   `.decree/` cache. It is idempotent and never overwrites existing files; if a
   `decree.toml` already exists it is left unchanged and its declared types are
   scaffolded instead of the default trio. Use `--no-examples` to skip the
   seeded chain, or `--dry-run` to preview. See [`decree init`](usage.md#decree-init)
   and [configuration](configuration.md).

3. Create or import your own documents (the seeded example chain is just a
   starting point — keep it, edit it, or delete it).

   ```bash
   decree new prd "Decision Lifecycle"
   decree new adr "Store Decisions in Repo"
   decree new spec "Decision Index"
   ```

4. Optionally enable sprint-scoped execution tracking.

   Sprint mode changes task-facing defaults only after the ledger exists:

   ```bash
   decree sprint init "Sprint 1"
   decree progress          # active sprint scope
   decree progress --corpus # whole-corpus scope
   ```

   New SPECs enter the active sprint by default while sprint mode is active.
   Use `--backlog --reason` or `--draft-pool --reason` for work that should not
   be committed to the current sprint.

5. If importing an old numeric corpus, convert it once.

   ```bash
   decree migrate ids --dry-run
   decree migrate ids --apply
   ```

6. Add `governs:` coverage.

   Do this manually for critical areas. For large existing corpora, generate
   deterministic analysis for an agent/skill, then apply the reviewed
   suggestions file:

   ```bash
   decree migrate governs --analyze --json > governs-analysis.json
   # agent/skill writes governs-suggestions.json
   decree migrate governs --apply-suggestions governs-suggestions.json
   decree migrate governs --apply-suggestions governs-suggestions.json --apply --yes
   ```

7. Build and verify the query cache.

   ```bash
   decree index rebuild
   decree index verify
   ```

8. Use the governance loop during development.

   ```bash
   decree why src/foo.py
   decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX
   decree progress --governs src/foo.py
   decree intent-check --plan "Change foo behavior" --files src/foo.py
   decree intent-review --diff-base origin/main
   ```

9. Add a changelog fragment for the change.

   ```bash
   uv run towncrier create +.feature --content "Add governed lookup for auth files."
   ```

10. Wire validation into developer workflow.

   Run `decree lint`, `decree index verify`, tests, and link checks before
   merge. If using pre-commit, keep the lychee and towncrier hooks active so
   markdown links and changelog fragments stay valid.

11. Expose decree to LLM agents only after the corpus is indexed.

   ```bash
   decree mcp serve --project .
   decree hook install
   ```

## LLM Boundary

Core decree does not call LLM providers. It emits explicit JSON contracts and
validates explicit JSON inputs.

- `decree migrate governs --analyze --json` emits
  `decree.governs-analysis.v1` for an external agent/skill.
- Agents may call Claude Code, OpenAI, local models, or a human review process
  outside decree.
- `decree migrate governs --apply-suggestions FILE` accepts only
  `decree.governs-suggestions.v1`, validates it, previews a diff, and writes
  only with `--apply`.
- `decree intent-check` reports deterministic structural conflicts. Semantic
  LLM judging belongs in an agent layer that post-processes `--json` output.

## Link Checking

This repository uses [lychee](https://github.com/lycheeverse/lychee) through
pre-commit. The config is online by default (`offline = false`) so external
references are checked instead of skipped.

Run it manually with:

```bash
lychee --config .lychee.toml --no-progress '**/*.md'
```

## Reference Docs

- [Agent Onboarding](../AGENTS.md): contribution rules for LLM agents working
  in this repository.
- [README](../README.md): package overview and quick start.
- [Usage](usage.md): command-by-command examples.
- [Configuration](configuration.md): `decree.toml` schema.
- [LLM Agent Integration](llm-agent-integration.md): provider-free agent
  contract and command loop.
- [JSON Contracts](json-contracts.md): the `--json` stdout/stderr split,
  exit-code contract, `decree.error.v1` error shape, and per-command payloads
  for programmatic consumers.
- [decree-governs-suggest skill](../skills/decree-governs-suggest/SKILL.md):
  agent-side `governs:` suggestion workflow.
- [Release, Changelog, and Versioning](release.md): package version source of
  truth, Towncrier fragments, and release checklist.
- [Architecture](architecture.md): internal module responsibilities.
- [Roadmap](roadmap.md): planned future work.
