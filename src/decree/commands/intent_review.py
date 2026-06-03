"""`decree intent-review` — diff-aware governance report.

Implements the diff-aware governance report. Takes a unified diff (or
staged/working-tree diff) and produces a structured report on how the changes
intersect with the governance corpus:

  - which decisions govern the changed paths (`governing_decisions`)
  - which of those decisions are stale (`stale_governance`)
  - which acceptance criteria might be affected (`unchecked_acceptance_criteria`)
  - which decisions structurally conflict over the same files (`conflicts`)
  - what to do about it (`recommended_actions`)

This is the *post-code* intent-review surface. The *pre-code* variant
(`intent_check(plan, planned_files)`) is PRD-01KT22NMRSXYT95XE808VD8EV4 R2, not implemented here.

No new query logic — the library function `intent_review()` composes
existing helpers from `commands.queries` and `commands.health`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from decree.commands.health import stale_decisions
from decree.commands.queries import GoverningDecision, why
from decree.config import load_doc_types
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info

# ── Public dataclasses ───────────────────────────────────────


@dataclass(frozen=True)
class GoverningSnapshot:
    """One decision that governs at least one changed path."""

    decision_id: str
    type: str
    status: str
    title: str
    match_kind: str
    matched_path: str
    symbol: str | None = None


@dataclass(frozen=True)
class UncheckedAC:
    """One unchecked acceptance criterion on an in-flight governing decision."""

    decision_id: str
    section_title: str
    text: str
    order_index: int


@dataclass(frozen=True)
class Conflict:
    """Two or more decisions structurally claim the same governed path.

    ``semantic_verdict`` remains for JSON schema compatibility with older
    reports. Core decree leaves it as ``None``; agent/skill layers may
    post-process JSON output if they need semantic conflict judging.
    """

    path: str
    decision_ids: tuple[str, ...]
    semantic_verdict: dict | None = None


@dataclass(frozen=True)
class Recommendation:
    """One actionable suggestion derived from the report signals."""

    action: str
    target_id: str | None
    detail: str


@dataclass(frozen=True)
class GovernsGap:
    """A path the active decision's own commits repeat-touch (commit_count >= 2)
    but it does not declare — an advisory suggestion to add it to that decision's
    `governs:` (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5). Read-only; never feeds `why()`."""

    path: str
    commit_count: int


@dataclass(frozen=True)
class IntentReport:
    """Top-level diff-aware governance report."""

    changed_paths: tuple[str, ...]
    governing_decisions: tuple[GoverningSnapshot, ...]
    stale_governance: tuple[dict, ...]
    unchecked_acceptance_criteria: tuple[UncheckedAC, ...]
    conflicts: tuple[Conflict, ...]
    recommended_actions: tuple[Recommendation, ...]
    # Point-of-change governs gaps for an active `under` decision (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5).
    under_decision: str | None = None
    under_error: str | None = None
    governs_gaps: tuple[GovernsGap, ...] = ()


# ── Diff parser — minimal in-house ──────────────────────────


_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)$")
_PLUSPLUS_RE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (?P<path>.+)$")


def parse_diff(diff: str) -> list[str]:
    """Extract changed file paths from a unified-diff string.

    Behavior:
      - Captures the `b/` (post-image) path from `diff --git a/X b/Y` lines.
      - Captures `+++ b/<path>` (covers most unified diff producers).
      - Captures rename targets via `rename to <path>`.
      - Skips deleted files (`+++ /dev/null`).
      - Dedupes while preserving first-seen order.

    No `unidiff` library dependency by design (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6 constraint).
    """
    if not diff:
        return []

    seen: dict[str, None] = {}
    deleted: set[str] = set()

    lines = diff.splitlines()
    pending_diff_a: str | None = None
    pending_diff_b: str | None = None
    in_deletion = False

    for line in lines:
        m = _DIFF_GIT_RE.match(line)
        if m:
            # Flush any pending state from previous file block.
            if pending_diff_b is not None and not in_deletion:
                seen.setdefault(pending_diff_b, None)
            pending_diff_a = m.group("a")
            pending_diff_b = m.group("b")
            in_deletion = False
            continue

        if line.startswith("+++ "):
            rest = line[4:].strip()
            if rest == "/dev/null":
                in_deletion = True
                if pending_diff_a is not None:
                    deleted.add(pending_diff_a)
                continue
            mm = _PLUSPLUS_RE.match(line)
            if mm:
                path = mm.group("path")
                # `+++ b/<path>` is the post-image path; this is the same as
                # pending_diff_b in well-formed diffs, but trust the +++ line
                # because it tolerates leading paths that contain spaces.
                pending_diff_b = path
            continue

        rn = _RENAME_TO_RE.match(line)
        if rn:
            pending_diff_b = rn.group("path")
            continue

    # Flush the final file block.
    if pending_diff_b is not None and not in_deletion:
        seen.setdefault(pending_diff_b, None)

    # Remove anything that we know was deleted.
    return [p for p in seen if p not in deleted]


# ── Library: intent_review() ────────────────────────────────


def _terminal_statuses_for(type_name: str) -> frozenset[str]:
    """Return the set of terminal statuses for a doc type (e.g. `implemented`)."""
    for dt in load_doc_types():
        if dt.name == type_name:
            return dt.terminal_statuses
    return frozenset()


def _governing_snapshot_from(gd: GoverningDecision) -> GoverningSnapshot:
    return GoverningSnapshot(
        decision_id=gd.decision_id,
        type=gd.type,
        status=gd.status,
        title=gd.title,
        match_kind=gd.match_kind.value,
        matched_path=gd.matched_path,
        symbol=gd.symbol,
    )


def _stale_decision_to_dict(sd) -> dict:
    return {
        "decision_id": sd.decision_id,
        "type": sd.type,
        "last_touched_ts": sd.last_touched_ts,
        "churn_count": sd.churn_count,
        "governed_paths": [{"path": p, "count": c} for (p, c) in sd.governed_paths],
    }


def compute_governs_gaps(db: IndexDB, under: str | None, paths: list[str]) -> tuple[tuple[GovernsGap, ...], str | None]:
    """Active-decision governs gaps (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5).

    Returns ``(governs_gaps, under_error)``. A gap is a path in ``paths`` that
    ``under``'s own trailer-linked commits repeat-touch
    (``observed_governs.commit_count >= 2`` — squash-immune) but ``under`` does
    not declare and that is not structural noise. Pure index read; reuses v1
    ``_path_covers`` and v2 ``_is_structural_noise`` (imported from health).
    The *known* ``under`` deliberately replaces v2's cross-decision precision
    controls (owned-elsewhere / shared-infra floor): under a chosen decision, a
    path it repeat-touches and does not declare is a gap even if other decisions
    also touch or govern it. Never read by ``why()``.

    A malformed or non-existent ``under`` returns ``((), error)`` — validated by
    corpus presence, not just id format.
    """
    if not under:
        return (), None
    conn = db.db.conn  # type: ignore[attr-defined]
    if conn.execute("SELECT 1 FROM decisions WHERE id = ?", (under,)).fetchone() is None:
        return (), f"--under decision not found in corpus: {under}"

    from decree.commands.health import _is_structural_noise, _path_covers

    observed: dict[str, int] = dict(
        conn.execute(
            "SELECT path, commit_count FROM observed_governs WHERE decision_id = ? AND commit_count >= 2",
            (under,),
        )
    )
    declared = [
        path
        for path, symbol in conn.execute("SELECT path, symbol FROM governs WHERE decision_id = ?", (under,))
        if not symbol  # symbol-scoped entries can't cover a file observation (parity with dead-governance)
    ]
    gaps: list[GovernsGap] = []
    for p in paths:
        cc = observed.get(p)
        if cc is None:
            continue  # not repeat-touched by `under`
        if any(_path_covers(d, p) for d in declared):
            continue  # already declared (note arg order: _path_covers(declared, observed))
        if _is_structural_noise(p):
            continue  # tests / changelog / documentation
        gaps.append(GovernsGap(path=p, commit_count=cc))
    gaps.sort(key=lambda g: (-g.commit_count, g.path))
    return tuple(gaps), None


def intent_review(
    db: IndexDB,
    project_root: Path,
    changed_paths: list[str],
    *,
    threshold_commits: int = 10,
    under: str | None = None,
) -> IntentReport:
    """Compose an IntentReport for the given changed paths.

    Stitches together prior-SPEC primitives — no new query logic. See SPEC-01KT22NMRYRZQ59EC88VJ5R0N6
    for the per-component contract.
    """
    # Stable ordering, deduped.
    seen: dict[str, None] = {}
    for p in changed_paths:
        seen.setdefault(p, None)
    paths = list(seen.keys())

    # 1. governing_decisions — dedupe across paths by decision_id, keep first occurrence.
    govs_by_id: dict[str, GoverningSnapshot] = {}
    path_to_decisions: dict[str, list[str]] = {}
    for path in paths:
        matches = why(db, path)
        path_to_decisions[path] = [m.decision_id for m in matches]
        for m in matches:
            if m.decision_id not in govs_by_id:
                govs_by_id[m.decision_id] = _governing_snapshot_from(m)
    governing_decisions = tuple(govs_by_id.values())

    # 2. unchecked_acceptance_criteria — for governing decisions in non-terminal status.
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

    # 3. stale_governance — full stale list intersected with governing-decision ids.
    governing_ids = set(govs_by_id.keys())
    all_stale = stale_decisions(db, project_root, threshold_commits)
    stale_governance = tuple(_stale_decision_to_dict(sd) for sd in all_stale if sd.decision_id in governing_ids)

    # 4. conflicts — multiple decisions claim the same changed path.
    conflicts: list[Conflict] = []
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
            ids = tuple(sorted(set((ids_blob or "").split(","))))
            ids = tuple(i for i in ids if i)
            if len(ids) > 1:
                conflicts.append(Conflict(path=path, decision_ids=ids))

    # 5. recommended_actions — deterministic, derived from above signals.
    recommendations = _build_recommendations(
        paths=paths,
        path_to_decisions=path_to_decisions,
        governing_decisions=governing_decisions,
        stale_ids={s["decision_id"] for s in stale_governance},
        unchecked=unchecked,
        conflicts=conflicts,
    )

    # 6. governs gaps for the active decision (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5).
    #    Appended AFTER _build_recommendations so `declare_governs` never enters
    #    the proceed/blocker logic — it is advisory and exit-code-neutral.
    governs_gaps, under_error = compute_governs_gaps(db, under, paths)
    if governs_gaps:
        gap_paths = ", ".join(g.path for g in governs_gaps)
        recommendations.append(
            Recommendation(
                action="declare_governs",
                target_id=under,
                detail=(
                    f"{under}'s commits repeat-touch {gap_paths}, "
                    f"{'which are' if len(governs_gaps) > 1 else 'which is'} not in its "
                    "`governs:`. Consider declaring it (advisory)."
                ),
            )
        )

    return IntentReport(
        changed_paths=tuple(paths),
        governing_decisions=governing_decisions,
        stale_governance=stale_governance,
        unchecked_acceptance_criteria=tuple(unchecked),
        conflicts=tuple(conflicts),
        recommended_actions=tuple(recommendations),
        under_decision=under,
        under_error=under_error,
        governs_gaps=governs_gaps,
    )


def _build_recommendations(
    *,
    paths: list[str],
    path_to_decisions: dict[str, list[str]],
    governing_decisions: tuple[GoverningSnapshot, ...],
    stale_ids: set[str],
    unchecked: list[UncheckedAC],
    conflicts: list[Conflict],
) -> list[Recommendation]:
    """Generate the 5 verb kinds from the signals collected by intent_review()."""
    recs: list[Recommendation] = []

    # update_decision — one per stale governing decision (sorted for determinism).
    for snap in sorted(governing_decisions, key=lambda g: g.decision_id):
        if snap.decision_id in stale_ids:
            recs.append(
                Recommendation(
                    action="update_decision",
                    target_id=snap.decision_id,
                    detail=(
                        f"{snap.decision_id} ({snap.title}) governs changed files "
                        f"and is stale; refresh it before merging."
                    ),
                )
            )

    # check_ac — one per unchecked AC on in-flight SPECs (already filtered to non-terminal).
    for ac in unchecked:
        recs.append(
            Recommendation(
                action="check_ac",
                target_id=ac.decision_id,
                detail=(f"{ac.decision_id} has an unchecked AC under '{ac.section_title}': {ac.text}"),
            )
        )

    # resolve_conflict — one per structural overlap.
    for c in conflicts:
        recs.append(
            Recommendation(
                action="resolve_conflict",
                target_id=None,
                detail=(
                    f"{c.path} is governed by {', '.join(c.decision_ids)}. "
                    "Decide which decision is authoritative or supersede the others."
                ),
            )
        )

    # add_governance — one per ungoverned changed path.
    for path in paths:
        if not path_to_decisions.get(path):
            recs.append(
                Recommendation(
                    action="add_governance",
                    target_id=None,
                    detail=(
                        f"{path} has no governing decision. Consider writing a SPEC "
                        f"or amending an existing one's `governs:` list."
                    ),
                )
            )

    # add_implements_trailer — if there's exactly one in-flight governing SPEC, hint.
    for snap in sorted(governing_decisions, key=lambda g: g.decision_id):
        if snap.type == "spec":
            terminal = _terminal_statuses_for("spec")
            if snap.status not in terminal:
                recs.append(
                    Recommendation(
                        action="add_implements_trailer",
                        target_id=snap.decision_id,
                        detail=(
                            f"Changes touch files governed by in-flight {snap.decision_id}. "
                            f"Consider `decree commit --implements {snap.decision_id}` so "
                            f"the commit links to the SPEC."
                        ),
                    )
                )

    return recs


# ── JSON shape ──────────────────────────────────────────────


def report_to_dict(report: IntentReport) -> dict:
    """Serialize an IntentReport to the JSON shape used by `--json` and the MCP tool."""
    return {
        "changed_paths": list(report.changed_paths),
        "governing_decisions": [asdict(g) for g in report.governing_decisions],
        "stale_governance": [dict(s) for s in report.stale_governance],
        "unchecked_acceptance_criteria": [asdict(a) for a in report.unchecked_acceptance_criteria],
        "conflicts": [{"path": c.path, "decision_ids": list(c.decision_ids)} for c in report.conflicts],
        "recommended_actions": [asdict(r) for r in report.recommended_actions],
        "under_decision": report.under_decision,
        "under_error": report.under_error,
        "governs_gaps": [{"path": g.path, "commit_count": g.commit_count} for g in report.governs_gaps],
    }


# ── Diff source resolution ──────────────────────────────────


def _read_diff_source(args: argparse.Namespace, project_root: Path) -> tuple[list[str], str, bool]:
    """Resolve the diff source and return (changed_paths, mode_description, structured).

    ``structured`` is True when the source carries add/delete structure (parsed
    via ``parse_diff``, which strips deletions) and False for the name-only
    default modes (a deletion is indistinguishable from an edit). The
    governs-gap check (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5) runs only when structured.

    Modes:
      1. --diff '-'  → read unified diff from stdin (structured).
      2. --diff PATH → read unified diff from file (structured).
      3. --diff-base REF → run `git diff REF...HEAD` (structured).
      4. Default → `git diff --cached --name-only`, fall back to working-tree
         names if staged is empty (name-only, not structured).
    """
    diff_arg = getattr(args, "diff", None)
    diff_base = getattr(args, "diff_base", None)

    if diff_arg == "-":
        text = sys.stdin.read()
        return parse_diff(text), "stdin", True

    if diff_arg:
        text = Path(diff_arg).read_text()
        return parse_diff(text), f"file:{diff_arg}", True

    if diff_base:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", f"{diff_base}...HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git diff failed (exit {result.returncode}): {result.stderr.strip()}")
        return parse_diff(result.stdout), f"git diff {diff_base}...HEAD", True

    # Default: staged first, then working-tree. Name-only — no add/delete structure.
    staged = subprocess.run(
        ["git", "-C", str(project_root), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    staged_paths = [p for p in staged.stdout.splitlines() if p.strip()]
    if staged_paths:
        return staged_paths, "git diff --cached", False

    worktree = subprocess.run(
        ["git", "-C", str(project_root), "diff", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    worktree_paths = [p for p in worktree.stdout.splitlines() if p.strip()]
    return worktree_paths, "git diff", False


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


def _open_db_or_error(project_arg: str | None) -> tuple[IndexDB | None, Path | None, int]:
    try:
        root = _resolve_root(project_arg)
    except FileNotFoundError as e:
        error("intent-review", str(e))
        return None, None, 1

    import os

    os.chdir(root)
    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()

    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        error(
            "intent-review",
            "index not found; run `decree index rebuild` first.",
        )
        return None, root, 1
    return db, root, 0


def _format_human(report: IntentReport, mode: str) -> str:
    lines: list[str] = []
    lines.append(f"Intent review — {mode}")
    if not report.changed_paths:
        lines.append("  (no changed paths)")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Changed paths ({len(report.changed_paths)}):")
    for p in report.changed_paths:
        lines.append(f"  • {p}")

    lines.append("")
    lines.append(f"Governing decisions ({len(report.governing_decisions)}):")
    if report.governing_decisions:
        for g in report.governing_decisions:
            lines.append(f"  ▸ {g.decision_id}  {g.status}  {g.match_kind}  governs {g.matched_path}")
            lines.append(f"    {g.title}")
    else:
        lines.append("  (none — ungoverned change)")

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
            lines.append(f"  ✗ {c.path}: {', '.join(c.decision_ids)}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"Recommended actions ({len(report.recommended_actions)}):")
    if report.recommended_actions:
        for r in report.recommended_actions:
            target = f" [{r.target_id}]" if r.target_id else ""
            lines.append(f"  → {r.action}{target}: {r.detail}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def intent_review_run(args: argparse.Namespace) -> int:
    """`decree intent-review` — diff-aware governance report CLI entry point."""
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    try:
        changed_paths, mode, structured = _read_diff_source(args, root)
    except FileNotFoundError as e:
        error("intent-review", f"diff source not found: {e}")
        return 1
    except RuntimeError as e:
        error("intent-review", str(e))
        return 1

    # The governs-gap check needs a structured diff to exclude deletions (a
    # name-only source can't tell a deletion from an edit, and the check forbids
    # working-tree reads). Skip it in name-only mode rather than propose
    # declaring a just-deleted file (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5).
    under = getattr(args, "under", None)
    if under and not structured:
        info("intent-review", "governs-gap suggestions need a structured diff (--diff/--diff-base); skipped.")
        under = None

    report = intent_review(db, root, changed_paths, under=under)

    if getattr(args, "json", False):
        print(json.dumps(report_to_dict(report), indent=2, sort_keys=False))
    else:
        print(_format_human(report, mode))

    if report.under_error:
        error("intent-review", report.under_error)
        return 2

    # CI-suitable exit: 1 if any blocking findings, else 0. Governs gaps are
    # advisory and never affect the exit code.
    has_blockers = bool(report.conflicts) or bool(report.stale_governance)
    if has_blockers:
        info(
            "intent-review",
            "exit 1: findings present (conflicts or stale governance).",
        )
        return 1
    return 0
