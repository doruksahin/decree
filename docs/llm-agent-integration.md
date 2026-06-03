# LLM Agent Integration

This document is the progressive-disclosure entry point for using decree from
LLM agents and automation.

For the full command capability map and new-project adoption sequence, start
with the [Capability Index](index.md).

## Contract

- `decree.toml` is the project contract. Document types, status lifecycles,
  required sections, coherence gates, and health thresholds live there.
- Frontmatter is authoring truth. `.decree/index.sqlite` is a derived query
  cache and must be rebuilt with `decree index rebuild` after corpus changes.
- Completion reports are generated snapshots, not authoring truth. If checked
  acceptance criteria change after a terminal status transition, refresh them
  with `decree report regenerate`.
- Commands that can be consumed by agents expose `--json` where the output is a
  stable schema. Prefer JSON for automation.
- Empty arrays are valid abstentions. Agents must not invent governance when
  `matches`, `governing_decisions`, or `conflicts` are empty.
- User-visible changes require a Towncrier fragment in `changelog.d/`. Agents
  should write the fragment in the same change while context is fresh.

## Recommended Agent Loop

0. If the project is not yet set up, an agent can scaffold it in one machine-readable
   step with `decree init --json` (idempotent; never overwrites existing files).
1. Run `decree lint`.
2. Run `decree index rebuild`.
3. Before coding, run `decree intent-check --plan "..." --files ... --json`. When
   other agent sessions run in parallel, also pass their planned paths via
   `--other-active-files '{"session-id": ["path", ...]}'` so the report includes
   `live_conflicts` (files another live session is about to write). In a governed
   session, pass `--under <your-decision>` so the report also surfaces
   `governs_gaps` — files your decision repeat-touches but doesn't declare.
4. If the response recommends `draft_adr_first`, `update_spec_first`,
   `resolve_conflict_first`, or `isolate_session`, resolve it before
   implementation. For `isolate_session`, run in a dedicated worktree or split
   the overlapping file out of one plan.
5. After code exists, run `decree intent-review --json` to compare the diff
   against the same governance corpus. Commit through `decree commit` so the
   change carries an `Implements:` trailer linking it to its decision, and gate
   the net diff in CI with `decree commit-check --diff-base origin/main --strict`
   — it reports which governed-file changes lack a matching trailer (coverage you
   can gate, not a guarantee).
6. Run `decree lint` again after changing decree documents.
7. Add or verify a `changelog.d/` Towncrier fragment for user-visible changes.

Between the rebuild (step 2) and planning (step 3), run `decree health --json`
(or the MCP `health` tool) to surface governance drift — stale decisions,
ungoverned hotspots, dead governance, and advisory suggested governance — and
resolve dead governance before it compounds. See
[health-signals.md](health-signals.md) for the detect → interpret → act flow.

## Agent-Owned LLM Calls

Core decree does not resolve models, read provider API keys, shell out to
Claude Code, or call litellm. LLM execution belongs to the agent runtime.

For `governs:` migration, use this handoff:

If your agent supports portable skills, use
[decree-governs-suggest](../skills/decree-governs-suggest/SKILL.md) for the
suggestion-generation step.

1. Run:

   ```bash
   decree migrate governs --analyze --json > governs-analysis.json
   ```

2. The agent reads `decree.governs-analysis.v1`, calls any chosen model/runtime,
   and writes:

   ```json
   {
     "schema": "decree.governs-suggestions.v1",
     "suggestions": [
       {
         "document_id": "SPEC-01KT22...",
         "governs": ["src/decree/commands/migrate.py"],
         "confidence": "high",
         "rationale": "The SPEC owns this command."
       }
     ]
   }
   ```

3. Preview and apply through core decree:

   ```bash
   decree migrate governs --apply-suggestions governs-suggestions.json
   decree migrate governs --apply-suggestions governs-suggestions.json --apply --yes
   ```

The agent owns prompts, retries, rate limits, auth, and provider flags. Decree
owns schema validation, diff rendering, and writes.

## No Hidden Fallbacks

- Missing indexes are errors with a hint to run `decree index rebuild`.
- Stale indexes are errors for query commands and MCP query tools. Rebuild the
  index before asking `why`, `refs`, `intent-check`, or `intent-review` to make
  governance claims.
- Invalid `governs` suggestions are reported and block writes.
- `decree intent-check` reports structural conflicts. Agents may perform
  semantic judging externally from `--json` output, but core decree never hides
  structural conflicts behind provider failures.
- Non-git projects make git-derived health and commit-sync data unavailable.
  Commands must say this in their result or documentation instead of implying
  that no history exists.

## Responsibilities

- `src/decree/cli.py`: command registration and user-facing help only.
- `src/decree/llm_io.py`: fenced JSON parsing only. Provider execution belongs
  outside core decree.
- `src/decree/index_db.py`: deterministic derived index and git trailer sync.
  Provenance is convention-bounded — commit→files is git-guaranteed, commit→decision
  is the trailer convention; see [provenance-model.md](provenance-model.md).
- `src/decree/commands/queries.py`: `why` and `refs` library/CLI behavior.
- `src/decree/commands/intent_check.py`: pre-code governance reports.
- `src/decree/commands/intent_review.py`: post-code diff governance reports.
- `src/decree/commands/migrate.py`: corpus migration/audit tooling.
- `src/decree/commands/mcp_server.py`: MCP tool wrappers; no duplicate query
  logic.

## MCP Tools

`decree mcp serve` exposes the query/analysis surface to agents over stdio.
Nine tools, all returning JSON (read-only except `report`):

- `why`, `refs` — governed-file lookup and reverse reference graph.
- `stale`, `health` — staleness and coherence drift. `health` returns four
  signals: stale decisions, ungoverned hotspots, **dead governance** (findings,
  exit 1) and advisory **suggested governance** (exit 0, never feeds `why`); see
  [health-signals.md](health-signals.md).
- `intent_check` — pre-code governance; accepts `other_active_files`
  (`{session_id: [paths]}`) and returns `live_conflicts` for parallel sessions.
  In a governed session, also pass `under` (the decision you work under) to get
  `governs_gaps` — files it repeat-touches but doesn't declare, advisory.
- `intent_review` — post-code diff governance; also accepts `under` for
  `governs_gaps` (point-of-change counterpart to `health`'s suggested governance;
  see [health-signals.md](health-signals.md)).
- `commit_check` — trailer-coverage gate: which governed-file changes in a diff
  lack a matching `Implements:/Refs:/Fixes:` trailer linking them to their
  in-flight decision. Advisory by default; `strict`/`min_coverage` for CI. Reads
  only declared `governs:`; coverage you can gate, not a guarantee.
- `progress` — acceptance-criteria completion for a doc / chain / corpus
  (objective closeout signal).
- `report` — regenerate completion-report artifacts (`dry_run` supported; the
  only write tool).

## Useful Commands

```bash
decree --help
decree init --json
decree lint
decree index rebuild
decree health --json
decree stale --json
decree report regenerate --all --existing-only
decree why src/foo.py --json
decree refs SPEC-01KT22NMS0D19VMD8VPK4D2MNX --json
decree progress --changed --base origin/main
decree intent-check --plan "..." --files src/foo.py --json
decree intent-check --plan "..." --files src/foo.py \
  --other-active-files '{"session-b": ["src/foo.py"]}' --json
decree intent-review --json
decree migrate ids --dry-run
decree migrate audit-coherence --json
decree migrate governs --analyze --json
decree migrate governs --apply-suggestions governs-suggestions.json
uv run towncrier create +.feature --content "Add governed lookup for auth files."
uv run towncrier check --staged
```
