"""`decree mcp serve` — MCP (Model Context Protocol) server exposing decree's
query API as agent-callable tools.

This is the thin protocol layer described by SPEC-007. It wraps the library
functions shipped in SPEC-005 (`commands.queries.why` / `commands.queries.refs`)
behind FastMCP's stdio transport. No new query logic lives here — only:

  1. project-root resolution (mirrors `commands.queries._resolve_root`),
  2. error-shaped responses for missing/stale indexes,
  3. CLI <-> JSON shape preservation so agents and `--json` consumers see one
     identical schema,
  4. **the LLM-facing docstrings**, which are the actual product of this SPEC.

Each tool docstring follows the 5-section structure mandated by SPEC-007:
summary / Args / Returns / When to call / When not to call.

Future SPECs (008 staleness/health, 009 intent_review) will add more
`@mcp.tool()` functions here as their underlying library functions ship.
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


def _stale_warning(db: IndexDB, root: Path) -> str | None:
    """Return a one-line drift warning if the index is stale, else None."""
    findings = db.verify(root)
    real_drift = [f for f in findings if f.kind != "index_missing"]
    if real_drift:
        return (
            f"index is stale ({len(real_drift)} drift findings); "
            "run `decree index rebuild` for current results"
        )
    return None


# ── Tools ────────────────────────────────────────────────────


@mcp.tool()
def why(path: str) -> dict:
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

    Returns:
        A dict with the same shape as `decree why <path> --json`:

            {
              "query": str,                      # the path as queried
              "match_count": int,                # number of governing decisions
              "matches": [
                {
                  "decision_id": str,            # e.g. "SPEC-007"
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

        Empty `matches` is a valid, correct answer — it means *no* decision
        currently governs the path. Do NOT confabulate a match; abstention is
        the right behavior when the index says nothing.

        On a stale index a `"warning"` key is included with a one-line drift
        notice. On a missing index the response is
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

    warning = _stale_warning(db, root)
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
    if warning is not None:
        payload["warning"] = warning
    return payload


@mcp.tool()
def refs(decision_id: str) -> dict:
    """Return the full reference graph for a single decision document.

    Use this when you have a decision ID in hand (from `why`, a commit
    trailer, a doc cross-reference, or the user) and need to understand its
    surroundings: what it depends on, what depends on it, its supersedes
    chain, the files it governs, and the commits that implemented it.

    Args:
        decision_id: The decision identifier, exactly as it appears in
            frontmatter and filenames (e.g. `SPEC-007`, `PRD-003`, `ADR-0002`).
            Case-sensitive; the canonical form is uppercase prefix +
            zero-padded number per the project's `decree.toml`.

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
        On a stale index a `"warning"` key is added to the success payload.

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

    warning = _stale_warning(db, root)
    report = _refs_lib(db, decision_id)
    if report is None:
        return {
            "error": "unknown decision id",
            "decision_id": decision_id,
        }

    payload: dict = {
        "decision_id": report.decision_id,
        "metadata": asdict(report.metadata),
        "forward_refs": [asdict(r) for r in report.forward_refs],
        "reverse_refs": [asdict(r) for r in report.reverse_refs],
        "supersedes_chain": list(report.supersedes_chain),
        "governs": [asdict(g) for g in report.governs],
        "commits": [asdict(c) for c in report.commits],
    }
    if warning is not None:
        payload["warning"] = warning
    return payload


# ── CLI handler ──────────────────────────────────────────────


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
            "index not found; tools will return error responses until "
            "`decree index rebuild` is run",
        )

    mcp.run()
    return 0
