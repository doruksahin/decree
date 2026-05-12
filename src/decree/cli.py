"""Decree CLI — software decision lifecycle toolkit."""

import argparse
import sys

from decree.commands import graph, index, lint, new, progress, status

EPILOG = """\
document chain:
  PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation

examples:
  decree new prd "User Authentication"
  decree new adr "Auth via JWT"
  decree new spec "Token Storage API"
  decree status ADR-0001 accept
  decree status PRD-001 approve
  decree lint
  decree progress

config:
  Document types are defined in decree.toml under [types.*].
  Each type has: prefix, digits, statuses, transitions, warn_on_reference.
  C4 architecture support: add [types.spec.c4] with enabled, id_field, levels.

claude code skills (if decree plugin is installed):
  /decree:init   Scaffold decree/ folder with working PRD/ADR/SPEC examples
  /decree:prd    Create a PRD with section guidance and lint validation
  /decree:adr    Create an ADR with reference discovery across existing docs
  /decree:spec   Create a SPEC with stale-reference warnings
  /decree:lint   Validate all documents, create tasks per error found
"""


def main() -> int:
    """Multi-type document CLI (the `decree` entry point)."""
    parser = argparse.ArgumentParser(
        prog="decree",
        description="Decree — software decision lifecycle toolkit. "
        "Manage PRDs, ADRs, and SPECs with cross-type references, "
        "status enforcement, and validation.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── new ──────────────────────────────────────────────────
    p_new = subparsers.add_parser(
        "new",
        help="Create a new document (PRD, ADR, or SPEC)",
        description="Create a new document from the type's template. "
        "Auto-numbers, slugifies the title, stamps today's date, "
        "and regenerates the type's index.",
    )
    p_new.add_argument(
        "doc_type",
        help="Document type: adr, prd, spec (must be configured in decree.toml)",
    )
    p_new.add_argument(
        "title",
        help='Document title (e.g. "Use Redis for caching")',
    )

    # ── status ───────────────────────────────────────────────
    p_status = subparsers.add_parser(
        "status",
        help="Transition a document's status",
        description="Enforce status lifecycle transitions. "
        "Only valid transitions are allowed (e.g. proposed → accepted). "
        "For supersede: pass the replacement ID as the third argument.",
    )
    p_status.add_argument(
        "doc_id",
        help="Document ID (e.g. ADR-0001, PRD-001, SPEC-001). Type is auto-detected from prefix.",
    )
    p_status.add_argument(
        "action",
        help="Action to perform. Available actions depend on the document type "
        "(e.g. accept, reject, approve, implement, archive, supersede).",
    )
    p_status.add_argument(
        "target_id",
        nargs="?",
        default=None,
        help="Replacement document ID (required for supersede action only).",
    )

    # ── lint ─────────────────────────────────────────────────
    p_lint = subparsers.add_parser(
        "lint",
        help="Validate all documents and cross-type references",
        description="Validate all configured document types. Checks: "
        "frontmatter validity, required sections, supersede symmetry, "
        "duplicate IDs, dangling references, stale references "
        "(to rejected/deprecated/superseded/archived docs), "
        "and self-references.",
    )
    p_lint.add_argument(
        "--check-attachments",
        action="store_true",
        help="Validate that attachment file paths exist on disk",
    )

    # ── index (sub-namespace: rebuild, status, verify, regenerate) ──
    p_index = subparsers.add_parser(
        "index",
        help="SQLite provenance index — rebuild, status, verify; or regenerate the per-type index.md tables",
        description="Manage the SQLite provenance index that backs `decree why`, `decree refs`, "
        "the MCP server, and other query commands. The legacy per-type markdown index.md "
        "tables are regenerated via `decree index regenerate`.",
    )
    index_subs = p_index.add_subparsers(dest="index_action", required=True)

    p_rebuild = index_subs.add_parser("rebuild", help="Full rebuild of the SQLite provenance index from frontmatter")
    p_rebuild.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    p_idx_status = index_subs.add_parser("status", help="Show schema version, last-rebuilt-at, and row counts")
    p_idx_status.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    p_verify = index_subs.add_parser("verify", help="Compare on-disk frontmatter against the index; report drift")
    p_verify.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")
    p_verify.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")

    index_subs.add_parser(
        "regenerate",
        help="Regenerate the per-type index.md markdown tables (legacy behavior)",
        description="Generate a markdown table listing all documents per type, sorted by status priority then number.",
    )

    # ── graph ────────────────────────────────────────────────
    subparsers.add_parser(
        "graph",
        help="Generate Mermaid diagrams (timeline, supersede chain, status distribution)",
        description="Append Mermaid diagram blocks to each type's index.md. "
        "Preserves hand-authored content above the GENERATED marker.",
    )

    # ── progress ─────────────────────────────────────────────
    subparsers.add_parser(
        "progress",
        help="Show checkbox completion across all documents",
        description="Scan all documents for markdown checkboxes (- [ ] / - [x]) "
        "and report per-document and overall completion with progress bars.",
    )

    # ── ddd ─────────────────────────────────────────────────
    p_ddd = subparsers.add_parser(
        "ddd",
        help="Decree Driven Development — show current phase and next action",
        description="Run a phase assessment: read the corpus, identify which lifecycle phase "
        "the project is in (ideation / architecture / design / planning / implementation / completion / done), "
        "and print the suggested next action. Offline, no LLM calls.",
    )
    p_ddd.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")
    p_ddd.add_argument("--quiet", action="store_true", help="Suppress document-chain details; print only phase + next action")
    p_ddd.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    # ── why ─────────────────────────────────────────────────
    p_why = subparsers.add_parser(
        "why",
        help="Show which decisions govern a file or directory",
        description="Query the SQLite provenance index for decisions whose `governs:` "
        "frontmatter covers the given repo-relative path. Exact matches outrank "
        "prefix (directory) matches; results are sorted by status priority then date desc.",
    )
    p_why.add_argument("path", help="Repo-relative path (optionally `path#symbol`)")
    p_why.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")
    p_why.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    # ── refs ────────────────────────────────────────────────
    p_refs = subparsers.add_parser(
        "refs",
        help="Show the reverse graph for a decision (who references it, what it governs, …)",
        description="Query the SQLite provenance index for everything connected to "
        "the given decision id: forward refs, reverse refs, supersedes chain (via networkx), "
        "governed paths, and (post-SPEC-006) implementing commits.",
    )
    p_refs.add_argument("decision_id", help="Decision ID (e.g. SPEC-001, PRD-003, ADR-0002)")
    p_refs.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")
    p_refs.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    # ── find-root ───────────────────────────────────────────
    subparsers.add_parser(
        "find-root",
        help="Print the path to the enclosing decree project root",
        description="Walk upward from cwd to find the directory containing decree.toml. "
        "Prints the path on stdout; exits 1 if not found.",
    )

    # ── commit ──────────────────────────────────────────────
    p_commit = subparsers.add_parser(
        "commit",
        help="git commit wrapper that adds Implements:/Refs:/Fixes: trailers",
        description="Wraps `git commit` with structural trailer construction via "
        "`git interpret-trailers`. Inspects staged files, optionally infers the "
        "active SPEC (most-likely match against `governs:` paths among in-flight SPECs), "
        "and appends `Implements:`, `Refs:`, and `Fixes:` trailers to the commit message. "
        "After a successful commit, syncs the `commits` table so `decree refs SPEC-NNN` "
        "surfaces the new commit immediately.",
    )
    p_commit.add_argument("-m", "--message", default=None, help="Commit message (passed through to git commit)")
    p_commit.add_argument(
        "--implements",
        action="append",
        default=None,
        metavar="ID",
        help="Add `Implements: <ID>` trailer (repeatable). Disables inference when given.",
    )
    p_commit.add_argument(
        "--refs",
        action="append",
        default=None,
        metavar="ID",
        help="Add `Refs: <ID>` trailer (repeatable).",
    )
    p_commit.add_argument(
        "--fixes",
        action="append",
        default=None,
        metavar="ID",
        help="Add `Fixes: <ID>` trailer (repeatable).",
    )
    p_commit.add_argument(
        "--no-infer",
        action="store_true",
        help="Skip active-SPEC inference entirely (don't auto-add `Implements:`).",
    )
    p_commit.add_argument(
        "--amend",
        action="store_true",
        help="Pass through to `git commit --amend`.",
    )
    p_commit.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    # ── hook ────────────────────────────────────────────────
    p_hook = subparsers.add_parser(
        "hook",
        help="Install or uninstall the Claude Code stop hook",
        description="Manage the Claude Code stop hook that runs `decree ddd` at session end "
        "and writes a snapshot for the next session to read.",
    )
    p_hook.add_argument(
        "action",
        choices=("install", "uninstall", "status"),
        help="What to do",
    )
    p_hook.add_argument(
        "--type",
        default="claude-stop",
        choices=("claude-stop",),
        help="Which hook type (currently only claude-stop is supported)",
    )

    # ── mcp (sub-namespace: serve) ──────────────────────────
    p_mcp = subparsers.add_parser(
        "mcp",
        help="Model Context Protocol server — expose decree's query API to agents",
        description="Run the Model Context Protocol server that exposes decree's "
        "queries (currently `why` and `refs`) as agent-callable tools over stdio. "
        "v1 ships two tools; future SPECs add `stale`, `health`, and `intent_review` "
        "as their underlying library functions land.",
    )
    mcp_subs = p_mcp.add_subparsers(dest="mcp_action", required=True)

    p_mcp_serve = mcp_subs.add_parser(
        "serve",
        help="Run the MCP stdio server bound to a decree project",
        description="Resolve the project root (explicit --project, else cwd-walk), "
        "open the SQLite index, and enter the FastMCP stdio loop. The server runs "
        "until stdin closes or it receives a termination signal. One server, one "
        "project, one index — cross-project queries require running multiple servers.",
    )
    p_mcp_serve.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd-walk)",
    )

    # ── health / stale (SPEC-008) ───────────────────────────
    def _add_health_args(p):
        p.add_argument(
            "--json",
            action="store_true",
            help="Emit JSON for programmatic consumers",
        )
        p.add_argument(
            "--project",
            default=None,
            help="Operate on the project at this path (default: cwd)",
        )
        p.add_argument(
            "--threshold-commits",
            type=int,
            default=None,
            help="Stale/hotspot commit threshold (default: 10 or [health] block)",
        )
        p.add_argument(
            "--threshold-days",
            type=int,
            default=None,
            help="Ungoverned-hotspot lookback window in days (default: 30)",
        )

    p_health = subparsers.add_parser(
        "health",
        help="Show stale decisions and ungoverned hotspots (SPEC-008)",
        description="Surface coherence and churn health: decisions whose governed "
        "files have churned without the decision being touched (stale), and high-churn "
        "files that no decision governs (ungoverned hotspots). Exit 0 if clean, 1 if "
        "findings.",
    )
    _add_health_args(p_health)

    p_stale = subparsers.add_parser(
        "stale",
        help="Alias for `decree health` (SPEC-008)",
        description="Same as `decree health`.",
    )
    _add_health_args(p_stale)

    args = parser.parse_args()
    from decree.commands import commit as commit_cmd
    from decree.commands import ddd as ddd_cmd
    from decree.commands import health as health_cmd
    from decree.commands import hook as hook_cmd
    from decree.commands import index_db_cli
    from decree.commands import mcp_server as mcp_cmd
    from decree.commands import queries as queries_cmd

    # The `index` command has sub-actions: rebuild, status, verify, regenerate.
    def _index_dispatch(a):
        action = a.index_action
        if action == "rebuild":
            return index_db_cli.rebuild_run(a)
        if action == "status":
            return index_db_cli.status_run(a)
        if action == "verify":
            return index_db_cli.verify_run(a)
        if action == "regenerate":
            return index.run(a)
        raise ValueError(f"unknown index action: {action}")

    # The `mcp` command has sub-actions: serve (more may land in future SPECs).
    def _mcp_dispatch(a):
        action = a.mcp_action
        if action == "serve":
            return mcp_cmd.mcp_serve_run(a)
        raise ValueError(f"unknown mcp action: {action}")

    commands = {
        "new": new.run,
        "status": status.run,
        "lint": lint.run,
        "index": _index_dispatch,
        "graph": graph.run,
        "progress": progress.run,
        "ddd": ddd_cmd.run,
        "find-root": ddd_cmd.find_root_run,
        "hook": hook_cmd.run,
        "why": queries_cmd.why_run,
        "refs": queries_cmd.refs_run,
        "commit": commit_cmd.commit_run,
        "mcp": _mcp_dispatch,
        "health": health_cmd.health_run,
        "stale": health_cmd.stale_run,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
