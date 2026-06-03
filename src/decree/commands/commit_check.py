"""`decree commit-check` — deterministic trailer-coverage core library.

Implements SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J. Phase 1 is the pure core
library only: four functions, no argparse/CLI/MCP (those are later
phases).

What it computes. Given the paths a diff touches, the set of *governed
changes* = `(path, decision)` pairs where `decision` is **in-flight**
(`_status_priority(type, status) == 1`, mirroring
`commit.infer_active_spec`) and declares `governs:` over `path`. A pair
is **covered** when a matching `Implements:/Refs:/Fixes: <decision-id>`
trailer is present in the relevant commit message(s). The result is a
gateable coverage fraction plus the uncovered pairs.

Design notes:
  * Reads **only the authoritative declared layer** via `queries.why()` —
    never `observed_governs`/`commits`-as-truth, never an LLM.
  * Trailer parsing shells out to the canonical
    `git interpret-trailers --parse` plumbing — the same parser
    `index_db.sync_commits_from_git` uses. Never a Python regex.
  * Pure functions: no IO coupling beyond the git plumbing the trailer
    parse inherently needs. Writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from decree.commands.intent_review import _read_diff_source
from decree.commands.queries import _status_priority, why
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info

# ── Public dataclasses ───────────────────────────────────────


@dataclass(frozen=True)
class GovernedChange:
    """One `(path, decision)` pair where an in-flight decision governs `path`."""

    path: str
    decision_id: str
    type: str
    title: str


@dataclass(frozen=True)
class Coverage:
    """Trailer-coverage result for a set of governed changes."""

    covered: int
    total: int
    fraction: float
    uncovered: list[GovernedChange] = field(default_factory=list)


# ── governed_changes ────────────────────────────────────────


def governed_changes(db: IndexDB, paths: Iterable[str]) -> list[GovernedChange]:
    """Return the in-flight declared `(path, decision)` records for `paths`.

    For each path we ask `queries.why()` for the declared governing
    decisions, then keep only those that are **in-flight**
    (`_status_priority(type, status) == 1`). Terminal-success (0) and
    warn-on-reference (2) decisions are excluded, as are ungoverned
    paths. A single path may yield multiple records if multiple in-flight
    decisions govern it.
    """
    changes: list[GovernedChange] = []
    for path in paths:
        for gd in why(db, path):
            if _status_priority(gd.type, gd.status) != 1:
                continue
            changes.append(
                GovernedChange(
                    path=path,
                    decision_id=gd.decision_id,
                    type=gd.type,
                    title=gd.title,
                )
            )
    return changes


# ── trailer parsing (canonical git plumbing) ────────────────


def trailer_ids(message_text: str) -> set[str]:
    """Return the set of decision IDs from `Implements:/Refs:/Fixes:` trailers.

    Uses `git interpret-trailers --parse` — the same canonical parser
    `index_db.sync_commits_from_git` relies on. Never a Python regex.
    Multi-value trailers (`Implements: SPEC-A, SPEC-B`) are comma-split.
    A message with no relevant trailers returns an empty set.
    """
    if not message_text.strip():
        return set()

    parse = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=message_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if parse.returncode != 0:
        return set()

    ids: set[str] = set()
    for line in parse.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip() not in ("Implements", "Refs", "Fixes"):
            continue
        for raw in value.split(","):
            decision_id = raw.strip()
            if decision_id:
                ids.add(decision_id)
    return ids


def range_trailer_ids(repo_path: Path, ref: str) -> set[str]:
    """Return the union of trailer IDs across all commits in `REF..HEAD`.

    This is what makes coverage **squash-safe**: the trailer may live on
    any single commit in the range, and the squashed merge subject need
    not carry it. We gather every commit body in `REF..HEAD` (one
    `git log` call) and feed the concatenation through the same canonical
    trailer parser. Order-independent by construction (it's a set union).
    """
    log = subprocess.run(
        ["git", "-C", str(repo_path), "log", "--format=%B%x1e", f"{ref}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode != 0:
        return set()

    ids: set[str] = set()
    for body in log.stdout.split("\x1e"):
        if not body.strip():
            continue
        ids |= trailer_ids(body)
    return ids


# ── coverage ────────────────────────────────────────────────


def coverage(governed: Iterable[GovernedChange], trailers: set[str]) -> Coverage:
    """Compute trailer coverage over `governed` given the present trailer IDs.

    A governed change is covered when its `decision_id` is in `trailers`.
    With **zero** governed changes the result is vacuously fully covered
    (`total=0`, `fraction=1.0`) — there is nothing to gate and no
    divide-by-zero.
    """
    governed = list(governed)
    total = len(governed)
    uncovered = [gc for gc in governed if gc.decision_id not in trailers]
    covered = total - len(uncovered)
    fraction = 1.0 if total == 0 else covered / total
    return Coverage(covered=covered, total=total, fraction=fraction, uncovered=uncovered)


# ── CLI plumbing (Phase 2) ──────────────────────────────────


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root (explicit --project wins, else cwd-walk).

    Mirrors ``intent_review._resolve_root``.
    """
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
    """Open the index DB for the resolved project.

    Returns ``(db, root, rc)``. A bad project (no ``decree.toml``) or a missing
    index both fail with ``rc == 2`` — commit-check cannot gate without the
    declared layer, and exit 2 is the command's "can't run / config error"
    code (the same code used when no input mode is supplied).
    """
    try:
        root = _resolve_root(project_arg)
    except FileNotFoundError as e:
        error("commit-check", str(e))
        return None, None, 2

    os.chdir(root)
    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()

    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        error(
            "commit-check",
            "index not found; run `decree index rebuild` first.",
        )
        return None, root, 2
    return db, root, 0


def _resolve_trailers(args: argparse.Namespace, root: Path) -> tuple[set[str] | None, str | None, int]:
    """Resolve the trailer-id set and the report ``mode``.

    Trailer source precedence:
      1. ``--diff-base REF`` → union of trailers across ``REF..HEAD`` (CI mode,
         squash-safe). mode == ``diff-base``.
      2. ``--message PATH``  → trailers from a single commit message (commit-msg
         hook mode). mode == ``message``.
      3. otherwise (staged, no message/base) → exit 2 with a hint. There is no
         commit message to read and no range to scan.

    The ``--diff`` flag only ever supplies *paths*; in ``--diff`` mode the
    trailers still come from ``--message`` (or, if neither base nor message is
    given, mode 3's exit-2 applies). Returns ``(trailers, mode, rc)`` where a
    non-``None`` ``trailers`` means success (``rc`` is 0).
    """
    diff_base = getattr(args, "diff_base", None)
    message = getattr(args, "message", None)

    if diff_base:
        return range_trailer_ids(root, diff_base), "diff-base", 0

    if message:
        try:
            text = Path(message).read_text()
        except OSError as e:
            error("commit-check", f"--message file not readable: {e}")
            return None, None, 2
        # mode reflects where the *changed paths* come from: a --diff source
        # still reports as "diff", otherwise it is the commit-msg "message" mode.
        mode = "diff" if getattr(args, "diff", None) else "message"
        return trailer_ids(text), mode, 0

    error(
        "commit-check",
        "no trailer source: supply --message (commit-msg mode) or --diff-base (CI mode).",
    )
    return None, None, 2


def _gate_exit(cov: Coverage, *, strict: bool, min_coverage: int | None) -> int:
    """Decide the exit code from coverage + gate flags.

    - Fully covered (or vacuously, zero governed) → 0.
    - Uncovered with no gate (no ``--strict``, no ``--min-coverage``) → 0
      (advisory).
    - ``--strict`` → 1 on any uncovered.
    - ``--min-coverage N`` → 1 when the covered percentage is below ``N``.
    Both gates may apply; either failing yields 1.
    """
    if not cov.uncovered:
        return 0
    if strict:
        return 1
    if min_coverage is not None:
        pct = cov.fraction * 100
        if pct < min_coverage:
            return 1
    return 0


def _payload(
    governed: list[GovernedChange],
    cov: Coverage,
    *,
    mode: str,
    strict: bool,
    min_coverage: int | None,
    exit_code: int,
) -> dict:
    """Build the canonical commit-check JSON payload.

    This is the single formatter shared by the CLI ``--json`` path
    (``commit_check_run``) and the ``commit_check`` MCP tool, so the two can
    never drift. The shape is exactly the contract asserted in
    ``tests/test_commit_check.py::test_json_contract``.
    """
    uncovered_ids = {gc.decision_id for gc in cov.uncovered}
    return {
        "coverage": {
            "covered": cov.covered,
            "total": cov.total,
            "fraction": cov.fraction,
        },
        "governed_changes": [
            {
                "path": gc.path,
                "decision_id": gc.decision_id,
                "type": gc.type,
                "covered": gc.decision_id not in uncovered_ids,
            }
            for gc in governed
        ],
        "uncovered": [{"path": gc.path, "decision_id": gc.decision_id, "title": gc.title} for gc in cov.uncovered],
        "mode": mode,
        "strict": strict,
        "min_coverage": min_coverage,
        "exit": exit_code,
    }


def _format_human(cov: Coverage, mode: str) -> str:
    """Render the human-readable trailer-coverage report."""
    lines: list[str] = []
    lines.append(f"Commit check — {mode}")
    # Floor (not round) so the displayed % never contradicts the gate, which
    # compares the unrounded `fraction*100 < min_coverage` in `_gate_exit`.
    # 2/3 = 66.67% must show "66%", not "67%", or it would imply passing
    # `--min-coverage 67` while the gate actually fails.
    pct = int(cov.fraction * 100)
    lines.append(f"Trailer coverage ({cov.covered}/{cov.total}, {pct}%)")

    if cov.total == 0:
        lines.append("  no governed changes — nothing to gate.")
        return "\n".join(lines)

    if cov.uncovered:
        lines.append("")
        lines.append(f"Uncovered ({len(cov.uncovered)}):")
        for gc in cov.uncovered:
            lines.append(f"  • {gc.path} → {gc.decision_id} ({gc.title})")
            lines.append(f"    Consider `decree commit --implements {gc.decision_id}` so the commit links to the SPEC.")
    return "\n".join(lines)


def commit_check_run(args: argparse.Namespace) -> int:
    """`decree commit-check` — deterministic trailer-coverage gate CLI entry point."""
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    # Changed paths (reuses intent-review's diff-source resolver).
    try:
        changed_paths, _src_mode, _structured = _read_diff_source(args, root)
    except FileNotFoundError as e:
        error("commit-check", f"diff source not found: {e}")
        return 2
    except RuntimeError as e:
        error("commit-check", str(e))
        return 2

    # Trailer source + report mode.
    trailers, mode, trc = _resolve_trailers(args, root)
    if trailers is None:
        return trc
    assert mode is not None

    governed = governed_changes(db, changed_paths)
    cov = coverage(governed, trailers)

    strict = bool(getattr(args, "strict", False))
    min_coverage = getattr(args, "min_coverage", None)
    exit_code = _gate_exit(cov, strict=strict, min_coverage=min_coverage)

    if getattr(args, "json", False):
        payload = _payload(
            governed,
            cov,
            mode=mode,
            strict=strict,
            min_coverage=min_coverage,
            exit_code=exit_code,
        )
        print(json.dumps(payload, indent=2, sort_keys=False))
    else:
        print(_format_human(cov, mode))

    if exit_code == 1:
        info("commit-check", "exit 1: trailer coverage below threshold.")
    return exit_code
