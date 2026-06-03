---
date: '2026-06-03'
governs:
- src/decree/commands/intent_check.py
- src/decree/commands/intent_review.py
id: SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D
- SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ
- SPEC-01KT22NMS0KTWGNKB36RR7K0JR
- SPEC-01KT22NMRYRZQ59EC88VJ5R0N6
status: implemented
---

# SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5 Point-of-change governs-gap suggestions in intent-check and intent-review

## Overview

v1 (dead-governance, SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D) and v2 (missing-governance,
SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ) **detect** governance drift. The roadmap's
remediation phase was "feed v2's candidates into `decree migrate governs` and
auto-`--write` the `governs:` frontmatter." A maintainer value-review rejected
that shape: the existing `--apply-suggestions` writer **refuses documents that
already declare `governs:`** — which is *every* missing-governance target — so
"no second writer" contradicts "extend existing governs"; directory roll-up
**manufactures dead-governance**; and writing the **authoritative** `governs:`
layer from an **advisory, lower-precision, sparse** signal is the exact promotion
the provenance model forbids ([docs/provenance-model.md](../../docs/provenance-model.md)).

This SPEC is the review's recommended redesign: surface the governs gap **at the
moment of change**, scoped to the **active decision** a governed session already
works under, inside `intent-check` (pre-code) and `intent-review` (post-code).
When the agent's planned/changed files include a path the active decision's own
trailer-linked commits have **repeat-touched** but the decision does **not**
declare, the report says *"you keep working on this file under DECISION but it
isn't in its `governs:` — consider adding it."*

### Why this beats batch v2 — context, not a lower bar

The naive idea ("the current edit is the +1, so accept `commit_count == 1`") is a
*rhetorical* +1, not a computed one: a single squash commit carrying
`Implements: D` sweeps 100 files at `commit_count == 1`, and a file brushed
incidentally by that squash is not owned by `D` just because the agent now edits
it. So this signal keeps v2's **squash-immune `commit_count >= 2` gate** (a squash
contributes only one commit).

The genuine win over batch v2 is **not** a lower threshold — it is that a *known*
`under` lets us **drop the cross-decision precision controls v2 needs precisely
because it does not know the active decision**:

- v2 drops paths **owned by any other decision** (to avoid guessing an owner) and
  paths **repeat-touched by ≥3 decisions** (shared-infra floor). Under a known
  `D`, neither applies: if `D`'s own commits repeat-touch a path and `D` does not
  declare it, that is a real gap **for `D`** even if other decisions also touch or
  govern it — the session has already declared which decision owns the current
  work.

That is why the point-of-change surface extracts signal the batch surface
suppresses (validated on decree below), while staying squash-immune. It also
surfaces to the agent **with the most context, at the cheapest moment to act**,
and **never writes the authoritative layer** — the agent makes the deliberate
`governs:` edit, the only legitimate advisory→authoritative promotion. It closes
the agentkith governed-session loop: governed session → known decision → drift
surfaced at edit time → agent declares it.

No new command, no new writer, no roll-up, no LLM — one advisory field and one
soft recommendation on the two existing intent reports, a pure index read.

## Technical Design

### The active-decision input

`intent_check(...)` and `intent_review(...)` gain an optional `under: str | None`
— the id of the decision the caller works under. Surfaced as CLI `--under
SPEC-...` on both commands and as an `under` parameter on the MCP
`intent_check` / `intent_review` tools (appended after existing params; positional
callers unaffected). A governed session passes the decision it owns; absent it the
gap check is **skipped** (empty), so existing callers are unchanged.

**Existence is validated, not assumed.** `require_doc_id` checks *format* only, so
the implementation probes existence with `SELECT 1 FROM decisions WHERE id = ?`
(the pattern `refs()` / `commit.py` already use). An `under` that is malformed or
not in the corpus populates a report field `under_error: str | None` and sets the
**CLI exit code to 2** (the config-error class `intent-check` already uses for bad
`--other-active-files` JSON; `intent-review` gains an exit-2 path — a small,
documented contract addition). This is distinct from `governs_gaps`, which never
changes the exit code.

### The governs-gap computation

Given a valid active decision `D` and the report's path set `F` (`planned_files`
for intent-check; the **added/modified** changed paths for intent-review — see
below), a path `P` in `F` is a **governs gap** iff:

