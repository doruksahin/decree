"""`decree mcp serve` — MCP (Model Context Protocol) server exposing decree's
query API as agent-callable tools.

This is the thin protocol layer described by SPEC-01KT22NMRYJ4482K92AX9GJTMA. It wraps the library
functions shipped in SPEC-01KT22NMRXWCS5TK5VC1FT6JER (`commands.queries.why` / `commands.queries.refs`)
behind FastMCP's stdio transport. No new query logic lives here — only:

  1. project-root resolution (mirrors `commands.queries._resolve_root`),
  2. error-shaped responses for missing/stale indexes,
  3. CLI <-> JSON shape preservation so agents and `--json` consumers see one
     identical schema,
  4. **the LLM-facing docstrings**, which are the actual product of this SPEC.

Each tool docstring follows the 5-section structure mandated by SPEC-01KT22NMRYJ4482K92AX9GJTMA:
summary / Args / Returns / When to call / When not to call.

The tool set covers governed-file lookup (`why`, `refs`), coherence signals
(`stale`, `health`), pre/post-code governance (`intent_check` — including
parallel-session `other_active_files` → `live_conflicts` — and `intent_review`),
and closeout (`progress`, `report`). New tools wrap existing command-core
library functions; no duplicate query logic lives here.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from decree.commands.queries import refs as _refs_lib
from decree.commands.queries import why as _why_lib
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info

# ── Module-level FastMCP server ─────────────────────────────
#
# Tools are registered at module import time. The server runs against a single
# project, resolved at `mcp_serve_run` time and stashed in the module-level
# `_PROJECT_ROOT` slot. The tool functions read from there on each call.

mcp = FastMCP("decree")

_PROJECT_ROOT: Path | None = None


def _set_project_root(root: Path) -> None:
    """Set the project root the tool functions read from on each call.

    Exposed mainly so tests can drive the server without going through the CLI.
    """
    global _PROJECT_ROOT
    _PROJECT_ROOT = root


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root — explicit `--project` wins, else cwd-walk.

    Mirrors `commands.queries._resolve_root` and `index_db_cli._resolve_root`.
    """
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return get_project_root()


def _get_db(project_path: Path | None = None) -> tuple[IndexDB, Path]:
    """Resolve the project root and return (IndexDB, root).

    Index existence is NOT checked here — callers must inspect `db.status()`
    so they can return a structured error response rather than throw.
    """
    root = project_path if project_path is not None else _PROJECT_ROOT
    if root is None:
        # cwd-walk fallback (matches CLI behavior when --project is omitted)
        root = _resolve_root(None)

    db = IndexDB(default_db_path(root))
    return db, root


def _index_missing_response() -> dict:
    """Structured error response when the SQLite index doesn't exist."""
    return {
        "error": "index not found",
        "hint": "Run `decree index rebuild` to build the index, then retry.",
    }


def _stale_index_response(db: IndexDB, root: Path) -> dict | None:
    """Return a structured error if the index is stale, else None."""
    findings = db.verify(root)
    real_drift = [f for f in findings if f.kind != "index_missing"]
    if real_drift:
        return {
            "error": "index stale",
            "drift_findings": len(real_drift),
            "hint": "Run `decree index rebuild` before querying.",
        }
    return None


# ── Tools ────────────────────────────────────────────────────


