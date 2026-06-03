---
id: ADR-01KT7E7RD6NYASNDWVE0PQ7J8G
status: accepted
date: 2026-06-03
---

# ADR-01KT7E7RD6NYASNDWVE0PQ7J8G Commit-check as a CI coverage gate, not a commit-msg guarantee

## Context and Problem Statement

decree's provenance is two-layered (see `docs/provenance-model.md`). git **guarantees**
which files a commit changed; the commit→**decision** link is the
`Implements:/Refs:/Fixes:` **trailer convention** — unenforced free text. When a change
to a governed file is committed without a trailer, the implementation is "invisible —
never linked to any decision," permanently, and every git-derived signal degrades. This
is decree's named weak link. The question: should decree add commit-time enforcement to
strengthen it, and in what shape?

## Decision Drivers

- Strengthen the weak link without overclaiming (decree's brand is honesty).
- Must survive how real teams merge — squash-merge collapses per-commit messages.
- Must not false-positive its way to being disabled (incidental edits, prefix governance).
- Must not pollute the authoritative read layer (`why`/`intent-check` read declared `governs:` only).
- Stay deterministic; no LLM; no new schema; additive and opt-in.
- Decisions and tickets are orthogonal — decree must not read or map ticket IDs.

## Considered Options

- **A. Local `commit-msg` hard block** — reject any commit touching a governed path without a trailer.
- **B. CI net-diff coverage gate** — a deterministic check on the PR's net diff, advisory by default with opt-in `--strict`/`--min-coverage`.
- **C. Advisory only** — add a coverage number to `intent-review`'s output, no gate.
- **D. Do nothing** — `decree commit` (writes trailers) + `decree health` (catches the aftermath) are enough.

## Decision Outcome

Chosen option: **B — a CI net-diff coverage gate (`decree commit-check`)**, because it is
the only option that strengthens the link *and* survives squash-merge *and* stays honest.

- **Not A:** a `commit-msg` block fires on every local/WIP commit, the trailers it forces
  are then destroyed by squash-merge, and it false-positives on incidental edits and
  directory-prefix governance — the "disabled on day two" failure. It is also bypassable
  by `--no-verify`, so calling it a "guarantee" would overclaim — the exact failure decree
  exists to prevent. The local git-hook *installer* is deferred to a harness/skill (a
  separate decision); core ships only a documented opt-in snippet.
- **Not C alone:** the genuinely missing thing is a discrete, gateable coverage scalar; a
  number buried in `intent-review` JSON is not gateable on its own. B subsumes C.
- **Not D:** `decree commit` is opt-in convenience and `health` is post-hoc/aggregate;
  neither enforces the link at the one moment it is knowable (the change under review).

`commit-check` reads **only the declared `governs:` layer** via `why()`, accepts
`Implements:`/`Refs:`/`Fixes:`, scopes to **in-flight** decisions, writes nothing, runs no
model. It is **advisory by default** (exit 0 + report); `--strict`/`--min-coverage` make
uncovered changes exit 1 for CI, and `--min-coverage` enables ratcheting adoption on
legacy repos with no flag day. It is described honestly as **"trailer coverage you can
gate," never a guarantee** — `--no-verify` and CI overrides exist; it measures and gates
where it runs, it cannot make the link true.

### Consequences

- Good: closes the weak link with an honest, gateable signal; purely additive; squash-safe.
- Bad/limits: not a guarantee (bypassable); local enforcement is the harness's job, not core's.
- Implemented by [SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J](../spec/spec-01kt7e7sq7qvxzyk2q0y37qd3j-trailer-coverage-gate-via-decree-commit-check.md).
