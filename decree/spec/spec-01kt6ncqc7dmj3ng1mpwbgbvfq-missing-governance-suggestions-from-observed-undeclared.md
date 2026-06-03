---
date: '2026-06-03'
governs:
- src/decree/commands/health.py
id: SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D
- SPEC-01KT22NMRYNFYM7EN80WS2HD6F
- SPEC-01KT22NMRXFWNE61NSETKATHBA
- SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S
status: draft
---

# SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ Missing governance suggestions from observed undeclared paths

## Overview

v1 (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D) added `observed_governs` — the files each
decision's trailer-linked commits actually touched — and **dead-governance**:
declared `governs:` paths that **no** linked commit touched (the **declared ∖
observed** direction, high precision, validated at zero false positives on the
decree corpus).

This SPEC adds the **inverse, lower-precision** direction — **observed ∖
declared**: paths a decision's own trailer-linked commits keep touching that the
decision does **not** declare it governs. That is *missing governance*: the
`governs:` declaration is incomplete relative to where the work landed.

### The noise model — and why the obvious one is wrong

The first draft of this SPEC proposed inverse-document-frequency (IDF)
down-weighting as the primary noise control: "a file touched by many decisions
governs nothing in particular." A maintainer review **ran that algorithm against
decree's own `observed_governs`** and it produced **162 candidates, 126 of them
(78%) from a single 106-file squash commit** — and IDF *ranked that noise
highest*, because squash over-attribution gives a file low cross-decision
frequency (high IDF). The provenance model
([docs/provenance-model.md](../../docs/provenance-model.md)) already names this:
git guarantees commit→files, but a **squash/batch commit over-attributes** every
file it touched to one decision. The dominant noise here is **per-decision
over-attribution**, not cross-decision commonality. IDF is built for the latter,
so it is the wrong primary tool.

The corrected model makes **per-decision attribution strength** the primary
precision lever:

1. **Repeat-touch gate (primary).** A path is a candidate for decision `X` only
   if `X` touched it in **≥ 2 distinct trailer-linked commits**
   (`observed_governs.commit_count ≥ 2` — already stored, a pure index read). A
   file dumped once in a 106-file squash has `commit_count = 1` and is dropped;
   a file `X` returned to across separate commits is real attribution. This is
   **fail-safe**: a decision with only one linked commit yields **no** candidates
   (every file is count 1) — the signal abstains rather than guess, exactly as
   decree abstains elsewhere under thin evidence.
2. **Shared-infra floor (secondary).** Among repeat-touched candidates, a path
   repeat-touched by **≥ 3 distinct decisions** has no single owner — drop it.
   This is the surviving, scale-stable form of the "document frequency"
   intuition (an absolute multi-owner floor, not the draft's `DF/N ≥ 0.5` ratio,
   which was inert at small N and meaningless across corpus sizes).

Because precision is still inherently below dead-governance, the signal stays
**advisory**: reported but **never changing `decree health`'s exit code**, and —
like every provenance read — **never** consulted by `why()` / `intent-check`.

### Distinct from existing signals

- `ungoverned_hotspots` (SPEC-01KT22NMRYNFYM7EN80WS2HD6F) answers a **corpus**
  question from **raw churn**: "which hot files have *no* owner?" It cannot say
  *who* should own them.
- Missing-governance answers a **per-decision** question from **trailer
  attribution**: "decision X's own commits keep touching this unowned file, so X
  is the likely owner." It is the **subset of ungoverned files for which trailer
  attribution proposes an owner** — surfaced in `health` as "ungoverned, *with a
  proposed owner*," and exactly the candidate `decree migrate governs` (v3) needs.

No LLM, no new dependency, no new command or MCP tool — a new advisory section in
`decree health`, computed as a pure index read.

## Technical Design

### The candidate set: observed ∖ declared, per decision