@mcp.tool()
def why(path: str, with_abstention: bool = False) -> dict:
    """Return the decisions (PRDs / ADRs / SPECs) that govern a file or directory.

    Use this BEFORE modifying any source file you did not author. The response
    tells you which decision documents declare authority over that path via
    their `governs:` frontmatter — the constraints, rationale, and history you
    need to respect (or formally supersede) before changing the code.

    Args:
        path: Repo-relative file or directory path (e.g. `src/decree/index_db.py`,
            `src/decree/`). May optionally be suffixed with `#symbol`
            (e.g. `src/foo.py#MyClass`); the symbol is preserved on each result
            row but does not affect ranking in v1. Absolute paths and paths
            with leading `./` are accepted but normalized.
        with_abstention: If True (default False), route through the SPEC-01KT22NMS0VWCTYPFPHP8M8V36
            calibrated retrieval method (`keyword-v1-calibrated`). When the
            composite confidence gate falls below its calibrated threshold,
            the response includes `abstained: True` plus a `signals` map and
            the `would_have_returned` list. Use this when you'd rather see
            "no governance found" than a low-confidence guess.

    Returns:
        A dict with the same shape as `decree why <path> --json`:

            {
              "query": str,                      # the path as queried
              "match_count": int,                # number of governing decisions
              "matches": [
                {
                  "decision_id": str,            # e.g. "SPEC-01KT22NMRYJ4482K92AX9GJTMA"
                  "type": str,                   # "prd" | "adr" | "spec"
                  "status": str,                 # "implemented", "accepted", ...
                  "date": str,                   # ISO date from frontmatter
                  "title": str,
                  "match_kind": "exact" | "prefix",
                  "matched_path": str,           # the path entry that matched
                  "symbol": str | None,
                },
                ...
              ],
            }

        When ``with_abstention=True`` and the calibrator vetoes the answer,
        additional keys are merged into the same dict:

            {
              "abstained": True,
              "composite_score": float,
              "threshold": float,
              "signals": {"dominance": 1.0, "coverage": 0.1, ...},
              "would_have_returned": ["SPEC-01KT22NMRYJ4482K92AX9GJTMA", ...],
              "abstention_reason": str,
            }

        Empty `matches` is a valid, correct answer — it means *no* decision
        currently governs the path. Do NOT confabulate a match; abstention is
        the right behavior when the index says nothing.

        On a stale index the response is
        `{"error": "index stale", "hint": "Run `decree index rebuild`"}`.
        On a missing index the response is
        `{"error": "index not found", "hint": "Run `decree index rebuild`"}`.

    When to call:
        - Before editing a source file or directory whose history/intent you
          don't already know. The response surfaces the governance constraints.
        - When investigating a bug or unexpected behavior: `why` tells you
          which decisions the implementation is supposed to honor.
        - When planning a refactor that touches code authored by a SPEC — you
          must either honor the SPEC's invariants or supersede it.

    When not to call:
        - On test files, fixtures, or generated artifacts — `governs:` targets
          *source* files, not their tests.
        - As a general "what does this code do?" lookup — this is a *decision*
          query, not a code-comprehension tool. Use the CLI's grep or your
          editor's go-to-definition for that.
        - In a tight per-line loop — call once per *path*, not per character.
    """
    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()

    stale = _stale_index_response(db, root)
    if stale is not None:
        return stale
    matches = _why_lib(db, path)

    payload: dict = {
        "query": path,
        "match_count": len(matches),
        "matches": [
            {
                "decision_id": m.decision_id,
                "type": m.type,
                "status": m.status,
                "date": m.date,
                "title": m.title,
                "match_kind": m.match_kind.value,
                "matched_path": m.matched_path,
                "symbol": m.symbol,
            }
            for m in matches
        ],
    }
    if with_abstention:
        from decree.commands.queries import _calibrated_assess

        try:
            abstention = _calibrated_assess(db, kind="file_path", text=path)
        except Exception as e:
            return {
                "error": "calibrated abstention unavailable",
                "detail": str(e),
                "hint": "Run `decree retrieval-eval --calibrate` before using with_abstention.",
            }
        if abstention is not None:
            payload.update(abstention)
    return payload


