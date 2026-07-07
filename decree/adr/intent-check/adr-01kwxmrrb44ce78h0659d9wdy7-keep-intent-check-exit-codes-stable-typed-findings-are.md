---
date: '2026-07-07'
id: ADR-01KWXMRRB44CE78H0659D9WDY7
references:
- PRD-01KWXMRR7R3S5CSAAZRGFHR5QN
status: accepted
---

# ADR-01KWXMRRB44CE78H0659D9WDY7 Keep intent-check exit codes stable, typed findings are additive

## Context and Problem Statement

PRD-01KWXMRR7R3S5CSAAZRGFHR5QN requires `intent-check` to classify every finding
as `blocking`, `advisory`, or `corpus_hygiene`. Today `intent-check` exits `1`
whenever a conflict, stale-governance entry, or live-session overlap is present,
and `0` otherwise (`src/decree/commands/intent_check.py`, the `has_blockers`
gate); `governs_gaps` are already advisory and never affect the exit code.

The new taxonomy reclassifies some findings that currently contribute to exit 1 —
for example a *stale contextual* decision that merely shares a hot file becomes
`corpus_hygiene`. The question: **should the finding class change what flips the
exit code, or is the class purely an additive, informational index over the same
exit contract?** This decision gates the whole P2 output-shape work, because it
determines whether the change is additive or a contract break.

## Decision Drivers

- Decree's core promise is fail-closed governance; a change must not silently let
  a run that used to gate CI start passing.
- The `--json` shape is additive-by-policy (`docs/json-contracts.md`); the
  exit-code behavior is a reverse-engineered contract that CI pipelines already
  depend on.
- Agents need to *proceed on advisory-only findings* without the tool
  misrepresenting its exit status.
- The agent-loop guidance (skill `decree-ddd`) already teaches interpreting exit-1
  findings by severity, so the "proceed on advisory" behavior can live in the
  agent without changing decree's exit contract.

## Considered Options

### Option A — Typed classes are additive; exit-code logic is byte-identical

Add `blocking_findings` / `advisory_findings` / `corpus_hygiene_findings` as new
keys, but leave the `has_blockers` gate unchanged (exit 1 ⇔ conflict ∨ stale ∨
live). Agents read the buckets and decide whether to proceed; decree never relaxes
its own exit. Mirrors SARIF, which puts a finding *kind* on every result
independent of the failure *level*.

- Good: strictly additive; zero consumer breakage; fail-closed preserved.
- Good: the "proceed on advisory" decision is explicit and auditable in the agent.
- Bad: agents that only check the exit code (not the buckets) gain nothing until
  they adopt the new fields.

### Option B — Exit code keys on `blocking_findings` only

Recompute the exit from the new `blocking` bucket, so a stale-only or
contextual-overlap-only run flips 1 → 0.

- Good: a single exit code encodes "should I stop"; simplest agent loop.
- Bad: silently breaks the exit contract — a stale-only corpus that used to gate
  CI now passes. This is exactly the fail-open regression the drivers forbid.

### Option C — New opt-in `--severity-gate` flag, default off

Keep the default exit contract; add a flag that relaxes the exit for
advisory-only findings when explicitly requested.

- Good: default contract intact; power users opt in.
- Bad: added surface for a need not yet demonstrated; premature.

## Decision Outcome

Chosen option: **Option A** — ship the typed finding classes as additive `--json`
+ MCP keys and hold the exit-code logic byte-identical. Exit relaxation stays
agent-side: the `decree-ddd` skill reads the buckets and justifies proceeding on
advisory/corpus findings, so decree stays fail-closed and its exit contract is
untouched. Land a regression test asserting a stale-only corpus still exits 1
after the buckets exist (backlog `B5`). Option C remains available later as a
non-breaking opt-in if a real need appears; Option B is rejected because it
converts an additive change into a fail-open contract break.
