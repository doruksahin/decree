"""`decree intent-check` — pre-PR planning-phase governance report.

Implements PRD-01KT22NMRSXYT95XE808VD8EV4 R2 (SPEC-01KT22NMS0KTWGNKB36RR7K0JR). The post-code counterpart, ``decree
intent-review`` (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6), takes a diff and asks "what does this change
intersect with?". This module is the *planning-phase* counterpart: a caller
says "I'm going to build X and touch these files", and we return the
governance map *before* any code is written.

The implementation is mostly composition of existing helpers — same trick
SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 used:

  * ``commands.queries.why`` (SPEC-01KT22NMRXWCS5TK5VC1FT6JER) for governance lookup.
  * ``commands.queries._calibrated_assess`` (SPEC-01KT22NMS0VWCTYPFPHP8M8V36) for optional
    calibrated abstention when no governance is found and the caller
    passed ``--with-abstention``.
  * ``commands.health.stale_decisions`` (SPEC-01KT22NMRYNFYM7EN80WS2HD6F) for stale intersection.
  * Acceptance-criteria SQL identical to SPEC-01KT22NMRYRZQ59EC88VJ5R0N6's.

The dataclasses are reused from SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 wherever the shape is the same.
``IntentCheckReport`` is the new top-level container; ``Conflict`` from
SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 keeps its optional ``semantic_verdict`` field
for schema compatibility, but core intent-check does not call LLM providers.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from decree.commands.health import stale_decisions
from decree.commands.intent_review import (
    Conflict,
    GoverningSnapshot,
    GovernsGap,
    Recommendation,
    UncheckedAC,
    _governing_snapshot_from,
    _stale_decision_to_dict,
    compute_governs_gaps,
)
from decree.commands.queries import _calibrated_assess, why
from decree.config import classify_path, load_doc_types
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info

# ── Public dataclass ────────────────────────────────────────


@dataclass(frozen=True)
class LiveSessionConflict:
    """A planned path also claimed by another *currently-active* agent session.

    Distinct from ``Conflict``, which is governance-level (multiple *decisions*
    claim one path). This is operational: two live sessions plan to write the
    same file *right now*. decree does not track session state itself — the
    caller passes the paths claimed by other active sessions via
    ``other_active_files`` and decree computes the overlap, so the "is anyone
    else touching this?" answer lives in the same report as the governance map.
    """

    path: str
    session_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntentCheckReport:
    """Top-level pre-code governance report.

    Mirrors SPEC-01KT22NMRYRZQ59EC88VJ5R0N6's ``IntentReport`` shape with planning-phase deltas:
    ``planned_files`` instead of ``changed_paths``, ``plan`` surfaced for
    semantic context, ``abstention`` populated when the calibrated method
    vetoes (SPEC-01KT22NMS0VWCTYPFPHP8M8V36), and the ``recommended_actions`` verbs expanded to
    pre-code phase (``draft_adr_first``, ``update_spec_first``,
    ``resolve_conflict_first``, ``proceed``) plus the SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 reuse set.
    """

    plan: str
    planned_files: tuple[str, ...]
    governing_decisions: tuple[GoverningSnapshot, ...]
    stale_governance: tuple[dict, ...]
    unchecked_acceptance_criteria: tuple[UncheckedAC, ...]
    conflicts: tuple[Conflict, ...]
    abstention: dict | None
    recommended_actions: tuple[Recommendation, ...]
    # Operational overlap with other live sessions (opt-in via ``other_active_files``).
    # Empty unless the caller passes the paths claimed by concurrently-running sessions.
    live_conflicts: tuple[LiveSessionConflict, ...] = ()
    # Point-of-change governs gaps for an active `under` decision (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5).
    under_decision: str | None = None
    under_error: str | None = None
    governs_gaps: tuple[GovernsGap, ...] = ()
    # Planned files partitioned by kind (SPEC-01KWXMRR7R3S5CSAAZRGFHR5QN / backlog B6):
    # a decree-document self-edit (``corpus``) or a decree-generated artifact
    # (``generated``) is not ungoverned source, so it never earns ``add_governance``.
    source_changes: tuple[str, ...] = ()
    corpus_changes: tuple[str, ...] = ()
    generated_artifact_changes: tuple[str, ...] = ()
    # Directory-prefix overlaps (backlog B12): paths co-governed via a directory
    # `governs:` entry that the exact-path conflict query cannot see. Advisory.
    directory_overlaps: tuple[dict, ...] = ()
    # Decision-relative framing when `--under` is given (backlog B8). Empty otherwise.
    owned_files: tuple[str, ...] = ()
    contextual_overlaps: tuple[dict, ...] = ()
    contradictions: tuple[dict, ...] = ()


# ── Internal helpers ────────────────────────────────────────


def _terminal_statuses_for(type_name: str) -> frozenset[str]:
    """Return the set of terminal statuses for a doc type."""
    for dt in load_doc_types():
        if dt.name == type_name:
            return dt.terminal_statuses
    return frozenset()


# Architectural-keyword heuristic for the ``draft_adr_first`` recommendation.
# Case-insensitive substring match against the plan body. Kept small and
# deterministic so unit tests can reason about it.
_ADR_KEYWORDS: tuple[str, ...] = (
    "design",
    "architecture",
    "system",
    "decide",
    "choose between",
)


def _plan_mentions_architecture(plan: str) -> bool:
    """True if the plan contains any of the architecture keywords (case-insensitive)."""
    if not plan:
        return False
    lowered = plan.lower()
    return any(kw in lowered for kw in _ADR_KEYWORDS)


# ── Library: intent_check() ─────────────────────────────────


def intent_check(
    db: IndexDB,
    project_root: Path,
    plan: str,
    planned_files: list[str],
    *,
    with_abstention: bool = False,
    threshold_commits: int = 10,
    other_active_files: dict[str, list[str]] | None = None,
    under: str | None = None,
) -> IntentCheckReport:
    """Compose an ``IntentCheckReport`` for a plan and planned files.

    Stitches the same prior-SPEC primitives SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 used, plus optional
    SPEC-01KT22NMS0VWCTYPFPHP8M8V36 calibrated abstention. Structural conflicts are deterministic;
    provider-backed semantic judging belongs in agent/skill layers.

    ``other_active_files`` is an optional mapping of *session id → paths that
    session is currently planning to write*. decree does not track session
    state itself; when a parallel-agent host (e.g. a canvas of concurrent
    Claude/Codex sessions) passes the other live sessions' claimed paths, the
    report's ``live_conflicts`` surfaces every planned file that another active
    session is also about to touch — the "is anyone else editing this right
    now?" signal that decision-level ``conflicts`` cannot answer.
    """
    # 0. Normalize planned_files: stable order, deduped.
    seen: dict[str, None] = {}
    for p in planned_files or ():
        seen.setdefault(p, None)
    paths = list(seen.keys())

    # 0b. Classify each planned file (path-only, deterministic). A decree
    #     document self-edit (``corpus``) or generated artifact (``generated``)
    #     is not ungoverned source, so it is excluded from ``add_governance``.
    doc_dirs = [dt.dir for dt in load_doc_types()]
    path_class = {p: classify_path(p, doc_dirs) for p in paths}
    source_changes = tuple(p for p in paths if path_class[p] == "source")
    corpus_changes = tuple(p for p in paths if path_class[p] == "corpus")
    generated_artifact_changes = tuple(p for p in paths if path_class[p] == "generated")
    nonsource_paths = {p for p, c in path_class.items() if c != "source"}

    # 1. governing_decisions — dedupe across paths by decision_id.
    govs_by_id: dict[str, GoverningSnapshot] = {}
    path_to_decisions: dict[str, list[str]] = {}
    for path in paths:
        matches = why(db, path)
        path_to_decisions[path] = [m.decision_id for m in matches]
        for m in matches:
            if m.decision_id not in govs_by_id:
                govs_by_id[m.decision_id] = _governing_snapshot_from(m)
    governing_decisions = tuple(govs_by_id.values())

    # 2. unchecked_acceptance_criteria — same SQL as SPEC-01KT22NMRYRZQ59EC88VJ5R0N6.
    conn = db.db.conn  # type: ignore[attr-defined]
    unchecked: list[UncheckedAC] = []
    for snap in governing_decisions:
        terminal = _terminal_statuses_for(snap.type)
        if snap.status in terminal:
            continue
        rows = conn.execute(
            "SELECT decision_id, section_title, text, order_index "
            "FROM acceptance_criteria "
            "WHERE decision_id = ? AND deferred = 0 AND done = 0 "
            "ORDER BY order_index",
            (snap.decision_id,),
        )
        for did, section_title, text, order_index in rows:
            unchecked.append(
                UncheckedAC(
                    decision_id=did,
                    section_title=section_title or "",
                    text=text or "",
                    order_index=int(order_index),
                )
            )

    # 3. stale_governance — full stale list ∩ governing-decision ids.
    governing_ids = set(govs_by_id.keys())
    all_stale = stale_decisions(db, project_root, threshold_commits)
    stale_governance = tuple(_stale_decision_to_dict(sd) for sd in all_stale if sd.decision_id in governing_ids)

    # 4. conflicts — multiple decisions claim the same planned path.
    raw_conflicts: list[Conflict] = []
    if paths:
        placeholders = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT path, GROUP_CONCAT(DISTINCT decision_id) "
            f"FROM governs "
            f"WHERE path IN ({placeholders}) "
            f"GROUP BY path "
            f"HAVING COUNT(DISTINCT decision_id) > 1 "
            f"ORDER BY path",
            tuple(paths),
        )
        for path, ids_blob in rows:
            ids = tuple(sorted({i for i in (ids_blob or "").split(",") if i}))
            if len(ids) > 1:
                raw_conflicts.append(Conflict(path=path, decision_ids=ids))

    # 5. conflicts stay structural-only in core decree. Agent/skill layers may
    #    post-process this JSON if they want semantic conflict judging.
    conflicts: list[Conflict] = list(raw_conflicts)

    # 5b. live_conflicts — planned paths also claimed by other active sessions.
    #     Operational, not governance: decree does not own session state, so the
    #     caller supplies it via ``other_active_files`` and we compute the
    #     overlap here, keeping the "who else is touching this?" answer in the
    #     same report as the governance map.
    live_conflicts: list[LiveSessionConflict] = []
    if other_active_files and paths:
        planned_set = set(paths)
        sessions_by_path: dict[str, set[str]] = {}
        for session_id, session_paths in other_active_files.items():
            for f in session_paths or ():
                if f in planned_set:
                    sessions_by_path.setdefault(f, set()).add(session_id)
        for path in sorted(sessions_by_path):
            live_conflicts.append(
                LiveSessionConflict(
                    path=path,
                    session_ids=tuple(sorted(sessions_by_path[path])),
                )
            )

    # 6. abstention — populated when --with-abstention and all governance
    #    lookups returned nothing. We synthesize a single abstention block
    #    over the planned paths so the caller can see *why* the calibrator
    #    deflected. v1 reports the first planned_file's calibration; if a
    #    caller needs per-path abstention they can call _calibrated_assess
    #    directly.
    abstention: dict | None = None
    if with_abstention and not governing_decisions and paths:
        first_path = paths[0]
        try:
            abstention = _calibrated_assess(db, kind="file_path", text=first_path)
        except Exception as e:
            abstention = {
                "error": "calibrated abstention unavailable",
                "detail": str(e),
                "hint": "Run `decree retrieval-eval --calibrate` before using with_abstention.",
            }

    # 7. recommended_actions — deterministic, derived from the above signals.
    recommendations = _build_recommendations(
        plan=plan,
        paths=paths,
        path_to_decisions=path_to_decisions,
        governing_decisions=governing_decisions,
        stale_ids={s["decision_id"] for s in stale_governance},
        unchecked=unchecked,
        conflicts=conflicts,
        live_conflicts=live_conflicts,
        corpus_or_generated=nonsource_paths,
    )

    # 7b. directory-prefix overlaps (B12) — why() sees a directory `governs:`
    #     governor via prefix, but the exact-path conflict query (step 4) cannot.
    #     Surfaced as advisory context, never as a blocking conflict.
    exact_conflict_paths = {c.path for c in conflicts}
    directory_overlaps = tuple(
        {"path": p, "decision_ids": sorted(set(path_to_decisions.get(p, [])))}
        for p in paths
        if len(set(path_to_decisions.get(p, []))) > 1 and p not in exact_conflict_paths
    )

    # 7c. decision-relative framing when `--under` is given (B8): partition
    #     multi-governed paths into contextual overlaps (the active decision owns
    #     the path; others are context) vs contradictions (a multi-governed path
    #     the active decision does not own).
    owned_files: tuple[str, ...] = ()
    contextual_overlaps: tuple[dict, ...] = ()
    contradictions: tuple[dict, ...] = ()
    if under:
        owned_files = tuple(p for p in paths if under in set(path_to_decisions.get(p, [])))
        multi: dict[str, set[str]] = {c.path: set(c.decision_ids) for c in conflicts}
        for o in directory_overlaps:
            multi.setdefault(o["path"], set()).update(o["decision_ids"])
        ctx: list[dict] = []
        contra: list[dict] = []
        for p in sorted(multi):
            ids = multi[p]
            if under in ids:
                ctx.append({"path": p, "contextual_decision_ids": sorted(ids - {under})})
            else:
                contra.append({"path": p, "decision_ids": sorted(ids)})
        contextual_overlaps = tuple(ctx)
        contradictions = tuple(contra)

    # 8. governs gaps for the active decision (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5) —
    #    appended after _build_recommendations so it stays out of the proceed guard.
    governs_gaps, under_error = compute_governs_gaps(db, under, paths)
    if governs_gaps:
        gap_paths = ", ".join(g.path for g in governs_gaps)
        recommendations = [
            *recommendations,
            Recommendation(
                action="declare_governs",
                target_id=under,
                detail=(
                    f"{under}'s commits repeat-touch {gap_paths}, "
                    f"{'which are' if len(governs_gaps) > 1 else 'which is'} not in its "
                    "`governs:`. Consider declaring it (advisory)."
                ),
            ),
        ]

    return IntentCheckReport(
        plan=plan or "",
        planned_files=tuple(paths),
        governing_decisions=governing_decisions,
        stale_governance=stale_governance,
        unchecked_acceptance_criteria=tuple(unchecked),
        conflicts=tuple(conflicts),
        abstention=abstention,
        recommended_actions=tuple(recommendations),
        live_conflicts=tuple(live_conflicts),
        under_decision=under,
        under_error=under_error,
        governs_gaps=governs_gaps,
        source_changes=source_changes,
        corpus_changes=corpus_changes,
        generated_artifact_changes=generated_artifact_changes,
        directory_overlaps=directory_overlaps,
        owned_files=owned_files,
        contextual_overlaps=contextual_overlaps,
        contradictions=contradictions,
    )


def _build_recommendations(
    *,
    plan: str,
    paths: list[str],
    path_to_decisions: dict[str, list[str]],
    governing_decisions: tuple[GoverningSnapshot, ...],
    stale_ids: set[str],
    unchecked: list[UncheckedAC],
    conflicts: list[Conflict],
    live_conflicts: list[LiveSessionConflict] | None = None,
    corpus_or_generated: set[str] | None = None,
) -> list[Recommendation]:
    """Generate pre-code-phase recommendation verbs from collected signals.

    Verbs (SPEC-01KT22NMS0KTWGNKB36RR7K0JR §recommended_actions):
      * ``proceed`` — no governance, no conflicts, no stale, no unchecked.
      * ``add_governance`` — one per planned file with no governance.
      * ``draft_adr_first`` — no governance AND plan contains an
        architectural keyword. Emitted in addition to ``add_governance``.
      * ``update_spec_first`` — one per governing SPEC with unchecked ACs.
      * ``check_ac`` — one per unchecked AC (informational; mirrors SPEC-01KT22NMRYRZQ59EC88VJ5R0N6).
      * ``update_decision`` — one per stale governance entry.
      * ``resolve_conflict_first`` — one per structural conflict.
      * ``isolate_session`` — one per planned path another live session also
        claims (parallel-agent overlap; emitted only when ``other_active_files``
        was supplied to ``intent_check``).
    """
    recs: list[Recommendation] = []
    live_conflicts = live_conflicts or []

    has_governance = bool(governing_decisions)
    has_conflicts = bool(conflicts)
    has_stale = bool(stale_ids)
    has_unchecked = bool(unchecked)
    has_live = bool(live_conflicts)

    # proceed — only when all signals are clean.
    if (
        not has_governance
        and not has_conflicts
        and not has_stale
        and not has_unchecked
        and not has_live
        and not any(not path_to_decisions.get(p) for p in paths)
    ):
        # All paths are governed *and* clean. Rare for a real plan with files,
        # so this branch mostly fires for "empty planned_files" callers.
        recs.append(
            Recommendation(
                action="proceed",
                target_id=None,
                detail="No blockers detected. Plan looks safe to implement.",
            )
        )
    elif not has_governance and not paths:
        # Pure-plan no-files call. Also "proceed" — there's nothing to check.
        recs.append(
            Recommendation(
                action="proceed",
                target_id=None,
                detail="No planned files supplied; nothing to check.",
            )
        )

    # add_governance — one per ungoverned planned *source* file. A decree
    # document self-edit or generated artifact (``corpus_or_generated``) is
    # authoring/derived, not ungoverned source, so it is excluded here.
    skip = corpus_or_generated or set()
    ungoverned_paths = [p for p in paths if not path_to_decisions.get(p) and p not in skip]
    for path in ungoverned_paths:
        recs.append(
            Recommendation(
                action="add_governance",
                target_id=None,
                detail=(
                    f"{path} has no governing decision. Consider writing a SPEC "
                    f"or amending an existing one's `governs:` list before "
                    f"starting."
                ),
            )
        )

    # draft_adr_first — no governance AND architectural keyword in plan.
    if not has_governance and ungoverned_paths and _plan_mentions_architecture(plan):
        recs.append(
            Recommendation(
                action="draft_adr_first",
                target_id=None,
                detail=(
                    "Plan mentions architectural concerns and no governance "
                    "covers the planned files. Draft an ADR before "
                    "implementing so the decision is recorded."
                ),
            )
        )

    # update_spec_first — for each governing SPEC with unchecked ACs.
    spec_ids_with_unchecked: set[str] = set()
    for ac in unchecked:
        spec_ids_with_unchecked.add(ac.decision_id)
    for snap in sorted(governing_decisions, key=lambda g: g.decision_id):
        if snap.type == "spec" and snap.decision_id in spec_ids_with_unchecked:
            recs.append(
                Recommendation(
                    action="update_spec_first",
                    target_id=snap.decision_id,
                    detail=(
                        f"{snap.decision_id} ({snap.title}) governs planned "
                        f"files and has unchecked acceptance criteria. "
                        f"Check off or amend ACs before implementing on top."
                    ),
                )
            )

    # check_ac — one per unchecked AC (informational; reused verb from SPEC-01KT22NMRYRZQ59EC88VJ5R0N6).
    for ac in unchecked:
        recs.append(
            Recommendation(
                action="check_ac",
                target_id=ac.decision_id,
                detail=(f"{ac.decision_id} has an unchecked AC under '{ac.section_title}': {ac.text}"),
            )
        )

    # update_decision — one per stale governing decision (sorted for determinism).
    for snap in sorted(governing_decisions, key=lambda g: g.decision_id):
        if snap.decision_id in stale_ids:
            recs.append(
                Recommendation(
                    action="update_decision",
                    target_id=snap.decision_id,
                    detail=(
                        f"{snap.decision_id} ({snap.title}) governs planned "
                        f"files and is stale; refresh it before implementing."
                    ),
                )
            )

    # resolve_conflict_first — one per structural conflict.
    for c in conflicts:
        verdict_hint = ""
        if c.semantic_verdict is not None:
            real = bool(c.semantic_verdict.get("is_real_conflict"))
            verdict_hint = " (LLM judged real conflict)" if real else " (LLM judged complementary)"
        recs.append(
            Recommendation(
                action="resolve_conflict_first",
                target_id=None,
                detail=(
                    f"{c.path} is governed by {', '.join(c.decision_ids)}"
                    f"{verdict_hint}. Decide which decision is authoritative "
                    f"before implementing."
                ),
            )
        )

    # isolate_session — one per planned path another live session also claims.
    for lc in live_conflicts:
        recs.append(
            Recommendation(
                action="isolate_session",
                target_id=None,
                detail=(
                    f"{lc.path} is also planned by active session(s) "
                    f"{', '.join(lc.session_ids)}. Run in a dedicated worktree, "
                    f"or split this file out of one plan, before starting."
                ),
            )
        )

    return recs


# ── JSON shape ──────────────────────────────────────────────


# Recommendation verbs that drive exit 1 (conflicts, stale governance, live overlap).
_BLOCKING_ACTIONS = frozenset({"resolve_conflict_first", "update_decision", "isolate_session"})
# Advisory verbs: surfaced, but never flip the exit code on their own.
_ADVISORY_ACTIONS = frozenset({"add_governance", "draft_adr_first", "update_spec_first", "check_ac", "declare_governs"})


def _bucket_findings(report: IntentCheckReport) -> dict[str, list[dict]]:
    """Partition findings into ``blocking`` / ``advisory`` / ``corpus_hygiene`` classes.

    The class is a *kind* of finding (SARIF-style), distinct from any severity
    axis, and additive: it never changes the exit code
    (ADR-01KWXMRRB44CE78H0659D9WDY7). Blocking findings are exactly the exit-1
    drivers (conflicts, stale governance, live-session overlap); advisory findings
    are surfaced but never flip the exit on their own; corpus-hygiene findings are
    decree document/artifact edits that need lint/regen, not governance.
    """
    blocking: list[dict] = []
    advisory: list[dict] = []
    corpus: list[dict] = []
    for r in report.recommended_actions:
        entry = {"action": r.action, "target_id": r.target_id, "detail": r.detail}
        if r.action in _BLOCKING_ACTIONS:
            blocking.append(entry)
        elif r.action in _ADVISORY_ACTIONS:
            advisory.append(entry)
        # ``proceed`` (and any unknown verb) belongs to no class.
    for p in report.corpus_changes:
        corpus.append(
            {
                "action": "corpus_maintenance",
                "target_id": p,
                "detail": (
                    f"{p} is a decree document; run `decree lint` "
                    "(and `decree index rebuild` after governs:/frontmatter edits) — no governance needed."
                ),
            }
        )
    for p in report.generated_artifact_changes:
        corpus.append(
            {
                "action": "generated_artifact",
                "target_id": p,
                "detail": f"{p} is a decree-generated artifact; regenerate it rather than hand-editing.",
            }
        )
    return {"blocking_findings": blocking, "advisory_findings": advisory, "corpus_hygiene_findings": corpus}


def report_to_dict(report: IntentCheckReport) -> dict:
    """Serialize an ``IntentCheckReport`` to the JSON shape used by --json + MCP."""
    return {
        "plan": report.plan,
        "planned_files": list(report.planned_files),
        "governing_decisions": [asdict(g) for g in report.governing_decisions],
        "stale_governance": [dict(s) for s in report.stale_governance],
        "unchecked_acceptance_criteria": [asdict(a) for a in report.unchecked_acceptance_criteria],
        "conflicts": [
            {
                "path": c.path,
                "decision_ids": list(c.decision_ids),
                "semantic_verdict": c.semantic_verdict,
            }
            for c in report.conflicts
        ],
        "live_conflicts": [{"path": lc.path, "session_ids": list(lc.session_ids)} for lc in report.live_conflicts],
        "abstention": report.abstention,
        "recommended_actions": [asdict(r) for r in report.recommended_actions],
        "under_decision": report.under_decision,
        "under_error": report.under_error,
        "governs_gaps": [{"path": g.path, "commit_count": g.commit_count} for g in report.governs_gaps],
        "source_changes": list(report.source_changes),
        "corpus_changes": list(report.corpus_changes),
        "generated_artifact_changes": list(report.generated_artifact_changes),
        "directory_overlaps": [dict(o) for o in report.directory_overlaps],
        "owned_files": list(report.owned_files),
        "contextual_overlaps": [dict(o) for o in report.contextual_overlaps],
        "contradictions": [dict(c) for c in report.contradictions],
        **_bucket_findings(report),
    }


# ── CLI plumbing ────────────────────────────────────────────


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root (explicit --project wins, else cwd-walk)."""
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()
    return get_project_root()


