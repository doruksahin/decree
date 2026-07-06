# Skill And Usage Improvements

Some fixes belong in decree core. Others belong in the portable skills and
recommended agent loop.

## Current Skill Risk

The typical loop is:

```txt
decree lint
decree progress
decree why <path>
decree intent-check --plan ... --files ...
resolve conflicts/stale findings before implementing
```

This is too blunt for live development. It treats all exit-1 findings as equal,
but current `intent-check` reports mixed-severity findings.

## Recommended Agent Loop

### 1. Classify The Work Mode

Before `intent-check`, the agent should name one mode:

```txt
bugfix
feature slice
architecture decision
refactor
docs/corpus maintenance
release/deploy
```

Mode affects how findings are interpreted. A bugfix can proceed past unrelated
corpus hygiene if the active decision is clear and the changed behavior is
tested. An architecture decision should stop on unresolved conflicting
decisions.

### 2. Identify The Authoritative Decision

For code changes, the skill should not stop at "these decisions govern the
file." It should force a sentence:

```txt
Authoritative decision for this plan: SPEC-...
Reason: owns the behavior/invariant being changed.
Contextual decisions: SPEC-..., ADR-...
```

Then run:

```bash
decree intent-check --under SPEC-... --plan "..." --files ...
```

If no authoritative decision exists, create or update one before implementation.

### 3. Interpret Findings By Severity

Until core decree emits typed severity, skills should apply this guidance:

Blocking:

- no governing decision for source code and no active decision selected
- active decision contradicts the planned behavior
- live-session overlap on the same file
- unchecked acceptance criteria directly relevant to the planned behavior

Advisory:

- contextual multi-SPEC overlap on a hot file
- stale decision that shares the file but does not own the changed behavior
- broad governs warnings

Corpus maintenance:

- the edited file is a decree document
- index needs rebuild after `governs:` changes
- draft 100% status drift

The final answer should state which bucket was present.

### 4. Record Boundary Preflight For Cross-Layer Work

For cross-layer implementation, skills should require a short boundary
preflight before code edits:

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

This is what prevented the Agentkith toolbar dictation bug from becoming a
local UI patch.

### 5. Use Decree To Update The SPEC, Not Just To Query It

When live work reveals a missing technical detail, the skill should instruct:

```txt
If the current SPEC is correct but incomplete, update the SPEC before code.
If the SPEC is wrong, pause for PRD/ADR/SPEC clarification.
If the SPEC is too broad, record the broad-governance pain instead of widening
it silently.
```

The toolbar dictation fix needed the voice SPEC to declare that pop-out
activity aggregate carries a first dictation target.

### 6. Final Report Contract

Agent final responses should include a small decree section when decree was
used:

```txt
Decree:
- Active decision: SPEC-...
- Findings: blocking/advisory/corpus hygiene
- Governance changes: yes/no
- Known residual drift: ...
```

This makes it possible to audit whether agents are using decree as a decision
tool or just running commands mechanically.

## Skill Changes To Consider

- Update `decree-ddd` to always prefer `intent-check --under` once an active
  decision is named.
- Add a "bugfix mode" interpretation guide to the skill.
- Add a "do not add governance for decree document self-edits" rule until core
  decree classifies corpus files itself.
- Add examples from Agentkith hot-file overlap and shared-contract expansion.
- Require agents to say when they proceed despite advisory findings.