1. **Repeat-touched by `D` (squash-immune).** `P` has `commit_count >= 2` in
   `observed_governs` for `D`. (`D`'s own document is never a candidate — corpus
   docs are excluded from `observed_governs` at index time by `_observable_path`.)
2. **Not declared by `D`.** No file-grained declared `governs:` entry of `D`
   covers `P`, computed as `any(_path_covers(declared_entry, P) for declared_entry
   in declared_of_D)` — note the **argument order**: `_path_covers(declared,
   observed)`. Symbol-scoped entries (`path#symbol`) are excluded from
   `declared_of_D` exactly as `_declared_and_linked` does (a file observation
   cannot cover a symbol), so a decision that declares only `src/foo.py#Sym` and
   whose commits repeat-touch `src/foo.py` *does* surface the file.
3. **Not structural noise.** `_is_structural_noise(P)` is false (tests, changelog,
   documentation `.md`/`.rst`).

Deliberately **no** owned-elsewhere filter and **no** shared-infra floor (those are
v2's substitutes for a known decision). Pure index read of `observed_governs` +
`governs` — no git shellout, no working-tree access.

`_path_covers` and `_is_structural_noise` are reused by importing from
`commands/health.py` (`intent_check`/`intent_review` already import `health`; the
edge is one-way, no circular import). They are module-private; the cross-module
coupling is held by the gap tests, which import them transitively through
`compute_governs_gaps`, so a health.py rename breaks the tests rather than
drifting silently. (A later cleanup may promote the two pure predicates to a
shared module; out of scope here.)

### intent-review: added/modified paths only (no deletions, no tree read)

intent-review's gap candidates are the diff's **added/modified** paths. In the
`--diff` / `--diff-base` modes `parse_diff` already strips deletions, so this is
free. In the default `--name-only` mode the diff carries no +/- structure and a
staged **deletion** would otherwise appear — proposing "declare the file you just
deleted." Since distinguishing a deletion without diff structure would require a
working-tree read (forbidden), the gap check in intent-review **runs only when the
diff source carries add/delete structure**; in the structureless name-only default
it is skipped (documented asymmetry, surfaced as an empty `governs_gaps` with a
note, not a silent drop). intent-check has no deletions (planned files are
forward-looking), so it has no such restriction.

### Output

Each report gains:

- `under_decision: str | None` and `under_error: str | None`.
- `governs_gaps: tuple[GovernsGap, ...]` — `GovernsGap(path, commit_count)`,
  sorted `(commit_count desc, path asc)`. `commit_count` (same name as v2's
  candidate field) is the honesty signal: how many of `D`'s commits touched it.
- A **soft** `declare_governs` recommendation (carrying the gap paths) when
  `governs_gaps` is non-empty.

### Advisory, never authoritative

- **`declare_governs` is excluded from the `proceed` guard and from the
  exit-code/`has_blockers` tuple** in both commands (intent-check exit keys off
  conflicts/stale/live; intent-review off conflicts/stale). Gaps never gate
  `proceed` and never change the exit code. (Only an invalid `under` → exit 2.)
- **Never feeds `why()` / `refs`.** `observed_governs` is read here to *suggest*,
  never to answer a governance query; `why()` still answers only from declared
  `governs:`. Promotion happens only if the agent edits the frontmatter.
- **Stale-tolerant, deterministic.** Reads the index as-is; no rebuild triggered.

### agentkith integration (consumer, out of scope here)

The governed session passes the decision it owns via `--under` / the MCP `under`
parameter; the existing "Start governed session → run intent-check" path then
returns `governs_gaps`. Wiring the session to pass `under` is an agentkith change
tracked separately.

## Testing Strategy

`pytest` over temp-git fixtures (the `tests/test_missing_governance.py` helper
style). Cover:

- **Gap surfaced.** `D` has ≥2 commits touching `src/foo.py`, does not declare it;
  `intent_check(under=D, files=["src/foo.py"])` and `intent_review` return it in
  `governs_gaps` (`commit_count >= 2`) with a `declare_governs` recommendation.
- **Squash-immune.** `D`'s single commit touched many files (`commit_count == 1`);
  none surface.
- **Declared excluded — including a directory entry.** `D` declares `src/auth/`
  (slash) and `src/cache.py`; an observed `src/auth/tokens.py` and `src/cache.py`
  never surface (guards the `_path_covers` direction). Slashless `src/auth` too.
- **Symbol entry.** `D` declares `src/foo.py#Sym`; observed `src/foo.py` surfaces.
- **Not-observed excluded.** A planned/changed path `D` never touched is not a gap.
- **Structural excluded.** A doc/test path `D` repeat-touched is not a gap.
- **No `under`.** Empty `governs_gaps`, report and exit identical to baseline.
- **Unknown `under`.** Malformed or absent id → `under_error` set, **exit 2**.
- **Advisory.** A report whose only signal is a gap exits unchanged from the
  no-`under` baseline and does not gate `proceed`.
- **intent-review deletions.** A staged deletion of a `D`-observed path does not
  surface (structured diff); name-only mode skips the gap check.
- **Never feeds `why()`.** A gap path is not reported as governed by `why()`.
- **`--json` shape** and gap ordering.

**Dogfood (recorded).** `decree intent-check --under SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ
--files src/decree/commands/mcp_server.py` surfaces `mcp_server.py` as a gap
(`commit_count == 2` from the surfacing + docs commits) — a signal **batch v2
suppresses** via owned-elsewhere, confirming the point-of-change surface extracts
decision-specific gaps the corpus surface cannot. Gates: `ruff`, `pytest`,
`decree lint`, `decree index rebuild`/`verify`, Towncrier.

## Acceptance Criteria

- [x] `intent_check` and `intent_review` accept an optional `under`; absent it the gap check is skipped and existing output + exit code are unchanged.
- [x] An `under` that is malformed or not in `decisions` sets `under_error` and exits 2 (validated via `SELECT 1 FROM decisions`, not `require_doc_id` alone); intent-review's new exit-2 path is documented.
- [x] `governs_gaps` = `F` ∩ {paths with `commit_count >= 2` in `observed_governs[under]`} minus `under`'s declared file-path `governs:` (via `_path_covers(declared_entry, P)`, symbol entries excluded) minus `_is_structural_noise`; a pure index read (no git shellout, no working-tree access). No owned-elsewhere or shared-infra filter.
- [x] A decision with no `commit_count >= 2` rows yields an empty gap set (squash-immune; fail-safe).
- [x] intent-review excludes deletions (added/modified paths only); in the structureless name-only mode the gap check is skipped, not run against deletions.
- [x] Reports expose `under_decision`, `under_error`, and `governs_gaps` (`path` + `commit_count`, sorted `(commit_count desc, path asc)`) in the dataclass and `--json`.
- [x] A soft `declare_governs` recommendation is emitted on gaps; it is excluded from the `proceed` guard and the exit-code tuple, so gaps never gate `proceed` or change the exit code.
- [x] CLI `--under` on both commands and an MCP `under` parameter, documented in `--help` and tool docstrings (including `under_decision`/`under_error`/`governs_gaps`/`declare_governs`).
- [x] `governs_gaps` is never read by `why()` / `refs`; promotion to `governs:` happens only via a deliberate frontmatter edit.
- [x] Tests cover gap-surfaced, squash-immune, declared-excluded (file + directory slash/slashless + symbol), not-observed, structural, no-`under`, unknown-`under` (exit 2), advisory, intent-review deletions, never-feeds-`why()`, and `--json` shape/order.
- [x] Dogfood recorded: `mcp_server.py` surfaces under SPEC-…VFQ where batch v2 does not.

## Deferred

Out of scope here (each its own SPEC under PRD-01KT22NMRS4QGHSFDBZ858PP1T, gated
on this surface earning real-world trust):

- [ ] **Corpus-scoped mode** — for a changed path with no `under`, suggest *which*
  decision repeat-touches it; needs v2's cross-decision precision controls back.
- [ ] **Promote the path predicates** (`_path_covers`, `_is_structural_noise`) to a
  shared module; today reused by cross-module import.
- [ ] **Confidence-gated assistance / assisted write** — *if ever* built, a new
  **append-only, file-grained, confirmation-gated** writer (the existing
  `--apply-suggestions` refuses pre-existing `governs:` and must not be loosened);
  **no directory roll-up** (it manufactures dead-governance).
- [ ] **`[health]`-config** for the structural-noise globs (shared dependency with
  v2), so configurability precedes any automation that depends on the filter.