For each decision `X`, a path `P ∈ observed_governs(X)` is a missing-governance
**candidate** iff every gate below passes. All inputs are already-indexed tables
(`observed_governs`, `governs`); the computation is a **pure read in `health.py`
with no git shellout and no working-tree access** — v1 paid the attribution cost
at index time, and reading the working tree here would make the result depend on
checkout state rather than the index (a determinism leak; see the generated-
artifact note below).

1. **Repeat-touch (primary precision gate).** `observed_governs.commit_count ≥ 2`
   for `(X, P)`. Drops single-commit over-attribution; abstains for
   thin-attribution decisions.

2. **Not already declared by `X`.** Excluded if any of `X`'s declared `governs:`
   covers `P`, using the **same v1 `_path_covers`** (`P == D` or `P` under
   directory `D`, trailing slash optional). No new predicate; `why()` untouched.

3. **Owned by nobody (load-bearing, not just scope).** Excluded if **any**
   decision's declared `governs:` covers `P`. A file that already has a governing
   decision is not *missing* governance. This also removes the case where a squash
   commit touched another decision's already-governed files, so it carries real
   precision weight, not only a scope cut. Surfacing cross-decision overlap ("X
   also touches Y's file") is a separate, noisier signal — deferred.

4. **Not structural noise.** A decision's commits routinely touch its tests and
   changelog fragment; these survive the repeat-touch gate yet are never
   governance targets. Excluded by a **path-based** (therefore deterministic)
   default heuristic — segments matching `tests/`, `test_*` / `*_test.*`,
   `*.test.*` / `*.spec.*`, and `changelog.d/`. This is a **decree-tuned,
   known-incomplete** default (it will not match every project's layout — e.g.
   Rust inline `#[cfg(test)]`, a project that uses `spec/` for specifications) and
   is the first candidate for `[health]`-config override (deferred). It is the one
   project-shaped default and is labelled as such, not sold as universal.

> **Generated artifacts are filtered at index time, by path — not here, by
> content.** The draft proposed `health._is_generated_artifact`, but that reads
> **current working-tree content** of a **historical** path: a renamed/deleted
> observed path would be mis-judged from whatever occupies that path today,
> making the candidate set non-deterministic. v1's `_observable_path` already
> drops corpus docs, `index.md`, `reports/`, and lockfiles **by path** at index
> time; that path-based, deterministic filter is the only generated-artifact
> filter used. If more coverage is needed it is added there, never as a read-time
> content sniff.

### Noise control: shared-infra floor and ranking

Over the candidates surviving the four gates:

- `DF(P)` = number of **distinct decisions** for which `P` is a repeat-touch
  candidate (a single `GROUP BY` over `observed_governs WHERE commit_count ≥ 2`).
- **Floor.** Drop candidates with `DF ≥ 3` (repeat-touched by 3+ decisions ⇒ no
  single owner ⇒ not a missing-governance suggestion for any one of them). This
  is absolute and scale-stable; it does not flip with corpus size.
- **Ranking.** Survivors sort by `(commit_count desc, DF asc, path asc)` —
  strongest per-decision attribution first, then rarer-across-decisions first.
  This ordering is part of the `--json` contract and is tested.
- **Caps.** The **human** section is capped to the top `K` candidates per
  decision (default 5) and the top `M` decisions by best-candidate `commit_count`
  (default 10), with **any truncation stated explicitly** (no silent caps).
  `--json` is **uncapped** — the full set is the machine contract
  `decree migrate governs` (v3) consumes.

### Advisory, never a finding

- **Exit code.** `missing_governance` is **excluded** from `health_run`'s
  `has_findings`. `decree health` exits `0` on missing-governance alone;
  dead-governance keeps exiting `1`. The two directions are deliberately
  asymmetric in authority. Because the repeat-touch gate keeps the list short and
  plausible, the section is shown by default (capped) rather than hidden behind a
  flag — default `health` stays high-signal.
- **Never feeds `why()` / `intent-check`.** Same invariant as v1 — those answer
  only from declared `governs:`. Missing-governance is a *suggestion to edit
  `governs:`*, not a governance fact.
- **Stale-tolerant.** Reads `observed_governs` as-is; `health` never triggers a
  rebuild.

### Output and honesty

- `HealthReport` gains `missing_governance: tuple[MissingGovernance, ...]`, where
  `MissingGovernance(decision_id, linked_commit_count, observed_path_count,
  candidates)` and each candidate carries `path`, `commit_count` (the primary
  trust signal — repeat-touch strength), and `distinct_decisions` (`DF`).
- The per-decision `linked_commit_count` and `observed_path_count` are the
  honesty fields that let a reader **dismiss** a suggestion: "this came from 1
  commit touching 106 files" is visible directly (and, per the repeat-touch gate,
  such a decision contributes no candidates at all). The existing
  `observed_as_of` timestamp covers freshness.
