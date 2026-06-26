# Changelog

All notable changes to Decree are documented here.

<!-- towncrier release notes start -->

## v1.2.0 - 2026-06-26

### Features

- Add optional sprint ledger tracking with `decree sprint`, active-sprint
  defaults for new SPEC/progress/DDD, sprint lint invariants, and MCP progress
  scope parity.

### Documentation

- Document and prototype the planned sprint-scoped execution workflow and
  end-user behavior.


## v1.1.0 - 2026-06-04

### Features

- Add `decree commit-check`: a deterministic trailer-coverage gate (and
  matching MCP tool) that reports which governed-file changes in a diff lack an
  `Implements:/Refs:/Fixes:` trailer linking them to their in-flight decision.
  Advisory by default; `--strict`/`--min-coverage` gate CI on the net diff
  (squash-safe via `--diff-base`). Reads only declared `governs:`; coverage you
  can gate, not a guarantee.
- Add `decree init`: a deterministic, idempotent project scaffolder that
  creates a canonical `decree.toml`, the type directories, a worked
  PRD→ADR→SPEC example chain, a `.gitignore` rule for the derived `.decree/`
  cache, and a built index — reporting every action with a reason (created /
  skipped / wrote / appended / rebuilt). It respects an existing `decree.toml`:
  it leaves it untouched and scaffolds *its* declared types rather than
  imposing the default trio (no orphan directories in a custom corpus), and
  reports a malformed config clearly without touching it. The report is clean
  and ordered: the derived index cache is reported as *rebuilt* (never counted
  as a creation), and a re-run on a set-up project prints `Already initialized
  — nothing to create (index refreshed).`. Flags: `--dry-run`, `--json`,
  `--no-examples`, and `--project`. The scaffolded project lints clean
  immediately.
- Add a machine-readable error contract for `--json` consumers: when a command
  run with `--json` hits an unexpected error, decree now emits a stable
  `{"schema": "decree.error.v1", "error": {...}}` object on stdout (and a clean
  one-line summary on stderr) and exits 2, instead of leaking a Python
  traceback. Without `--json`, the human/developer path is unchanged.

### Bug Fixes

- CI and release workflows now run `decree index rebuild` before `decree index
  verify`, so the verify step no longer fails on a fresh checkout (the
  `.decree/index.sqlite` cache is gitignored and absent until rebuilt). The
  link check tolerates slow external reference links.
- Correct stale "publishes to PyPI" release-automation wording in the README
  and capability index — decree distributes via GitHub Releases and a Homebrew
  tap, not PyPI. The link check now verifies the project homepage
  (decree.doruk.uk) instead of excluding it.

### Documentation

- Add `docs/json-contracts.md`: the reference for programmatic consumers — the
  `--json` stdout/stderr split, the **exit-code contract** (0 = clean, 1 =
  findings with JSON still on stdout, 2 = hard error), the `decree.error.v1`
  shape, and per-command payload keys. Also document copy-paste recipes for
  gating decree in a consumer repo (hand-rolled git hook, `pre-commit`
  framework, and CI) in `docs/usage.md`.


## v1.0.0 - 2026-06-03

### Breaking Changes

- Remove in-core LLM provider execution from governs migration and
  intent-check; replace it with deterministic analyze/apply JSON contracts for
  agent-owned suggestion generation.

### Features

- Add `decree graph --json` emitting the full decision graph (documents +
  reference edges) as a stable, ULID-aware machine contract for external
  consumers, without touching index.md.
- Add `decree progress --json` emitting structured per-document and aggregate
  acceptance-criteria counts (doc/chain/whole-corpus scopes) as a stable
  machine contract for external consumers.
- Add `progress` and `report` MCP tools and an `other_active_files` parameter
  to `intent_check` (surfacing cross-session `live_conflicts`), so agent hosts
  can run governed parallel sessions: scoped governance preflight, live
  file-overlap detection, and objective acceptance-criteria closeout over MCP.
- Add a `governs` field to each document in `decree graph --json`, exposing the
  repo-relative paths a decision governs (with any `#symbol` suffix stripped)
  so external consumers can seed governed sessions from a decision.
- Add parallel-safe `TYPE-ULID` document identity, explicit ID migration,
  scoped progress/DDD views, and fail-closed generated-artifact ownership.
- Add tag-triggered release automation that validates releases, builds
  distributions, creates GitHub Releases with the wheel and sdist, bumps the
  Homebrew tap, and keeps workflow YAML under actionlint CI.
- Expose `decree --version` and single-source runtime package version reads
  from installed `pyproject.toml` metadata.
- The MCP `health` tool and `decree ddd` now surface the governance-drift
  signals — dead governance (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D) and advisory
  suggested governance (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ). The MCP `health`
  payload is serialized through the same formatter as `decree health --json`,
  so the two never diverge and agents receive both signals over MCP. `decree
  ddd` reports per-corpus dead/suggested-governance counts as a lifecycle hint
  — a fail-safe, pure index read (no git walk; zero, never an error, when there
  is no index). `decree lint` is deliberately left untouched: it validates
  document structure and never reads the index, and the codebase keeps
  validation separate from coherence.
