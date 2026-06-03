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

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from decree.commands.queries import _status_priority, why
from decree.index_db import IndexDB

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
