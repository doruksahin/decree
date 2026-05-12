---
date: '2026-05-12'
governs:
- src/decree/commands/intent_check.py
references:
- PRD-004
status: implemented
---

# SPEC-014 decree intent-check — Pre-PR Planning-Phase Governance

## Overview

Implements PRD-004 R2 — **pre-PR intent_check**. The post-code counterpart (`decree intent-review`) was shipped in SPEC-009. This SPEC adds the *planning-phase* counterpart: an LLM agent says "I'm about to implement X" and `decree.intent_check(plan, planned_files)` returns the governance map *before* any code is written.

This is the entire.io thesis at decree's surface: shift decree from passive record-keeping to active influence on what gets built. After SPEC-014 lands, **PRD-004 v1 closes**.

The implementation is mostly composition of existing components — same trick that worked for SPEC-009:
- `queries.why()` / `queries.refs()` from SPEC-005
- `health.stale_decisions()` from SPEC-008
- Calibrated abstention from SPEC-013 (so intent_check inherits the trust surface)
- Optional LLM-judged semantic conflict detection via `litellm` (already in deps from SPEC-011) — the genuinely-new bit

PM directive carried forward: leverage existing components; the only "new" code is the conflict-judging prompt template and the report composition.

## Technical Design

### CLI surface

```
decree intent-check --plan "I'm going to add caching for the auth path"
                    --files src/auth.py src/cache.py
                    [--with-abstention] [--target-precision P]
                    [--judge-conflicts]
                    [--model MODEL]
                    [--json] [--project PATH]
```

- `--plan TEXT` — free-form plan summary (required). One sentence to one paragraph.
- `--files PATH...` (required, repeatable) — repo-relative paths the plan will touch.
- `--with-abstention` — route governance lookups through SPEC-013's calibrated method.
- `--target-precision P` — calibration target (same semantics as SPEC-013).
- `--judge-conflicts` — for each structural conflict, run an LLM judge to decide whether the conflict is real or two decisions about different aspects. Off by default to keep the command latency-free without an API key.
- `--model MODEL` — litellm model string (same resolution chain as SPEC-011).
- `--json` — structured output.
- `--project PATH` — operate against the project at PATH.

Exit codes:
- `0` — no conflicts (real or judged) and no stale governance.
- `1` — at least one conflict or stale governance entry surfaced.
- `2` — config error (no API key when `--judge-conflicts`, missing required flags, etc).

### IntentCheckReport shape

```python
@dataclass(frozen=True)
class IntentCheckReport:
    plan: str
    planned_files: tuple[str, ...]
    governing_decisions: tuple[GoverningSnapshot, ...]   # reused from SPEC-009
    stale_governance: tuple[dict, ...]                   # reused from SPEC-009
    unchecked_acceptance_criteria: tuple[UncheckedAC, ...]  # reused
    conflicts: tuple[Conflict, ...]                      # reused; enriched if --judge-conflicts
    abstention: dict | None                              # set if calibrated method abstained
    recommended_actions: tuple[Recommendation, ...]      # new verbs for pre-code phase
```

Differences from SPEC-009's `IntentReport`:

- **`planned_files` replaces `changed_paths`** — same data shape, different semantic.
- **`plan` field surfaced** — useful for LLM-judged conflicts (the judge needs the plan as context).
- **`conflicts` may be LLM-enriched** — each `Conflict` gains an optional `semantic_verdict: dict { is_real_conflict: bool, reasoning: str }` when `--judge-conflicts` is set.
- **`abstention` field added** — when `--with-abstention` is set and all governance lookups abstain.
- **`recommended_actions` new verbs**:
  - `draft_adr_first` — no governance found AND plan mentions architectural keywords ("design", "architecture", "system", "decide").
  - `update_spec_first` — in-flight SPEC has unchecked ACs the plan would affect.
  - `resolve_conflict_first` — structural or semantic conflict on planned files.
  - `proceed` — no blockers detected.
  - Plus reuse of SPEC-009 verbs: `update_decision`, `check_ac`, `add_governance`.

### LLM-judged conflict detection (`--judge-conflicts`)

