"""SPEC-01KT22NMRYNFYM7EN80WS2HD6F — `decree health` / `decree stale` command.

Surfaces the *data-push* health signals described in PRD-01KT22NMRS4QGHSFDBZ858PP1T R7:

  - **Stale decisions** — decisions whose `governs:` files have churned
    by more than `--threshold-commits` since the decision itself was last
    touched. The classic "ADR last edited 18 months ago; the API it
    governs has had 30 commits since" failure mode.
  - **Ungoverned hotspots** — files in the last `--threshold-days`
    window with >`--threshold-commits` commits and **no** decision
    governing them (the Repowise inversion).

Both signals come from local `git log` shellouts (no new deps — same
pattern as SPEC-01KT22NMRY8YK9RP4323KX4RQG's `IndexDB.sync_commits_from_git`) joined against
the SQLite index's `governs` table.

`health_run` / `stale_run` are the CLI handlers; `health()` /
`stale_decisions()` / `ungoverned_hotspots()` are the pure library
functions reused by SPEC-01KT22NMRYNFYM7EN80WS2HD6F's MCP tools.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
from datetime import UTC
from pathlib import Path

from decree.config import load_doc_types
from decree.index_db import IndexDB, default_db_path
from decree.log import fail, info, success

# Governs-count above which a decision's ownership surface is "broad" (advisory, B11).
_BROAD_GOVERNS_THRESHOLD = 25

# ── Dataclasses ────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class StaleDecision:
    decision_id: str
    type: str
    last_touched_ts: int  # unix seconds; -1 if unknown (no git history for the doc)
    churn_count: int
    governed_paths: tuple[tuple[str, int], ...]  # (path, commit-count) tuples


@dataclasses.dataclass(frozen=True)
class UngovernedHotspot:
    path: str
    commit_count: int
    since_days: int


@dataclasses.dataclass(frozen=True)
class DeadGovernance:
    """A decision's declared `governs:` paths that no trailer-linked commit has
    ever touched — aspirational/abandoned scope (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D).

    Only emitted when the decision HAS an observation basis (`linked_commit_count`
    >= 1); a decision with no trailer-linked commits is "unobserved", not dead.
    """

    decision_id: str
    paths: tuple[str, ...]
    linked_commit_count: int


@dataclasses.dataclass(frozen=True)
class GovernanceCandidate:
    """One observed-but-undeclared path proposed as a `governs:` addition
    (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ)."""

    path: str
    commit_count: int  # distinct trailer-linked commits of the decision that touched it (>= 2)
    distinct_decisions: int  # DF: how many decisions repeat-touch this path (cross-decision rarity)


@dataclasses.dataclass(frozen=True)
class MissingGovernance:
    """A decision's repeat-touched paths it does not declare and nobody owns —
    advisory governance suggestions (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ).

    The inverse of `DeadGovernance` (observed minus declared, not declared minus
    observed) and deliberately lower-authority: **advisory** — never affects
    `decree health` exit status, and never read by `why()` / `intent-check`.
    """

    decision_id: str
    linked_commit_count: int  # the decision's trailer-linked commits (honesty: spot squash committers)
    observed_path_count: int  # how many paths those commits touched (honesty)
    candidates: tuple[GovernanceCandidate, ...]


@dataclasses.dataclass(frozen=True)
class LifecycleDrift:
    """A decision whose lifecycle status has drifted from reality (advisory, B10/B9).

    ``reason`` is one of ``complete_but_not_terminal`` (all primary ACs checked +
    commits attached, but status is still non-terminal — the Agentkith Case-4
    "100% but draft" drift), ``terminal_but_governance_stale``, or
    ``terminal_but_governance_dead`` (a shipped decision whose governance rotted).
    Never affects `decree health` exit status.
    """

    decision_id: str
    type: str
    status: str
    reason: str
    detail: str


@dataclasses.dataclass(frozen=True)
class BroadGovernance:
    """A decision whose declared `governs:` surface is broad or overlapping (advisory, B11).

    Path-only and index-derived. ``hot_file_overlap_count`` counts governed paths
    another decision also governs — the Case-3 signal where `governs:` drifted
    from "files owned" toward "files touched". Never affects exit status.
    """

    decision_id: str
    governs_count: int
    exact_governs_count: int
    directory_governs_count: int
    linked_commit_count: int
    governs_to_commits_ratio: float
    hot_file_overlap_count: int


@dataclasses.dataclass(frozen=True)
class HealthReport:
    stale_decisions: tuple[StaleDecision, ...]
    ungoverned_hotspots: tuple[UngovernedHotspot, ...]
    threshold_commits: int
    threshold_days: int
    dead_governance: tuple[DeadGovernance, ...] = ()
    unobserved_decision_ids: tuple[str, ...] = ()
    last_rebuilt_at: str | None = None
    missing_governance: tuple[MissingGovernance, ...] = ()
    lifecycle_drift: tuple[LifecycleDrift, ...] = ()
    broad_governance: tuple[BroadGovernance, ...] = ()


# ── git shellout helpers ───────────────────────────────────


def _is_git_repo(project_root: Path) -> bool:
    """True if `project_root` is inside a git working tree."""
    try:
        check = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return check.returncode == 0


def _file_last_touched_ts(project_root: Path, rel_path: str) -> int:
    """Unix-seconds of the most recent commit touching `rel_path`. -1 if no history."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "log",
            "-1",
            "--format=%ct",
            "--",
            rel_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return -1
    line = result.stdout.strip()
    if not line:
        return -1
    try:
        return int(line)
    except ValueError:
        return -1


