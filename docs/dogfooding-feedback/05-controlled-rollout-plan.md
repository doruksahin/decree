# Controlled Rollout Plan

The changes should be made in small slices. The goal is to improve signal
without weakening decree's fail-closed behavior.

## Phase 1: Documentation And Skill Guidance

Scope:

- Add this dogfooding pack.
- Update portable skills to require an authoritative decision and prefer
  `intent-check --under`.
- Add guidance for interpreting exit-1 findings during bugfix work.

Validation:

- No command behavior changes.
- Link check and docs review.
- Re-run the Agentkith toolbar dictation scenario manually against the updated
  skill guidance.

## Phase 2: Intent-Check Output Shape

Scope:

- Add finding categories to JSON and human output.
- Separate source changes, corpus changes, and generated artifacts.
- Keep existing exit codes stable.

Candidate JSON fields:

```json
{
  "blocking_findings": [],
  "advisory_findings": [],
  "corpus_hygiene_findings": []
}
```

Validation:

- Existing JSON contract tests continue to pass or gain versioned additions.
- New fixtures cover Agentkith hot-file overlap and SPEC self-edit behavior.
- Human output clearly separates "block now" from "clean later."

## Phase 3: Active Decision Semantics

Scope:

- Make `--under` the center of the report when provided.
- Reclassify multi-governed files relative to the active decision.
- Keep structural overlap visible, but do not label every overlap as a conflict.

Validation:

- Agentkith `OrchestratorCockpitViewModel.ts` style fixture:
  one active voice SPEC, one contextual voice SPEC, one implemented model
  controls SPEC.
- Output should say contextual overlap unless a contradiction fixture exists.

## Phase 4: Health Signals For Governance Quality

Scope:

- Add broad-governance advisory signal.
- Add lifecycle drift signal for 100% draft documents and terminal-status
  report drift.

Validation:

- Fixture with SPEC governing 60+ paths.
- Fixture with draft SPEC at 100% primary criteria.
- Findings remain advisory unless configured otherwise.

## Phase 5: Corpus Hygiene Commands

Scope:

- Add explicit remediation helpers if phases 2-4 prove the findings useful.

Possible commands:

```bash
decree health --broad-governs
decree status suggest
decree governs audit --decision SPEC-...
```

Do not add write commands until the read-side signal is trusted.

## Success Criteria

Decree is more useful if, in the next Agentkith live bugfix:

- the agent can name the active decision before editing
- `intent-check` output separates current blockers from corpus hygiene
- valid SPEC maintenance does not produce misleading add-governance advice
- hot-file overlap is visible but not automatically treated as contradiction
- final reports can explain why decree changed the implementation path

