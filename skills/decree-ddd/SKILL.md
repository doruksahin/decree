---
name: decree-ddd
description: Use at the start of decree-enabled implementation work to load current project state, identify the active PRD/ADR/SPEC chain, and choose the next governed action.
---

# decree DDD

Use this skill before non-trivial work in a decree-enabled repository.

## Classify The Work Mode First

Before running `intent-check`, name one mode. The mode decides how strictly you
read findings:

- `bugfix` — may proceed past unrelated corpus-hygiene findings once the active
  decision is named and the changed behavior is tested.
- `feature slice` — proceed under the owning SPEC; add governance for new files.
- `architecture decision` — stop on contradicting decisions; record an ADR.
- `refactor` — respect existing ownership; do not silently widen `governs:`.
- `docs/corpus maintenance` — editing decree documents is expected; see below.
- `release/deploy` — no new governance; run lint + progress only.

## Required First Commands

Run from the project root:

```bash
uv run decree lint
uv run decree progress
```

If code paths will be changed, also run:

```bash
uv run decree why <path>
uv run decree intent-check --plan "Short plan" --files <path>...
```

Do not claim governance when `why`, `refs`, or `intent-check` returns no
matching decision. Write or update a SPEC first.

## Identify The Authoritative Decision

For any code change, do not stop at "these decisions govern the file." Name one:

```txt
Authoritative decision for this plan: SPEC-...
Reason: owns the behavior/invariant being changed.
Contextual decisions: SPEC-..., ADR-...   (adjacent behavior, not the target)
```

Then re-run intent-check under that decision so the report is decision-relative:

```bash
uv run decree intent-check --under SPEC-... --plan "..." --files <path>...
```

`--under` also surfaces `governs_gaps` — files your decision repeat-touches but
doesn't declare. If no authoritative decision exists, create or update one before
implementing.

## Interpreting intent-check Findings By Severity

`intent-check` exits `1` for any conflict, stale governance, or live-session
overlap, and `0` otherwise. Exit `1` mixes real blockers with contextual overlap
and corpus-hygiene debt, so **interpret the recommendations — do not blindly
resolve every finding before implementing.** Map each `action` to a bucket:

Blocking (resolve or justify before coding):

- `resolve_conflict_first` — several decisions govern a planned file. If they are
  *complementary* (e.g. a first-slice SPEC + an evolution SPEC on one hot file),
  name the authoritative decision, pass `--under`, and treat the rest as
  contextual. Only truly stop if a contextual decision's acceptance criteria
  *contradict* your plan.
- `isolate_session` — another live session plans the same file. A real blocker:
  run in a dedicated worktree or split the file out of one plan.
- `update_decision` — a stale governing decision. Blocking only if that decision
  *owns the behavior you are changing*; if it merely shares a hot file, record it
  as corpus hygiene and proceed under your active decision.

Advisory (proceed; note it, clean later):

- `update_spec_first` — a governing SPEC has unchecked acceptance criteria.
- `add_governance` — a planned source file has no governing decision. Blocking
  for new source under an unclear decision; advisory once the active decision is
  named and will declare the path.
- `draft_adr_first` — architectural plan with no governance yet.
- `check_ac` — informational; an unchecked acceptance criterion.

Corpus maintenance (not a code-governance gap):

- The planned file is a decree document (its own SPEC/ADR/PRD markdown). Editing
  a decision document to update its design or `governs:` list is authoring truth,
  **not** missing governance — do not act on `add_governance` for it. Run
  `decree lint` and, after `governs:`/frontmatter edits, `decree index rebuild`.

If you proceed past an advisory or corpus finding, say so and why.

## Document Creation Rules

- New documents require a bucket:

  ```bash
  uv run decree new prd "Feature Name" --bucket area/feature
  uv run decree new adr "Decision Name" --bucket area/feature
  uv run decree new spec "Implementation Name" --bucket area/feature
  ```

- If sprint mode is enabled, new SPECs enter the active sprint by default.
  Membership is one `decree/sprints/live/<DOC-ID>.yaml` file per document
  (state in `decree/sprints/state.yaml`), so parallel worktrees enroll new
  SPECs without merge conflicts.
- Use `--backlog --reason "..."` or `--draft-pool --reason "..."` only when the
  work should explicitly stay out of the active sprint.
- Keep PRD -> ADR -> SPEC references in frontmatter. Keep implementation file
  ownership in `governs:`.

## Cross-Layer Boundary Preflight

Before editing across layers (renderer + main, domain + composition root),
answer this preflight so the fix lands on the owning contract, not the nearest
file:

```txt
User goal:
Current surface:
Domain owner:
Operation owner:
Existing seam to extend:
New dependency:
Why this is not nearest-file bloat:
Allowed files:
Forbidden files:
Verification:
```

## When Live Work Reveals A Missing Detail

- If the current SPEC is correct but incomplete, update the SPEC before code.
- If the SPEC is wrong, pause for PRD/ADR/SPEC clarification.
- If the SPEC is too broad (governs many files it doesn't truly own), record the
  broad-governance pain instead of widening it silently.

## Work Loop

1. Classify the work mode and load state with `decree lint` and `decree progress`.
2. Read the active SPEC and list unchecked acceptance criteria.
3. Run `decree why` for planned files, name the authoritative decision, then
   `decree intent-check --under <decision> --plan "..." --files ...`.
4. Interpret findings by severity (above). Resolve or justify blockers.
5. Make the smallest coherent implementation.
6. Check off acceptance criteria only when the behavior is implemented and
   tested.
7. Run targeted tests.
8. Run `decree lint` and `decree progress` again.
9. When a SPEC's primary acceptance criteria reach 100% mid-sprint, record the
   completed outcome, then transition the document status:

   ```bash
   uv run decree sprint complete SPEC-...
   uv run decree status SPEC-... implement   # from approved; run submit/approve first if still draft
   ```

   Completed and dropped items leave the default `decree progress` scope; use
   `--sprint <SPRINT-ID>` to include them.
10. For sprint review, generate the local board:

    ```bash
    uv run decree generate-html --output decree-board.html
    ```

## Final Report

When decree was used, end the session with a short decree section so the work is
auditable:

```txt
Decree:
- Active decision: SPEC-...
- Findings: blocking / advisory / corpus hygiene (which were present)
- Governance changes: yes/no
- Known residual drift: ...
```

## Status Guidance

- PRD captures user value and requirements.
- ADR captures the architectural decision.
- SPEC captures technical design, tests, acceptance criteria, and `governs:`.
- Implementation commits should use `decree commit` with the appropriate
  `Implements:` trailer when the change actually implements a SPEC.

## Fail-Closed Rules

- Do not hide lint, progress, or intent-check findings.
- Interpret exit-1 findings by severity; do not treat every finding as a blocker,
  and do not suppress a real blocker (conflict / stale owner / live overlap).
- Do not mutate generated indexes from query commands.
- Do not silently install hooks. Use explicit install commands for hooks.
- Do not use LLM provider calls from core decree; agent skills own model calls.
