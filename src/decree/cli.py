"""Decree CLI — software decision lifecycle toolkit."""

import argparse
import importlib
import json
import sys

from decree.log import error as _log_error
from decree.version import get_version

EPILOG = """\
document chain:
  PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation

examples:
  decree new prd "User Authentication" --bucket auth
  decree new adr "Auth via JWT" --bucket auth
  decree new spec "Token Storage API" --bucket auth
  decree new prd "Sprint Planning" --bucket delivery
  decree list --tree
  decree generate-html --output decree-board.html
  decree agents install --target all --scope project
  decree migrate governs --analyze --json
  decree migrate governs --apply-suggestions suggestions.json --apply --yes
  decree why src/auth/tokens.py
  decree intent-check --plan "Change token refresh" --files src/auth/tokens.py
  decree status ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ accept
  decree progress --changed --base origin/main
  decree lint

config:
  Document types are defined in decree.toml under [types.*].
  Each type has: prefix, statuses, transitions, warn_on_reference.
  New documents use explicit frontmatter IDs in TYPE-ULID format.
  C4 architecture support: add [types.spec.c4] with enabled, id_field, levels.

capability index:
  docs/index.md maps each capability to its command, responsibility, and
  recommended adoption sequence for new projects and LLM agents.

claude code skills (if decree plugin is installed):
  /decree:init   Scaffold decree/ folder with working PRD/ADR/SPEC examples
  /decree:prd    Create a PRD with section guidance and lint validation
  /decree:adr    Create an ADR with reference discovery across existing docs
  /decree:spec   Create a SPEC with stale-reference warnings
  /decree:lint   Validate all documents, create tasks per error found
  /decree:ddd    Check project state and suggest the next lifecycle action
"""


def _emit_json_error(args: argparse.Namespace, exc: Exception) -> None:
    """Emit decree's machine-readable error contract for ``--json`` consumers.

    On an unexpected (unhandled) error, callers that passed ``--json`` get a
    stable ``decree.error.v1`` object on stdout — instead of a Python traceback —
    plus a clean one-line summary on stderr. See docs/json-contracts.md.
    """
    command = getattr(args, "command", None)
    payload = {
        "schema": "decree.error.v1",
        "error": {
            "command": command,
            "kind": type(exc).__name__,
            "message": str(exc),
        },
    }
    print(json.dumps(payload, indent=2), file=sys.stdout)
    _log_error("decree", f"{command or 'decree'}: {type(exc).__name__}: {exc}")


