# Pain Points

The pain points below are grouped by failure mode. Each one should map either
to a command behavior change, a skill guidance change, or a corpus hygiene
practice.

## 1. Structural Conflict Is Too Coarse

Current behavior:

```txt
If multiple decisions govern a planned file, intent-check reports a conflict.
```

Problem:

```txt
Shared ViewModels, main composition roots, and cross-layer contracts naturally
belong to more than one decision over time. The overlap is often contextual,
not contradictory.
```

Needed distinction:

- real conflict: two decisions require incompatible behavior
- contextual overlap: one decision owns the current change, others explain
  adjacent behavior
- composition overlap: a root file wires many domains and should not be treated
  the same as a domain file

## 2. `governs:` Blurs Ownership And Touch History

Current behavior:

```txt
Large feature SPECs often list every file touched by the implementation.
```

Problem:

```txt
When a SPEC governs 60+ files, `why` still works, but ownership signal weakens.
```

Symptoms:

- hot files accumulate many governing decisions
- intent-check reports expected overlap as conflicts
- agents amend the nearest active SPEC instead of asking which decision truly
  owns the invariant

## 3. Stale Governance Is Not Ranked By Relevance

Current behavior:

```txt
intent-check exits 1 for stale governance intersecting planned files.
```

Problem:

```txt
Some stale findings are real blockers. Others are corpus hygiene debt unrelated
to the current bugfix.
```

Needed distinction:

- stale active decision that owns the planned behavior
- stale contextual decision sharing a hot file
- stale terminal/implemented decision that should be excluded from active
  planning conflict unless the planned behavior contradicts it

## 4. Status And Progress Drift Dilutes Trust

Current behavior:

```txt
Progress can show 100% primary criteria while status remains draft.
```

Problem:

```txt
Agents use status to infer whether a decision is proposed, accepted, or shipped.
When many completed documents remain draft, the lifecycle signal becomes weak.
```

The tool already has status commands. The missing piece is higher-pressure
guidance and sharper health surfacing for "100% draft for too long".

## 5. Decision Document Edits Look Ungoverned

Current behavior:

```txt
If a planned file is a decree document and no decision governs that markdown
path, intent-check can recommend add_governance.
```

Problem:

```txt
Decision documents are authoring truth. Editing a SPEC to update its design or
governs list is not the same thing as editing application code without
governance.
```

Needed distinction:

- code/source planned file
- decree corpus planned file
- generated decree artifact

## 6. `--under` Is Too Optional In Agent Workflows

Current behavior:

```txt
The docs mention --under, but many skill workflows still run intent-check with
only --plan and --files.
```

Problem:

```txt
Without --under, intent-check cannot distinguish "my active decision lacks this
path" from "some decision somewhere overlaps this path."
```

`--under` should become the default once an agent has identified an
authoritative decision.

## 7. The Agent Skill Loop Overreacts To Exit 1

Current behavior:

```txt
Skills often say to resolve conflicts/stale findings before implementation.
```

Problem:

```txt
Exit 1 currently includes real blockers, useful warnings, and known corpus
hygiene debt. A blanket "resolve first" instruction can stop valid bugfix work
or push agents into unrelated cleanup.
```

The agent loop should require interpretation, not blind obedience.