@mcp.tool()
def refs(decision_id: str, with_abstention: bool = False) -> dict:
    """Return the full reference graph for a single decision document.

    Use this when you have a decision ID in hand (from `why`, a commit
    trailer, a doc cross-reference, or the user) and need to understand its
    surroundings: what it depends on, what depends on it, its supersedes
    chain, the files it governs, and the commits that implemented it.

    Args:
        decision_id: The decision identifier, exactly as it appears in
            frontmatter and filenames, for example `SPEC-01KT22NMRYJ4482K92AX9GJTMA`.
            Case-sensitive; the canonical form is uppercase `TYPE-ULID`.
        with_abstention: If True (default False), first run the SPEC-01KT22NMS0VWCTYPFPHP8M8V36
            calibrated retrieval method against the decision id as a concept
            query. If the composite confidence falls below the calibrated
            threshold, the response returns an abstention shape instead of
            the full reverse-graph payload — same intent as ``why``'s flag.

    Returns:
        A dict with the same shape as `decree refs <decision_id> --json`:

            {
              "decision_id": str,
              "metadata": {
                "decision_id": str, "type": str, "status": str,
                "title": str, "date": str, "body_hash": str,
              },
              "forward_refs":     [{"from_id": str, "to_id": str, "kind": str}, ...],
              "reverse_refs":     [{"from_id": str, "to_id": str, "kind": str}, ...],
              "supersedes_chain": [str, ...],   # ordered, oldest -> newest
              "governs":          [{"path": str, "symbol": str, "order_index": int}, ...],
              "commits":          [{"sha": str, "trailer_kind": str,
                                    "summary": str, "committed_at": str}, ...],
            }

        On an unknown decision id the response is
        `{"error": "unknown decision id", "decision_id": "..."}`.
        On a missing index the response is
        `{"error": "index not found", "hint": "Run `decree index rebuild`"}`.
        On a stale index the response is
        `{"error": "index stale", "hint": "Run `decree index rebuild`"}`.

        When ``with_abstention=True`` and the calibrator vetoes the answer,
        the dict has the abstention shape ``{"decision_id": str,
        "abstained": True, "composite_score": float, "threshold": float,
        "signals": {...}, "would_have_returned": [...]}``.

    When to call:
        - After `why` returned a match and you want to drill into the
          governing decision: pull its references, see what supersedes it,
          and check which commits already touch it.
        - When you're about to mark a decision as superseded — first call
          `refs` on it to surface every dependent that needs updating.
        - When triaging "is this decision still live?" — the supersedes_chain
          and commits arrays answer that quickly.

    When not to call:
        - To list *all* decisions of a type — use the `decree index regenerate`
          markdown indexes or query the SQLite db directly. `refs` is per-ID.
        - To search by title or content — `refs` only accepts the exact ID.
          If you don't have the ID, start with `why` against a relevant path.
        - On every iteration of a graph walk — the result already contains
          forward_refs and reverse_refs; cache, don't re-fetch.
    """
    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()

    stale = _stale_index_response(db, root)
    if stale is not None:
        return stale

    if with_abstention:
        from decree.commands.queries import _calibrated_assess

        try:
            abstention = _calibrated_assess(db, kind="concept", text=decision_id)
        except Exception as e:
            return {
                "error": "calibrated abstention unavailable",
                "detail": str(e),
                "hint": "Run `decree retrieval-eval --calibrate` before using with_abstention.",
            }
        if abstention is not None and abstention.get("abstained"):
            payload: dict = {"decision_id": decision_id, **abstention}
            return payload

    report = _refs_lib(db, decision_id)
    if report is None:
        return {
            "error": "unknown decision id",
            "decision_id": decision_id,
        }

    payload = {
        "decision_id": report.decision_id,
        "metadata": asdict(report.metadata),
        "forward_refs": [asdict(r) for r in report.forward_refs],
        "reverse_refs": [asdict(r) for r in report.reverse_refs],
        "supersedes_chain": list(report.supersedes_chain),
        "governs": [asdict(g) for g in report.governs],
        "commits": [asdict(c) for c in report.commits],
    }
    return payload


# ── CLI handler ──────────────────────────────────────────────