def main() -> int:
    """Multi-type document CLI (the `decree` entry point)."""
    parser = argparse.ArgumentParser(
        prog="decree",
        description="Decree — software decision lifecycle toolkit. "
        "Manage PRDs, ADRs, and SPECs with cross-type references, "
        "`governs:` file ownership, status enforcement, and validation.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Show the installed decree package version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── new ──────────────────────────────────────────────────
    p_new = subparsers.add_parser(
        "new",
        help="Create a new document (PRD, ADR, or SPEC)",
        description="Create a new document from the type's template. "
        "Generates a local TYPE-ULID frontmatter id, slugifies the title, "
        "and stamps today's date. Derived indexes are explicit: run "
        "`decree index regenerate` when you want index.md refreshed.",
    )
    p_new.add_argument(
        "doc_type",
        help="Document type: adr, prd, spec (must be configured in decree.toml)",
    )
    p_new.add_argument(
        "title",
        help='Document title (e.g. "Use Redis for caching")',
    )
    p_new.add_argument(
        "--bucket",
        required=True,
        default=None,
        metavar="PATH",
        help="Required: write the document under a non-root navigation bucket, e.g. delivery/api.",
    )
    new_sprint_dest = p_new.add_mutually_exclusive_group()
    new_sprint_dest.add_argument(
        "--backlog",
        action="store_true",
        help="When sprint mode is enabled, put a new SPEC in backlog instead of the active sprint.",
    )
    new_sprint_dest.add_argument(
        "--draft-pool",
        action="store_true",
        dest="draft_pool",
        help="When sprint mode is enabled, put a new SPEC in the draft pool instead of the active sprint.",
    )
    p_new.add_argument(
        "--reason",
        default=None,
        help="Required with --backlog or --draft-pool; explains why the SPEC is not in the active sprint.",
    )

    # ── list ────────────────────────────────────────────────
    p_list = subparsers.add_parser(
        "list",
        help="List documents by configured type or physical bucket",
        description="Read-only corpus browser. Buckets are physical folders under each configured "
        "document type directory; they are navigation only and do not imply references, "
        "sprint membership, supersession, or governance.",
    )
    p_list.add_argument(
        "doc_type",
        nargs="?",
        default=None,
        help="Optional configured document type to list, e.g. prd, adr, or spec.",
    )
    p_list.add_argument("--tree", action="store_true", help="Group output by bucket, then type.")
    p_list.add_argument("--bucket", default=None, metavar="PATH", help="Show only documents in this exact bucket.")
    p_list.add_argument("--status", default=None, metavar="STATUS", help="Show only documents with this status.")
    p_list.add_argument(
        "--with-progress",
        action="store_true",
        help="Include primary checkbox completion counts in human output.",
    )
    p_list.add_argument("--json", action="store_true", help="Emit stable machine-readable document records.")

    # ── generate-html ───────────────────────────────────────
    p_generate_html = subparsers.add_parser(
        "generate-html",
        help="Generate a self-contained HTML board for decree documents and sprints",
        description="Write a read-only, self-contained HTML board from the current decree corpus. "
        "The generated file embeds sprint records, document metadata, buckets, and checkbox progress. "
        "No server or derived index rebuild is performed.",
    )
    p_generate_html.add_argument(
        "-o",
        "--output",
        default="decree-board.html",
        metavar="PATH",
        help="HTML file to write (default: decree-board.html at the project root).",
    )
    p_generate_html.add_argument(
        "--sprint",
        default=None,
        metavar="SPRINT-ID",
        help="Sprint selected by default in the generated board. Defaults to the active sprint.",
    )

    # ── agents ─────────────────────────────────────────────
    p_agents = subparsers.add_parser(
        "agents",
        help="Install or inspect decree skills for Codex and Claude Code",
        description="Install packaged decree portable skills into Codex or Claude Code. "
        "Project scope writes under .codex/skills and .claude/skills. "
        "User scope writes under ~/.codex/skills and ~/.claude/skills. "
        "Existing different files are preserved unless --force is passed.",
    )
    agents_subs = p_agents.add_subparsers(dest="agents_action", required=True)
    p_agents_install = agents_subs.add_parser(
        "install",
        help="Install packaged decree skills for Codex, Claude Code, or both",
    )
    p_agents_install.add_argument(
        "--target",
        choices=("codex", "claude", "all"),
        default="all",
        help="Agent host to install for (default: all).",
    )
    p_agents_install.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="Install into the current project or the current user's home directory (default: project).",
    )
    p_agents_install.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned skill writes without changing files.",
    )
    p_agents_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing different skill files.",
    )
    p_agents_install.add_argument(
        "--hooks",
        action="store_true",
        help="Also install the project-local Claude Code stop hook when target includes Claude.",
    )

    p_agents_status = agents_subs.add_parser(
        "status",
        help="Report whether packaged decree skills are installed",
    )
    p_agents_status.add_argument(
        "--target",
        choices=("codex", "claude", "all"),
        default="all",
        help="Agent host to inspect (default: all).",
    )
    p_agents_status.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="Inspect project-local or user-local skill destinations (default: project).",
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
        help="Document ID (e.g. ADR-01KT22NMRV8ZFMDKV0WNFNGMCJ). Type is auto-detected from prefix.",
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

    # ── sprint ───────────────────────────────────────────────
    p_sprint = subparsers.add_parser(
        "sprint",
        help="Manage sprint-scoped execution tracking",
        description="Manage the sprint directory store at decree/sprints/: state.yaml holds the "
        "lifecycle state, live/<DOC-ID>.yaml holds one file per live membership, and "
        "closed/<SPRINT-ID>.yaml holds one archive per closed sprint. "
        "Sprint mode is disabled until `decree sprint init` creates state.yaml.",
    )
    sprint_subs = p_sprint.add_subparsers(dest="sprint_action", required=True)

    p_sprint_init = sprint_subs.add_parser("init", help="Enable sprint mode and create the first active sprint")
    p_sprint_init.add_argument("name", help='Sprint name, e.g. "Sprint 1"')

    sprint_subs.add_parser("status", help="Show sprint mode state, active sprint, backlog, and draft pool")

    p_sprint_pause = sprint_subs.add_parser(
        "pause",
        help="Pause sprint mode after every active item is completed, dropped, or rolled over",
    )
    p_sprint_pause.add_argument("--reason", required=True, help="Why sprint mode is paused")

    p_sprint_resume = sprint_subs.add_parser("resume", help="Resume sprint mode with a new active sprint")
    p_sprint_resume.add_argument("name", help='New sprint name, e.g. "Sprint 2"')

    p_sprint_add = sprint_subs.add_parser("add", help="Add a document to the active sprint")
    p_sprint_add.add_argument("document", help="Document ID to add")
    p_sprint_add.add_argument("--kind", choices=("execution", "planning"), default=None)

    p_sprint_backlog = sprint_subs.add_parser("backlog", help="Add a document to backlog")
    p_sprint_backlog.add_argument("document", help="Document ID to add")
    p_sprint_backlog.add_argument("--kind", choices=("execution", "planning"), default=None)
    p_sprint_backlog.add_argument("--reason", required=True, help="Why this item is not in the active sprint")

    p_sprint_draft = sprint_subs.add_parser(
        "draft-pool",
        aliases=("draft",),
        help="Add a document to the explicit draft pool",
    )
    p_sprint_draft.add_argument("document", help="Document ID to add")
    p_sprint_draft.add_argument("--kind", choices=("execution", "planning"), default=None)
    p_sprint_draft.add_argument("--reason", required=True, help="Why this item has no sprint commitment")

    p_sprint_complete = sprint_subs.add_parser(
        "complete",
        help="Record a completed outcome for one active sprint item mid-sprint "
        "(requires 100%% primary acceptance criteria)",
        description="Record a completed outcome for one item mid-sprint. The item must be an open "
        "scope=active live item and its primary acceptance criteria must be 100% checked. "
        "The outcome and a progress snapshot are written into that item's own live file only.",
    )
    p_sprint_complete.add_argument("document", help="Document ID to complete")
    p_sprint_complete.add_argument(
        "--commit",
        action="append",
        default=None,
        metavar="SHA",
        help="Evidence commit SHA recorded in the outcome (repeatable).",
    )

    p_sprint_drop = sprint_subs.add_parser(
        "drop",
        help="Record a dropped outcome for one active sprint item mid-sprint",
    )
    p_sprint_drop.add_argument("document", help="Document ID to drop")
    p_sprint_drop.add_argument("--reason", required=True, help="Why this item is dropped from the sprint")

    p_sprint_rollover = sprint_subs.add_parser("rollover", help="Close the active sprint and create its successor")
    p_sprint_rollover.add_argument("name", help='Successor sprint name, e.g. "Sprint 2"')
    p_sprint_rollover.add_argument(
        "--outcomes",
        required=True,
        help=(
            "YAML file mapping each OPEN active sprint document (items completed or dropped mid-sprint "
            "are already resolved) to completed/carried_over/deferred/dropped/superseded."
        ),
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
        "the MCP server, and other query commands. The per-type markdown index.md "
        "tables are regenerated via `decree index regenerate`.",
    )
    index_subs = p_index.add_subparsers(dest="index_action", required=True)

    p_rebuild = index_subs.add_parser(
        "rebuild",
        help="Full rebuild of the SQLite provenance index from frontmatter",
        description="Recreate .decree/index.sqlite from canonical frontmatter IDs, references, "
        "governs entries, acceptance criteria, and valid git trailers. Invalid legacy "
        "git trailers are warned and skipped; they are not silently converted.",
    )
    p_rebuild.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    p_idx_status = index_subs.add_parser(
        "status",
        help="Show schema version, last-rebuilt-at, and row counts",
        description="Inspect the local SQLite provenance index without modifying it. "
        "Use this before query commands when you need to confirm freshness.",
    )
    p_idx_status.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")

    p_verify = index_subs.add_parser(
        "verify",
        help="Compare on-disk frontmatter against the index; report drift",
        description="Validate that .decree/index.sqlite matches the current on-disk corpus. "
        "Reports drift explicitly instead of falling back to stale indexed data.",
    )
    p_verify.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")
    p_verify.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")

    index_subs.add_parser(
        "regenerate",
        help="Regenerate the per-type index.md markdown tables",
        description=(
            "Generate a markdown table listing all documents per type, sorted by status priority, date, and id."
        ),
    )

    # ── graph ────────────────────────────────────────────────
    p_graph = subparsers.add_parser(
        "graph",
        help="Generate Mermaid diagrams (timeline, supersede chain, status distribution)",
        description="Append Mermaid diagram blocks to each type's index.md. "
        "Preserves hand-authored content above the GENERATED marker.",
    )
    p_graph.add_argument(
        "--json",
        action="store_true",
        help="Emit the full graph (documents + reference edges) as JSON to stdout "
        "and write nothing. Stable machine contract for external consumers.",
    )

    # ── progress ─────────────────────────────────────────────
    p_progress = subparsers.add_parser(
        "progress",
        help="Show checkbox completion across all documents",
        description="Scan all documents for markdown checkboxes (- [ ] / - [x]) "
        "and report per-document and overall completion with progress bars. "
        "Use scope flags for parallel work so agents can focus on one document, "
        "one chain, changed documents, or documents governing a path.",
    )
    progress_scope = p_progress.add_mutually_exclusive_group()
    progress_scope.add_argument("--doc", metavar="ID", help="Show progress for one document ID")
    progress_scope.add_argument("--chain", metavar="ID", help="Show progress for the connected document chain")
    progress_scope.add_argument("--governs", metavar="PATH", help="Show docs whose governs entries cover PATH")
    progress_scope.add_argument(
        "--changed",
        action="store_true",
        help="Show docs changed relative to --base (requires --base)",
    )
    progress_scope.add_argument("--sprint", metavar="SPRINT-ID", help="Show progress for one sprint")
    progress_scope.add_argument("--all-sprints", action="store_true", help="Show progress for all sprint items")
    progress_scope.add_argument("--backlog", action="store_true", help="Show progress for backlog items")
    progress_scope.add_argument("--draft-pool", action="store_true", help="Show progress for draft-pool items")
    progress_scope.add_argument(
        "--corpus",
        action="store_true",
        help="Show the whole corpus even when sprint mode is enabled",
    )
    p_progress.add_argument("--base", metavar="REF", help="Git base ref for --changed, e.g. origin/main")
    p_progress.add_argument(
        "--include-context",
        action="store_true",
        help="In sprint scopes, also display referenced PRD/ADR context documents without counting them as tasks.",
    )
    p_progress.add_argument(
        "--json",
        action="store_true",
        help="Emit structured progress (per-doc + aggregate acceptance-criteria counts) "
        "as JSON to stdout. Supports document, chain, sprint, backlog, draft-pool, or corpus scopes; stable "
        "machine contract for external consumers.",
    )

    # ── report (sub-namespace: regenerate) ─────────────────
    p_report = subparsers.add_parser(
        "report",
        help="Completion-report maintenance — regenerate explicit report snapshots",
        description="Maintain generated completion reports. Reports are snapshots "
        "written when a document reaches a terminal-success status; if acceptance "
        "criteria are edited later, regenerate them explicitly. No hidden refresh "
        "happens during lint.",
    )
    report_subs = p_report.add_subparsers(dest="report_action", required=True)
    p_report_regen = report_subs.add_parser(
        "regenerate",
        help="Regenerate completion reports for DOC_ID values or --all terminal-success docs",
        description="Refresh completion report markdown from current frontmatter and "
        "checkbox state. Pass explicit DOC_ID values to update specific reports, "
        "or --all to target every terminal-success document whose report config is "
        "enabled. Use --existing-only to refresh committed snapshots without "
        "creating new report files.",
    )
    p_report_regen.add_argument(
        "doc_ids",
        nargs="*",
        metavar="DOC_ID",
        help="Document IDs to regenerate (e.g. SPEC-01KT22NMS0D19VMD8VPK4D2MNX). Mutually exclusive with --all.",
    )
    p_report_regen.add_argument(
        "--all",
        action="store_true",
        help="Target every terminal-success document (accepted ADRs, implemented PRDs/SPECs, or custom equivalents).",
    )
    p_report_regen.add_argument(
        "--existing-only",
        action="store_true",
        dest="existing_only",
        help="With --all or explicit IDs, skip documents whose resolved report path does not already exist.",
    )
    p_report_regen.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print the reports that would be written; do not modify files.",
    )
    p_report_regen.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    # ── ddd ─────────────────────────────────────────────────
    p_ddd = subparsers.add_parser(
        "ddd",
        help="Decree Driven Development — show current phase and next action",
        description="Run a phase assessment: read the corpus, identify which lifecycle phase "
        "the project is in (ideation / architecture decisions / technical design / planning / "
        "implementation / completion / done), and print the suggested next action. Includes a "
        "governance-drift hint (dead and suggested governance counts; run `decree health` for "
        "detail). Offline, no LLM calls.",
    )
    p_ddd.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")
    p_ddd.add_argument(
        "--quiet", action="store_true", help="Suppress document-chain details; print only phase + next action"
    )
    p_ddd.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")
    ddd_scope = p_ddd.add_mutually_exclusive_group()
    ddd_scope.add_argument("--doc", metavar="ID", help="Assess only one document")
    ddd_scope.add_argument("--chain", metavar="ID", help="Assess the connected document chain")
    ddd_scope.add_argument("--governs", metavar="PATH", help="Assess docs whose governs entries cover PATH")
    ddd_scope.add_argument(
        "--changed",
        action="store_true",
        help="Assess docs changed relative to --base (requires --base)",
    )
    ddd_scope.add_argument("--sprint", metavar="SPRINT-ID", help="Assess one sprint")
    ddd_scope.add_argument("--all-sprints", action="store_true", help="Assess all sprint items")
    ddd_scope.add_argument("--backlog", action="store_true", help="Assess backlog items")
    ddd_scope.add_argument("--draft-pool", action="store_true", help="Assess draft-pool items")
    ddd_scope.add_argument(
        "--corpus",
        action="store_true",
        help="Assess the whole corpus even when sprint mode is enabled",
    )
    p_ddd.add_argument("--base", metavar="REF", help="Git base ref for --changed, e.g. origin/main")

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
    p_why.add_argument(
        "--with-abstention",
        action="store_true",
        dest="with_abstention",
        help="Route through calibrated retrieval; abstain when confidence is below threshold.",
    )
    p_why.add_argument(
        "--target-precision",
        type=float,
        default=None,
        dest="target_precision",
        metavar="P",
        help="Desired precision floor for non-abstain responses (default: read from calibration).",
    )

    # ── refs ────────────────────────────────────────────────
    p_refs = subparsers.add_parser(
        "refs",
        help="Show the reverse graph for a decision (who references it, what it governs, …)",
        description="Query the SQLite provenance index for everything connected to "
        "the given decision id: forward refs, reverse refs, supersedes chain (via networkx), "
        "governed paths, and (post-SPEC-01KT22NMRY8YK9RP4323KX4RQG) implementing commits.",
    )
    p_refs.add_argument("decision_id", help="Decision ID (e.g. SPEC-01KT22NMS0D19VMD8VPK4D2MNX)")
    p_refs.add_argument("--json", action="store_true", help="Emit JSON for programmatic consumers")
    p_refs.add_argument("--project", default=None, help="Operate on the project at this path (default: cwd)")
    p_refs.add_argument(
        "--with-abstention",
        action="store_true",
        dest="with_abstention",
        help="Route through calibrated retrieval; abstain when confidence is below threshold.",
    )
    p_refs.add_argument(
        "--target-precision",
        type=float,
        default=None,
        dest="target_precision",
        metavar="P",
        help="Desired precision floor for non-abstain responses (default: read from calibration).",
    )

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
        "After a successful commit, syncs the `commits` table so `decree refs <SPEC-ID>` "
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
        "query and analysis API as agent-callable tools over stdio: `why`, `refs`, "
        "`stale`, `health`, `intent_check` (with parallel-session "
        "`other_active_files`), `intent_review`, `progress`, and `report`.",
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

    # ── health / stale (SPEC-01KT22NMRYNFYM7EN80WS2HD6F) ───────────────────────────
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
        help="Governance & coherence drift: stale, ungoverned hotspots, dead & suggested governance",
        description="Surface four git-derived coherence signals: (1) STALE decisions whose "
        "governed files churned without the decision being touched; (2) UNGOVERNED HOTSPOTS — "
        "high-churn files no decision governs; (3) DEAD GOVERNANCE — declared `governs:` paths "
        "no trailer-linked commit ever touched (high-precision); and (4) SUGGESTED GOVERNANCE "
        "(advisory) — files a decision's own commits repeat-touch (>=2 commits) but it does not "
        "declare and nobody owns. Exit 1 if stale, ungoverned, or dead-governance findings exist; "
        "suggested governance is advisory and never affects the exit code. Read-only and "
        "deterministic; never feeds `why`. Details: docs/health-signals.md.",
    )
    _add_health_args(p_health)

    p_stale = subparsers.add_parser(
        "stale",
        help="Alias for `decree health` (SPEC-01KT22NMRYNFYM7EN80WS2HD6F)",
        description="Same as `decree health`.",
    )
    _add_health_args(p_stale)

    # ── intent-review (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6) ────────────────────────────
    p_ir = subparsers.add_parser(
        "intent-review",
        help="Diff-aware governance report (SPEC-01KT22NMRYRZQ59EC88VJ5R0N6)",
        description="Take a diff (file, stdin, --diff-base, or auto-detect from git "
        "staged/working-tree) and report which decisions govern the changed paths, "
        "which are stale, which acceptance criteria are unchecked, and structural "
        "conflicts. Exit 0 if clean, 1 if conflicts or stale findings exist.",
    )
    p_ir.add_argument(
        "--diff",
        default=None,
        metavar="PATH",
        help="Unified-diff file path, or `-` to read from stdin.",
    )
    p_ir.add_argument(
        "--diff-base",
        default=None,
        metavar="REF",
        help="Run `git diff <REF>...HEAD` to compute the diff.",
    )
    p_ir.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON for programmatic consumers.",
    )
    p_ir.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )
    p_ir.add_argument(
        "--under",
        default=None,
        metavar="ID",
        help="Active decision id (a governed session's decision). When a changed file is one "
        "this decision's own commits repeat-touch (>=2) but it does not declare, surface an "
        "advisory governs: gap (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5). Needs a structured diff "
        "(--diff/--diff-base); invalid id exits 2.",
    )

    # ── init ─────────────────────────────────────────────────
    p_init = subparsers.add_parser(
        "init",
        help="Scaffold a project: decree.toml, type dirs, a worked example chain, and a built index",
        description="Deterministic, idempotent project scaffolder. Ensures the "
        "target has a canonical decree.toml, the decree/<type>/ directories, a "
        "worked PRD→ADR→SPEC example chain, and a built .decree/index.sqlite — "
        "creating only what is missing, never overwriting, reporting every "
        "action (created / skipped-with-reason / would-create). Safe to re-run. "
        "Use --with-agents to also install project-local Codex/Claude skills. "
        "Exit 0 on success (including a fully-present project), exit 1 on "
        "agent skill conflicts, exit 2 on IO/config error.",
    )
    p_init.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report exactly what it would do; write nothing (no files, no index).",
    )
    p_init.add_argument(
        "--json",
        action="store_true",
        help="Emit the plan/result as a stable JSON machine contract on stdout.",
    )
    p_init.add_argument(
        "--no-examples",
        action="store_true",
        dest="no_examples",
        help="Scaffold config + dirs + index only; do not seed the example chain.",
    )
    p_init.add_argument(
        "--with-agents",
        action="store_true",
        dest="with_agents",
        help="Also install packaged Codex and Claude Code skills under the project; never installs hooks.",
    )
    p_init.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    # ── commit-check (SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J) ─────────────────────────────
    p_cc = subparsers.add_parser(
        "commit-check",
        help="Trailer-coverage gate for in-flight governed changes (SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J)",
        description="Deterministic gate: of the changed paths governed by an "
        "in-flight decision, how many carry a matching "
        "`Implements:/Refs:/Fixes:` trailer? Resolve changed paths from a diff "
        "(--diff / --diff-base) or git staged/working-tree; resolve trailers "
        "from --diff-base (CI mode, squash-safe across REF..HEAD) or --message "
        "(commit-msg hook mode). Reads only the declared layer; no LLM. "
        "Advisory by default (exit 0); --strict or --min-coverage make it "
        "gateable (exit 1 when coverage is below threshold). Exit 2 on config "
        "error or missing trailer source.",
    )
    p_cc.add_argument(
        "--diff-base",
        default=None,
        metavar="REF",
        dest="diff_base",
        help="Compute changed paths via `git diff REF...HEAD` and gather trailers "
        "across REF..HEAD (squash-safe CI mode).",
    )
    p_cc.add_argument(
        "--diff",
        default=None,
        metavar="PATH",
        help="Unified-diff file path, or `-` to read from stdin (paths only; trailers still come from --message).",
    )
    p_cc.add_argument(
        "--message",
        default=None,
        metavar="PATH",
        help="Commit-message file to read trailers from (commit-msg hook mode).",
    )
    p_cc.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any governed change lacks a matching trailer.",
    )
    p_cc.add_argument(
        "--min-coverage",
        type=int,
        default=None,
        dest="min_coverage",
        metavar="N",
        help="Exit 1 if trailer coverage percentage is below N (0-100).",
    )
    p_cc.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON for programmatic consumers.",
    )
    p_cc.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    # ── intent-check (SPEC-01KT22NMS0KTWGNKB36RR7K0JR) ─────────────────────────────
    p_ic = subparsers.add_parser(
        "intent-check",
        help="Pre-PR planning-phase governance report (SPEC-01KT22NMS0KTWGNKB36RR7K0JR)",
        description="Given a plan summary and the files the plan will touch, "
        "report which decisions govern those files, which are stale, which "
        "acceptance criteria are unchecked, and structural conflicts — "
        "*before* any code is written. This is the agent planning guard: use it "
        "before implementation, not after a diff exists. Exit 0 if clean, 1 if "
        "conflicts or stale governance findings, 2 on config error.",
    )
    p_ic.add_argument(
        "--plan",
        required=True,
        metavar="TEXT",
        help="One-sentence to one-paragraph description of the planned change.",
    )
    p_ic.add_argument(
        "--files",
        nargs="+",
        required=True,
        metavar="PATH",
        help="One or more repo-relative paths the plan will touch.",
    )
    p_ic.add_argument(
        "--other-active-files",
        default=None,
        dest="other_active_files",
        metavar="JSON",
        help=(
            "JSON object mapping other active session ids to the paths they plan "
            'to touch, e.g. \'{"session-b": ["src/foo.py"]}\'. Planned files that '
            "overlap a live session surface as live-session conflicts (parity with "
            "the intent_check MCP tool's other_active_files parameter)."
        ),
    )
    p_ic.add_argument(
        "--with-abstention",
        action="store_true",
        dest="with_abstention",
        help="SPEC-01KT22NMS0VWCTYPFPHP8M8V36: route governance lookups through the calibrated method.",
    )
    p_ic.add_argument(
        "--target-precision",
        type=float,
        default=None,
        dest="target_precision",
        metavar="P",
        help="SPEC-01KT22NMS0VWCTYPFPHP8M8V36: desired precision floor for non-abstain responses.",
    )
    p_ic.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON for programmatic consumers.",
    )
    p_ic.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )
    p_ic.add_argument(
        "--under",
        default=None,
        metavar="ID",
        help="Active decision id (a governed session's decision). When a planned file is one "
        "this decision's own commits repeat-touch (>=2) but it does not declare, surface an "
        "advisory governs: gap (SPEC-01KT6TCFMWAV6N8G5DR5QMX1P5). Invalid id exits 2.",
    )

    # ── migrate (sub-namespace: audit-coherence, governs, ids, sprint-ledger) ───
    p_migrate = subparsers.add_parser(
        "migrate",
        help="Corpus migration tooling — dry-run audits, explicit suggestions, ID and sprint-ledger migration",
        description="Migration tooling for the decree corpus. "
        "`audit-coherence` runs coherence gates in dry-run mode against every doc "
        "and reports per-gate violations. "
        "`governs` emits deterministic analysis JSON and applies externally "
        "generated suggestions for the typed `governs:` frontmatter field. "
        "`ids` converts legacy sequential filenames to TYPE-ULID frontmatter IDs. "
        "`sprint-ledger` converts the v1 sprints/ledger.yaml monolith to the v2 directory store.",
    )
    migrate_subs = p_migrate.add_subparsers(dest="migrate_action", required=True)

    p_mig_audit = migrate_subs.add_parser(
        "audit-coherence",
        help="Dry-run coherence-gate impact report (SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR)",
        description="Run SPEC-01KT22NMRYNFYM7EN80WS2HD6F's coherence gates in preview mode (force-enabled "
        "regardless of decree.toml's per-type opt-in) across the entire corpus and "
        "report per-gate violations. Exit 0 if clean, 1 if any findings. Use to "
        "preview the lint-storm before enabling a gate globally.",
    )
    p_mig_audit.add_argument(
        "--gate",
        action="append",
        default=None,
        metavar="GATE",
        help="Limit audit to specific gates (repeatable). Values: "
        "terminal_status_progress, unreferenced_active, status_field_requirements. "
        "Default: all gates.",
    )
    p_mig_audit.add_argument(
        "--fix",
        action="store_true",
        help="Interactive remediation mode (fix/skip/defer/quit per finding). Requires a TTY.",
    )
    p_mig_audit.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON for programmatic consumers.",
    )
    p_mig_audit.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    p_mig_gov = migrate_subs.add_parser(
        "governs",
        help="Analyze missing `governs:` links and apply explicit suggestions",
        description="Adoption helper for an existing decree corpus. Core decree "
        "does not call an LLM here. Use --analyze --json to emit a stable JSON "
        "contract for an external agent/skill, then pass that agent's "
        "decree.governs-suggestions.v1 file to --apply-suggestions. Apply mode "
        "validates schema, document IDs, repo-relative paths, duplicates, and "
        "on-disk existence before writing.",
    )
    gov_mode = p_mig_gov.add_mutually_exclusive_group(required=True)
    gov_mode.add_argument(
        "--analyze",
        action="store_true",
        help="Emit deterministic analysis for external agents. Pair with --json for the full contract.",
    )
    gov_mode.add_argument(
        "--apply-suggestions",
        metavar="FILE",
        help="Read a decree.governs-suggestions.v1 JSON file and preview/apply validated governs edits.",
    )
    p_mig_gov.add_argument(
        "--apply",
        action="store_true",
        help="With --apply-suggestions, write validated governs arrays after confirmation.",
    )
    p_mig_gov.add_argument(
        "--dry-run",
        action="store_true",
        help="With --apply, don't write; report what would change.",
    )
    p_mig_gov.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="ID",
        help="Limit to specific document IDs (repeatable).",
    )
    p_mig_gov.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (CI-suitable).",
    )
    p_mig_gov.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of unified diffs.",
    )
    p_mig_gov.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    p_mig_ids = migrate_subs.add_parser(
        "ids",
        help="Migrate legacy sequential filenames to explicit TYPE-ULID frontmatter IDs",
        description="Convert old numeric filename-derived identities into canonical frontmatter IDs. "
        "Dry-run reports the full old-to-new mapping without modifying files. "
        "Apply rewrites document IDs, structured references, filenames, report snapshots, "
        "and regenerated indexes. Runtime fallback is intentionally not supported.",
    )
    ids_mode = p_mig_ids.add_mutually_exclusive_group(required=True)
    ids_mode.add_argument("--dry-run", action="store_true", help="Print the migration plan without writing files")
    ids_mode.add_argument("--apply", action="store_true", help="Apply the migration")
    p_mig_ids.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    p_mig_sprint = migrate_subs.add_parser(
        "sprint-ledger",
        help="Migrate the v1 sprints/ledger.yaml monolith to the v2 directory store",
        description="Convert decree/sprints/ledger.yaml (schema decree.sprints.v1) into the v2 "
        "directory store: state.yaml plus one live/<DOC-ID>.yaml per live membership and one "
        "closed/<SPRINT-ID>.yaml per closed sprint. Dry-run prints the migration plan without "
        "writing. Apply writes the new files, deletes ledger.yaml, and validates the result.",
    )
    sprint_ledger_mode = p_mig_sprint.add_mutually_exclusive_group(required=True)
    sprint_ledger_mode.add_argument(
        "--dry-run", action="store_true", help="Print the migration plan without writing files"
    )
    sprint_ledger_mode.add_argument("--apply", action="store_true", help="Apply the migration")
    p_mig_sprint.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )

    # ── retrieval-eval (SPEC-01KT22NMRZXE5C42F6Z0ZY559A) ───────────────────────────
    p_eval = subparsers.add_parser(
        "retrieval-eval",
        help="Run labeled-query retrieval evaluation (SPEC-01KT22NMRZXE5C42F6Z0ZY559A)",
        description="Run registered retrieval methods against a YAML query set "
        "and emit a markdown report with Recall@K / MRR / nDCG@10 and 95% "
        "bootstrap confidence intervals. Compares non-baseline methods against "
        "the frozen `keyword-v1` baseline. Uses `ir_measures` for metrics and "
        "`scipy.stats.bootstrap` for CIs.",
    )
    p_eval.add_argument(
        "--queries",
        default=None,
        metavar="PATH",
        help="Path to the YAML query set. Default: eval/queries.yaml",
    )
    p_eval.add_argument(
        "--method",
        action="append",
        default=None,
        metavar="NAME",
        help="Run only these methods (repeatable). Default: all registered.",
    )
    p_eval.add_argument(
        "--baseline",
        default=None,
        metavar="NAME",
        help="Method used as comparison baseline. Default: keyword-v1.",
    )
    p_eval.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Path to write markdown report. Default: docs/evaluation/<YYYY-MM-DD>.md",
    )
    p_eval.add_argument(
        "--json",
        action="store_true",
        help="Also emit machine-readable JSON alongside the markdown report.",
    )
    p_eval.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=1000,
        help="Bootstrap resample count (default 1000).",
    )
    p_eval.add_argument(
        "--k",
        action="append",
        type=int,
        default=None,
        metavar="K",
        help="K value for Recall@K (repeatable). Default: 1, 3, 5, 10.",
    )
    p_eval.add_argument(
        "--freeze",
        action="store_true",
        help="Write the chosen baseline's scores to eval/baselines/<method>.json.",
    )
    p_eval.add_argument(
        "--verbose",
        action="store_true",
        help="Include per-query breakdown in the report.",
    )
    p_eval.add_argument(
        "--project",
        default=None,
        help="Operate on the project at this path (default: cwd).",
    )
    p_eval.add_argument(
        "--calibrate",
        action="store_true",
        help="SPEC-01KT22NMS0VWCTYPFPHP8M8V36: run calibration end-to-end and write eval/calibrations/<method>.json.",
    )
    p_eval.add_argument(
        "--target-precision",
        type=float,
        default=0.9,
        dest="target_precision",
        metavar="P",
        help="SPEC-01KT22NMS0VWCTYPFPHP8M8V36: desired precision among non-abstain answers (default 0.9).",
    )

    args = parser.parse_args()

    def _run(module_name: str, function_name: str = "run"):
        def _runner(a):
            module = importlib.import_module(f"decree.commands.{module_name}")
            return getattr(module, function_name)(a)

        return _runner

    # The `index` command has sub-actions: rebuild, status, verify, regenerate.
    def _index_dispatch(a):
        from decree.commands import index as index_cmd
        from decree.commands import index_db_cli

        action = a.index_action
        if action == "rebuild":
            return index_db_cli.rebuild_run(a)
        if action == "status":
            return index_db_cli.status_run(a)
        if action == "verify":
            return index_db_cli.verify_run(a)
        if action == "regenerate":
            return index_cmd.run(a)
        raise ValueError(f"unknown index action: {action}")

    # The `mcp` command has sub-actions: serve (more may land in future SPECs).
    def _mcp_dispatch(a):
        from decree.commands import mcp_server as mcp_cmd

        action = a.mcp_action
        if action == "serve":
            return mcp_cmd.mcp_serve_run(a)
        raise ValueError(f"unknown mcp action: {action}")

    # The `migrate` command has sub-actions: audit-coherence (SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR),
    # governs (SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S), ids, sprint-ledger (SPEC-01KWKXHERB56W94SCRZEVMBQMJ);
    # future: backfill-trailers (v2).
    def _migrate_dispatch(a):
        from decree.commands import migrate as migrate_cmd

        action = a.migrate_action
        if action == "audit-coherence":
            return migrate_cmd.audit_coherence_run(a)
        if action == "governs":
            return migrate_cmd.governs_run(a)
        if action == "ids":
            return migrate_cmd.migrate_ids_run(a)
        if action == "sprint-ledger":
            return migrate_cmd.migrate_sprint_ledger_run(a)
        raise ValueError(f"unknown migrate action: {action}")

    def _report_dispatch(a):
        from decree.commands import report as report_cmd

        action = a.report_action
        if action == "regenerate":
            return report_cmd.regenerate_run(a)
        raise ValueError(f"unknown report action: {action}")

    commands = {
        "new": _run("new"),
        "init": _run("init"),
        "status": _run("status"),
        "list": _run("list_docs"),
        "generate-html": _run("generate_html"),
        "agents": _run("agents"),
        "sprint": _run("sprint"),
        "lint": _run("lint"),
        "index": _index_dispatch,
        "graph": _run("graph"),
        "progress": _run("progress"),
        "report": _report_dispatch,
        "ddd": _run("ddd"),
        "find-root": _run("ddd", "find_root_run"),
        "hook": _run("hook"),
        "why": _run("queries", "why_run"),
        "refs": _run("queries", "refs_run"),
        "commit": _run("commit", "commit_run"),
        "mcp": _mcp_dispatch,
        "health": _run("health", "health_run"),
        "stale": _run("health", "stale_run"),
        "intent-review": _run("intent_review", "intent_review_run"),
        "intent-check": _run("intent_check", "intent_check_run"),
        "commit-check": _run("commit_check", "commit_check_run"),
        "migrate": _migrate_dispatch,
        "retrieval-eval": _run("eval", "eval_run"),
    }
    try:
        return commands[args.command](args)
    except Exception as exc:
        # An unhandled error must never reach a --json consumer as a raw Python
        # traceback. Emit the stable decree.error.v1 contract instead; outside
        # --json mode the error surfaces normally (the human/dev path, with its
        # traceback, is unchanged). See docs/json-contracts.md.
        if getattr(args, "json", False):
            _emit_json_error(args, exc)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
