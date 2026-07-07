---
id: ADR-01KWY7ENVMMAMS4HSBJ4C6XN4T
status: accepted
date: 2026-07-07
references:
- PRD-01KWXMRR7R3S5CSAAZRGFHR5QN
---

# ADR-01KWY7ENVMMAMS4HSBJ4C6XN4T Defer intent-check baseline axis and AC-snapshot drift signal

## Context and Problem Statement

The Agentkith research backlog
([docs/dogfooding-feedback/06-research-backlog.md](../../../docs/dogfooding-feedback/06-research-backlog.md))
proposed two items that the rest of the workstream did not ship:

- **B15** — a "new vs pre-existing" finding axis for `intent-check` (SARIF
  `baselineState` / Semgrep-diff style), computed by a two-run set-difference so a
  newly-introduced conflict is distinguished from pre-existing debt.
- **B13** — a lifecycle-drift signal for a terminal decision whose acceptance
  criteria changed after its completion report was generated, which needs an
  AC-granular snapshot to detect.

The question is whether to build them now or defer them, and — because "leave no
debt" is the instruction — to make that a recorded decision rather than a silent
gap.

## Decision Drivers

- **Evidence.** The five concrete Agentkith cases motivate typed findings (B3),
  planned-file classification (B6), `--under` framing (B8), directory overlap
  (B12), and the shipped health signals (B9/B10/B11). None of them is a B13 or
  B15 pain; both are research-inferred, not observed.
- **The core pain is already addressed.** B3's finding classes
  (`blocking` / `advisory` / `corpus_hygiene`) plus B12's advisory
  `directory_overlaps` already separate "real blocker" from "expected overlap",
  which is what B15's baseline axis was meant to help with.
- **Diff-scoping already exists.** `decree progress --changed --base <ref>`
  provides change-scoped analysis today; a second, intent-check-specific baseline
  mechanism would duplicate it.
- **Cost and risk.** B13's robust form needs an AC-content-hash stamped into the
  completion report at generation time (a new mechanism); the cheap git-timestamp
  proxy is fragile and would break `health`'s pure-index invariant. B15 needs a
  new two-run/baseline mode for `intent-check` with unsettled design. Building
  either speculatively risks a wrong, load-bearing abstraction.

## Considered Options

- **Option A — build both now.** Adds surface and a fragile heuristic (B13) or a
  contested mode (B15) with no observed demand.
- **Option B — defer both, record concrete re-triggers.** No speculative surface;
  the shipped classes cover today's need; revisit on real evidence.
- **Option C — build B13 only** via git-timestamp. Ships a known-fragile signal
  that overlaps `stale_decisions` and the B9 terminal-governance signal.

## Decision Outcome

Chosen option: **Option B** — defer B13 and B15 and record the re-triggers, so
this is a closed decision rather than lingering debt.

Re-trigger B15 when a live session shows a *newly introduced* conflict that the
B3 finding classes and B12 `directory_overlaps` did not let the agent distinguish
from pre-existing debt. Re-trigger B13 when a terminal decision is observed whose
acceptance criteria silently drifted after its completion report; build it then
by stamping an AC-content-hash into the report at generation time (keeping
`health` pure-index), not by diffing the working tree.

Option A/C are rejected: they add unowned surface or a fragile signal ahead of
evidence, which is the debt this decision avoids.