For each structural conflict from the index (two decisions sharing a `governs:` path), call an LLM with this prompt (added to `src/decree/migrate_prompts.py` alongside SPEC-011's prompt):

```
Two decisions in this repo's governance corpus both claim to govern the
same file path. Determine whether they are a *real* conflict (they
disagree about how the file should behave) or *complementary* (they
address different aspects of the same file — different layers,
different concerns, different lifecycles).

Context:
  Plan being checked: <plan>
  Shared path: <path>

Decision A: <decision_id_a>
Title: <title_a>
Body excerpt: <body_a, truncated 2000 chars>

Decision B: <decision_id_b>
Title: <title_b>
Body excerpt: <body_b, truncated 2000 chars>

Return JSON: {"is_real_conflict": bool, "reasoning": "one sentence"}
```

Uses `litellm.completion()` with the same model-resolution chain as SPEC-011. Failures fall back to structural-only (the conflict still surfaces, just without semantic verdict).

### Library shape

```python
# src/decree/commands/intent_check.py

def intent_check(
    db: IndexDB,
    project_root: Path,
    plan: str,
    planned_files: list[str],
    *,
    with_abstention: bool = False,
    judge_conflicts: bool = False,
    model: str | None = None,
    threshold_commits: int = 10,
) -> IntentCheckReport:
    ...

def intent_check_run(args: argparse.Namespace) -> int:
    ...
```

Internal composition:
1. For each planned_file: call `queries.why(db, p, with_abstention=with_abstention)`. Dedupe into `governing_decisions`.
2. From the id set: pull unchecked ACs (same SQL as SPEC-009).
3. Call `health.stale_decisions(db, project_root, threshold_commits)`; intersect with governing ids → `stale_governance`.
4. Structural conflict detection (same SQL as SPEC-009).
5. If `judge_conflicts=True`: for each conflict, call LLM with context. Set `semantic_verdict`.
6. Generate `recommended_actions` from signals + plan keyword heuristics.

### MCP tool

The 6th tool. Same 5-section docstring quality bar from SPEC-007.

```python
@mcp.tool()
def intent_check(
    plan: str,
    planned_files: list[str],
    with_abstention: bool = False,
    judge_conflicts: bool = False,
) -> dict:
    """Pre-code governance check — what decisions apply to your plan?
    
    Args:
        plan: One-sentence to one-paragraph description of what you intend to build.
        planned_files: List of repo-relative paths you'll create or modify.
        with_abstention: Route governance lookups through calibrated abstention
            (SPEC-013). Recommended for agent loops that will trust the output.
        judge_conflicts: Run an LLM judge on structural conflicts to decide if
            they're real (disagreement) or complementary (different aspects).
            Adds ~3-5s latency per conflict; requires an LLM API key.
    
    Returns:
        Structured IntentCheckReport with governing_decisions, stale_governance,
        unchecked_acceptance_criteria, conflicts (optionally LLM-judged),
        abstention (when applicable), recommended_actions.
    
    When to call:
        - At the *start* of an implementation task, before writing any code.
        - When the user gives a task and you're about to make a plan; call this
          to see what existing decisions constrain your plan.
        - Before opening a PR with a fresh feature branch — sanity-check.
    
    When not to call:
        - For trivial refactors or documentation changes (high overhead).
        - After code is written — that's `intent_review` (SPEC-009), not this.
        - For exploratory code not intended to be merged.
    """
    ...
```

Tool registry grows from 5 to 6 (`why`, `refs`, `stale`, `health`, `intent_review`, `intent_check`).

### Files touched

- **Create**: `src/decree/commands/intent_check.py` — library function + CLI handler + dataclasses (reuse SPEC-009's dataclasses where possible).
- **Modify**: `src/decree/migrate_prompts.py` — add `CONFLICT_JUDGE_PROMPT_TEMPLATE` + `build_conflict_judge_prompt(plan, path, doc_a, doc_b)`.
- **Modify**: `src/decree/commands/mcp_server.py` — register `intent_check` as the 6th tool.
- **Modify**: `src/decree/cli.py` — register `decree intent-check` subcommand.
- **Create**: `tests/test_intent_check.py` — unit + integration coverage; LLM judge mocked.
- **Modify**: `tests/test_mcp_server.py` — extend tool registry assertions to 6 tools.

### What this SPEC does NOT do

- **No live LLM calls in CI** — `--judge-conflicts` mocked.
- **No symbol-level governance** — file-level only.
- **No agent-loop integration** — the tool is available; integration into a specific agent's planning workflow is a consumer concern.
- **No webhook / GitHub bot** — research-frontiers D.3.
- **No multi-step plan parsing** — `plan` is opaque context for the LLM judge.
- **No automatic decree-toml editing** — recommendations are informational.

## Testing Strategy

### Unit tests (`tests/test_intent_check.py`)

- **Empty plan / empty files**: returns IntentCheckReport with empty arrays; `recommended_actions` includes `proceed`.
- **Planned files match in-flight SPEC**: `governing_decisions` includes that SPEC; `unchecked_acceptance_criteria` populated; `recommended_actions` includes `update_spec_first` and/or `check_ac`.
- **Planned files have no governance**: `governing_decisions` empty; `recommended_actions` includes `add_governance` per file; if plan summary contains "design"/"architecture"/"system"/"decide" → `draft_adr_first` heuristic.
- **Stale governance**: SPEC governs file, file has churned without SPEC being touched → `stale_governance` populated; `recommended_actions` includes `update_decision`.
- **Structural conflict**: two SPECs governing same path → `conflicts` populated; `recommended_actions` includes `resolve_conflict_first`.
- **`--judge-conflicts` real conflict**: mock LLM returns `is_real_conflict=true` → conflict's `semantic_verdict` populated.
- **`--judge-conflicts` complementary**: mock LLM returns `is_real_conflict=false` → still listed but `semantic_verdict.is_real_conflict=false`.
- **`--judge-conflicts` LLM error**: mock raises → conflict still surfaces without verdict; no crash.
- **`--with-abstention`**: planned files where calibrated method abstains → `abstention` field populated.
- **`--json` output**: schema-stable.
- **CLI flags**: all flag combinations parse.
- **Exit codes**: 0 clean, 1 with conflicts/stale, 2 missing API key under `--judge-conflicts`.

### MCP tests (`tests/test_mcp_server.py` extension)

- **`intent_check` tool — minimal**: pass plan + files, assert report shape.
- **`intent_check` tool — `with_abstention=True`**: routes through calibrated.
- **`intent_check` tool — `judge_conflicts=True`**: mock LLM, assert semantic_verdict surfaces.
- **Tool registry**: 6 tools total.

### Integration test

- **End-to-end against decree corpus**: `decree intent-check --plan "Add staleness threshold config" --files src/decree/commands/health.py`. Should return SPEC-008 as governing.
- **End-to-end JSON**: parsable, has expected keys.

### Dogfood

- SPEC-014's `governs:` declares `src/decree/commands/intent_check.py` after creation.
- PM smoke-tests the MCP tool from a Claude Code session.

## v1 Acceptance Criteria

### Library + CLI

- [ ] `src/decree/commands/intent_check.py` exists with `intent_check()`, `intent_check_run()`, `IntentCheckReport`.
- [ ] Library composes existing helpers (`queries.why`, `queries.refs`, `health.stale_decisions`, optionally calibrated routing).
- [ ] `decree intent-check` subcommand registered with all flags.
- [ ] Exit codes match SPEC.
- [ ] `--with-abstention` routes governance lookups through SPEC-013.
- [ ] `--judge-conflicts` calls litellm for each structural conflict.

### LLM judge

- [ ] `build_conflict_judge_prompt(plan, path, doc_a, doc_b)` added to `migrate_prompts.py`.
- [ ] Uses `litellm.completion()` with the SPEC-011 model-resolution chain.
- [ ] LLM failure falls back to structural-only conflict listing (no crash).
- [ ] Response parsing tolerates fenced JSON (reuse `_parse_llm_json` from SPEC-011 or copy pattern).

### Recommendations

- [ ] 5 new verbs emitted appropriately: `draft_adr_first`, `update_spec_first`, `resolve_conflict_first`, `proceed`, plus reuse of SPEC-009 verbs.
- [ ] Recommendations deterministic given the same inputs.

### MCP tool

- [ ] `intent_check` registered with 5-section docstring.
- [ ] Accepts `plan: str`, `planned_files: list[str]`, `with_abstention: bool = False`, `judge_conflicts: bool = False`.
- [ ] Tool registry grows to 6 tools.

### Tests

- [ ] `tests/test_intent_check.py` covers all unit + integration cases.
- [ ] `tests/test_mcp_server.py` extended to assert 6 tools registered.
- [ ] No live LLM calls — all `--judge-conflicts` paths mocked.
- [ ] Full suite passes (535 baseline + new tests).

### Dogfood

- [ ] SPEC-014's frontmatter declares `governs: ["src/decree/commands/intent_check.py"]` after file exists.
- [ ] PM-recorded MCP smoke test.

## What this does NOT do (deferred)

- [ ] Live LLM calls in CI.
- [ ] Symbol-level governance.
- [ ] GitHub PR bot integration — research-frontiers D.3.
- [ ] Multi-step plan parsing.
- [ ] Automatic decree.toml edits.
- [ ] Agent-loop integration.

## References

- PRD-004 R2 — what this SPEC implements.
- SPEC-009 — post-code `intent_review`; this SPEC mirrors its shape for the pre-code phase.
- SPEC-013 — calibrated abstention used here when `--with-abstention` is set.
- SPEC-011 — litellm + `_parse_llm_json` pattern reused for the LLM judge.
- research-frontiers.md C.2 — original framing.
- entire.io analysis (`docs/market-analysis/entire-io/`) — the thesis this SPEC operationalizes.