- `--json` gains a `missing_governance` key. Human output gains a clearly
  labelled **"Suggested governance (advisory)"** section, visually separate from
  dead-governance, stating it does not affect exit status and reading as
  "ungoverned files with a proposed owner" so it does not duplicate the
  hotspots section.

### Relationship to existing decisions

Builds on v1 (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D): consumes `observed_governs`,
reuses `_path_covers`, follows the same advisory/fail-safe/never-feeds-`why()`
discipline. Lives in `decree health` (SPEC-01KT22NMRYNFYM7EN80WS2HD6F) beside
`ungoverned_hotspots`, which it refines (the unowned files for which attribution
proposes an owner) rather than duplicates. Matches `governs` directory semantics
(SPEC-01KT22NMRXFWNE61NSETKATHBA) via the shared cover predicate. Its output is
the candidate source `decree migrate governs --analyze`
(SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S) consumes in v3 — detection here, remediation
there, no second writer.

## Testing Strategy

`pytest` over temp-git fixtures, extending the helpers in
`tests/test_dead_governance.py`. Cover:

- **Repeat-touch surfaced / single-commit suppressed.** A file a decision touches
  in ≥2 distinct linked commits surfaces; a file touched once in a many-file
  commit (the squash signature) does not — the regression that falsified the
  draft.
- **Declared excluded** (exact and directory, slash and slashless).
- **Owned-elsewhere excluded** — a path governed by another decision is not
  surfaced for the decision that merely touched it.
- **Shared-infra floor** — a path repeat-touched by ≥3 decisions is dropped; by 2
  is kept and ranked.
- **Structural exclusions** — `tests/` and `changelog.d/` touches not surfaced.
- **Determinism** — the candidate set does not change when the working tree
  changes (rename/delete an observed path on disk; rebuild-free `health` output
  is identical), proving no working-tree dependence.
- **Advisory** — a report with missing-governance but no dead/stale/hotspot
  findings exits `0`.
- **`--json` shape**, candidate ordering as contract, and the
  never-read-by-`why()`/`intent-check` invariant.

**Dogfood gating experiment (a hard gate, not a soft note).** Run the implemented
signal on the decree corpus and record the count. **Pass bar: ≤ 10 candidates
total, every one manually confirmed a plausible governance extension, and 0
implausible.** (0 is a pass — it means attribution is currently too thin to
suggest, which is correct fail-safe behaviour, not a defect.) If the bar is
exceeded, the precision model is escalated — add the **breadth gate** (suppress
decisions whose `observed_path_count / linked_commit_count` ratio marks a batch
committer) named in Deferred — **before** this SPEC is considered done. The draft
produced 162 here; the corrected model must produce a short, confirmed list or it
does not ship. Gates: `ruff`, `pytest`, `decree lint`,
`decree index rebuild`/`verify`, Towncrier fragment.