def _open_db_or_error(
    project_arg: str | None,
) -> tuple[IndexDB | None, Path | None, int]:
    try:
        root = _resolve_root(project_arg)
    except FileNotFoundError as e:
        error("intent-check", str(e))
        return None, None, 1

    os.chdir(root)
    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()

    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        error(
            "intent-check",
            "index not found; run `decree index rebuild` first.",
        )
        return None, root, 1
    return db, root, 0


def _next_command(report: IntentCheckReport, blocking: list[dict], cleanup: list[dict]) -> str:
    """Deterministic single next-step suggestion, derived from the top blocker."""
    actions = {e["action"] for e in blocking}
    # Under an active decision, give decision-relative guidance instead of
    # re-suggesting --under (which is already set).
    if report.under_decision:
        if report.contradictions:
            paths = ", ".join(c["path"] for c in report.contradictions)
            return (
                f"Resolve the contradiction on {paths} — governed by other decisions, not "
                f"{report.under_decision} — or work under the decision that owns it."
            )
        if report.contextual_overlaps:
            return (
                f"Proceed under {report.under_decision}; the other governors are contextual — "
                "resolve only if their acceptance criteria contradict your plan."
            )
    if "resolve_conflict_first" in actions:
        first = report.conflicts[0] if report.conflicts else None
        pick = first.decision_ids[0] if first and first.decision_ids else "<SPEC-ID>"
        return (
            f'decree intent-check --under {pick} --plan "..." --files ...  '
            "(name the authoritative decision; treat the other governors as contextual)"
        )
    if "isolate_session" in actions:
        return "Run in a dedicated worktree, or split the overlapping file out of one plan, before starting."
    if "update_decision" in actions:
        return "Refresh the stale governing decision, then re-run intent-check."
    if cleanup:
        return "Proceed; address the advisory / corpus-hygiene items when convenient."
    return "Proceed — no blockers detected."