@mcp.tool()
def stale(threshold_commits: int = 10) -> dict:
    """Return decisions whose governed files have churned without the decision being touched.

    A *stale decision* is one whose `governs:` paths have accumulated more
    than `threshold_commits` commits since the decision document itself
    was last modified. The classic failure mode this catches: an ADR or
    SPEC describing API/design constraints whose implementation files
    have moved on without the decision being revisited or superseded.

    Args:
        threshold_commits: Minimum total post-decision commit count
            across all governed paths to flag a decision as stale.
            Defaults to 10. Lower it to surface more candidates (useful
            for triage); raise it to focus only on the worst offenders.

    Returns:
        A dict with the same shape as `decree health --json` restricted
        to the stale-decisions section:

            {
              "stale_decisions": [
                {
                  "decision_id": str,            # e.g. "SPEC-01KT22NMRYNFYM7EN80WS2HD6F"
                  "type": str,                   # "prd" | "adr" | "spec"
                  "last_touched_ts": int,        # unix seconds, -1 if unknown
                  "churn_count": int,            # total commits across governed paths
                  "governed_paths": [
                    {"path": str, "count": int}, ...
                  ],
                },
                ...
              ],
              "threshold_commits": int,
            }

        Empty `stale_decisions` is a valid answer — the corpus is
        currently in sync with its governed files. On a non-git project
        or missing index the response is
        `{"error": "<reason>", "hint": "..."}`.

    When to call:
        - During triage / sprint planning: "which decisions are most
          out-of-sync with what the code is doing now?"
        - Before re-implementing or replacing a subsystem: see whether
          its governing decision is already drifting.
        - Periodically (e.g., weekly) to surface ADRs/SPECs that need
          remediation or supersession.

    When not to call:
        - To check a single file's governance — use `why` instead.
        - On every commit — this walks `git log` for every governed path
          and is O(decisions x governs). Cache the result if needed.
        - On a non-git project — staleness needs commit history.
    """
    from decree.commands.health import _is_git_repo
    from decree.commands.health import stale_decisions as _stale_lib

    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()
    if not _is_git_repo(root):
        return {
            "error": "not a git repository",
            "hint": "decree stale needs git history; initialize the project as a git repo first.",
        }

    findings = _stale_lib(db, root, threshold_commits)
    return {
        "stale_decisions": [
            {
                "decision_id": sd.decision_id,
                "type": sd.type,
                "last_touched_ts": sd.last_touched_ts,
                "churn_count": sd.churn_count,
                "governed_paths": [{"path": p, "count": c} for (p, c) in sd.governed_paths],
            }
            for sd in findings
        ],
        "threshold_commits": threshold_commits,
    }


@mcp.tool()
def health(threshold_commits: int = 10, threshold_days: int = 30) -> dict:
    """Return the full coherence health report: stale decisions, ungoverned hotspots, and governance drift.

    Combines four git-derived coherence signals into one response (the two
    PRD-01KT22NMRS4QGHSFDBZ858PP1T R7 signals — stale and ungoverned — plus the
    two governance-drift signals):

      1. **Stale decisions** — same as `stale`: decisions whose
         `governs:` paths have churned by >`threshold_commits` commits
         since the decision document was last touched.
      2. **Ungoverned hotspots** — files modified more than
         `threshold_commits` times in the last `threshold_days` days
         with **no** governing decision in the index. The Repowise
         inversion: instead of waiting for an ADR author to volunteer,
         the tool surfaces *where* a decision is missing.
      3. **Dead governance** — declared `governs:` paths no trailer-linked
         commit has ever touched (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D); the
         high-precision drift signal, counted as a finding.
      4. **Suggested governance** (advisory) — files a decision's own commits
         repeat-touch (>=2 commits) but it does not declare and nobody owns
         (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ). Advisory only: surface it as a
         hint to extend `governs:`, never as a governance fact — `why` never
         reads it, and it never affects coherence exit status.

    Args:
        threshold_commits: Minimum commit count to flag either a stale
            decision (total post-decision churn) or an ungoverned hotspot
            (commits in the lookback window). Defaults to 10.
        threshold_days: Lookback window (in days) for the ungoverned
            hotspot scan. Defaults to 30. Does not affect stale
            detection (which uses each decision's own last-touched
            timestamp).

    Returns:
        A dict with the same shape as `decree health --json`:

            {
              "stale_decisions": [
                {"decision_id": str, "type": str,
                 "last_touched_ts": int, "churn_count": int,
                 "governed_paths": [{"path": str, "count": int}, ...]},
                ...
              ],
              "ungoverned_hotspots": [
                {"path": str, "commit_count": int, "since_days": int},
                ...
              ],
              "dead_governance": [
                {"decision_id": str, "paths": [str, ...],
                 "linked_commit_count": int}, ...
              ],
              "missing_governance": [
                {"decision_id": str, "linked_commit_count": int,
                 "observed_path_count": int,
                 "candidates": [{"path": str, "commit_count": int,
                                 "distinct_decisions": int}, ...]}, ...
              ],
              "unobserved_decisions": [str, ...],
              "observed_as_of": str | null,
              "threshold_commits": int,
              "threshold_days": int,
            }

        Empty findings arrays mean the corpus is in coherence with the
        codebase at the given thresholds; `missing_governance` is advisory and
        does not imply incoherence. On a non-git project or missing index the
        response is `{"error": "<reason>", "hint": "..."}`.

    When to call:
        - As a periodic health check: "where is decree governance
          drifting?" Surfaces both decisions in need of update and code
          paths that need an ADR/SPEC written for them.
        - Before a roadmap planning meeting: ungoverned hotspots are
          the natural ADR backlog.
        - When investigating a recurring bug area: the file may be an
          ungoverned hotspot — write the ADR before patching again.

    When not to call:
        - Per-file lookups — use `why` instead.
        - On every keystroke — this walks `git log` twice (decisions and
          hotspots). Run on demand, not on every save.
        - As a substitute for `lint` — health surfaces *coherence*
          signals, not malformed documents.
    """
    from decree.commands.health import _is_git_repo, _report_to_dict
    from decree.commands.health import health as _health_lib

    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()
    if not _is_git_repo(root):
        return {
            "error": "not a git repository",
            "hint": "decree health needs git history; initialize the project as a git repo first.",
        }

    # Serialize through the CLI's own formatter so this payload and
    # `decree health --json` never diverge — dead governance
    # (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D) and suggested/missing governance
    # (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ) reach agents via the same shape.
    report = _health_lib(db, root, threshold_commits, threshold_days)
    return _report_to_dict(report)