**Validation result (recorded).** On the decree corpus the corrected signal
yields **0 candidates** — decree's history is bulk single-commit imports (every
observed path has `commit_count = 1`, no repeat-touch), so the signal correctly
**abstains**: 0 false positives, dogfood gate met. Because decree's own corpus
cannot exercise the value path, that path is validated by the realistic
incremental-history fixture in `tests/test_missing_governance.py`: among
declared / owned-elsewhere / structural / shared-infra / single-touch noise it
surfaces **exactly one** candidate — the file a decision repeat-developed across
two commits but never declared — proving the signal speaks correctly, and only
then, when incremental history exists.

## Acceptance Criteria

- [ ] `missing_governance(db)` returns, per decision, repeat-touched paths (`observed_governs.commit_count ≥ 2`) not covered by its own declared `governs:` (reusing v1's `_path_covers`), computed as a pure index read with no git shellout and no working-tree access.
- [ ] Candidates covered by **any** decision's declared `governs:` (owned elsewhere) are excluded.
- [ ] Structural noise (`tests/`, `test_*`/`*_test.*`, `*.test.*`/`*.spec.*`, `changelog.d/`) is excluded by a path-based (deterministic) heuristic; no read-time content sniffing (`_is_generated_artifact` is **not** used) — generated-artifact filtering stays the index-time path filter from v1.
- [ ] `DF(path)` = distinct decisions with `commit_count ≥ 2` for that path; candidates with `DF ≥ 3` are dropped, and survivors rank by `(commit_count desc, DF asc, path asc)`.
- [ ] Output is capped to top `K` candidates per decision and top `M` decisions, with any truncation stated explicitly (no silent caps).
- [ ] `HealthReport.missing_governance` carries per decision `decision_id`, `linked_commit_count`, `observed_path_count`, and candidates with `path`, `commit_count`, `distinct_decisions`; `--json` exposes a `missing_governance` key with a stable candidate ordering.
- [ ] `decree health` gains a "Suggested governance (advisory)" human section, framed as "ungoverned files with a proposed owner," stating it does not affect exit status.
- [ ] `missing_governance` is excluded from `has_findings`: `decree health` exits `0` when missing-governance is the only signal; dead-governance still exits `1`.
- [ ] The candidate set is **deterministic** with respect to the working tree (changing/removing an observed path on disk does not change `health` output without a rebuild) — covered by a test.
- [ ] `missing_governance` is never read by `why()` or `intent-check` (no silent fallback) — covered by a test.
- [ ] Tests cover repeat-touch-surfaced, single-commit-suppressed, declared-excluded (slash + slashless), owned-elsewhere-excluded, shared-infra floor, structural exclusions, determinism, advisory exit `0`, and `--json` shape/order.
- [ ] **Dogfood gate met:** on the decree corpus the signal yields ≤ 10 candidates, each manually confirmed plausible, 0 implausible; the count is recorded. If exceeded, the breadth gate is added before closing this SPEC.

## Deferred

Out of scope for this SPEC (each becomes its own SPEC under
PRD-01KT22NMRS4QGHSFDBZ858PP1T, only after this signal earns trust as
low-false-positive on a real corpus):

- [ ] **Breadth gate (escalation)** — suppressing decisions whose
  `observed_path_count / linked_commit_count` ratio marks a batch committer.
  Implemented only if the dogfood bar above is exceeded; named here so the
  escalation path is explicit, not improvised.
- [ ] **Cross-decision overlap** — surfacing "decision X also touches decision
  Y's governed file," a separate and noisier signal than the no-owner gap.
- [ ] **`[health]`-config tuning** — making the `K`/`M` caps, the `DF` floor, and
  the structural-exclusion globs configurable instead of built-in defaults.
- [ ] **Directory roll-up** — collapsing file-grain candidates into directory
  suggestions (only needed once a frontmatter value is written).
- [ ] **`decree migrate governs --analyze` git candidate source** consuming this
  output, with `--write` routed through the existing `--apply-suggestions` atomic
  path (SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S) — no second writer.
- [ ] **Surfacing** via the existing MCP `health` tool payload and as
  `decree lint` / `decree ddd` hints (no new tool, no new command).
