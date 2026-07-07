# Research Backlog

Grounded, prioritized to-do list derived from the Agentkith dogfooding pack
(files `00`–`05`). Each item was cross-checked against the real decree code
(file:line anchors below are verified) and against external precedent from
comparable tools (SARIF, Semgrep, CODEOWNERS, log4brains) — the `[S#]` markers
resolve in the [Sources](#sources) section. Backlog IDs (`B1`…`B15`) map back to
the pack's `CI1`–`CI7` / `SK1`–`SK6` proposals via the **Feedback ref** column.

This is a build plan, not a commitment: items marked "Needs a decision" require a
human call (see [Decisions to make](#decisions-to-make-human-before-building))
before implementation.

## Shipped

Landed via PRD-01KWXMRR7R3S5CSAAZRGFHR5QN → ADR-01KWXMRRB44CE78H0659D9WDY7 →
SPEC-01KWXPAP3ENJ9BF7MADKHHCF6H (Option A: additive, exit-code stable):

- **B1** — severity-aware `decree-ddd` skill guidance (both copies) + fixed
  `llm-agent-integration.md`.
- **B14** — SKILL sync-guard test.
- **B7** — `config.classify_path()` (path-only source/corpus/generated).
- **B6** — planned-file classification + `add_governance` suppression for
  decree-document self-edits (Agentkith Case 5 fixed).
- **B3** — `blocking_findings` / `advisory_findings` / `corpus_hygiene_findings`
  additive JSON + MCP keys.
- **B4** — human "Block now / Clean later" output + recommended next command.
- **B5** — exit-code contract regression tests (advisory/corpus stay exit 0;
  stale-only stays exit 1).

Still open (need a human decision first): **B8** `--under` reframe, **B2** full
5-case fixture module, **B9–B13** health signals, **B12** directory-prefix
overlap, **B15** baseline/new-vs-debt. Also found: the sprint CLI cannot
`complete`/`drop` a *backlog* item that reaches terminal status — a small decree
gap worth its own fix.

## TL;DR

The core problem is not that `intent-check` emits too many warnings — it's that it collapses three unlike things (multi-decision conflicts, stale-governance debt, and live-session overlap) into one undifferentiated exit-1 bucket at `intent_check.py:703`, so an agent can't tell "stop and fix" from "note and proceed." The fix is **typed findings, not fewer findings**: give every finding a closed *class* (`blocking` / `advisory` / `corpus_hygiene`) that is distinct from severity, exactly as SARIF splits `kind` from `level` [S1][S2][S3]. Almost all of this data already exists as separate arrays in `IntentCheckReport` (`intent_check.py:68-96`); the work is categorizing and re-presenting it, not recomputing it, and it can land strictly additively under the existing json-contracts additive rule (`json-contracts.md:21-23`). **Build first, in order:** (1) the SK1-6 skill edits (pure prose, zero code) so agents stop blindly obeying exit 1 today; (2) the additive typed finding-class buckets in `--json` plus a "block now / clean later" human split (CI1+CI6, P2) with exit codes held byte-identical; (3) CI3 corpus/self-edit classification so the `corpus_hygiene` bucket is real and the Case5 self-edit false positive dies. Everything past that (first-class `--under`, health signals) is valuable but gated behind two human decisions: **does `--under` change the exit code**, and **is path classification path-only or working-tree-aware**.

## Prioritized backlog

| ID | Change | Feedback ref | Current code reality (partly exists?) | Effort | Impact | Risk | Doc type | Rollout phase |
|----|--------|-------------|----------------------------------------|--------|--------|------|----------|---------------|
| B1 | Ship the six agent-loop edits (work-mode, authoritative decision, severity interpretation, boundary preflight, update-SPEC-first, final report contract) to both SKILL copies + docs | SK1-6 | Absent from skill; `--under`/`update_spec_first` verb already exist in core. Pure prose bridge until CI1 lands (`04:62`) | L | High | Med (mis-advice) | skill-edit | P1 |
| B2 | Agentkith dogfood fixture suite + characterization tests pinning CURRENT output | CI7 | Partly seeded (`_write_corpus_two_specs_same_file` test_intent_check.py:133-187; `_bootstrap_repo` test_health.py:69-108). No shared module, no 3-SPEC/draft-100%/60-path/self-edit corpora | M | High (enabler) | Low | SPEC (test) | P1-2 |
| B3 | Add `blocking_findings[]`/`advisory_findings[]`/`corpus_hygiene_findings[]` as additive top-level keys over existing findings | CI1 | Data exists flat & untyped (report_to_dict:481-503). `governs_gaps` is the proven additive precedent | M | High | Low | SPEC | P2 |
| B4 | Rewrite `_format_human` into "Block now" / "Clean later" sections + one recommended-next-command line | CI6 | Absent; one flat render (intent_check.py:552-643). Built on B3's bucketizer; "Clean later" corpus-hygiene half stays empty until B6 | S | High | Low (human-only) | SPEC (needs B3+B6) | P2 |
| B5 | Freeze exit-code logic + regression test asserting stale-only corpus still exits 1 after buckets land | CI1 | Exit 1 = conflicts∨stale∨live (`:703`). Reclassification could silently flip 1→0 — a contract break | S | High (safety) | High if skipped | ADR + test | P2 |
| B6 | Consume B7's classifier to skip corpus/generated paths + suppress `add_governance` for decree-doc self-edits | CI3 | No self-edit filter; `add_governance` unfiltered (intent_check.py:373-385). `_is_structural_noise` only wired into `--under` path | M | High | Med (heuristic) | ADR + SPEC | P2 |
| B7 | Extract a reusable `classify_path(path)->source\|corpus\|generated` primitive (prerequisite of B6) | CI3 | Primitives scattered & private: `_is_generated_artifact` (health.py:210-224), `_observable_path` (index_db.py:654-671), `_is_structural_noise` (health.py:407-427). No unified `classify_path()` | M | Med (enabler) | Med | ADR | P2 (start, before B6) |
| B8 | Make `--under SPEC-ID` a first-class decision-relative report (owned / gaps / contextual overlaps / contradictions) | CI2 | Flag EXISTS but narrow: only computes `governs_gaps` + one `declare_governs` rec (intent_check.py:277-291). No owned-vs-contextual reframe | L | High | Med (exit-scope creep) | ADR + SPEC | P3 |
| B9 | Lifecycle-drift (c): implemented/terminal + stale-or-dead governs gap | CI5 | Both findings already computed (stale_decisions health.py:229-289; dead_governance :365-389). Only missing input = `d.status` | S | Med | Low | SPEC | P4 |
| B10 | Lifecycle-drift (a): 100% primary ACs + draft + commits attached | CI5 | All inputs indexed (`acceptance_criteria` deferred=0; `decisions.status`; `linked` dict). Health reads none today | S | Med | Low | SPEC | P4 |
| B11 | Broad-governance advisory signal (governs_count, exact/dir split, ratio, hot-file overlap) — subsumes CI4's owned-vs-touched sub-item | CI4 | Fully derivable; churn dict already computed & discarded (health.py:308). No per-decision aggregation surfaced | M | Med | Med (git cost, thresholds) | SPEC | P4 |
| B12 | Expand conflict/overlap detection beyond exact-path to directory-prefix governs (intent-check query, NOT health) | CI4/Case3 | Confirmed gap: conflict query is `WHERE path IN(...)` exact-only (intent_check.py:206-214); directory overlap invisible | M | Med | Med (count explosion) | ADR (reconcile) | P4 |
| B13 | Lifecycle-drift (b): terminal status + ACs changed after report snapshot | CI5 | Weakest support: no AC-granular snapshot; only unstructured report checkboxes (report.py:181-204). Needs parse-diff or new AC-hash | L | Low-Med | Med (purity break) | ADR + SPEC | P4-5 |
| B14 | Sync guard so the two `decree-ddd` SKILL copies can't drift | SK1-6 infra | Currently byte-identical but NO test enforces it; `decree-governs-suggest` copies ALREADY diverge | S | Low (footgun) | Low | test | P1 |
| B15 (inferred) | "New vs pre-existing" finding state (SARIF `baselineState` / Semgrep diff) to separate newly-introduced conflicts from pre-existing debt | inferred | `progress --changed` base-ref diffing is in CLAUDE.md quick-ref but NOT in the provided code grounding (no file:line) — treat as UNVERIFIED; intent-check has no two-run set-difference in any grounded module | L | Med (future) | Med | ADR | P5+ |

## Item detail

### B1 — Agent-loop skill edits (SK1-6)
**Change:** Add six sections to BOTH `src/decree/templates/agent/skills/decree-ddd/SKILL.md` (authoritative, shipped via `agents.py:16,35-48`) and the top-level `skills/decree-ddd/SKILL.md`, inserted around the current Work Loop (`SKILL.md:48-72`): classify work mode before intent-check (`04:23-40`); name an authoritative decision and switch the example to `intent-check --under SPEC-... --plan ... --files ...` (`04:44-58`); interpret exit-1 by severity instead of the current blind "resolve all" (`04:63-83`, softening `llm-agent-integration.md:59-62`); a 10-field boundary preflight (`04:88-101`); the three-way "update the SPEC, not just query it" branch (`04:110-115`, leaning on the existing `update_spec_first` verb at `intent_check.py:409`); and a 4-line final report contract (`04:124-131`), optionally mirrored into `AGENTS.md:104-113`.
**Why:** This is the direct answer to Case1 (agent hit a 3-SPEC ViewModel with no way to work under one) and to the whole "one exit-1 bucket" complaint — it gives the agent the interpretation layer today, by hand, before core types anything. Boundary preflight is what kept the Agentkith toolbar fix from becoming a local UI patch (`04:103-104`).
**Effort/risk (revised):** Effort is **L, not M** — this is six independent sections rolled across two SKILL copies plus edits to `llm-agent-integration.md` and `AGENTS.md`, not one edit. The **SK3 severity-interpretation edit carries Med risk**: it hand-classifies findings against today's flat output, so if the prose doesn't exactly match the current verbs/arrays it will actively mis-advise agents (worse than saying nothing). Pin SK3's hand-mapping to the exact field names in `report_to_dict:481-503` and keep it a fallback that CI1/B3 later supersedes.
**Precedent:** SARIF proves class-vs-severity is a real distinction the agent can encode by hand now [S1][S3]; CODEOWNERS shows overlap can be modeled as explicit co-ownership rather than an error [S7][S9], which the "authoritative decision + contextual decisions" sentence encodes.
**Open questions:** Describe the richer `--under` report now (aspirational) or gate that paragraph behind a "once CI2/B8 lands" note so agents aren't told to expect output the tool doesn't yet produce? After CI1 lands, keep the hand-classification as a fallback for older decree versions or replace it wholesale?

### B2 — Agentkith dogfood fixture suite (CI7)
**Change:** New shared module `tests/agentkith_fixtures.py` with five builders, copying `_git_init/_commit/_bootstrap_repo` from `test_health.py:24-119` for the git-backed cases: (1) hot ViewModel governed by 3 complementary SPECs, one designated `--under` (extend `_write_corpus_two_specs_same_file`, test_intent_check.py:133-187, pure IndexDB); (2) shared-contract ungoverned→governed two-variant (why abstains + `add_governance` fires vs `governs_gaps` closed); (3) broad-governs 60+ paths overlapping a second voice SPEC (git, needs commits for ratio/hot-file overlap); (4) draft-at-100% SPEC with commits attached (git); (5) planned SPEC self-edit (`planned_files` includes `decree/spec/spec-*.md`). Land characterization tests pinning CURRENT command output now so CI1-CI6 diffs are visible.
**Why:** Each corpus is one Agentkith case; without them, CI1-CI6 changes are unverifiable and the two exact-key-set shape tests (`test_intent_check.py:403-416`, `:558-571`) become the only tripwire.
**Open questions:** Which builders truly need git (3 and 4 do; 1, 2, 5 don't) — keep git optional per-builder. Return `(db, root)` vs `(repo, root)` vs always `(root,)` and let tests rebuild — pick one convention.

### B3 — Typed finding-class buckets (CI1)
**Change:** Add a pure categorizer `_bucket_findings(report)` mapping existing findings with no recomputation: blocking = conflicts + stale_governance + live_conflicts (the exact current `has_blockers` set), advisory = `governs_gaps`, corpus_hygiene = the `add_governance` recs reclassified once B6 lands. Surface as three NEW top-level arrays in `report_to_dict` (`intent_check.py:481-503`) and as defaulted tuple fields on `IntentCheckReport` (`:68-96`) for MCP parity (shared serializer `mcp_server.py:806`). Update the MCP docstring (`mcp_server.py:699-748`), `json-contracts.md:89`, `usage.md:481-518`, and the two exact-key-set assertions. Note the framing: these buckets are a finding **class** (the SARIF `kind` analogue), NOT a severity (`level`) — keep the SPEC unambiguous that `blocking`/`advisory`/`corpus_hygiene` name what kind of finding it is, and any serious→minor severity is a separate optional axis.
**Why:** This is the structural fix for the core complaint — Case1/Case2/Case3 all reduce to "a contextual overlap is indistinguishable from a real contradiction in one flat list."
**Precedent:** SARIF puts a closed `kind` enum on every result independent of `level`, and makes non-failures structurally non-severe (`kind!=fail ⇒ level=none`) [S1][S2] — the model for making `corpus_hygiene` a class that can never flip the exit code. Use a small closed ordered vocabulary with fixed prose meanings, not free-form strings [S3].
**Open questions:** Uniform `{kind, ...}` envelope per bucket entry, or reference the heterogeneous per-array shapes? Do buckets duplicate the flat lists (safe, additive) or eventually replace them (needs a version bump)? Is `add_governance` corpus-hygiene only after B6, or does the bucket start empty until then?

### B4 — Human "block now / clean later" output (CI6)
**Change:** Rewrite `_format_human` (`intent_check.py:552-643`) into two labeled sections — "Block now" (conflicts + stale_governance + live_conflicts) and "Clean later" (`governs_gaps` + corpus-hygiene) — then one recommended-next-command line derived from the top blocker. Build on B3's bucketizer so JSON and human share one source of truth; leave `report_to_dict` untouched.
**Why:** Case1/Case5 — a human/agent reading the flat "Recommended actions (N)" list can't see which line stops the change.
**Dependency (revised):** B4 depends on B3 **AND B6** — the "Clean later" section's corpus-hygiene half is empty until CI3/B6 reclassifies the self-edit `add_governance` recs into `corpus_hygiene`. Landing B4 without B6 ships a "Clean later" heading with only `governs_gaps` under it and leaves Case5 broken.
**Precedent:** The block/clean split is the human rendering of SARIF's fail-vs-non-fail structural distinction [S2].
**Open questions:** Land inline before B3 (per rollout P2-before-P4) or wait to reuse B3's bucketizer and avoid duplicated categorization? Priority order for the single "next command" when multiple blocker kinds coexist (conflict vs stale vs live)?

### B5 — Freeze the exit-code contract (CI1 guard)
**Change:** In the additive PR, keep `intent_check.py:703` byte-identical (exit 1 whenever conflicts/stale/live present); ship buckets as an informational typed index only. Add a regression test: stale-only corpus still exits 1 after buckets land. Defer any "proceed-on-advisory" exit relaxation to an explicit opt-in flag or a documented version bump.
**Why:** The CI1 proposal reclassifies "stale contextual decision" as corpus_hygiene; if the exit logic ever keys on `blocking_findings` only, a stale-only run silently flips 1→0 — a break to the reverse-engineered exit contract (`json-contracts.md:31-47`), not an additive change.
**Open questions:** Should proceed-on-advisory be a decree-side exit change at all, or purely an agent-loop decision (read buckets, ignore exit) per SK3/B1? Leaning agent-side keeps the exit contract intact.

### B6 — Suppress self-edit `add_governance` via classify_path (CI3)
**Change:** Gate the `add_governance` loop (`intent_check.py:373-385`) to skip corpus/generated paths **by consuming B7's `classify_path()` primitive — B6 does NOT introduce its own classifier**, and emit `source_changes`/`corpus_changes`/`generated_artifact_changes` keys. Corpus = under any `load_doc_types()` dir (`doctypes.py:15`, already imported at `intent_check.py:45`) or equal to a `decisions.path`; generated = index.md/reports/graph outputs — all of that logic lives in B7. These new keys auto-propagate to MCP through the shared serializer (`mcp_server.py:806`), so update the MCP docstring (`mcp_server.py:699-748`), `json-contracts.md`, and `usage.md` in the same PR or the contract doc drifts.
**Why:** Case5 — editing a decree doc as a planned file today yields "has no governing decision... write a SPEC." Valid corpus maintenance looks ungoverned.
**Open questions:** Is "generated-artifact" worth a distinct bucket vs folding into corpus (decree's own generated outputs are few)? Total suppression, or a different hint (e.g. "run decree lint") for corpus docs? Corpus detection MUST read config dirs, not hardcode `decree/` (delegated to B7's definition).

### B7 — Reusable `classify_path()` primitive (prerequisite of B6)
**Change:** Add one classifier (likely `config.py` or a small new module) taking a repo-relative path → source/corpus/generated. **B6 is its only consumer** (see below). Prefer the path-only variant (deterministic, index-time reproducible) over `_is_generated_artifact`'s working-tree header sniff.
**Why:** The primitives exist five times over privately (`parser.py:26`, `health.py:210-224`, `health.py:407-427`, `index_db.py:654-671`, config dirs) — B6/CI3 needs one shared, tested definition or the corpus/generated logic diverges.
**B11 does NOT depend on B7 (corrected):** the CI4 `broad_governance(db, churn)` signal never consumes `classify_path` — it aggregates governs rows and churn — and `observed_governs` already filters corpus/generated via `_observable_path`. Do not gate B11 on this refactor.
**Open questions:** Path-only (deterministic) or allowed to read file headers? Is "corpus" defined by config type dirs, by presence in the `decisions` table (handles renamed docs), or both? **This decision (B7) must precede B6.**

### B8 — First-class `--under` decision-relative report (CI2)
**Change:** Add a projection layer over already-computed data: partition `governing_decisions` (`intent_check.py:162-171`) into `under`-owned vs contextual by `decision_id`, and split `conflicts` (`:202-222`) into contradictions involving `under` vs contextual overlaps not involving it. New keys `active_decision`/`owned_files`/`contextual_overlaps`/`contradictions`; reuse `governs_gaps` as the gaps section; lead `_format_human` with the active decision. `--under` flag, param threading (`cli.py:955-962`, `intent_check.py:140`, `mcp_server.py:804`) and `under_error`→exit 2 already exist.
**Why:** Case1 (work under SPEC-X, treat the other 2 as contextual) and Case3 (66/60-path SPECs); Case2 (composition-root overlap is structural, not contradictory).
**Precedent:** CODEOWNERS models multiple owners on one path as a sanctioned set-union with "any-one-satisfies" semantics [S7], resolves nested overlaps deterministically by precedence rather than erroring [S8], and requires co-ownership to be declared explicitly [S9] — the template for treating composition-root plurality as co-governance, not conflict.
**Open questions (load-bearing):** Does `--under` change the EXIT CODE (demote contextual overlaps to advisory) or only presentation? This is the P3 decision and must be gated behind B5/an ADR. How to distinguish a "contradiction" from expected composition-root overlap (Case2) without semantic judging, given the core is deterministic (`usage.md:516`)? Fall back to flat output when the under-decision governs none of its own files, or still render the owned/contextual frame?

### B9 / B10 / B13 — Lifecycle-drift health signals (CI5)
Health today selects neither `decisions.status` nor `acceptance_criteria` (confirmed), so all three variants need health to gain a `SELECT id, status, type FROM decisions` beyond the current `id/type/path` (`health.py:251`).
- **B9 (c) — implemented + stale governs gap [S, do first]:** Filter the already-computed `stale_decisions` (`health.py:229-289`) + `dead_governance` (`:365-389`) by terminal status via `is_terminal_success` (`report.py:393-407`). No new git access, no new tables. **Why:** governance rotting after ship. *Open:* distinct signal or just tag existing entries `is_terminal: true`? Does "stale governs gap" mean stale, dead, or the union?
- **B10 (a) — 100% primary ACs + draft + commits [S]:** `SELECT decision_id, SUM(done), COUNT(*) FROM acceptance_criteria WHERE deferred=0 GROUP BY decision_id` (do NOT reuse `progress.py:20-26`, which re-parses markdown and bypasses the index) ∧ status non-terminal ∧ `linked>=1` (reuse `_declared_and_linked` health.py:358-361). **Why:** Case4 — a SPEC at 100% primary ACs still `status=draft`; status stops signaling maturity. **Precedent:** log4brains encodes exactly this — draft "is not a resting state... you must change it once you reach a decision" [S10]. *Open:* advisory (CI6 buckets it "clean later") or exit-1 finding? Require commits, or also flag 100%+draft with zero commits (weaker)?
- **B13 (b) — terminal + ACs changed post-report [L]:** No AC-granular snapshot exists; only the unstructured completion-report checkboxes (`report.py:181-204`) + a `**Generated**` timestamp (`:166`). Option (i) parse the report checkbox block and diff vs current `acceptance_criteria`; option (ii) coarse git-time compare (`_file_last_touched_ts` vs report timestamp). **Why:** governance that claims done but drifted. **Precedent:** this is a two-run/snapshot diff — SARIF's `baselineState` is computed by matching a result across runs, with `updated` specifically flagging a matched finding whose supporting evidence changed [S4][S5], and Semgrep's diff-aware scan is the two-run set-difference model (`new/changed = head − base`) [S6] that an AC-hash snapshot would emulate. *Open:* content-diff (accurate, breaks health's pure-index invariant) vs timestamp-compare (cheap, coarse)? Stamp an AC content-hash into the snapshot at generation time so the check becomes a pure header read? Skip silently when no report exists (matches coverage-honesty)?

### B11 — Broad-governance advisory signal (CI4)
**Change:** New frozen `BroadGovernance(decision_id, governs_count, exact_governs_count, directory_governs_count, linked_commit_count, governs_to_commits_ratio, hot_file_overlap_count, overlapping_decision_ids)` + pure `broad_governance(db, churn)` in `health.py`. This dataclass **subsumes CI4's owned-vs-touched / `governs_to_commits_ratio` sub-item** (called out here so it isn't silently folded). All four metrics are derivable with zero new git access: governs_count via `GROUP BY decision_id`; exact/dir split via trailing-`/` (the `why()` PREFIX convention, `queries.py:150-153`, already done corpus-wide at `health.py:314-315`); ratio numerator = governs_count, denominator = the `linked` dict (`:358-361`); hot-file overlap = intersect governed paths with the churn dict already computed and discarded (`:308`). Advisory only — MUST stay out of `has_findings` (`:706`). These keys auto-propagate to MCP via health's `_report_to_dict`, so update the MCP docstring and `docs/health-signals.md` in the same PR.
**Why:** Case3 — governs became "files touched," not "files owned"; two voice SPECs governing 66/60 overlapping hot paths.
**Open questions:** What governs_count/ratio thresholds define "too broad" (follow the `_MG_*` constant + `[health]` config pattern, `:400-404`)? Count only exact hot-governed files or also directory-`governs:` reach (use `_path_covers`)? Report per-decision overlap count or pairwise clusters? Thread `_recent_file_churn` single-call to avoid doubling git cost.

### B12 — Directory-prefix overlap in conflict detection (CI4/Case3)
**Change:** Replace the exact-only conflict query `WHERE path IN (...)` (`intent_check.py:206-214`, `intent_review.py:325-333`) with `why()`'s two-branch match (exact + trailing-`/` prefix, `queries.py:150-153`). Reconcile the known divergence first: `why()` treats a slashless directory as exact-only, while `health._path_covers` (`:332-344`) treats slashless dirs as prefixes. **This is an intent-check/intent_review change, not a health signal** — it lands in the conflict query, and it depends on B3/B8 severity separation (below) so the extra directory matches surface as advisory/expected, not new blockers.
**Why:** Case3 — a file owned by SPEC-A exactly and SPEC-B via `src/voice/` prefix never registers as a conflict today, so broad-governance overlap is invisible.
**Open questions:** Expanding to prefix matching can explode conflict counts on broad SPECs — this strongly implies exact conflicts (blocking) must be separated from directory overlap (advisory/expected) per B3/B8. Distinguish structural overlap (Case2) by a decision-level flag or purely by exact-vs-directory match kind?

### B14 — SKILL sync guard (SK infra)
**Change:** Add a one-line test asserting the two `decree-ddd/SKILL.md` files are byte-equal (or dedupe to one source). Confirm whether the existing `decree-governs-suggest` divergence is intentional.
**Why:** Every B1 edit must land in both copies; nothing enforces it, so the packaged skill can ship stale guidance while the repo looks updated (`tests/test_agents.py` only checks existence + "decree DDD").

### B15 (inferred) — "New vs pre-existing" finding state
**Change:** A future taxonomy axis orthogonal to B3's class: is a finding newly introduced by this change, or pre-existing debt? A two-run set-difference (`new = head − base`) would compute it.
**Grounding caveat (revised):** The premise "decree already diffs against a base ref" comes from the CLAUDE.md quick-reference (`decree progress --changed --base origin/main`), **not from the provided code grounding** — no file:line supports it, so treat the "already diffs" claim as UNVERIFIED and confirm against `progress.py` before relying on it. What IS grounded: intent-check has no two-run set-difference in any module cited here.
**Why:** A newly-introduced conflict (blocking) is not the same as a stale overlap that predates the change (corpus_hygiene) — the exact distinction Case2/Case3 need to stop treating expected structural overlap as a new blocker.
**Precedent:** SARIF's `baselineState` is a closed 4-state enum (new / unchanged / updated / absent) COMPUTED by comparing two runs [S4], where "updated" specifically flags a matched finding whose evidence changed [S5]; Semgrep diff-aware scanning computes `new = head − base` rather than filtering one run to the diff lines [S6]. *This is a decision, not a committed item — flag it before over-investing in single-run classification.*

## Sequencing

**Quick wins — pure doc/skill, no code (Phase 1):**
- B1 (SK1-6 skill edits, effort L) and B14 (sync guard). No core change, works against today's flat output by hand-classification (`04:62`). The `--under` example in B1 already runs (emits `governs_gaps`); just don't promise the B8 reframe before it lands. B1 is a quick win in the sense of "no code," not "small" — budget for six sections across two copies plus SK3's exact-field mapping.
- B2 fixture suite can start here as characterization (pin current output) even though full assertions wait for the commands to exist.

**Phase 2 — intent-check output shape:** order is **B7 (classify_path primitive, FIRST) → B6 (self-edit suppression) → B3 (typed buckets) → B4 (human split) → B5 (exit-code freeze/guard)**. B7 must precede B6; B6 fills B3's `corpus_hygiene` bucket and unblocks Case5; B4 needs both B3 and B6. All additive and safe under `json-contracts.md:21-23`; the only in-repo cost is updating the two exact-key-set assertions plus the MCP docstring/json-contracts/health-signals docs. B6 is firmly in this phase — without it the `corpus_hygiene` bucket is empty and Case5 stays broken.

**Phase 3 — `--under` semantics:** B8. Presentation-only reframe is additive; any exit-code demotion is a contract change gated behind B5's decision.

**Phase 4 — health signals + one intent-check query change:** health signals B9 (cheapest, do first), B10, B11, B13 (biggest, last) — all advisory, exit 0, MCP passthrough automatic. **B12 rides in P4 by schedule but is NOT a health signal** — it modifies the intent-check/intent_review conflict query and depends on B3/B8 severity separation.

**Phase 5 — future:** B15 diff-aware / baseline state (only if the `progress --changed` premise verifies).

**Needs a decision (write an ADR before building):** B5/B8 exit-code semantics; B7 path-only-vs-header classification; B12 directory-overlap reconciliation (`why()` vs `_path_covers`); B13 snapshot approach; B15 whether to add a baseline axis at all (and whether its base-ref premise is real). **Bigger builds:** B8 (L), B13 (L), B15 (L), B1 (L, doc). Everything else is S/M.

## Decisions to make (human, before building)

1. **Does `--under` change the exit code, or only presentation?** (B8/B5) The load-bearing P3 call. Demoting contextual overlaps to advisory flips exit 1→0 for the same corpus — SK4-style "don't blindly obey exit 1" achieved by breaking the contract rather than by typing findings. Recommendation from the grounding: keep exit relaxation agent-side (read buckets, ignore exit), leaving decree's exit contract intact.
2. **Is path classification path-only (deterministic, reproducible) or allowed to read working-tree headers** (`_is_generated_artifact`)? (B7) Path-only is weaker but index-reproducible; header-sniffing is nondeterministic vs checkout state. Also: is "corpus" defined by config type dirs, by the `decisions` table, or both? B7 is consumed only by B6.
3. **`--under` already exists — it is NOT new.** It threads through CLI/MCP and errors→exit 2 today; it only lacks the decision-relative reframe. Guidance and the SPEC must not describe B8's output as if the flag is greenfield.
4. **Do the new buckets duplicate the flat arrays or eventually replace them?** (B3) Duplicate/parallel for at least one release (additive-safe); deprecating the flat lists needs a version bump + pinning guidance (`json-contracts.md:98-108`).
5. **Are the lifecycle-drift and broad-governance signals advisory or exit-1 findings?** (B9-B13, B11) CI6 buckets "complete but draft" under "clean later," implying advisory/exit 0 — confirm, since it decides `has_findings` membership.
6. **How is a "contradiction" told apart from expected composition-root/broad-governance overlap** without semantic judgment, given the deterministic core? (B8/B12) By decision-level flag or purely by exact-vs-directory match kind?
7. **Reconcile the directory-match divergence:** `why()` treats a slashless `governs:` entry as exact-only; `health._path_covers` treats it as a prefix. (B12) One of them must win before conflict expansion.
8. **Skill copies:** dedupe to one source or keep two guarded by B14's test? And is the existing `decree-governs-suggest` divergence intentional or already drifted?
9. **Is the `progress --changed` base-ref diff real?** (B15) It appears in CLAUDE.md but not the code grounding — verify against `progress.py` before treating it as an existing capability to build B15 on.

## Sources

1. [S1][S2] SARIF v2.1.0 spec (`kind` vs `level`; non-failures structurally non-severe): https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/sarif-v2.1.0-os.html
2. [S3] SARIF tutorials — Basics (ordered error/warning/note level scale): https://github.com/microsoft/sarif-tutorials/blob/main/docs/2-Basics.md
3. [S4] SARIF tutorials — Displaying results in a viewer (`baselineState` 4-state enum, computed across runs): https://github.com/microsoft/sarif-tutorials/blob/main/docs/Displaying-results-in-a-viewer.md
4. [S5] SARIF spec issue #312 (new/absent/updated semantics; why "updated" was added): https://github.com/oasis-tcs/sarif-spec/issues/312
5. [S6] Semgrep diff-aware scanning (two-run set-difference `new = head − base`): https://docs.semgrep.dev/kb/semgrep-ci/trigger-diff-scans-env-var
6. [S7][S8][S9] GitHub CODEOWNERS (co-owner set-union / any-one-satisfies; last-matching-pattern precedence; explicit co-ownership required): https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
7. [S10] log4brains ADR draft status ("you must change it once you reach a decision"): https://thomvaill.github.io/log4brains/adr/