def _format_human(report: IntentCheckReport) -> str:
    """Render a human-readable intent-check report.

    Leads with a "Block now" / "Clean later" summary so a reader can tell an
    exit-1 blocker from cleanup at a glance (backlog B4), then keeps the detailed
    sections below for full context.
    """
    lines: list[str] = []
    lines.append("Intent check — pre-PR governance map")
    if report.plan:
        snippet = report.plan if len(report.plan) <= 200 else report.plan[:197] + "..."
        lines.append(f"  Plan: {snippet}")

    buckets = _bucket_findings(report)
    blocking = buckets["blocking_findings"]
    cleanup = buckets["advisory_findings"] + buckets["corpus_hygiene_findings"]

    lines.append("")
    lines.append(f"Block now ({len(blocking)}):")
    if blocking:
        for e in blocking:
            target = f" [{e['target_id']}]" if e.get("target_id") else ""
            lines.append(f"  ✗ {e['action']}{target}: {e['detail']}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Clean later ({len(cleanup)}):")
    if cleanup:
        for e in cleanup:
            target = f" [{e['target_id']}]" if e.get("target_id") else ""
            lines.append(f"  ~ {e['action']}{target}: {e['detail']}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Recommended next command:")
    lines.append(f"  {_next_command(report, blocking, cleanup)}")

    # Decision-relative framing when working under an active decision (B8): what
    # it owns, which other governors are contextual, and any path it does not own.
    if report.under_decision:
        lines.append("")
        lines.append(f"Active decision: {report.under_decision}")
        owned = ", ".join(report.owned_files) if report.owned_files else "(none)"
        lines.append(f"  Owned files ({len(report.owned_files)}): {owned}")
        if report.contextual_overlaps:
            lines.append(f"  Contextual overlaps ({len(report.contextual_overlaps)}):")
            for o in report.contextual_overlaps:
                others = ", ".join(o["contextual_decision_ids"])
                lines.append(f"    ~ {o['path']} — also governed by {others} (context, not a contradiction)")
        if report.contradictions:
            lines.append(f"  Contradictions ({len(report.contradictions)}):")
            for c in report.contradictions:
                govs = ", ".join(c["decision_ids"])
                lines.append(f"    ✗ {c['path']} — governed by {govs}, none of which is {report.under_decision}")

    lines.append("")
    lines.append(f"Planned files ({len(report.planned_files)}):")
    if report.planned_files:
        for p in report.planned_files:
            lines.append(f"  • {p}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Governing decisions ({len(report.governing_decisions)}):")
    if report.governing_decisions:
        for g in report.governing_decisions:
            lines.append(f"  ▸ {g.decision_id}  {g.status}  {g.match_kind}  governs {g.matched_path}")
            lines.append(f"    {g.title}")
    else:
        lines.append("  (none — ungoverned plan)")

    lines.append("")
    lines.append(f"Stale governance ({len(report.stale_governance)}):")
    if report.stale_governance:
        for s in report.stale_governance:
            lines.append(f"  ⚠ {s['decision_id']}  churn={s['churn_count']}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Unchecked acceptance criteria ({len(report.unchecked_acceptance_criteria)}):")
    if report.unchecked_acceptance_criteria:
        for ac in report.unchecked_acceptance_criteria:
            snippet = ac.text if len(ac.text) <= 80 else ac.text[:77] + "..."
            lines.append(f"  ☐ {ac.decision_id}  [{ac.section_title}]  {snippet}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Conflicts ({len(report.conflicts)}):")
    if report.conflicts:
        for c in report.conflicts:
            base = f"  ✗ {c.path}: {', '.join(c.decision_ids)}"
            if c.semantic_verdict is not None:
                real = bool(c.semantic_verdict.get("is_real_conflict"))
                label = "real" if real else "complementary"
                reasoning = str(c.semantic_verdict.get("reasoning", "") or "")
                base += f"  [LLM: {label}]"
                if reasoning:
                    base += f" — {reasoning}"
            lines.append(base)
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Live-session conflicts ({len(report.live_conflicts)}):")
    if report.live_conflicts:
        for lc in report.live_conflicts:
            lines.append(f"  ⇄ {lc.path}: also planned by {', '.join(lc.session_ids)}")
    else:
        lines.append("  (none)")

    if report.abstention is not None:
        lines.append("")
        lines.append("Calibrated abstention:")
        lines.append(
            f"  abstained={report.abstention.get('abstained')}  "
            f"composite={float(report.abstention.get('composite_score', 0.0)):.2f}  "
            f"threshold={float(report.abstention.get('threshold', 0.0)):.2f}"
        )
        reason = report.abstention.get("abstention_reason")
        if reason:
            lines.append(f"  reason: {reason}")

    lines.append("")
    lines.append(f"Recommended actions ({len(report.recommended_actions)}):")
    if report.recommended_actions:
        for r in report.recommended_actions:
            target = f" [{r.target_id}]" if r.target_id else ""
            lines.append(f"  → {r.action}{target}: {r.detail}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def intent_check_run(args: argparse.Namespace) -> int:
    """`decree intent-check` — pre-PR governance report CLI entry point.

    Exit codes (SPEC-01KT22NMS0KTWGNKB36RR7K0JR):
      * 0 — no conflicts (decision- or live-session-level) and no stale governance.
      * 1 — at least one conflict, live-session overlap, or stale governance
        entry surfaced. Live-session overlaps require ``--other-active-files``.
      * 2 — config error (e.g. missing or stale index, or bad
        ``--other-active-files`` JSON).
    """
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    plan = getattr(args, "plan", "") or ""
    planned_files: list[str] = list(getattr(args, "files", []) or [])

    with_abstention = bool(getattr(args, "with_abstention", False))

    other_active_files: dict[str, list[str]] | None = None
    raw_other = getattr(args, "other_active_files", None)
    if raw_other:
        try:
            parsed = json.loads(raw_other)
        except json.JSONDecodeError as e:
            error("intent-check", f"--other-active-files is not valid JSON: {e}")
            return 2
        if not isinstance(parsed, dict):
            error(
                "intent-check",
                '--other-active-files must be a JSON object, e.g. {"session-b": ["src/foo.py"]}.',
            )
            return 2
        other_active_files = {str(k): [str(p) for p in (v or [])] for k, v in parsed.items()}

    report = intent_check(
        db,
        root,
        plan,
        planned_files,
        with_abstention=with_abstention,
        other_active_files=other_active_files,
        under=getattr(args, "under", None),
    )

    if getattr(args, "json", False):
        print(json.dumps(report_to_dict(report), indent=2, sort_keys=False))
    else:
        print(_format_human(report))

    if report.under_error:
        error("intent-check", report.under_error)
        return 2

    # Exit 1 if any conflict (decision or live-session) or stale entry surfaced; else 0.
    # Governs gaps are advisory and never affect the exit code.
    has_blockers = bool(report.conflicts) or bool(report.stale_governance) or bool(report.live_conflicts)
    if has_blockers:
        info(
            "intent-check",
            "exit 1: findings present (conflicts, live-session overlaps, or stale governance).",
        )
        return 1
    return 0
