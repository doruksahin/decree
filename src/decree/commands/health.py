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
import subprocess
from datetime import UTC
from pathlib import Path

from decree.index_db import IndexDB, default_db_path
from decree.log import fail, info, success

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
class HealthReport:
    stale_decisions: tuple[StaleDecision, ...]
    ungoverned_hotspots: tuple[UngovernedHotspot, ...]
    threshold_commits: int
    threshold_days: int


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


def health(
    db: IndexDB,
    project_root: Path,
    threshold_commits: int,
    threshold_days: int,
) -> HealthReport:
    """Compose the full health report — stale decisions + ungoverned hotspots."""
    return HealthReport(
        stale_decisions=tuple(stale_decisions(db, project_root, threshold_commits)),
        ungoverned_hotspots=tuple(ungoverned_hotspots(db, project_root, threshold_commits, threshold_days)),
        threshold_commits=threshold_commits,
        threshold_days=threshold_days,
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

    has_findings = bool(report.stale_decisions or report.ungoverned_hotspots)
    if has_findings:
        return 1
    if not getattr(args, "json", False):
        success("health: clean.")
    return 0


def stale_run(args: argparse.Namespace) -> int:
    """`decree stale` — alias for `decree health`."""
    return health_run(args)
