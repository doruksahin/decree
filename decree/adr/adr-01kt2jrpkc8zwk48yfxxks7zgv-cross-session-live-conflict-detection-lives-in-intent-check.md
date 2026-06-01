---
date: '2026-06-02'
id: ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV
references:
- PRD-01KT22NMRSXYT95XE808VD8EV4
status: accepted
---

# ADR-01KT2JRPKC8ZWK48YFXXKS7ZGV Cross-session live-conflict detection lives in intent-check

## Context and Problem Statement

`decree intent-check` (SPEC-01KT22NMS0KTWGNKB36RR7K0JR) answers a planning-phase
question: "given my plan and the files it will touch, what governance applies,
and do multiple *decisions* claim the same path?" That conflict signal is
*decision-level* — it compares planned files against the `governs:` graph.

Agent hosts that run **many concurrent coding sessions** (e.g. a canvas of
parallel Claude/Codex sessions) have a second, operational question that
decision-level conflicts cannot answer: "is another **session that is running
right now** also about to write one of my files?" Two agents editing the same
file in parallel is the dominant failure mode of multi-session development.

The question is *where* that overlap check should live. decree's identity is a
standalone decision-lifecycle tool; it deliberately does **not** track runtime
state. But the overlap computation is small, deterministic, and naturally
co-located with the governance map the host already requests at session launch.

## Decision Drivers

- decree must not become a session/process registry — it has no business
  owning runtime state, and SPEC-01KT22NMS0KTWGNKB36RR7K0JR's contract is
  pre-code planning, not orchestration.
- A parallel-agent host should get one coherent answer at launch (governance
  **and** live overlap), not stitch two tools together.
- The result must stay backward compatible: single-session and CLI callers that
  don't supply session state must see no behavioural change.
- Governance conflicts and operational overlaps are different categories and
  must not be conflated in the output schema.

## Considered Options

- **A — Extend `intent_check` with an opt-in `other_active_files` parameter.**
  The caller passes `{session_id: [paths]}` for the *other* live sessions;
  decree intersects them with `planned_files` and returns a separate
  `live_conflicts` field plus an `isolate_session` recommendation. decree
  computes the overlap but never stores it.
- **B — A separate `live-conflict` / coordination module (or a new tool).**
  Keeps intent-check purely governance-scoped; the host calls two tools and
  joins the results itself.
- **C — Reuse the governance `Conflict` shape with a `kind` discriminator,**
  packing session ids into `decision_ids`.

## Decision Outcome

Chosen option: **A**, with a strict boundary — decree *computes* the overlap
from caller-supplied state but *stores* nothing. `other_active_files` is
keyword-only and defaults to `None`, so every existing caller (and the CLI
without `--other-active-files`) is unaffected. The overlap is surfaced as a
**dedicated `LiveSessionConflict` / `live_conflicts`** field, never mixed into
the governance `conflicts` array, rejecting option C's overloading of
`decision_ids`. Option B was rejected because forcing every host to re-implement
the same intersection — and to make a second round-trip at the latency-sensitive
launch moment — adds coordination surface without removing decree's
responsibility for *defining* what a conflict is.

### Consequences

- Good: one launch-time call yields governance + live overlap; the host's job
  is reduced to maintaining a registry of each session's planned files.
- Good: the `conflicts` (governance) vs `live_conflicts` (operational) split
  keeps the two categories legible to consumers.
- Good: fully additive — `intent_check` library signature, `IntentCheckReport`,
  the `--json`/MCP schema, and the MCP tool set all grew without breaking
  existing shapes; the `intent-check` exit code now also trips on a live
  overlap, documented in the CLI help and `intent_check_run` docstring.
- Bad / accepted: decree now contains a small amount of operational
  (non-governance) logic. This is bounded to pure set intersection over
  caller-supplied data and explicitly stores no state, which keeps the
  "decree does not track sessions" invariant intact.
- Parity: the capability is exposed identically across the library function,
  the `decree intent-check --other-active-files` CLI flag, and the
  `intent_check` MCP tool's `other_active_files` parameter, so there is no
  silent CLI-vs-agent asymmetry.