@mcp.tool()
def intent_review(diff: str | None = None, changed_paths: list[str] | None = None, under: str | None = None) -> dict:
    """Diff-aware governance report — what decisions does this change affect?

    Given a unified diff (or an explicit list of changed paths), return a
    structured report stitching every prior decree query into one view:
    which decisions govern the changed paths, which of those are stale,
    which acceptance criteria look affected, which decisions structurally
    conflict over the same files, and what to do about it.

    Args:
        diff: Unified diff content (string). Optional if `changed_paths`
            is given. When parsed, the post-image path of each file is
            captured (renames and additions included); deleted files are
            skipped.
        changed_paths: List of repo-relative paths the change touches.
            Optional if `diff` is given; if both are present, `changed_paths`
            wins (caller is expected to know the diff's contents).
        under: Optional id of the decision this governed session works under.
            When a changed file is one that decision's own commits repeat-touch
            (>=2 commits) but it doesn't declare, the response adds an advisory
            `governs_gaps` list and a `declare_governs` recommendation
            (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5). Pass deletion-free paths. An
            unknown id sets `under_error`. Defaults to None.

    Returns:
        A dict with the same shape as `decree intent-review --json`:

            {
              "changed_paths": [str, ...],
              "governing_decisions": [
                {"decision_id": str, "type": str, "status": str,
                 "title": str, "match_kind": "exact"|"prefix",
                 "matched_path": str, "symbol": str | None},
                ...
              ],
              "stale_governance": [
                {"decision_id": str, "type": str,
                 "last_touched_ts": int, "churn_count": int,
                 "governed_paths": [{"path": str, "count": int}, ...]},
                ...
              ],
              "unchecked_acceptance_criteria": [
                {"decision_id": str, "section_title": str,
                 "text": str, "order_index": int},
                ...
              ],
              "conflicts": [
                {"path": str, "decision_ids": [str, ...]},
                ...
              ],
              "recommended_actions": [
                {"action": str, "target_id": str | None, "detail": str},
                ...
              ],
            }

        Empty arrays are valid responses (abstention; do not confabulate).
        On a missing index the response is
        `{"error": "index not found", "hint": "Run `decree index rebuild`"}`.

    When to call:
        - Before authoring a commit on a feature branch — get the
          governance map so the commit message can reference relevant
          decisions and link to the right SPEC.
        - When reviewing a PR — surface conflicts and stale governance
          before approving.
        - Pre-merge — verify no governing decision contradicts the
          change and no in-flight AC is silently un-finished.

    When not to call:
        - On documentation-only changes (`decree/`, `docs/`) — surfaces
          nothing useful.
        - On test-only diffs — `governs:` is source-file scoped.
        - For pre-PR planning intent ("I plan to do X") — that's a
          different tool (`intent_check`, PRD-01KT22NMRSXYT95XE808VD8EV4 R2; not yet implemented).
    """
    from decree.commands.intent_review import (
        intent_review as _intent_review_lib,
    )
    from decree.commands.intent_review import (
        parse_diff,
        report_to_dict,
    )

    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()

    stale = _stale_index_response(db, root)
    if stale is not None:
        return stale

    if changed_paths is not None:
        paths = list(changed_paths)
    elif diff is not None:
        paths = parse_diff(diff)
    else:
        paths = []

    # `under` (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5): when a governed session passes the
    # decision it works under, the payload adds `governs_gaps` — changed files that
    # decision's own commits repeat-touch but it doesn't declare (advisory; the
    # caller is expected to pass deletion-free `changed_paths`/`diff`).
    report = _intent_review_lib(db, root, paths, under=under)
    payload = report_to_dict(report)
    return payload


