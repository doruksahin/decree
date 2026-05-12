"""CLI subcommand handlers for the SQLite provenance index.

`decree index rebuild` — full rebuild from frontmatter.
`decree index status`  — schema version, last-rebuilt-at, row counts.
`decree index verify`  — drift detection (compares disk against index).

The existing `decree index` markdown-regeneration command is preserved under
`decree index regenerate`. The dispatch happens in cli.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from decree.index_db import IndexDB, default_db_path
from decree.log import error, info, success


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root from --project or cwd-walk."""
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    import os
    # Make sure caches reflect any cwd change
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return get_project_root()


# ── rebuild ─────────────────────────────────────────────────


def rebuild_run(args: argparse.Namespace) -> int:
    """`decree index rebuild` — full rebuild from frontmatter."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error("index", str(e))
        return 1

    # Switch cwd so load_all_types and friends pick up the right project
    import os

    os.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    db = IndexDB(default_db_path(root))
    info("index", f"rebuilding into {db.db_path.relative_to(root)}")
    stats = db.rebuild(root)
    info("index", f"decisions={stats.decisions}  refs={stats.refs}  governs={stats.governs}  acs={stats.acceptance_criteria}")
    success(f"index rebuilt in {stats.duration_ms}ms")
    return 0


# ── status ──────────────────────────────────────────────────


def status_run(args: argparse.Namespace) -> int:
    """`decree index status` — print schema version, last-rebuilt-at, row counts."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error("index", str(e))
        return 1

    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        error("index", f"no index at {status.db_path} — run `decree index rebuild`")
        return 1

    print(f"DB path:         {status.db_path}")
    print(f"Schema version:  {status.schema_version}")
    print(f"Last rebuilt at: {status.last_rebuilt_at}")
    print(f"Row counts:")
    for table, count in status.row_counts.items():
        print(f"  {table:<24} {count}")
    return 0


# ── verify ──────────────────────────────────────────────────


def verify_run(args: argparse.Namespace) -> int:
    """`decree index verify` — compare on-disk frontmatter against the index."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error("index", str(e))
        return 1

    import os

    os.chdir(root)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()

    db = IndexDB(default_db_path(root))
    findings = db.verify(root)

    if getattr(args, "json", False):
        print(
            json.dumps(
                [{"decision_id": f.decision_id, "kind": f.kind, "detail": f.detail} for f in findings],
                indent=2,
            )
        )
    else:
        if not findings:
            success("index verify: clean — 0 drift findings")
        else:
            for f in findings:
                print(f"  [{f.kind}] {f.decision_id}  {f.detail}")
            error("index", f"{len(findings)} drift findings")

    return 0 if not findings else 1