def _commit_count_since(project_root: Path, rel_path: str, since_ts: int) -> int:
    """Commits touching `rel_path` strictly after `since_ts` (unix seconds).

    Uses `git log --since=<iso>` which is inclusive of equal timestamps;
    we add 1 second to make it strictly *after* the decision's own commit.
    """
    if since_ts < 0:
        return 0
    since_arg = f"@{since_ts + 1}"  # git understands @<unix-seconds>
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "log",
            f"--since={since_arg}",
            "--oneline",
            "--",
            rel_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def _recent_file_churn(project_root: Path, threshold_days: int) -> dict[str, int]:
    """Files modified in last `threshold_days` → commits-per-file.

    Returns a dict {repo-relative-path: count}.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "log",
            f"--since={threshold_days} days ago",
            "--name-only",
            "--pretty=format:",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for raw in result.stdout.splitlines():
        path = raw.strip()
        if not path:
            continue
        counts[path] = counts.get(path, 0) + 1
    return counts


def _is_generated_artifact(project_root: Path, rel_path: str) -> bool:
    """Return True for decree-generated files that should not require governance."""
    path = project_root / rel_path
    if not path.is_file():
        return False
    try:
        prefix = path.read_text(errors="ignore")[:4096]
    except OSError:
        return False
    if path.name == "index.md" and (
        "auto-generated by `decree index regenerate`" in prefix or "GENERATED:decree-graph" in prefix
    ):
        return True
    return "/reports/" in f"/{rel_path}" and "Completion Report" in prefix


# ── Library functions ──────────────────────────────────────


def stale_decisions(db: IndexDB, project_root: Path, threshold_commits: int) -> list[StaleDecision]:
    """Return decisions whose governed files have churned beyond `threshold_commits`.

    Algorithm (per SPEC-01KT22NMRYNFYM7EN80WS2HD6F):
      1. For each decision in the index with `governs:` entries, find the
         most recent commit timestamp touching the decision's markdown
         file.
      2. For each governed path, count commits to that path *after* the
         decision's timestamp.
      3. If total post-decision commits across all governed paths
         exceeds `threshold_commits`, yield a StaleDecision.

    No-git project: returns []. Caller decides whether to warn.
    """
    if not _is_git_repo(project_root):
        return []

    conn = db.db.conn  # type: ignore[attr-defined]

    # Pull every decision that has at least one governs entry.
    rows = list(
        conn.execute(
            "SELECT d.id, d.type, d.path, "
            "       GROUP_CONCAT(g.path, char(10)) AS govern_paths "
            "FROM decisions d "
            "JOIN governs g ON g.decision_id = d.id "
            "GROUP BY d.id"
        )
    )

    findings: list[StaleDecision] = []
    for decision_id, type_name, doc_path, govern_paths_blob in rows:
        if not govern_paths_blob:
            continue
        last_ts = _file_last_touched_ts(project_root, doc_path)
        if last_ts < 0:
            # The decision document itself has no git history yet — skip.
            continue
        per_path: list[tuple[str, int]] = []
        total = 0
        for gp in str(govern_paths_blob).splitlines():
            gp = gp.strip()
            if not gp:
                continue
            count = _commit_count_since(project_root, gp, last_ts)
            if count > 0:
                per_path.append((gp, count))
                total += count
        if total > threshold_commits:
            findings.append(
                StaleDecision(
                    decision_id=decision_id,
                    type=type_name,
                    last_touched_ts=last_ts,
                    churn_count=total,
                    governed_paths=tuple(per_path),
                )
            )
    # Sort by churn descending so the worst offenders surface first.
    findings.sort(key=lambda f: f.churn_count, reverse=True)
    return findings


def ungoverned_hotspots(
    db: IndexDB,
    project_root: Path,
    threshold_commits: int,
    threshold_days: int,
) -> list[UngovernedHotspot]:
    """Return files with commit count > threshold and no governing decision.

    A file is "governed" if any row in the `governs` table either:
      - matches its path exactly, or
      - is a directory prefix (entry ends with `/` and the file starts
        with that entry).
    """
    if not _is_git_repo(project_root):
        return []

    churn = _recent_file_churn(project_root, threshold_days)
    if not churn:
        return []

    conn = db.db.conn  # type: ignore[attr-defined]
    governs_rows = list(conn.execute("SELECT path FROM governs"))
    exact = {row[0] for row in governs_rows if not str(row[0]).endswith("/")}
    prefixes = tuple(row[0] for row in governs_rows if str(row[0]).endswith("/"))

    findings: list[UngovernedHotspot] = []
    for path, count in churn.items():
        if count <= threshold_commits:
            continue
        if _is_generated_artifact(project_root, path):
            continue
        if path in exact:
            continue
        if any(path.startswith(p) for p in prefixes):
            continue
        findings.append(UngovernedHotspot(path=path, commit_count=count, since_days=threshold_days))
    findings.sort(key=lambda f: f.commit_count, reverse=True)
    return findings


def _path_covers(declared: str, observed: str) -> bool:
    """Dead-check path matching (SPEC-01KT6EEAHKWDQB2Y6S4TTKB77D).

    A declared `governs:` path covers an observed file if they are equal or the
    file lives under the declared directory — including a directory written
    WITHOUT a trailing slash. This deliberately diverges from `why()`'s matching
    (`queries.py`, which prefix-matches only paths ending in `/`); sharing one
    predicate would either leak this permissiveness into `why()` (forbidden) or
    falsely flag a live slashless directory as dead. See docs/provenance-model.md.
    """
    if declared == observed:
        return True
    return observed.startswith(declared.rstrip("/") + "/")


def _declared_and_linked(db: IndexDB) -> tuple[dict[str, list[str]], dict[str, int]]:
    """(declared file-path governs per decision, trailer-linked commit count per
    decision). Symbol-scoped `governs` entries (`path#symbol`) are skipped — a
    file-grained observation can never cover a symbol, so they are unobservable
    at this grain, not dead."""
    conn = db.db.conn  # type: ignore[attr-defined]
    declared: dict[str, list[str]] = {}
    for decision_id, path, symbol in conn.execute("SELECT decision_id, path, symbol FROM governs"):
        if symbol:
            continue
        declared.setdefault(decision_id, []).append(path)
    linked: dict[str, int] = {
        row[0]: row[1]
        for row in conn.execute("SELECT decision_id, COUNT(DISTINCT sha) FROM commits GROUP BY decision_id")
    }
    return declared, linked


def dead_governance(db: IndexDB) -> list[DeadGovernance]:
    """Declared `governs:` paths that no trailer-linked commit has touched.

    Pure index read (no git shellout — attribution was computed at index time
    into `observed_governs`). Precision gate: a decision with zero trailer-linked
    commits is "unobserved", not dead, and is omitted here (see
    `unobserved_decisions`). Never consulted by `why()`.
    """
    conn = db.db.conn  # type: ignore[attr-defined]
    declared, linked = _declared_and_linked(db)
    observed: dict[str, set[str]] = {}
    for decision_id, path in conn.execute("SELECT decision_id, path FROM observed_governs"):
        observed.setdefault(decision_id, set()).add(path)

    findings: list[DeadGovernance] = []
    for decision_id, paths in declared.items():
        n_linked = linked.get(decision_id, 0)
        if n_linked == 0:
            continue  # unobserved, not dead
        obs = observed.get(decision_id, set())
        dead = sorted(p for p in paths if not any(_path_covers(p, f) for f in obs))
        if dead:
            findings.append(DeadGovernance(decision_id=decision_id, paths=tuple(dead), linked_commit_count=n_linked))
    findings.sort(key=lambda f: f.decision_id)
    return findings


def unobserved_decisions(db: IndexDB) -> list[str]:
    """Decision IDs that declare `governs:` paths but have no trailer-linked
    commit, so their governance cannot be observed (not dead — unobservable).
    Surfaced for coverage honesty alongside `dead_governance`."""
    declared, linked = _declared_and_linked(db)
    return sorted(did for did in declared if linked.get(did, 0) == 0)


# Missing-governance (SPEC-01KT6NCQC7DMJ3NG1MPWBGBVFQ) — advisory tuning knobs.
_MG_REPEAT_TOUCH_MIN = 2  # a path must be touched by >= this many of a decision's distinct commits
_MG_SHARED_FLOOR = 3  # a path repeat-touched by >= this many decisions has no single owner
_MG_TOP_CANDIDATES = 5  # human-output cap, candidates per decision
_MG_TOP_DECISIONS = 10  # human-output cap, decisions


def _is_structural_noise(path: str) -> bool:
    """Path-based (therefore deterministic) exclusion of files a decision's
    commits routinely touch but that are never `governs:` targets — tests,
    changelog fragments, and documentation (markdown / reStructuredText). The
    documentation exclusion was added after the decree dogfood surfaced it: a
    doc-heavy commit and the implementing commit both carried the decision's
    trailer, repeat-touching `README.md` / `AGENTS.md` / `docs/*.md` and
    falsely proposing them as governed code. A decree-tuned, **known-incomplete**
    default: it will not match every project layout (e.g. Rust inline
    `#[cfg(test)]`, or a project that uses `spec/` for specifications), and it is
    the first candidate for a `[health]`-config override (deferred). It reads
    only the stored path string, never the working tree."""
    segments = path.split("/")
    base = segments[-1]
    if "tests" in segments or "changelog.d" in segments:
        return True
    if base.startswith("test_") or re.search(r"_test\.", base):
        return True
    if ".test." in base or ".spec." in base:
        return True
    return base.endswith((".md", ".rst"))  # documentation is never a governs: target


def missing_governance(db: IndexDB) -> list[MissingGovernance]:
    """Observed minus declared, per decision: repeat-touched paths a decision does
    not declare and **nobody** owns — advisory `governs:` suggestions.

    Pure index read — no git shellout and **no working-tree access**; reading the
    tree would make the candidate set depend on checkout state rather than the
    index (a determinism leak). Precision rests on **per-decision attribution
    strength**, not cross-decision frequency: a path must be touched by >= 2 of
    the decision's distinct trailer-linked commits (`commit_count >= 2`), which
    drops single-commit squash over-attribution and abstains for thin-attribution
    decisions. A secondary shared-infra floor drops paths repeat-touched by >= 3
    decisions (no single owner). Never read by `why()` / `intent-check`, never
    affects exit status. Returns the full set (caps are a human-output concern).
    """
    conn = db.db.conn  # type: ignore[attr-defined]
    declared, linked = _declared_and_linked(db)
    all_declared = [p for paths in declared.values() for p in paths]

    observed: dict[str, list[tuple[str, int]]] = {}
    for decision_id, path, commit_count in conn.execute("SELECT decision_id, path, commit_count FROM observed_governs"):
        observed.setdefault(decision_id, []).append((path, commit_count))

    # DF: distinct decisions that *repeat-touch* a path (cross-decision rarity).
    df: dict[str, set[str]] = {}
    for decision_id, rows in observed.items():
        for path, commit_count in rows:
            if commit_count >= _MG_REPEAT_TOUCH_MIN:
                df.setdefault(path, set()).add(decision_id)

    findings: list[MissingGovernance] = []
    for decision_id, rows in observed.items():
        own_declared = declared.get(decision_id, [])
        candidates: list[GovernanceCandidate] = []
        for path, commit_count in rows:
            if commit_count < _MG_REPEAT_TOUCH_MIN:
                continue  # thin attribution / squash over-attribution
            if any(_path_covers(d, path) for d in own_declared):
                continue  # already declared by this decision
            if any(_path_covers(d, path) for d in all_declared):
                continue  # owned by some decision — not a missing-governance gap
            if _is_structural_noise(path):
                continue
            df_count = len(df.get(path, ()))
            if df_count >= _MG_SHARED_FLOOR:
                continue  # shared infra, no single owner
            candidates.append(GovernanceCandidate(path=path, commit_count=commit_count, distinct_decisions=df_count))
        if not candidates:
            continue
        candidates.sort(key=lambda c: (-c.commit_count, c.distinct_decisions, c.path))
        findings.append(
            MissingGovernance(
                decision_id=decision_id,
                linked_commit_count=linked.get(decision_id, 0),
                observed_path_count=len(rows),
                candidates=tuple(candidates),
            )
        )
    findings.sort(key=lambda f: (-f.candidates[0].commit_count, f.decision_id))
    return findings


def broad_governance(db: IndexDB, threshold: int = _BROAD_GOVERNS_THRESHOLD) -> list[BroadGovernance]:
    """Advisory (B11): decisions whose declared `governs:` surface is broad or overlapping.

    Path-only and index-derived (no git). ``hot_file_overlap_count`` counts a
    decision's governed paths that another decision also governs — the Case-3
    signal where `governs:` drifted from "files owned" toward "files touched".
    """
    declared, linked = _declared_and_linked(db)
    path_owners: dict[str, set[str]] = {}
    for did, paths in declared.items():
        for p in paths:
            path_owners.setdefault(p, set()).add(did)

    findings: list[BroadGovernance] = []
    for did, paths in declared.items():
        gc = len(paths)
        if gc < threshold:
            continue
        exact = sum(1 for p in paths if not p.endswith("/"))
        directory = gc - exact
        lc = linked.get(did, 0)
        ratio = round(gc / lc, 2) if lc else float(gc)
        hot = sum(1 for p in paths if len(path_owners.get(p, ())) > 1)
        findings.append(BroadGovernance(did, gc, exact, directory, lc, ratio, hot))
    findings.sort(key=lambda f: f.governs_count, reverse=True)
    return findings


def lifecycle_drift(
    db: IndexDB,
    stale: list[StaleDecision],
    dead: list[DeadGovernance],
) -> list[LifecycleDrift]:
    """Advisory (B10/B9): decisions whose lifecycle status has drifted from reality.

    ``complete_but_not_terminal`` — every primary acceptance criterion is checked
    and commits are attached, but the status is still non-terminal (Agentkith
    Case 4). ``terminal_but_governance_dead`` / ``_stale`` — a terminal-success
    decision whose governance has since rotted. Never affects exit status.
    """
    from decree.commands.report import is_terminal_success

    conn = db.db.conn  # type: ignore[attr-defined]
    decisions = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT id, type, status FROM decisions")}
    ac_counts: dict[str, tuple[int, int]] = {}
    for did, done, total in conn.execute(
        "SELECT decision_id, SUM(done), COUNT(*) FROM acceptance_criteria WHERE deferred = 0 GROUP BY decision_id"
    ):
        ac_counts[did] = (int(done or 0), int(total or 0))
    linked: dict[str, int] = {
        row[0]: row[1]
        for row in conn.execute("SELECT decision_id, COUNT(DISTINCT sha) FROM commits GROUP BY decision_id")
    }
    doctypes = {dt.name: dt for dt in load_doc_types()}
    stale_ids = {sd.decision_id for sd in stale}
    dead_ids = {dg.decision_id for dg in dead}

    findings: list[LifecycleDrift] = []
    for did in sorted(decisions):
        type_name, status = decisions[did]
        dt = doctypes.get(type_name)
        if is_terminal_success(dt, status):
            if did in dead_ids:
                findings.append(
                    LifecycleDrift(
                        did,
                        type_name,
                        status,
                        "terminal_but_governance_dead",
                        f"{did} is {status} (terminal) but its declared governance is dead (unobserved in commits).",
                    )
                )
            elif did in stale_ids:
                findings.append(
                    LifecycleDrift(
                        did,
                        type_name,
                        status,
                        "terminal_but_governance_stale",
                        f"{did} is {status} (terminal) but its governed files have churned since (stale).",
                    )
                )
            continue
        done, total = ac_counts.get(did, (0, 0))
        if total > 0 and done == total and linked.get(did, 0) >= 1:
            findings.append(
                LifecycleDrift(
                    did,
                    type_name,
                    status,
                    "complete_but_not_terminal",
                    f"{did} has {done}/{total} primary ACs done and {linked[did]} commit(s) attached, "
                    f"but status is '{status}'. Transition it, or move incomplete work to a deferred section.",
                )
            )
    return findings


def health(
    db: IndexDB,
    project_root: Path,
    threshold_commits: int,
    threshold_days: int,
) -> HealthReport:
    """Compose the full health report — stale, ungoverned, and dead governance."""
    stale = stale_decisions(db, project_root, threshold_commits)
    dead = dead_governance(db)
    return HealthReport(
        stale_decisions=tuple(stale),
        ungoverned_hotspots=tuple(ungoverned_hotspots(db, project_root, threshold_commits, threshold_days)),
        threshold_commits=threshold_commits,
        threshold_days=threshold_days,
        dead_governance=tuple(dead),
        unobserved_decision_ids=tuple(unobserved_decisions(db)),
        last_rebuilt_at=db.status().last_rebuilt_at,
        missing_governance=tuple(missing_governance(db)),
        lifecycle_drift=tuple(lifecycle_drift(db, stale, dead)),
        broad_governance=tuple(broad_governance(db)),
    )


# ── Formatters ─────────────────────────────────────────────


def _format_human(report: HealthReport) -> str:
    from datetime import datetime

    lines: list[str] = []
    if report.stale_decisions:
        lines.append("Stale decisions (governed files have churned without the decision being touched):")
        lines.append("")
        for sd in report.stale_decisions:
            when = (
                datetime.fromtimestamp(sd.last_touched_ts, tz=UTC).date().isoformat()
                if sd.last_touched_ts > 0
                else "unknown"
            )
            lines.append(f"  {sd.decision_id}   {sd.churn_count} commits since {when} on governs paths:")
            for path, count in sd.governed_paths:
                lines.append(f"    {path}  ({count} commits)")
            lines.append("")
    else:
        lines.append("Stale decisions: none (all governed paths quiet).")
        lines.append("")

    if report.ungoverned_hotspots:
        lines.append("Ungoverned hotspots (high churn, no governing decision):")
        lines.append("")
        for h in report.ungoverned_hotspots:
            lines.append(f"  {h.path}  {h.commit_count} commits in last {h.since_days} days — no governing decision")
        lines.append("")
    else:
        lines.append("Ungoverned hotspots: none above threshold.")
        lines.append("")

    if report.dead_governance:
        lines.append("Dead governance (declared governs paths no trailer-linked commit has touched):")
        lines.append("")
        for dg in report.dead_governance:
            lines.append(f"  {dg.decision_id}   untouched by its {dg.linked_commit_count} linked commit(s):")
            for p in dg.paths:
                lines.append(f"    {p}")
        lines.append("")
    else:
        lines.append("Dead governance: none (every declared path with a commit basis was touched).")
        lines.append("")

    if report.missing_governance:
        shown = report.missing_governance[:_MG_TOP_DECISIONS]
        decisions_suffix = (
            f" (top {_MG_TOP_DECISIONS} of {len(report.missing_governance)} decisions)"
            if len(report.missing_governance) > len(shown)
            else ""
        )
        lines.append(
            "Suggested governance (advisory — ungoverned files with a proposed owner; "
            f"does not affect exit status){decisions_suffix}:"
        )
        lines.append("")
        for mg in shown:
            cands = mg.candidates[:_MG_TOP_CANDIDATES]
            more = f"  (+{len(mg.candidates) - len(cands)} more)" if len(mg.candidates) > len(cands) else ""
            lines.append(
                f"  {mg.decision_id}   from {mg.linked_commit_count} linked commit(s) "
                f"touching {mg.observed_path_count} path(s):{more}"
            )
            for c in cands:
                shared = (
                    "" if c.distinct_decisions <= 1 else f", shared with {c.distinct_decisions - 1} other decision(s)"
                )
                lines.append(f"    {c.path}  (touched in {c.commit_count} commits{shared})")
        lines.append("")
    else:
        lines.append("Suggested governance: none (no repeat-touched undeclared paths).")
        lines.append("")

    observed_as_of = report.last_rebuilt_at or "unknown"
    lines.append(
        f"  observed as of {observed_as_of}; "
        f"{len(report.unobserved_decision_ids)} decision(s) have no trailer-linked "
        "commits (governance unobservable)."
    )
    lines.append("")

    if report.lifecycle_drift:
        lines.append(f"Lifecycle drift ({len(report.lifecycle_drift)}) — advisory:")
        for ld in report.lifecycle_drift:
            lines.append(f"  ~ {ld.decision_id} [{ld.reason}]: {ld.detail}")
        lines.append("")

    if report.broad_governance:
        lines.append(f"Broad governance ({len(report.broad_governance)}) — advisory:")
        for bg in report.broad_governance:
            lines.append(
                f"  ~ {bg.decision_id}: governs {bg.governs_count} "
                f"({bg.exact_governs_count} exact / {bg.directory_governs_count} dir), "
                f"{bg.hot_file_overlap_count} shared hot file(s), "
                f"ratio {bg.governs_to_commits_ratio}"
            )
        lines.append("")

    lines.append(f"Thresholds: --threshold-commits={report.threshold_commits} --threshold-days={report.threshold_days}")
    return "\n".join(lines)


def _report_to_dict(report: HealthReport) -> dict:
    return {
        "stale_decisions": [
            {
                "decision_id": sd.decision_id,
                "type": sd.type,
                "last_touched_ts": sd.last_touched_ts,
                "churn_count": sd.churn_count,
                "governed_paths": [{"path": p, "count": c} for (p, c) in sd.governed_paths],
            }
            for sd in report.stale_decisions
        ],
        "ungoverned_hotspots": [
            {
                "path": h.path,
                "commit_count": h.commit_count,
                "since_days": h.since_days,
            }
            for h in report.ungoverned_hotspots
        ],
        "dead_governance": [
            {
                "decision_id": dg.decision_id,
                "paths": list(dg.paths),
                "linked_commit_count": dg.linked_commit_count,
            }
            for dg in report.dead_governance
        ],
        "missing_governance": [
            {
                "decision_id": mg.decision_id,
                "linked_commit_count": mg.linked_commit_count,
                "observed_path_count": mg.observed_path_count,
                "candidates": [
                    {
                        "path": c.path,
                        "commit_count": c.commit_count,
                        "distinct_decisions": c.distinct_decisions,
                    }
                    for c in mg.candidates
                ],
            }
            for mg in report.missing_governance
        ],
        "lifecycle_drift": [
            {
                "decision_id": ld.decision_id,
                "type": ld.type,
                "status": ld.status,
                "reason": ld.reason,
                "detail": ld.detail,
            }
            for ld in report.lifecycle_drift
        ],
        "broad_governance": [
            {
                "decision_id": bg.decision_id,
                "governs_count": bg.governs_count,
                "exact_governs_count": bg.exact_governs_count,
                "directory_governs_count": bg.directory_governs_count,
                "linked_commit_count": bg.linked_commit_count,
                "governs_to_commits_ratio": bg.governs_to_commits_ratio,
                "hot_file_overlap_count": bg.hot_file_overlap_count,
            }
            for bg in report.broad_governance
        ],
        "unobserved_decisions": list(report.unobserved_decision_ids),
        "observed_as_of": report.last_rebuilt_at,
        "threshold_commits": report.threshold_commits,
        "threshold_days": report.threshold_days,
    }


# ── CLI handlers ───────────────────────────────────────────


def _resolve_root(project_arg: str | None) -> Path:
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return get_project_root()


def _resolve_thresholds(args: argparse.Namespace) -> tuple[int, int]:
    """Resolve thresholds: CLI flags > [health] block > built-in defaults."""
    from decree.config import load_health_config

    try:
        cfg = load_health_config()
    except Exception:
        cfg = None
    t_commits = args.threshold_commits if args.threshold_commits is not None else (cfg.threshold_commits if cfg else 10)
    t_days = args.threshold_days if args.threshold_days is not None else (cfg.threshold_days if cfg else 30)
    return t_commits, t_days


def health_run(args: argparse.Namespace) -> int:
    """`decree health` — full report (stale + ungoverned)."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 1

    if not _is_git_repo(root):
        info("health", "not a git repository — health requires git history. exit 0.")
        return 0

    t_commits, t_days = _resolve_thresholds(args)
    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        info(
            "health",
            "index not found; run `decree index rebuild` first. "
            "Hotspot detection still runs but stale-decision check is empty.",
        )

    report = health(db, root, t_commits, t_days)

    if getattr(args, "json", False):
        print(json.dumps(_report_to_dict(report), indent=2, sort_keys=True))
    else:
        print(_format_human(report))

    has_findings = bool(report.stale_decisions or report.ungoverned_hotspots or report.dead_governance)
    if has_findings:
        return 1
    if not getattr(args, "json", False):
        success("health: clean.")
    return 0


def stale_run(args: argparse.Namespace) -> int:
    """`decree stale` — alias for `decree health`."""
    return health_run(args)