@mcp.tool()
def intent_check(
    plan: str,
    planned_files: list[str],
    with_abstention: bool = False,
    other_active_files: dict[str, list[str]] | None = None,
    under: str | None = None,
) -> dict:
    """Pre-code governance check — what decisions apply to your plan?

    Call this BEFORE writing code on a non-trivial task. You describe what
    you intend to build and which files the plan will touch; the tool
    returns the governance map *now*, so you can resolve conflicts and
    update stale decisions before any line of implementation lands.

    This is the planning-phase counterpart of `intent_review` (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6).
    `intent_review` runs against a diff; `intent_check` runs against a
    plan + planned file list.

    Args:
        plan: One-sentence to one-paragraph description of what you intend
            to build. Used for the architectural-keyword heuristic that
            triggers `draft_adr_first`.
        planned_files: List of repo-relative paths the plan will create or
            modify. Required, must be non-empty in practice (an empty list
            collapses to a `proceed` recommendation).
        with_abstention: If True (default False), route the governance
            lookups through SPEC-01KT22NMS0VWCTYPFPHP8M8V36's calibrated retrieval method. When
            all paths return empty governance the response includes an
            `abstention` block with signals and threshold so the caller
            can see *why* the calibrator deflected.
        other_active_files: Optional mapping of *session id → paths that
            session is currently planning to write*, e.g.
            `{"session-b": ["src/app/Canvas.tsx"]}`. decree does not track
            session state; pass the claimed paths of other concurrently-running
            agent sessions and the response's `live_conflicts` will list every
            planned file another active session is also about to touch. Defaults
            to None (single-session mode — `live_conflicts` is empty).
        under: Optional id of the decision this governed session works under.
            When a planned file is one that decision's own commits repeat-touch
            (>=2 commits) but it doesn't declare, the response adds an advisory
            `governs_gaps` list and a `declare_governs` recommendation
            (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5). An unknown id sets `under_error`.
            Advisory: never changes governance facts. Defaults to None.

    Returns:
        A dict with the same shape as `decree intent-check --json`:

            {
              "plan": str,
              "planned_files": [str, ...],
              "governing_decisions": [
                {"decision_id": str, "type": str, "status": str,
                 "title": str, "match_kind": "exact"|"prefix",
                 "matched_path": str, "symbol": str | None},
                ...
              ],
              "stale_governance": [
                {"decision_id": str, "type": str,
                 "last_touched_ts": int, "churn_count": int,
                 "governed_paths": [{"path": str, "count": int}, ...]},
                ...
              ],
              "unchecked_acceptance_criteria": [
                {"decision_id": str, "section_title": str,
                 "text": str, "order_index": int},
                ...
              ],
              "conflicts": [
                {"path": str, "decision_ids": [str, ...],
                 "semantic_verdict": {"is_real_conflict": bool,
                                       "reasoning": str} | None},
                ...
              ],
              "live_conflicts": [
                {"path": str, "session_ids": [str, ...]},
                ...
              ],
              "abstention": {"abstained": bool, "composite_score": float,
                             "threshold": float, "signals": {...},
                             ...} | None,
              "recommended_actions": [
                {"action": str, "target_id": str | None, "detail": str},
                ...
              ],
            }

        Recommendation `action` strings (planning-phase verbs):
        `proceed`, `add_governance`, `draft_adr_first`, `update_spec_first`,
        `check_ac`, `update_decision`, `resolve_conflict_first`,
        `isolate_session` (emitted per `live_conflicts` entry).

        `conflicts` is governance-level (multiple decisions claim one path);
        `live_conflicts` is operational (another running session plans the same
        path) and is non-empty only when `other_active_files` was supplied.

        Empty arrays are valid responses (abstention; do not confabulate).
        On a missing index the response is
        `{"error": "index not found", "hint": "Run `decree index rebuild`"}`.
        On a stale index the response is
        `{"error": "index stale", "hint": "Run `decree index rebuild`"}`.

    When to call:
        - At the *start* of an implementation task, before writing any
          code. The response tells you what existing decisions constrain
          your plan and whether a fresh ADR is needed first.
        - When a user gives you a task and you're forming a plan — call
          this to see what the corpus already says about the affected
          files.
        - Before opening a feature branch — quick sanity check.

    When not to call:
        - For trivial refactors or documentation-only changes (the
          ceremony exceeds the value).
        - *After* code is written — that's `intent_review` (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6),
          not this. The two tools complement each other.
        - For exploratory code not intended to be merged.
    """
    from decree.commands.intent_check import (
        intent_check as _intent_check_lib,
    )
    from decree.commands.intent_check import (
        report_to_dict,
    )

    db, root = _get_db()
    status = db.status()
    if not status.exists:
        return _index_missing_response()

    stale = _stale_index_response(db, root)
    if stale is not None:
        return stale

    # `under` (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5): the governed session's decision.
    # When a planned file is one that decision's own commits repeat-touch but it
    # doesn't declare, the payload adds an advisory `governs_gaps` + a
    # `declare_governs` recommendation. `under_error` is set for an unknown id.
    report = _intent_check_lib(
        db,
        root,
        plan,
        list(planned_files or []),
        with_abstention=with_abstention,
        other_active_files=other_active_files or None,
        under=under,
    )
    return report_to_dict(report)


