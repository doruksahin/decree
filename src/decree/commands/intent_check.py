"""`decree intent-check` — pre-PR planning-phase governance report.

Implements PRD-004 R2 (SPEC-014). The post-code counterpart, ``decree
intent-review`` (SPEC-009), takes a diff and asks "what does this change
intersect with?". This module is the *planning-phase* counterpart: a caller
says "I'm going to build X and touch these files", and we return the
governance map *before* any code is written.

The implementation is mostly composition of existing helpers — same trick
SPEC-009 used:

  * ``commands.queries.why`` (SPEC-005) for governance lookup.
  * ``commands.queries._calibrated_assess`` (SPEC-013) for optional
    calibrated abstention when no governance is found and the caller
    passed ``--with-abstention``.
  * ``commands.health.stale_decisions`` (SPEC-008) for stale intersection.
  * Acceptance-criteria SQL identical to SPEC-009's.
  * ``litellm`` (already in deps via SPEC-011) for the optional structural-
    conflict semantic judge.

The dataclasses are reused from SPEC-009 wherever the shape is the same.
``IntentCheckReport`` is the new top-level container; ``Conflict`` from
SPEC-009 was extended in-place with an optional ``semantic_verdict`` field.
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
    Recommendation,
    UncheckedAC,
    _governing_snapshot_from,
    _stale_decision_to_dict,
)
from decree.commands.queries import _calibrated_assess, why
from decree.config import load_doc_types
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info


# ── Public dataclass ────────────────────────────────────────


@dataclass(frozen=True)
class IntentCheckReport:
    """Top-level pre-code governance report.

    Mirrors SPEC-009's ``IntentReport`` shape with planning-phase deltas:
    ``planned_files`` instead of ``changed_paths``, ``plan`` surfaced for
    semantic context, ``abstention`` populated when the calibrated method
    vetoes (SPEC-013), and the ``recommended_actions`` verbs expanded to
    pre-code phase (``draft_adr_first``, ``update_spec_first``,
    ``resolve_conflict_first``, ``proceed``) plus the SPEC-009 reuse set.
    """

    plan: str
    planned_files: tuple[str, ...]
    governing_decisions: tuple[GoverningSnapshot, ...]
    stale_governance: tuple[dict, ...]
    unchecked_acceptance_criteria: tuple[UncheckedAC, ...]
    conflicts: tuple[Conflict, ...]
    abstention: dict | None
    recommended_actions: tuple[Recommendation, ...]


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


def _fetch_decision_for_judge(db: IndexDB, decision_id: str) -> dict | None:
    """Return ``{decision_id, title, body}`` for the LLM judge, or None.

    Body lives in the FTS5 virtual table (see ``IndexDB._ensure_schema``).
    Title lives in ``decisions``. The judge needs both.
    """
    conn = db.db.conn  # type: ignore[attr-defined]
    row = conn.execute(
        "SELECT id, title FROM decisions WHERE id = ?", (decision_id,)
    ).fetchone()
    if row is None:
        return None
    did, title = row
    body_row = conn.execute(
        "SELECT body FROM decisions_fts WHERE id = ?", (decision_id,)
    ).fetchone()
    body = body_row[0] if body_row is not None else ""
    return {"decision_id": did, "title": title or "", "body": body or ""}


def _judge_conflict(
    plan: str,
    conflict: Conflict,
    doc_a: dict,
    doc_b: dict,
    model: str,
) -> dict | None:
    """Call litellm to decide whether a structural conflict is real.

    Returns ``{"is_real_conflict": bool, "reasoning": str}`` on success and
    ``None`` on any failure (network, parse, provider). The caller is
    expected to leave ``Conflict.semantic_verdict = None`` in that case;
    the conflict still surfaces in the report.
    """
    import litellm  # local import — keep the litellm dep out of the cold path

    from decree.migrate_prompts import build_conflict_judge_prompt

    prompt = build_conflict_judge_prompt(plan, conflict.path, doc_a, doc_b)
    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=30,
        )
        content = response.choices[0].message.content
        payload = _parse_llm_json(content)
    except Exception:  # noqa: BLE001 — per-conflict isolation by design
        return None

    if not isinstance(payload, dict):
        return None
    if "is_real_conflict" not in payload:
        return None
    return {
        "is_real_conflict": bool(payload.get("is_real_conflict")),
        "reasoning": str(payload.get("reasoning", "") or ""),
    }


def _parse_llm_json(content: str) -> dict:
    """Parse an LLM response body as JSON.

    Same fence-stripping pattern as ``commands.migrate._parse_llm_json``.
    Duplicated locally to avoid a cross-command import cycle; the function
    is six lines and the duplication is preferable to coupling.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


# ── Library: intent_check() ─────────────────────────────────


