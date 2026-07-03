---
name: decree-ddd
description: Use at the start of decree-enabled implementation work to load current project state, identify the active PRD/ADR/SPEC chain, and choose the next governed action.
---

# decree DDD

Use this skill before non-trivial work in a decree-enabled repository.

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

## Work Loop

1. Load current state with `decree lint` and `decree progress`.
2. Read the active SPEC and list unchecked acceptance criteria.
3. Run `decree why` and `decree intent-check` for planned files.
4. Make the smallest coherent implementation.
5. Check off acceptance criteria only when the behavior is implemented and
   tested.
6. Run targeted tests.
7. Run `decree lint` and `decree progress` again.
8. When a SPEC's primary acceptance criteria reach 100% mid-sprint, record the
   completed outcome, then transition the document status:

   ```bash
   uv run decree sprint complete SPEC-...
   uv run decree status SPEC-... implement   # from approved; run submit/approve first if still draft
   ```

   Completed and dropped items leave the default `decree progress` scope; use
   `--sprint <SPRINT-ID>` to include them.
9. For sprint review, generate the local board:

   ```bash
   uv run decree generate-html --output decree-board.html
   ```

## Status Guidance

- PRD captures user value and requirements.
- ADR captures the architectural decision.
- SPEC captures technical design, tests, acceptance criteria, and `governs:`.
- Implementation commits should use `decree commit` with the appropriate
  `Implements:` trailer when the change actually implements a SPEC.

## Fail-Closed Rules

- Do not hide lint, progress, or intent-check findings.
- Do not mutate generated indexes from query commands.
- Do not silently install hooks. Use explicit install commands for hooks.
- Do not use LLM provider calls from core decree; agent skills own model calls.