@mcp.tool()
def progress(doc_id: str | None = None, chain_id: str | None = None) -> dict:
    """Acceptance-criteria completion for a decision, a chain, or the whole corpus.

    Counts the primary and deferred `- [x]` / `- [ ]` checkboxes a SPEC (or any
    decision) declares, so you can measure *objective* progress instead of
    trusting a "looks done" self-report. The natural closeout signal: snapshot
    the governing SPEC before a coding session, call again after, and compare —
    a SPEC that went 0/36 → 11/36 is partially done, not implemented.

    Args:
        doc_id: Restrict to a single document id, e.g.
            `SPEC-01KT22NMRWENYKC3MGRA50M7GE`. Wins over `chain_id` if both set.
        chain_id: Restrict to every document transitively connected to this id
            (its PRD → ADR → SPEC chain). Omit both to score the whole corpus.

    Returns:
        A dict with the same counts as `decree progress` (no stdout):

            {
              "scope": str,                 # "doc <id>" | "chain <id>" | "all documents"
              "document_count": int,
              "primary":  {"done": int, "total": int, "percent": int | None},
              "deferred": {"done": int, "total": int},
              "documents": [
                {"doc_id": str, "title": str, "status": str,
                 "primary": {"done": int, "total": int, "percent": int | None},
                 "deferred": {"done": int, "total": int}},
                ...
              ],
            }

        On an unknown id the response is
        `{"error": "document not found: <id>", "hint": "..."}`.

    When to call:
        - At session closeout, to verify the work actually advanced the SPEC's
          acceptance criteria before marking anything complete.
        - When deciding whether a SPEC is safe to transition to `implemented`.
        - To report parallel-work progress scoped to one chain.

    When not to call:
        - As a substitute for reading the SPEC — this counts checkboxes, it does
          not judge whether the implementation is correct.
        - On every keystroke — call at meaningful boundaries (start/end of work).
    """
    from decree.commands.progress import progress_for_scope

    # progress reads documents from disk via the parser (not the SQLite index),
    # so there is no index check — a bad id is the only expected error.
    try:
        return progress_for_scope(doc_id=doc_id or None, chain_id=chain_id or None)
    except ValueError as e:
        return {"error": str(e), "hint": "Pass a valid TYPE-ULID document id."}
    except Exception as e:  # pragma: no cover - defensive boundary
        return {"error": "progress failed", "detail": str(e)}