- `decree health` now reports **dead governance** — declared `governs:` paths
  that no trailer-linked commit has ever touched — backed by a new
  `observed_governs` index. Advisory and fail-safe: a decision with no
  trailer-linked commits is reported "unobserved", not dead, and the output is
  coverage-honest (per-decision linked-commit counts and an "as of last index
  sync" timestamp).
- `decree health` now reports **suggested governance** (advisory) — files a
  decision's own trailer-linked commits repeat-touch (≥2 distinct commits) but
  that it does not declare in `governs:` and no decision owns, surfaced as
  "ungoverned files with a proposed owner." It is the inverse of
  dead-governance and deliberately lower-authority: it never affects `decree
  health`'s exit status and is never read by `why()`. Precision rests on
  per-decision repeat-touch attribution rather than cross-decision frequency
  (which squash commits defeat), with a shared-infrastructure floor and
  deterministic, path-based filtering (no working-tree reads).
- `decree intent-check` and `decree intent-review` accept `--under <decision>`
  (and an `under` parameter on the matching MCP tools). When a governed session
  passes the decision it works under, the report surfaces `governs_gaps` —
  planned/changed files that decision's own trailer-linked commits repeat-touch
  (>=2 commits, squash-immune) but it does not declare — plus a soft
  `declare_governs` recommendation. It is the point-of-change counterpart to
  batch missing-governance (`decree health`): scoped to a known decision and a
  live edit, it drops the cross-decision filters the batch surface needs, so it
  surfaces decision-specific gaps the batch surface suppresses. Advisory only —
  it never changes the exit code, never feeds `why()`, and never writes; the
  agent makes the deliberate `governs:` edit. An unknown `--under` id exits 2.

### Bug Fixes

- Install instructions now install decree from its GitHub repository; the bare
  name `decree` on PyPI is an unrelated third-party project.
- decree is distributed from GitHub Releases and a Homebrew tap, not PyPI: the
  name `decree` there is an unrelated third-party project, so Trusted Publishing
  could never succeed. The release workflow ships the wheel and sdist as GitHub
  Release assets and auto-bumps the tap.
- `decree health` no longer proposes documentation files (`.md` / `.rst`) as
  suggested-governance candidates. A decision's implementing commit and a later
  docs commit can both carry its trailer, repeat-touching `README.md` /
  `AGENTS.md` / `docs/*.md`; documentation is never a `governs:` target, so it
  is now excluded from missing-governance alongside tests and changelog
  fragments. Surfaced by the decree dogfood once the governance feature itself
  was developed across multiple trailer-linked commits.

### Documentation

- Add runnable example scenarios under `examples/`: six self-contained scripts
  that build a throwaway git corpus and run real `decree` commands (`why`,
  `intent-check`, `intent-review`, `health`, and the `--under` governs-gap),
  each printing real output with a `VALUE:` line (what you gain) and a
  `HONESTY:` line (where decree refuses to overclaim — advisory vs finding,
  structural vs semantic, convention vs certainty). They walk the lifecycle of
  one change (before → while → after → over time), use pinned IDs for
  reproducibility, and double as smoke tests for the `--json` shapes and the
  exit-code contract.
- Document decree's capability map, LLM agent integration contract,
  link-checking policy, package version source of truth, and Towncrier-based
  release workflow.
- Document progressive-disclosure AGENTS files so future LLM sessions can
  safely contribute to the repository.
- Document the agentkith MCP integration: add SPEC-01KT3M6NY02TXXPJCP52QEYFW1,
  and sync the agent-integration / usage / capability-index docs and `decree
  mcp` help to the `progress`/`report` tools and `intent_check` cross-session
  `other_active_files`/`live_conflicts`.
- Documented the governance-drift health signals end to end. A new [Health
  Signals](docs/health-signals.md) reference covers all four `decree health`
  signals (stale decisions, ungoverned hotspots, dead governance, advisory
  suggested governance), their exit semantics, the JSON/MCP payload, and the
  detect → interpret → act flow. The `decree health` and `decree ddd` `--help`
  text and the MCP `health` tool description now name every signal and state
  which are findings (exit 1) versus advisory (exit 0), and the provenance
  model, capability index, usage guide, and agent-integration docs link the new
  reference.

### Dependency Changes

- Add Towncrier as the changelog-fragment tool and enforce news fragments
  through pre-commit and pull-request CI.


## v0.1.0 — Multi-doctype Decree

Renamed from `madr-tools` to `decree`. Full rewrite as a general-purpose
document lifecycle toolkit.

- **Multi-doctype support** -- PRD, ADR, SPEC with independent lifecycles
- **`decree.toml` config** -- all types, statuses, transitions, and sections driven by TOML
- **Cross-type references** -- lint detects dangling and stale refs across doc types
- **C4 architecture support** -- opt-in C4 level tracking per document type
- **Progress tracking** -- `decree progress` reports checkbox completion across all docs
- **Model diagram** -- `decree model` generates PRD/ADR/SPEC relationship diagrams
- **Graph command** -- Mermaid timeline, supersede chain, and status pie charts
- **Claude Code skills** -- `/decree:prd`, `/decree:adr`, `/decree:spec`, `/decree:lint`, `/decree:init`, `/decree:ddd`

## v0.x — madr-tools

Initial single-type ADR management tool based on MADR v4.0.0.

- `new` -- create ADR with numeric auto-numbering and slug
- `status` -- enforce lifecycle transitions (proposed/accepted/rejected/deprecated/superseded)
- `lint` -- frontmatter validation, required sections, supersede symmetry
- `index` -- auto-generated markdown table from frontmatter
- Pydantic-validated frontmatter, python-frontmatter I/O
