---
id: PRD-01KWXMRR7R3S5CSAAZRGFHR5QN
status: draft
date: 2026-07-07
---

# PRD-01KWXMRR7R3S5CSAAZRGFHR5QN Typed intent-check findings

## Problem Statement

During live Agentkith dogfooding, `intent-check` collapsed three unlike things —
real conflicts, stale-governance debt, and expected multi-decision overlap — into
one undifferentiated exit-1 bucket. An agent could not tell "stop and fix" from
"note and proceed," which produces two failure modes: overreaction (stopping a
valid bugfix to chase unrelated corpus hygiene) and under-reaction (ignoring a
real blocker because exit 1 is treated as noise).

Concrete evidence (`docs/dogfooding-feedback/01-agentkith-evidence.md`):

- **Case 1/3** — a hot ViewModel governed by three complementary voice SPECs
  reported as a conflict, with no way to say "work under SPEC-X; the other two are
  contextual."
- **Case 2** — a main composition root naturally wires many domains; structural
  overlap there is not contradictory intent, but the output cannot say so.
- **Case 5** — editing a SPEC document to update its own design triggered
  `add_governance` advice, making valid corpus maintenance look ungoverned.

The goal is **not fewer warnings** — decree must stay fail-closed. The goal is
warnings an agent can act on without guessing.

## Requirements

- Every finding carries a **class** — `blocking`, `advisory`, or `corpus_hygiene`
  — distinct from any severity axis, exposed in both `--json` and the MCP tool.
- The classification is **additive**: existing `--json`/MCP consumers see the
  current fields unchanged, and exit codes are unaffected (see
  ADR-01KWXMRRB44CE78H0659D9WDY7).
- Planned files are classified as `source`, `corpus` (a decree document), or
  `generated` (a decree-produced artifact). `add_governance` is never emitted for
  a decree document editing itself.
- Human output separates "block now" from "clean later" and ends with one
  recommended next command.
- A dogfood fixture suite reproduces the five Agentkith cases so future changes
  are graded against real corpora, not toy ones.

## Success Criteria

- In the next Agentkith bugfix, an agent can proceed on advisory-only output
  after naming its active decision, while a real conflict / stale owner /
  live-session overlap still exits 1.
- Editing a decree document no longer yields an `add_governance` recommendation
  for that document.
- Existing JSON-contract tests continue to pass (the new keys are additive), and
  new fixtures cover the hot-file overlap and SPEC self-edit cases.

## Scope

In scope: the finding-class taxonomy (`CI1`), planned-file classification and
self-edit suppression (`CI3`), and the "block now / clean later" human output
(`CI6`) — backlog items `B3`, `B4`, `B6`, `B7`, plus the `B2` fixtures.

Out of scope (tracked separately in
[docs/dogfooding-feedback/06-research-backlog.md](../../../docs/dogfooding-feedback/06-research-backlog.md)):
first-class `--under` decision-relative reporting (`CI2`/`B8`), and the
governance-quality health signals — broad-governance (`CI4`) and lifecycle-drift
(`CI5`). The exit-code contract question is decided in
ADR-01KWXMRRB44CE78H0659D9WDY7.