@mcp.tool()
def report(
    doc_ids: list[str] | None = None,
    all_terminal: bool = False,
    dry_run: bool = False,
) -> dict:
    """Regenerate completion-report artifacts for finished decisions (closeout evidence).

    Writes the per-decision completion report markdown that turns a finished
    SPEC into an auditable artifact tied to its acceptance criteria — the
    handoff document a reviewer or release note can cite. This is the one MCP
    tool that *writes files*; pass `dry_run=True` to preview what would be
    written without touching disk.

    Args:
        doc_ids: Explicit list of decision ids to regenerate reports for, e.g.
            `["SPEC-01KT22NMRWENYKC3MGRA50M7GE"]`. The common closeout call.
        all_terminal: If True, regenerate for every decision currently in a
            terminal-success status (bulk refresh). Ignored when `doc_ids` is
            given.
        dry_run: If True (default False), compute and return what *would* be
            written without creating or modifying any file.

    Returns:
        A dict summarizing the regeneration:

            {
              "dry_run": bool,
              "total": int,
              "written":     [{"doc_id": str, "path": str}, ...],
              "would_write": [{"doc_id": str, "path": str}, ...],   # dry-run only
              "skipped":     [{"doc_id": str, "reason": str}, ...],
            }

    When to call:
        - At session closeout, after `progress` confirms a SPEC is complete, to
          emit its completion report as reviewable evidence.
        - To bulk-refresh reports after a batch of decisions reached a terminal
          status (`all_terminal=True`).

    When not to call:
        - On in-progress decisions — reports are for terminal-success docs; a
          partial SPEC will be reported as `skipped`.
        - As a read-only query — this writes files. Use `progress` to *measure*
          completion without emitting an artifact.
    """
    from decree.commands.report import regenerate_reports

    root = _PROJECT_ROOT if _PROJECT_ROOT is not None else _resolve_root(None)
    try:
        results = regenerate_reports(
            root,
            doc_ids=tuple(doc_ids or ()),
            all_terminal=bool(all_terminal),
            existing_only=False,
            dry_run=bool(dry_run),
        )
    except Exception as e:  # pragma: no cover - defensive boundary
        return {"error": "report regeneration failed", "detail": str(e)}

    return {
        "dry_run": bool(dry_run),
        "total": len(results),
        "written": [
            {"doc_id": r.doc_id, "path": str(r.path) if r.path else None} for r in results if r.action == "written"
        ],
        "would_write": [
            {"doc_id": r.doc_id, "path": str(r.path) if r.path else None} for r in results if r.action == "would_write"
        ],
        "skipped": [{"doc_id": r.doc_id, "reason": r.reason} for r in results if r.action == "skipped"],
    }


def mcp_serve_run(args: argparse.Namespace) -> int:
    """`decree mcp serve` — enter the FastMCP stdio loop bound to a project."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error("mcp", str(e))
        return 1

    # Chdir so library code that walks from cwd picks the right project
    import os

    os.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    _set_project_root(root)

    # Surface index status at startup but never refuse to start — per-call
    # tools will return structured errors if the index is missing/stale.
    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        info(
            "mcp",
            "index not found; tools will return error responses until `decree index rebuild` is run",
        )

    mcp.run()
    return 0
