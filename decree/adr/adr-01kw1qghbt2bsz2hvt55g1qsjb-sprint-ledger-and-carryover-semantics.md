---
id: ADR-01KW1QGHBT2BSZ2HVT55G1QSJB
status: proposed
date: 2026-06-26
references:
- PRD-01KW1QEZEC1R1BSTZN1SSPPCEJ
---

# ADR-01KW1QGHBT2BSZ2HVT55G1QSJB Sprint Ledger and Carryover Semantics

## Context and Problem Statement

Decree needs sprint-scoped execution tracking without weakening the existing
decision lifecycle model. PRDs describe product intent, ADRs record decisions,
SPECs define implementation blueprints, and `governs:` links decisions to code.
Sprints are different: they are time-bounded execution windows with outcomes
such as completed, carried over, deferred, or dropped.

If sprint membership is stored directly on PRD/ADR/SPEC documents, the same
fields can start to mean both "what decision explains this work" and "which
timebox currently owns this task". That creates drift: a PRD opened in Sprint 1
could incorrectly constrain new SPECs in Sprint 2, and old sprint filters could
hide still-valid governance decisions.

The system needs a model that preserves sprint history as execution evidence
while leaving document references and governance lookup corpus-wide.

## Decision Drivers

- Sprint history must be auditable after the underlying SPEC changes later.
- Governance commands must not be affected by sprint filters.
- PRD product intent must be allowed to span multiple sprints.
- The same executable SPEC must not silently move between sprints.
- Carryover must be explicit, reasoned, and linearly linked.
- Completion must be proven by close-time evidence rather than asserted under
  rollover pressure.
- Backlog must remain reviewable instead of becoming a silent holding area.
- Natural no-sprint periods must be represented without inventing fake active
  sprints.
- Existing repositories must not be forced into fake sprint history before
  sprint mode is initialized.

## Considered Options

- Store `sprint:` fields directly in PRD/ADR/SPEC frontmatter.
- Store sprint membership and outcomes in a dedicated sprint ledger or sprint
  document, with references to PRD/ADR/SPEC IDs.
- Infer sprint membership from git commits, branches, or commit trailers.

## Decision Outcome

Chosen option: "dedicated sprint ledger or sprint document", because sprint
membership is execution state rather than decision state.

The ledger is the source of truth for active sprint identity, item membership,
backlog membership, item outcomes, carryover links, and closed-sprint snapshots.
PRD/ADR/SPEC frontmatter remains the source of truth for decision identity,
status, references, and code governance. Task-facing commands can default to the
active sprint by reading the ledger, while governance-facing commands continue
to read the whole corpus.

The ledger has explicit operating modes. In active mode it has exactly one
active sprint. In paused mode it has no active sprint and records `since` plus a
human-readable reason. Paused mode is the sanctioned representation for freezes,
maintenance windows, or other periods where creating a fake sprint would distort
history.

The default executable sprint item is a SPEC. PRDs and ADRs may be shown as
context for active SPECs, and may be explicitly tracked as planning items when
the work is to author or review those documents, but they do not count as
implementation progress by default.

The same PRD can have SPECs in multiple sprints. The same SPEC can appear in
multiple sprints only as a linear carryover chain with a required reason. Closed
sprints keep snapshot outcomes; their historical result is not recomputed from
live SPEC status. A `completed` outcome is valid only when the snapshot proves
primary acceptance criteria were 100% complete at close time. Other terminal
outcomes such as carried over, deferred, dropped, or superseded require an
explicit reason.

Backlog entries are ledger records with `since`, `source`, and `reason` fields.
Age-based backlog findings are lint warnings or health findings, not silent
success, so unresolved work remains visible even when it is intentionally
outside the active sprint.

Task-facing output must separate executable tasks, planning items, and referenced
context. Context can explain why a SPEC exists, but it must not be visually or
numerically mixed into sprint task progress.

Git-derived detection of closed-sprint mutation is advisory only. Command-level
immutability and lint self-consistency checks are the primary safety mechanism.