def intent_check(
    db: IndexDB,
    project_root: Path,
    plan: str,
    planned_files: list[str],
    *,
    with_abstention: bool = False,
    judge_conflicts: bool = False,
    model: str | None = None,
    threshold_commits: int = 10,
) -> IntentCheckReport:
    """Compose an ``IntentCheckReport`` for a plan and planned files.

    Stitches the same prior-SPEC primitives SPEC-009 used, plus optional
    SPEC-013 calibrated abstention and an LLM-judged semantic verdict on
    structural conflicts. See SPEC-014 for the per-component contract.
    """
    # 0. Normalize planned_files: stable order, deduped.
    seen: dict[str, None] = {}
    for p in planned_files or ():
        seen.setdefault(p, None)
    paths = list(seen.keys())

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

    # 2. unchecked_acceptance_criteria — same SQL as SPEC-009.
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
    stale_governance = tuple(
        _stale_decision_to_dict(sd)
        for sd in all_stale
        if sd.decision_id in governing_ids
    )

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

    # 5. Optional LLM judge per conflict. Failures are per-conflict and
    #    fall back to structural-only (the conflict still surfaces).
    conflicts: list[Conflict] = list(raw_conflicts)
    if judge_conflicts and raw_conflicts:
        # Caller is responsible for validating that a model can be resolved
        # *before* invoking intent_check; if model is None we skip judging.
        if model:
            judged: list[Conflict] = []
            for c in raw_conflicts:
                # Only judge the first two ids deterministically; 3+ ids on a
                # single path is rare and v1 ships pairwise.
                id_a = c.decision_ids[0]
                id_b = c.decision_ids[1]
                doc_a = _fetch_decision_for_judge(db, id_a)
                doc_b = _fetch_decision_for_judge(db, id_b)
                verdict: dict | None = None
                if doc_a is not None and doc_b is not None:
                    verdict = _judge_conflict(plan, c, doc_a, doc_b, model)
                judged.append(
                    Conflict(
                        path=c.path,
                        decision_ids=c.decision_ids,
                        semantic_verdict=verdict,
                    )
                )
            conflicts = judged

    # 6. abstention — populated when --with-abstention and all governance
    #    lookups returned nothing. We synthesize a single abstention block
    #    over the planned paths so the caller can see *why* the calibrator
    #    deflected. v1 reports the first planned_file's calibration; if a
    #    caller needs per-path abstention they can call _calibrated_assess
    #    directly.
    abstention: dict | None = None
    if with_abstention and not governing_decisions and paths:
        first_path = paths[0]
        abstention = _calibrated_assess(db, kind="file_path", text=first_path)

    # 7. recommended_actions — deterministic, derived from the above signals.
    recommendations = _build_recommendations(
        plan=plan,
        paths=paths,
        path_to_decisions=path_to_decisions,
        governing_decisions=governing_decisions,
        stale_ids={s["decision_id"] for s in stale_governance},
        unchecked=unchecked,
        conflicts=conflicts,
    )

    return IntentCheckReport(
        plan=plan or "",
        planned_files=tuple(paths),
        governing_decisions=governing_decisions,
        stale_governance=stale_governance,
        unchecked_acceptance_criteria=tuple(unchecked),
        conflicts=tuple(conflicts),
        abstention=abstention,
        recommended_actions=tuple(recommendations),
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
) -> list[Recommendation]:
    """Generate pre-code-phase recommendation verbs from collected signals.

    Verbs (SPEC-014 §recommended_actions):
      * ``proceed`` — no governance, no conflicts, no stale, no unchecked.
      * ``add_governance`` — one per planned file with no governance.
      * ``draft_adr_first`` — no governance AND plan contains an
        architectural keyword. Emitted in addition to ``add_governance``.
      * ``update_spec_first`` — one per governing SPEC with unchecked ACs.
      * ``check_ac`` — one per unchecked AC (informational; mirrors SPEC-009).
      * ``update_decision`` — one per stale governance entry.
      * ``resolve_conflict_first`` — one per structural conflict.
    """
    recs: list[Recommendation] = []

    has_governance = bool(governing_decisions)
    has_conflicts = bool(conflicts)
    has_stale = bool(stale_ids)
    has_unchecked = bool(unchecked)

    # proceed — only when all signals are clean.
    if (
        not has_governance
        and not has_conflicts
        and not has_stale
        and not has_unchecked
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

    # add_governance — one per ungoverned planned file.
    ungoverned_paths = [p for p in paths if not path_to_decisions.get(p)]
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

    # check_ac — one per unchecked AC (informational; reused verb from SPEC-009).
    for ac in unchecked:
        recs.append(
            Recommendation(
                action="check_ac",
                target_id=ac.decision_id,
                detail=(
                    f"{ac.decision_id} has an unchecked AC under "
                    f"'{ac.section_title}': {ac.text}"
                ),
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
            verdict_hint = (
                " (LLM judged real conflict)"
                if real
                else " (LLM judged complementary)"
            )
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

    return recs


# ── JSON shape ──────────────────────────────────────────────


def report_to_dict(report: IntentCheckReport) -> dict:
    """Serialize an ``IntentCheckReport`` to the JSON shape used by --json + MCP."""
    return {
        "plan": report.plan,
        "planned_files": list(report.planned_files),
        "governing_decisions": [asdict(g) for g in report.governing_decisions],
        "stale_governance": [dict(s) for s in report.stale_governance],
        "unchecked_acceptance_criteria": [
            asdict(a) for a in report.unchecked_acceptance_criteria
        ],
        "conflicts": [
            {
                "path": c.path,
                "decision_ids": list(c.decision_ids),
                "semantic_verdict": c.semantic_verdict,
            }
            for c in report.conflicts
        ],
        "abstention": report.abstention,
        "recommended_actions": [asdict(r) for r in report.recommended_actions],
    }


# ── CLI plumbing ────────────────────────────────────────────


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root (explicit --project wins, else cwd-walk)."""
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    from decree.config import get_project_root, load_doc_types as _ldt

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
    from decree.config import get_project_root, load_doc_types as _ldt

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


def _format_human(report: IntentCheckReport) -> str:
    """Render a human-readable intent-check report.

    Same visual idiom as ``intent_review._format_human`` so the two
    commands look like siblings.
    """
    lines: list[str] = []
    lines.append("Intent check — pre-PR governance map")
    if report.plan:
        snippet = report.plan if len(report.plan) <= 200 else report.plan[:197] + "..."
        lines.append(f"  Plan: {snippet}")

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
            lines.append(
                f"  ▸ {g.decision_id}  {g.status}  {g.match_kind}  "
                f"governs {g.matched_path}"
            )
            lines.append(f"    {g.title}")
    else:
        lines.append("  (none — ungoverned plan)")

    lines.append("")
    lines.append(f"Stale governance ({len(report.stale_governance)}):")
    if report.stale_governance:
        for s in report.stale_governance:
            lines.append(
                f"  ⚠ {s['decision_id']}  churn={s['churn_count']}"
            )
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(
        f"Unchecked acceptance criteria "
        f"({len(report.unchecked_acceptance_criteria)}):"
    )
    if report.unchecked_acceptance_criteria:
        for ac in report.unchecked_acceptance_criteria:
            snippet = ac.text if len(ac.text) <= 80 else ac.text[:77] + "..."
            lines.append(
                f"  ☐ {ac.decision_id}  [{ac.section_title}]  {snippet}"
            )
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
    lines.append(
        f"Recommended actions ({len(report.recommended_actions)}):"
    )
    if report.recommended_actions:
        for r in report.recommended_actions:
            target = f" [{r.target_id}]" if r.target_id else ""
            lines.append(f"  → {r.action}{target}: {r.detail}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def intent_check_run(args: argparse.Namespace) -> int:
    """`decree intent-check` — pre-PR governance report CLI entry point.

    Exit codes (SPEC-014):
      * 0 — no conflicts (real or judged) and no stale governance.
      * 1 — at least one conflict or stale governance entry surfaced.
      * 2 — config error (e.g. ``--judge-conflicts`` without an API key,
        missing flags); enforced at parse time *before* opening the index.
    """
    # ── Pre-flight: enforce --judge-conflicts requires a resolvable model ─
    judge_conflicts = bool(getattr(args, "judge_conflicts", False))
    resolved_model: str | None = None
    if judge_conflicts:
        try:
            from decree.commands.migrate import resolve_model

            resolved_model = resolve_model(args)
        except SystemExit as e:
            # resolve_model uses SystemExit(2) for no-key; surface a clean
            # decree-style error and propagate exit 2.
            error(
                "intent-check",
                f"--judge-conflicts requires a resolvable LLM model: {e}",
            )
            return 2

    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    plan = getattr(args, "plan", "") or ""
    planned_files: list[str] = list(getattr(args, "files", []) or [])

    with_abstention = bool(getattr(args, "with_abstention", False))

    report = intent_check(
        db,
        root,
        plan,
        planned_files,
        with_abstention=with_abstention,
        judge_conflicts=judge_conflicts,
        model=resolved_model,
    )

    if getattr(args, "json", False):
        print(json.dumps(report_to_dict(report), indent=2, sort_keys=False))
    else:
        print(_format_human(report))

    # Exit 1 if any conflict or stale entry surfaced; else 0.
    has_blockers = bool(report.conflicts) or bool(report.stale_governance)
    if has_blockers:
        info(
            "intent-check",
            "exit 1: findings present (conflicts or stale governance).",
        )
        return 1
    return 0
